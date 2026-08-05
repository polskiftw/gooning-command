from __future__ import annotations

from collections.abc import Iterable
from types import MethodType

from .database import Database


DECISION_SCHEMA = """
CREATE TABLE IF NOT EXISTS ready_pair_decisions (
    first_key TEXT NOT NULL,
    second_key TEXT NOT NULL,
    decision TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (first_key, second_key),
    CHECK (first_key < second_key)
);
"""


def normalized_pair(left_key: str, right_key: str) -> tuple[str, str]:
    if left_key == right_key:
        raise ValueError("a READY decision requires two different assets")
    first, second = sorted((left_key, right_key))
    return first, second


def ensure_ready_decisions(database: Database) -> None:
    with database._lock, database.connection:
        database.connection.executescript(DECISION_SCHEMA)


def remember_exclusion(database: Database, left_key: str, right_key: str) -> None:
    first, second = normalized_pair(left_key, right_key)
    with database._lock, database.connection:
        database.connection.execute(
            """
            INSERT INTO ready_pair_decisions (first_key, second_key, decision)
            VALUES (?, ?, 'exclude')
            ON CONFLICT(first_key, second_key) DO UPDATE SET
                decision = excluded.decision,
                updated_at = CURRENT_TIMESTAMP
            """,
            (first, second),
        )


def apply_ready_decisions(database: Database) -> int:
    """Reapply durable exclusions after disposable pair rows are rebuilt."""
    with database._lock, database.connection:
        excluded_rows = database.connection.execute(
            """
            SELECT p.id
            FROM pairs p
            JOIN ready_pair_decisions d
              ON d.first_key = MIN(p.left_key, p.right_key)
             AND d.second_key = MAX(p.left_key, p.right_key)
            WHERE d.decision = 'exclude'
            """
        ).fetchall()
        pair_ids = [int(row["id"]) for row in excluded_rows]
        if not pair_ids:
            return 0
        database.connection.executemany(
            """
            UPDATE pairs
            SET status = 'excluded', decision = 'exclude', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            ((pair_id,) for pair_id in pair_ids),
        )
        database.connection.executemany(
            "DELETE FROM deletion_queue WHERE pair_id = ?",
            ((pair_id,) for pair_id in pair_ids),
        )
        return len(pair_ids)


def purge_asset_decisions(database: Database, keys: Iterable[str]) -> int:
    materialized = sorted(set(keys))
    if not materialized:
        return 0
    with database._lock, database.connection:
        placeholders = ",".join("?" for _ in materialized)
        cursor = database.connection.execute(
            f"""
            DELETE FROM ready_pair_decisions
            WHERE first_key IN ({placeholders}) OR second_key IN ({placeholders})
            """,
            tuple(materialized) + tuple(materialized),
        )
        return int(cursor.rowcount)


def install_ready_lifecycle(database: Database) -> None:
    """Make READY decisions survive pair-row replacement and purge on deletion.

    Pair rows and ids are intentionally disposable. These hooks preserve the
    user's normalized pair decision independently, then reapply it after every
    legacy or certified rebuild. Installation is idempotent per Database object.
    """
    if getattr(database, "_ready_lifecycle_installed", False):
        return
    ensure_ready_decisions(database)

    original_replace_pairs = database.replace_pairs
    original_exclude_pair_keys = database.exclude_pair_keys
    original_record_deletions = database.record_deletions
    original_record_reverse_deletion = database.record_reverse_deletion

    def replace_pairs(self, pairs, *, preserve_exclusions=False):
        count = original_replace_pairs(pairs, preserve_exclusions=preserve_exclusions)
        apply_ready_decisions(self)
        return count

    def exclude_pair_keys(self, left_key: str, right_key: str) -> bool:
        excluded = original_exclude_pair_keys(left_key, right_key)
        if excluded:
            remember_exclusion(self, left_key, right_key)
        return excluded

    def record_deletions(self, results) -> None:
        materialized = list(results)
        original_record_deletions(materialized)
        purge_asset_decisions(
            self,
            (key for key, _pair_id, _size, result in materialized if result == "deleted"),
        )

    def record_reverse_deletion(
        self,
        left_key: str,
        right_key: str,
        size: int,
        result: str,
    ) -> None:
        original_record_reverse_deletion(left_key, right_key, size, result)
        if result == "deleted":
            purge_asset_decisions(self, (left_key,))

    database.replace_pairs = MethodType(replace_pairs, database)
    database.exclude_pair_keys = MethodType(exclude_pair_keys, database)
    database.record_deletions = MethodType(record_deletions, database)
    database.record_reverse_deletion = MethodType(record_reverse_deletion, database)
    database._ready_lifecycle_installed = True
