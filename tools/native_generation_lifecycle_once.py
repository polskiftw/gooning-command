from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


certified_path = Path("deduper/certified_app.py")
certified = certified_path.read_text()
certified = replace_once(
    certified,
    'from .frontier_worker import scan_closed_group\n',
    'from .frontier_worker import scan_closed_group\nfrom .generation_app_lifecycle import GenerationAppLifecycle\nfrom .generation_integration import GenerationStartupState\n',
    "generation lifecycle imports",
)
certified = replace_once(
    certified,
    '''    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._family_repair_queue = FamilyRepairQueue(self.database)
        self.after(1000, self._resume_pending_family_repairs)
''',
    '''    def __init__(
        self,
        *args,
        generation_startup: GenerationStartupState,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._family_repair_queue = FamilyRepairQueue(self.database)
        self.after(1000, self._resume_pending_family_repairs)
        self._generation_lifecycle = GenerationAppLifecycle(
            self,
            generation_startup,
        ).install()
''',
    "native generation lifecycle ownership",
)
certified_path.write_text(certified)

main_path = Path("deduper/main.py")
main = main_path.read_text()
main = replace_once(
    main,
    'from deduper.generation_app_lifecycle import attach_generation_lifecycle\n',
    '',
    "attachment import",
)
main = replace_once(
    main,
    '''    app = CertifiedDeduperApp(config, database, store, data_directory, evidence=evidence)
    attach_generation_lifecycle(app, generation_startup)
''',
    '''    app = CertifiedDeduperApp(
        config,
        database,
        store,
        data_directory,
        evidence=evidence,
        generation_startup=generation_startup,
    )
''',
    "native lifecycle construction",
)
main_path.write_text(main)

lifecycle_path = Path("deduper/generation_app_lifecycle.py")
lifecycle = lifecycle_path.read_text()
old = '''\n\ndef attach_generation_lifecycle(\n    app: AppLike,\n    startup: GenerationStartupState,\n) -> GenerationAppLifecycle:\n    lifecycle = GenerationAppLifecycle(app, startup).install()\n    app._generation_lifecycle = lifecycle\n    return lifecycle\n'''
if lifecycle.count(old) != 1:
    raise SystemExit(f"attachment helper: expected exactly one match, found {lifecycle.count(old)}")
lifecycle_path.write_text(lifecycle.replace(old, "\n", 1))

Path("tests/test_native_generation_lifecycle_architecture.py").write_text('''from pathlib import Path\nimport unittest\n\n\nclass NativeGenerationLifecycleArchitectureTests(unittest.TestCase):\n    def test_production_app_owns_generation_lifecycle(self) -> None:\n        main = Path("deduper/main.py").read_text()\n        certified = Path("deduper/certified_app.py").read_text()\n        lifecycle = Path("deduper/generation_app_lifecycle.py").read_text()\n        self.assertNotIn("attach_generation_lifecycle", main + lifecycle)\n        self.assertIn("generation_startup: GenerationStartupState", certified)\n        self.assertIn("self._generation_lifecycle = GenerationAppLifecycle", certified)\n        self.assertIn("generation_startup=generation_startup", main)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
