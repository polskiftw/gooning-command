from __future__ import annotations

import unittest
from unittest.mock import patch

from deduper.certified_group_admission import (
    admit_closed_frontier_group,
    preview_projection,
)
from deduper.certified_queue import CertifiedQueue
from deduper.frontier_worker import FrontierResult
from deduper.group_closure import ClosedGroup


class CertifiedGroupAdmissionTests(unittest.TestCase):
    def test_unfinished_frontier_never_enters_preview(self) -> None:
        queue = CertifiedQueue()
        result = FrontierResult(
            seed_key="A",
            slider=80,
            members=("A", "B"),
            compared_assets=10,
            edges_written=1,
            group=None,
        )

        admitted = admit_closed_frontier_group(queue, object(), (), result)

        self.assertFalse(admitted.admitted)
        self.assertEqual(admitted.family_count, 0)
        self.assertEqual(admitted.pair_count, 0)

    @patch("deduper.certified_group_admission.ready_pairs_for_slider")
    def test_whole_closed_family_enters_as_one_immutable_unit(self, ready_pairs) -> None:
        ready_pairs.return_value = [
            ("A", "B", 91.0, "first"),
            ("A", "C", 87.0, "second"),
            ("X", "Y", 40.0, "unrelated"),
        ]
        queue = CertifiedQueue()
        group = ClosedGroup("family-abc", 80, ("A", "B", "C"))
        result = FrontierResult("A", 80, group.members, 30, 2, group)

        admitted = admit_closed_frontier_group(queue, object(), (), result)

        self.assertTrue(admitted.admitted)
        self.assertEqual(admitted.family_count, 1)
        self.assertEqual(admitted.pair_count, 2)
        self.assertEqual(
            preview_projection(queue),
            [
                ("A", "C", 87.0, "second"),
                ("A", "B", 91.0, "first"),
            ],
        )

    @patch("deduper.certified_group_admission.ready_pairs_for_slider")
    def test_identical_repeat_is_harmless_but_family_change_is_rejected(self, ready_pairs) -> None:
        ready_pairs.return_value = [("A", "B", 90.0, "same")]
        queue = CertifiedQueue()
        group = ClosedGroup("family-ab", 80, ("A", "B"))
        result = FrontierResult("A", 80, group.members, 20, 1, group)

        first = admit_closed_frontier_group(queue, object(), (), result)
        second = admit_closed_frontier_group(queue, object(), (), result)

        self.assertTrue(first.admitted)
        self.assertFalse(second.admitted)
        ready_pairs.return_value = [("B", "A", 90.0, "changed orientation")]
        with self.assertRaisesRegex(ValueError, "cannot change"):
            admit_closed_frontier_group(queue, object(), (), result)

    @patch("deduper.certified_group_admission.ready_pairs_for_slider")
    def test_closed_family_without_actionable_pairs_fails_closed(self, ready_pairs) -> None:
        ready_pairs.return_value = [("X", "Y", 99.0, "unrelated")]
        queue = CertifiedQueue()
        group = ClosedGroup("family-ab", 80, ("A", "B"))
        result = FrontierResult("A", 80, group.members, 20, 1, group)

        with self.assertRaisesRegex(ValueError, "no actionable preview pairs"):
            admit_closed_frontier_group(queue, object(), (), result)
        self.assertEqual(queue.family_count(), 0)


if __name__ == "__main__":
    unittest.main()
