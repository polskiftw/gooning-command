from pathlib import Path

app_path = Path('deduper/app.py')
text = app_path.read_text()
replacements = {
    '"Comparison did not finish.\\n\\nSaved results are safe; press SCAN to try again."': '"Comparison did not finish.\\n\\nSaved results are safe; automatic recovery will resume on startup."',
    'self.empty_pair_message = "Not compared yet.\\n\\nPress SCAN to find duplicate pairs."': 'self.empty_pair_message = "No certified comparison exists yet.\\n\\nAutomatic startup is preparing one."',
    'for button in (self.scan_button, self.nuke_button, self.sha_nuke_button):': 'for button in (self.nuke_button, self.sha_nuke_button):',
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f'missing expected app.py anchor: {old}')
    text = text.replace(old, new, 1)
app_path.write_text(text)

test_path = Path('tests/test_automatic_certified_startup.py')
test = test_path.read_text()
old = '''    def test_manual_scan_button_is_hidden(self) -> None:\n        base_source = Path("deduper/app.py").read_text()\n        certified_source = Path("deduper/certified_app.py").read_text()\n        self.assertNotIn('text="SCAN"', base_source)\n        self.assertNotIn("scan_button", certified_source)\n'''
new = '''    def test_manual_scan_surface_is_absent_from_production_ui(self) -> None:\n        production_sources = [\n            Path("deduper/app.py").read_text(),\n            Path("deduper/certified_app.py").read_text(),\n            Path("deduper/fast_app.py").read_text(),\n        ]\n        combined = "\\n".join(production_sources)\n        self.assertNotIn('text="SCAN"', combined)\n        self.assertNotIn("scan_button", combined)\n        self.assertNotIn("Press SCAN", combined)\n        self.assertNotIn("press SCAN", combined)\n'''
if old not in test:
    raise SystemExit('missing automatic startup test anchor')
test_path.write_text(test.replace(old, new, 1))
