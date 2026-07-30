# GParty

GParty is a self-contained media collector, Cloudflare R2 library, random browser viewer, and Windows duplicate-review tool.

The browser viewer validates random-item API responses and automatically retries transient, timed-out, empty, or malformed responses without replacing the currently displayed media.

## Architecture

```text
Reddit sources
      |
      v
GitHub Actions: Yoink
      |
      +--> gallery/<media objects>
      +--> gallery-index.json
      +--> _internal/gallery-dl-archive-v0.2.1.sqlite3
                 |
                 v
          Cloudflare R2
            /        \
           v          v
 Worker random viewer  Windows GParty Deduper
```

The shared storage contract is:

| Purpose | Value |
|---|---|
| Media prefix | `gallery/` |
| Gallery index | `gallery-index.json` |
| Worker R2 binding | `MEDIA_BUCKET` |
| Bucket selector | `R2_BUCKET_NAME` |

## Repository layout

| Path | Purpose |
|---|---|
| `app.py` | Collector, download history, R2 upload, and index generation |
| `settings.json` | Collector limits, delays, formats, and fallback sources |
| `worker/worker.js` | Cloudflare Worker routes and R2 media streaming |
| `worker/app.js` | Browser viewer behavior |
| `worker/style.css` | Browser viewer styling |
| `worker/wrangler.jsonc` | Local Wrangler entrypoint, asset rules, limits, and bucket binding |
| `worker/repair_index.py` | Adds unindexed R2 media to the gallery index |
| `worker/audit_index.py` | Read-only aggregate integrity audit for the live index and bucket |
| `deduper/` | Windows R2 scanner, matcher, review interface, and tests |
| `.github/workflows/yoink.yml` | Scheduled and manual collector |
| `.github/workflows/flush.yml` | Manual index repair |
| `.github/workflows/audit-index.yml` | Manual read-only R2 index audit |
| `.github/workflows/update-cf-web.yml` | Manual Worker deployment |
| `.github/workflows/build-deduper.yml` | Tested Windows ZIP build and rolling release |
| `requirements.txt` | Collector and repair dependencies |

## Collector requirements

- Cloudflare R2 bucket and API credentials
- Cloudflare Worker and deployment token
- GitHub Actions
- A Tailscale exit node available to GitHub Actions
- Reddit cookies in Netscape `cookies.txt` format

## GitHub Actions secrets

Collector, Flush, and R2:

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
```

Yoink routing and Reddit:

```text
TS_OAUTH_CLIENT_ID
TS_OAUTH_SECRET
TS_EXIT_NODE_IP
REDDIT_COOKIES_BASE64
REDDIT_SOURCE_1
REDDIT_SOURCE_2
REDDIT_SOURCE_3
REDDIT_SOURCE_4
```

Each `REDDIT_SOURCE_*` value may be a subreddit name or a complete Reddit `/new/` URL. These runtime overrides keep the real source list out of the committed `settings.json`.

Worker deployment:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_WORKER_NAME
R2_BUCKET_NAME
```

The Worker also requires its runtime `CONTACT_EMAIL` secret.

## Collector configuration

`settings.json` contains:

```json
{
  "sources": [
    "placeholder1",
    "placeholder2",
    "placeholder3"
  ],
  "browser_user_agent": "Mozilla/5.0 ...",
  "posts_per_subreddit_per_scan": 100,
  "reddit_request_delay_min_seconds": 2,
  "reddit_request_delay_max_seconds": 4,
  "stop_after_consecutive_archived_posts": 15,
  "reddit_429_backoff_seconds": 60,
  "allowed_extensions": ["jpg", "jpeg", "png", "gif", "webp", "mp4", "m4v", "webm"],
  "r2_gallery_prefix": "gallery/",
  "maximum_file_size_mb": 500,
  "download_retries": 4,
  "download_timeout_seconds": 45
}
```

The private `REDDIT_SOURCE_*` secrets replace the placeholder entries before `app.py` runs. Keep `r2_gallery_prefix` aligned with the Worker, Flush, and deduper configuration.

## Collector operation

Run **Actions → Yoink → Run workflow**, or allow its schedule to run:

```text
3,18,33,48 * * * *
```

Yoink restores the archive database, selects the configured private exit node, downloads new media, restores the direct GitHub route, uploads media to R2, conditionally merges additions into `gallery-index.json`, and saves the archive.

Run **Actions → Flush → Run workflow** after an interrupted upload may have placed media into R2 without updating the index. Flush adds missing valid objects to `gallery-index.json`; it never deletes media. Yoink, Flush, and the desktop deduper all use the same ETag-protected read/merge/write helper, so a concurrent writer must retry against the newest index instead of overwriting another writer's additions or removals.

