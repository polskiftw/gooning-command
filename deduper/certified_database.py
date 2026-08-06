from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .database import Database
from .ready_lifecycle import (
    apply_ready_decisions,
    ensure_ready_decisions,
    purge_asset_decisions,
    remember_exclusion,
)


class CertifiedDatabase(Database):
    """Production database with durable certified-review decisions built in."""

    def __init__(self, path: Path):
        super().__init__(path)
        ensure_ready_decisions(self)

    def replace_pairs(self, pairs, *, preserve_exclusions: bool = False) -> int:
        count = super().replace_pairs(
            pairs,
            preserve_exclusions=preserve_exclusions,
        )
        apply_ready_decisions(self)
        return count

    def exclude_pair_permanently(self, left_key: str, right_key: str) -> bool:
        excluded = super().exclude_pair_keys(left_key, right_key)
        if excluded:
            remember_exclusion(self, left_key, right_key)
        return excluded

    def record_deletions(
        self,
        results: Iterable[tuple[str, int | None, int, str]],
    ) -> None:
        materialized = list(results)
        super().record_deletions(materialized)
        purge_asset_decisions(
            self,
            (
                key
                for key, _pair_id, _size, result in materialized
                if result == "deleted"
            ),
        )

    def record_reverse_deletion(
        self,
        left_key: str,
        right_key: str,
        size: int,
        result: str,
    ) -> None:
        super().record_reverse_deletion(left_key, right_key, size, result)
        if result == "deleted":
            purge_asset_decisions(self, (left_key,))
