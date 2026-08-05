from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.evidence_store import EvidenceEdge, EvidenceStore
from deduper.progressive_indexer import (
    IndexingCancelled,
    index_bands,
    pending_bands,
    run_progressive_index,
)


class ProgressiveIndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_bands_cover_every_slider_once_strict_to_loose(self) -> None:
        bands = index_bands()
        covered: list[int] = []
        for band in bands:
            self.assertGreaterEqual(band.strictest_slider, band.loosest_slider)
            covered.extend(range(band.strictest_slider, band.loosest_slider - 1, -1))
        self.assertEqual(covered, list(range(99, -1, -1)))

    def test_completed_band_is_not_scheduled_again(self) -> None:
        first = index_bands()[0]
        self.store.mark_range_complete(first.loosest_slider)
        remaining = list(pending_bands(self.store))
        self.assertTrue(remaining)
        self.assertLess(remaining[0].strictest_slider, first.loosest_slider)

    def test_boundary_advances_only_after_complete_commit(self) -> None:
        first = index_bands()[0]
        calls = 0

        def scan(_assets, band, _cancelled):
            nonlocal calls
            calls += 1
            self.assertEqual(band, first)
            return [EvidenceEdge("a", "b", phash_distance=1, evidence_mask=1)]

        # Limit this test to one band by pre-marking every looser band complete
        # after the scanner's first invocation via cancellation.
        cancelled = False

        def stop_after_first() -> bool:
            return cancelled

        def progress(_result) -> None:
            nonlocal cancelled
            cancelled = True

        with self.assertRaises(IndexingCancelled):
            run_progressive_index(
                self.store,
                [],
                scan,
                cancelled=stop_after_first,
                progress=progress,
            )
        self.assertEqual(calls, 1)
        self.assertEqual(self.store.loosest_complete_slider(), first.loosest_slider)
        self.assertEqual(self.store.edge_count(), 1)

    def test_cancelled_band_does_not_advance_boundary(self) -> None:
        calls = 0
        cancelled = False

        def scan(_assets, _band, _is_cancelled):
            nonlocal calls, cancelled
            calls += 1
            cancelled = True
            return [EvidenceEdge("a", "b", phash_distance=2, evidence_mask=1)]

        with self.assertRaises(IndexingCancelled):
            run_progressive_index(
                self.store,
                [],
                scan,
                cancelled=lambda: cancelled,
            )
        self.assertEqual(calls, 1)
        self.assertIsNone(self.store.loosest_complete_slider())
        self.assertEqual(self.store.edge_count(), 0)

    def test_resume_starts_after_last_completed_band(self) -> None:
        bands = index_bands()
        first = bands[0]
        self.store.mark_range_complete(first.loosest_slider)
        seen = []
        cancelled = False

        def scan(_assets, band, _is_cancelled):
            nonlocal cancelled
            seen.append(band)
            cancelled = True
            return []

        with self.assertRaises(IndexingCancelled):
            run_progressive_index(
                self.store,
                [],
                scan,
                cancelled=lambda: cancelled,
            )
        self.assertEqual(seen[0], bands[1])


if __name__ == "__main__":
    unittest.main()
