# GParty — DGD Guide

GParty collects media into Cloudflare R2, serves it through a Cloudflare Worker, and includes a Windows program for reviewing and deleting duplicate media.

This guide covers the whole project from setup through routine use.

# 1. What each part does

```text
Reddit
  |
  v
Yoink GitHub Action
  |
  v
app.py
  |
  +--> R2 gallery/ media
  +--> R2 gallery-index.json
  +--> R2 download-history database
                |
                +--> Cloudflare Worker viewer
                |
                +--> Windows GParty Deduper
```

The programs agree on these names:

| Thing | Exact name |
|---|---|
| Media folder inside R2 | `gallery/` |
| Media list inside R2 | `gallery-index.json` |
| Download history inside R2 | `_internal/gallery-dl-archive-v0.2.1.sqlite3` |
| Worker bucket binding | `MEDIA_BUCKET` |
| Bucket-name secret | `R2_BUCKET_NAME` |

# 2. Files in the repository

| File or folder | Job |
|---|---|
| `app.py` | Downloads, uploads, remembers finished posts, and writes the R2 index |
| `settings.json` | Collector settings and harmless source placeholders |
| `requirements.txt` | Packages used by Yoink and Flush |
| `worker/worker.js` | Cloudflare Worker routes and R2 access |
| `worker/app.js` | Viewer buttons, filters, keyboard, and media behavior |
| `worker/style.css` | Viewer appearance |
| `worker/wrangler.jsonc` | Local Wrangler settings and Worker wiring |
| `worker/repair_index.py` | Adds missing R2 objects to the index |
| `deduper/` | Windows deduper code, build recipe, configuration sample, and tests |
| `.github/workflows/yoink.yml` | Collector workflow |
| `.github/workflows/flush.yml` | Index repair workflow |
| `.github/workflows/update-cf-web.yml` | Worker deployment workflow |
| `.github/workflows/build-deduper.yml` | Windows deduper build workflow |
| `README.md` | Standard project documentation |
| `DGD.md` | This complete plain-language documentation |

# 3. Cloudflare things you need

Create or identify:

1. The R2 bucket.
2. An R2 API token that can read and write that bucket.
3. The Cloudflare Worker.
4. A Cloudflare API token that can deploy that Worker.

The R2 endpoint has this shape:

```text
https://R2_ACCOUNT_ID.r2.cloudflarestorage.com
```

The account ID is not a password. The R2 access key and secret access key are passwords and must stay out of the repository.

# 4. GitHub Actions secrets

Open:

```text
Repository
→ Settings
→ Secrets and variables
→ Actions
```

Add these R2 secrets:

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
```

Add these Yoink routing secrets:

```text
TS_OAUTH_CLIENT_ID
TS_OAUTH_SECRET
TS_EXIT_NODE_IP
```

Add the Reddit cookie file as one Base64 line:

```text
REDDIT_COOKIES_BASE64
```

Add up to four private source values:

```text
REDDIT_SOURCE_1
REDDIT_SOURCE_2
REDDIT_SOURCE_3
REDDIT_SOURCE_4
```

A source value can be either:

```text
example
```

or:

```text
https://www.reddit.com/r/example/new/
```

Yoink builds a temporary private `settings.json` on the GitHub runner. The real source values are not written into the repository.

Add these Worker-deployment secrets:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_WORKER_NAME
R2_BUCKET_NAME
```

The Worker itself also needs this runtime secret:

```text
CONTACT_EMAIL
```

