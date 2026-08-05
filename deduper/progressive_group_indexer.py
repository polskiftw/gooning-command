from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .band_scanner import stream_index_band_stages
from .evidence_qualification import mark_edges_qualified
from .evidence_store import EvidenceStore
from .frontier_worker import FrontierCancelled, FrontierResult
from .group_scheduler import GroupScheduleResult, run_group_seed_schedule
from .models import Asset
from .progressive_indexer import IndexBand, IndexingCancelled, pending_bands


@dataclass(frozen=True)
class ProgressiveGroupBandResult:
    band: IndexBand
    discovered_edges: int
    group_result: GroupScheduleResult
    total_edges: int


BandProgress = Callable[[ProgressiveGroupBandResult], None]
GroupProgress = Callable[[IndexBand, FrontierResult, int], None]
StageProgress = Callable[[IndexBand, str, int], None]


def _empty_group_result(slider: int) -> GroupScheduleResult:
    return GroupScheduleResult(
        slider=slider,
        groups_completed=0,
        assets_completed=0,
        comparisons=0,
        edges_written=0,
    )


def _add_group_results(
    left: GroupScheduleResult,
    right: GroupScheduleResult,
) -> GroupScheduleResult:
    return GroupScheduleResult(
        slider=left.slider,
        groups_completed=left.groups_completed + right.groups_completed,
        assets_completed=left.assets_completed + right.assets_completed,
        comparisons=left.comparisons + right.comparisons,
        edges_written=left.edges_written + right.edges_written,
    )


def run_progressive_group_index(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    *,
    compare_workers: int = 1,
    cancelled: Callable[[], bool] | None = None,
    band_progress: BandProgress | None = None,
    group_progress: GroupProgress | None = None,
    stage_progress: StageProgress | None = None,
) -> list[ProgressiveGroupBandResult]:
    """Index strict-to-loose and close groups as seed stages become available.

    The controller never consults UI slider state. For each unfinished effective
    threshold band, every completed matcher stage is committed as seed evidence
    and immediately fed to the closure scheduler. READY groups can therefore be
    published before the band-wide matcher reaches its final stage. The band's
    completion boundary advances only after the authoritative ``complete`` stage
    and all group scheduling for it finish successfully.
    """
    materialized = [asset for asset in assets if not asset.deleted]
    is_cancelled = cancelled or (lambda: False)
    results: list[ProgressiveGroupBandResult] = []

    evidence.set_state("build_status", "building")
    evidence.set_state("scan_mode", "streaming_progressive_group_bands")

    for band in pending_bands(evidence):
        if is_cancelled():
            raise IndexingCancelled()

        evidence.set_state("active_band_strictest", str(band.strictest_slider))
        evidence.set_state("active_band_loosest", str(band.loosest_slider))
        evidence.set_state("active_band_status", "discovering_and_closing")

        discovered = 0
        aggregate = _empty_group_result(band.loosest_slider)
        saw_complete = False

        try:
            for stage in stream_index_band_stages(
                materialized,
                band,
                is_cancelled,
                compare_workers=max(1, int(compare_workers)),
            ):
                if is_cancelled():
                    raise IndexingCancelled()

                evidence.set_state("active_band_stage", stage.name)
                evidence.set_state("active_band_status", "saving_stage_seeds")
                discovered += evidence.upsert_edges(stage.edges)
                mark_edges_qualified(evidence, stage.edges, band.strictest_slider)

                def on_group(result: FrontierResult, seed_count: int) -> None:
                    if group_progress is not None:
                        group_progress(band, result, seed_count)

                evidence.set_state("active_band_status", "closing_stage_groups")
                stage_groups = run_group_seed_schedule(
                    evidence,
                    materialized,
                    band.loosest_slider,
                    cancelled=is_cancelled,
                    progress=on_group,
                )
                aggregate = _add_group_results(aggregate, stage_groups)
                if stage_progress is not None:
                    stage_progress(band, stage.name, len(stage.edges))
                if stage.complete:
                    saw_complete = True
        except FrontierCancelled as exc:
            evidence.set_state("active_band_status", "cancelled")
            raise IndexingCancelled() from exc

        if is_cancelled():
            evidence.set_state("active_band_status", "cancelled")
            raise IndexingCancelled()
        if not saw_complete:
            evidence.set_state("active_band_status", "failed_no_complete_stage")
            raise RuntimeError("matcher ended without a complete band stage")

        evidence.mark_range_complete(band.loosest_slider)
        evidence.set_state("active_band_status", "complete")
        result = ProgressiveGroupBandResult(
            band=band,
            discovered_edges=discovered,
            group_result=aggregate,
            total_edges=evidence.edge_count(),
        )
        results.append(result)
        if band_progress is not None:
            band_progress(result)

    if evidence.loosest_complete_slider() == 0:
        evidence.set_state("build_status", "complete")
        evidence.set_state("active_band_status", "idle")
    return results
