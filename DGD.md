# GParty — DGD Guide

GParty is one repository containing the complete collection and viewing system. GitHub Actions runs the collector, Cloudflare R2 stores the media and state, and a Cloudflare Worker serves the browser viewer.

This guide is self-contained. It covers setup, architecture, operation, deployment, maintenance, and troubleshooting.

# 1. System overview

```text
Configured Reddit sources
          |
          v
.github/workflows/yoink.yml
          |
          v
        app.py
          |
          +---- media --------------------> R2: gallery/
          +---- gallery manifest ---------> R2: gallery-index.json
          +---- download history ---------> R2: _internal/gallery-dl-archive-v0.2.1.sqlite3
                                                   |
                                                   v
                                      workers/worker.js
                                                   |
                                                   v
                                         Browser viewer
```

The collector and Worker communicate through the R2 bucket. They share this storage contract:

| Purpose | Canonical value |
|---|---|
| Media prefix | `gallery/` |
| Gallery index key | `gallery-index.json` |
| Worker binding name | `MEDIA_BUCKET` |
| Bucket secret | `R2_BUCKET_NAME` |

# 2. Repository layout

| Path | Purpose |
|---|---|
| `app.py` | Collector phases, download history, R2 uploads, and index generation |
| `workers/repair_index.py` | Finds valid media objects missing from the gallery index |
| `workers/worker.js` | Cloudflare Worker routes, R2 reads, media streaming, and viewer interface |
| `settings.json` | Collector configuration |
| `.github/workflows/yoink.yml` | Scheduled and manual collector workflow |
| `.github/workflows/flush.yml` | Manual index repair workflow |
| `.github/workflows/update-cloudflare.yml` | Manual Worker deployment workflow |
| `requirements.txt` | Python dependencies installed by GitHub Actions |
| `README.md` | Concise project README |
| `DGD.md` | This complete alternate guide |

Both Worker-related programs now live inside the plural `workers/` directory. They remain separate programs and perform separate jobs.

# 3. Cloudflare resources

Create or identify:

1. One R2 bucket for the project.
2. One Cloudflare Worker for the viewer.
3. An R2 API token for the collector and repair workflow.
4. A Cloudflare API token for Worker deployment.

The collector reaches R2 through:

```text
https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
```

The Worker accesses the same bucket through the `MEDIA_BUCKET` binding.

# 4. GitHub Actions secrets

Open:

```text
Repository
→ Settings
→ Secrets and variables
→ Actions
```

## Collector and Flush

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
```

## Tailscale routing for Yoink

```text
TS_OAUTH_CLIENT_ID
TS_OAUTH_SECRET
TS_EXIT_NODE_IP
```

## Reddit browser session for Yoink

```text
REDDIT_COOKIES_BASE64
```

This value is the complete Netscape-format `cookies.txt` file encoded as one Base64 line.

## Private source overrides

```text
REDDIT_SOURCE_1
REDDIT_SOURCE_2
REDDIT_SOURCE_3
```

Each value may be a subreddit name or a complete Reddit `/new/` URL. The workflow writes a temporary settings file and leaves the committed `settings.json` unchanged.

## Worker deployment

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
R2_BUCKET_NAME
```

`R2_BUCKET_NAME` must name the same bucket used by the collector.

# 5. Collector configuration

The exact keys in `settings.json` are:

```json
{
  "sources": [
    "https://www.reddit.com/r/example1/new/",
    "https://www.reddit.com/r/example2/new/",
    "https://www.reddit.com/r/example3/new/"
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

Keep `r2_gallery_prefix` set to `gallery/` unless the same prefix is changed in the collector, repair script, and Worker.

# 6. Yoink workflow

File:

```text
.github/workflows/yoink.yml
```

Actions display name:

```text
Yoink
```

Current schedule:

```text
3,18,33,48 * * * *
```

Yoink can also be started from **Actions → Yoink → Run workflow**.

The workflow performs these phases:

```text
1. Check out the repository.
2. Build temporary settings with private source overrides.
3. Install Python, FFmpeg, and Python dependencies.
4. Record and mask the GitHub runner public IP.
5. Restore the archive database from R2.
6. Join Tailscale and select the configured exit node.
7. Confirm that the public route changed.
8. Run the download phase.
9. Clear the exit node.
10. Confirm that the direct GitHub route returned.
11. Run the upload phase.
```

The collector uses these `APP_MODE` values:

| Mode | Operation |
|---|---|
| `restore` | Restore the archive database from R2 |
| `download` | Generate downloader configuration and retrieve new media |
| `upload` | Upload media, update the gallery index, and save history |
| `full` | Run restore, download, and upload in one local process |

# 7. Download history

Canonical R2 key:

```text
_internal/gallery-dl-archive-v0.2.1.sqlite3
```

The archive is restored before each collection pass and saved after the upload phase. It records items already processed by gallery-dl.

# 8. R2 gallery index

Canonical key:

```text
gallery-index.json
```

Shape:

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

`app.py` writes this object after media uploads. `workers/worker.js` reads it and accepts entries whose keys begin with `gallery/`.

# 9. Flush workflow

File:

```text
.github/workflows/flush.yml
```

Run it from **Actions → Flush → Run workflow** after an interrupted upload may have placed media objects in R2 before the updated index was written.

Flush runs `workers/repair_index.py`, reads `gallery-index.json`, lists valid media under `gallery/`, and adds missing entries.

# 10. Worker behavior

Entrypoint:

```text
workers/worker.js
```

Routes:

| Route | Operation |
|---|---|
| `/` | Returns the GParty viewer |
| `/api/random` | Selects a random indexed item using the requested filter |
| `/media/<encoded-key>` | Streams an indexed R2 object with range support |

The Worker reads:

```javascript
const INDEX_KEY = "gallery-index.json";
env.MEDIA_BUCKET.get(...)
```

It accepts media keys beginning with:

```text
gallery/
```

The index is cached in Worker memory for 60 seconds. Media responses use private browser caching and byte-range support for video playback.

# 11. Manual Worker deployment

File:

```text
.github/workflows/update-cloudflare.yml
```

Actions display name:

```text
update-cloudflare
```

Run it from **Actions → update-cloudflare → Run workflow** and enter the exact existing Cloudflare Worker name.

The workflow generates a temporary Wrangler configuration:

```toml
name = "<entered Worker name>"
main = "<repository>/workers/worker.js"
compatibility_date = "2026-07-28"

