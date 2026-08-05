from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.cache_view import cached_pairs_for_slider
from deduper.evidence_qualification import mark_edges_qualified
from deduper.evidence_store import EvidenceEdge, EvidenceStore
from deduper.models import Asset


def asset(key: str, size: int, width: int = 100, height: int = 100) -> Asset:
    return Asset(
        key=key,
        size=size,
        etag="",
        last_modified="",
        media_type="image",
        extension="jpg",
        width=width,
        height=height,
    )


class CacheViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")
        self.assets = [asset("a.jpg", 100), asset("b.jpg", 200)]

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_edge_appears_only_at_or_below_first_qualified_slider(self) -> None:
        edge = EvidenceEdge("a.jpg", "b.jpg", phash_distance=8, evidence_mask=1)
        self.store.upsert_edges([edge])
        mark_edges_qualified(self.store, [edge], 80)
        self.store.mark_range_complete(70)

        self.assertEqual(cached_pairs_for_slider(self.store, self.assets, 90), [])
        pairs = cached_pairs_for_slider(self.store, self.assets, 80)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], "b.jpg")
        self.assertEqual(pairs[0][1], "a.jpg")
        self.assertEqual(len(cached_pairs_for_slider(self.store, self.assets, 70)), 1)

    def test_unqualified_legacy_observation_is_hidden(self) -> None:
        self.store.upsert_edges(
            [EvidenceEdge("a.jpg", "b.jpg", phash_distance=1, evidence_mask=1)]
        )
        self.store.mark_range_complete(99)
        self.assertEqual(cached_pairs_for_slider(self.store, self.assets, 99), [])

    def test_uncertified_looser_slider_is_rejected(self) -> None:
        self.store.mark_range_complete(80)
        with self.assertRaisesRegex(ValueError, "not certified"):
            cached_pairs_for_slider(self.store, self.assets, 79)

    def test_strictest_qualification_is_preserved(self) -> None:
        edge = EvidenceEdge("a.jpg", "b.jpg", pdq_distance=20, evidence_mask=2)
        self.store.upsert_edges([edge])
        mark_edges_qualified(self.store, [edge], 75)
        mark_edges_qualified(self.store, [edge], 40)
        row = self.store.connection.execute(
            "SELECT first_qualified_slider FROM edge_qualification"
        ).fetchone()
        self.assertEqual(row["first_qualified_slider"], 75)


if __name__ == "__main__":
    unittest.main()
