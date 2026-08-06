from __future__ import annotations

from collections.abc import Iterable
from .models import Pair


def pair_identity(left_key: str, right_key: str) -> tuple[str, str]:
    """Return an orientation-independent identity for one review pair."""
    return tuple(sorted((left_key, right_key)))


def preserved_pair_index(
    pairs: Iterable[Pair],
    left_key: str | None,
    right_key: str | None,
    fallback_index: int,
) -> int:
    """Keep the visible pair stable across disposable pair-table rebuilds.

    Exact orientation wins so the survivor/delete sides do not unexpectedly swap.
    If only a reoriented row exists, keep that logical pair rather than jumping to
    unrelated work. Otherwise clamp the old numeric position into the new list.
    """
    materialized = list(pairs)
    if not materialized:
        return 0
    if left_key is not None and right_key is not None:
        for index, pair in enumerate(materialized):
            if pair.left_key == left_key and pair.right_key == right_key:
                return index
        wanted = pair_identity(left_key, right_key)
        for index, pair in enumerate(materialized):
            if pair_identity(pair.left_key, pair.right_key) == wanted:
                return index
    return min(max(0, int(fallback_index)), len(materialized) - 1)

