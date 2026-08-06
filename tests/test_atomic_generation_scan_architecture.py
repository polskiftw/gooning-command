from pathlib import Path
import unittest


class CertifiedFamilyPublicationArchitectureTests(unittest.TestCase):
    def test_each_admitted_family_is_published_to_preview_immediately(self) -> None:
        smart = Path("deduper/smart_app.py").read_text()

        self.assertIn("def publish_certified_queue()", smart)
        self.assertIn("preview_projection(certified_queue)", smart)
        self.assertIn("self._ui(self._refresh_pairs)", smart)
        self.assertIn("if not admission.admitted:", smart)
        self.assertIn("visible_count = publish_certified_queue()", smart)
        self.assertIn("certified review pairs are now available in preview", smart)

        self.assertNotIn("replacement review pairs prepared privately", smart)
        self.assertNotIn("Nothing has been published to review yet", smart)
        self.assertNotIn("active certified queue remains unchanged until atomic promotion", smart)

    def test_completed_generation_still_controls_destructive_unlock(self) -> None:
        smart = Path("deduper/smart_app.py").read_text()

        self.assertIn("CertifiedGenerationBuilder", smart)
        self.assertIn("builder.build()", smart)
        self.assertIn("self._scan_completed_current_inventory = True", smart)
        self.assertIn("NUKE remains locked", smart)
        self.assertIn("self._refresh_index_boundary(apply=False)", smart)


if __name__ == "__main__":
    unittest.main()
