from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.config import ConfigError, parse_config


class ConfigTests(unittest.TestCase):
    def test_parses_complete_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.txt"
            path.write_text(
                "\n".join(
                    [
                        "R2_ACCOUNT_ID=account",
                        "R2_ACCESS_KEY_ID=key",
                        "R2_SECRET_ACCESS_KEY=secret=with=equals",
                        "R2_BUCKET_NAME=bucket",
                        "GALLERY_PREFIX=/gallery/",
                        "ALLOW_DELETE=YES",
                    ]
                ),
                encoding="utf-8",
            )
            config = parse_config(path)
        self.assertEqual(config.gallery_prefix, "gallery/")
        self.assertEqual(config.secret_access_key, "secret=with=equals")
        self.assertTrue(config.allow_delete)
        self.assertEqual(config.compare_workers, 20)

    def test_parses_compare_workers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.txt"
            path.write_text(
                "\n".join(
                    [
                        "R2_ACCOUNT_ID=account",
                        "R2_ACCESS_KEY_ID=key",
                        "R2_SECRET_ACCESS_KEY=secret",
                        "R2_BUCKET_NAME=bucket",
                        "COMPARE_WORKERS=24",
                    ]
                ),
                encoding="utf-8",
            )
            config = parse_config(path)
        self.assertEqual(config.compare_workers, 24)

    def test_rejects_missing_required_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.txt"
            path.write_text("R2_ACCOUNT_ID=account\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                parse_config(path)


if __name__ == "__main__":
    unittest.main()
