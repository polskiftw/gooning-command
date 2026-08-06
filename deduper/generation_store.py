from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Iterable


GENERATION_SCHEMA_VERSION = 1

GENERATION_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS certified_generations (
    generation_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (
        state IN ('staging', 'certified', 'retired', 'failed', 'legacy_view_only')
    ),
    inventory_fingerprint TEXT,
    inventory_object_count INTEGER,
    slider_value INTEGER,
    matcher_version TEXT,
    hash_version TEXT,
    workflow_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    promoted_at TEXT,
    saved_queue_position INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_staging_generation
ON certified_generations(state)
WHERE state = 'staging';

CREATE TABLE IF NOT EXISTS generation_pairs (
    generation_id TEXT NOT NULL REFERENCES certified_generations(generation_id)
        ON DELETE CASCADE,
    queue_position INTEGER NOT NULL,
    group_id TEXT NOT NULL,
    survivor_key TEXT NOT NULL REFERENCES assets(key),
    deletion_key TEXT NOT NULL REFERENCES assets(key),
    similarity REAL NOT NULL,
    reason TEXT NOT NULL,
    included INTEGER NOT NULL DEFAULT 1 CHECK (included IN (0, 1)),
    excluded INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0, 1)),
    PRIMARY KEY (generation_id, queue_position),
    UNIQUE (generation_id, deletion_key),
    UNIQUE (generation_id, survivor_key, deletion_key),
    CHECK (survivor_key <> deletion_key),
    CHECK (NOT (included = 1 AND excluded = 1))
);

CREATE INDEX IF NOT EXISTS generation_pairs_group_idx
ON generation_pairs(generation_id, group_id, queue_position);

CREATE TABLE IF NOT EXISTS generation_sha_deletions (
    generation_id TEXT NOT NULL REFERENCES certified_generations(generation_id)
        ON DELETE CASCADE,
    deletion_key TEXT NOT NULL REFERENCES assets(key),
    survivor_key TEXT NOT NULL REFERENCES assets(key),
    queue_position INTEGER NOT NULL,
    PRIMARY KEY (generation_id, deletion_key),
    UNIQUE (generation_id, queue_position),
    CHECK (survivor_key <> deletion_key)
);

CREATE TABLE IF NOT EXISTS generation_review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id TEXT NOT NULL REFERENCES certified_generations(generation_id)
        ON DELETE CASCADE,
    survivor_key TEXT NOT NULL,
    deletion_key TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS family_recertification_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_generation_id TEXT NOT NULL REFERENCES certified_generations(generation_id),
    group_id TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'queued' CHECK (
        state IN ('queued', 'running', 'complete', 'failed', 'cancelled')
    ),
    member_keys_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS family_recertification_priority_idx
ON family_recertification_jobs(state, priority DESC, id);

CREATE TABLE IF NOT EXISTS active_certified_generation (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation_id TEXT REFERENCES certified_generations(generation_id)
);

CREATE TABLE IF NOT EXISTS generation_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class GenerationIdentity:
    inventory_fingerprint: str
    inventory_object_count: int
    slider_value: int
    matcher_version: str
    hash_version: str
    workflow_version: str


@dataclass(frozen=True)
class GenerationRecord:
    generation_id: str
    state: str
    identity: GenerationIdentity | None
    saved_queue_position: int


