from pathlib import Path
import unittest


class AtomicGenerationScanArchitectureTests(unittest.TestCase):
    def test_scan_does_not_publish_visible_queue_progressively(self) -> None:
        smart = Path("deduper/smart_app.py").read_text()
        self.assertNotIn("def publish_queue", smart)
        self.assertNotIn("self.database.replace_pairs([], preserve_exclusions=True)", smart)
        self.assertIn("CertifiedGenerationBuilder", smart)
        self.assertIn("builder.build()", smart)
        self.assertIn("previous certified queue retained", smart)
        self.assertIn("self._refresh_index_boundary(apply=False)", smart)
        self.assertIn("atomic promotion", smart)


if __name__ == "__main__":
    unittest.main()