# 5. Collector settings

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
  "allowed_extensions": [
    "jpg",
    "jpeg",
    "png",
    "gif",
    "webp",
    "mp4",
    "m4v",
    "webm"
  ],
  "r2_gallery_prefix": "gallery/",
  "maximum_file_size_mb": 500,
  "download_retries": 4,
  "download_timeout_seconds": 45
}
```

The private `REDDIT_SOURCE_*` secrets replace the placeholders during Yoink. Keep the R2 prefix as `gallery/`.

# 6. Yoink

File:

```text
.github/workflows/yoink.yml
```

It runs at:

```text
3,18,33,48 * * * *
```

That means four scheduled attempts per hour, at minutes 3, 18, 33, and 48. GitHub can start scheduled jobs late.

Run it yourself with:

```text
GitHub repository
→ Actions
→ Yoink
→ Run workflow
```

Yoink does this:

1. Checks out the repository.
2. Inserts the private source secrets into temporary settings.
3. Installs Python, FFmpeg, and the collector packages.
4. Records and masks the GitHub runner IP.
5. Restores the small R2 download-history database.
6. Connects to Tailscale and selects the private exit node.
7. Confirms the public route changed.
8. Downloads new media.
9. Stops using the exit node.
10. Confirms GitHub's direct route returned.
11. Uploads media to R2.
12. Writes the gallery index and saves download history.

`app.py` supports these internal modes:

| Mode | Job |
|---|---|
| `restore` | Downloads the saved history database |
| `download` | Downloads new media |
| `upload` | Uploads media, index, and history |
| `full` | Runs all three phases in one local process |

# 7. Gallery index

The exact R2 key is:

```text
gallery-index.json
```

Its shape is:

```json
{
  "version": 1,
  "generated_at": 1234567890,
  "count": 1,
  "items": [
    {
      "key": "gallery/example-file.jpg",
      "ext": "jpg",
      "size": 123456
    }
  ]
}
```

The collector writes this file. The Worker reads it. The deduper removes deleted keys from it.

# 8. Flush

Run:

```text
GitHub repository
→ Actions
→ Flush
→ Run workflow
```

Use Flush if an interrupted Yoink uploaded media but failed before updating `gallery-index.json`.

Flush:

1. Lists valid files under `gallery/`.
2. Reads `gallery-index.json`.
3. Adds missing valid files.
4. Writes the repaired index only when needed.

Flush does not delete media.

# 9. Worker

The Worker routes are:

| Route | Job |
|---|---|
| `/` | Loads the viewer |
| `/api/random` | Picks a random indexed item using the selected filter |
| `/media/<encoded-key>` | Streams one indexed R2 object, including video range requests |

The Worker reads `gallery-index.json` through `env.MEDIA_BUCKET`. It only accepts indexed keys beginning with `gallery/`.

The Worker's in-memory index cache lasts 60 seconds. A corrected index may therefore take up to one minute to appear in the viewer.

# 10. Publish Worker changes

Run:

```text
GitHub repository
→ Actions
→ update-cf-web
→ Run workflow
```

The workflow deploys the existing Worker named by `CLOUDFLARE_WORKER_NAME`. It creates a temporary Wrangler configuration using:

```toml
main = "worker/worker.js"

