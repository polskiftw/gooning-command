from __future__ import annotations

import multiprocessing
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from deduper.certified_app import CertifiedDeduperApp
from deduper.certified_database import CertifiedDatabase
from deduper.config import ConfigError, app_directory, parse_config
from deduper.database_migration import migrate_and_recover
from deduper.evidence_contract import enforce_evidence_contract
from deduper.evidence_store import EvidenceStore
from deduper.generation_integration import initialize_generation_storage
from deduper.r2 import R2Store


def _show_error(title: str, message: str) -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showerror(title, message)
    finally:
        root.destroy()


def _write_startup_error(directory: Path, stage: str, exc: BaseException) -> Path:
    path = directory / "startup-error.txt"
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    path.write_text(
        f"GParty Deduper startup failed during: {stage}\n\n{details}",
        encoding="utf-8",
    )
    return path


def main() -> int:
    directory = app_directory()
    config_path = directory / "config.txt"
    data_directory = directory / "data"
    data_directory.mkdir(parents=True, exist_ok=True)

    database: CertifiedDatabase | None = None
    evidence: EvidenceStore | None = None
    stage = "configuration"

    try:
        config = parse_config(config_path)

        stage = "main database startup validation"
        database = CertifiedDatabase(data_directory / "gparty-deduper.sqlite3")
        migrate_and_recover(database)

        stage = "certified generation initialization"
        generation_startup = initialize_generation_storage(database)

        stage = "evidence database initialization"
        evidence = EvidenceStore(data_directory / "gparty-evidence.sqlite3")

        stage = "evidence contract validation"
        enforce_evidence_contract(evidence)

        stage = "application window construction"
        store = R2Store(config)
        app = CertifiedDeduperApp(
            config,
            database,
            store,
            data_directory,
            evidence=evidence,
            generation_startup=generation_startup,
        )

        # Ownership transfers to the app after successful construction. Its
        # cancellation-safe close path closes both database handles.
        database = None
        evidence = None
        app.mainloop()
        return 0

    except ConfigError as exc:
        _show_error("GParty Deduper configuration", str(exc))
        return 2
    except Exception as exc:
        try:
            error_path = _write_startup_error(directory, stage, exc)
            log_note = f"\n\nFull details were saved to:\n{error_path}"
        except Exception:
            log_note = "\n\nThe diagnostic log could not be written."
        _show_error(
            "GParty Deduper startup failed",
            f"Startup stopped during {stage}.\n\n"
            f"{type(exc).__name__}: {exc}{log_note}",
        )
        return 3
    finally:
        if evidence is not None:
            evidence.close()
        if database is not None:
            database.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
