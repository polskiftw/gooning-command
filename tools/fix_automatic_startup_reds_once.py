from pathlib import Path

app = Path('deduper/app.py')
text = app.read_text()
old = '''        self.scan_button = ttk.Button(actions, text="SCAN", style="Accent.TButton", command=self.start_scan)\n        self.scan_button.pack(side="left", padx=(0, 8))\n'''
if old not in text:
    raise SystemExit('scan button construction block missing')
text = text.replace(old, '', 1)
app.write_text(text)

certified = Path('deduper/certified_app.py')
text = certified.read_text()
old = '''        # Certified operation is automatic. The historical manual SCAN control\n        # must not be exposed because startup validation owns whether the saved\n        # queue is retained or a replacement generation is built.\n        self.scan_button.pack_forget()\n'''
if old not in text:
    raise SystemExit('scan hiding block missing')
text = text.replace(old, '', 1)
certified.write_text(text)

test = Path('tests/test_generation_app_lifecycle.py')
text = test.read_text()
old = '''        self.boundary_refreshes = 0\n\n    def after(self, delay_ms, callback):\n'''
new = '''        self.boundary_refreshes = 0\n        self.scan_starts = 0\n\n    def start_scan(self):\n        self.scan_starts += 1\n\n    def after(self, delay_ms, callback):\n'''
if old not in text:
    raise SystemExit('FakeApp insertion anchor missing')
text = text.replace(old, new, 1)
old = '''        self.assertIn("deletion locked", app.status.get())\n\n\nif __name__ == "__main__":\n'''
new = '''        self.assertIn("deletion locked", app.status.get())\n        self.assertEqual(len(app.after_calls), 1)\n        delay, callback = app.after_calls[0]\n        self.assertEqual(delay, 0)\n        callback()\n        self.assertEqual(app.scan_starts, 1)\n\n\nif __name__ == "__main__":\n'''
if old not in text:
    raise SystemExit('rebuild assertion anchor missing')
text = text.replace(old, new, 1)
test.write_text(text)

auto = Path('tests/test_automatic_certified_startup.py')
text = auto.read_text()
text = text.replace('''        source = Path("deduper/certified_app.py").read_text()\n        self.assertIn("self.scan_button.pack_forget()", source)\n''', '''        base_source = Path("deduper/app.py").read_text()\n        certified_source = Path("deduper/certified_app.py").read_text()\n        self.assertNotIn('text="SCAN"', base_source)\n        self.assertNotIn("scan_button", certified_source)\n''')
auto.write_text(text)
