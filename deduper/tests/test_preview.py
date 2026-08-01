from __future__ import annotations

import io
import unittest

try:
    from PIL import Image

    from deduper.preview import PreviewCancelled, prepare_preview
except ModuleNotFoundError:
    prepare_preview = None


@unittest.skipIf(prepare_preview is None, "deduper media packages are not installed")
class PreviewTests(unittest.TestCase):
    def test_still_decodes_from_memory_and_is_bounded(self) -> None:
        source = Image.new("RGB", (2400, 1800), "red")
        encoded = io.BytesIO()
        source.save(encoded, format="JPEG")

        preview = prepare_preview(encoded.getvalue(), "jpg")

        self.assertEqual(len(preview.frames), 1)
        self.assertLessEqual(preview.frames[0].width, 2000)
        self.assertLessEqual(preview.frames[0].height, 1400)

    def test_animation_is_bounded_and_cancellable(self) -> None:
        frames = [Image.new("RGB", (80, 60), (index, 0, 0)) for index in range(80)]
        encoded = io.BytesIO()
        frames[0].save(
            encoded,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=20,
            loop=0,
        )
        data = encoded.getvalue()

        preview = prepare_preview(data, "gif")
        self.assertLessEqual(len(preview.frames), 60)

        with self.assertRaises(PreviewCancelled):
            prepare_preview(data, "gif", lambda: True)


if __name__ == "__main__":
    unittest.main()
