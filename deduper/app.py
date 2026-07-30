from __future__ import annotations

import queue
import shutil
import tempfile
import tkinter as tk
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import ttk

from .config import Config
from .database import Database
from .hashing import hash_file
from .matcher import acquire_pairs
from .models import Pair
from .preview import MediaPreview, PreviewCache
from .r2 import R2Store


BG = "#090909"
PANEL = "#151515"
TEXT = "#f4f4f4"
MUTED = "#aaa"
RED = "#d62f2f"
GREEN = "#35b56b"


def human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} TB"


class DeduperApp(tk.Tk):
    def __init__(self, config: Config, database: Database, store: R2Store, data_directory: Path):
        super().__init__()
        self.config = config
        self.database = database
        self.store = store
        self.data_directory = data_directory
        self.events: queue.Queue[tuple[Callable, tuple]] = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gparty")
        self.cache = PreviewCache(
            data_directory / "preview-cache",
            config.preview_cache_mb * 1024 * 1024,
        )
        self.pairs: list[Pair] = []
        self.pair_index = 0
        self.busy = False
        self.preview_requests: dict[MediaPreview, int] = {}

        self.title("GParty Deduper")
        self.geometry("1320x880")
        self.minsize(1000, 700)
        self.configure(background=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._configure_styles()
        self._build()
        self.bind("<Left>", self._keyboard_previous)
        self.bind("<Right>", self._keyboard_next)
        self.after(60, self._drain_events)
        self._refresh_counts()
        self._refresh_pairs()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TButton", background="#292929", foreground=TEXT, padding=(12, 8))
        style.map("TButton", background=[("active", "#3b3b3b"), ("disabled", "#181818")])
        style.configure("Danger.TButton", background=RED, foreground="white")
        style.map("Danger.TButton", background=[("active", "#f04444")])
        style.configure("Accent.TButton", background="#245fa8", foreground="white")
        style.map("Accent.TButton", background=[("active", "#3277c9")])
        style.configure("Horizontal.TScale", background=BG, troughcolor="#333")

    def _build(self) -> None:
        header = tk.Frame(self, background=BG)
        header.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(
            header,
            text="GPARTY DEDUPER",
            background=BG,
            foreground=TEXT,
            font=("Segoe UI", 17, "bold"),
        ).pack(side="left")
        self.counts_label = tk.Label(header, background=BG, foreground=MUTED, anchor="e")
        self.counts_label.pack(side="right")

        actions = tk.Frame(self, background=BG)
        actions.pack(fill="x", padx=14, pady=(0, 8))
        self.scan_button = ttk.Button(actions, text="SCAN", style="Accent.TButton", command=self.start_scan)
        self.scan_button.pack(side="left", padx=(0, 8))
        self.nuke_button = ttk.Button(actions, text="NUKE", style="Danger.TButton", command=self.start_nuke)
        self.nuke_button.pack(side="left")
        tk.Label(
            actions,
            text="Loose",
            background=BG,
            foreground=MUTED,
        ).pack(side="left", padx=(24, 4))
        self.slider = tk.IntVar(value=50)
        ttk.Scale(
            actions,
            from_=0,
            to=99,
            variable=self.slider,
            orient="horizontal",
            length=300,
            takefocus=False,
        ).pack(side="left")
        tk.Label(
            actions,
            text="Strict",
            background=BG,
            foreground=MUTED,
        ).pack(side="left", padx=(4, 0))

        comparison = tk.Frame(self, background=BG)
        comparison.pack(fill="both", expand=True, padx=14)
        comparison.grid_columnconfigure(0, weight=1)
        comparison.grid_columnconfigure(1, weight=0)
        comparison.grid_columnconfigure(2, weight=1)
        comparison.grid_rowconfigure(1, weight=1)

        tk.Label(
            comparison,
            text="SURVIVOR",
            background=BG,
            foreground=GREEN,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, pady=(0, 6))
        self.exclude_button = ttk.Button(
            comparison,
            text="EXCLUDE FROM THIS NUKE",
            command=self._exclude_current,
        )
        self.exclude_button.grid(row=0, column=1, padx=12, pady=(0, 6))
        tk.Label(
            comparison,
            text="DELETE ON NUKE",
            background=BG,
            foreground="#ff6767",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=2, pady=(0, 6))

        left_panel = tk.Frame(comparison, background=PANEL)
        left_panel.grid(row=1, column=0, sticky="nsew")
        right_panel = tk.Frame(comparison, background=PANEL)
        right_panel.grid(row=1, column=2, sticky="nsew")
        self.left_preview = MediaPreview(left_panel, background=PANEL)
        self.left_preview.pack(fill="both", expand=True)
        self.right_preview = MediaPreview(right_panel, background=PANEL)
        self.right_preview.pack(fill="both", expand=True)
        self.left_meta = tk.Label(left_panel, background=PANEL, foreground=MUTED, justify="left", anchor="w")
        self.left_meta.pack(fill="x", padx=8, pady=6)
        self.right_meta = tk.Label(right_panel, background=PANEL, foreground=MUTED, justify="left", anchor="w")
        self.right_meta.pack(fill="x", padx=8, pady=6)

        center = tk.Frame(comparison, background=BG, width=190)
        center.grid(row=1, column=1, sticky="ns", padx=12)
        center.grid_propagate(False)
        self.pair_label = tk.Label(
            center,
            background=BG,
            foreground=TEXT,
            justify="center",
            wraplength=180,
            font=("Segoe UI", 11, "bold"),
        )
        self.pair_label.pack(expand=True)

        navigation = tk.Frame(self, background=BG)
        navigation.pack(fill="x", padx=14, pady=7)
        self.previous_button = ttk.Button(navigation, text="◀ PREVIOUS", command=self._previous)
        self.previous_button.pack(side="left")
        self.next_button = ttk.Button(navigation, text="NEXT ▶", command=self._next)
        self.next_button.pack(side="right")

        self.status = tk.StringVar(value="Ready.")
        status = tk.Label(
            self,
            textvariable=self.status,
            background="#111",
            foreground=TEXT,
            anchor="w",
            padx=12,
            pady=7,
        )
        status.pack(fill="x")

    def _drain_events(self) -> None:
        try:
            while True:
                callback, args = self.events.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        self.after(60, self._drain_events)

    def _ui(self, callback: Callable, *args) -> None:
        self.events.put((callback, args))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in (self.scan_button, self.nuke_button):
            button.configure(state=state)
        self._set_review_state(bool(self.pairs))

    def _run(self, label: str, operation: Callable[[], str], finished: Callable[[], None] | None = None) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.status.set(label)

        def worker() -> None:
            try:
                message = operation()
            except Exception as exc:
                message = f"FAILED — {type(exc).__name__}: {exc}"
            self._ui(self._operation_finished, message, finished)

        self.executor.submit(worker)

    def _operation_finished(self, message: str, finished: Callable[[], None] | None) -> None:
        self._set_busy(False)
        self.status.set(message)
        self._refresh_counts()
        if finished:
            finished()

    def start_scan(self) -> None:
        slider = int(round(self.slider.get()))

        def scan() -> str:
            self._ui(self.status.set, "Connecting to R2 and reading inventory…")
            self.store.verify()
            inventory = self.store.list_assets()
            live_keys = {asset.key for asset in inventory}
            new_count, changed_count = self.database.upsert_inventory(inventory)
            missing_count = self.database.mark_missing_deleted(live_keys)
            pending = list(self.database.assets_needing_hashes())
            errors = 0
            if pending:
                work_directory = Path(tempfile.mkdtemp(prefix="gparty-scan-"))
                try:
                    for index, asset in enumerate(pending, 1):
                        self._ui(
                            self.status.set,
                            f"SCAN {index}/{len(pending)} — {asset.key}",
                        )
                        local_path = work_directory / f"media.{asset.extension}"
                        local_path.unlink(missing_ok=True)
                        try:
                            self.store.download(asset.key, local_path)
                            hash_file(asset, local_path, self.config)
                            if asset.scan_error:
                                errors += 1
                        except Exception as exc:
                            asset.scan_error = f"{type(exc).__name__}: {exc}"[:1000]
                            errors += 1
                        finally:
                            self.database.save_hashes(asset)
                            local_path.unlink(missing_ok=True)
                finally:
                    shutil.rmtree(work_directory, ignore_errors=True)

            assets = self.database.all_hashed_assets()
            self._ui(self.status.set, f"Finding duplicate groups in {len(assets)} hashed objects…")
            pairs = acquire_pairs(assets, slider)
            target_count = self.database.replace_pairs(pairs)
            return (
                f"Scan complete. {new_count} new, {changed_count} changed, "
                f"{missing_count} missing, {errors} errors, {target_count} deletion candidates."
            )

        self._run("Starting scan…", scan, self._refresh_pairs)

    def start_nuke(self) -> None:
        queued = self.database.queued_deletions()
        cleanup = self.database.pending_index_cleanup()
        if not queued and not cleanup:
            self.status.set("NUKE has nothing queued.")
            return
        if not self.config.allow_delete:
            self.status.set(
                "NUKE is locked. Set ALLOW_DELETE=YES in config.txt, then restart the app."
            )
            return

        def nuke() -> str:
            cleanup_error = None
            if cleanup:
                try:
                    self.store.remove_from_gallery_index(cleanup)
                    self.database.clear_index_cleanup(cleanup)
                except Exception as exc:
                    cleanup_error = f"{type(exc).__name__}: {exc}"
            results, deleted, index_error = self.store.delete_queued(queued)
            self.database.record_deletions(results)
            if index_error:
                self.database.queue_index_cleanup(deleted)
            failed = len(results) - len(deleted)
            reclaimed = sum(size for key, _, size in queued if key in set(deleted))
            message = (
                f"NUKE complete. Deleted {len(deleted)} objects, reclaimed {human_bytes(reclaimed)}, "
                f"{failed} failed."
            )
            if index_error:
                message += f" Gallery index cleanup was saved for automatic retry: {index_error}"
            if cleanup_error:
                message += f" Earlier gallery index cleanup still needs retrying: {cleanup_error}"
            return message

        self._run(f"NUKE deleting {len(queued)} queued objects…", nuke, self._refresh_pairs)

    def _refresh_counts(self) -> None:
        counts = self.database.counts()
        lock = "" if self.config.allow_delete else "  •  NUKE LOCKED"
        self.counts_label.configure(
            text=(
                f"R2: {counts['live']}  •  Hashed: {counts['hashed']}  •  "
                f"Targets: {counts['pending']}  •  Queued: {counts['queued']}{lock}"
            )
        )

    def _refresh_pairs(self) -> None:
        self.pairs = self.database.scan_pairs()
        self.pair_index = min(self.pair_index, max(0, len(self.pairs) - 1))
        self._show_current_pair()

    def _show_current_pair(self) -> None:
        if not self.pairs:
            self.pair_label.configure(text="No duplicate pairs.\n\nAdjust the slider and press SCAN.")
            self.left_meta.configure(text="")
            self.right_meta.configure(text="")
            self.left_preview.clear("No target")
            self.right_preview.clear("No target")
            self._set_review_state(False)
            return
        self._set_review_state(True)
        pair = self.pairs[self.pair_index]
        left = self.database.asset(pair.left_key)
        right = self.database.asset(pair.right_key)
        exclusion = "\n\nEXCLUDED FROM THIS NUKE" if pair.status == "excluded" else ""
        self.pair_label.configure(
            text=(
                f"PAIR {self.pair_index + 1} / {len(self.pairs)}\n\n"
                f"{pair.similarity:.1f}%\n\n{pair.reason}{exclusion}"
            )
        )
        if pair.status == "excluded":
            self.exclude_button.configure(text="EXCLUDED FROM THIS NUKE", state="disabled")
        else:
            self.exclude_button.configure(text="EXCLUDE FROM THIS NUKE", state="normal")
        self.left_meta.configure(text=self._asset_text(left))
        self.right_meta.configure(text=self._asset_text(right))
        self._load_preview(pair.left_key, self.left_preview)
        self._load_preview(pair.right_key, self.right_preview)

    def _asset_text(self, asset) -> str:
        if asset is None:
            return "Missing database record"
        dimensions = (
            f"{asset.width}×{asset.height}" if asset.width and asset.height else "unknown dimensions"
        )
        duration = f"  •  {asset.duration:.1f}s" if asset.duration else ""
        return f"{asset.key}\n{human_bytes(asset.size)}  •  {dimensions}{duration}"

    def _load_preview(self, key: str, widget: MediaPreview) -> None:
        widget.clear()
        request = self.preview_requests.get(widget, 0) + 1
        self.preview_requests[widget] = request

        def fetch() -> None:
            try:
                path = self.cache.obtain(key, self.store.download)
                self._ui(self._finish_preview, widget, request, path, None)
            except Exception as exc:
                self._ui(self._finish_preview, widget, request, None, type(exc).__name__)

        self.executor.submit(fetch)

    def _finish_preview(
        self,
        widget: MediaPreview,
        request: int,
        path: Path | None,
        error: str | None,
    ) -> None:
        if self.preview_requests.get(widget) != request:
            return
        if error or path is None:
            widget.clear(f"Preview failed\n{error or 'unknown error'}")
        else:
            widget.load(path)

    def _set_review_state(self, enabled: bool) -> None:
        state = "normal" if enabled and not self.busy else "disabled"
        for button in (self.exclude_button, self.previous_button, self.next_button):
            button.configure(state=state)

    def _exclude_current(self) -> None:
        if not self.pairs:
            return
        pair = self.pairs[self.pair_index]
        if pair.status == "excluded":
            return
        self.database.exclude_pair(pair.id)
        self.status.set(f"Excluded from this NUKE: {pair.right_key}")
        self._refresh_counts()
        self.pairs = self.database.scan_pairs()
        self.pair_index = (self.pair_index + 1) % len(self.pairs)
        self._show_current_pair()

    def _previous(self) -> None:
        if self.busy or not self.pairs:
            return
        self.pair_index = (self.pair_index - 1) % len(self.pairs)
        self._show_current_pair()

    def _next(self) -> None:
        if self.busy or not self.pairs:
            return
        self.pair_index = (self.pair_index + 1) % len(self.pairs)
        self._show_current_pair()

    def _keyboard_previous(self, _event=None) -> str:
        self._previous()
        return "break"

    def _keyboard_next(self, _event=None) -> str:
        self._next()
        return "break"

    def _close(self) -> None:
        self.left_preview.stop()
        self.right_preview.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.database.close()
        self.destroy()
