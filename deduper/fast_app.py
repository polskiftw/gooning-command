from __future__ import annotations

import threading

from .app import DeduperApp
from .matcher import MatchingCancelled, acquire_pair_stages
from .scanner import scan_assets


class FastDeduperApp(DeduperApp):
    """Deduper UI with a bounded concurrent, resumable scan pipeline."""

    def __init__(self, *args, **kwargs):
        self.scan_cancel = threading.Event()
        super().__init__(*args, **kwargs)

    def start_scan(self) -> None:
        slider = int(round(self.slider.get()))
        self.scan_cancel.clear()

        def scan() -> str:
            self._ui(self.status.set, "Connecting to R2 and reading inventory…")
            self.store.verify()
            inventory = self.store.list_assets()
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
            self.database.set_matching_state("running")
            self._ui(
                self._set_empty_pair_message,
                "Comparison running…\n\nExact duplicates will appear as soon as they are saved.",
            )

            def matching_progress(stage: str, completed: int, total: int) -> None:
                self._ui(
                    self.status.set,
                    f"MATCHING {stage} {completed}/{total} — saved results stay safe",
                )

            target_count = 0
            try:
                for stage, pairs in acquire_pair_stages(
                    assets,
                    slider,
                    matching_progress,
                    self.scan_cancel.is_set,
                ):
                    target_count = self.database.replace_pairs(pairs)
                    self.database.set_matching_state(stage)
                    self._ui(self._matching_stage_saved, stage, target_count)
            except MatchingCancelled:
                self.database.set_matching_state("cancelled")
                self._ui(
                    self._set_empty_pair_message,
                    "Comparison stopped safely.\n\nAny completed matching stage remains saved.",
                )
                return (
                    f"Matching stopped safely. {target_count} saved deletion candidates remain ready; "
                    "press SCAN to continue with a fresh comparison."
                )
            except Exception:
                self.database.set_matching_state("failed")
                self._ui(
                    self._set_empty_pair_message,
                    "Comparison failed.\n\nAny completed matching stage remains saved; see the status below.",
                )
                raise
            return (
                f"Scan complete. {new_count} new, {changed_count} changed, "
                f"{missing_count} missing, {errors} errors, {target_count} deletion candidates."
            )

        self._run("Starting parallel scan…", scan, self._refresh_pairs)

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

    def _close(self) -> None:
        self.scan_cancel.set()
        self.left_preview.stop()
        self.right_preview.stop()
        # Wait for active workers to leave their current download/decode cleanly before
        # SQLite is closed. Completed hashes have already been committed individually.
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.database.close()
        self.destroy()
