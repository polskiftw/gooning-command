from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.evidence_inventory import inventory_records_from_assets, reconcile_asset_inventory
from deduper.evidence_store import EvidenceEdge, EvidenceStore
from deduper.models import Asset


def asset(
    key: str,
    size: int,
    etag: str = "etag",
    modified: str = "date",
) -> Asset:
    return Asset(
        key=key,
        size=size,
        etag=etag,
        last_modified=modified,
        media_type="image",
        extension="jpg",
    )


class EvidenceInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_asset_adapter_preserves_storage_identity(self) -> None:
        records = inventory_records_from_assets(
            [asset("gallery/a.jpg", 123, "abc", "2026-08-05")]
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].key, "gallery/a.jpg")
        self.assertEqual(records[0].size, 123)
        self.assertEqual(records[0].etag, "abc")
        self.assertEqual(records[0].last_modified, "2026-08-05")

    def test_first_real_listing_creates_snapshot(self) -> None:
        result = reconcile_asset_inventory(
            self.store,
            [asset("gallery/a.jpg", 10), asset("gallery/b.jpg", 20)],
        )
        self.assertEqual(result.delta.added, {"gallery/a.jpg", "gallery/b.jpg"})
        self.assertFalse(result.cache_was_current)
        self.assertEqual(self.store.inventory_count(), 2)

    def test_unchanged_real_listing_reuses_snapshot(self) -> None:
        listing = [asset("gallery/a.jpg", 10), asset("gallery/b.jpg", 20)]
        reconcile_asset_inventory(self.store, listing)
        result = reconcile_asset_inventory(self.store, list(reversed(listing)))
        self.assertTrue(result.cache_was_current)
        self.assertFalse(result.delta.has_changes)

    def test_changed_real_asset_invalidates_only_touching_edges(self) -> None:
        initial = [
            asset("gallery/a.jpg", 10),
            asset("gallery/b.jpg", 20),
            asset("gallery/c.jpg", 30),
        ]
        reconcile_asset_inventory(self.store, initial)
        self.store.upsert_edges(
            [
                EvidenceEdge("gallery/a.jpg", "gallery/b.jpg", phash_distance=1),
                EvidenceEdge("gallery/b.jpg", "gallery/c.jpg", phash_distance=2),
            ]
        )
        updated = [
            asset("gallery/a.jpg", 11, "new-etag"),
            asset("gallery/b.jpg", 20),
            asset("gallery/c.jpg", 30),
        ]
        result = reconcile_asset_inventory(self.store, updated)
        self.assertEqual(result.delta.changed, {"gallery/a.jpg"})
        rows = self.store.connection.execute(
            "SELECT left_key, right_key FROM comparison_edges"
        ).fetchall()
        self.assertEqual(
            [(row["left_key"], row["right_key"]) for row in rows],
            [("gallery/b.jpg", "gallery/c.jpg")],
        )
        self.assertIsNone(self.store.loosest_complete_slider())
        self.assertEqual(self.store.get_state("build_status"), "dirty")


if __name__ == "__main__":
    unittest.main()
