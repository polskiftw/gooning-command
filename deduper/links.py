from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote


PUBLIC_MEDIA_BASE_URL = "https://gooning.party/media/"


def public_media_url(key: str) -> str:
    return f"{PUBLIC_MEDIA_BASE_URL}{quote(key, safe='')}"


def firefox_executables() -> list[str]:
    """Return explicit Firefox launchers without falling back to another browser."""
    candidates: list[str] = []
    on_path = shutil.which("firefox")
    if on_path:
        candidates.append(on_path)

    if os.name == "nt":
        try:
            import winreg

            registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe"
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, registry_path) as key:
                        registered, _ = winreg.QueryValueEx(key, None)
                    if registered:
                        candidates.append(registered)
                except OSError:
                    continue
        except ImportError:
            pass

        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(str(Path(root) / "Mozilla Firefox" / "firefox.exe"))

    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique and (os.name != "nt" or Path(candidate).is_file()):
            unique.append(candidate)
    return unique


def open_in_firefox(url: str) -> None:
    errors: list[OSError] = []
    for executable in firefox_executables():
        try:
            subprocess.Popen([executable, "-new-tab", url])
            return
        except OSError as exc:
            errors.append(exc)
    if errors:
        raise FileNotFoundError(f"Firefox could not be started: {errors[-1]}")
    raise FileNotFoundError("Firefox was not found on this computer")
