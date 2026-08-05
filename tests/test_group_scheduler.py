from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.evidence_qualification import mark_edges_qualified
from deduper.evidence_store import EvidenceEdge, EvidenceStore, InventoryRecord
from deduper.frontier_worker import FrontierCancelled
from deduper.group_scheduler import run_group_seed_schedule
from deduper.models import Asset


def asset(key: str, phash: str) -> Asset:
    return Asset(
        key=key,
        size=1,
        etag=key,
        last_modified="now",
        media_type="image",
        extension="jpg",
        sha256=key,
        phash=phash,
        width=100,
        height=100,
    )


class GroupSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")
        self.assets = [
            asset("a", "0000000000000000"),
            asset("b", "0000000000000001"),
            asset("c", "ffffffffffffffff"),
            asset("d", "fffffffffffffffe"),
        ]
        self.store.replace_inventory_snapshot(
            [InventoryRecord(item.key, item.size, item.etag) for item in self.assets]
        )
        seeds = [
            EvidenceEdge("a", "b", phash_distance=1, evidence_mask=1),
            EvidenceEdge("c", "d", phash_distance=1, evidence_mask=1),
        ]
        self.store.upsert_edges(seeds)
        mark_edges_qualified(self.store, seeds, 99)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_schedule_closes_each_seed_component_once(self) -> None:
        seen: list[tuple[str, ...]] = []
        result = run_group_seed_schedule(
            self.store,
            self.assets,
            99,
            progress=lambda item, _total: seen.append(item.members),
        )
        self.assertEqual(result.groups_completed, 2)
        self.assertEqual({frozenset(group) for group in seen}, {frozenset(("a", "b")), frozenset(("c", "d"))})

    def test_resume_skips_already_covered_component(self) -> None:
        first_seen: list[str] = []
        run_group_seed_schedule(
            self.store,
            self.assets,
            99,
            progress=lambda item, _total: first_seen.append(item.seed_key),
        )
        second_seen: list[str] = []
        result = run_group_seed_schedule(
            self.store,
            self.assets,
            99,
            progress=lambda item, _total: second_seen.append(item.seed_key),
        )
        self.assertEqual(result.groups_completed, 0)
        self.assertEqual(second_seen, [])

    def test_cancelled_schedule_keeps_completed_group_and_resumes(self) -> None:
        cancelled = False

        def progress(_item, _total) -> None:
            nonlocal cancelled
            cancelled = True

        with self.assertRaises(FrontierCancelled):
            run_group_seed_schedule(
                self.store,
                self.assets,
                99,
                cancelled=lambda: cancelled,
                progress=progress,
            )
        resumed = run_group_seed_schedule(self.store, self.assets, 99)
        self.assertEqual(resumed.groups_completed, 1)


if __name__ == "__main__":
    unittest.main()
