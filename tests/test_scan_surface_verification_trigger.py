from pathlib import Path
import unittest


class ScanSurfaceVerificationTriggerTests(unittest.TestCase):
    def test_manual_scan_surface_is_absent_from_shipped_ui(self) -> None:
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
        self.assertNotIn('text=\"SCAN\"', combined)


if __name__ == "__main__":
    unittest.main()
