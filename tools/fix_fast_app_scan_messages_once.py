from pathlib import Path

path = Path("deduper/fast_app.py")
text = path.read_text()
replacements = {
    '"Safety lock active: run SCAN before NUKE so the current R2 inventory is certified."': '"Safety lock active while automatic startup certification validates the current R2 inventory."',
    '"NUKE is safety-locked. Run a complete, error-free SCAN to certify "\n                "the current R2 inventory first."': '"NUKE is safety-locked until automatic startup certification validates "\n                "the current R2 inventory."',
    '"Permanent index: no certified slider positions yet — press SCAN"': '"Permanent index: automatic startup certification is still building the first slider position"',
    '"No certified slider positions yet. Press SCAN to begin indexing."': '"No certified slider positions yet. Automatic startup certification is still indexing."',
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"missing expected source text: {old}")
    text = text.replace(old, new)
if "Press SCAN" in text or "press SCAN" in text or "run SCAN" in text or "Run a complete, error-free SCAN" in text:
    raise SystemExit("manual SCAN instruction remains")
path.write_text(text)
