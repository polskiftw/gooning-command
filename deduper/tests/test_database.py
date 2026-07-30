from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.database import Database
from deduper.models import Asset


def asset(key: str, sha256: str | None = None) -> Asset:
    return Asset(
        key=key,
        size=100,
        etag="etag",
        last_modified="today",
        media_type="image",
        extension="jpg",
        sha256=sha256,
    )


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.database.close()
        self.temporary.cleanup()

    def test_inventory_hash_queue_and_undo(self) -> None:
        left, right = asset("gallery/a.jpg"), asset("gallery/b.jpg")
        new_count, changed_count = self.database.upsert_inventory([left, right])
        self.assertEqual((new_count, changed_count), (2, 0))

        left.sha256 = "a" * 64
        right.sha256 = "b" * 64
        self.database.save_hashes(left)
        self.database.save_hashes(right)
        self.database.replace_pairs([(left.key, right.key, 92.0, "test")])
        pair = self.database.pending_pairs()[0]

        self.database.decide_pair(pair.id, "delete_left", left.key)
        self.assertEqual(self.database.queued_deletions()[0][0], left.key)
        self.database.undo_pair(pair.id)
        self.assertEqual(self.database.queued_deletions(), [])
        self.assertEqual(len(self.database.pending_pairs()), 1)

    def test_changed_object_is_rehashed(self) -> None:
        original = asset("gallery/a.jpg")
        self.database.upsert_inventory([original])
        original.sha256 = "a" * 64
        self.database.save_hashes(original)

        changed = asset("gallery/a.jpg")
        changed.etag = "new-etag"
        new_count, changed_count = self.database.upsert_inventory([changed])
        self.assertEqual((new_count, changed_count), (0, 1))
        self.assertEqual(len(list(self.database.assets_needing_hashes())), 1)

    def test_same_asset_queued_by_two_pairs_survives_one_undo(self) -> None:
        items = [asset(f"gallery/{name}.jpg") for name in ("a", "b", "c")]
        self.database.upsert_inventory(items)
        for index, item in enumerate(items):
            item.sha256 = str(index) * 64
            self.database.save_hashes(item)
        self.database.replace_pairs(
            [
                (items[0].key, items[1].key, 90, "one"),
                (items[0].key, items[2].key, 89, "two"),
            ]
        )
        first, second = self.database.pending_pairs()
        self.database.decide_pair(first.id, "delete_left", items[0].key)
        self.database.decide_pair(second.id, "delete_left", items[0].key)
        self.database.undo_pair(second.id)
        self.assertEqual([row[0] for row in self.database.queued_deletions()], [items[0].key])


if __name__ == "__main__":
    unittest.main()
