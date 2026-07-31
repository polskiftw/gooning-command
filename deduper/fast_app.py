from __future__ import annotations

import threading

from .app import DeduperApp
from .matcher import acquire_pairs
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
            self._ui(self.status.set, f"Finding duplicate groups in {len(assets)} hashed objects…")
            pairs = acquire_pairs(assets, slider)
            target_count = self.database.replace_pairs(pairs)
            return (
                f"Scan complete. {new_count} new, {changed_count} changed, "
                f"{missing_count} missing, {errors} errors, {target_count} deletion candidates."
            )

        self._run("Starting parallel scan…", scan, self._refresh_pairs)

    def _close(self) -> None:
        self.scan_cancel.set()
        self.left_preview.stop()
        self.right_preview.stop()
        # Wait for active workers to leave their current download/decode cleanly before
        # SQLite is closed. Completed hashes have already been committed individually.
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.database.close()
        self.destroy()
