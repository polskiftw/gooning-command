from __future__ import annotations

import unittest

from deduper.models import Pair
from deduper.review_ui import pair_identity, preserved_pair_index


def pair(identifier: int, left: str, right: str) -> Pair:
    return Pair(identifier, left, right, 90.0, "test", "included", None)


class ReviewUiTests(unittest.TestCase):
    def test_pair_identity_is_orientation_independent(self) -> None:
        self.assertEqual(pair_identity("a", "b"), pair_identity("b", "a"))

    def test_exact_visible_pair_survives_insertions_and_new_row_ids(self) -> None:
        refreshed = [
            pair(100, "new-left", "new-right"),
            pair(101, "a", "b"),
            pair(102, "c", "d"),
        ]
        self.assertEqual(preserved_pair_index(refreshed, "a", "b", 0), 1)

    def test_reoriented_logical_pair_is_preserved(self) -> None:
        refreshed = [pair(100, "c", "d"), pair(101, "b", "a")]
        self.assertEqual(preserved_pair_index(refreshed, "a", "b", 0), 1)

    def test_removed_visible_pair_clamps_old_position(self) -> None:
        refreshed = [pair(100, "a", "b"), pair(101, "c", "d")]
        self.assertEqual(preserved_pair_index(refreshed, "gone", "pair", 8), 1)

    def test_empty_queue_returns_zero(self) -> None:
        self.assertEqual(preserved_pair_index([], "a", "b", 4), 0)


if __name__ == "__main__":
    unittest.main()
