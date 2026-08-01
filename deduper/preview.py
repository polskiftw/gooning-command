from __future__ import annotations

import io
import math
import tempfile
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
from PIL import Image, ImageOps, ImageTk, ImageSequence


class PreviewCancelled(Exception):
    pass


@dataclass(slots=True)
class PreparedPreview:
    frames: list[Image.Image]
    delays: list[int]


def prepare_preview(
    data: bytes,
    extension: str,
    cancelled: Callable[[], bool] | None = None,
) -> PreparedPreview:
    """Decode and resize media away from Tk's UI thread.

    Preview work is deliberately bounded. A huge GIF or long video should be a
    useful moving preview, not hundreds of full-resolution frames consuming RAM
    and freezing navigation after the user has already moved to another pair.
    """
    is_cancelled = cancelled or (lambda: False)
    extension = extension.lower().lstrip(".")
    if extension in MediaPreview.VIDEO_EXTENSIONS:
        # OpenCV requires a seekable filename for compressed video. This file
        # exists only during decoding and is removed before the preview is shown;
        # it is not a cache and is never reused by later navigation.
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}") as temporary:
                temporary.write(data)
                temporary_path = Path(temporary.name)
            capture = cv2.VideoCapture(str(temporary_path))
            if not capture.isOpened():
                capture.release()
                raise ValueError("Cannot decode video")
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
            source_fps = fps if fps > 0 else 24.0
            stride = max(1, round(source_fps / 6.0))
            frames: list[Image.Image] = []
            source_index = 0
            while len(frames) < 60:
                if is_cancelled():
                    raise PreviewCancelled()
                ok, frame = capture.read()
                if not ok:
                    break
                if source_index % stride == 0:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(rgb)
                    image.thumbnail((720, 540), Image.Resampling.BILINEAR)
                    frames.append(image)
                source_index += 1
            if not frames:
                raise ValueError("Cannot decode video frames")
            return PreparedPreview(frames, [167] * len(frames))
        finally:
            if "capture" in locals():
                capture.release()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    image = Image.open(io.BytesIO(data))
    try:
        if not getattr(image, "is_animated", False):
            still = ImageOps.exif_transpose(image).convert("RGB")
            still.thumbnail((2000, 1400), Image.Resampling.LANCZOS)
            return PreparedPreview([still], [100])

        frames = []
        delays = []
        frame_count = int(getattr(image, "n_frames", 1))
        step = max(1, math.ceil(frame_count / 60))
        carried_delay = 0
        for index, frame in enumerate(ImageSequence.Iterator(image)):
            if is_cancelled():
                raise PreviewCancelled()
            carried_delay += max(20, int(frame.info.get("duration", image.info.get("duration", 100))))
            if index % step != 0:
                continue
            rendered = ImageOps.exif_transpose(frame.copy()).convert("RGB")
            rendered.thumbnail((720, 540), Image.Resampling.LANCZOS)
            frames.append(rendered)
            delays.append(carried_delay)
            carried_delay = 0
        if not frames:
            raise ValueError("Cannot decode animation frames")
        return PreparedPreview(frames, delays)
    finally:
        image.close()


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
        self._frames = []
        self._frame_delays = []
        self._photo = None

    def load(self, path: Path) -> None:
        """Synchronous compatibility helper; the app uses prepare_preview in a worker."""
        try:
            self.load_prepared(prepare_preview(path.read_bytes(), path.suffix))
        except Exception as exc:
            self.canvas.itemconfigure(self._image_item, image="")
            self.canvas.itemconfigure(
                self._text_item,
                text=f"Preview failed\n{type(exc).__name__}",
            )
            self._center_items()

    def load_prepared(self, preview: PreparedPreview) -> None:
        self.stop()
        self._frames = preview.frames
        self._frame_delays = preview.delays
        self._frame_index = 0
        if len(self._frames) == 1:
            self._render(self._frames[0])
        else:
            self._show_animation_frame(self._generation)

    def _show_animation_frame(self, generation: int) -> None:
        if generation != self._generation or not self._frames:
            return
        self._render(self._frames[self._frame_index])
        delay = self._frame_delays[self._frame_index]
        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self._after_id = self.after(delay, self._show_animation_frame, generation)

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
