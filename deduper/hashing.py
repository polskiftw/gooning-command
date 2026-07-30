from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import imagehash
import numpy as np
import pdqhash
from PIL import Image, ImageOps, ImageSequence

from .config import Config
from .models import Asset


def hash_file(asset: Asset, path: Path, config: Config) -> Asset:
    asset.sha256 = _sha256(path)
    try:
        if asset.extension == "gif":
            _hash_gif(asset, path, config)
        elif asset.media_type == "video":
            _hash_video(asset, path, config)
        else:
            _hash_image(asset, path)
    except Exception as exc:  # one broken media file must not abort a full scan
        asset.scan_error = f"{type(exc).__name__}: {exc}"[:1000]
    return asset


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    return image


def _still_hashes(image: Image.Image) -> tuple[str, str, str, int]:
    normalized = _normalized(image)
    phash = str(imagehash.phash(normalized, hash_size=8))
    crop = imagehash.crop_resistant_hash(normalized)
    crop_hashes = json.dumps([str(segment) for segment in crop.segment_hashes], separators=(",", ":"))
    rgb = np.asarray(normalized, dtype=np.uint8)
    vector, quality = pdqhash.compute(rgb)
    pdq = _pdq_to_hex(vector)
    return phash, crop_hashes, pdq, int(quality)


def _hash_image(asset: Asset, path: Path) -> None:
    with Image.open(path) as image:
        asset.width, asset.height = image.size
        asset.phash, asset.crop_hashes, asset.pdq_hash, asset.pdq_quality = _still_hashes(image)


def _hash_gif(asset: Asset, path: Path, config: Config) -> None:
    with Image.open(path) as image:
        asset.width, asset.height = image.size
        frame_count = int(getattr(image, "n_frames", 1))
        duration_ms = sum(int(frame.info.get("duration", image.info.get("duration", 100))) for frame in ImageSequence.Iterator(image))
        asset.duration = duration_ms / 1000
        image.seek(0)
        asset.phash, asset.crop_hashes, asset.pdq_hash, asset.pdq_quality = _still_hashes(image)
        if frame_count > 1:
            step = _ceiling_sample_step(frame_count, config.max_video_frames)
            hashes: list[dict[str, int | str]] = []
            elapsed = 0
            for index in range(frame_count):
                image.seek(index)
                if index % step == 0:
                    normalized = _normalized(image.copy())
                    vector, quality = pdqhash.compute(np.asarray(normalized, dtype=np.uint8))
                    hashes.append({"h": _pdq_to_hex(vector), "q": int(quality), "t": elapsed})
                elapsed += int(image.info.get("duration", 100))
            asset.vpdq_hashes = json.dumps(hashes, separators=(",", ":"))


def _ceiling_sample_step(frame_count: int, maximum_samples: int) -> int:
    """Choose an evenly spaced step that never exceeds the configured sample count."""
    return max(1, (frame_count + maximum_samples - 1) // maximum_samples)


def _hash_video(asset: Asset, path: Path, config: Config) -> None:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError("OpenCV could not open the video")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        asset.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        asset.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        asset.duration = frame_count / fps if fps > 0 and frame_count > 0 else None
        interval_frames = max(1, int(round(fps * config.video_sample_seconds))) if fps > 0 else 30
        hashes: list[dict[str, int | str]] = []
        representative: Image.Image | None = None
        representative_quality = -1
        frame_index = 0
        while len(hashes) < config.max_video_frames:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            image = _normalized(image)
            vector, quality = pdqhash.compute(np.asarray(image, dtype=np.uint8))
            if int(quality) > representative_quality:
                representative = image.copy()
                representative_quality = int(quality)
            timestamp_ms = int(capture.get(cv2.CAP_PROP_POS_MSEC) or 0)
            hashes.append({"h": _pdq_to_hex(vector), "q": int(quality), "t": timestamp_ms})
            frame_index += interval_frames
            if frame_count > 0 and frame_index >= frame_count:
                break
        if not hashes:
            raise ValueError("No decodable video frames were found")
        asset.vpdq_hashes = json.dumps(hashes, separators=(",", ":"))
        if representative is not None:
            asset.phash, asset.crop_hashes, asset.pdq_hash, asset.pdq_quality = _still_hashes(representative)
    finally:
        capture.release()


def _pdq_to_hex(vector: np.ndarray) -> str:
    bits = np.asarray(vector, dtype=np.uint8).reshape(-1)
    if bits.size != 256:
        raise ValueError(f"PDQ returned {bits.size} bits instead of 256")
    return np.packbits(bits).tobytes().hex()
