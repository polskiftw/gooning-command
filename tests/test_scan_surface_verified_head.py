from pathlib import Path
import unittest


class ScanSurfaceVerifiedHeadTests(unittest.TestCase):
    def test_current_head_has_no_manual_scan_instructions(self) -> None:
        combined = "\n".join(
            Path(path).read_text()
            for path in (
                "deduper/app.py",
                "deduper/certified_app.py",
                "deduper/fast_app.py",
            )
        )
        self.assertNotIn("scan_button", combined)
        self.assertNotIn("Press SCAN", combined)
        self.assertNotIn("press SCAN", combined)
        self.assertNotIn("run SCAN", combined)
        self.assertNotIn("Run a complete, error-free SCAN", combined)


if __name__ == "__main__":
    unittest.main()
