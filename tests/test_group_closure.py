from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.evidence_qualification import mark_edges_qualified
from deduper.evidence_store import EvidenceEdge, EvidenceStore, InventoryRecord
from deduper.group_closure import (
    certify_closed_groups,
    invalidate_closure_for_assets,
    mark_frontier_complete,
    ready_group_members,
)


class GroupClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")
        self.store.replace_inventory_snapshot(
            [
                InventoryRecord("a", 1, "a1"),
                InventoryRecord("b", 1, "b1"),
                InventoryRecord("c", 1, "c1"),
                InventoryRecord("d", 1, "d1"),
            ]
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def add_edge(self, left: str, right: str, first_slider: int = 95) -> None:
        edge = EvidenceEdge(left, right, phash_distance=1, evidence_mask=1)
        self.store.upsert_edges([edge])
        mark_edges_qualified(self.store, [edge], first_slider)

    def test_partial_component_is_not_ready(self) -> None:
        self.add_edge("a", "b")
        mark_frontier_complete(self.store, ["a"], 95)
        self.assertEqual(certify_closed_groups(self.store, 95), [])
        self.assertEqual(ready_group_members(self.store, 95), set())

    def test_complete_component_becomes_ready(self) -> None:
        self.add_edge("a", "b")
        mark_frontier_complete(self.store, ["a", "b"], 95)
        groups = certify_closed_groups(self.store, 95)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].members, ("a", "b"))
        self.assertEqual(ready_group_members(self.store, 95), {"a", "b"})

    def test_component_expansion_requires_new_member_coverage(self) -> None:
        self.add_edge("a", "b")
        mark_frontier_complete(self.store, ["a", "b"], 95)
        self.assertEqual(len(certify_closed_groups(self.store, 95)), 1)

        self.add_edge("b", "c")
        self.assertEqual(certify_closed_groups(self.store, 95), [])
        mark_frontier_complete(self.store, ["c"], 95)
        groups = certify_closed_groups(self.store, 95)
        self.assertEqual(groups[0].members, ("a", "b", "c"))

    def test_inventory_change_invalidates_old_coverage(self) -> None:
        self.add_edge("a", "b")
        mark_frontier_complete(self.store, ["a", "b"], 95)
        self.assertEqual(len(certify_closed_groups(self.store, 95)), 1)

        self.store.replace_inventory_snapshot(
            [
                InventoryRecord("a", 1, "a2"),
                InventoryRecord("b", 1, "b1"),
                InventoryRecord("c", 1, "c1"),
                InventoryRecord("d", 1, "d1"),
            ]
        )
        self.assertEqual(certify_closed_groups(self.store, 95), [])
        self.assertEqual(ready_group_members(self.store, 95), set())

    def test_asset_invalidation_removes_ready_group(self) -> None:
        self.add_edge("a", "b")
        mark_frontier_complete(self.store, ["a", "b"], 95)
        certify_closed_groups(self.store, 95)
        invalidate_closure_for_assets(self.store, ["a"])
        self.assertEqual(ready_group_members(self.store, 95), set())


if __name__ == "__main__":
    unittest.main()
