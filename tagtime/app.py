from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .config import ConfigError, app_directory, parse_config
from .runner import TagTimeRunner


class TagTimeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("GParty Tag Time")
        self.root.geometry("620x390")
        self.root.minsize(540, 350)
        self.root.configure(bg="#090909")
        self.events: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        self.force_close = False

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Tag.Horizontal.TProgressbar", troughcolor="#202020", background="#d9d9d9")

        frame = tk.Frame(root, bg="#090909", padx=38, pady=30)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="GParty",
            fg="#777",
            bg="#090909",
            font=("Segoe UI", 12, "bold"),
        ).pack()
        tk.Label(
            frame,
            text="TAG TIME",
            fg="white",
            bg="#090909",
            font=("Segoe UI", 30, "bold"),
        ).pack(pady=(2, 22))

        self.button = tk.Button(
            frame,
            text="TAG TIME",
            command=self.start,
            bg="#ededed",
            fg="#050505",
            activebackground="#ffffff",
            activeforeground="#050505",
            relief="flat",
            bd=0,
            padx=36,
            pady=13,
            font=("Segoe UI", 15, "bold"),
            cursor="hand2",
        )
        self.button.pack()

        self.progress = ttk.Progressbar(
            frame,
            mode="determinate",
            maximum=1,
            value=0,
            style="Tag.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", pady=(28, 12))
        self.status = tk.StringVar(value="Ready. Press the big button when you want to start.")
        tk.Label(
            frame,
            textvariable=self.status,
            fg="#c6c6c6",
            bg="#090909",
            justify="center",
            wraplength=520,
            font=("Segoe UI", 10),
        ).pack(fill="x")
        self.detail = tk.StringVar(value="Tagged files are remembered automatically.")
        tk.Label(
            frame,
            textvariable=self.detail,
            fg="#707070",
            bg="#090909",
            justify="center",
            wraplength=520,
            font=("Segoe UI", 9),
        ).pack(fill="x", pady=(7, 0))

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.drain_events)

    def start(self) -> None:
        if self.running:
            return
        base = app_directory()
        try:
            config = parse_config(base / "config.txt")
        except ConfigError as problem:
            messagebox.showerror("Tag Time needs its config", str(problem), parent=self.root)
            return

        self.running = True
        self.cancel.clear()
        self.button.configure(state="disabled", text="TAGGING…")
        self.status.set("Starting Tag Time…")
        self.detail.set("You can close the window whenever you want; finished files stay finished.")
        runner = TagTimeRunner(
            config,
            base / "data",
            self.cancel,
            lambda name, values: self.events.put((name, values)),
        )
        threading.Thread(target=runner.run, name="tag-time", daemon=True).start()

    def drain_events(self) -> None:
        try:
            while True:
                name, values = self.events.get_nowait()
                self.handle_event(name, values)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self.drain_events)

    def handle_event(self, name: str, values: dict) -> None:
        if name == "status":
            self.status.set(str(values["text"]))
        elif name == "model_progress":
            current = int(values["current"])
            total = int(values["total"])
            self.progress.configure(maximum=max(1, total), value=current)
            self.status.set(f"Downloading JoyTag once… {current / 1024 / 1024:.0f} MB")
            if total:
                self.detail.set(f"{values['filename']} — {current * 100 / total:.1f}%")
        elif name == "scan_ready":
            remaining = int(values["remaining"])
            self.progress.configure(maximum=max(1, remaining), value=0)
            self.detail.set(
                f"{values['tagged']:,} already tagged • {remaining:,} waiting • {values['total']:,} total"
            )
        elif name == "asset":
            position = int(values["position"])
            remaining = int(values["remaining"])
            self.progress.configure(maximum=max(1, remaining), value=position - 1)
            self.status.set(f"Tagging {position:,} of {remaining:,}…")
        elif name == "finished":
            self.running = False
            self.progress.configure(value=self.progress.cget("maximum"))
            if values.get("cancelled"):
                self.status.set("Paused safely. Press TAG TIME later to continue.")
            else:
                self.status.set("Tag Time is done.")
            if "tagged" in values:
                self.detail.set(
                    f"{int(values['tagged']):,} tagged • {int(values['errors']):,} will retry next time"
                )
            self.button.configure(state="normal", text="TAG TIME")
            if self.force_close:
                self.root.destroy()
        elif name == "fatal":
            self.running = False
            self.status.set("Tag Time stopped before it could finish.")
            self.detail.set(str(values["message"]))
            self.button.configure(state="normal", text="TRY AGAIN")
            if self.force_close:
                self.root.destroy()

    def close(self) -> None:
        if not self.running:
            self.root.destroy()
            return
        if self.force_close:
            self.root.destroy()
            return
        self.force_close = True
        self.cancel.set()
        self.status.set("Pausing safely and saving the current catalog…")
        self.detail.set("The window will close as soon as the current file is finished.")


def run() -> None:
    root = tk.Tk()
    TagTimeApp(root)
    root.mainloop()
