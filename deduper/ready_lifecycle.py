from __future__ import annotations

from collections.abc import Iterable

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
    return tuple(sorted((left_key, right_key)))  # type: ignore[return-value]


def ensure_ready_decisions(database: Database) -> None:
    with database._lock, database.connection:  # same transactional lock as Database
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
    """Reapply durable exclusions after disposable READY pair rows are rebuilt."""
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


def replace_ready_pairs(
    database: Database,
    pairs: Iterable[tuple[str, str, float, str]],
) -> int:
    count = database.replace_pairs(pairs, preserve_exclusions=False)
    apply_ready_decisions(database)
    return count


def purge_asset_decisions(database: Database, keys: Iterable[str]) -> int:
    materialized = set(keys)
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
