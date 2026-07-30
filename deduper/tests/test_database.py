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

    def test_scan_pairs_are_automatically_queued_on_the_right(self) -> None:
        left, right = asset("gallery/a.jpg"), asset("gallery/b.jpg")
        new_count, changed_count = self.database.upsert_inventory([left, right])
        self.assertEqual((new_count, changed_count), (2, 0))

        left.sha256 = "a" * 64
        right.sha256 = "b" * 64
        self.database.save_hashes(left)
        self.database.save_hashes(right)
        self.database.replace_pairs([(left.key, right.key, 92.0, "test")])
        pair = self.database.scan_pairs()[0]

        self.assertEqual((pair.left_key, pair.right_key, pair.status), (left.key, right.key, "included"))
        self.assertEqual(self.database.queued_deletions()[0][0], right.key)
        self.database.exclude_pair(pair.id)
        self.assertEqual(self.database.queued_deletions(), [])
        self.assertEqual(self.database.scan_pairs()[0].status, "excluded")

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

    def test_new_scan_resets_temporary_exclusion(self) -> None:
        left, right = asset("gallery/a.jpg"), asset("gallery/b.jpg")
        self.database.upsert_inventory([left, right])
        self.database.replace_pairs([(left.key, right.key, 92.0, "test")])
        self.database.exclude_pair(self.database.scan_pairs()[0].id)

        self.database.replace_pairs([(left.key, right.key, 92.0, "test")])

        pair = self.database.scan_pairs()[0]
        self.assertEqual(pair.status, "included")
        self.assertEqual([row[0] for row in self.database.queued_deletions()], [right.key])

    def test_scan_pairs_are_ordered_from_least_to_most_likely(self) -> None:
        items = [asset(f"gallery/{name}.jpg") for name in ("a", "b", "c")]
        self.database.upsert_inventory(items)
        self.database.replace_pairs(
            [
                (items[2].key, items[1].key, 99.0, "obvious"),
                (items[2].key, items[0].key, 71.0, "questionable"),
            ]
        )

        self.assertEqual([pair.similarity for pair in self.database.scan_pairs()], [71.0, 99.0])


if __name__ == "__main__":
    unittest.main()
