from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    gallery_prefix: str = "gallery/"
    index_key: str = "gallery-index.json"
    allow_delete: bool = False
    video_sample_seconds: float = 1.0
    max_video_frames: int = 120
    scan_workers: int = 10
    video_workers: int = 3
    compare_workers: int = 20

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def parse_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(
            f"Missing {path.name}. Copy config.example.txt to config.txt and fill in the four R2 values."
        )

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"{path.name} line {line_number} must use NAME=value")
        name, value = line.split("=", 1)
        name = name.strip().upper()
        if not name:
            raise ConfigError(f"{path.name} line {line_number} has an empty setting name")
        values[name] = value.strip()

    required = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"]
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise ConfigError(f"Missing required setting(s): {', '.join(missing)}")

    prefix = values.get("GALLERY_PREFIX", "gallery/").strip("/")
    if not prefix:
        raise ConfigError("GALLERY_PREFIX cannot be empty")

    try:
        video_sample_seconds = float(values.get("VIDEO_SAMPLE_SECONDS", "1"))
        max_video_frames = int(values.get("MAX_VIDEO_FRAMES", "120"))
        scan_workers = int(values.get("SCAN_WORKERS", "10"))
        video_workers = int(values.get("VIDEO_WORKERS", "3"))
        compare_workers = int(values.get("COMPARE_WORKERS", "20"))
    except ValueError as exc:
        raise ConfigError(
            "VIDEO_SAMPLE_SECONDS, MAX_VIDEO_FRAMES, SCAN_WORKERS, VIDEO_WORKERS, "
            "and COMPARE_WORKERS must be numbers"
        ) from exc

    # 300 was the old shipped default. Treat that untouched legacy value as 120
    # so existing portable installs receive the faster setting automatically.
    if max_video_frames == 300:
        max_video_frames = 120

    if video_sample_seconds <= 0 or max_video_frames < 1:
        raise ConfigError(
            "VIDEO_SAMPLE_SECONDS must be above 0 and MAX_VIDEO_FRAMES at least 1"
        )
    if not 1 <= scan_workers <= 32:
        raise ConfigError("SCAN_WORKERS must be between 1 and 32")
    if not 1 <= video_workers <= scan_workers:
        raise ConfigError("VIDEO_WORKERS must be between 1 and SCAN_WORKERS")
    if not 1 <= compare_workers <= 32:
        raise ConfigError("COMPARE_WORKERS must be between 1 and 32")

    return Config(
        account_id=values["R2_ACCOUNT_ID"],
        access_key_id=values["R2_ACCESS_KEY_ID"],
        secret_access_key=values["R2_SECRET_ACCESS_KEY"],
        bucket_name=values["R2_BUCKET_NAME"],
        gallery_prefix=prefix + "/",
        index_key=values.get("INDEX_KEY", "gallery-index.json") or "gallery-index.json",
        allow_delete=values.get("ALLOW_DELETE", "NO").upper() == "YES",
        video_sample_seconds=video_sample_seconds,
        max_video_frames=max_video_frames,
        scan_workers=scan_workers,
        video_workers=video_workers,
        compare_workers=compare_workers,
    )
