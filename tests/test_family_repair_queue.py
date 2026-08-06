from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from deduper.database import Database
from deduper.family_repair_queue import FamilyRepairQueue


class FamilyRepairQueueTests(unittest.TestCase):
    def make_database(self):
        temporary = tempfile.TemporaryDirectory()
        database = Database(Path(temporary.name) / "test.sqlite3")
        return temporary, database

    def test_priority_order_survives_database_reopen(self):
        temporary, database = self.make_database()
        path = database.path
        queue = FamilyRepairQueue(database)
        repair_id = queue.enqueue("A", "1", ("1", "2", "3"))
        database.close()

        reopened = Database(path)
        restored = FamilyRepairQueue(reopened).pending()
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].repair_id, repair_id)
        self.assertEqual(restored[0].deleted_key, "A")
        self.assertEqual(restored[0].protected_key, "1")
        self.assertEqual(restored[0].priority_keys, ("1", "2", "3"))
        reopened.close()
        temporary.cleanup()

    def test_running_job_is_recovered_as_pending_work(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        repair_id = queue.enqueue("A", "1", ("1", "2"))
        queue.mark_running(repair_id)

        restored = queue.pending()
        self.assertEqual([job.repair_id for job in restored], [repair_id])
        database.close()
        temporary.cleanup()

    def test_complete_job_does_not_resume(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        repair_id = queue.enqueue("A", "1", ("1", "2"))
        queue.complete(repair_id)

        self.assertFalse(queue.has_pending())
        self.assertEqual(queue.pending(), ())
        database.close()
        temporary.cleanup()

    def test_protected_partner_must_be_first(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        with self.assertRaises(ValueError):
            queue.enqueue("A", "1", ("2", "1"))
        database.close()
        temporary.cleanup()

    def test_deleted_asset_cannot_enter_repair_queue(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        with self.assertRaises(ValueError):
            queue.enqueue("A", "1", ("1", "A"))
        database.close()
        temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
