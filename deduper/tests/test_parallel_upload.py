from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import parallel_upload


SETTINGS = {
    "allowed_extensions": ["jpg", "png", "mp4"],
    "maximum_file_size_mb": 500,
    "r2_gallery_prefix": "gallery/",
}


class ParallelUploadCompatibilityTests(unittest.TestCase):
    def test_successful_uploads_keep_the_deduper_index_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scan_root = Path(directory)
            first = scan_root / "first.jpg"
            second = scan_root / "second.mp4"
            first.write_bytes(b"first image")
            second.write_bytes(b"second clip")
            checkpointed: list[dict] = []

            def remember_merge(_client, _bucket, index_key, additions):
                self.assertEqual(index_key, "gallery-index.json")
                checkpointed.extend(additions)
                return list(checkpointed)

            with (
                patch("parallel_upload.read_index_items", return_value=[]),
                patch("parallel_upload.merge_index_items", side_effect=remember_merge),
                patch("parallel_upload.app.upload_file_with_retry") as upload,
                patch.object(parallel_upload, "INDEX_CHECKPOINT_SIZE", 1),
            ):
                uploaded, discovered, failed = parallel_upload.upload_downloads_parallel(
                    SETTINGS,
                    scan_root,
                    object(),
                    "bucket",
                )

            self.assertEqual((uploaded, discovered, failed), (2, 2, 0))
            self.assertEqual(upload.call_count, 2)
            self.assertEqual({item["ext"] for item in checkpointed}, {"jpg", "mp4"})
            self.assertEqual({item["size"] for item in checkpointed}, {11})
            self.assertTrue(all(item["key"].startswith("gallery/") for item in checkpointed))
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_failed_upload_never_enters_the_shared_gallery_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scan_root = Path(directory)
            good = scan_root / "good.jpg"
            bad = scan_root / "bad.jpg"
            good.write_bytes(b"good")
            bad.write_bytes(b"bad")
            checkpointed: list[dict] = []

            def upload_side_effect(_client, *, local_path, **_kwargs):
                if local_path.name == "bad.jpg":
                    raise RuntimeError("simulated upload failure")

            def remember_merge(_client, _bucket, _index_key, additions):
                checkpointed.extend(additions)
                return list(checkpointed)

            with (
                patch("parallel_upload.read_index_items", return_value=[]),
                patch("parallel_upload.merge_index_items", side_effect=remember_merge),
                patch(
                    "parallel_upload.app.upload_file_with_retry",
                    side_effect=upload_side_effect,
                ),
            ):
                uploaded, discovered, failed = parallel_upload.upload_downloads_parallel(
                    SETTINGS,
                    scan_root,
                    object(),
                    "bucket",
                )

            self.assertEqual((uploaded, discovered, failed), (1, 2, 1))
            self.assertEqual(len(checkpointed), 1)
            self.assertTrue(checkpointed[0]["key"].endswith("_good.jpg"))
            self.assertFalse(good.exists())
            self.assertFalse(bad.exists())

    def test_existing_index_key_is_not_reuploaded_after_a_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scan_root = Path(directory)
            media = scan_root / "retry.jpg"
            media.write_bytes(b"already checkpointed")
            key = app.object_key("gallery/", media, "retry.jpg")

            with (
                patch(
                    "parallel_upload.read_index_items",
                    return_value=[{"key": key, "ext": "jpg", "size": media.stat().st_size}],
                ),
                patch("parallel_upload.merge_index_items") as merge,
                patch("parallel_upload.app.upload_file_with_retry") as upload,
            ):
                result = parallel_upload.upload_downloads_parallel(
                    SETTINGS,
                    scan_root,
                    object(),
                    "bucket",
                )

            self.assertEqual(result, (0, 1, 0))
            upload.assert_not_called()
            merge.assert_not_called()
            self.assertFalse(media.exists())


if __name__ == "__main__":
    unittest.main()
