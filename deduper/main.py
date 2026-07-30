from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from deduper.app import DeduperApp
from deduper.config import ConfigError, app_directory, parse_config
from deduper.database import Database
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
    app = DeduperApp(config, database, store, data_directory)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
