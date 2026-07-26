from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import mimetypes
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

APP_VERSION = "0.2.3"
BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = Path(os.getenv("SETTINGS_PATH", BASE_DIR / "settings.json"))
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / ".run-data"))
ARCHIVE_PATH = DATA_DIR / "gallery-dl-archive.sqlite3"
CONFIG_PATH = DATA_DIR / "gallery-dl.generated.json"
COOKIES_PATH = DATA_DIR / "reddit-cookies.txt"
INDEX_KEY = os.getenv("R2_INDEX_KEY", "gallery-index.json")
ARCHIVE_R2_KEY = os.getenv("R2_ARCHIVE_KEY", "_internal/gallery-dl-archive-v0.2.1.sqlite3")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("gooning-party")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required GitHub Actions secret/environment variable: {name}")
    return value


def load_settings() -> dict[str, Any]:
    with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
        settings = json.load(handle)
    sources = settings.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("settings.json must contain at least one source URL")
    placeholders = [source for source in sources if "CHANGE_THIS_SUBREDDIT" in str(source)]
    if placeholders:
        raise RuntimeError(
            "You still have CHANGE_THIS_SUBREDDIT placeholders in settings.json. "
            "Replace all three with real subreddit names first."
        )
    # Friendly validation for the knobs you are expected to edit.
    posts = int(settings.get("posts_per_subreddit_per_scan", 50))
    delay_min = float(settings.get("reddit_request_delay_min_seconds", 2))
    delay_max = float(settings.get("reddit_request_delay_max_seconds", 4))
    abort_after = int(settings.get("stop_after_consecutive_archived_posts", 15))
    backoff = float(settings.get("reddit_429_backoff_seconds", 60))
    if posts < 1:
        raise RuntimeError("posts_per_subreddit_per_scan must be at least 1")
    if delay_min < 0 or delay_max < delay_min:
        raise RuntimeError("Reddit request delay must be 0 or greater, and max must be at least min")
    if abort_after < 1:
        raise RuntimeError("stop_after_consecutive_archived_posts must be at least 1")
    if backoff < 0:
        raise RuntimeError("reddit_429_backoff_seconds must be 0 or greater")
    return settings


