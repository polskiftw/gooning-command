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
    '''        self.exclude_button = ttk.Button(
            comparison,
            text="EXCLUDE FROM THIS NUKE",
            command=self._exclude_current,
        )
        self.exclude_button.grid(row=0, column=1, padx=12, pady=(0, 6))
''',
    '''        self.exclude_button_frame = ttk.Frame(comparison)
        self.exclude_button_frame.grid(row=0, column=1, padx=12, pady=(0, 6))
        self.exclude_button = ttk.Button(
            self.exclude_button_frame,
            text="EXCLUDE THIS RUN",
            command=self._exclude_current,
        )
        self.exclude_button.pack(fill="x")
        self.permanent_exclude_button = ttk.Button(
            self.exclude_button_frame,
            text="EXCLUDE PERMANENTLY",
            command=self._exclude_permanently,
        )
        self.permanent_exclude_button.pack(fill="x", pady=(5, 0))
''',
    "native exclusion controls",
)
app = replace_once(
    app,
    '        self.left_meta.pack(fill="x", padx=8, pady=(0, 6))\n',
    '''        self.left_meta.pack(fill="x", padx=8, pady=(0, 6))
        self.left_bye_bitch_button = ttk.Button(
            left_panel,
            text="BYE BITCH",
            style="Danger.TButton",
            command=lambda: self._bye_bitch("left"),
        )
        self.left_bye_bitch_button.pack(fill="x", padx=8, pady=(0, 8))
''',
    "left BYE BITCH control",
)
app = replace_once(
    app,
    '        self.right_meta.pack(fill="x", padx=8, pady=(0, 6))\n',
    '''        self.right_meta.pack(fill="x", padx=8, pady=(0, 6))
        self.right_bye_bitch_button = ttk.Button(
            right_panel,
            text="BYE BITCH",
            style="Danger.TButton",
            command=lambda: self._bye_bitch("right"),
        )
        self.right_bye_bitch_button.pack(fill="x", padx=8, pady=(0, 8))
''',
    "right BYE BITCH control",
)
app = replace_once(
    app,
    '''        self.reverse_delete_button = ttk.Button(
            center,
            text="DELETE LEFT — KEEP RIGHT",
            style="Danger.TButton",
            command=self._delete_left_keep_right,
        )
        self.reverse_delete_button.pack(side="bottom", pady=(0, 14))
''',
    "",
    "obsolete center delete control",
)
app = replace_once(
    app,
    '''        reverse_state = (
            "normal"
            if enabled
            and not self.review_locked
            and not self.reverse_delete_busy
            and self.config.allow_delete
            else "disabled"
        )
        self.reverse_delete_button.configure(state=reverse_state)
''',
    '''        delete_state = (
            "normal"
            if enabled
            and not self.review_locked
            and not self.reverse_delete_busy
            and self.config.allow_delete
            else "disabled"
        )
        self.left_bye_bitch_button.configure(state=delete_state)
        self.right_bye_bitch_button.configure(state=delete_state)
''',
    "side delete state",
)
app, count = re.subn(
    r'\n    def _delete_left_keep_right\(self\) -> None:.*?\n    def _exclude_current\(self\) -> None:',
    '\n    def _exclude_current(self) -> None:',
    app,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"obsolete base delete implementation: expected one block, found {count}")
app_path.write_text(app)

fast_path = Path("deduper/fast_app.py")
fast = fast_path.read_text()
fast = replace_once(fast, '        self._install_exclusion_buttons()\n', '', "post-build exclusion install call")
fast, count = re.subn(
    r'\n    def _install_exclusion_buttons\(self\) -> None:.*?\n    def _set_action_state\(self\) -> None:',
    '\n    def _set_action_state(self) -> None:',
    fast,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"post-build exclusion method: expected one block, found {count}")
fast = fast.replace(
    '            self.reverse_delete_button.configure(state="disabled")',
    '            self.left_bye_bitch_button.configure(state="disabled")\n            self.right_bye_bitch_button.configure(state="disabled")',
)
fast, count = re.subn(
    r'\n    def _delete_left_keep_right\(self\) -> None:.*?\n    def _advance_after_exclusion\(self, message: str\) -> None:',
    '\n    def _advance_after_exclusion(self, message: str) -> None:',
    fast,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"obsolete fast delete override: expected one block, found {count}")
fast_path.write_text(fast)

certified_path = Path("deduper/certified_app.py")
certified = certified_path.read_text()
certified, count = re.subn(
    r'\n    def _build\(self\) -> None:.*?\n    def _resume_pending_family_repairs\(self\) -> None:',
    '\n    def _resume_pending_family_repairs(self) -> None:',
    certified,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"certified post-build controls: expected one block, found {count}")
certified_path.write_text(certified)

Path("tests/test_native_ui_architecture.py").write_text('''from pathlib import Path
import unittest


class NativeUiArchitectureTests(unittest.TestCase):
    def test_production_ui_has_no_obsolete_reverse_delete_path(self) -> None:
        sources = "\\n".join(
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
''')
