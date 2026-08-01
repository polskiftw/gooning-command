from __future__ import annotations

import multiprocessing
import tkinter as tk
from tkinter import messagebox

from deduper.config import ConfigError, app_directory, parse_config
from deduper.database import Database
from deduper.fast_app import FastDeduperApp
from deduper.r2 import R2Store


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

    database = Database(data_directory / "gparty-deduper.sqlite3")
    store = R2Store(config)
    app = FastDeduperApp(config, database, store, data_directory)
    app.mainloop()
    return 0


if __name__ == "__main__":
    # Required for ProcessPoolExecutor inside the packaged Windows executable.
    multiprocessing.freeze_support()
    raise SystemExit(main())
