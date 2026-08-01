from __future__ import annotations

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
    tag_index_key: str = "_internal/tag-index-v1.json"
    threshold: float = 0.4
    animated_frames: int = 4
    publish_every: int = 100

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
        threshold = float(values.get("TAG_THRESHOLD", "0.4"))
        animated_frames = int(values.get("ANIMATED_FRAMES", "4"))
        publish_every = int(values.get("PUBLISH_EVERY", "100"))
    except ValueError as exc:
        raise ConfigError("TAG_THRESHOLD, ANIMATED_FRAMES, and PUBLISH_EVERY must be numbers") from exc

    if not 0.05 <= threshold <= 0.95:
        raise ConfigError("TAG_THRESHOLD must be between 0.05 and 0.95")
    if not 1 <= animated_frames <= 24:
        raise ConfigError("ANIMATED_FRAMES must be between 1 and 24")
    if not 1 <= publish_every <= 10_000:
        raise ConfigError("PUBLISH_EVERY must be between 1 and 10000")

    return Config(
        account_id=values["R2_ACCOUNT_ID"],
        access_key_id=values["R2_ACCESS_KEY_ID"],
        secret_access_key=values["R2_SECRET_ACCESS_KEY"],
        bucket_name=values["R2_BUCKET_NAME"],
        gallery_prefix=prefix + "/",
        tag_index_key=values.get("TAG_INDEX_KEY", "_internal/tag-index-v1.json")
        or "_internal/tag-index-v1.json",
        threshold=threshold,
        animated_frames=animated_frames,
        publish_every=publish_every,
    )

