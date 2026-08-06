from pathlib import Path
import unittest


class NativeReviewUiArchitectureTests(unittest.TestCase):
    def test_review_hardening_is_native(self) -> None:
        main = Path("deduper/main.py").read_text()
        review = Path("deduper/review_ui.py").read_text()
        app = Path("deduper/app.py").read_text()
        self.assertNotIn("install_review_ui_hardening", main + review)
        self.assertIn("_review_desired_preview_keys", app)
        self.assertIn("preserved_pair_index", app)


if __name__ == "__main__":
    unittest.main()
