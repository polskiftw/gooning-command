from __future__ import annotations

from .certified_group_admission import admit_closed_frontier_group, preview_projection
from .certified_queue import CertifiedQueue
from .evidence_inventory import reconcile_asset_inventory
from .fast_app import FastDeduperApp
from .focused_recertification import recertify_added_or_changed_assets
from .matcher import partition_exact_duplicates
from .progressive_group_indexer import run_progressive_group_index
from .progressive_indexer import IndexingCancelled
from .scanner import scan_assets


class SmartDeduperApp(FastDeduperApp):
    """Fast deduper with targeted recertification for inventory deltas."""

    def start_scan(self) -> None:
        self.scan_cancel.clear()
        self._streaming_ready_slider = None
        self._streaming_ready_pairs = 0
        self._inventory_verified_for_delete = False
        self._scan_completed_current_inventory = False

        # Review rows from an interrupted/older scan must never be presented as
        # CERTIFIED for this new session. They are disposable UI projections and
        # are repopulated only from whole, closed, immutable certified families.
        self.database.replace_pairs([], preserve_exclusions=True)
        self._refresh_pairs()
        self._set_action_state()
        self._set_review_state(False)

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
            visual_assets, sha_deletions = partition_exact_duplicates(assets)
            sha_target_count = self.database.replace_sha_deletions(sha_deletions)
            certified_queue = CertifiedQueue()
            self._active_certified_queue = certified_queue
            self.database.set_matching_state("running")
            self._ui(
                self._set_empty_pair_message,
                "Indexing from Strict toward Loose…\n\n"
                "A review group appears only after the entire connected family has been "
                "exhaustively checked against the complete current inventory at that threshold. "
                "New certified families may re-sort the queue, but an admitted family's members, "
                "survivor, and deletion relationships cannot change.",
            )

            delta = evidence_sync.delta
            focus_keys = set(delta.added) | set(delta.changed)
            incremental = None
            if errors == 0 and focus_keys and old_boundary is not None and old_fingerprint:
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

            def publish_queue(slider: int) -> int:
                pairs = preview_projection(certified_queue)
                target_count = self.database.replace_pairs(
                    pairs,
                    preserve_exclusions=True,
                )
                self._streaming_ready_slider = slider
                self._streaming_ready_pairs = target_count
                self._ui(self._refresh_pairs)
                self._ui(lambda: self._refresh_index_boundary(apply=False))
                return target_count

            def group_progress(band, result, seed_count: int) -> None:
                nonlocal completed_groups
                admission = admit_closed_frontier_group(
                    certified_queue,
                    self.evidence,
                    visual_assets,
                    result,
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
                target_count = publish_queue(band.loosest_slider)
                self._ui(
                    self.status.set,
                    (
                        f"CERTIFIED whole family {completed_groups}: "
                        f"{len(result.group.members)} members at slider {band.loosest_slider}; "
                        f"{target_count} final review pairs available. Queue positions may re-sort "
                        "by percentage; certified family relationships are frozen."
                    ),
                )

            def band_progress(result) -> None:
                nonlocal completed_bands
                completed_bands += 1
                self._streaming_ready_slider = result.band.loosest_slider
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
                    f"{completed_groups} certified whole families; unlocked through slider "
                    f"{boundary_text}. Unfinished families never entered preview; NUKE remains locked."
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
            self.database.set_matching_state("complete")
            if errors == 0 and boundary == 0:
                self._scan_completed_current_inventory = True
                safety_summary = "NUKE unlocked for this app session"
            elif errors:
                safety_summary = f"NUKE remains locked because {errors} hash errors remain"
            else:
                safety_summary = "NUKE remains locked because the full index is incomplete"
            return (
                f"Scan complete. {new_count} new, {changed_count} changed, "
                f"{missing_count} missing, {errors} errors, "
                f"{sha_target_count} invisible SHA extras, {observed_edges} permanent evidence edges, "
                f"{completed_groups} certified whole families, {completed_bands} newly certified bands, "
                f"index unlocked through slider {boundary_text}; {cache_summary}; {safety_summary}."
            )

        self._run("Starting smart incremental scan…", scan, self._scan_finished, lock_review=False)
