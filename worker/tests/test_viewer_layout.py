from __future__ import annotations

import re
import unittest
from pathlib import Path


WORKER_DIR = Path(__file__).resolve().parents[1]


class ViewerLayoutHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = (WORKER_DIR / "style.css").read_text(encoding="utf-8")
        cls.script = (WORKER_DIR / "app.js").read_text(encoding="utf-8")

    def mobile_rule(self, selector: str) -> str:
        mobile_css = self.css.split("@media (max-width: 700px)", 1)[1]
        match = re.search(
            rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}",
            mobile_css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, f"Missing mobile rule for {selector}")
        return match.group("body")

    def test_mobile_media_uses_intrinsic_box_instead_of_object_fit_canvas(self) -> None:
        media_rule = self.mobile_rule("#media")
        self.assertIn("width: auto !important", media_rule)
        self.assertIn("height: auto !important", media_rule)
        self.assertIn("max-width: 100%", media_rule)
        self.assertIn("max-height: 100%", media_rule)
        self.assertIn("object-fit: initial", media_rule)
        self.assertNotIn("width: 100% !important", media_rule)
        self.assertNotIn("height: 100% !important", media_rule)

    def test_mobile_wrapper_keeps_media_off_fractional_clip_edges(self) -> None:
        wrapper_rule = self.mobile_rule("#media-wrap")
        self.assertIn("padding-block: 1px", wrapper_rule)
        self.assertIn("overflow: visible", wrapper_rule)

    def test_dynamic_viewport_height_is_used_when_supported(self) -> None:
        self.assertIn("@supports (height: 100dvh)", self.css)
        self.assertRegex(
            self.css,
            r"html,\s*body\s*\{\s*height:\s*100dvh;\s*\}",
        )

    def test_mobile_javascript_removes_desktop_pixel_dimensions(self) -> None:
        self.assertIn('media.style.removeProperty("width")', self.script)
        self.assertIn('media.style.removeProperty("height")', self.script)
        self.assertNotIn('media.style.width = "100%"', self.script)
        self.assertNotIn('media.style.height = "100%"', self.script)

    def test_safari_viewport_and_stage_changes_refresh_sizing(self) -> None:
        self.assertIn("window.visualViewport", self.script)
        self.assertIn('window.addEventListener("orientationchange"', self.script)
        self.assertIn("new ResizeObserver(scheduleSizeRefresh).observe(stage)", self.script)
        self.assertIn('window.addEventListener("pageshow"', self.script)


if __name__ == "__main__":
    unittest.main()
