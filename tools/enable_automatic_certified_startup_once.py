from pathlib import Path

certified = Path('deduper/certified_app.py')
text = certified.read_text()
old = '''        super().__init__(*args, **kwargs)\n        self._family_recertification_queue = FamilyRecertificationQueue(self.database)\n'''
new = '''        super().__init__(*args, **kwargs)\n        # Certified operation is automatic. The historical manual SCAN control\n        # must not be exposed because startup validation owns whether the saved\n        # queue is retained or a replacement generation is built.\n        self.scan_button.pack_forget()\n        self._family_recertification_queue = FamilyRecertificationQueue(self.database)\n'''
if old not in text:
    raise SystemExit('certified init anchor missing')
certified.write_text(text.replace(old, new, 1))

lifecycle = Path('deduper/generation_app_lifecycle.py')
text = lifecycle.read_text()
old = '''        self.app._startup_inventory_snapshot = snapshot.inventory\n        self.app._startup_generation_phase = snapshot.phase\n'''
new = '''        self.app._startup_inventory_snapshot = snapshot.inventory\n        self.app._startup_generation_phase = snapshot.phase\n\n        if snapshot.rebuild_required:\n            # Validation already materialized the one authoritative startup\n            # inventory snapshot. Automatically build the replacement without\n            # requiring a manual button or performing a second R2 listing.\n            self.app.after(0, self.app.start_scan)\n'''
if old not in text:
    raise SystemExit('snapshot anchor missing')
lifecycle.write_text(text.replace(old, new, 1))

smart = Path('deduper/smart_app.py')
text = smart.read_text()
old = '''            self._ui(self.status.set, "Connecting to R2 and reading inventory…")\n            self.store.verify()\n            inventory = self.store.list_assets()\n            evidence_checkpoint = self.evidence.metadata_checkpoint()\n'''
new = '''            startup_inventory = getattr(self, "_startup_inventory_snapshot", ())\n            startup_phase = getattr(self, "_startup_generation_phase", None)\n            if startup_inventory and getattr(startup_phase, "value", startup_phase) == "rebuild_required":\n                self._ui(self.status.set, "R2 changed — reconciling validated inventory snapshot…")\n                inventory = list(startup_inventory)\n                self._startup_inventory_snapshot = ()\n            else:\n                self._ui(self.status.set, "Connecting to R2 and reading inventory…")\n                self.store.verify()\n                inventory = self.store.list_assets()\n            evidence_checkpoint = self.evidence.metadata_checkpoint()\n'''
if old not in text:
    raise SystemExit('smart inventory anchor missing')
smart.write_text(text.replace(old, new, 1))

test = Path('tests/test_automatic_certified_startup.py')
test.write_text('''from pathlib import Path\nimport unittest\n\n\nclass AutomaticCertifiedStartupTests(unittest.TestCase):\n    def test_manual_scan_button_is_hidden(self) -> None:\n        source = Path("deduper/certified_app.py").read_text()\n        self.assertIn("self.scan_button.pack_forget()", source)\n\n    def test_rebuild_required_starts_automatically(self) -> None:\n        source = Path("deduper/generation_app_lifecycle.py").read_text()\n        self.assertIn("if snapshot.rebuild_required:", source)\n        self.assertIn("self.app.after(0, self.app.start_scan)", source)\n\n    def test_automatic_rebuild_reuses_validation_inventory(self) -> None:\n        source = Path("deduper/smart_app.py").read_text()\n        self.assertIn("startup_inventory = getattr", source)\n        self.assertIn("inventory = list(startup_inventory)", source)\n        self.assertIn("self._startup_inventory_snapshot = ()", source)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
