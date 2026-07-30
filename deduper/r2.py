from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from .config import Config
from .models import Asset


ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "mp4", "m4v", "webm"}
VIDEO_EXTENSIONS = {"mp4", "m4v", "webm"}
TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=16 * 1024 * 1024,
    multipart_chunksize=8 * 1024 * 1024,
    max_concurrency=2,
    use_threads=True,
)


class R2Store:
    def __init__(self, config: Config):
        self.config = config
        self.client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name="auto",
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 8, "mode": "adaptive"},
                connect_timeout=30,
                read_timeout=180,
                tcp_keepalive=True,
            ),
        )

    def verify(self) -> None:
        self.client.head_bucket(Bucket=self.config.bucket_name)

    def list_assets(self) -> list[Asset]:
        assets: list[Asset] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self.config.bucket_name,
            Prefix=self.config.gallery_prefix,
        ):
            for item in page.get("Contents", []):
                key = str(item.get("Key", ""))
                extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
                size = int(item.get("Size", 0))
                if not key or key.endswith("/") or size <= 0 or extension not in ALLOWED_EXTENSIONS:
                    continue
                media_type = "video" if extension in VIDEO_EXTENSIONS else "image"
                modified = item.get("LastModified")
                assets.append(
                    Asset(
                        key=key,
                        size=size,
                        etag=str(item.get("ETag", "")).strip('"'),
                        last_modified=modified.isoformat() if modified else "",
                        media_type=media_type,
                        extension=extension,
                    )
                )
        return assets

    def download(self, key: str, destination: Path, callback: Callable[[int], None] | None = None) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(
            self.config.bucket_name,
            key,
            str(destination),
            Callback=callback,
            Config=TRANSFER_CONFIG,
        )

    def delete_queued(
        self, queued: Iterable[tuple[str, int | None, int]]
    ) -> tuple[list[tuple[str, int | None, int, str]], list[str], str | None]:
        queued_list = list(queued)
        results: list[tuple[str, int | None, int, str]] = []
        deleted_keys: list[str] = []
        for start in range(0, len(queued_list), 1000):
            batch = queued_list[start : start + 1000]
            response = self.client.delete_objects(
                Bucket=self.config.bucket_name,
                Delete={"Objects": [{"Key": key} for key, _, _ in batch], "Quiet": False},
            )
            deleted = {item["Key"] for item in response.get("Deleted", [])}
            errors = {item["Key"]: item.get("Message", "R2 delete failed") for item in response.get("Errors", [])}
            for key, pair_id, size in batch:
                if key in deleted:
                    results.append((key, pair_id, size, "deleted"))
                    deleted_keys.append(key)
                else:
                    results.append((key, pair_id, size, errors.get(key, "R2 did not confirm deletion")))
        index_error = None
        if deleted_keys:
            try:
                self.remove_from_gallery_index(set(deleted_keys))
            except Exception as exc:
                index_error = f"{type(exc).__name__}: {exc}"
        return results, deleted_keys, index_error

    def remove_from_gallery_index(self, deleted_keys: set[str]) -> int:
        for attempt in range(5):
            try:
                response = self.client.get_object(
                    Bucket=self.config.bucket_name,
                    Key=self.config.index_key,
                )
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"NoSuchKey", "404", "NotFound"}:
                    return 0
                raise

            payload = json.loads(response["Body"].read().decode("utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("items"), list):
                original = payload["items"]
                remaining = [
                    item
                    for item in original
                    if not (isinstance(item, dict) and str(item.get("key", "")) in deleted_keys)
                ]
                payload["items"] = remaining
                payload["count"] = len(remaining)
                payload["generated_at"] = int(time.time())
            elif isinstance(payload, list):
                original = payload
                remaining = [
                    item
                    for item in original
                    if not (isinstance(item, dict) and str(item.get("key", "")) in deleted_keys)
                ]
                payload = remaining
            else:
                raise RuntimeError(f"{self.config.index_key} has an unsupported format")

            removed = len(original) - len(remaining)
            if not removed:
                return 0
            try:
                self.client.put_object(
                    Bucket=self.config.bucket_name,
                    Key=self.config.index_key,
                    Body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                    ContentType="application/json",
                    CacheControl="no-cache",
                    IfMatch=str(response.get("ETag", "")).strip('"'),
                )
                return removed
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code not in {"PreconditionFailed", "412"} or attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
        raise RuntimeError("Gallery index changed repeatedly during cleanup")
