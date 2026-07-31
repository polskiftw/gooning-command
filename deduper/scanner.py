from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import Config
from .hashing import hash_file
from .models import Asset
from .r2 import R2Store


StatusCallback = Callable[[int, int, str], None]
SaveCallback = Callable[[Asset], None]


def scan_assets(
    assets: Iterable[Asset],
    store: R2Store,
    config: Config,
    save: SaveCallback,
    status: StatusCallback,
    cancel: threading.Event,
) -> tuple[int, int]:
    """Download and hash pending assets concurrently while saving each completed result.

    Images/GIFs can fan out broadly. Video work is deliberately bounded because each
    decoder is CPU- and memory-heavy. Completed assets are saved immediately, so a
    cancelled scan resumes from only the unfinished items next time.
    """
    pending = list(assets)
    if not pending:
        return 0, 0

    work_directory = Path(tempfile.mkdtemp(prefix="gparty-scan-"))
    video_slots = threading.Semaphore(config.video_workers)
    completed = 0
    errors = 0

    def process(position: int, asset: Asset) -> Asset:
        if cancel.is_set():
            raise _ScanCancelled()
        local_path = work_directory / f"{position:08d}.{asset.extension}"
        try:
            store.download(asset.key, local_path)
            if cancel.is_set():
                raise _ScanCancelled()
            if asset.media_type == "video" or asset.extension == "gif":
                with video_slots:
                    if cancel.is_set():
                        raise _ScanCancelled()
                    hash_file(asset, local_path, config)
            else:
                hash_file(asset, local_path, config)
            return asset
        except _ScanCancelled:
            raise
        except Exception as exc:
            asset.scan_error = f"{type(exc).__name__}: {exc}"[:1000]
            return asset
        finally:
            local_path.unlink(missing_ok=True)

    futures: dict[Future[Asset], tuple[int, Asset]] = {}
    executor = ThreadPoolExecutor(
        max_workers=config.scan_workers,
        thread_name_prefix="gparty-scan",
    )
    try:
        for position, asset in enumerate(pending, 1):
            if cancel.is_set():
                break
            futures[executor.submit(process, position, asset)] = (position, asset)

        for future in as_completed(futures):
            position, asset = futures[future]
            if cancel.is_set():
                break
            try:
                result = future.result()
            except _ScanCancelled:
                continue
            save(result)
            completed += 1
            if result.scan_error:
                errors += 1
            status(completed, len(pending), result.key)
    finally:
        cancel.set() if cancel.is_set() else None
        for future in futures:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        shutil.rmtree(work_directory, ignore_errors=True)

    return completed, errors


class _ScanCancelled(Exception):
    pass
