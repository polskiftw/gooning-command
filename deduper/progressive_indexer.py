from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from .evidence_qualification import mark_edges_qualified
from .evidence_store import EvidenceEdge, EvidenceStore
from .frontier_worker import FrontierCancelled
from .group_scheduler import run_group_seed_schedule
from .matcher import thresholds
from .models import Asset


@dataclass(frozen=True)
class IndexBand:
    """One complete matcher-parameter band shared by one or more slider positions."""

    strictest_slider: int
    loosest_slider: int
    signature: tuple[tuple[str, float | int], ...]


@dataclass(frozen=True)
class BandResult:
    band: IndexBand
    edges_written: int
    total_edges: int


BandScanner = Callable[
    [list[Asset], IndexBand, Callable[[], bool]],
    Iterable[EvidenceEdge],
]
ProgressCallback = Callable[[BandResult], None]


class IndexingCancelled(Exception):
    """Raised without advancing the completion boundary for the active band."""


def _signature(slider: int) -> tuple[tuple[str, float | int], ...]:
    values = thresholds(slider)
    return tuple(sorted(values.items()))


def index_bands() -> list[IndexBand]:
    """Collapse the 100 slider positions into distinct matcher configurations."""
    bands: list[IndexBand] = []
    current_signature: tuple[tuple[str, float | int], ...] | None = None
    strictest = loosest = 99

    for slider in range(99, -1, -1):
        signature = _signature(slider)
        if current_signature is None:
            current_signature = signature
            strictest = loosest = slider
            continue
        if signature == current_signature:
            loosest = slider
            continue
        bands.append(IndexBand(strictest, loosest, current_signature))
        current_signature = signature
        strictest = loosest = slider

    assert current_signature is not None
    bands.append(IndexBand(strictest, loosest, current_signature))
    return bands


def pending_bands(evidence: EvidenceStore) -> Iterator[IndexBand]:
    """Yield only bands looser than the last completely committed boundary."""
    completed = evidence.loosest_complete_slider()
    for band in index_bands():
        if completed is not None and band.loosest_slider >= completed:
            continue
        yield band


def run_progressive_index(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    scan_band: BandScanner,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: ProgressCallback | None = None,
) -> list[BandResult]:
    """Publish closed groups first, then complete strict-to-loose band coverage.

    Matcher-proven seed edges from the selected live slider are processed one
    connected component at a time. Each component becomes READY as soon as all
    member frontiers are exhausted. The slower whole-library band pass then
    continues as a completeness backstop and advances the slider boundary only
    after a complete band commits.
    """
    materialized_assets = list(assets)
    is_cancelled = cancelled or (lambda: False)
    results: list[BandResult] = []

    evidence.set_state("build_status", "building")
    observed_slider = evidence.get_state("last_observed_slider")
    if observed_slider is not None:
        try:
            run_group_seed_schedule(
                evidence,
                materialized_assets,
                int(observed_slider),
                cancelled=is_cancelled,
            )
        except FrontierCancelled as exc:
            raise IndexingCancelled() from exc

    for band in pending_bands(evidence):
        if is_cancelled():
            raise IndexingCancelled()

        evidence.set_state("active_band_strictest", str(band.strictest_slider))
        evidence.set_state("active_band_loosest", str(band.loosest_slider))
        evidence.set_state("active_band_status", "scanning")

        edges = list(scan_band(materialized_assets, band, is_cancelled))
        if is_cancelled():
            evidence.set_state("active_band_status", "cancelled")
            raise IndexingCancelled()

        evidence.set_state("active_band_status", "committing")
        written = evidence.upsert_edges(edges)
        mark_edges_qualified(evidence, edges, band.strictest_slider)
        if is_cancelled():
            evidence.set_state("active_band_status", "cancelled_after_commit")
            raise IndexingCancelled()

        evidence.mark_range_complete(band.loosest_slider)
        evidence.set_state("active_band_status", "complete")
        result = BandResult(band, written, evidence.edge_count())
        results.append(result)
        if progress is not None:
            progress(result)

    if evidence.loosest_complete_slider() == 0:
        evidence.set_state("build_status", "complete")
        evidence.set_state("active_band_status", "idle")
    return results
