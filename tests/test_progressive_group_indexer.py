from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deduper.evidence_store import EvidenceEdge, EvidenceStore, InventoryRecord
from deduper.group_scheduler import GroupScheduleResult
from deduper.models import Asset
from deduper.progressive_group_indexer import run_progressive_group_index
from deduper.progressive_indexer import IndexBand


def asset(key: str) -> Asset:
    return Asset(
        key=key,
        size=1,
        etag=key,
        last_modified="now",
        media_type="image",
        extension="jpg",
        phash="0" * 16,
    )


class ProgressiveGroupIndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")
        self.store.replace_inventory_snapshot(
            [InventoryRecord("a", 1, "a"), InventoryRecord("b", 1, "b")]
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_controller_uses_internal_band_and_not_ui_slider(self) -> None:
        band = IndexBand(99, 97, (("phash", 4),))
        edge = EvidenceEdge("a", "b", phash_distance=1, evidence_mask=1)
        schedule_result = GroupScheduleResult(
            slider=97,
            groups_completed=1,
            assets_completed=2,
            comparisons=2,
            edges_written=1,
        )

        with (
            patch("deduper.progressive_group_indexer.pending_bands", return_value=iter([band])),
            patch(
                "deduper.progressive_group_indexer.scan_index_band",
                return_value=[edge],
            ) as scan_band,
            patch(
                "deduper.progressive_group_indexer.run_group_seed_schedule",
                return_value=schedule_result,
            ) as schedule,
        ):
            results = run_progressive_group_index(
                self.store,
                [asset("a"), asset("b")],
                compare_workers=7,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].band, band)
        self.assertEqual(self.store.loosest_complete_slider(), 97)
        scan_band.assert_called_once()
        called_band = scan_band.call_args.args[1]
        self.assertEqual(called_band.strictest_slider, 99)
        self.assertEqual(called_band.loosest_slider, 97)
        self.assertEqual(scan_band.call_args.kwargs["compare_workers"], 7)
        self.assertEqual(schedule.call_args.args[2], 97)
        self.assertEqual(self.store.get_state("scan_mode"), "progressive_group_bands")


if __name__ == "__main__":
    unittest.main()
