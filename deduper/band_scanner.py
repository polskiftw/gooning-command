from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .evidence_capture import evidence_for_pairs
from .evidence_store import EvidenceEdge
from .matcher import MatchingCancelled, acquire_pair_stages
from .models import Asset
from .progressive_indexer import IndexBand, IndexingCancelled


@dataclass(frozen=True)
class BandSeedStage:
    """One completed matcher stage that can safely supply frontier seeds.

    Stage edges are qualifying relationships, but they are not closure proof.
    The frontier worker must still exhaust every member before publishing READY.
    ``complete`` identifies the matcher's authoritative final band result.
    """

    name: str
    edges: tuple[EvidenceEdge, ...]
    complete: bool


def stream_index_band_stages(
    assets: list[Asset],
    band: IndexBand,
    cancelled: Callable[[], bool],
    *,
    compare_workers: int = 1,
) -> Iterator[BandSeedStage]:
    """Yield completed candidate stages while one band is still discovering.

    This allows strict-to-loose group closure to begin as soon as the matcher
    exposes its first qualifying relationships. The whole band is not considered
    complete until the final ``complete`` stage has been yielded and committed.
    """
    if cancelled():
        raise IndexingCancelled()

    try:
        for stage, pairs in acquire_pair_stages(
            assets,
            band.loosest_slider,
            progress=None,
            cancelled=cancelled,
            include_exact=False,
            compare_workers=max(1, int(compare_workers)),
        ):
            if cancelled():
                raise IndexingCancelled()
            edges = tuple(evidence_for_pairs(assets, pairs, band.loosest_slider))
            yield BandSeedStage(stage, edges, stage == "complete")
    except MatchingCancelled as exc:
        raise IndexingCancelled() from exc


def scan_index_band(
    assets: list[Asset],
    band: IndexBand,
    cancelled: Callable[[], bool],
    *,
    compare_workers: int = 1,
) -> list[EvidenceEdge]:
    """Return the complete qualifying evidence set for one index band."""
    final_edges: tuple[EvidenceEdge, ...] = ()
    saw_complete = False
    for stage in stream_index_band_stages(
        assets,
        band,
        cancelled,
        compare_workers=compare_workers,
    ):
        if stage.complete:
            final_edges = stage.edges
            saw_complete = True
    if cancelled():
        raise IndexingCancelled()
    if not saw_complete:
        raise RuntimeError("matcher ended without a complete band stage")
    return list(final_edges)


def make_band_scanner(compare_workers: int) -> Callable[
    [list[Asset], IndexBand, Callable[[], bool]],
    list[EvidenceEdge],
]:
    """Bind the configured worker count for ``run_progressive_index``."""

    workers = max(1, int(compare_workers))

    def scanner(
        assets: list[Asset],
        band: IndexBand,
        cancelled: Callable[[], bool],
    ) -> list[EvidenceEdge]:
        return scan_index_band(
            assets,
            band,
            cancelled,
            compare_workers=workers,
        )

    return scanner
