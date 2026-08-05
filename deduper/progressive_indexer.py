from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from .evidence_store import EvidenceEdge, EvidenceStore
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
    """Collapse the 100 slider positions into distinct matcher configurations.

    Positions are traversed strict-to-loose (99 down to 0). Adjacent positions
    with identical effective thresholds share one band and are completed by one
    matcher pass.
    """
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
    """Build durable evidence strict-to-loose with transactional checkpoints.

    ``scan_band`` must return the complete evidence set discoverable for that
    band's matcher configuration. Evidence rows may be upserted repeatedly, but
    the slider boundary moves only after the entire returned set commits.
    Therefore an interrupted band is never advertised as READY.
    """
    materialized_assets = list(assets)
    is_cancelled = cancelled or (lambda: False)
    results: list[BandResult] = []

    evidence.set_state("build_status", "building")
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
        if is_cancelled():
            # Rows are safe observations, but this band is not certified. Do not
            # advance the completion boundary after a cancellation.
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
