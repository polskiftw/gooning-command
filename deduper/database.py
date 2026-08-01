from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path

from .models import Asset, Pair


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assets (
    key TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    etag TEXT NOT NULL DEFAULT '',
    last_modified TEXT NOT NULL DEFAULT '',
    media_type TEXT NOT NULL,
    extension TEXT NOT NULL,
    sha256 TEXT,
    phash TEXT,
    crop_hashes TEXT,
    pdq_hash TEXT,
    pdq_quality INTEGER,
    vpdq_hashes TEXT,
    width INTEGER,
    height INTEGER,
    duration REAL,
    scan_error TEXT,
    scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    left_key TEXT NOT NULL REFERENCES assets(key),
    right_key TEXT NOT NULL REFERENCES assets(key),
    similarity REAL NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decision TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    UNIQUE(left_key, right_key)
);

CREATE TABLE IF NOT EXISTS deletion_queue (
    key TEXT PRIMARY KEY REFERENCES assets(key),
    pair_id INTEGER REFERENCES pairs(id),
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sha_deletion_queue (
    key TEXT PRIMARY KEY REFERENCES assets(key),
    survivor_key TEXT NOT NULL REFERENCES assets(key),
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deletion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deleted_key TEXT NOT NULL,
    survivor_key TEXT,
    pair_id INTEGER,
    size INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    result TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_cleanup_queue (
    key TEXT PRIMARY KEY,
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS assets_sha256_idx ON assets(sha256);
CREATE INDEX IF NOT EXISTS assets_phash_idx ON assets(phash);
CREATE INDEX IF NOT EXISTS pairs_status_idx ON pairs(status, similarity DESC);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.executescript(SCHEMA)
            workflow = self.connection.execute(
                "SELECT value FROM meta WHERE key = 'review_workflow'"
            ).fetchone()
            if workflow is None or workflow["value"] != "single-screen-v2":
                self.connection.execute("DELETE FROM deletion_queue")
                self.connection.execute("DELETE FROM pairs")
                self.connection.execute(
                    """
                    INSERT INTO meta (key, value) VALUES ('review_workflow', 'single-screen-v2')
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """
                )

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def upsert_inventory(self, assets: Iterable[Asset]) -> tuple[int, int]:
        new_count = changed_count = 0
        with self._lock, self.connection:
            for asset in assets:
                existing = self.connection.execute(
                    "SELECT size, etag, last_modified FROM assets WHERE key = ?", (asset.key,)
                ).fetchone()
                if existing is None:
                    self.connection.execute(
                        """
                        INSERT INTO assets
                            (key, size, etag, last_modified, media_type, extension)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset.key,
                            asset.size,
                            asset.etag,
                            asset.last_modified,
                            asset.media_type,
                            asset.extension,
                        ),
                    )
                    new_count += 1
                elif (
                    existing["size"] != asset.size
                    or existing["etag"] != asset.etag
                    or existing["last_modified"] != asset.last_modified
                ):
                    self.connection.execute(
                        """
                        UPDATE assets
                        SET size = ?, etag = ?, last_modified = ?, media_type = ?, extension = ?,
                            sha256 = NULL, phash = NULL, crop_hashes = NULL, pdq_hash = NULL,
                            pdq_quality = NULL, vpdq_hashes = NULL, width = NULL, height = NULL,
                            duration = NULL, scan_error = NULL, deleted = 0
                        WHERE key = ?
                        """,
                        (
                            asset.size,
                            asset.etag,
                            asset.last_modified,
                            asset.media_type,
                            asset.extension,
                            asset.key,
                        ),
                    )
                    self.connection.execute(
                        "DELETE FROM sha_deletion_queue WHERE key = ? OR survivor_key = ?",
                        (asset.key, asset.key),
                    )
                    changed_count += 1
                else:
                    self.connection.execute("UPDATE assets SET deleted = 0 WHERE key = ?", (asset.key,))
        return new_count, changed_count

    def mark_missing_deleted(self, live_keys: set[str]) -> int:
        with self._lock, self.connection:
            rows = self.connection.execute("SELECT key FROM assets WHERE deleted = 0").fetchall()
            missing = [row["key"] for row in rows if row["key"] not in live_keys]
            self.connection.executemany("UPDATE assets SET deleted = 1 WHERE key = ?", ((key,) for key in missing))
            self.connection.executemany("DELETE FROM deletion_queue WHERE key = ?", ((key,) for key in missing))
            self.connection.executemany(
                "DELETE FROM sha_deletion_queue WHERE key = ? OR survivor_key = ?",
                ((key, key) for key in missing),
            )
        return len(missing)

    def assets_needing_hashes(self) -> Iterator[Asset]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT * FROM assets
                WHERE deleted = 0 AND sha256 IS NULL
                ORDER BY key
                """
            ).fetchall()
        for row in rows:
            yield self._asset_from_row(row)

    def save_hashes(self, asset: Asset) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                UPDATE assets SET
                    sha256 = ?, phash = ?, crop_hashes = ?, pdq_hash = ?, pdq_quality = ?,
                    vpdq_hashes = ?, width = ?, height = ?, duration = ?, scan_error = ?,
                    scanned_at = CURRENT_TIMESTAMP
                WHERE key = ?
                """,
                (
                    asset.sha256,
                    asset.phash,
                    asset.crop_hashes,
                    asset.pdq_hash,
                    asset.pdq_quality,
                    asset.vpdq_hashes,
                    asset.width,
                    asset.height,
                    asset.duration,
                    asset.scan_error,
                    asset.key,
                ),
            )

    def all_hashed_assets(self) -> list[Asset]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM assets WHERE deleted = 0 AND sha256 IS NOT NULL"
            ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def replace_pairs(
        self,
        pairs: Iterable[tuple[str, str, float, str]],
        *,
        preserve_exclusions: bool = False,
    ) -> int:
        normalized: dict[tuple[str, str], tuple[float, str]] = {}
        for left, right, similarity, reason in pairs:
            key = (left, right)
            current = normalized.get(key)
            if current is None or similarity > current[0]:
                normalized[key] = (similarity, reason)

        with self._lock, self.connection:
            # A later matching checkpoint replaces and expands the result set. Keep
            # review decisions already made while that background work was running.
            excluded = set()
            if preserve_exclusions:
                excluded = {
                    (row["left_key"], row["right_key"])
                    for row in self.connection.execute(
                        "SELECT left_key, right_key FROM pairs WHERE status = 'excluded'"
                    ).fetchall()
                }
            rows = []
            for (left, right), (similarity, reason) in normalized.items():
                is_excluded = (left, right) in excluded
                rows.append(
                    (
                        left,
                        right,
                        similarity,
                        reason,
                        "excluded" if is_excluded else "included",
                        "exclude" if is_excluded else None,
                        "excluded" if is_excluded else "included",
                    )
                )

            # Thousands of execute() calls held the shared database lock long enough
            # to make navigation look frozen. Bulk insertion keeps the checkpoint
            # transaction short while preserving its all-or-nothing behavior.
            self.connection.execute("DELETE FROM deletion_queue")
            self.connection.execute("DELETE FROM pairs")
            self.connection.executemany(
                """
                INSERT INTO pairs
                    (left_key, right_key, similarity, reason, status, decision, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?,
                    CASE WHEN ? = 'excluded' THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                rows,
            )
            self.connection.execute(
                """
                INSERT OR IGNORE INTO deletion_queue (key, pair_id)
                SELECT right_key, id FROM pairs WHERE status = 'included'
                """
            )
        return len(normalized)

    def replace_sha_deletions(self, deletions: Iterable[tuple[str, str]]) -> int:
        """Replace the invisible exact-SHA queue for the current scan.

        Each tuple is (survivor_key, deletion_key). Exact duplicates never enter
        the review-pair table, but NUKE still receives every redundant object.
        """
        normalized = {
            deletion_key: survivor_key
            for survivor_key, deletion_key in deletions
            if survivor_key != deletion_key
        }
        with self._lock, self.connection:
            self.connection.execute("DELETE FROM sha_deletion_queue")
            self.connection.executemany(
                """
                INSERT INTO sha_deletion_queue (key, survivor_key)
                VALUES (?, ?)
                """,
                ((key, survivor) for key, survivor in normalized.items()),
            )
        return len(normalized)

    def set_matching_state(self, state: str) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO meta (key, value) VALUES ('matching_state', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (state,),
            )

    def matching_state(self) -> str:
        with self._lock:
            row = self.connection.execute(
                "SELECT value FROM meta WHERE key = 'matching_state'"
            ).fetchone()
        return str(row["value"]) if row else "not_started"

    def scan_pairs(self) -> list[Pair]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT p.* FROM pairs p
                JOIN assets left_asset ON left_asset.key = p.left_key
                JOIN assets right_asset ON right_asset.key = p.right_key
                WHERE left_asset.deleted = 0 AND right_asset.deleted = 0
                ORDER BY p.similarity ASC, p.id
                """
            ).fetchall()
        return [self._pair_from_row(row) for row in rows]

    def exclude_pair(self, pair_id: int) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                UPDATE pairs
                SET status = 'excluded', decision = 'exclude', reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (pair_id,),
            )
            self.connection.execute("DELETE FROM deletion_queue WHERE pair_id = ?", (pair_id,))

    def exclude_pair_keys(self, left_key: str, right_key: str) -> bool:
        """Exclude the current version of a pair even if a checkpoint rebuilt its row."""
        with self._lock, self.connection:
            row = self.connection.execute(
                "SELECT id FROM pairs WHERE left_key = ? AND right_key = ?",
                (left_key, right_key),
            ).fetchone()
            if row is None:
                return False
            pair_id = int(row["id"])
            self.connection.execute(
                """
                UPDATE pairs
                SET status = 'excluded', decision = 'exclude', reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (pair_id,),
            )
            self.connection.execute("DELETE FROM deletion_queue WHERE pair_id = ?", (pair_id,))
            return True

    def queued_deletions(self) -> list[tuple[str, int | None, int]]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT q.key, q.pair_id, a.size, q.queued_at
                FROM deletion_queue q JOIN assets a ON a.key = q.key
                WHERE a.deleted = 0
                  AND NOT EXISTS (SELECT 1 FROM sha_deletion_queue s WHERE s.key = q.key)
                UNION ALL
                SELECT q.key, NULL AS pair_id, a.size, q.queued_at
                FROM sha_deletion_queue q JOIN assets a ON a.key = q.key
                WHERE a.deleted = 0
                ORDER BY 4, 1
                """
            ).fetchall()
        return [(row["key"], row["pair_id"], row["size"]) for row in rows]

    def queued_sha_deletions(self) -> list[tuple[str, int | None, int]]:
        """Return only invisible exact-SHA extras for the dedicated mini NUKE."""
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT q.key, NULL AS pair_id, a.size
                FROM sha_deletion_queue q JOIN assets a ON a.key = q.key
                WHERE a.deleted = 0
                ORDER BY q.queued_at, q.key
                """
            ).fetchall()
        return [(row["key"], row["pair_id"], row["size"]) for row in rows]

    def record_deletions(self, results: Iterable[tuple[str, int | None, int, str]]) -> None:
        with self._lock, self.connection:
            for key, pair_id, size, result in results:
                survivor = None
                if pair_id is not None:
                    row = self.connection.execute(
                        "SELECT left_key, right_key FROM pairs WHERE id = ?", (pair_id,)
                    ).fetchone()
                    if row:
                        survivor = row["right_key"] if row["left_key"] == key else row["left_key"]
                else:
                    row = self.connection.execute(
                        "SELECT survivor_key FROM sha_deletion_queue WHERE key = ?", (key,)
                    ).fetchone()
                    if row:
                        survivor = row["survivor_key"]
                self.connection.execute(
                    """
                    INSERT INTO deletion_log
                        (deleted_key, survivor_key, pair_id, size, result)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (key, survivor, pair_id, size, result),
                )
                if result == "deleted":
                    self.connection.execute("UPDATE assets SET deleted = 1 WHERE key = ?", (key,))
                    self.connection.execute("DELETE FROM deletion_queue WHERE key = ?", (key,))
                    self.connection.execute("DELETE FROM sha_deletion_queue WHERE key = ?", (key,))

    def queue_index_cleanup(self, keys: Iterable[str]) -> None:
        with self._lock, self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO index_cleanup_queue (key) VALUES (?)",
                ((key,) for key in keys),
            )

    def pending_index_cleanup(self) -> set[str]:
        with self._lock:
            rows = self.connection.execute("SELECT key FROM index_cleanup_queue").fetchall()
        return {row["key"] for row in rows}

    def clear_index_cleanup(self, keys: Iterable[str]) -> None:
        with self._lock, self.connection:
            self.connection.executemany(
                "DELETE FROM index_cleanup_queue WHERE key = ?",
                ((key,) for key in keys),
            )

    def counts(self) -> dict[str, int]:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN deleted = 0 THEN 1 ELSE 0 END) AS live,
                    SUM(CASE WHEN deleted = 0 AND sha256 IS NOT NULL THEN 1 ELSE 0 END) AS hashed,
                    SUM(CASE WHEN scan_error IS NOT NULL THEN 1 ELSE 0 END) AS errors
                FROM assets
                """
            ).fetchone()
            pairs = self.connection.execute(
                """
                SELECT COUNT(*) FROM pairs p
                JOIN assets left_asset ON left_asset.key = p.left_key
                JOIN assets right_asset ON right_asset.key = p.right_key
                WHERE left_asset.deleted = 0 AND right_asset.deleted = 0
                """
            ).fetchone()[0]
            queued = self.connection.execute(
                """
                SELECT COUNT(*) FROM deletion_queue q
                JOIN assets a ON a.key = q.key
                WHERE a.deleted = 0
                  AND NOT EXISTS (SELECT 1 FROM sha_deletion_queue s WHERE s.key = q.key)
                """
            ).fetchone()[0]
            sha_queued = self.connection.execute(
                """
                SELECT COUNT(*) FROM sha_deletion_queue q
                JOIN assets a ON a.key = q.key
                WHERE a.deleted = 0
                """
            ).fetchone()[0]
        return {
            "total": int(row["total"] or 0),
            "live": int(row["live"] or 0),
            "hashed": int(row["hashed"] or 0),
            "errors": int(row["errors"] or 0),
            "pending": int(pairs),
            "sha_queued": int(sha_queued),
            "queued": int(queued) + int(sha_queued),
        }

    def asset(self, key: str) -> Asset | None:
        with self._lock:
            row = self.connection.execute("SELECT * FROM assets WHERE key = ?", (key,)).fetchone()
        return self._asset_from_row(row) if row else None

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> Asset:
        return Asset(
            key=row["key"],
            size=row["size"],
            etag=row["etag"],
            last_modified=row["last_modified"],
            media_type=row["media_type"],
            extension=row["extension"],
            sha256=row["sha256"],
            phash=row["phash"],
            crop_hashes=row["crop_hashes"],
            pdq_hash=row["pdq_hash"],
            pdq_quality=row["pdq_quality"],
            vpdq_hashes=row["vpdq_hashes"],
            width=row["width"],
            height=row["height"],
            duration=row["duration"],
            scan_error=row["scan_error"],
            deleted=bool(row["deleted"]),
        )

    @staticmethod
    def _pair_from_row(row: sqlite3.Row) -> Pair:
        return Pair(
            id=row["id"],
            left_key=row["left_key"],
            right_key=row["right_key"],
            similarity=row["similarity"],
            reason=row["reason"],
            status=row["status"],
            decision=row["decision"],
        )
