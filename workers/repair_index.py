from __future__ import annotations

import json
import mimetypes
import os
import time
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

INDEX_KEY = os.getenv("R2_INDEX_KEY", "gallery-index.json")
GALLERY_PREFIX = os.getenv("R2_GALLERY_PREFIX", "gallery/").strip("/") + "/"
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "mp4", "m4v", "webm"}


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def r2_client():
    account_id = required_env("R2_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=required_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=required_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 8, "mode": "adaptive"}),
    )


def read_index(client, bucket: str) -> list[dict[str, Any]]:
    try:
        response = client.get_object(Bucket=bucket, Key=INDEX_KEY)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"NoSuchKey", "404", "NotFound"}:
            return []
        raise

    payload = json.loads(response["Body"].read().decode("utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    if isinstance(payload, list):
        return payload
    raise RuntimeError(f"{INDEX_KEY} has an unsupported format")


def list_gallery_objects(client, bucket: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=GALLERY_PREFIX):
        for item in page.get("Contents", []):
            key = str(item.get("Key", ""))
            size = int(item.get("Size", 0))
            extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
            if not key or key.endswith("/") or size <= 0 or extension not in ALLOWED_EXTENSIONS:
                continue
            objects.append({"key": key, "ext": extension, "size": size})
    return objects


def write_index(client, bucket: str, items: list[dict[str, Any]]) -> None:
    payload = {
        "version": 1,
        "generated_at": int(time.time()),
        "count": len(items),
        "items": items,
    }
    client.put_object(
        Bucket=bucket,
        Key=INDEX_KEY,
        Body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache",
    )


def main() -> int:
    client = r2_client()
    bucket = required_env("R2_BUCKET_NAME")

    index_items = read_index(client, bucket)
    indexed_keys = {
        str(item.get("key"))
        for item in index_items
        if isinstance(item, dict) and item.get("key")
    }
    gallery_objects = list_gallery_objects(client, bucket)
    missing = [item for item in gallery_objects if item["key"] not in indexed_keys]

    print(f"R2 media objects found: {len(gallery_objects)}")
    print(f"Already indexed: {len(gallery_objects) - len(missing)}")
    print(f"Missing entries found: {len(missing)}")

    if missing:
        index_items.extend(missing)
        write_index(client, bucket, index_items)
        print(f"Missing entries restored: {len(missing)}")
    else:
        print("The gallery index was already complete; no write was needed.")

    print("Objects deleted: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
