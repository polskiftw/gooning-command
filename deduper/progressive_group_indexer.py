from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .band_scanner import scan_index_band
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


def run_progressive_group_index(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    *,
    compare_workers: int = 1,
    cancelled: Callable[[], bool] | None = None,
    band_progress: BandProgress | None = None,
    group_progress: GroupProgress | None = None,
) -> list[ProgressiveGroupBandResult]:
    """Index strict-to-loose without consulting the UI slider.

    For each unfinished effective matcher band, discover the complete candidate
    edge set, qualify those edges at the band's strictest slider, then close and
    certify connected groups one at a time. The whole-band completion boundary
    advances only after both discovery and group scheduling finish successfully.
    """
    materialized = [asset for asset in assets if not asset.deleted]
    is_cancelled = cancelled or (lambda: False)
    results: list[ProgressiveGroupBandResult] = []

    evidence.set_state("build_status", "building")
    evidence.set_state("scan_mode", "progressive_group_bands")

    for band in pending_bands(evidence):
        if is_cancelled():
            raise IndexingCancelled()

        evidence.set_state("active_band_strictest", str(band.strictest_slider))
        evidence.set_state("active_band_loosest", str(band.loosest_slider))
        evidence.set_state("active_band_status", "discovering_seeds")

        edges = scan_index_band(
            materialized,
            band,
            is_cancelled,
            compare_workers=max(1, int(compare_workers)),
        )
        if is_cancelled():
            evidence.set_state("active_band_status", "cancelled")
            raise IndexingCancelled()

        evidence.set_state("active_band_status", "saving_seeds")
        discovered = evidence.upsert_edges(edges)
        mark_edges_qualified(evidence, edges, band.strictest_slider)

        def on_group(result: FrontierResult, seed_count: int) -> None:
            if group_progress is not None:
                group_progress(band, result, seed_count)

        evidence.set_state("active_band_status", "closing_groups")
        try:
            group_result = run_group_seed_schedule(
                evidence,
                materialized,
                band.loosest_slider,
                cancelled=is_cancelled,
                progress=on_group,
            )
        except FrontierCancelled as exc:
            evidence.set_state("active_band_status", "cancelled")
            raise IndexingCancelled() from exc

        if is_cancelled():
            evidence.set_state("active_band_status", "cancelled")
            raise IndexingCancelled()

        evidence.mark_range_complete(band.loosest_slider)
        evidence.set_state("active_band_status", "complete")
        result = ProgressiveGroupBandResult(
            band=band,
            discovered_edges=discovered,
            group_result=group_result,
            total_edges=evidence.edge_count(),
        )
        results.append(result)
        if band_progress is not None:
            band_progress(result)

    if evidence.loosest_complete_slider() == 0:
        evidence.set_state("build_status", "complete")
        evidence.set_state("active_band_status", "idle")
    return results
