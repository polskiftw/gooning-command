from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.evidence_qualification import mark_edges_qualified
from deduper.evidence_store import EvidenceEdge, EvidenceStore, InventoryRecord
from deduper.evidence_sync import inventory_delta, reconcile_inventory
from deduper.group_closure import certify_closed_groups, mark_frontier_complete, ready_group_members


class EvidenceSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_delta_distinguishes_added_changed_removed_and_unchanged(self) -> None:
        previous = [
            InventoryRecord("a", 1, "a", "1"),
            InventoryRecord("b", 2, "b", "2"),
            InventoryRecord("c", 3, "c", "3"),
        ]
        current = [
            InventoryRecord("a", 1, "a", "1"),
            InventoryRecord("b", 20, "b2", "20"),
            InventoryRecord("d", 4, "d", "4"),
        ]
        delta = inventory_delta(previous, current)
        self.assertEqual(delta.unchanged, frozenset({"a"}))
        self.assertEqual(delta.changed, frozenset({"b"}))
        self.assertEqual(delta.removed, frozenset({"c"}))
        self.assertEqual(delta.added, frozenset({"d"}))

    def test_unchanged_inventory_keeps_completed_boundary(self) -> None:
        records = [InventoryRecord("a", 1, "a", "1")]
        self.store.replace_inventory_snapshot(records)
        self.store.mark_range_complete(70)
        result = reconcile_inventory(self.store, records)
        self.assertTrue(result.cache_was_current)
        self.assertFalse(result.delta.has_changes)
        self.assertEqual(self.store.loosest_complete_slider(), 70)

    def test_changed_asset_invalidates_only_edges_touching_it(self) -> None:
        original = [
            InventoryRecord("a", 1, "a", "1"),
            InventoryRecord("b", 2, "b", "2"),
            InventoryRecord("c", 3, "c", "3"),
        ]
        self.store.replace_inventory_snapshot(original)
        self.store.upsert_edges(
            [
                EvidenceEdge("a", "b", phash_distance=1),
                EvidenceEdge("b", "c", phash_distance=2),
            ]
        )
        self.store.mark_range_complete(50)

        current = [
            InventoryRecord("a", 10, "new", "10"),
            InventoryRecord("b", 2, "b", "2"),
            InventoryRecord("c", 3, "c", "3"),
        ]
        result = reconcile_inventory(self.store, current)

        self.assertEqual(result.delta.changed, frozenset({"a"}))
        rows = self.store.connection.execute(
            "SELECT left_key, right_key FROM comparison_edges ORDER BY left_key, right_key"
        ).fetchall()
        self.assertEqual([(row["left_key"], row["right_key"]) for row in rows], [("b", "c")])
        self.assertIsNone(self.store.loosest_complete_slider())
        self.assertEqual(self.store.get_state("build_status"), "dirty")

    def test_same_count_replacement_is_not_treated_as_current(self) -> None:
        original = [InventoryRecord("a", 1), InventoryRecord("b", 2)]
        replacement = [InventoryRecord("a", 1), InventoryRecord("c", 2)]
        self.store.replace_inventory_snapshot(original)
        result = reconcile_inventory(self.store, replacement)
        self.assertFalse(result.cache_was_current)
        self.assertEqual(result.delta.removed, frozenset({"b"}))
        self.assertEqual(result.delta.added, frozenset({"c"}))

    def test_removal_only_preserves_boundary_and_unaffected_ready_group(self) -> None:
        original = [
            InventoryRecord("a", 1),
            InventoryRecord("b", 2),
            InventoryRecord("c", 3),
        ]
        self.store.replace_inventory_snapshot(original)
        edge = EvidenceEdge("a", "b", phash_distance=1, evidence_mask=1)
        self.store.upsert_edges([edge])
        mark_edges_qualified(self.store, [edge], 95)
        mark_frontier_complete(self.store, ["a", "b"], 95)
        certify_closed_groups(self.store, 95)
        self.store.mark_range_complete(95)

        result = reconcile_inventory(
            self.store,
            [InventoryRecord("a", 1), InventoryRecord("b", 2)],
        )

        self.assertTrue(result.delta.is_removal_only)
        self.assertTrue(result.reused_complete_boundary)
        self.assertEqual(self.store.loosest_complete_slider(), 95)
        self.assertEqual(ready_group_members(self.store, 95), {"a", "b"})

    def test_addition_does_not_reuse_old_boundary(self) -> None:
        original = [InventoryRecord("a", 1), InventoryRecord("b", 2)]
        self.store.replace_inventory_snapshot(original)
        self.store.mark_range_complete(80)

        result = reconcile_inventory(
            self.store,
            original + [InventoryRecord("c", 3)],
        )

        self.assertFalse(result.reused_complete_boundary)
        self.assertIsNone(self.store.loosest_complete_slider())


if __name__ == "__main__":
    unittest.main()
