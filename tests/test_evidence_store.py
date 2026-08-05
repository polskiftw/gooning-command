from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.evidence_store import (
    EvidenceEdge,
    EvidenceStore,
    InventoryRecord,
    inventory_fingerprint,
)


class EvidenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_inventory_fingerprint_is_order_independent(self) -> None:
        left = [
            InventoryRecord("gallery/a.jpg", 10, "a", "1"),
            InventoryRecord("gallery/b.jpg", 20, "b", "2"),
        ]
        right = list(reversed(left))
        self.assertEqual(inventory_fingerprint(left), inventory_fingerprint(right))

    def test_inventory_fingerprint_detects_same_count_replacement(self) -> None:
        original = [
            InventoryRecord("gallery/a.jpg", 10),
            InventoryRecord("gallery/b.jpg", 20),
        ]
        replacement = [
            InventoryRecord("gallery/a.jpg", 10),
            InventoryRecord("gallery/c.jpg", 20),
        ]
        self.assertNotEqual(
            inventory_fingerprint(original),
            inventory_fingerprint(replacement),
        )

    def test_snapshot_round_trip(self) -> None:
        records = [InventoryRecord("gallery/a.jpg", 10, "etag", "date")]
        fingerprint = self.store.replace_inventory_snapshot(records)
        self.assertEqual(self.store.inventory_count(), 1)
        self.assertTrue(self.store.inventory_matches(records))
        self.assertEqual(
            self.store.get_state("inventory_fingerprint"),
            fingerprint,
        )

    def test_edges_are_normalized_and_merged(self) -> None:
        self.store.upsert_edges(
            [
                EvidenceEdge(
                    "gallery/z.jpg",
                    "gallery/a.jpg",
                    phash_distance=8,
                    vpdq_left_similarity=0.25,
                    vpdq_right_similarity=0.75,
                    evidence_mask=1,
                )
            ]
        )
        self.store.upsert_edges(
            [
                EvidenceEdge(
                    "gallery/a.jpg",
                    "gallery/z.jpg",
                    pdq_distance=22,
                    evidence_mask=2,
                )
            ]
        )
        row = self.store.connection.execute(
            "SELECT * FROM comparison_edges"
        ).fetchone()
        self.assertEqual(row["left_key"], "gallery/a.jpg")
        self.assertEqual(row["right_key"], "gallery/z.jpg")
        self.assertEqual(row["phash_distance"], 8)
        self.assertEqual(row["pdq_distance"], 22)
        self.assertEqual(row["vpdq_left_similarity"], 0.75)
        self.assertEqual(row["vpdq_right_similarity"], 0.25)
        self.assertEqual(row["evidence_mask"], 3)

    def test_completed_boundary_only_moves_toward_loose(self) -> None:
        self.assertIsNone(self.store.loosest_complete_slider())
        self.store.mark_range_complete(99)
        self.store.mark_range_complete(80)
        self.store.mark_range_complete(90)
        self.assertEqual(self.store.loosest_complete_slider(), 80)

    def test_remove_asset_invalidates_its_edges(self) -> None:
        self.store.upsert_edges(
            [EvidenceEdge("gallery/a.jpg", "gallery/b.jpg", phash_distance=1)]
        )
        self.store.remove_asset("gallery/a.jpg")
        self.assertEqual(self.store.edge_count(), 0)
        self.assertEqual(self.store.get_state("build_status"), "dirty")


if __name__ == "__main__":
    unittest.main()
