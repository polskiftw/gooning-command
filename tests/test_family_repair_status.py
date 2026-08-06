from __future__ import annotations

import unittest

from deduper.family_repair_queue import PendingFamilyRepair
from deduper.family_repair_status import family_repair_status_text


class FamilyRepairStatusTests(unittest.TestCase):
    def job(self, status: str, attempts: int, error: str | None = None):
        return PendingFamilyRepair(
            repair_id=7,
            deleted_key="A",
            protected_key="1",
            priority_keys=("1", "2"),
            status=status,
            attempt_count=attempts,
            last_error=error,
        )

    def test_pending_status_names_deleted_and_protected_objects(self):
        text = family_repair_status_text(self.job("pending", 0))
        self.assertIn("deleted A", text)
        self.assertIn("protected partner 1", text)
        self.assertIn("safe in R2", text)
        self.assertIn("hidden from review", text)

    def test_running_status_is_literal(self):
        text = family_repair_status_text(self.job("running", 1))
        self.assertIn("Family repair running", text)
        self.assertIn("1 attempt", text)
        self.assertNotIn("automatic retry", text)

    def test_retry_status_includes_attempts_and_saved_failure(self):
        text = family_repair_status_text(self.job("retry", 2, "network timeout"))
        self.assertIn("automatic retry", text)
        self.assertIn("2 attempts", text)
        self.assertIn("network timeout", text)
        self.assertIn("safe in R2", text)


if __name__ == "__main__":
    unittest.main()
