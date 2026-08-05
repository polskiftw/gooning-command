from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.evidence_qualification import mark_edges_qualified
from deduper.evidence_store import EvidenceEdge, EvidenceStore, InventoryRecord
from deduper.evidence_sync import reconcile_inventory
from deduper.focused_matcher import acquire_focused_pairs
from deduper.focused_recertification import recertify_added_or_changed_assets
from deduper.group_closure import mark_frontier_complete, ready_group_members, certify_closed_groups
from deduper.models import Asset


class FocusedRecertificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    @staticmethod
    def asset(key: str, phash: str) -> Asset:
        return Asset(key, 100, key, "1", "image", "jpg", phash=phash)

    def test_focused_matcher_emits_only_pairs_touching_focus(self) -> None:
        assets = [
            self.asset("a", "0000000000000000"),
            self.asset("b", "0000000000000001"),
            self.asset("c", "0000000000000002"),
        ]
        pairs = acquire_focused_pairs(assets, {"c"}, 99)
        keys = {tuple(sorted((left, right))) for left, right, _, _ in pairs}
        self.assertIn(("a", "c"), keys)
        self.assertIn(("b", "c"), keys)
        self.assertNotIn(("a", "b"), keys)

    def test_added_asset_extends_old_certification_without_resetting_boundary(self) -> None:
        old_records = [
            InventoryRecord("a", 100, "a", "1"),
            InventoryRecord("b", 100, "b", "1"),
        ]
        old_fingerprint = self.store.replace_inventory_snapshot(old_records)
        edge = EvidenceEdge("a", "b", phash_distance=1, evidence_mask=1)
        self.store.upsert_edges([edge])
        mark_edges_qualified(self.store, [edge], 99)
        mark_frontier_complete(self.store, ["a", "b"], 99)
        certify_closed_groups(self.store, 99)
        self.store.mark_range_complete(99)

        new_records = old_records + [InventoryRecord("c", 100, "c", "1")]
        sync = reconcile_inventory(self.store, new_records)
        assets = [
            self.asset("a", "0000000000000000"),
            self.asset("b", "0000000000000001"),
            self.asset("c", "0000000000000002"),
        ]
        result = recertify_added_or_changed_assets(
            self.store,
            assets,
            {"c"},
            old_fingerprint=old_fingerprint,
            old_boundary=99,
            new_fingerprint=sync.fingerprint,
        )

        self.assertIsNotNone(result)
        self.assertEqual(self.store.loosest_complete_slider(), 99)
        self.assertEqual(ready_group_members(self.store, 99), {"a", "b", "c"})

    def test_changed_asset_does_not_reuse_old_frontier_coverage(self) -> None:
        old_records = [
            InventoryRecord("a", 100, "a", "1"),
            InventoryRecord("b", 100, "b", "1"),
        ]
        old_fingerprint = self.store.replace_inventory_snapshot(old_records)
        mark_frontier_complete(self.store, ["a", "b"], 99)
        self.store.mark_range_complete(99)

        changed = [
            InventoryRecord("a", 101, "a2", "2"),
            InventoryRecord("b", 100, "b", "1"),
        ]
        sync = reconcile_inventory(self.store, changed)
        assets = [
            self.asset("a", "ffffffffffffffff"),
            self.asset("b", "0000000000000000"),
        ]
        result = recertify_added_or_changed_assets(
            self.store,
            assets,
            {"a"},
            old_fingerprint=old_fingerprint,
            old_boundary=99,
            new_fingerprint=sync.fingerprint,
        )
        self.assertIsNotNone(result)
        row = self.store.connection.execute(
            "SELECT inventory_fingerprint FROM asset_frontier_coverage WHERE asset_key = 'a' AND slider = 99"
        ).fetchone()
        self.assertEqual(str(row["inventory_fingerprint"]), sync.fingerprint)


if __name__ == "__main__":
    unittest.main()
