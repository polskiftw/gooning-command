from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.database import Database
from deduper.models import Asset
from deduper.ready_lifecycle import install_ready_lifecycle


class ReadyLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "deduper.sqlite3"
        self.database = Database(self.path)
        install_ready_lifecycle(self.database)
        self.database.upsert_inventory(
            [
                Asset("a.jpg", 100, "a", "1", "image", "jpg"),
                Asset("b.jpg", 200, "b", "1", "image", "jpg"),
                Asset("c.jpg", 300, "c", "1", "image", "jpg"),
            ]
        )

    def tearDown(self) -> None:
        self.database.close()
        self.temp.cleanup()

    def test_exclusion_survives_rebuild_and_orientation_change(self) -> None:
        self.database.replace_pairs([("a.jpg", "b.jpg", 90.0, "first")])
        pair = self.database.scan_pairs()[0]
        self.assertTrue(self.database.exclude_pair_keys(pair.left_key, pair.right_key))

        self.database.replace_pairs([("b.jpg", "a.jpg", 91.0, "reoriented")])
        rebuilt = self.database.scan_pairs()[0]
        self.assertEqual(rebuilt.status, "excluded")
        self.assertEqual(self.database.queued_deletions(), [])

    def test_exclusion_survives_database_reopen(self) -> None:
        self.database.replace_pairs([("a.jpg", "b.jpg", 90.0, "first")])
        self.database.exclude_pair_keys("a.jpg", "b.jpg")
        self.database.close()

        self.database = Database(self.path)
        install_ready_lifecycle(self.database)
        self.database.replace_pairs([("a.jpg", "b.jpg", 92.0, "after restart")])
        self.assertEqual(self.database.scan_pairs()[0].status, "excluded")

    def test_deleted_asset_purges_obsolete_decision(self) -> None:
        self.database.replace_pairs([("a.jpg", "b.jpg", 90.0, "first")])
        self.database.exclude_pair_keys("a.jpg", "b.jpg")
        self.database.record_deletions([("b.jpg", None, 200, "deleted")])

        row = self.database.connection.execute(
            "SELECT COUNT(*) AS count FROM ready_pair_decisions"
        ).fetchone()
        self.assertEqual(int(row["count"]), 0)

    def test_installation_is_idempotent(self) -> None:
        install_ready_lifecycle(self.database)
        install_ready_lifecycle(self.database)
        self.database.replace_pairs([("a.jpg", "b.jpg", 90.0, "first")])
        self.assertEqual(len(self.database.scan_pairs()), 1)


if __name__ == "__main__":
    unittest.main()