class GenerationStore:
    """Generation-scoped persistence sharing the existing deduper SQLite database."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self) -> None:
        """Install additive generation tables without clearing legacy data."""
        with self.connection:
            self.connection.executescript(GENERATION_SCHEMA)
            self.connection.execute(
                """
                INSERT INTO generation_schema_meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(GENERATION_SCHEMA_VERSION),),
            )
            self.connection.execute(
                """
                INSERT OR IGNORE INTO active_certified_generation
                    (singleton, generation_id)
                VALUES (1, NULL)
                """
            )

    def register_legacy_view_only(self) -> str | None:
        """Preserve an existing mutable queue as explicitly untrusted legacy data.

        This records only the existence of legacy review material. It deliberately
        does not copy mutable pair rows into certified generation tables and never
        upgrades `matching_state = complete` without a trustworthy identity.
        """
        if not self._table_exists("pairs"):
            return None
        row = self.connection.execute("SELECT COUNT(*) AS count FROM pairs").fetchone()
        if row is None or int(row["count"]) == 0:
            return None
        existing = self.connection.execute(
            """
            SELECT generation_id FROM certified_generations
            WHERE state = 'legacy_view_only'
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        if existing:
            return str(existing["generation_id"])

        generation_id = f"legacy-{uuid.uuid4()}"
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO certified_generations (generation_id, state)
                VALUES (?, 'legacy_view_only')
                """,
                (generation_id,),
            )
        return generation_id

    def create_staging(self, identity: GenerationIdentity) -> str:
        self._validate_identity(identity)
        generation_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute(
                "DELETE FROM certified_generations WHERE state = 'staging'"
            )
            self.connection.execute(
                """
                INSERT INTO certified_generations (
                    generation_id, state, inventory_fingerprint,
                    inventory_object_count, slider_value, matcher_version,
                    hash_version, workflow_version
                ) VALUES (?, 'staging', ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    identity.inventory_fingerprint,
                    identity.inventory_object_count,
                    identity.slider_value,
                    identity.matcher_version,
                    identity.hash_version,
                    identity.workflow_version,
                ),
            )
        return generation_id

    def replace_staging_pairs(
        self,
        generation_id: str,
        pairs: Iterable[tuple[int, str, str, str, float, str]],
    ) -> int:
        self._require_state(generation_id, "staging")
        rows = list(pairs)
        deletion_keys = [row[3] for row in rows]
        if len(deletion_keys) != len(set(deletion_keys)):
            raise ValueError("a deletion candidate may appear only once per generation")
        with self.connection:
            self.connection.execute(
                "DELETE FROM generation_pairs WHERE generation_id = ?",
                (generation_id,),
            )
            self.connection.executemany(
                """
                INSERT INTO generation_pairs (
                    generation_id, queue_position, group_id, survivor_key,
                    deletion_key, similarity, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (generation_id, position, group_id, survivor, deletion, similarity, reason)
                    for position, group_id, survivor, deletion, similarity, reason in rows
                ),
            )
        return len(rows)

    def replace_staging_sha_deletions(
        self,
        generation_id: str,
        deletions: Iterable[tuple[int, str, str]],
    ) -> int:
        self._require_state(generation_id, "staging")
        rows = list(deletions)
        with self.connection:
            self.connection.execute(
                "DELETE FROM generation_sha_deletions WHERE generation_id = ?",
                (generation_id,),
            )
            self.connection.executemany(
                """
                INSERT INTO generation_sha_deletions (
                    generation_id, queue_position, survivor_key, deletion_key
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (generation_id, position, survivor, deletion)
                    for position, survivor, deletion in rows
                ),
            )
        return len(rows)

    def complete_staging(self, generation_id: str) -> None:
        self._require_state(generation_id, "staging")
        with self.connection:
            self.connection.execute(
                """
                UPDATE certified_generations
                SET completed_at = CURRENT_TIMESTAMP
                WHERE generation_id = ?
                """,
                (generation_id,),
            )

    def promote(self, generation_id: str) -> None:
        """Atomically retire the old active generation and promote staging."""
        self._require_state(generation_id, "staging")
        row = self.connection.execute(
            """
            SELECT completed_at FROM certified_generations
            WHERE generation_id = ?
            """,
            (generation_id,),
        ).fetchone()
        if row is None or row["completed_at"] is None:
            raise ValueError("staging generation is incomplete")

        with self.connection:
            active = self.connection.execute(
                """
                SELECT generation_id FROM active_certified_generation
                WHERE singleton = 1
                """
            ).fetchone()
            old_id = active["generation_id"] if active else None
            if old_id and old_id != generation_id:
                self.connection.execute(
                    """
                    UPDATE certified_generations
                    SET state = 'retired'
                    WHERE generation_id = ? AND state = 'certified'
                    """,
                    (old_id,),
                )
            self.connection.execute(
                """
                UPDATE certified_generations
                SET state = 'certified', promoted_at = CURRENT_TIMESTAMP
                WHERE generation_id = ? AND state = 'staging'
                """,
                (generation_id,),
            )
            self.connection.execute(
                """
                UPDATE active_certified_generation
                SET generation_id = ?
                WHERE singleton = 1
                """,
                (generation_id,),
            )

    def fail_staging(self, generation_id: str, reason: str) -> None:
        self._require_state(generation_id, "staging")
        with self.connection:
            self.connection.execute(
                """
                UPDATE certified_generations
                SET state = 'failed', failure_reason = ?
                WHERE generation_id = ?
                """,
                (reason, generation_id),
            )

    def active(self) -> GenerationRecord | None:
        row = self.connection.execute(
            """
            SELECT g.*
            FROM active_certified_generation a
            JOIN certified_generations g ON g.generation_id = a.generation_id
            WHERE a.singleton = 1 AND g.state = 'certified'
            """
        ).fetchone()
        return self._record(row) if row else None

    def set_queue_position(self, generation_id: str, position: int) -> None:
        if position < 0:
            raise ValueError("queue position cannot be negative")
        self._require_state(generation_id, "certified")
        with self.connection:
            self.connection.execute(
                """
                UPDATE certified_generations
                SET saved_queue_position = ?
                WHERE generation_id = ?
                """,
                (position, generation_id),
            )

    def pairs(self, generation_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT * FROM generation_pairs
            WHERE generation_id = ?
            ORDER BY queue_position
            """,
            (generation_id,),
        ).fetchall()

    def sha_deletions(self, generation_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT * FROM generation_sha_deletions
            WHERE generation_id = ?
            ORDER BY queue_position
            """,
            (generation_id,),
        ).fetchall()

    def _require_state(self, generation_id: str, expected: str) -> None:
        row = self.connection.execute(
            "SELECT state FROM certified_generations WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(generation_id)
        if row["state"] != expected:
            raise ValueError(
                f"generation {generation_id} is {row['state']}, expected {expected}"
            )

    def _table_exists(self, table: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _validate_identity(identity: GenerationIdentity) -> None:
        if not identity.inventory_fingerprint:
            raise ValueError("inventory fingerprint is required")
        if identity.inventory_object_count < 0:
            raise ValueError("inventory object count cannot be negative")
        if not 0 <= identity.slider_value <= 99:
            raise ValueError("slider value must be between 0 and 99")
        if not identity.matcher_version:
            raise ValueError("matcher version is required")
        if not identity.hash_version:
            raise ValueError("hash version is required")
        if not identity.workflow_version:
            raise ValueError("workflow version is required")

    @staticmethod
    def _record(row: sqlite3.Row) -> GenerationRecord:
        has_identity = all(
            row[name] is not None
            for name in (
                "inventory_fingerprint",
                "inventory_object_count",
                "slider_value",
                "matcher_version",
                "hash_version",
                "workflow_version",
            )
        )
        identity = None
        if has_identity:
            identity = GenerationIdentity(
                inventory_fingerprint=str(row["inventory_fingerprint"]),
                inventory_object_count=int(row["inventory_object_count"]),
                slider_value=int(row["slider_value"]),
                matcher_version=str(row["matcher_version"]),
                hash_version=str(row["hash_version"]),
                workflow_version=str(row["workflow_version"]),
            )
        return GenerationRecord(
            generation_id=str(row["generation_id"]),
            state=str(row["state"]),
            identity=identity,
            saved_queue_position=int(row["saved_queue_position"]),
        )
