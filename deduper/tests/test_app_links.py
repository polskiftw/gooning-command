from __future__ import annotations

import unittest
from unittest.mock import patch

from deduper.links import open_in_firefox, public_media_url


class PreviewLinkTests(unittest.TestCase):
    def test_public_media_url_encodes_the_complete_r2_key(self) -> None:
        self.assertEqual(
            public_media_url("gallery/folder name/image #1.jpeg"),
            "https://gooning.party/media/gallery%2Ffolder%20name%2Fimage%20%231.jpeg",
        )

    @patch("deduper.links.subprocess.Popen")
    @patch("deduper.links.firefox_executables", return_value=[r"C:\Firefox\firefox.exe"])
    def test_open_in_firefox_uses_an_explicit_firefox_new_tab(
        self,
        _executables,
        popen,
    ) -> None:
        open_in_firefox("https://gooning.party/media/gallery%2Fexample.jpeg")

        popen.assert_called_once_with(
            [
                r"C:\Firefox\firefox.exe",
                "-new-tab",
                "https://gooning.party/media/gallery%2Fexample.jpeg",
            ]
        )

    @patch("deduper.links.firefox_executables", return_value=[])
    def test_open_in_firefox_does_not_fall_back_to_another_browser(self, _executables) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "Firefox was not found"):
            open_in_firefox("https://gooning.party/")


if __name__ == "__main__":
    unittest.main()
