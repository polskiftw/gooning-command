from __future__ import annotations

import importlib
import unittest


PACKAGED_MODULES = (
    "deduper.main",
    "deduper.smart_app",
    "deduper.incremental_matcher",
    "deduper.incremental_recertification",
    "deduper.database_migration",
    "deduper.review_ui",
)


class PackagingImportTests(unittest.TestCase):
    def test_runtime_modules_import_from_source_tree(self) -> None:
        for module_name in PACKAGED_MODULES:
            with self.subTest(module=module_name):
                self.assertIsNotNone(importlib.import_module(module_name))


if __name__ == "__main__":
    unittest.main()
