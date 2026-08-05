from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.evidence_inventory import reconcile_asset_inventory
from deduper.evidence_store import EvidenceStore
from deduper.frontier_worker import FrontierCancelled, qualifying_edge, scan_closed_group
from deduper.group_closure import ready_group_members
from deduper.models import Asset


def asset(key: str, phash: str) -> Asset:
    return Asset(
        key=key,
        size=100,
        etag=key,
        last_modified="2026-08-05",
        media_type="image",
        extension="jpg",
        sha256=key * 8,
        phash=phash,
        width=100,
        height=100,
    )


class FrontierWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_pair_qualification_respects_slider(self) -> None:
        left = asset("a", "0000000000000000")
        right = asset("b", "0000000000000fff")  # 12-bit distance
        self.assertIsNone(qualifying_edge(left, right, 99))
        self.assertIsNotNone(qualifying_edge(left, right, 0))

    def test_worker_expands_chain_and_certifies_only_closed_component(self) -> None:
        # A-B distance 4, B-C distance 4, A-C distance 8. At strict slider 99,
        # all remain in one connected component through B. D is unrelated.
        assets = [
            asset("a", "0000000000000000"),
            asset("b", "000000000000000f"),
            asset("c", "00000000000000ff"),
            asset("d", "ffffffffffffffff"),
        ]
        reconcile_asset_inventory(self.store, assets)
        result = scan_closed_group(self.store, assets, "a", 99)
        self.assertEqual(result.members, ("a", "b", "c"))
        self.assertIsNotNone(result.group)
        self.assertEqual(set(result.group.members), {"a", "b", "c"})
        self.assertEqual(ready_group_members(self.store, 99), {"a", "b", "c"})

    def test_cancellation_never_certifies_active_member(self) -> None:
        assets = [
            asset("a", "0000000000000000"),
            asset("b", "000000000000000f"),
            asset("c", "ffffffffffffffff"),
        ]
        reconcile_asset_inventory(self.store, assets)
        calls = 0

        def cancelled() -> bool:
            return calls >= 1

        def progress(_key: str, _done: int, _total: int) -> None:
            nonlocal calls
            calls += 1

        with self.assertRaises(FrontierCancelled):
            scan_closed_group(
                self.store,
                assets,
                "a",
                99,
                cancelled=cancelled,
                progress=progress,
            )
        self.assertEqual(ready_group_members(self.store, 99), set())

    def test_group_can_be_ready_before_whole_band_boundary(self) -> None:
        assets = [
            asset("a", "0000000000000000"),
            asset("b", "000000000000000f"),
        ]
        reconcile_asset_inventory(self.store, assets)
        self.assertIsNone(self.store.loosest_complete_slider())
        result = scan_closed_group(self.store, assets, "a", 99)
        self.assertIsNotNone(result.group)
        self.assertIsNone(self.store.loosest_complete_slider())


if __name__ == "__main__":
    unittest.main()
