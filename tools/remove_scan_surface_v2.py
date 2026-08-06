from pathlib import Path

app = Path('deduper/app.py')
text = app.read_text()
old = '        for button in (self.scan_button, self.nuke_button, self.sha_nuke_button):\n            button.configure(state=state)\n'
new = '        for button in (self.nuke_button, self.sha_nuke_button):\n            button.configure(state=state)\n'
if old not in text:
    raise SystemExit('missing action-state scan_button anchor')
text = text.replace(old, new, 1)
text = text.replace('Saved results are safe; press SCAN to try again.', 'Saved results are safe; automatic certification will retry on startup.')
text = text.replace('Not compared yet.\\n\\nPress SCAN to find duplicate pairs.', 'No certified queue exists yet.\\n\\nAutomatic certification begins on startup.')
app.write_text(text)

test = Path('tests/test_no_manual_scan_surface.py')
test.write_text('''from pathlib import Path\nimport unittest\n\n\nclass NoManualScanSurfaceTests(unittest.TestCase):\n    def test_production_ui_has_no_scan_button_symbol_or_instruction(self) -> None:\n        paths = [\n            Path("deduper/app.py"),\n            Path("deduper/certified_app.py"),\n            Path("deduper/fast_app.py"),\n        ]\n        combined = "\\n".join(path.read_text() for path in paths)\n        self.assertNotIn("scan_button", combined)\n        self.assertNotIn("Press SCAN", combined)\n        self.assertNotIn('text="SCAN"', combined)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
