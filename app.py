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
from boto3.s3.transfer import TransferConfig
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

APP_VERSION = "0.2.8"
BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = Path(os.getenv("SETTINGS_PATH", BASE_DIR / "settings.json"))
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / ".run-data"))
ARCHIVE_PATH = DATA_DIR / "gallery-dl-archive.sqlite3"
CONFIG_PATH = DATA_DIR / "gallery-dl.generated.json"
COOKIES_PATH = DATA_DIR / "reddit-cookies.txt"
INDEX_KEY = os.getenv("R2_INDEX_KEY", "gallery-index.json")
ARCHIVE_R2_KEY = os.getenv("R2_ARCHIVE_KEY", "_internal/gallery-dl-archive-v0.2.1.sqlite3")
DOWNLOAD_ROOT = DATA_DIR / "downloads"
RUN_STATE_PATH = DATA_DIR / "run-state.json"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("gooning-party")



R2_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=16 * 1024 * 1024,
    multipart_chunksize=8 * 1024 * 1024,
    max_concurrency=1,
    use_threads=False,
)


def upload_file_with_retry(
    client,
    *,
    local_path: Path,
    bucket: str,
    key: str,
    extra_args: dict[str, str],
    attempts: int = 6,
) -> None:
    """Upload one file, retrying the entire transfer after tunnel/TLS interruptions."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            client.upload_file(
                str(local_path),
                bucket,
                key,
                ExtraArgs=extra_args,
                Config=R2_TRANSFER_CONFIG,
            )
            return
        except (BotoCoreError, ClientError, OSError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            wait_seconds = min(60, 2 ** attempt)
            log.warning(
                "R2 upload interrupted for %s (attempt %s/%s): %s. Retrying in %ss...",
                local_path.name,
                attempt,
                attempts,
                exc,
                wait_seconds,
            )
            time.sleep(wait_seconds)
    assert last_error is not None
    raise last_error

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
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 8, "mode": "adaptive"},
            connect_timeout=30,
            read_timeout=120,
            tcp_keepalive=True,
        ),
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
    upload_file_with_retry(
        client,
        local_path=ARCHIVE_PATH,
        bucket=bucket,
        key=ARCHIVE_R2_KEY,
        extra_args={"ContentType": "application/x-sqlite3", "CacheControl": "no-store"},
    )
    log.info("Saved download history to R2 for the next GitHub Actions run")


def build_gallery_dl_config(settings: dict[str, Any]) -> None:
    write_reddit_cookies()
    config = {
        "extractor": {
            "base-directory": "/tmp/gooning-party-downloads",
            # Never use full Reddit titles as local filenames. Linux limits one
            # filename component to 255 bytes, and some post titles exceed that.
            # Keep gallery-dl's own generated base filename, but truncate it to
            # 120 bytes before touching the filesystem. This avoids Linux
            # Errno 36 without using unsupported fallback-format syntax.
            "filename": "{filename[b:120]}.{extension}",
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


def upload_downloads(settings: dict[str, Any], scan_root: Path, client, bucket: str) -> tuple[int, int, int]:
    allowed = {str(ext).lower().lstrip(".") for ext in settings["allowed_extensions"]}
    maximum_bytes = int(settings.get("maximum_file_size_mb", 500)) * 1024 * 1024
    prefix = str(settings.get("r2_gallery_prefix", "gallery/"))
    index_items = read_index(client, bucket)
    indexed_keys = {item.get("key") for item in index_items if isinstance(item, dict)}
    uploaded = 0
    discovered = 0
    failed_uploads = 0

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
            try:
                upload_file_with_retry(
                    client,
                    local_path=file_path,
                    bucket=bucket,
                    key=key,
                    extra_args={
                        "ContentType": content_type,
                        "CacheControl": "public, max-age=31536000, immutable",
                    },
                )
            except Exception:
                failed_uploads += 1
                log.exception(
                    "Could not upload %s after all retries. The scan will continue, "
                    "and this source's history will be rolled back so it can retry next run.",
                    file_path.name,
                )
                continue

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
    return uploaded, discovered, failed_uploads


def reset_download_area() -> None:
    if DOWNLOAD_ROOT.exists():
        for path in sorted(DOWNLOAD_ROOT.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    RUN_STATE_PATH.unlink(missing_ok=True)


def download_all_sources(settings: dict[str, Any]) -> None:
    """Download every configured source while the workflow is on the home exit node."""
    reset_download_area()
    source_states: list[dict[str, Any]] = []
    total_discovered = 0
    any_scan_completed = False

    for number, source in enumerate(settings["sources"], start=1):
        source_root = DOWNLOAD_ROOT / f"source-{number}"
        source_root.mkdir(parents=True, exist_ok=True)

        checkpoint = DATA_DIR / f"archive-before-source-{number}.sqlite3"
        if ARCHIVE_PATH.exists():
            checkpoint.write_bytes(ARCHIVE_PATH.read_bytes())
        else:
            checkpoint.unlink(missing_ok=True)

        return_code = run_gallery_dl(str(source), source_root, settings)
        discovered = sum(1 for path in source_root.rglob("*") if path.is_file())
        total_discovered += discovered
        if return_code == 0:
            any_scan_completed = True

        source_states.append(
            {
                "number": number,
                "source": str(source),
                "return_code": return_code,
                "discovered": discovered,
                "source_dir": str(source_root),
                "checkpoint": str(checkpoint),
            }
        )

        if return_code != 0 and discovered == 0:
            log.warning("Source produced no downloaded files: %s", source)

    RUN_STATE_PATH.write_text(
        json.dumps(
            {
                "version": 1,
                "created_at": int(time.time()),
                "sources": source_states,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if not any_scan_completed and total_discovered == 0:
        raise RuntimeError("All configured source scans failed before downloading any files")

    log.info(
        "Download phase complete: %s file(s) saved locally. No R2 media uploads were attempted through the exit node.",
        total_discovered,
    )


def upload_all_sources(settings: dict[str, Any], client, bucket: str) -> None:
    """Upload all previously downloaded files after the workflow leaves the exit node."""
    if not RUN_STATE_PATH.exists():
        raise RuntimeError("Missing run-state.json. The download phase did not complete correctly.")

    state = json.loads(RUN_STATE_PATH.read_text(encoding="utf-8"))
    source_states = state.get("sources")
    if not isinstance(source_states, list):
        raise RuntimeError("run-state.json is invalid")

    total_uploaded = 0
    total_discovered = 0
    total_failed = 0
    earliest_failed_checkpoint: Path | None = None
    earliest_failed_number: int | None = None

    for item in source_states:
        source_root = Path(str(item["source_dir"]))
        checkpoint = Path(str(item["checkpoint"]))
        uploaded, discovered, failed_uploads = upload_downloads(
            settings, source_root, client, bucket
        )
        total_uploaded += uploaded
        total_discovered += discovered
        total_failed += failed_uploads

        if failed_uploads:
            number = int(item.get("number", 0))
            if earliest_failed_number is None or number < earliest_failed_number:
                earliest_failed_number = number
                earliest_failed_checkpoint = checkpoint
            log.warning(
                "%s upload(s) failed for source %s. The final history will be rolled back far enough to retry every uncertain file next run.",
                failed_uploads,
                item.get("source", "<unknown>"),
            )

    # A gallery-dl archive is cumulative. If any source upload failed, restore the
    # checkpoint from before the earliest failed source. This may redownload some
    # later successful files next time, but the R2 index prevents duplicate uploads.
    if earliest_failed_number is not None:
        if earliest_failed_checkpoint is not None and earliest_failed_checkpoint.exists():
            ARCHIVE_PATH.write_bytes(earliest_failed_checkpoint.read_bytes())
        else:
            ARCHIVE_PATH.unlink(missing_ok=True)
        log.warning(
            "Rolled download history back to before source %s so failed media cannot be forgotten.",
            earliest_failed_number,
        )

    save_archive(client, bucket)

    for item in source_states:
        Path(str(item["checkpoint"])).unlink(missing_ok=True)
    RUN_STATE_PATH.unlink(missing_ok=True)

    log.info(
        "Direct R2 upload phase complete: %s downloaded file(s) examined, %s uploaded, %s failed.",
        total_discovered,
        total_uploaded,
        total_failed,
    )


def main() -> int:
    mode = os.getenv("APP_MODE", "full").strip().lower()
    log.info("Starting Gooning Party Fresh v%s in %s mode", APP_VERSION, mode)
    settings = load_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if mode == "restore":
            client = r2_client()
            bucket = required_env("R2_BUCKET_NAME")
            restore_archive(client, bucket)
            return 0

        if mode == "download":
            build_gallery_dl_config(settings)
            download_all_sources(settings)
            return 0

        if mode == "upload":
            client = r2_client()
            bucket = required_env("R2_BUCKET_NAME")
            upload_all_sources(settings, client, bucket)
            return 0

        if mode == "full":
            # Local/manual fallback. GitHub Actions should use the three explicit phases.
            client = r2_client()
            bucket = required_env("R2_BUCKET_NAME")
            restore_archive(client, bucket)
            build_gallery_dl_config(settings)
            download_all_sources(settings)
            upload_all_sources(settings, client, bucket)
            return 0

        raise RuntimeError(f"Unknown APP_MODE: {mode}")
    except Exception:
        log.exception("%s phase failed", mode.capitalize())
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