[[r2_buckets]]
binding = "MEDIA_BUCKET"
bucket_name = "<R2_BUCKET_NAME>"
```

Committing Worker code does not update the live site. The manual deployment workflow does.

# 11. Build the Windows deduper

Run:

```text
GitHub repository
→ Actions
→ Build GParty Deduper
→ Run workflow
```

Wait for the green check. Then:

1. Open that completed workflow run.
2. Find **Artifacts**.
3. Download `GParty-Deduper-Windows`.
4. Open the downloaded artifact.
5. Extract `GParty-Deduper-Windows.zip` into a normal folder on the PC.

The build workflow:

1. Uses a Windows GitHub runner.
2. Installs Python 3.12 and the deduper packages.
3. Runs the deduper tests.
4. Builds `GParty Deduper.exe` with PyInstaller.
5. Adds the example configuration and license.
6. Uploads the finished portable ZIP for 30 days.

It also runs automatically when deduper code or the deduper build workflow changes on `main`.

# 12. Configure the Windows deduper

Inside the extracted program folder:

1. Copy `config.example.txt`.
2. Rename the copy to `config.txt`.
3. Open `config.txt` in Notepad.
4. Fill in the four R2 values.

The file looks like:

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

The four R2 values are the same kind of values stored in the GitHub secrets. Do not commit `config.txt`.

`ALLOW_DELETE=NO` locks NUKE. This lets the program scan and compare safely while it is being tested.

When ready to permit real deletions:

```text
ALLOW_DELETE=YES
```

Then close and reopen the app. The R2 token also needs object-delete access. NUKE does not show another confirmation box.

# 13. What SCAN does

Press:

```text
SCAN
```

The first scan:

1. Lists supported objects under `gallery/`.
2. Downloads one object to a temporary file.
3. Calculates its hashes.
4. Saves only the key, size, type, hashes, and scan information in local SQLite.
5. Deletes the temporary media file.
6. Repeats for the next object.

The first full scan is the long one. Later scans use the R2 key, ETag, size, and modified time to hash only new or changed objects.

The database lives here:

```text
data/gparty-deduper.sqlite3
```

The application also keeps a size-limited preview cache under:

```text
data/preview-cache/
```

Neither folder is uploaded to R2 or GitHub.

# 14. Hashes used by the deduper

| Hash | Finds |
|---|---|
| SHA-256 | Exactly identical bytes |
| pHash | Stills that look nearly identical |
| Crop-resistant hash | Crops, borders, and reframing |
| Meta PDQ | Strong still-image perceptual matches |
| vPDQ-style frame set | Similar clips, re-encodes, and video subsequences |

For video and animated GIFs, the program samples frames, calculates a Meta PDQ hash for each useful frame, and compares the two sets in both directions. This follows the published vPDQ method while remaining buildable as a normal Windows application.

# 15. ACQUIRE TARGETS

Move the slider before pressing:

```text
ACQUIRE TARGETS
```

The slider has 100 positions:

| Direction | Result |
|---|---|
| Left | Looser; catches more possibilities and more false positives |
| Middle | Balanced starting point |
| Right | Stricter; fewer false positives and more missed duplicates |

The program uses a BK-tree for pHash and PDQ comparisons and banded frame lookup for vPDQ candidates. It does not blindly compare every object with every other object.

Exact SHA-256 duplicates are always targets, even at the strictest slider position.

# 16. Review targets

Each target shows:

- The left media
- The right media
- Each R2 key
- Each file size
- Dimensions
- Video length when available
- Similarity score
- Why the pair matched

The controls are:

| Button | Result |
|---|---|
| `DELETE LEFT` | Queues the left object |
| `SKIP` | Marks this pair reviewed without deleting either object |
| `DELETE RIGHT` | Queues the right object |
| `BACK` | Undoes the most recent review decision |
| `FORWARD` | Shows another pending pair without deciding this one |

The DELETE buttons do not contact R2. They only change the local review queue.

One object can appear in several pairs. Choosing to delete one file does not stop its survivor from being compared with other objects.

The smaller preview underneath is one random live media object. It loops when it is animated. It is not a third duplicate candidate.

# 17. NUKE

NUKE performs the queued R2 deletions.

It:

1. Deletes the queued media objects in R2 batches.
2. Records each success or failure in local SQLite.
3. Marks confirmed deletions locally.
4. Removes confirmed deleted keys from `gallery-index.json`.
5. Reports the number of deleted objects and reclaimed bytes.

If R2 deletes an object but the later index write fails, the deduper remembers those keys in a local cleanup queue. The next NUKE retries the gallery-index cleanup, including when there are no new media deletions.

# 18. Deduper files that stay local

These paths are ignored by Git:

```text
deduper/config.txt
deduper/data/
deduper/build/
deduper/dist/
```

The SQLite database remembers:

- R2 inventory
- Hashes and media details
- Scan failures
- Candidate pairs
- Review decisions
- Deletion queue
- Deletion history and survivors
- Any gallery-index cleanup still needing a retry

# 19. Routine use

Normal cleanup session:

1. Open `GParty Deduper.exe`.
2. Press **SCAN**.
3. Wait for the scan to finish.
4. Set the slider.
5. Press **ACQUIRE TARGETS**.
6. Review targets.
7. Press **NUKE** when ready.
8. Wait up to 60 seconds for the Worker cache to refresh.

The program can be closed between any of these stages. SQLite keeps the work.

# 20. Troubleshooting

## The deduper says config.txt is missing

Copy `config.example.txt`, rename the copy to `config.txt`, fill it in, and keep it beside the EXE.

## The deduper cannot connect to R2

Check:

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
```

Also confirm the R2 token is allowed to list and read the bucket.

## NUKE is locked

Set:

```text
ALLOW_DELETE=YES
```

Restart the app. Confirm the R2 token is also allowed to delete objects and update the index.

## SCAN reports one or more errors

The scan continues after an unreadable object. The error is stored in SQLite. If that object changes in R2, a later scan tries it again.

## The first scan takes a long time

That is expected because every object must be downloaded, decoded, and hashed once. Later scans normally process only new or changed objects.

## A deleted item briefly appears in the viewer

Wait 60 seconds for the Worker index cache. If the app reported an index-cleanup failure, run NUKE again.

## Yoink uploaded media that does not appear in the viewer

Run Flush and wait 60 seconds.

## A Worker code commit is not visible

Run `update-cf-web`. Worker deployment is manual.

# 21. Local development

On Windows with Python 3.12:

```text
python -m venv .venv
.venv\Scripts\activate
pip install -r deduper\requirements-build.txt
python -m unittest discover -s deduper\tests -v
python -m deduper.main
```

Build the EXE:

```text
cd deduper
pyinstaller --clean --noconfirm GPartyDeduper.spec
```

# 22. Wiring checklist

| Producer or setting | Consumer | Must match |
|---|---|---|
| `settings.json`: `r2_gallery_prefix` | Worker, Flush, deduper | `gallery/` |
| `app.py`: index key | Worker, Flush, deduper | `gallery-index.json` |
| Deploy workflow binding | `worker/worker.js` | `MEDIA_BUCKET` |
| GitHub R2 bucket secret | Collector, Flush, deployment | `R2_BUCKET_NAME` |
| Deduper `R2_BUCKET_NAME` | The same R2 library | Same bucket |

# 23. License

GParty uses the PolyForm Noncommercial License 1.0.0. Commercial use requires written permission from the copyright holder.

Copyright © 2026 polskiftw.
