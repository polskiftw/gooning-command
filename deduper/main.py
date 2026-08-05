from __future__ import annotations

import multiprocessing
import tkinter as tk
from tkinter import messagebox

from deduper.app import DeduperApp
from deduper.certified_slider import install_certified_slider_lock
from deduper.config import ConfigError, app_directory, parse_config
from deduper.database import Database
from deduper.database_migration import migrate_and_recover
from deduper.evidence_contract import enforce_evidence_contract
from deduper.evidence_store import EvidenceStore
from deduper.r2 import R2Store
from deduper.ready_lifecycle import install_ready_lifecycle
from deduper.review_ui import install_review_ui_hardening
from deduper.smart_app import SmartDeduperApp


def main() -> int:
    directory = app_directory()
    config_path = directory / "config.txt"
    data_directory = directory / "data"
    data_directory.mkdir(parents=True, exist_ok=True)

    try:
        config = parse_config(config_path)
    except ConfigError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("GParty Deduper configuration", str(exc))
        root.destroy()
        return 2

    install_review_ui_hardening(DeduperApp)
    install_certified_slider_lock(SmartDeduperApp)
    database = Database(data_directory / "gparty-deduper.sqlite3")
    try:
        migrate_and_recover(database)
    except Exception as exc:
        database.close()
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "GParty Deduper database",
            "The database failed its safety check and was not modified further.\n\n"
            f"{type(exc).__name__}: {exc}",
        )
        root.destroy()
        return 3
    install_ready_lifecycle(database)
    evidence = EvidenceStore(data_directory / "gparty-evidence.sqlite3")
    enforce_evidence_contract(evidence)
    store = R2Store(config)
    app = SmartDeduperApp(config, database, store, data_directory, evidence=evidence)
    app.mainloop()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
