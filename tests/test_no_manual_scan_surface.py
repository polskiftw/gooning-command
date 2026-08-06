from pathlib import Path
import unittest


class NoManualScanSurfaceTests(unittest.TestCase):
    def test_production_ui_has_no_scan_button_symbol_or_instruction(self) -> None:
        paths = [
            Path("deduper/app.py"),
            Path("deduper/certified_app.py"),
            Path("deduper/fast_app.py"),
        ]
        combined = "\n".join(path.read_text() for path in paths)
        self.assertNotIn("scan_button", combined)
        self.assertNotIn("Press SCAN", combined)
        self.assertNotIn('text="SCAN"', combined)


if __name__ == "__main__":
    unittest.main()
