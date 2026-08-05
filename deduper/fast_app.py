from __future__ import annotations

import threading

from .app import DeduperApp
from .evidence_inventory import reconcile_asset_inventory
from .evidence_store import EvidenceStore
from .matcher import MatchingCancelled, acquire_pair_stages, partition_exact_duplicates
from .scanner import scan_assets


class FastDeduperApp(DeduperApp):
    """Deduper UI with a bounded concurrent, resumable scan pipeline."""

    def __init__(self, *args, evidence: EvidenceStore, **kwargs):
        self.scan_cancel = threading.Event()
        self.evidence = evidence
        super().__init__(*args, **kwargs)

    def start_scan(self) -> None:
        slider = int(round(self.slider.get()))
        self.scan_cancel.clear()

        def scan() -> str:
            self._ui(self.status.set, "Connecting to R2 and reading inventory…")
            self.store.verify()
            inventory = self.store.list_assets()
            evidence_sync = reconcile_asset_inventory(self.evidence, inventory)
            live_keys = {asset.key for asset in inventory}
            new_count, changed_count = self.database.upsert_inventory(inventory)
            missing_count = self.database.mark_missing_deleted(live_keys)
            pending = list(self.database.assets_needing_hashes())

            def progress(completed: int, total: int, key: str) -> None:
                self._ui(self.status.set, f"SCAN {completed}/{total} — {key}")

            completed, errors = scan_assets(
                pending,
                self.store,
                self.config,
                self.database.save_hashes,
                progress,
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
            # A new scan resets the temporary visual-review decisions. Exact SHA
            # groups live in their own invisible queue and never become previews.
            self.database.replace_pairs([])
            self.database.set_matching_state("running")
            self._ui(
                self._set_empty_pair_message,
                "Comparison running…\n\nVisual matches will appear as each stage finishes.",
            )

            stage_totals = {
                "pHash": sum(
                    1 for asset in visual_assets if asset.phash and not asset.vpdq_hashes
                ),
                "PDQ": sum(
                    1 for asset in visual_assets if asset.pdq_hash and not asset.vpdq_hashes
                ),
                "crop-resistant": len(visual_assets),
                "vPDQ index": sum(1 for asset in visual_assets if asset.vpdq_hashes),
                "vPDQ": sum(1 for asset in visual_assets if asset.vpdq_hashes),
            }
            self._ui(self._begin_matching_progress, stage_totals, sha_target_count)

            def matching_progress(stage: str, completed: int, total: int) -> None:
                self._ui(self._update_matching_progress, stage, completed, total)

            target_count = 0
            try:
                for stage, pairs in acquire_pair_stages(
                    visual_assets,
                    slider,
                    matching_progress,
                    self.scan_cancel.is_set,
                    include_exact=False,
                    compare_workers=self.config.compare_workers,
                ):
                    target_count = self.database.replace_pairs(
                        pairs,
                        preserve_exclusions=True,
                    )
                    self.database.set_matching_state(stage)
                    self._ui(self._matching_stage_saved, stage, target_count)
            except MatchingCancelled:
                self.database.set_matching_state("cancelled")
                self._ui(
                    self._set_empty_pair_message,
                    "Comparison stopped safely.\n\nAny completed matching stage remains saved.",
                )
                return (
                    f"Matching stopped safely. {target_count} visual candidates and "
                    f"{sha_target_count} SHA extras remain ready; "
                    "press SCAN to continue with a fresh comparison."
                )
            except Exception:
                self.database.set_matching_state("failed")
                self._ui(
                    self._set_empty_pair_message,
                    "Comparison failed.\n\nAny completed matching stage remains saved; see the status below.",
                )
                raise

            delta = evidence_sync.delta
            cache_summary = (
                "evidence inventory unchanged"
                if evidence_sync.cache_was_current
                else (
                    f"evidence inventory: {len(delta.added)} added, "
                    f"{len(delta.changed)} changed, {len(delta.removed)} removed"
                )
            )
            return (
                f"Scan complete. {new_count} new, {changed_count} changed, "
                f"{missing_count} missing, {errors} errors, {target_count} visual candidates, "
                f"{sha_target_count} invisible SHA extras; {cache_summary}."
            )

        self._run("Starting parallel scan…", scan, self._refresh_pairs, lock_review=False)

    def _begin_matching_progress(self, totals: dict[str, int], sha_targets: int) -> None:
        self.matching_totals = totals
        self.matching_completed = {stage: 0 for stage in totals}
        self.sha_target_count = sha_targets
        self._render_matching_progress()
        self._refresh_counts()
        self._refresh_pairs()

    def _update_matching_progress(self, stage: str, completed: int, total: int) -> None:
        if not hasattr(self, "matching_totals"):
            return
        self.matching_totals[stage] = total
        self.matching_completed[stage] = completed
        self._render_matching_progress()

    def _render_matching_progress(self) -> None:
        labels = {
            "pHash": "pHash",
            "PDQ": "PDQ",
            "crop-resistant": "Crop",
            "vPDQ index": "vPDQ index",
            "vPDQ": "vPDQ",
        }
        parts = []
        completed_total = 0
        work_total = 0
        for stage in ("pHash", "PDQ", "crop-resistant", "vPDQ index", "vPDQ"):
            total = self.matching_totals.get(stage, 0)
            completed = min(self.matching_completed.get(stage, 0), total)
            completed_total += completed
            work_total += total
            percent = 100 if total == 0 else round(completed * 100 / total)
            parts.append(f"{labels[stage]} {completed:,}/{total:,} ({percent}%)")
        overall = 100 if work_total == 0 else round(completed_total * 100 / work_total)
        self.comparison_progress.set(
            f"CPU ×{self.config.compare_workers}  •  "
            f"SHA extras {self.sha_target_count:,} (hidden)  •  "
            + "  •  ".join(parts)
            + f"  •  FULL CHECK {overall}%"
        )

    def _matching_stage_saved(self, stage: str, target_count: int) -> None:
        labels = {
            "exact": "Exact duplicates saved",
            "phash": "pHash matches saved",
            "pdq": "PDQ matches saved",
            "images": "Image matches saved",
            "complete": "All matching complete",
        }
        empty_messages = {
            "exact": "Exact matching finished.\n\nVisual comparison is still running…",
            "phash": "pHash matching finished.\n\nPDQ comparison is still running…",
            "pdq": "PDQ matching finished.\n\nCrop-resistant comparison is still running…",
            "images": "Image matching finished.\n\nVideo comparison is still running…",
            "complete": "No duplicates found.\n\nThe comparison completed successfully.",
        }
        self._set_empty_pair_message(empty_messages[stage])
        self.status.set(f"{labels[stage]} — {target_count} deletion candidates safe in the database.")
        self._refresh_counts()
        self._refresh_pairs()

    def _nuke_finished(self) -> None:
        counts = self.database.counts()
        if hasattr(self, "sha_target_count"):
            self.sha_target_count = counts["sha_queued"]
            self._render_matching_progress()
        self._refresh_pairs()

    def _close(self) -> None:
        self.scan_cancel.set()
        self.left_preview.stop()
        self.right_preview.stop()
        for cancellation in self.preview_cancellations.values():
            cancellation.set()
        self.preview_executor.shutdown(wait=True, cancel_futures=True)
        # Wait for active workers to leave their current download/decode cleanly before
        # SQLite is closed. Completed hashes have already been committed individually.
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.evidence.close()
        self.database.close()
        self.destroy()
