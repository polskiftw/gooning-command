from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Asset:
    key: str
    size: int
    etag: str
    extension: str


class TagDatabase:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assets (
                key TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                etag TEXT NOT NULL,
                extension TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                tags_json TEXT,
                error TEXT,
                sync_id INTEGER NOT NULL DEFAULT 0,
                tagged_at TEXT
            );
            CREATE INDEX IF NOT EXISTS assets_state_idx ON assets(state);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def sync_assets(self, assets: list[Asset]) -> None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE name = 'sync_id'"
        ).fetchone()
        sync_id = int(row[0]) + 1 if row else 1
        with self.connection:
            self.connection.execute(
                "INSERT INTO metadata(name, value) VALUES('sync_id', ?) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (str(sync_id),),
            )
            for asset in assets:
                existing = self.connection.execute(
                    "SELECT size, etag FROM assets WHERE key = ?", (asset.key,)
                ).fetchone()
                unchanged = existing == (asset.size, asset.etag)
                self.connection.execute(
                    """
                    INSERT INTO assets(key, size, etag, extension, sync_id)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        size = excluded.size,
                        etag = excluded.etag,
                        extension = excluded.extension,
                        sync_id = excluded.sync_id,
                        state = CASE WHEN ? THEN assets.state ELSE 'pending' END,
                        tags_json = CASE WHEN ? THEN assets.tags_json ELSE NULL END,
                        error = CASE WHEN ? THEN assets.error ELSE NULL END,
                        tagged_at = CASE WHEN ? THEN assets.tagged_at ELSE NULL END
                    """,
                    (
                        asset.key,
                        asset.size,
                        asset.etag,
                        asset.extension,
                        sync_id,
                        unchanged,
                        unchanged,
                        unchanged,
                        unchanged,
                    ),
                )
            self.connection.execute("DELETE FROM assets WHERE sync_id != ?", (sync_id,))

    def pending(self) -> list[Asset]:
        rows = self.connection.execute(
            "SELECT key, size, etag, extension FROM assets WHERE state != 'tagged' ORDER BY key"
        ).fetchall()
        return [Asset(*row) for row in rows]

    def mark_tagged(self, key: str, tags: list[str], tagged_at: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE assets SET state = 'tagged', tags_json = ?, error = NULL, tagged_at = ? WHERE key = ?",
                (json.dumps(tags, ensure_ascii=False, separators=(",", ":")), tagged_at, key),
            )

    def mark_error(self, key: str, message: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE assets SET state = 'error', error = ? WHERE key = ?",
                (message[:2000], key),
            )

    def tagged_rows(self) -> list[tuple[str, str, list[str]]]:
        rows = self.connection.execute(
            "SELECT key, extension, tags_json FROM assets WHERE state = 'tagged' ORDER BY key"
        ).fetchall()
        return [(key, extension, json.loads(tags_json or "[]")) for key, extension, tags_json in rows]

    def counts(self) -> tuple[int, int, int]:
        total = self.connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        tagged = self.connection.execute(
            "SELECT COUNT(*) FROM assets WHERE state = 'tagged'"
        ).fetchone()[0]
        errors = self.connection.execute(
            "SELECT COUNT(*) FROM assets WHERE state = 'error'"
        ).fetchone()[0]
        return total, tagged, errors

