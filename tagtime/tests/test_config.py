from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tagtime.config import ConfigError, parse_config


class ConfigTests(unittest.TestCase):
    def write(self, body: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "config.txt"
        path.write_text(body, encoding="utf-8")
        return path

    def test_deduper_r2_names_work_without_translation(self) -> None:
        config = parse_config(
            self.write(
                "R2_ACCOUNT_ID=account\n"
                "R2_ACCESS_KEY_ID=access\n"
                "R2_SECRET_ACCESS_KEY=secret\n"
                "R2_BUCKET_NAME=bucket\n"
            )
        )
        self.assertEqual(config.endpoint_url, "https://account.r2.cloudflarestorage.com")
        self.assertEqual(config.gallery_prefix, "gallery/")
        self.assertEqual(config.tag_index_key, "_internal/tag-index-v1.json")
        self.assertEqual(config.threshold, 0.4)

    def test_missing_secret_is_explained(self) -> None:
        with self.assertRaisesRegex(ConfigError, "R2_SECRET_ACCESS_KEY"):
            parse_config(
                self.write(
                    "R2_ACCOUNT_ID=account\n"
                    "R2_ACCESS_KEY_ID=access\n"
                    "R2_BUCKET_NAME=bucket\n"
                )
            )


if __name__ == "__main__":
    unittest.main()

