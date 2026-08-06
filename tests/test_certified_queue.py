from __future__ import annotations

import unittest

from deduper.certified_queue import CertifiedFamily, CertifiedQueue
from deduper.generation_builder import CertifiedPairRow, ShaDeletionRow


def family(group_id: str, survivor: str, deletions: list[tuple[str, float]]) -> CertifiedFamily:
    members = tuple([survivor, *[key for key, _ in deletions]])
    pairs = tuple(
        CertifiedPairRow(group_id, survivor, deletion, similarity, "certified")
        for deletion, similarity in deletions
    )
    return CertifiedFamily(group_id, members, pairs)


class CertifiedQueueTests(unittest.TestCase):
    def test_new_families_reorder_queue_lowest_to_highest_without_mutating_pairs(self) -> None:
        queue = CertifiedQueue()
        first = family("g1", "A", [("B", 92.0)])
        queue.admit_family(first)
        self.assertEqual([(row.survivor_key, row.deletion_key) for row in queue.pairs()], [("A", "B")])

        queue.admit_family(family("g2", "C", [("D", 80.0), ("E", 97.0)]))

        self.assertEqual(
            [(row.survivor_key, row.deletion_key, row.similarity) for row in queue.pairs()],
            [("C", "D", 80.0), ("A", "B", 92.0), ("C", "E", 97.0)],
        )
        self.assertEqual(queue.pairs()[1], first.pairs[0])

    def test_identical_family_readmission_is_idempotent(self) -> None:
        queue = CertifiedQueue()
        certified = family("g1", "A", [("B", 92.0)])
        self.assertTrue(queue.admit_family(certified))
        self.assertFalse(queue.admit_family(certified))
        self.assertEqual(queue.family_count(), 1)

    def test_certified_family_cannot_change_after_admission(self) -> None:
        queue = CertifiedQueue()
        queue.admit_family(family("g1", "A", [("B", 92.0)]))

        with self.assertRaisesRegex(ValueError, "cannot change"):
            queue.admit_family(family("g1", "A", [("B", 92.0), ("C", 95.0)]))

    def test_asset_cannot_join_a_second_certified_family(self) -> None:
        queue = CertifiedQueue()
        queue.admit_family(family("g1", "A", [("B", 92.0)]))

        with self.assertRaisesRegex(ValueError, "already certified"):
            queue.admit_family(family("g2", "B", [("C", 90.0)]))

    def test_payload_uses_current_sorted_preview_order(self) -> None:
        queue = CertifiedQueue()
        queue.admit_family(family("g1", "A", [("B", 99.0)]))
        queue.admit_family(family("g2", "C", [("D", 75.0)]))
        queue.admit_sha_deletions((ShaDeletionRow("A", "X"),))

        payload = queue.payload()

        self.assertEqual([row.deletion_key for row in payload.pairs], ["D", "B"])
        self.assertEqual(payload.sha_deletions, (ShaDeletionRow("A", "X"),))

    def test_sha_survivor_cannot_change_after_admission(self) -> None:
        queue = CertifiedQueue()
        queue.admit_sha_deletions((ShaDeletionRow("A", "B"),))

        with self.assertRaisesRegex(ValueError, "cannot change survivor"):
            queue.admit_sha_deletions((ShaDeletionRow("C", "B"),))


if __name__ == "__main__":
    unittest.main()
