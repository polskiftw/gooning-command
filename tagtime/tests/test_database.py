from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tagtime.database import Asset, TagDatabase


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = TagDatabase(Path(tempfile.mkdtemp()) / "tags.sqlite3")

    def tearDown(self) -> None:
        self.database.close()

    def test_completed_asset_resumes_but_changed_asset_retags(self) -> None:
        first = Asset("gallery/a.jpg", 10, "etag-one", "jpg")
        self.database.sync_assets([first])
        self.database.mark_tagged(first.key, ["cat", "blue_eyes"], "now")
        self.database.sync_assets([first])
        self.assertEqual(self.database.pending(), [])

        changed = Asset(first.key, 11, "etag-two", "jpg")
        self.database.sync_assets([changed])
        self.assertEqual(self.database.pending(), [changed])

    def test_assets_that_left_r2_leave_the_published_catalog(self) -> None:
        first = Asset("gallery/a.jpg", 10, "a", "jpg")
        second = Asset("gallery/b.jpg", 20, "b", "jpg")
        self.database.sync_assets([first, second])
        self.database.mark_tagged(first.key, ["cat"], "now")
        self.database.mark_tagged(second.key, ["dog"], "now")
        self.database.sync_assets([second])
        self.assertEqual(self.database.tagged_rows(), [(second.key, "jpg", ["dog"])])


if __name__ == "__main__":
    unittest.main()

