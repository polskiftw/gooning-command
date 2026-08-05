from __future__ import annotations

from collections.abc import Callable

from .evidence_capture import evidence_for_pairs
from .evidence_store import EvidenceEdge
from .matcher import MatchingCancelled, acquire_pair_stages
from .models import Asset
from .progressive_indexer import IndexBand, IndexingCancelled


def scan_index_band(
    assets: list[Asset],
    band: IndexBand,
    cancelled: Callable[[], bool],
    *,
    compare_workers: int = 1,
) -> list[EvidenceEdge]:
    """Return the complete qualifying evidence set for one index band.

    The band's loosest slider position is authoritative because every stricter
    position represented by the same band has identical effective matcher
    thresholds. The legacy preview database is not touched.
    """
    if cancelled():
        raise IndexingCancelled()

    final_pairs: list[tuple[str, str, float, str]] = []
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
            if stage == "complete":
                final_pairs = pairs
    except MatchingCancelled as exc:
        raise IndexingCancelled() from exc

    if cancelled():
        raise IndexingCancelled()
    return evidence_for_pairs(assets, final_pairs, band.loosest_slider)


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
