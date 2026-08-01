from __future__ import annotations

import json
import unittest

from tagtime.index import build_tag_index


class IndexTests(unittest.TestCase):
    def test_catalog_counts_are_individual_and_items_use_compact_ids(self) -> None:
        payload = json.loads(
            build_tag_index(
                [
                    ("gallery/a.jpg", "jpg", ["cat", "blue_eyes"]),
                    ("gallery/b.webp", "webp", ["cat"]),
                ],
                threshold=0.4,
            )
        )
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["catalog"], [["cat", 2], ["blue_eyes", 1]])
        self.assertEqual(payload["items"][0], ["gallery/a.jpg", "jpg", [0, 1]])
        self.assertEqual(payload["items"][1], ["gallery/b.webp", "webp", [0]])
        self.assertNotIn("combination_counts", payload)


if __name__ == "__main__":
    unittest.main()

