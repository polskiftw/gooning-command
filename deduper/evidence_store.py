from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


EVIDENCE_SCHEMA_VERSION = 1
COMPARISON_ENGINE_VERSION = 1


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS inventory_snapshot (
    key TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    etag TEXT NOT NULL DEFAULT '',
    last_modified TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS comparison_edges (
    left_key TEXT NOT NULL,
    right_key TEXT NOT NULL,
    phash_distance INTEGER,
    pdq_distance INTEGER,
    crop_similarity REAL,
    vpdq_left_similarity REAL,
    vpdq_right_similarity REAL,
    evidence_mask INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (left_key, right_key),
    CHECK (left_key < right_key)
);

CREATE TABLE IF NOT EXISTS cache_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS comparison_edges_phash_idx
    ON comparison_edges(phash_distance)
    WHERE phash_distance IS NOT NULL;
CREATE INDEX IF NOT EXISTS comparison_edges_pdq_idx
    ON comparison_edges(pdq_distance)
    WHERE pdq_distance IS NOT NULL;
CREATE INDEX IF NOT EXISTS comparison_edges_crop_idx
    ON comparison_edges(crop_similarity DESC)
    WHERE crop_similarity IS NOT NULL;
"""


@dataclass(frozen=True)
class InventoryRecord:
    key: str
    size: int
    etag: str = ""
    last_modified: str = ""


@dataclass(frozen=True)
class EvidenceMetadataCheckpoint:
    inventory: tuple[InventoryRecord, ...]
    state: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class EvidenceEdge:
    left_key: str
    right_key: str
    phash_distance: int | None = None
    pdq_distance: int | None = None
    crop_similarity: float | None = None
    vpdq_left_similarity: float | None = None
    vpdq_right_similarity: float | None = None
    evidence_mask: int = 0

    def normalized(self) -> "EvidenceEdge":
        if self.left_key == self.right_key:
            raise ValueError("an evidence edge must reference two different assets")
        if self.left_key < self.right_key:
            return self
        return EvidenceEdge(
            left_key=self.right_key,
            right_key=self.left_key,
            phash_distance=self.phash_distance,
            pdq_distance=self.pdq_distance,
            crop_similarity=self.crop_similarity,
            vpdq_left_similarity=self.vpdq_right_similarity,
            vpdq_right_similarity=self.vpdq_left_similarity,
            evidence_mask=self.evidence_mask,
        )


def inventory_fingerprint(records: Iterable[InventoryRecord]) -> str:
    """Return a stable identity for an inventory, independent of listing order."""
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item.key):
        for value in (
            record.key,
            str(int(record.size)),
            record.etag or "",
            record.last_modified or "",
        ):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


class EvidenceStore:
    """Durable slider-independent comparison evidence.

    This database is intentionally separate from the current review database so
    the cache can be introduced and validated without risking existing hashes,
    pair decisions, or deletion queues.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.executescript(SCHEMA)
            self._set_state("schema_version", str(EVIDENCE_SCHEMA_VERSION))
            self._set_state("comparison_engine_version", str(COMPARISON_ENGINE_VERSION))
            if self.get_state("loosest_complete_slider") is None:
                self._set_state("loosest_complete_slider", "100")
            if self.get_state("build_status") is None:
                self._set_state("build_status", "empty")

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def get_state(self, key: str) -> str | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT value FROM cache_state WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._lock, self.connection:
            self._set_state(key, value)

    def _set_state(self, key: str, value: str) -> None:
        self.connection.execute(
            """
            INSERT INTO cache_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def metadata_checkpoint(self) -> EvidenceMetadataCheckpoint:
        """Capture authoritative inventory and build-state metadata.

        Comparison edges are deliberately excluded: they are reusable evidence and
        may safely survive an abandoned build. The inventory identity and certified
        boundary are restored unless the replacement generation is promoted.
        """
        with self._lock:
            inventory_rows = self.connection.execute(
                """
                SELECT key, size, etag, last_modified
                FROM inventory_snapshot ORDER BY key
                """
            ).fetchall()
            state_rows = self.connection.execute(
                "SELECT key, value FROM cache_state ORDER BY key"
            ).fetchall()
        return EvidenceMetadataCheckpoint(
            inventory=tuple(
                InventoryRecord(
                    key=str(row["key"]),
                    size=int(row["size"]),
                    etag=str(row["etag"]),
                    last_modified=str(row["last_modified"]),
                )
                for row in inventory_rows
            ),
            state=tuple((str(row["key"]), str(row["value"])) for row in state_rows),
        )

    def restore_metadata(self, checkpoint: EvidenceMetadataCheckpoint) -> None:
        """Restore the active evidence identity after an unpromoted build."""
        with self._lock, self.connection:
            self.connection.execute("DELETE FROM inventory_snapshot")
            self.connection.executemany(
                """
                INSERT INTO inventory_snapshot (key, size, etag, last_modified)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (item.key, item.size, item.etag, item.last_modified)
                    for item in checkpoint.inventory
                ),
            )
            self.connection.execute("DELETE FROM cache_state")
            self.connection.executemany(
                "INSERT INTO cache_state (key, value) VALUES (?, ?)",
                checkpoint.state,
            )

    def replace_inventory_snapshot(self, records: Iterable[InventoryRecord]) -> str:
        materialized = sorted(records, key=lambda item: item.key)
        fingerprint = inventory_fingerprint(materialized)
        with self._lock, self.connection:
            self.connection.execute("DELETE FROM inventory_snapshot")
            self.connection.executemany(
                """
                INSERT INTO inventory_snapshot (key, size, etag, last_modified)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (item.key, int(item.size), item.etag or "", item.last_modified or "")
                    for item in materialized
                ),
            )
            self._set_state("inventory_fingerprint", fingerprint)
            self._set_state("inventory_count", str(len(materialized)))
        return fingerprint

    def inventory_matches(self, records: Iterable[InventoryRecord]) -> bool:
        stored = self.get_state("inventory_fingerprint")
        if stored is None:
            return False
        return stored == inventory_fingerprint(records)

    def inventory_count(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM inventory_snapshot"
            ).fetchone()
        return int(row["count"])

    def clear_evidence(self) -> None:
        with self._lock, self.connection:
            self.connection.execute("DELETE FROM comparison_edges")
            self._set_state("loosest_complete_slider", "100")
            self._set_state("build_status", "empty")

    def remove_asset(self, key: str) -> None:
        with self._lock, self.connection:
            self.connection.execute("DELETE FROM inventory_snapshot WHERE key = ?", (key,))
            self.connection.execute(
                "DELETE FROM comparison_edges WHERE left_key = ? OR right_key = ?",
                (key, key),
            )
            self._set_state("build_status", "dirty")

    def upsert_edges(self, edges: Iterable[EvidenceEdge]) -> int:
        normalized = [edge.normalized() for edge in edges]
        if not normalized:
            return 0
        with self._lock, self.connection:
            self.connection.executemany(
                """
                INSERT INTO comparison_edges (
                    left_key, right_key, phash_distance, pdq_distance,
                    crop_similarity, vpdq_left_similarity, vpdq_right_similarity,
                    evidence_mask
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(left_key, right_key) DO UPDATE SET
                    phash_distance = COALESCE(excluded.phash_distance, comparison_edges.phash_distance),
                    pdq_distance = COALESCE(excluded.pdq_distance, comparison_edges.pdq_distance),
                    crop_similarity = COALESCE(excluded.crop_similarity, comparison_edges.crop_similarity),
                    vpdq_left_similarity = COALESCE(
                        excluded.vpdq_left_similarity,
                        comparison_edges.vpdq_left_similarity
                    ),
                    vpdq_right_similarity = COALESCE(
                        excluded.vpdq_right_similarity,
                        comparison_edges.vpdq_right_similarity
                    ),
                    evidence_mask = comparison_edges.evidence_mask | excluded.evidence_mask,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    (
                        edge.left_key,
                        edge.right_key,
                        edge.phash_distance,
                        edge.pdq_distance,
                        edge.crop_similarity,
                        edge.vpdq_left_similarity,
                        edge.vpdq_right_similarity,
                        edge.evidence_mask,
                    )
                    for edge in normalized
                ),
            )
        return len(normalized)

    def edge_count(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM comparison_edges"
            ).fetchone()
        return int(row["count"])

    def mark_range_complete(self, loosest_slider: int) -> None:
        value = max(0, min(99, int(loosest_slider)))
        current_raw = self.get_state("loosest_complete_slider")
        current = 100 if current_raw is None else int(current_raw)
        # The completed range may only expand toward Loose. A crash or retry must
        # never falsely move the boundary in the stricter direction.
        completed = min(current, value)
        with self._lock, self.connection:
            self._set_state("loosest_complete_slider", str(completed))
            self._set_state("build_status", "complete" if completed == 0 else "building")

    def loosest_complete_slider(self) -> int | None:
        raw = self.get_state("loosest_complete_slider")
        if raw is None:
            return None
        value = int(raw)
        return None if value > 99 else value
