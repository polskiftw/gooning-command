from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


app_path = Path("deduper/app.py")
app = app_path.read_text()
app = replace_once(
    app,
    '''        ttk.Scale(
            actions,
            from_=0,
            to=99,
            variable=self.slider,
            orient="horizontal",
            length=300,
            takefocus=False,
        ).pack(side="left")
''',
    '''        self.slider_widget = ttk.Scale(
            actions,
            from_=0,
            to=99,
            variable=self.slider,
            orient="horizontal",
            length=300,
            takefocus=False,
        )
        self.slider_widget.pack(side="left")
''',
    "owned slider widget",
)
app_path.write_text(app)

fast_path = Path("deduper/fast_app.py")
fast = fast_path.read_text()
fast = replace_once(
    fast,
    '''        self._set_review_state(bool(self.pairs))
        self.status.set(
            "Safety lock active: run SCAN before NUKE so the current R2 inventory is certified."
        )
''',
    '''        self._set_review_state(bool(self.pairs))
        self._apply_certified_slider_lock()
        self.status.set(
            "Safety lock active: run SCAN before NUKE so the current R2 inventory is certified."
        )
''',
    "initial slider lock",
)
fast = replace_once(
    fast,
    '''    def _set_action_state(self) -> None:
        super()._set_action_state()
        if not self._inventory_verified_for_delete:
            self.nuke_button.configure(state="disabled")
            self.sha_nuke_button.configure(state="disabled")
''',
    '''    def _set_action_state(self) -> None:
        super()._set_action_state()
        if not self._inventory_verified_for_delete:
            self.nuke_button.configure(state="disabled")
            self.sha_nuke_button.configure(state="disabled")
        if hasattr(self, "slider_widget"):
            self.after_idle(self._apply_certified_slider_lock)

    def _apply_certified_slider_lock(self) -> None:
        if not hasattr(self, "slider_widget"):
            return
        boundary = self.evidence.loosest_complete_slider()
        busy = bool(self.busy or self.reverse_delete_busy)
        self._slider_guard = True
        try:
            if boundary is None:
                self.slider_widget.configure(from_=99, to=99, state="disabled")
                self.slider.set(99)
                return
            boundary = max(0, min(99, int(boundary)))
            requested = max(boundary, min(99, int(round(self.slider.get()))))
            self.slider_widget.configure(
                from_=boundary,
                to=99,
                state="disabled" if busy else "normal",
            )
            self.slider.set(requested)
        finally:
            self._slider_guard = False
''',
    "native slider lock methods",
)
fast = replace_once(
    fast,
    '''    def _slider_changed(self, *_args) -> None:
        if self._slider_guard:
            return
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
        self._slider_after_id = self.after(180, self._apply_slider_view)
''',
    '''    def _slider_changed(self, *_args) -> None:
        if self._slider_guard:
            return
        boundary = self.evidence.loosest_complete_slider()
        requested = int(round(self.slider.get()))
        if (
            boundary is None
            or self.busy
            or self.reverse_delete_busy
            or requested < int(boundary)
            or requested > 99
        ):
            self._apply_certified_slider_lock()
            return
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
        self._slider_after_id = self.after(180, self._apply_slider_view)
''',
    "guarded slider change",
)
fast = replace_once(
    fast,
    '''        if apply and not self.busy:
            self._apply_slider_view()
''',
    '''        self._apply_certified_slider_lock()
        if apply and not self.busy:
            self._apply_slider_view()
''',
    "boundary slider lock",
)
# Disable immediately before any scan implementation begins.
fast = replace_once(
    fast,
    '''    def start_scan(self) -> None:
''',
    '''    def start_scan(self) -> None:
        self.slider_widget.configure(state="disabled")
''',
    "scan slider disable",
)
fast_path.write_text(fast)

main_path = Path("deduper/main.py")
main = main_path.read_text()
main = replace_once(main, 'from deduper.certified_slider import install_certified_slider_lock\n', '', "slider installer import")
main = replace_once(main, '    install_certified_slider_lock(CertifiedDeduperApp)\n', '', "slider installer call")
main_path.write_text(main)

slider_path = Path("deduper/certified_slider.py")
slider = slider_path.read_text()
if "install_certified_slider_lock" not in slider:
    raise SystemExit("certified slider installer missing before deletion")
slider_path.unlink()

test_path = Path("tests/test_native_slider_architecture.py")
test_path.write_text('''from pathlib import Path\nimport unittest\n\n\nclass NativeSliderArchitectureTests(unittest.TestCase):\n    def test_slider_lock_is_native(self) -> None:\n        main = Path("deduper/main.py").read_text()\n        fast = Path("deduper/fast_app.py").read_text()\n        app = Path("deduper/app.py").read_text()\n        self.assertNotIn("install_certified_slider_lock", main)\n        self.assertFalse(Path("deduper/certified_slider.py").exists())\n        self.assertIn("self.slider_widget = ttk.Scale", app)\n        self.assertIn("def _apply_certified_slider_lock", fast)\n        self.assertIn('self.slider_widget.configure(state="disabled")', fast)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
