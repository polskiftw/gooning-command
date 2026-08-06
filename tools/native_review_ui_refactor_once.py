from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


app_path = Path("deduper/app.py")
app = app_path.read_text()
app = replace_once(
    app,
    "from .models import Pair\n",
    "from .models import Pair\nfrom .review_ui import preserved_pair_index\n",
    "review helper import",
)
app = replace_once(
    app,
    "        self.preview_requests: dict[MediaPreview, int] = {}\n        self.preview_cancellations: dict[MediaPreview, threading.Event] = {}\n",
    "        self.preview_requests: dict[MediaPreview, int] = {}\n        self.preview_cancellations: dict[MediaPreview, threading.Event] = {}\n        self._review_loaded_preview_keys: dict[MediaPreview, str] = {}\n        self._review_desired_preview_keys: dict[MediaPreview, str] = {}\n        self._review_pending_preview_requests: dict[tuple[MediaPreview, int], str] = {}\n",
    "review UI state",
)
app = replace_once(
    app,
    "    def _refresh_pairs(self) -> None:\n        self.pairs = self.database.scan_pairs()\n        self.pair_index = min(self.pair_index, max(0, len(self.pairs) - 1))\n        self._show_current_pair()\n",
    "    def _refresh_pairs(self) -> None:\n        old_left = self.left_asset_key\n        old_right = self.right_asset_key\n        old_index = self.pair_index\n        refreshed = self.database.scan_pairs()\n        self.pairs = refreshed\n        self.pair_index = preserved_pair_index(\n            refreshed,\n            old_left,\n            old_right,\n            old_index,\n        )\n        self._show_current_pair()\n",
    "stable pair refresh",
)
app = replace_once(
    app,
    "    def _show_current_pair(self) -> None:\n        if not self.pairs:\n",
    "    def _show_current_pair(self) -> None:\n        if not self.pairs:\n            self._review_loaded_preview_keys.clear()\n            self._review_desired_preview_keys.clear()\n            self._review_pending_preview_requests.clear()\n",
    "empty review cleanup",
)
app = replace_once(
    app,
    "    def _load_preview(self, key: str, widget: MediaPreview) -> None:\n        widget.clear()\n",
    "    def _load_preview(self, key: str, widget: MediaPreview) -> None:\n        self._review_desired_preview_keys[widget] = key\n        if self._review_loaded_preview_keys.get(widget) == key:\n            return\n        widget.clear()\n",
    "preview target guard",
)
app = replace_once(
    app,
    "        self.preview_requests[widget] = request\n\n        def fetch() -> None:\n",
    "        self.preview_requests[widget] = request\n        self._review_pending_preview_requests[(widget, request)] = key\n\n        def fetch() -> None:\n",
    "preview request tracking",
)
app = replace_once(
    app,
    "    ) -> None:\n        if self.preview_requests.get(widget) != request:\n            return\n        if error or preview is None:\n            widget.clear(f\"Preview failed\\n{error or 'unknown error'}\")\n        else:\n            widget.load_prepared(preview)\n\n    def _set_review_state",
    "    ) -> None:\n        key = self._review_pending_preview_requests.pop((widget, request), None)\n        if self.preview_requests.get(widget) != request:\n            return\n        if error or preview is None:\n            widget.clear(f\"Preview failed\\n{error or 'unknown error'}\")\n        else:\n            widget.load_prepared(preview)\n            if key is not None and self._review_desired_preview_keys.get(widget) == key:\n                self._review_loaded_preview_keys[widget] = key\n\n    def _set_review_state",
    "preview completion guard",
)
app_path.write_text(app)

main_path = Path("deduper/main.py")
main = main_path.read_text()
main = replace_once(main, "from deduper.app import DeduperApp\n", "", "obsolete app import")
main = replace_once(main, "from deduper.review_ui import install_review_ui_hardening\n", "", "review installer import")
main = replace_once(main, "    install_review_ui_hardening(DeduperApp)\n", "", "review installer call")
main_path.write_text(main)

review_path = Path("deduper/review_ui.py")
review = review_path.read_text()
marker = "\n\ndef install_review_ui_hardening"
if marker not in review:
    raise SystemExit("review installer definition not found")
review = review.split(marker, 1)[0] + "\n"
review = review.replace("from typing import Any\n\n", "")
review_path.write_text(review)

test_path = Path("tests/test_native_review_ui_architecture.py")
test_path.write_text('''from pathlib import Path\nimport unittest\n\n\nclass NativeReviewUiArchitectureTests(unittest.TestCase):\n    def test_review_hardening_is_native(self) -> None:\n        main = Path("deduper/main.py").read_text()\n        review = Path("deduper/review_ui.py").read_text()\n        app = Path("deduper/app.py").read_text()\n        self.assertNotIn("install_review_ui_hardening", main + review)\n        self.assertIn("_review_desired_preview_keys", app)\n        self.assertIn("preserved_pair_index", app)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
