from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.client import Config as BotoConfig

from .config import Config
from .database import Asset


ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "mp4", "m4v", "webm"}
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
                assets.append(
                    Asset(
                        key=key,
                        size=size,
                        etag=str(item.get("ETag", "")).strip('"'),
                        extension=extension,
                    )
                )
        return assets

    def download(
        self,
        key: str,
        destination: Path,
        callback: Callable[[int], None] | None = None,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(
            self.config.bucket_name,
            key,
            str(destination),
            Callback=callback,
            Config=TRANSFER_CONFIG,
        )

    def upload_tag_index(self, body: bytes) -> None:
        self.client.put_object(
            Bucket=self.config.bucket_name,
            Key=self.config.tag_index_key,
            Body=body,
            ContentType="application/json; charset=utf-8",
            CacheControl="no-store",
            Metadata={"private": "true", "purpose": "tag-index-v1"},
        )

