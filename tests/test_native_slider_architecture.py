from pathlib import Path
import unittest


class NativeSliderArchitectureTests(unittest.TestCase):
    def test_slider_lock_is_native(self) -> None:
        main = Path("deduper/main.py").read_text()
        fast = Path("deduper/fast_app.py").read_text()
        app = Path("deduper/app.py").read_text()
        self.assertNotIn("install_certified_slider_lock", main)
        self.assertFalse(Path("deduper/certified_slider.py").exists())
        self.assertIn("self.slider_widget = ttk.Scale", app)
        self.assertIn("def _apply_certified_slider_lock", fast)
        self.assertIn('self.slider_widget.configure(state="disabled")', fast)
        self.assertGreaterEqual(fast.count("self._apply_certified_slider_lock()"), 4)


if __name__ == "__main__":
    unittest.main()
