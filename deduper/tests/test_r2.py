from __future__ import annotations

import io
import json
import unittest

from deduper.config import Config

try:
    from deduper.r2 import R2Store
except ModuleNotFoundError:
    R2Store = None


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.written = None
        self.if_match = None

    def get_object(self, **_kwargs):
        return {
            "Body": io.BytesIO(json.dumps(self.payload).encode("utf-8")),
            "ETag": '"current-etag"',
        }

    def put_object(self, **kwargs):
        self.written = json.loads(kwargs["Body"].decode("utf-8"))
        self.if_match = kwargs["IfMatch"]


@unittest.skipIf(R2Store is None, "boto3 is not installed in the lightweight test environment")
class R2IndexTests(unittest.TestCase):
    def test_removes_deleted_keys_from_index(self) -> None:
        store = object.__new__(R2Store)
        store.config = Config("a", "b", "c", "bucket")
        store.client = FakeClient(
            {
                "version": 1,
                "count": 2,
                "items": [
                    {"key": "gallery/a.jpg"},
                    {"key": "gallery/b.jpg"},
                ],
            }
        )
        removed = store.remove_from_gallery_index({"gallery/a.jpg"})
        self.assertEqual(removed, 1)
        self.assertEqual(store.client.written["count"], 1)
        self.assertEqual(store.client.written["items"][0]["key"], "gallery/b.jpg")
        self.assertEqual(store.client.if_match, "current-etag")


if __name__ == "__main__":
    unittest.main()
