# GParty

GParty is a self-contained media collection and viewing project built on GitHub Actions, Cloudflare R2, and Cloudflare Workers.

The repository contains both parts of the system:

- A Python collector that retrieves new media from configured Reddit sources and stores it in R2.
- A Cloudflare Worker that reads the R2 gallery index and serves the browser viewer.

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
                 |
                 v
      Cloudflare Worker viewer
```

The collector and Worker share two storage conventions:

- Media objects are stored under `gallery/`.
- The gallery manifest is stored as `gallery-index.json`.

## Repository layout

| Path | Purpose |
|---|---|
| `app.py` | Collector, download history, R2 uploads, and index generation |
| `repair_index.py` | Repairs index entries for media already present in R2 |
| `settings.json` | Collector sources, limits, delays, extensions, and R2 prefix |
| `worker/worker.js` | Cloudflare Worker and browser viewer |
| `.github/workflows/yoink.yml` | Scheduled and manual collection workflow |
| `.github/workflows/flush.yml` | Manual R2 index repair workflow |
| `.github/workflows/deploy-worker.yml` | Manual Cloudflare Worker deployment workflow |
| `requirements.txt` | Python dependencies |
| `DGD.md` | Complete alternate setup and maintenance guide |

## Requirements

- A Cloudflare account with an R2 bucket and a Worker
- A GitHub repository with Actions enabled
- A Tailscale exit node reachable by GitHub Actions
- Reddit browser cookies in Netscape `cookies.txt` format

## GitHub Actions secrets

### Collector and repair workflows

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
TS_OAUTH_CLIENT_ID
TS_OAUTH_SECRET
TS_EXIT_NODE_IP
REDDIT_COOKIES_BASE64
```

The first three configured sources can be privately replaced at runtime with:

```text
REDDIT_SOURCE_1
REDDIT_SOURCE_2
REDDIT_SOURCE_3
```

Each source override accepts either a subreddit name or a complete Reddit `/new/` URL.

### Worker deployment

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
R2_BUCKET_NAME
```

`R2_BUCKET_NAME` is shared by the collector and Worker deployment. The deployment workflow binds that bucket to the Worker as `MEDIA_BUCKET`, matching `env.MEDIA_BUCKET` in `worker/worker.js`.

## Configure the collector

Edit `settings.json`.

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
  "allowed_extensions": ["jpg", "jpeg", "png", "gif", "webp", "mp4", "m4v", "webm"],
  "r2_gallery_prefix": "gallery/",
  "maximum_file_size_mb": 500,
  "download_retries": 4,
  "download_timeout_seconds": 45
}
```

Keep `r2_gallery_prefix` set to `gallery/` unless the same prefix is also changed in the Worker and repair logic.

## Run the collector

Open **Actions → Yoink → Run workflow**.

Yoink restores the download archive, connects through the configured Tailscale exit node, downloads new media, restores the direct GitHub route, uploads media to R2, updates `gallery-index.json`, and saves the archive database.

The workflow also runs on this schedule:

```text
3,18,33,48 * * * *
```

## Repair the gallery index

Open **Actions → Flush → Run workflow** after an interrupted upload phase may have placed media in R2 before the index was updated.

Flush scans valid objects under `gallery/` and adds missing entries to `gallery-index.json`.

## Deploy the Worker

1. Create the Worker in Cloudflare or identify the existing Worker name.
2. Add the Worker deployment secrets listed above.
3. Open **Actions → Deploy Worker → Run workflow**.
4. Enter the exact existing Worker name.

The workflow creates a temporary Wrangler configuration with:

```toml
main = "worker/worker.js"

[[r2_buckets]]
binding = "MEDIA_BUCKET"
bucket_name = "<R2_BUCKET_NAME>"
```

Deployment is manual. Repository commits do not automatically deploy the Worker.

## Shared storage contract

The current wiring is:

| Component | Value |
|---|---|
| Collector index key | `gallery-index.json` |
| Worker index key | `gallery-index.json` |
| Collector media prefix | `gallery/` |
| Worker accepted media prefix | `gallery/` |
| Worker code binding | `MEDIA_BUCKET` |
| Deployment binding | `MEDIA_BUCKET` |
| Bucket selector | `R2_BUCKET_NAME` |

These values must remain aligned.

## License

GParty is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). Commercial use requires prior written permission from the copyright holder.

Copyright © 2026 polskiftw.