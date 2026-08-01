from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .database import TagDatabase
from .index import build_tag_index
from .media import load_frames
from .model import MODEL_ID, JoyTagger, ensure_model
from .r2 import R2Store


EventCallback = Callable[[str, dict], None]


class TagTimeRunner:
    def __init__(
        self,
        config: Config,
        data_directory: Path,
        cancel: threading.Event,
        callback: EventCallback,
    ):
        self.config = config
        self.data_directory = data_directory
        self.cancel = cancel
        self.callback = callback

    def emit(self, name: str, **values: object) -> None:
        self.callback(name, values)

    def publish(self, database: TagDatabase, store: R2Store) -> None:
        body = build_tag_index(
            database.tagged_rows(),
            threshold=self.config.threshold,
            model=MODEL_ID,
        )
        store.upload_tag_index(body)

    def run(self) -> None:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        model_directory = self.data_directory / "model"
        temporary_directory = self.data_directory / "temp"
        shutil.rmtree(temporary_directory, ignore_errors=True)
        temporary_directory.mkdir(parents=True, exist_ok=True)
        database = TagDatabase(self.data_directory / "tag-time.sqlite3")
        store: R2Store | None = None
        try:
            self.emit("status", text="Preparing JoyTag…")
            ensure_model(
                model_directory,
                lambda filename, current, total: self.emit(
                    "model_progress",
                    filename=filename,
                    current=current,
                    total=total,
                ),
            )
            if self.cancel.is_set():
                self.emit("finished", cancelled=True)
                return

            tagger = JoyTagger(model_directory)
            acceleration = "RTX / DirectML" if tagger.provider == "DmlExecutionProvider" else "CPU"
            self.emit("status", text=f"JoyTag ready ({acceleration}). Reading R2…")
            store = R2Store(self.config)
            store.verify()
            assets = store.list_assets()
            database.sync_assets(assets)
            pending = database.pending()
            total, tagged, errors = database.counts()
            self.emit("scan_ready", total=total, tagged=tagged, remaining=len(pending), errors=errors)

            completed_this_run = 0
            for position, asset in enumerate(pending, 1):
                if self.cancel.is_set():
                    break
                self.emit(
                    "asset",
                    position=position,
                    remaining=len(pending),
                    key=asset.key,
                )
                local_path = temporary_directory / f"current.{asset.extension}"
                try:
                    store.download(asset.key, local_path)
                    frames = load_frames(local_path, asset.extension, self.config.animated_frames)
                    best: dict[str, float] = {}
                    for frame in frames:
                        for tag, score in tagger.predict_scores(frame).items():
                            if score > best.get(tag, 0.0):
                                best[tag] = score
                    tags = [
                        tag
                        for tag, score in sorted(best.items(), key=lambda item: (-item[1], item[0]))
                        if score >= self.config.threshold
                    ]
                    database.mark_tagged(
                        asset.key,
                        tags,
                        datetime.now(timezone.utc).isoformat(),
                    )
                    completed_this_run += 1
                except Exception as problem:
                    database.mark_error(asset.key, f"{type(problem).__name__}: {problem}")
                    self.emit("asset_error")
                finally:
                    local_path.unlink(missing_ok=True)

                if completed_this_run and completed_this_run % self.config.publish_every == 0:
                    self.emit("status", text="Saving the newest tags to GParty…")
                    self.publish(database, store)

            self.emit("status", text="Saving the tag catalog to GParty…")
            self.publish(database, store)
            total, tagged, errors = database.counts()
            self.emit(
                "finished",
                cancelled=self.cancel.is_set(),
                total=total,
                tagged=tagged,
                errors=errors,
            )
        except Exception as problem:
            self.emit("fatal", message=f"{type(problem).__name__}: {problem}")
        finally:
            database.close()
            shutil.rmtree(temporary_directory, ignore_errors=True)

