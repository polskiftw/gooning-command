from __future__ import annotations

import threading

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
        super().__init__(*args, **kwargs)
        self.slider.trace_add("write", self._slider_changed)
        self._refresh_index_boundary(apply=False)

    def _slider_changed(self, *_args) -> None:
        if self._slider_guard:
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
                    "Permanent index: no certified slider positions yet — press SCAN"
                )
            return
        if requested < boundary:
            self._slider_guard = True
            try:
                self.slider.set(boundary)
            finally:
                self._slider_guard = False
            requested = boundary
        self.comparison_progress.set(
            f"Permanent index READY: slider {boundary}–99  •  selected {requested}"
        )
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
                self.status.set("No certified slider positions yet. Press SCAN to begin indexing.")
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
        # The visible slider is intentionally not read here. SCAN owns its own
        # strict-to-loose progression; the slider is only a certified-view filter.
        self.scan_cancel.clear()
        self._streaming_ready_slider = None
        self._streaming_ready_pairs = 0

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
                    "unfinished objects will resume next scan."
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
                    f"{boundary_text}; early READY work remains saved; resume with SCAN."
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
            return (
                f"Scan complete. {new_count} new, {changed_count} changed, "
                f"{missing_count} missing, {errors} errors, "
                f"{sha_target_count} invisible SHA extras, {observed_edges} permanent evidence edges, "
                f"{completed_groups} certified groups, index unlocked through slider "
                f"{boundary_text}; {cache_summary}."
            )

        self._run("Starting independent progressive scan…", scan, self._scan_finished, lock_review=False)

    def _scan_finished(self) -> None:
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
