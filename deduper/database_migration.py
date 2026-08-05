from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .database import Database


DATABASE_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class MigrationReport:
    previous_version: int
    current_version: int
    recovered_interrupted_scan: bool
    integrity_ok: bool
    foreign_key_violations: int


def _meta_int(connection: sqlite3.Connection, key: str, default: int = 0) -> int:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return default


def _set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def migrate_and_recover(database: Database) -> MigrationReport:
    """Upgrade an existing deduper DB without discarding user work.

    Migrations are additive and transactional. Existing assets, hashes, pair
    decisions, deletion queues, deletion history, and cleanup queues are never
    cleared here. A process that died while matching is converted to an explicit
    resumable state; destructive controls remain separately session-locked until
    a current-inventory scan succeeds.
    """
    with database._lock:
        connection = database.connection
        previous = _meta_int(connection, "database_schema_version", 0)
        recovered = False

        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS migration_log (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    description TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS deletion_queue_pair_idx
                    ON deletion_queue(pair_id);
                CREATE INDEX IF NOT EXISTS sha_deletion_queue_survivor_idx
                    ON sha_deletion_queue(survivor_key);
                CREATE INDEX IF NOT EXISTS assets_live_hash_idx
                    ON assets(deleted, sha256);
                """
            )

            state_row = connection.execute(
                "SELECT value FROM meta WHERE key = 'matching_state'"
            ).fetchone()
            state = str(state_row["value"]) if state_row else ""
            if state in {"running", "exact", "phash", "pdq", "images"}:
                _set_meta(connection, "matching_state", "interrupted")
                _set_meta(connection, "recovery_required", "1")
                recovered = True

            migrations = {
                1: "Record explicit database schema version",
                2: "Add queue and live-hash indexes",
                3: "Mark interrupted matching as safely resumable",
            }
            for version in range(previous + 1, DATABASE_SCHEMA_VERSION + 1):
                connection.execute(
                    "INSERT OR IGNORE INTO migration_log (version, description) VALUES (?, ?)",
                    (version, migrations[version]),
                )
            _set_meta(connection, "database_schema_version", str(DATABASE_SCHEMA_VERSION))

        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity_ok = bool(integrity_row and str(integrity_row[0]).lower() == "ok")
        foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        if not integrity_ok or foreign_key_violations:
            raise RuntimeError(
                "Deduper database failed startup validation: "
                f"integrity_ok={integrity_ok}, foreign_key_violations={foreign_key_violations}"
            )

    return MigrationReport(
        previous_version=previous,
        current_version=DATABASE_SCHEMA_VERSION,
        recovered_interrupted_scan=recovered,
        integrity_ok=integrity_ok,
        foreign_key_violations=foreign_key_violations,
    )
