from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence


VIDEO_EXTENSIONS = {"mp4", "m4v", "webm"}


def _sample_positions(total: int, wanted: int) -> list[int]:
    if total <= 1 or wanted <= 1:
        return [0]
    count = min(total, wanted)
    return sorted({int(round(position)) for position in np.linspace(0, total - 1, count)})


def _load_pillow_frames(path: Path, wanted: int) -> list[Image.Image]:
    with Image.open(path) as source:
        total = int(getattr(source, "n_frames", 1) or 1)
        positions = set(_sample_positions(total, wanted))
        frames = [
            frame.convert("RGB").copy()
            for index, frame in enumerate(ImageSequence.Iterator(source))
            if index in positions
        ]
    if not frames:
        raise OSError("No readable image frames were found")
    return frames


def _load_video_frames(path: Path, wanted: int) -> list[Image.Image]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        positions = _sample_positions(max(1, total), wanted)
        frames: list[Image.Image] = []
        for position in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, position)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(rgb))
        if not frames:
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = capture.read()
            if ok and frame is not None:
                frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    finally:
        capture.release()
    if not frames:
        raise OSError("No readable video frames were found")
    return frames


def load_frames(path: Path, extension: str, wanted: int) -> list[Image.Image]:
    if extension.lower() in VIDEO_EXTENSIONS:
        return _load_video_frames(path, wanted)
    return _load_pillow_frames(path, wanted)