[[r2_buckets]]
binding = "MEDIA_BUCKET"
bucket_name = "<R2_BUCKET_NAME>"
```

The binding chain is:

```text
workers/worker.js: env.MEDIA_BUCKET
              maps to
Wrangler binding: MEDIA_BUCKET
              maps to
Cloudflare bucket: R2_BUCKET_NAME
```

Repository commits update the source only. The live Worker changes after the manual deployment workflow completes successfully.

# 12. Wiring audit

| Connection | Producer/configuration | Consumer | Status |
|---|---|---|---|
| Gallery index | `app.py`: `gallery-index.json` | `workers/worker.js`: `gallery-index.json` | Aligned |
| Media prefix | `settings.json`: `gallery/` | Worker prefix validation: `gallery/` | Aligned |
| Repair prefix | `workers/repair_index.py`: gallery objects | Gallery index and Worker | Shared contract |
| Bucket name | GitHub secret `R2_BUCKET_NAME` | Collector, Flush, deploy workflow | Shared secret |
| Worker binding | Deploy workflow: `MEDIA_BUCKET` | Worker: `env.MEDIA_BUCKET` | Aligned |
| Worker entrypoint | Deploy workflow | `workers/worker.js` | Aligned |
| Deployment trigger | `workflow_dispatch` | Manual Actions run | Manual |

# 13. First deployment procedure

1. Create the R2 bucket.
2. Create the R2 API credentials.
3. Configure all collector secrets.
4. Configure Tailscale OAuth and exit-node secrets.
5. Encode and save the Reddit cookie secret.
6. Configure `settings.json` or the private source overrides.
7. Run Yoink once.
8. Confirm that R2 contains `gallery-index.json`, `gallery/`, and the archive database.
9. Create the Cloudflare Worker.
10. Create the Worker deployment API token.
11. Configure `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
12. Run update-cloudflare with the exact Worker name.
13. Open the Worker URL and confirm that the viewer loads indexed media.

# 14. Routine operation

## Collect new media

Allow the Yoink schedule to run or start Yoink manually.

## Repair a partial index update

Run Flush once.

## Publish Worker code changes

Commit the source changes, then run update-cloudflare manually.

## Change the collection schedule

Edit the cron expression in `.github/workflows/yoink.yml` and commit it.

# 15. Troubleshooting

## Yoink stops during route verification

Confirm that the Tailscale OAuth credentials, device tag, exit-node IP, and exit-node advertisement are correct.

## Yoink cannot restore or upload R2 objects

Confirm `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_BUCKET_NAME`.

## The Worker opens but reports no matching media

Confirm that `gallery-index.json` exists in the bound bucket and contains entries under `items` whose keys begin with `gallery/`.

## The Worker deploys but R2 reads fail

Confirm that the deployment workflow used the correct `R2_BUCKET_NAME` and that the Worker API token can deploy the Worker with the R2 binding.

## Uploaded media is missing from the viewer

Run Flush, then allow up to 60 seconds for the Worker's in-memory index cache to expire.

## A Worker code commit is not visible on the site

Run the update-cloudflare workflow. Deployment is manual.

# 16. Documentation maintenance

`README.md` and `DGD.md` each describe the complete project. Update both whenever a shared path, secret, workflow, binding, setting, route, or deployment step changes.

Documentation describes the canonical current state. Removed implementations and superseded instructions stay out of the permanent guides.
