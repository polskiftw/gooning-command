from __future__ import annotations

import threading
from tkinter import ttk

from .app import DeduperApp
from .cache_view import cached_pairs_for_slider, ready_pairs_for_slider
from .evidence_inventory import reconcile_asset_inventory
from .evidence_store import EvidenceStore
from .matcher import partition_exact_duplicates
from .progressive_group_indexer import run_progressive_group_index
from .progressive_indexer import IndexingCancelled
from .scanner import scan_assets


class FastDeduperApp(DeduperApp):
    """Deduper UI with a bounded concurrent, resumable scan pipeline."""

    def __init__(self, *args, evidence: EvidenceStore, **kwargs):
        self.scan_cancel = threading.Event()
        self.evidence = evidence
        self._slider_guard = False
        self._slider_after_id: str | None = None
        self._streaming_ready_slider: int | None = None
        self._streaming_ready_pairs = 0
        self._inventory_verified_for_delete = False
        self._scan_completed_current_inventory = False
        super().__init__(*args, **kwargs)
        self.slider.trace_add("write", self._slider_changed)
        self._refresh_index_boundary(apply=False)
        self._show_current_pair()
        self._set_action_state()
        self._set_review_state(bool(self.pairs))
        self._apply_certified_slider_lock()
        self.status.set(
            "Safety lock active while automatic startup certification validates the current R2 inventory."
        )

    def _set_action_state(self) -> None:
        super()._set_action_state()
        if not self._inventory_verified_for_delete:
            self.nuke_button.configure(state="disabled")
            self.sha_nuke_button.configure(state="disabled")
        if hasattr(self, "slider_widget"):
            self.after_idle(self._apply_certified_slider_lock)

    def _apply_certified_slider_lock(self) -> None:
        if not hasattr(self, "slider_widget"):
            return
        boundary = self.evidence.loosest_complete_slider()
        busy = bool(self.busy or self.reverse_delete_busy)
        self._slider_guard = True
        try:
            if boundary is None:
                self.slider_widget.configure(from_=99, to=99, state="disabled")
                self.slider.set(99)
                return
            boundary = max(0, min(99, int(boundary)))
            requested = max(boundary, min(99, int(round(self.slider.get()))))
            self.slider_widget.configure(
                from_=boundary,
                to=99,
                state="disabled" if busy else "normal",
            )
            self.slider.set(requested)
        finally:
            self._slider_guard = False

    def _show_current_pair(self) -> None:
        super()._show_current_pair()
        if not hasattr(self, "permanent_exclude_button"):
            return
        if not self.pairs:
            self.exclude_button.configure(text="EXCLUDE THIS RUN", state="disabled")
            self.permanent_exclude_button.configure(
                text="EXCLUDE PERMANENTLY",
                state="disabled",
            )
            return
        pair = self.pairs[self.pair_index]
        if pair.status == "excluded":
            self.exclude_button.configure(text="EXCLUDED", state="disabled")
            self.permanent_exclude_button.configure(state="disabled")
        else:
            state = "disabled" if self.review_locked else "normal"
            self.exclude_button.configure(text="EXCLUDE THIS RUN", state=state)
            self.permanent_exclude_button.configure(
                text="EXCLUDE PERMANENTLY",
                state=state,
            )
        if not self._inventory_verified_for_delete:
            self.left_bye_bitch_button.configure(state="disabled")
            self.right_bye_bitch_button.configure(state="disabled")

    def _set_review_state(self, enabled: bool) -> None:
        super()._set_review_state(enabled)
        if not self._inventory_verified_for_delete:
            self.left_bye_bitch_button.configure(state="disabled")
            self.right_bye_bitch_button.configure(state="disabled")
        if not hasattr(self, "permanent_exclude_button"):
            return
        state = "normal" if enabled and not self.review_locked else "disabled"
        self.permanent_exclude_button.configure(state=state)
        if self.pairs and self.pairs[self.pair_index].status == "excluded":
            self.exclude_button.configure(state="disabled")
            self.permanent_exclude_button.configure(state="disabled")

    def _start_nuke(self, *, sha_only: bool) -> None:
        if not self._inventory_verified_for_delete:
            self.status.set(
                "NUKE is safety-locked until automatic startup certification validates "
                "the current R2 inventory."
            )
            return
        super()._start_nuke(sha_only=sha_only)

    def _advance_after_exclusion(self, message: str) -> None:
        self.status.set(message)
        self._refresh_counts()
        self.pairs = self.database.scan_pairs()
        if self.pairs:
            self.pair_index = (self.pair_index + 1) % len(self.pairs)
        else:
            self.pair_index = 0
        self._show_current_pair()

    def _exclude_current(self) -> None:
        if not self.pairs:
            return
        pair = self.pairs[self.pair_index]
        if pair.status == "excluded":
            return
        if not self.database.exclude_pair_keys(pair.left_key, pair.right_key):
            self._refresh_pairs()
            return
        self._advance_after_exclusion(
            f"Excluded for this run only: {pair.left_key} ↔ {pair.right_key}"
        )

    def _exclude_permanently(self) -> None:
        if not self.pairs:
            return
        pair = self.pairs[self.pair_index]
        if pair.status == "excluded":
            return
        exclude_permanently = getattr(self.database, "exclude_pair_permanently", None)
        if exclude_permanently is None:
            self.status.set("Permanent exclusion is unavailable in this build.")
            return
        if not exclude_permanently(pair.left_key, pair.right_key):
            self._refresh_pairs()
            return
        self._advance_after_exclusion(
            f"Permanently excluded unchanged pair: {pair.left_key} ↔ {pair.right_key}"
        )

    def _slider_changed(self, *_args) -> None:
        if self._slider_guard:
            return
        boundary = self.evidence.loosest_complete_slider()
        requested = int(round(self.slider.get()))
        if (
            boundary is None
            or self.busy
            or self.reverse_delete_busy
            or requested < int(boundary)
            or requested > 99
        ):
            self._apply_certified_slider_lock()
            return
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
        self._slider_after_id = self.after(180, self._apply_slider_view)

    def _refresh_index_boundary(self, *, apply: bool) -> None:
        boundary = self.evidence.loosest_complete_slider()
        requested = int(round(self.slider.get()))
        if boundary is None:
            if self._streaming_ready_slider is not None:
                self.comparison_progress.set(
                    f"Early READY: {self._streaming_ready_pairs} certified pairs at slider "
                    f"{self._streaming_ready_slider}; full band still indexing"
                )
            else:
                self.comparison_progress.set(
                    "Permanent index: automatic startup certification is still building the first slider position"
                )
            self._apply_certified_slider_lock()
            return
        if requested < boundary:
            self._slider_guard = True
            try:
                self.slider.set(boundary)
            finally:
                self._slider_guard = False
            requested = boundary
        safety = "  •  NUKE VERIFIED" if self._inventory_verified_for_delete else "  •  NUKE LOCKED"
        self.comparison_progress.set(
            f"Permanent index READY: slider {boundary}–99  •  selected {requested}{safety}"
        )
        self._apply_certified_slider_lock()
        if apply and not self.busy:
            self._apply_slider_view()

    def _apply_slider_view(self) -> None:
        self._slider_after_id = None
        if self.busy or self.reverse_delete_busy:
            return
        boundary = self.evidence.loosest_complete_slider()
        if boundary is None:
            if self._streaming_ready_slider is not None:
                self.status.set(
                    "Only early certified groups are available while indexing continues; "
                    "the slider unlocks after a complete band finishes."
                )
            else:
                self.status.set("No certified slider positions yet. Automatic startup certification is still indexing.")
            return

        requested = int(round(self.slider.get()))
        if requested < boundary:
            self._slider_guard = True
            try:
                self.slider.set(boundary)
            finally:
                self._slider_guard = False
            requested = boundary
            self.status.set(
                f"Slider clamped to {boundary}; looser positions are still indexing."
            )

        slider = requested

        def load_view() -> str:
            assets = self.database.all_hashed_assets()
            pairs = cached_pairs_for_slider(self.evidence, assets, slider)
            target_count = self.database.replace_pairs(
                pairs,
                preserve_exclusions=True,
            )
            self.database.set_matching_state("complete")
            return (
                f"READY slider {slider}: {target_count} stable deletion candidates "
                f"from the certified permanent index."
            )

        self._run(
            f"Loading certified slider {slider} view…",
            load_view,
            self._refresh_pairs,
            lock_review=True,
        )

    def start_scan(self) -> None:
        self.slider_widget.configure(state="disabled")
        self.scan_cancel.clear()
        self._streaming_ready_slider = None
        self._streaming_ready_pairs = 0
        self._inventory_verified_for_delete = False
        self._scan_completed_current_inventory = False
        self._set_action_state()
        self._set_review_state(bool(self.pairs))

        def scan() -> str:
            self._ui(self.status.set, "Connecting to R2 and reading inventory…")
            self.store.verify()
            inventory = self.store.list_assets()
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
            self.database.set_matching_state("running")
            self._ui(
                self._set_empty_pair_message,
                "Indexing from Strict toward Loose…\n\nCertified groups will appear here as soon as they close.",
            )

            completed_bands = 0
            completed_groups = 0

            def publish_ready_groups(slider: int) -> int:
                pairs = ready_pairs_for_slider(self.evidence, visual_assets, slider)
                target_count = self.database.replace_pairs(
                    pairs,
                    preserve_exclusions=True,
                )
                self._streaming_ready_slider = slider
                self._streaming_ready_pairs = target_count
                self._ui(self._refresh_pairs)
                self._ui(self._refresh_index_boundary, apply=False)
                return target_count

            def group_progress(band, result, seed_count: int) -> None:
                nonlocal completed_groups
                if result.group is None:
                    self._ui(
                        self.status.set,
                        (
                            f"Band {band.strictest_slider}–{band.loosest_slider}: "
                            f"seed {result.seed_key} still open after {seed_count} seeds; "
                            f"{len(result.members)} discovered members."
                        ),
                    )
                    return

                completed_groups += 1
                target_count = publish_ready_groups(band.loosest_slider)
                self._ui(
                    self.status.set,
                    (
                        f"CERTIFIED group {completed_groups}: {len(result.group.members)} members "
                        f"at slider {band.loosest_slider}; {target_count} READY review pairs "
                        "published while the rest of the band continues."
                    ),
                )

            def band_progress(result) -> None:
                nonlocal completed_bands
                completed_bands += 1
                self._ui(self._progressive_band_completed, result)

            try:
                self._ui(
                    self.status.set,
                    "Building permanent index independently from Strict toward Loose…",
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
                    f"{completed_groups} certified groups; unlocked through slider "
                    f"{boundary_text}; early READY work remains saved; NUKE remains locked."
                )

            observed_edges = self.evidence.edge_count()
            boundary = self.evidence.loosest_complete_slider()
            boundary_text = "none" if boundary is None else str(boundary)
            delta = evidence_sync.delta
            cache_summary = (
                "evidence inventory unchanged"
                if evidence_sync.cache_was_current
                else (
                    f"evidence inventory: {len(delta.added)} added, "
                    f"{len(delta.changed)} changed, {len(delta.removed)} removed"
                )
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
                f"{completed_groups} certified groups, index unlocked through slider "
                f"{boundary_text}; {cache_summary}; {safety_summary}."
            )

        self._run("Starting independent progressive scan…", scan, self._scan_finished, lock_review=False)

    def _scan_finished(self) -> None:
        if self._scan_completed_current_inventory:
            self._inventory_verified_for_delete = True
        self._set_action_state()
        self._set_review_state(bool(self.pairs))
        self._refresh_index_boundary(apply=True)
        self._refresh_pairs()

    def _progressive_band_completed(self, result) -> None:
        group_count = result.group_result.groups_completed
        self.status.set(
            f"Permanent index unlocked through slider {result.band.loosest_slider}; "
            f"{group_count} groups certified in this band; "
            f"{result.total_edges:,} evidence edges saved."
        )
        self._refresh_index_boundary(apply=False)

    def _nuke_finished(self) -> None:
        self._refresh_pairs()

    def _close(self) -> None:
        self.scan_cancel.set()
        self.left_preview.stop()
        self.right_preview.stop()
        for cancellation in self.preview_cancellations.values():
            cancellation.set()
        self.preview_executor.shutdown(wait=True, cancel_futures=True)
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.evidence.close()
        self.database.close()
        self.destroy()
