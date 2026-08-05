from __future__ import annotations

import unittest

from deduper.band_scanner import make_band_scanner, scan_index_band
from deduper.progressive_indexer import IndexBand, IndexingCancelled
from deduper.matcher import thresholds
from deduper.models import Asset


def asset(key: str, phash: str) -> Asset:
    return Asset(
        key=key,
        size=100,
        etag="etag",
        last_modified="date",
        media_type="image",
        extension=".jpg",
        phash=phash,
        width=100,
        height=100,
    )


def band(slider: int) -> IndexBand:
    return IndexBand(
        strictest_slider=slider,
        loosest_slider=slider,
        signature=tuple(sorted(thresholds(slider).items())),
    )


class BandScannerTests(unittest.TestCase):
    def test_strict_band_records_raw_distance_for_qualifying_pair(self) -> None:
        assets = [
            asset("gallery/a.jpg", "0000000000000000"),
            asset("gallery/b.jpg", "000000000000000f"),
        ]
        edges = scan_index_band(assets, band(99), lambda: False)
        self.assertEqual(len(edges), 1)
        self.assertEqual(
            {edges[0].left_key, edges[0].right_key},
            {"gallery/a.jpg", "gallery/b.jpg"},
        )
        self.assertEqual(edges[0].phash_distance, 4)

    def test_loose_band_admits_relationship_rejected_by_strict_band(self) -> None:
        assets = [
            asset("gallery/a.jpg", "0000000000000000"),
            asset("gallery/b.jpg", "0000000000007fff"),
        ]
        self.assertEqual(scan_index_band(assets, band(99), lambda: False), [])
        loose = scan_index_band(assets, band(0), lambda: False)
        self.assertEqual(len(loose), 1)
        self.assertEqual(loose[0].phash_distance, 15)

    def test_cancellation_never_returns_partial_band(self) -> None:
        assets = [
            asset("gallery/a.jpg", "0000000000000000"),
            asset("gallery/b.jpg", "000000000000000f"),
        ]
        with self.assertRaises(IndexingCancelled):
            scan_index_band(assets, band(99), lambda: True)

    def test_factory_binds_worker_count(self) -> None:
        assets = [
            asset("gallery/a.jpg", "0000000000000000"),
            asset("gallery/b.jpg", "000000000000000f"),
        ]
        scanner = make_band_scanner(1)
        self.assertEqual(scanner(assets, band(99), lambda: False)[0].phash_distance, 4)


if __name__ == "__main__":
    unittest.main()
