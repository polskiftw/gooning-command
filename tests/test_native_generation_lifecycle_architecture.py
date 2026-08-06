from pathlib import Path
import unittest


class NativeGenerationLifecycleArchitectureTests(unittest.TestCase):
    def test_production_app_owns_generation_lifecycle(self) -> None:
        main = Path("deduper/main.py").read_text()
        certified = Path("deduper/certified_app.py").read_text()
        lifecycle = Path("deduper/generation_app_lifecycle.py").read_text()
        self.assertNotIn("attach_generation_lifecycle", main + lifecycle)
        self.assertIn("generation_startup: GenerationStartupState", certified)
        self.assertIn("self._generation_lifecycle = GenerationAppLifecycle", certified)
        self.assertIn("generation_startup=generation_startup", main)


if __name__ == "__main__":
    unittest.main()
