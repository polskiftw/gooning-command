from __future__ import annotations

import hashlib
import math
import os
import threading
import tkinter as tk
from pathlib import Path

import cv2
from PIL import Image, ImageOps, ImageTk, ImageSequence


class PreviewCache:
    def __init__(self, directory: Path, maximum_bytes: int):
        self.directory = directory
        self.maximum_bytes = maximum_bytes
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path_for(self, key: str) -> Path:
        extension = key.rsplit(".", 1)[-1].lower() if "." in key else "bin"
        name = hashlib.sha256(key.encode("utf-8")).hexdigest() + "." + extension
        return self.directory / name

    def obtain(self, key: str, downloader) -> Path:
        destination = self.path_for(key)
        with self._lock:
            if destination.exists() and destination.stat().st_size > 0:
                os.utime(destination, None)
                return destination
            partial = destination.with_suffix(destination.suffix + ".part")
            partial.unlink(missing_ok=True)
            downloader(key, partial)
            partial.replace(destination)
            self.prune(protected=destination)
        return destination

    def prune(self, protected: Path | None = None) -> None:
        with self._lock:
            files = [path for path in self.directory.iterdir() if path.is_file() and not path.name.endswith(".part")]
            total = sum(path.stat().st_size for path in files)
            for path in sorted(files, key=lambda item: item.stat().st_atime):
                if total <= self.maximum_bytes:
                    break
                if protected is not None and path == protected:
                    continue
                size = path.stat().st_size
                path.unlink(missing_ok=True)
                total -= size


class MediaPreview(tk.Frame):
    VIDEO_EXTENSIONS = {"mp4", "m4v", "webm"}

    def __init__(self, master, *, background: str = "#111"):
        super().__init__(master, background=background)
        # A Label changes its requested size whenever a differently sized image is
        # assigned. That made both comparison columns repeatedly stretch and bounce
        # while previews arrived. Canvas items never participate in geometry sizing.
        self.canvas = tk.Canvas(
            self,
            background=background,
            highlightthickness=0,
            borderwidth=0,
            width=1,
            height=1,
        )
        self.canvas.pack(fill="both", expand=True)
        self._image_item = self.canvas.create_image(0, 0, anchor="center")
        self._text_item = self.canvas.create_text(
            0,
            0,
            text="No media",
            fill="#aaa",
            justify="center",
            anchor="center",
        )
        self._after_id: str | None = None
        self._frames: list[Image.Image] = []
        self._frame_delays: list[int] = []
        self._frame_index = 0
        self._capture: cv2.VideoCapture | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._generation = 0
        self.canvas.bind("<Configure>", self._redraw)

    def clear(self, text: str = "Loading…") -> None:
        self.stop()
        self.canvas.itemconfigure(self._image_item, image="")
        self.canvas.itemconfigure(self._text_item, text=text)
        self._center_items()

    def stop(self) -> None:
        self._generation += 1
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self._after_id = None
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self._frames = []
        self._frame_delays = []
        self._photo = None

    def load(self, path: Path) -> None:
        self.stop()
        extension = path.suffix.lower().lstrip(".")
        try:
            if extension in self.VIDEO_EXTENSIONS:
                self._load_video(path)
            else:
                self._load_image(path)
        except Exception as exc:
            self.canvas.itemconfigure(self._image_item, image="")
            self.canvas.itemconfigure(
                self._text_item,
                text=f"Preview failed\n{type(exc).__name__}",
            )
            self._center_items()

    def _load_image(self, path: Path) -> None:
        image = Image.open(path)
        if getattr(image, "is_animated", False):
            frames: list[Image.Image] = []
            delays: list[int] = []
            frame_count = int(getattr(image, "n_frames", 1))
            step = max(1, math.ceil(frame_count / 180))
            carried_delay = 0
            for index, frame in enumerate(ImageSequence.Iterator(image)):
                carried_delay += max(20, int(frame.info.get("duration", image.info.get("duration", 100))))
                if index % step != 0:
                    continue
                rendered = ImageOps.exif_transpose(frame.copy()).convert("RGB")
                rendered.thumbnail((1600, 1000), Image.Resampling.LANCZOS)
                frames.append(rendered)
                delays.append(carried_delay)
                carried_delay = 0
            image.close()
            self._frames = frames
            self._frame_delays = delays
            self._frame_index = 0
            self._show_animation_frame(self._generation)
        else:
            still = ImageOps.exif_transpose(image).convert("RGB")
            image.close()
            still.thumbnail((2000, 1400), Image.Resampling.LANCZOS)
            self._frames = [still]
            self._render(still)

    def _load_video(self, path: Path) -> None:
        self._capture = cv2.VideoCapture(str(path))
        if not self._capture.isOpened():
            raise ValueError("Cannot decode video")
        fps = float(self._capture.get(cv2.CAP_PROP_FPS) or 0)
        delay = max(42, round(1000 / fps)) if fps > 0 else 42
        self._frame_delays = [delay]
        self._show_video_frame(self._generation)

    def _show_animation_frame(self, generation: int) -> None:
        if generation != self._generation or not self._frames:
            return
        self._render(self._frames[self._frame_index])
        delay = self._frame_delays[self._frame_index]
        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self._after_id = self.after(delay, self._show_animation_frame, generation)

    def _show_video_frame(self, generation: int) -> None:
        if generation != self._generation or self._capture is None:
            return
        ok, frame = self._capture.read()
        if not ok:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._capture.read()
        if ok:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self._render(Image.fromarray(rgb))
        self._after_id = self.after(self._frame_delays[0], self._show_video_frame, generation)

    def _render(self, image: Image.Image) -> None:
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        rendered = image.copy()
        rendered.thumbnail((width, height), Image.Resampling.BILINEAR)
        self._photo = ImageTk.PhotoImage(rendered)
        self.canvas.itemconfigure(self._image_item, image=self._photo)
        self.canvas.itemconfigure(self._text_item, text="")
        self._center_items()

    def _center_items(self) -> None:
        center = (
            max(1, self.canvas.winfo_width()) // 2,
            max(1, self.canvas.winfo_height()) // 2,
        )
        self.canvas.coords(self._image_item, *center)
        self.canvas.coords(self._text_item, *center)

    def _redraw(self, _event=None) -> None:
        self._center_items()
        if len(self._frames) == 1:
            self._render(self._frames[0])

    def destroy(self) -> None:
        self.stop()
        super().destroy()
