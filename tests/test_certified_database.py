from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.certified_database import CertifiedDatabase
from deduper.models import Asset


class CertifiedDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = CertifiedDatabase(Path(self.temp.name) / "deduper.sqlite3")
        self.database.upsert_inventory(
            [
                Asset("a.jpg", 10, "a", "1", "image", "jpg"),
                Asset("b.jpg", 20, "b", "1", "image", "jpg"),
            ]
        )
        self.database.replace_pairs([("a.jpg", "b.jpg", 99.0, "test")])

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_permanent_exclusion_survives_pair_rebuild(self) -> None:
        self.assertTrue(self.database.exclude_pair_permanently("a.jpg", "b.jpg"))
        self.database.replace_pairs([("a.jpg", "b.jpg", 99.0, "test")])
        pair = self.database.scan_pairs()[0]
        self.assertEqual(pair.status, "excluded")
        self.assertEqual(self.database.queued_deletions(), [])

    def test_successful_deletion_purges_permanent_decision(self) -> None:
        self.assertTrue(self.database.exclude_pair_permanently("a.jpg", "b.jpg"))
        self.database.record_deletions([("b.jpg", None, 20, "deleted")])
        row = self.database.connection.execute(
            "SELECT COUNT(*) FROM ready_pair_decisions"
        ).fetchone()
        self.assertEqual(int(row[0]), 0)


if __name__ == "__main__":
    unittest.main()
