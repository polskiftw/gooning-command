from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PendingFamilyRecertification:
    recertification_id: int
    deleted_key: str
    protected_key: str
    priority_keys: tuple[str, ...]
    status: str
    attempt_count: int
    last_error: str | None


class FamilyRecertificationQueue:
    """Crash-safe priority queue for BYE BITCH family recertification.

    Startup performs an idempotent in-place migration from historical
    ``family_repair_*`` tables to the current ``family_recertification_*``
    schema before any queue operation runs.
    """

    OPEN_STATUSES = ("pending", "running", "retry")

    def __init__(self, database) -> None:
        self.database = database
        with self.database._lock, self.database.connection:
            self._migrate_legacy_schema()
            self._create_current_schema()
            self._recover_interrupted_work()

    def _table_exists(self, name: str) -> bool:
        row = self.database.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def _create_current_schema(self) -> None:
        self.database.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS family_recertification_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deleted_key TEXT NOT NULL,
                protected_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                last_attempt_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS family_recertification_members (
                recertification_id INTEGER NOT NULL
                    REFERENCES family_recertification_jobs(id) ON DELETE CASCADE,
                priority INTEGER NOT NULL,
                asset_key TEXT NOT NULL,
                PRIMARY KEY (recertification_id, asset_key),
                UNIQUE (recertification_id, priority)
            );
            CREATE INDEX IF NOT EXISTS family_recertification_status_idx
                ON family_recertification_jobs(status, id);
            """
        )
        columns = {
            str(row["name"])
            for row in self.database.connection.execute(
                "PRAGMA table_info(family_recertification_jobs)"
            ).fetchall()
        }
        if "attempt_count" not in columns:
            self.database.connection.execute(
                "ALTER TABLE family_recertification_jobs "
                "ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )
        if "last_error" not in columns:
            self.database.connection.execute(
                "ALTER TABLE family_recertification_jobs ADD COLUMN last_error TEXT"
            )
        if "last_attempt_at" not in columns:
            self.database.connection.execute(
                "ALTER TABLE family_recertification_jobs ADD COLUMN last_attempt_at TEXT"
            )

    def _migrate_legacy_schema(self) -> None:
        legacy_jobs = self._table_exists("family_repair_jobs")
        legacy_members = self._table_exists("family_repair_members")
        if not legacy_jobs and not legacy_members:
            return
        if legacy_jobs != legacy_members:
            raise RuntimeError("incomplete legacy family recertification schema")

        self._create_current_schema()
        legacy_columns = {
            str(row["name"])
            for row in self.database.connection.execute(
                "PRAGMA table_info(family_repair_jobs)"
            ).fetchall()
        }
        attempt_expr = "attempt_count" if "attempt_count" in legacy_columns else "0"
        error_expr = "last_error" if "last_error" in legacy_columns else "NULL"
        attempted_expr = "last_attempt_at" if "last_attempt_at" in legacy_columns else "NULL"
        self.database.connection.execute(
            f"""
            INSERT OR IGNORE INTO family_recertification_jobs (
                id, deleted_key, protected_key, status, attempt_count, last_error,
                last_attempt_at, created_at, completed_at
            )
            SELECT id, deleted_key, protected_key, status, {attempt_expr}, {error_expr},
                   {attempted_expr}, created_at, completed_at
            FROM family_repair_jobs
            """
        )
        self.database.connection.execute(
            """
            INSERT OR IGNORE INTO family_recertification_members (
                recertification_id, priority, asset_key
            )
            SELECT repair_id, priority, asset_key
            FROM family_repair_members
            """
        )

        old_jobs = int(self.database.connection.execute(
            "SELECT COUNT(*) AS count FROM family_repair_jobs"
        ).fetchone()["count"])
        new_jobs = int(self.database.connection.execute(
            "SELECT COUNT(*) AS count FROM family_recertification_jobs"
        ).fetchone()["count"])
        old_members = int(self.database.connection.execute(
            "SELECT COUNT(*) AS count FROM family_repair_members"
        ).fetchone()["count"])
        new_members = int(self.database.connection.execute(
            "SELECT COUNT(*) AS count FROM family_recertification_members"
        ).fetchone()["count"])
        if new_jobs < old_jobs or new_members < old_members:
            raise RuntimeError("family recertification schema migration verification failed")

        orphan = self.database.connection.execute(
            """
            SELECT 1
            FROM family_recertification_members m
            LEFT JOIN family_recertification_jobs j ON j.id = m.recertification_id
            WHERE j.id IS NULL
            LIMIT 1
            """
        ).fetchone()
        if orphan is not None:
            raise RuntimeError("family recertification migration produced orphan members")

        self.database.connection.execute("DROP TABLE family_repair_members")
        self.database.connection.execute("DROP TABLE family_repair_jobs")

    def _recover_interrupted_work(self) -> None:
        self.database.connection.execute(
            """
            UPDATE family_recertification_jobs
            SET status = 'retry',
                last_error = COALESCE(
                    last_error,
                    'Application closed during family recertification'
                )
            WHERE status = 'running'
            """
        )
        self.database.connection.execute(
            """
            UPDATE family_recertification_jobs
            SET status = 'complete', completed_at = CURRENT_TIMESTAMP
            WHERE status IN ('pending', 'running', 'retry')
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM family_recertification_jobs
                  WHERE status IN ('pending', 'running', 'retry')
                  GROUP BY deleted_key
              )
            """
        )
        self.database.connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                family_recertification_one_open_deleted_idx
            ON family_recertification_jobs(deleted_key)
            WHERE status IN ('pending', 'running', 'retry')
            """
        )

    def _priority_keys(self, recertification_id: int) -> tuple[str, ...]:
        rows = self.database.connection.execute(
            """
            SELECT asset_key
            FROM family_recertification_members
            WHERE recertification_id = ?
            ORDER BY priority
            """,
            (recertification_id,),
        ).fetchall()
        return tuple(str(row["asset_key"]) for row in rows)

    def enqueue(
        self,
        deleted_key: str,
        protected_key: str,
        priority_keys: Iterable[str],
    ) -> int:
        ordered = tuple(dict.fromkeys(priority_keys))
        if not ordered:
            raise ValueError("family recertification requires at least one surviving asset")
        if ordered[0] != protected_key:
            raise ValueError("protected key must be first in family recertification priority")
        if deleted_key in ordered:
            raise ValueError("deleted key cannot be queued for family recertification")

        with self.database._lock, self.database.connection:
            existing = self.database.connection.execute(
                """
                SELECT id, protected_key
                FROM family_recertification_jobs
                WHERE deleted_key = ? AND status IN ('pending', 'running', 'retry')
                """,
                (deleted_key,),
            ).fetchone()
            if existing is not None:
                recertification_id = int(existing["id"])
                if str(existing["protected_key"]) != protected_key:
                    raise ValueError("unfinished family recertification has a different protected partner")
                if self._priority_keys(recertification_id) != ordered:
                    raise ValueError("unfinished family recertification has a different priority order")
                return recertification_id

            cursor = self.database.connection.execute(
                """
                INSERT INTO family_recertification_jobs (deleted_key, protected_key, status)
                VALUES (?, ?, 'pending')
                """,
                (deleted_key, protected_key),
            )
            recertification_id = int(cursor.lastrowid)
            self.database.connection.executemany(
                """
                INSERT INTO family_recertification_members (recertification_id, priority, asset_key)
                VALUES (?, ?, ?)
                """,
                (
                    (recertification_id, priority, asset_key)
                    for priority, asset_key in enumerate(ordered)
                ),
            )
        return recertification_id

    def pending(self) -> tuple[PendingFamilyRecertification, ...]:
        with self.database._lock:
            jobs = self.database.connection.execute(
                """
                SELECT id, deleted_key, protected_key, status, attempt_count, last_error
                FROM family_recertification_jobs
                WHERE status IN ('pending', 'running', 'retry')
                ORDER BY id
                """
            ).fetchall()
            results = []
            for job in jobs:
                results.append(
                    PendingFamilyRecertification(
                        recertification_id=int(job["id"]),
                        deleted_key=str(job["deleted_key"]),
                        protected_key=str(job["protected_key"]),
                        priority_keys=self._priority_keys(int(job["id"])),
                        status=str(job["status"]),
                        attempt_count=int(job["attempt_count"]),
                        last_error=(str(job["last_error"]) if job["last_error"] else None),
                    )
                )
        return tuple(results)

    def mark_running(self, recertification_id: int) -> bool:
        """Atomically claim pending/retry work; only one caller can succeed."""
        with self.database._lock, self.database.connection:
            cursor = self.database.connection.execute(
                """
                UPDATE family_recertification_jobs
                SET status = 'running',
                    attempt_count = attempt_count + 1,
                    last_error = NULL,
                    last_attempt_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('pending', 'retry')
                """,
                (recertification_id,),
            )
        return cursor.rowcount == 1

    def mark_pending(self, recertification_id: int, error: str | None = None) -> None:
        """Release a claim for retry while preserving the visible failure reason."""
        message = error[:1000] if error else "Family recertification did not finish"
        with self.database._lock, self.database.connection:
            self.database.connection.execute(
                """
                UPDATE family_recertification_jobs
                SET status = 'retry', last_error = ?
                WHERE id = ? AND status = 'running'
                """,
                (message, recertification_id),
            )

    def complete(self, recertification_id: int) -> None:
        with self.database._lock, self.database.connection:
            self.database.connection.execute(
                """
                UPDATE family_recertification_jobs
                SET status = 'complete', completed_at = CURRENT_TIMESTAMP, last_error = NULL
                WHERE id = ?
                """,
                (recertification_id,),
            )

    def has_pending(self) -> bool:
        with self.database._lock:
            row = self.database.connection.execute(
                """
                SELECT 1 FROM family_recertification_jobs
                WHERE status IN ('pending', 'running', 'retry')
                LIMIT 1
                """,
            ).fetchone()
        return row is not None
