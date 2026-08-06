from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("deduper/smart_app.py")
text = path.read_text()

text = replace_once(
    text,
    'from .focused_recertification import recertify_added_or_changed_assets\n',
    'from .focused_recertification import recertify_added_or_changed_assets\nfrom .generation_builder import CertifiedGenerationBuilder\n',
    "generation builder import",
)
text = replace_once(
    text,
    'from .survivor_orientation import partition_exact_duplicates\n',
    'from .survivor_orientation import partition_exact_duplicates\nfrom .survivor_policy import matcher_identity\n',
    "matcher identity import",
)

text = replace_once(
    text,
    '''        self.database.replace_pairs([], preserve_exclusions=True)
        self._refresh_pairs()
        self._set_action_state()
        self._set_review_state(False)
''',
    '''        # The active certified generation remains visible and immutable while
        # a replacement is built privately. Busy-state gating disables review
        # actions without clearing or progressively rewriting the saved queue.
        self._set_action_state()
        self._set_review_state(bool(self.pairs))
''',
    "preserve active queue at scan start",
)

text = replace_once(
    text,
    '''            sha_target_count = self.database.replace_sha_deletions(sha_deletions)
            certified_queue = CertifiedQueue()
            self._active_certified_queue = certified_queue
            self.database.set_matching_state("running")
''',
    '''            sha_target_count = len(sha_deletions)
            certified_queue = CertifiedQueue()
            certified_queue.admit_sha_deletions(sha_deletions)
''',
    "private staging queue",
)

start = text.index('            def publish_queue(slider: int) -> int:\n')
end = text.index('            def group_progress(band, result, seed_count: int) -> None:\n', start)
text = text[:start] + text[end:]

text = replace_once(
    text,
    '''                target_count = publish_queue(band.loosest_slider)
                self._ui(
                    self.status.set,
                    (
                        f"CERTIFIED whole family {completed_groups}: "
                        f"{len(result.group.members)} members at slider {band.loosest_slider}; "
                        f"{target_count} final review pairs available. Queue positions may re-sort "
                        "by percentage; certified family relationships are frozen."
                    ),
                )
''',
    '''                staged_count = len(certified_queue.pairs())
                self._ui(
                    self.status.set,
                    (
                        f"STAGED whole family {completed_groups}: "
                        f"{len(result.group.members)} members at slider {band.loosest_slider}; "
                        f"{staged_count} replacement review pairs prepared privately. "
                        "The active certified queue remains unchanged until atomic promotion."
                    ),
                )
''',
    "private group progress",
)

text = replace_once(
    text,
    '''                self._streaming_ready_slider = result.band.loosest_slider
                self._streaming_ready_pairs = len(certified_queue.pairs())
                self._ui(self._progressive_band_completed, result)
                self._ui(lambda: self._refresh_index_boundary(apply=False))
                self._ui(
                    self.status.set,
                    (
                        f"CERTIFIED band {result.band.strictest_slider}–"
                        f"{result.band.loosest_slider} complete: "
                        f"{len(certified_queue.pairs())} preview pairs from immutable whole families. "
                        "The slider can now use this completed band."
                    ),
                )
''',
    '''                self._ui(
                    self.status.set,
                    (
                        f"STAGED band {result.band.strictest_slider}–"
                        f"{result.band.loosest_slider} complete: "
                        f"{len(certified_queue.pairs())} replacement pairs prepared privately. "
                        "Nothing has been published to review yet."
                    ),
                )
''',
    "private band progress",
)

text = replace_once(
    text,
    '''                return (
                    f"Indexing stopped safely after {completed_bands} completed bands and "
                    f"{completed_groups} certified whole families; unlocked through slider "
                    f"{boundary_text}. Unfinished families never entered preview; NUKE remains locked."
                )
''',
    '''                return (
                    f"Indexing stopped safely after {completed_bands} completed bands and "
                    f"{completed_groups} staged whole families; computed through slider "
                    f"{boundary_text}. Staging was not promoted; the previous certified queue "
                    "remains unchanged and NUKE remains locked."
                )
''',
    "cancelled staging message",
)

text = replace_once(
    text,
    '''            self.database.set_matching_state("complete")
            if errors == 0 and boundary == 0:
                self._scan_completed_current_inventory = True
                safety_summary = "NUKE unlocked for this app session"
                if repair_queue is not None:
                    for repair in pending_repairs:
                        repair_queue.complete(repair.repair_id)
            elif errors:
                safety_summary = f"NUKE remains locked because {errors} hash errors remain"
            else:
                safety_summary = "NUKE remains locked because the full index is incomplete"
''',
    '''            promoted_pair_count = 0
            if errors == 0 and boundary == 0:
                generations = self._generation_lifecycle.startup.store
                builder = CertifiedGenerationBuilder(
                    generations,
                    inventory,
                    int(round(self.slider.get())),
                    lambda _inventory, _slider, _cancelled: certified_queue.payload(),
                    matcher_version=matcher_identity(self.config.survivor_policy),
                )
                build_result = builder.build()
                promoted_pair_count = self.database.replace_pairs(
                    preview_projection(certified_queue),
                    preserve_exclusions=True,
                )
                self.database.replace_sha_deletions(sha_deletions)
                self.database.set_matching_state("complete")
                self._active_certified_queue = certified_queue
                self._generation_lifecycle.startup = type(
                    self._generation_lifecycle.startup
                )(
                    store=generations,
                    active_generation=build_result.generation,
                    legacy_view_only_generation_id=(
                        self._generation_lifecycle.startup.legacy_view_only_generation_id
                    ),
                )
                self._scan_completed_current_inventory = True
                safety_summary = (
                    f"atomically promoted {promoted_pair_count} certified review pairs; "
                    "NUKE unlocked for this app session"
                )
                if repair_queue is not None:
                    for repair in pending_repairs:
                        repair_queue.complete(repair.repair_id)
            elif errors:
                safety_summary = (
                    f"staging not promoted; previous certified queue retained; "
                    f"NUKE remains locked because {errors} hash errors remain"
                )
            else:
                safety_summary = (
                    "staging not promoted; previous certified queue retained; "
                    "NUKE remains locked because the full index is incomplete"
                )
''',
    "atomic generation promotion",
)

text = replace_once(
    text,
    '''        self._run("Starting smart incremental scan…", scan, self._scan_finished, lock_review=False)
''',
    '''        self._run("Building replacement certified generation…", scan, self._scan_finished, lock_review=False)

    def _scan_finished(self) -> None:
        if self._scan_completed_current_inventory:
            self._inventory_verified_for_delete = True
        self._set_action_state()
        self._set_review_state(bool(self.pairs))
        # Do not call apply=True here: the mutable evidence cache is construction
        # material, not authority for replacing the newly promoted generation.
        self._refresh_index_boundary(apply=False)
        self._refresh_pairs()
''',
    "generation-safe scan completion",
)

path.write_text(text)

Path("tests/test_atomic_generation_scan_architecture.py").write_text('''from pathlib import Path\nimport unittest\n\n\nclass AtomicGenerationScanArchitectureTests(unittest.TestCase):\n    def test_scan_does_not_publish_visible_queue_progressively(self) -> None:\n        smart = Path("deduper/smart_app.py").read_text()\n        self.assertNotIn("def publish_queue", smart)\n        self.assertNotIn("self.database.replace_pairs([], preserve_exclusions=True)", smart)\n        self.assertIn("CertifiedGenerationBuilder", smart)\n        self.assertIn("builder.build()", smart)\n        self.assertIn("previous certified queue retained", smart)\n        self.assertIn("self._refresh_index_boundary(apply=False)", smart)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
