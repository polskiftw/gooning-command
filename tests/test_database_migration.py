from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.database import Database
from deduper.database_migration import DATABASE_SCHEMA_VERSION, migrate_and_recover
from deduper.models import Asset


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "gparty-deduper.sqlite3"
        self.database = Database(self.path)
        assets = [
            Asset("gallery/a.jpg", 10, "a", "1", "image", "jpg", sha256="a" * 64),
            Asset("gallery/b.jpg", 9, "b", "1", "image", "jpg", sha256="b" * 64),
        ]
        self.database.upsert_inventory(assets)
        for asset in assets:
            self.database.save_hashes(asset)
        self.database.replace_pairs(
            [("gallery/a.jpg", "gallery/b.jpg", 99.0, "fixture")]
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def counts(self) -> tuple[int, int, int]:
        connection = self.database.connection
        return (
            connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM pairs").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM deletion_queue").fetchone()[0],
        )

    def test_migration_preserves_existing_work_and_is_idempotent(self) -> None:
        before = self.counts()
        first = migrate_and_recover(self.database)
        after_first = self.counts()
        second = migrate_and_recover(self.database)
        after_second = self.counts()

        self.assertEqual(before, after_first)
        self.assertEqual(after_first, after_second)
        self.assertEqual(first.current_version, DATABASE_SCHEMA_VERSION)
        self.assertEqual(second.previous_version, DATABASE_SCHEMA_VERSION)
        self.assertTrue(first.integrity_ok)
        self.assertEqual(first.foreign_key_violations, 0)
        self.assertEqual(
            self.database.connection.execute(
                "SELECT COUNT(*) FROM migration_log"
            ).fetchone()[0],
            DATABASE_SCHEMA_VERSION,
        )

    def test_running_scan_becomes_interrupted_without_clearing_queue(self) -> None:
        before = self.counts()
        self.database.set_matching_state("running")
        report = migrate_and_recover(self.database)

        self.assertTrue(report.recovered_interrupted_scan)
        self.assertEqual(self.database.matching_state(), "interrupted")
        self.assertEqual(before, self.counts())
        self.assertEqual(
            self.database.connection.execute(
                "SELECT value FROM meta WHERE key = 'recovery_required'"
            ).fetchone()[0],
            "1",
        )

    def test_complete_scan_is_not_relabelled(self) -> None:
        self.database.set_matching_state("complete")
        report = migrate_and_recover(self.database)
        self.assertFalse(report.recovered_interrupted_scan)
        self.assertEqual(self.database.matching_state(), "complete")


if __name__ == "__main__":
    unittest.main()
