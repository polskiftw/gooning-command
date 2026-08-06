from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PendingFamilyRepair:
    repair_id: int
    deleted_key: str
    protected_key: str
    priority_keys: tuple[str, ...]


class FamilyRepairQueue:
    """Crash-safe priority queue for BYE BITCH family recertification."""

    def __init__(self, database) -> None:
        self.database = database
        with self.database._lock, self.database.connection:
            self.database.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS family_repair_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deleted_key TEXT NOT NULL,
                    protected_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS family_repair_members (
                    repair_id INTEGER NOT NULL REFERENCES family_repair_jobs(id) ON DELETE CASCADE,
                    priority INTEGER NOT NULL,
                    asset_key TEXT NOT NULL,
                    PRIMARY KEY (repair_id, asset_key),
                    UNIQUE (repair_id, priority)
                );

                CREATE INDEX IF NOT EXISTS family_repair_status_idx
                    ON family_repair_jobs(status, id);
                """
            )

    def enqueue(
        self,
        deleted_key: str,
        protected_key: str,
        priority_keys: Iterable[str],
    ) -> int:
        ordered = tuple(dict.fromkeys(priority_keys))
        if not ordered:
            raise ValueError("family repair requires at least one surviving asset")
        if ordered[0] != protected_key:
            raise ValueError("protected key must be first in family repair priority")
        if deleted_key in ordered:
            raise ValueError("deleted key cannot be queued for family repair")

        with self.database._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """
                INSERT INTO family_repair_jobs (deleted_key, protected_key, status)
                VALUES (?, ?, 'pending')
                """,
                (deleted_key, protected_key),
            )
            repair_id = int(cursor.lastrowid)
            self.database.connection.executemany(
                """
                INSERT INTO family_repair_members (repair_id, priority, asset_key)
                VALUES (?, ?, ?)
                """,
                (
                    (repair_id, priority, asset_key)
                    for priority, asset_key in enumerate(ordered)
                ),
            )
        return repair_id

    def pending(self) -> tuple[PendingFamilyRepair, ...]:
        with self.database._lock:
            jobs = self.database.connection.execute(
                """
                SELECT id, deleted_key, protected_key
                FROM family_repair_jobs
                WHERE status IN ('pending', 'running')
                ORDER BY id
                """
            ).fetchall()
            results = []
            for job in jobs:
                members = self.database.connection.execute(
                    """
                    SELECT asset_key
                    FROM family_repair_members
                    WHERE repair_id = ?
                    ORDER BY priority
                    """,
                    (job["id"],),
                ).fetchall()
                results.append(
                    PendingFamilyRepair(
                        repair_id=int(job["id"]),
                        deleted_key=str(job["deleted_key"]),
                        protected_key=str(job["protected_key"]),
                        priority_keys=tuple(str(row["asset_key"]) for row in members),
                    )
                )
        return tuple(results)

    def mark_running(self, repair_id: int) -> None:
        with self.database._lock, self.database.connection:
            self.database.connection.execute(
                "UPDATE family_repair_jobs SET status = 'running' WHERE id = ?",
                (repair_id,),
            )

    def mark_pending(self, repair_id: int) -> None:
        with self.database._lock, self.database.connection:
            self.database.connection.execute(
                "UPDATE family_repair_jobs SET status = 'pending' WHERE id = ?",
                (repair_id,),
            )

    def complete(self, repair_id: int) -> None:
        with self.database._lock, self.database.connection:
            self.database.connection.execute(
                """
                UPDATE family_repair_jobs
                SET status = 'complete', completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (repair_id,),
            )

    def has_pending(self) -> bool:
        with self.database._lock:
            row = self.database.connection.execute(
                """
                SELECT 1 FROM family_repair_jobs
                WHERE status IN ('pending', 'running')
                LIMIT 1
                """
            ).fetchone()
        return row is not None
