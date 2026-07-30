from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Asset:
    key: str
    size: int
    etag: str
    last_modified: str
    media_type: str
    extension: str
    sha256: str | None = None
    phash: str | None = None
    crop_hashes: str | None = None
    pdq_hash: str | None = None
    pdq_quality: int | None = None
    vpdq_hashes: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    scan_error: str | None = None
    deleted: bool = False


@dataclass(slots=True)
class Pair:
    id: int
    left_key: str
    right_key: str
    similarity: float
    reason: str
    status: str
    decision: str | None
