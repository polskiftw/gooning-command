from __future__ import annotations

import os
import urllib.request
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image


MODEL_ID = "fancyfeast/joytag"
MODEL_BASE_URL = "https://huggingface.co/fancyfeast/joytag/resolve/main"
MODEL_FILES = ("model.onnx", "top_tags.txt")
MODEL_MINIMUM_BYTES = {"model.onnx": 300 * 1024 * 1024, "top_tags.txt": 50 * 1024}
IMAGE_SIZE = 448
MEAN = np.asarray([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.asarray([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def _download_file(
    url: str,
    destination: Path,
    progress: Callable[[str, int, int], None],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "GParty-Tag-Time/1.0"}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=180) as response:
        resumed = response.status == 206 and existing > 0
        if not resumed:
            existing = 0
        declared = int(response.headers.get("Content-Length") or 0)
        total = existing + declared if declared else 0
        mode = "ab" if resumed else "wb"
        current = existing
        with partial.open(mode) as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                current += len(block)
                progress(destination.name, current, total)
            output.flush()
            os.fsync(output.fileno())

    if total and current != total:
        raise OSError(f"The {destination.name} download ended early")
    os.replace(partial, destination)


def ensure_model(
    model_directory: Path,
    progress: Callable[[str, int, int], None],
) -> None:
    for filename in MODEL_FILES:
        destination = model_directory / filename
        minimum = MODEL_MINIMUM_BYTES[filename]
        if destination.exists() and destination.stat().st_size >= minimum:
            continue
        destination.unlink(missing_ok=True)
        _download_file(f"{MODEL_BASE_URL}/{filename}", destination, progress)
        if destination.stat().st_size < minimum:
            destination.unlink(missing_ok=True)
            raise OSError(f"The downloaded {filename} is incomplete")


def prepare_image(image: Image.Image) -> np.ndarray:
    image = image.convert("RGB")
    max_dimension = max(image.size)
    padded = Image.new("RGB", (max_dimension, max_dimension), (255, 255, 255))
    left = (max_dimension - image.width) // 2
    top = (max_dimension - image.height) // 2
    padded.paste(image, (left, top))
    if padded.size != (IMAGE_SIZE, IMAGE_SIZE):
        padded = padded.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BICUBIC)

    pixels = np.asarray(padded, dtype=np.float32) / 255.0
    pixels = (pixels - MEAN) / STD
    return np.transpose(pixels, (2, 0, 1))[None, ...].astype(np.float32, copy=False)


class JoyTagger:
    def __init__(self, model_directory: Path):
        import onnxruntime as ort

        available = set(ort.get_available_providers())
        providers = []
        if "DmlExecutionProvider" in available:
            providers.append("DmlExecutionProvider")
        providers.append("CPUExecutionProvider")
        session_options = ort.SessionOptions()
        session_options.enable_mem_pattern = False
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(
            str(model_directory / "model.onnx"),
            sess_options=session_options,
            providers=providers,
        )
        self.input_name = self.session.get_inputs()[0].name
        self.tags = [
            line.strip()
            for line in (model_directory / "top_tags.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not self.tags:
            raise RuntimeError("JoyTag's tag list is empty")

    @property
    def provider(self) -> str:
        return self.session.get_providers()[0]

    def predict_scores(self, image: Image.Image) -> dict[str, float]:
        outputs = self.session.run(None, {self.input_name: prepare_image(image)})
        scores = None
        for output in outputs:
            candidate = np.asarray(output).squeeze()
            if candidate.ndim == 1 and candidate.shape[0] == len(self.tags):
                scores = candidate.astype(np.float32, copy=False)
                break
        if scores is None:
            raise RuntimeError("JoyTag returned an unexpected result")
        scores = np.clip(scores, -80.0, 80.0)
        scores = 1.0 / (1.0 + np.exp(-scores))
        return {tag: float(score) for tag, score in zip(self.tags, scores, strict=True)}
