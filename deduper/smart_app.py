from __future__ import annotations

from .certified_group_admission import admit_closed_frontier_group, preview_projection
from .certified_queue import CertifiedQueue
from .evidence_inventory import reconcile_asset_inventory
from .fast_app import FastDeduperApp
from .focused_recertification import recertify_added_or_changed_assets
from .generation_builder import CertifiedGenerationBuilder
from .progressive_group_indexer import run_progressive_group_index
from .progressive_indexer import IndexingCancelled
from .scanner import scan_assets
from .survivor_orientation import partition_exact_duplicates
from .survivor_policy import matcher_identity


class SmartDeduperApp(FastDeduperApp):
    """Fast deduper with targeted recertification for inventory deltas."""

    def start_scan(self) -> None:
        self.scan_cancel.clear()
        self._streaming_ready_slider = None
        self._streaming_ready_pairs = 0
        self._inventory_verified_for_delete = False
        self._scan_completed_current_inventory = False

        # The active certified generation remains visible and immutable while
        # a replacement is built privately. Busy-state gating disables review
        # actions without clearing or progressively rewriting the saved queue.
        self._set_action_state()
        self._set_review_state(bool(self.pairs))

        def scan() -> str:
            self._ui(self.status.set, "Connecting to R2 and reading inventory…")
            self.store.verify()
            inventory = self.store.list_assets()
            old_fingerprint = self.evidence.get_state("inventory_fingerprint")
            old_boundary = self.evidence.loosest_complete_slider()
            evidence_sync = reconcile_asset_inventory(self.evidence, inventory)
            live_keys = {asset.key for asset in inventory}
            new_count, changed_count = self.database.upsert_inventory(inventory)
            missing_count = self.database.mark_missing_deleted(live_keys)
            pending = list(self.database.assets_needing_hashes())

            def hash_progress(completed: int, total: int, key: str) -> None:
                self._ui(self.status.set, f"HASH {completed}/{total} — {key}")

            completed, errors = scan_assets(
                pending,
                self.store,
                self.config,
                self.database.save_hashes,
                hash_progress,
                self.scan_cancel,
            )
            if self.scan_cancel.is_set() and completed < len(pending):
                return (
                    f"Scan stopped safely. Saved {completed}/{len(pending)} completed objects; "
                    "unfinished objects will resume next scan. NUKE remains locked."
                )

            assets = self.database.all_hashed_assets()
            visual_assets, sha_deletions = partition_exact_duplicates(
                assets,
                self.config.survivor_policy,
            )
            sha_target_count = len(sha_deletions)
            certified_queue = CertifiedQueue()
            certified_queue.admit_sha_deletions(sha_deletions)
            self._ui(
                self._set_empty_pair_message,
                "Indexing from Strict toward Loose…\n\n"
                "A review group appears only after the entire connected family has been "
                "exhaustively checked against the complete current inventory at that threshold. "
                "New certified families may re-sort the queue, but an admitted family's members, "
                "survivor, and deletion relationships cannot change.",
            )

            repair_queue = getattr(self, "_family_repair_queue", None)
            pending_repairs = repair_queue.pending() if repair_queue is not None else ()
            repair_focus_keys = {
                key
                for repair in pending_repairs
                for key in repair.priority_keys
                if key in live_keys
            }
            delta = evidence_sync.delta
            focus_keys = set(delta.added) | set(delta.changed) | repair_focus_keys
            incremental = None
            if errors == 0 and focus_keys and old_boundary is not None and old_fingerprint:
                if repair_focus_keys:
                    self._ui(
                        self.status.set,
                        f"Repairing {len(repair_focus_keys)} protected family survivors first…",
                    )
                else:
                    self._ui(
                        self.status.set,
                        f"Focused incremental comparison for {len(focus_keys)} new/changed objects…",
                    )
                try:
                    incremental = recertify_added_or_changed_assets(
                        self.evidence,
                        visual_assets,
                        focus_keys,
                        old_fingerprint=old_fingerprint,
                        old_boundary=old_boundary,
                        new_fingerprint=evidence_sync.fingerprint,
                        cancelled=self.scan_cancel.is_set,
                    )
                except Exception:
                    incremental = None
                    self.evidence.set_state("loosest_complete_slider", "100")
                    self.evidence.set_state("build_status", "dirty")

            completed_bands = 0
            completed_groups = 0

            def group_progress(band, result, seed_count: int) -> None:
                nonlocal completed_groups
                admission = admit_closed_frontier_group(
                    certified_queue,
                    self.evidence,
                    visual_assets,
                    result,
                    survivor_policy=self.config.survivor_policy,
                )
                if result.group is None:
                    self._ui(
                        self.status.set,
                        (
                            f"Band {band.strictest_slider}–{band.loosest_slider}: "
                            f"seed {result.seed_key} frontier processed after {seed_count} seeds; "
                            f"{len(result.members)} discovered members. Whole family unfinished — "
                            "nothing was added to preview."
                        ),
                    )
                    return
                if admission.admitted:
                    completed_groups += 1
                staged_count = len(certified_queue.pairs())
                self._ui(
                    self.status.set,
                    (
                        f"STAGED whole family {completed_groups}: "
                        f"{len(result.group.members)} members at slider {band.loosest_slider}; "
                        f"{staged_count} replacement review pairs prepared privately. "
                        "The active certified queue remains unchanged until atomic promotion."
                    ),
                )

            def band_progress(result) -> None:
                nonlocal completed_bands
                completed_bands += 1
                self._ui(
                    self.status.set,
                    (
                        f"STAGED band {result.band.strictest_slider}–"
                        f"{result.band.loosest_slider} complete: "
                        f"{len(certified_queue.pairs())} replacement pairs prepared privately. "
                        "Nothing has been published to review yet."
                    ),
                )

            try:
                if incremental is None:
                    self._ui(
                        self.status.set,
                        "Building permanent index independently from Strict toward Loose…",
                    )
                else:
                    self._ui(
                        self.status.set,
                        (
                            f"Focused recertification complete for {incremental.focus_assets} objects; "
                            "checking for any unfinished historical bands…"
                        ),
                    )
                run_progressive_group_index(
                    self.evidence,
                    visual_assets,
                    compare_workers=self.config.compare_workers,
                    cancelled=self.scan_cancel.is_set,
                    band_progress=band_progress,
                    group_progress=group_progress,
                )
            except IndexingCancelled:
                boundary = self.evidence.loosest_complete_slider()
                boundary_text = "none" if boundary is None else str(boundary)
                return (
                    f"Indexing stopped safely after {completed_bands} completed bands and "
                    f"{completed_groups} staged whole families; computed through slider "
                    f"{boundary_text}. Staging was not promoted; the previous certified queue "
                    "remains unchanged and NUKE remains locked."
                )

            observed_edges = self.evidence.edge_count()
            boundary = self.evidence.loosest_complete_slider()
            boundary_text = "none" if boundary is None else str(boundary)
            if evidence_sync.cache_was_current:
                cache_summary = "evidence inventory unchanged"
            elif incremental is not None:
                cache_summary = (
                    f"focused incremental: {incremental.focus_assets} objects across "
                    f"{incremental.bands_recertified} completed bands, "
                    f"{incremental.edges_written} evidence edges, "
                    f"{incremental.groups_certified} groups recertified"
                )
            else:
                cache_summary = (
                    f"evidence inventory: {len(delta.added)} added, "
                    f"{len(delta.changed)} changed, {len(delta.removed)} removed"
                )
            promoted_pair_count = 0
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
            return (
                f"Scan complete. {new_count} new, {changed_count} changed, "
                f"{missing_count} missing, {errors} errors, "
                f"{sha_target_count} invisible SHA extras, {observed_edges} permanent evidence edges, "
                f"{completed_groups} certified whole families, {completed_bands} newly certified bands, "
                f"index unlocked through slider {boundary_text}; {cache_summary}; {safety_summary}."
            )

        self._run("Building replacement certified generation…", scan, self._scan_finished, lock_review=False)

    def _scan_finished(self) -> None:
        if self._scan_completed_current_inventory:
            self._inventory_verified_for_delete = True
        self._set_action_state()
        self._set_review_state(bool(self.pairs))
        # Do not call apply=True here: the mutable evidence cache is construction
        # material, not authority for replacing the newly promoted generation.
        self._refresh_index_boundary(apply=False)
        self._refresh_pairs()
