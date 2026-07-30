from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image, ImageDraw

    from deduper.config import Config
    from deduper.hashing import _ceiling_sample_step, hash_file
    from deduper.models import Asset
except ModuleNotFoundError:
    hash_file = None


@unittest.skipIf(hash_file is None, "deduper media packages are not installed")
class HashingTests(unittest.TestCase):
    def test_gif_sample_step_uses_ceiling_division(self) -> None:
        self.assertEqual(_ceiling_sample_step(299, 300), 1)
        self.assertEqual(_ceiling_sample_step(300, 300), 1)
        self.assertEqual(_ceiling_sample_step(599, 300), 2)
        self.assertEqual(_ceiling_sample_step(600, 300), 2)
        self.assertEqual(_ceiling_sample_step(899, 300), 3)

    def test_still_image_produces_all_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            image = Image.new("RGB", (128, 96), "navy")
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 15, 100, 75), fill="orange")
            draw.ellipse((45, 25, 85, 65), fill="white")
            image.save(path)

            asset = Asset(
                key="gallery/sample.png",
                size=path.stat().st_size,
                etag="",
                last_modified="",
                media_type="image",
                extension="png",
            )
            result = hash_file(asset, path, Config("a", "b", "c", "bucket"))

        self.assertIsNone(result.scan_error)
        self.assertEqual(len(result.sha256 or ""), 64)
        self.assertEqual(len(result.phash or ""), 16)
        self.assertEqual(len(result.pdq_hash or ""), 64)
        self.assertTrue(result.crop_hashes)


if __name__ == "__main__":
    unittest.main()
