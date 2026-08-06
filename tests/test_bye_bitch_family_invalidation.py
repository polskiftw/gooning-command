from __future__ import annotations

import unittest

from deduper.certified_queue import CertifiedFamily, CertifiedQueue
from deduper.generation_builder import CertifiedPairRow


def row(group: str, left: str, right: str, score: float) -> CertifiedPairRow:
    return CertifiedPairRow(group, left, right, score, "test")


class ByeBitchFamilyInvalidationTests(unittest.TestCase):
    def make_queue(self) -> CertifiedQueue:
        queue = CertifiedQueue()
        queue.admit_family(
            CertifiedFamily(
                "family-1",
                ("A", "1", "2", "3"),
                (
                    row("family-1", "A", "1", 72),
                    row("family-1", "A", "2", 81),
                    row("family-1", "A", "3", 94),
                ),
            )
        )
        queue.admit_family(
            CertifiedFamily(
                "unrelated",
                ("B", "9"),
                (row("unrelated", "B", "9", 88),),
            )
        )
        return queue

    def test_deleting_letter_removes_every_letter_number_row(self):
        queue = self.make_queue()

        result = queue.invalidate_for_deletion("A", "1")

        self.assertEqual(result.deleted_key, "A")
        self.assertEqual(result.protected_key, "1")
        self.assertEqual(result.recertify_keys, ("1", "2", "3"))
        self.assertEqual(
            [(pair.survivor_key, pair.deletion_key) for pair in queue.pairs()],
            [("B", "9")],
        )
        self.assertIsNone(queue.family_for_asset("A"))
        self.assertIsNone(queue.family_for_asset("2"))

    def test_deleting_number_removes_every_row_from_same_family(self):
        queue = self.make_queue()

        result = queue.invalidate_for_deletion("2", "A")

        self.assertEqual(result.recertify_keys, ("A", "1", "3"))
        self.assertEqual(
            [(pair.survivor_key, pair.deletion_key) for pair in queue.pairs()],
            [("B", "9")],
        )

    def test_unrelated_certified_family_remains_actionable(self):
        queue = self.make_queue()
        queue.invalidate_for_deletion("A", "1")

        family = queue.family_for_pair("B", "9")

        self.assertIsNotNone(family)
        self.assertEqual(family.group_id, "unrelated")

    def test_protected_member_must_be_from_clicked_family(self):
        queue = self.make_queue()

        with self.assertRaisesRegex(ValueError, "same certified family"):
            queue.invalidate_for_deletion("A", "9")


if __name__ == "__main__":
    unittest.main()