Run **Actions → Audit Index → Run workflow** to compare the live index with R2 without modifying either one. It reports aggregate counts for duplicate keys, malformed metadata, incorrect random weighting, missing objects, and unindexed objects. It never prints media filenames or credentials, and the run turns red when it finds an integrity problem.

Run **Actions → update-cf-web → Run workflow** to publish Worker source changes. Repository commits do not automatically deploy the live Worker.

## Windows GParty Deduper

The deduper works directly against R2. It temporarily downloads one object at a time for hashing and previews, but it never keeps a second permanent copy of the media library.

It records these fingerprints in a local SQLite database:

- SHA-256 for byte-identical files
- pHash for visually similar stills and representative video frames
- crop-resistant segmented hashes for crops, borders, and reframing
- Meta PDQ hashes for robust still-image comparison
- vPDQ-style sampled PDQ frame sets for GIF and video comparison

Crop-resistant hashes have their own indexed candidate search, so they can find a cropped duplicate even when the whole-image pHash is too different. Animated GIF frames are sampled across the complete animation with ceiling division; the configured `MAX_VIDEO_FRAMES` value is used as the ceiling and is not hard-coded to 300.

### Download the Windows ZIP

Download [the latest Windows ZIP](https://github.com/polskiftw/gparty/releases/download/windows-latest/GParty-Deduper-Windows.zip), then extract it into a normal folder.

The workflow runs the test suite and builds the portable application on a real Windows runner with PyInstaller. It runs automatically when deduper code or its build workflow changes on `main`, replaces the rolling release ZIP after a successful build, and retains the normal workflow artifact for 30 days. A newer run cancels an older build, and stale commits cannot replace the latest release.

### Configure the deduper

Copy `config.example.txt` to `config.txt` beside `GParty Deduper.exe`:

```text
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=

GALLERY_PREFIX=gallery/
INDEX_KEY=gallery-index.json
ALLOW_DELETE=NO
VIDEO_SAMPLE_SECONDS=1
MAX_VIDEO_FRAMES=300
PREVIEW_CACHE_MB=750
```

Use an R2 token with object read/list access while testing. NUKE remains locked until the token has delete/write access and `ALLOW_DELETE=YES`.

`config.txt`, the SQLite database, and preview cache are ignored by Git. The program stores them beside the EXE under `data/`.

### Deduper workflow

The app keeps the complete workflow on one screen:

1. Set the 100-position slider. Left is looser; right is stricter.
2. **SCAN** lists R2, hashes new or changed objects, finds duplicate groups, and queues every deletion candidate.
3. Review the automatically selected survivor on the left and deletion candidate on the right.
4. Use **PREVIOUS** and **NEXT**, or the keyboard Left and Right arrow keys, to move through every pair.
5. Press **EXCLUDE FROM THIS NUKE** to spare the current right-side candidate and immediately advance to the next pair.
6. **NUKE** immediately deletes every non-excluded right-side candidate and removes its key from `gallery-index.json`.

Pairs are displayed from the least likely accepted match to the most likely match. There are no confirmation dialogs. Exclusions apply only to the current scan; pressing SCAN again makes every detected duplicate eligible again. Each right-side deletion candidate must directly match its left-side survivor. Connected match chains can therefore be split into multiple safe groups instead of treating an indirect chain member as a duplicate. Survivors are preferred by resolution, duration, perceptual-hash quality, and file size, in that order. If index cleanup fails after an object deletion, the app saves that cleanup locally and retries it the next time NUKE runs.

## Local deduper development

Python 3.12:

```text
python -m venv .venv
.venv\Scripts\activate
pip install -r deduper\requirements-build.txt
python -m unittest discover -s deduper\tests -v
python -m deduper.main
```

Build locally on Windows:

```text
cd deduper
pyinstaller --clean --noconfirm GPartyDeduper.spec
```

## Built with

- [gallery-dl](https://github.com/mikf/gallery-dl)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [Boto3](https://github.com/boto/boto3)
- [ImageHash](https://github.com/JohannesBuchner/imagehash)
- [PDQ Hash Python](https://github.com/faustomorales/pdqhash-python), based on Meta PDQ
- [OpenCV](https://opencv.org/)
- [Pillow](https://python-pillow.org/)
- [PyInstaller](https://pyinstaller.org/)

## License

GParty is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). Commercial use requires prior written permission from the copyright holder.

Copyright © 2026 polskiftw.
