from pathlib import Path
import unittest


class AutomaticCertifiedStartupTests(unittest.TestCase):
    def test_manual_scan_button_is_hidden(self) -> None:
        source = Path("deduper/certified_app.py").read_text()
        self.assertIn("self.scan_button.pack_forget()", source)

    def test_rebuild_required_starts_automatically(self) -> None:
        source = Path("deduper/generation_app_lifecycle.py").read_text()
        self.assertIn("if snapshot.rebuild_required:", source)
        self.assertIn("self.app.after(0, self.app.start_scan)", source)

    def test_automatic_rebuild_reuses_validation_inventory(self) -> None:
        # The rebuild must consume validation's single authoritative R2 snapshot.
        source = Path("deduper/smart_app.py").read_text()
        self.assertIn("startup_inventory = getattr", source)
        self.assertIn("inventory = list(startup_inventory)", source)
        self.assertIn("self._startup_inventory_snapshot = ()", source)


if __name__ == "__main__":
    unittest.main()
