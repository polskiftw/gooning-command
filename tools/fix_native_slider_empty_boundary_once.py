from pathlib import Path

path = Path("deduper/fast_app.py")
text = path.read_text()
old = '''            else:
                self.comparison_progress.set(
                    "Permanent index: no certified slider positions yet — press SCAN"
                )
            return
'''
new = '''            else:
                self.comparison_progress.set(
                    "Permanent index: no certified slider positions yet — press SCAN"
                )
            self._apply_certified_slider_lock()
            return
'''
if text.count(old) != 1:
    raise SystemExit(f"empty-boundary path: expected one match, found {text.count(old)}")
path.write_text(text.replace(old, new, 1))
