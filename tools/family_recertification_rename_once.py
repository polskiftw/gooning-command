from pathlib import Path

ROOTS = [Path("deduper"), Path("tests")]
REPLACEMENTS = [
    ("family_repair_queue", "family_recertification_queue"),
    ("family_repair_status", "family_recertification_status"),
    ("PendingFamilyRepair", "PendingFamilyRecertification"),
    ("FamilyRepairQueue", "FamilyRecertificationQueue"),
    ("family_repair_status_text", "family_recertification_status_text"),
    ("_family_repair_queue", "_family_recertification_queue"),
    ("_resume_pending_family_repairs", "_resume_pending_family_recertifications"),
    ("_run_family_repair", "_run_family_recertification"),
    ("_family_repair_finished", "_family_recertification_finished"),
    ("pending_repairs", "pending_recertifications"),
    ("repair_focus_keys", "recertification_focus_keys"),
    ("repair_queue", "recertification_queue"),
    ("repair_id", "recertification_id"),
]

for root in ROOTS:
    for path in root.rglob("*.py"):
        text = path.read_text()
        original = text
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        # User-facing prose and Python comments only. Legacy SQL table names stay
        # unchanged so existing queued work remains readable after upgrade.
        text = text.replace("Family repair", "Family recertification")
        text = text.replace("family repair", "family recertification")
        text = text.replace("repairing", "recertifying")
        text = text.replace("Repairing", "Recertifying")
        text = text.replace("repair attempt", "recertification attempt")
        text = text.replace("repair did not finish", "recertification did not finish")
        if text != original:
            path.write_text(text)

renames = {
    Path("deduper/family_repair_queue.py"): Path("deduper/family_recertification_queue.py"),
    Path("deduper/family_repair_status.py"): Path("deduper/family_recertification_status.py"),
    Path("tests/test_family_repair_queue.py"): Path("tests/test_family_recertification_queue.py"),
    Path("tests/test_family_repair_status.py"): Path("tests/test_family_recertification_status.py"),
}
for old, new in renames.items():
    if not old.exists():
        raise SystemExit(f"missing rename source: {old}")
    if new.exists():
        raise SystemExit(f"rename target already exists: {new}")
    old.rename(new)

# Keep legacy SQL identifiers explicit and documented rather than accidentally
# presenting them as current terminology.
queue = Path("deduper/family_recertification_queue.py")
text = queue.read_text()
marker = 'class FamilyRecertificationQueue:\n    """Crash-safe priority queue for BYE BITCH family recertification."""\n'
replacement = '''class FamilyRecertificationQueue:
    """Crash-safe priority queue for BYE BITCH family recertification.

    The SQLite table names retain their historical ``family_repair_*`` spelling
    solely for in-place database compatibility. They are private storage names,
    not current product terminology.
    """
'''
if text.count(marker) != 1:
    raise SystemExit("queue class marker mismatch")
queue.write_text(text.replace(marker, replacement, 1))

architecture = Path("tests/test_family_recertification_architecture.py")
architecture.write_text('''from pathlib import Path\nimport unittest\n\n\nclass FamilyRecertificationArchitectureTests(unittest.TestCase):\n    def test_current_code_and_ui_use_recertification_language(self) -> None:\n        certified = Path("deduper/certified_app.py").read_text()\n        smart = Path("deduper/smart_app.py").read_text()\n        status = Path("deduper/family_recertification_status.py").read_text()\n        self.assertFalse(Path("deduper/family_repair_queue.py").exists())\n        self.assertFalse(Path("deduper/family_repair_status.py").exists())\n        self.assertIn("FamilyRecertificationQueue", certified)\n        self.assertIn("family_recertification_status_text", certified)\n        self.assertNotIn("Family repair", certified + smart + status)\n        self.assertNotIn("family repair", certified + smart + status)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
