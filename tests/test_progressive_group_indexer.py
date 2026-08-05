from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deduper.band_scanner import BandSeedStage
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


def schedule_result(slider: int, groups: int = 0) -> GroupScheduleResult:
    return GroupScheduleResult(
        slider=slider,
        groups_completed=groups,
        assets_completed=2 if groups else 0,
        comparisons=2 if groups else 0,
        edges_written=1 if groups else 0,
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
        stages = iter(
            [
                BandSeedStage("phash", (edge,), False),
                BandSeedStage("complete", (edge,), True),
            ]
        )

        with (
            patch("deduper.progressive_group_indexer.pending_bands", return_value=iter([band])),
            patch(
                "deduper.progressive_group_indexer.stream_index_band_stages",
                return_value=stages,
            ) as stream_band,
            patch(
                "deduper.progressive_group_indexer.run_group_seed_schedule",
                side_effect=[schedule_result(97, 1), schedule_result(97)],
            ) as schedule,
        ):
            results = run_progressive_group_index(
                self.store,
                [asset("a"), asset("b")],
                compare_workers=7,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].band, band)
        self.assertEqual(results[0].group_result.groups_completed, 1)
        self.assertEqual(self.store.loosest_complete_slider(), 97)
        stream_band.assert_called_once()
        called_band = stream_band.call_args.args[1]
        self.assertEqual(called_band.strictest_slider, 99)
        self.assertEqual(called_band.loosest_slider, 97)
        self.assertEqual(stream_band.call_args.kwargs["compare_workers"], 7)
        self.assertEqual(schedule.call_count, 2)
        self.assertTrue(all(call.args[2] == 97 for call in schedule.call_args_list))
        self.assertEqual(
            self.store.get_state("scan_mode"),
            "streaming_progressive_group_bands",
        )

    def test_early_stage_closes_groups_before_band_boundary_unlocks(self) -> None:
        band = IndexBand(99, 97, (("phash", 4),))
        edge = EvidenceEdge("a", "b", phash_distance=1, evidence_mask=1)
        observed_boundaries: list[int | None] = []
        observed_stages: list[str] = []

        def stages(*_args, **_kwargs):
            yield BandSeedStage("phash", (edge,), False)
            yield BandSeedStage("complete", (edge,), True)

        def on_stage(_band: IndexBand, name: str, _edge_count: int) -> None:
            observed_stages.append(name)
            observed_boundaries.append(self.store.loosest_complete_slider())

        with (
            patch("deduper.progressive_group_indexer.pending_bands", return_value=iter([band])),
            patch(
                "deduper.progressive_group_indexer.stream_index_band_stages",
                side_effect=stages,
            ),
            patch(
                "deduper.progressive_group_indexer.run_group_seed_schedule",
                side_effect=[schedule_result(97, 1), schedule_result(97)],
            ),
        ):
            run_progressive_group_index(
                self.store,
                [asset("a"), asset("b")],
                stage_progress=on_stage,
            )

        self.assertEqual(observed_stages, ["phash", "complete"])
        self.assertEqual(observed_boundaries, [None, None])
        self.assertEqual(self.store.loosest_complete_slider(), 97)


if __name__ == "__main__":
    unittest.main()