def r2_client():
    account_id = required_env("R2_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=required_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=required_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def write_reddit_cookies() -> None:
    encoded = required_env("REDDIT_COOKIES_BASE64")
    try:
        cookie_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(
            "REDDIT_COOKIES_BASE64 is invalid. Paste the entire one-line Base64 value, "
            "with no quotation marks and no missing characters."
        ) from exc

    text = cookie_bytes.decode("utf-8-sig", errors="strict")
    if "reddit.com" not in text.lower():
        raise RuntimeError("The decoded cookie file does not appear to contain Reddit cookies.")
    if not text.lstrip().startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")):
        raise RuntimeError("The decoded cookie file is not Netscape cookies.txt format.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_PATH.write_text(text, encoding="utf-8")
    try:
        COOKIES_PATH.chmod(0o600)
    except OSError:
        pass
    log.info("Prepared Reddit browser cookies (no OAuth app or developer API credentials)")


def restore_archive(client, bucket: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(bucket, ARCHIVE_R2_KEY, str(ARCHIVE_PATH))
        log.info("Restored prior download history from R2")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"NoSuchKey", "404", "NotFound"}:
            log.info("No prior download history exists yet; this is normal on the first run")
            return
        raise


def save_archive(client, bucket: str) -> None:
    if not ARCHIVE_PATH.exists() or ARCHIVE_PATH.stat().st_size == 0:
        log.warning("No download-history file was produced, so there is nothing to save")
        return
    client.upload_file(
        str(ARCHIVE_PATH),
        bucket,
        ARCHIVE_R2_KEY,
        ExtraArgs={"ContentType": "application/x-sqlite3", "CacheControl": "no-store"},
    )
    log.info("Saved download history to R2 for the next GitHub Actions run")


def build_gallery_dl_config(settings: dict[str, Any]) -> None:
    write_reddit_cookies()
    config = {
        "extractor": {
            "base-directory": "/tmp/gooning-party-downloads",
            # Never use full Reddit titles as local filenames. Linux limits one
            # filename component to 255 bytes, and some post titles exceed that.
            # Prefer a stable media/post ID, fall back to a safely truncated
            # original filename, and keep a gallery item number for albums.
            "filename": "{category}_{id|media_id|display_id|filename:X80}_{num|_lit[0]:>03}.{extension}",
            "archive": str(ARCHIVE_PATH),
            "retries": int(settings.get("download_retries", 4)),
            "timeout": int(settings.get("download_timeout_seconds", 45)),
            # Wait a small random amount between Reddit/page requests.
            "sleep-request": (
                f"{float(settings.get('reddit_request_delay_min_seconds', 2)):g}-"
                f"{float(settings.get('reddit_request_delay_max_seconds', 4)):g}"
            ),
            # On HTTP 429, pause before gallery-dl retries.
            "sleep-429": float(settings.get("reddit_429_backoff_seconds", 60)),
            "cookies": str(COOKIES_PATH),
            "cookies-update": str(COOKIES_PATH),
            "reddit": {
                "api": "rest",
                "cookies": str(COOKIES_PATH),
                "videos": True,
            },
            "ytdl": {"enabled": True},
        },
        "downloader": {
            "part-directory": "/tmp/gooning-party-parts",
            "ytdl": {
                "format": "bestvideo*+bestaudio/best",
                "forward-cookies": True,
            },
        },
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log.info("Generated gallery-dl configuration")


def read_index(client, bucket: str) -> list[dict[str, Any]]:
    try:
        response = client.get_object(Bucket=bucket, Key=INDEX_KEY)
        payload = json.loads(response["Body"].read().decode("utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return payload["items"]
        if isinstance(payload, list):
            return payload
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"NoSuchKey", "404", "NotFound"}:
            raise
    return []


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


def safe_name(path: Path) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in path.name)
    return clean[-160:] or "media.bin"


def object_key(prefix: str, file_path: Path, relative_path: str) -> str:
    # Stable for the same downloaded file/path. It is not an image-content duplicate checker.
    digest = hashlib.sha1()
    digest.update(relative_path.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    fingerprint = digest.hexdigest()[:20]
    return f"{prefix.strip('/')}/{fingerprint}_{safe_name(file_path)}"


def run_gallery_dl(source: str, destination: Path, settings: dict[str, Any]) -> int:
    posts = int(settings.get("posts_per_subreddit_per_scan", 50))
    abort_after = int(settings.get("stop_after_consecutive_archived_posts", 15))
    command = [
        "gallery-dl",
        "--config",
        str(CONFIG_PATH),
        "-o",
        f"extractor.base-directory={destination}",
        "--post-range",
        f"1-{posts}",
        "--abort",
        str(abort_after),
        source,
    ]
    log.info(
        "Scanning source: %s (newest %s posts; stop after %s consecutive archived skips)",
        source,
        posts,
        abort_after,
    )
    result = subprocess.run(command, text=True, check=False)
    if result.returncode != 0:
        log.warning(
            "gallery-dl finished with code %s for %s. "
            "This can mean a partial failure; any files that did download will still be uploaded.",
            result.returncode,
            source,
        )
    return result.returncode


def upload_downloads(settings: dict[str, Any], scan_root: Path, client, bucket: str) -> tuple[int, int]:
    allowed = {str(ext).lower().lstrip(".") for ext in settings["allowed_extensions"]}
    maximum_bytes = int(settings.get("maximum_file_size_mb", 500)) * 1024 * 1024
    prefix = str(settings.get("r2_gallery_prefix", "gallery/"))
    index_items = read_index(client, bucket)
    indexed_keys = {item.get("key") for item in index_items if isinstance(item, dict)}
    uploaded = 0
    discovered = 0

    for file_path in list(scan_root.rglob("*")):
        if not file_path.is_file():
            continue
        discovered += 1
        extension = file_path.suffix.lower().lstrip(".")
        try:
            if extension not in allowed:
                log.info("Discarding unwanted extension: %s", file_path.name)
                continue
            size = file_path.stat().st_size
            if size <= 0 or size > maximum_bytes:
                log.info("Discarding file outside size limit: %s (%s bytes)", file_path.name, size)
                continue

            relative = file_path.relative_to(scan_root).as_posix()
            key = object_key(prefix, file_path, relative)
            if key in indexed_keys:
                log.info("Already present in R2 index; skipping: %s", file_path.name)
                continue

            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            client.upload_file(
                str(file_path),
                bucket,
                key,
                ExtraArgs={"ContentType": content_type, "CacheControl": "public, max-age=31536000, immutable"},
            )
            index_items.append({"key": key, "ext": extension, "size": size})
            indexed_keys.add(key)
            uploaded += 1
            log.info("Uploaded %s -> r2://%s/%s", file_path.name, bucket, key)
        finally:
            # Keep GitHub's small temporary disk from filling between source scans.
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                log.warning("Could not remove temporary file: %s", file_path)

    if uploaded:
        write_index(client, bucket, index_items)
        log.info("Updated %s with %s total media items", INDEX_KEY, len(index_items))
    else:
        log.info("No new media files needed uploading in this batch")
    return uploaded, discovered


def scan_once(settings: dict[str, Any], client, bucket: str) -> None:
    total_uploaded = 0
    total_discovered = 0
    clean_successes = 0

    with tempfile.TemporaryDirectory(prefix="gooning-party-") as tmp:
        scan_root = Path(tmp)
        for number, source in enumerate(settings["sources"], start=1):
            source_root = scan_root / f"source-{number}"
            source_root.mkdir(parents=True, exist_ok=True)

            return_code = run_gallery_dl(str(source), source_root, settings)
            uploaded, discovered = upload_downloads(settings, source_root, client, bucket)
            total_uploaded += uploaded
            total_discovered += discovered
            if return_code == 0:
                clean_successes += 1

            # Persist history only after this source's downloaded files were safely handled.
            save_archive(client, bucket)

            if return_code != 0 and discovered == 0:
                log.warning("Source produced no usable downloaded files: %s", source)

    if clean_successes == 0 and total_discovered == 0:
        raise RuntimeError("All configured source scans failed before downloading any files")

    log.info(
        "Scan complete: %s downloaded file(s) examined and %s new file(s) uploaded",
        total_discovered,
        total_uploaded,
    )

def main() -> int:
    log.info("Starting Gooning Party Fresh v%s in one-run GitHub Actions mode", APP_VERSION)
    settings = load_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = r2_client()
    bucket = required_env("R2_BUCKET_NAME")
    restore_archive(client, bucket)
    build_gallery_dl_config(settings)

    exit_code = 0
    try:
        scan_once(settings, client, bucket)
    except Exception:
        log.exception("Scan failed")
        exit_code = 1
    finally:
        try:
            save_archive(client, bucket)
        except Exception:
            log.exception("Could not save download history to R2")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
