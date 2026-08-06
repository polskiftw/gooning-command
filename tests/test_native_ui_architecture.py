from pathlib import Path
import unittest


# These tests keep the production review UI native and single-owned.
class NativeUiArchitectureTests(unittest.TestCase):
    def test_production_ui_has_no_obsolete_reverse_delete_path(self) -> None:
        sources = "\n".join(
            Path(path).read_text()
            for path in ("deduper/app.py", "deduper/fast_app.py", "deduper/certified_app.py")
        )
        self.assertNotIn("reverse_delete_button", sources)
        self.assertNotIn("_delete_left_keep_right", sources)
        self.assertNotIn("_install_exclusion_buttons", sources)
        self.assertNotIn("pack_forget()", Path("deduper/certified_app.py").read_text())

    def test_native_controls_are_built_once(self) -> None:
        app = Path("deduper/app.py").read_text()
        self.assertEqual(app.count('text="BYE BITCH"'), 2)
        self.assertEqual(app.count('text="EXCLUDE THIS RUN"'), 1)
        self.assertEqual(app.count('text="EXCLUDE PERMANENTLY"'), 1)


if __name__ == "__main__":
    unittest.main()
