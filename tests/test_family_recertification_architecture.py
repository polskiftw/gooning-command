from pathlib import Path
import unittest


class FamilyRecertificationArchitectureTests(unittest.TestCase):
    def test_current_code_and_ui_use_recertification_language(self) -> None:
        certified = Path("deduper/certified_app.py").read_text()
        smart = Path("deduper/smart_app.py").read_text()
        status = Path("deduper/family_recertification_status.py").read_text()
        self.assertFalse(Path("deduper/family_repair_queue.py").exists())
        self.assertFalse(Path("deduper/family_repair_status.py").exists())
        self.assertIn("FamilyRecertificationQueue", certified)
        self.assertIn("family_recertification_status_text", certified)
        self.assertNotIn("Family repair", certified + smart + status)
        self.assertNotIn("family repair", certified + smart + status)


if __name__ == "__main__":
    unittest.main()
