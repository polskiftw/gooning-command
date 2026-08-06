from __future__ import annotations

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
        self.assertEqual(restored[0].status, "pending")
        self.assertEqual(restored[0].attempt_count, 0)
        self.assertIsNone(restored[0].last_error)
        reopened.close()
        temporary.cleanup()

    def test_running_job_is_recovered_as_visible_retry_work(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        repair_id = queue.enqueue("A", "1", ("1", "2"))
        self.assertTrue(queue.mark_running(repair_id))

        restored_queue = FamilyRepairQueue(database)
        restored = restored_queue.pending()
        self.assertEqual([job.repair_id for job in restored], [repair_id])
        self.assertEqual(restored[0].status, "retry")
        self.assertEqual(restored[0].attempt_count, 1)
        self.assertIn("closed during family repair", restored[0].last_error.lower())
        self.assertTrue(restored_queue.mark_running(repair_id))
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

    def test_identical_reenqueue_returns_existing_unfinished_job(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        first = queue.enqueue("A", "1", ("1", "2"))
        second = queue.enqueue("A", "1", ("1", "2"))

        self.assertEqual(second, first)
        self.assertEqual(len(queue.pending()), 1)
        database.close()
        temporary.cleanup()

    def test_conflicting_reenqueue_is_rejected(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        queue.enqueue("A", "1", ("1", "2"))

        with self.assertRaises(ValueError):
            queue.enqueue("A", "2", ("2", "1"))
        with self.assertRaises(ValueError):
            queue.enqueue("A", "1", ("1", "3"))
        database.close()
        temporary.cleanup()

    def test_only_one_worker_can_claim_pending_repair(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        repair_id = queue.enqueue("A", "1", ("1", "2"))

        self.assertTrue(queue.mark_running(repair_id))
        self.assertFalse(queue.mark_running(repair_id))
        self.assertEqual(queue.pending()[0].attempt_count, 1)
        database.close()
        temporary.cleanup()

    def test_failure_reason_survives_and_next_claim_increments_attempt(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        repair_id = queue.enqueue("A", "1", ("1", "2"))

        self.assertTrue(queue.mark_running(repair_id))
        queue.mark_pending(repair_id, "R2 inventory listing failed")
        failed = queue.pending()[0]
        self.assertEqual(failed.status, "retry")
        self.assertEqual(failed.attempt_count, 1)
        self.assertEqual(failed.last_error, "R2 inventory listing failed")

        self.assertTrue(queue.mark_running(repair_id))
        claimed = queue.pending()[0]
        self.assertEqual(claimed.status, "running")
        self.assertEqual(claimed.attempt_count, 2)
        self.assertIsNone(claimed.last_error)
        database.close()
        temporary.cleanup()

    def test_completed_job_allows_a_new_future_job_for_same_deleted_key(self):
        temporary, database = self.make_database()
        queue = FamilyRepairQueue(database)
        first = queue.enqueue("A", "1", ("1", "2"))
        queue.complete(first)
        second = queue.enqueue("A", "1", ("1", "2"))

        self.assertNotEqual(second, first)
        self.assertEqual([job.repair_id for job in queue.pending()], [second])
        database.close()
        temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
