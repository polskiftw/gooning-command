# GParty — DGD Guide

This is the canonical guide for the GitHub collector side of the project.

Do not combine these instructions with older versions. This file describes the repository as it works now.

# 1. What this repository is

This repository is the backend collector.

It:

1. Checks configured Reddit sources.
2. Downloads supported new media.
3. Uploads that media to Cloudflare R2.
4. Updates `gallery-index.json` and the download-history database.

It is not the public website. The separate Cloudflare Worker controls the viewer and serves files from R2.

```text
Getting content into R2 = GitHub repository
Showing content from R2 = Cloudflare Worker
```

# 2. GitHub Actions workflows

There are two workflow files.

## Yoink

File:

```text
.github/workflows/yoink.yaml
```

Display name in the Actions tab:

```text
Yoink
```

Yoink is the normal collector workflow. It runs on the configured schedule and can also be started manually.

Current schedule:

```text
3,18,33,48 * * * *
```

That requests runs at approximately `:03`, `:18`, `:33`, and `:48` of every hour. GitHub may start scheduled runs late.

Yoink does this:

```text
1. Start an Ubuntu GitHub runner.
2. Check out the repository.
3. Apply optional private subreddit overrides.
4. Install Python, FFmpeg, and required packages.
5. Record and mask the GitHub runner public IP.
6. Restore the prior gallery-dl archive database from R2.
7. Join Tailscale.
8. Route Reddit and media downloads through the configured home exit node.
9. Download supported new media.
10. Stop using the home exit node.
11. Confirm GitHub's direct route returned.
12. Upload media directly to R2.
13. Update gallery-index.json.
14. Save the updated download-history database to R2.
```

The workflow refuses to contact Reddit if the home route cannot be confirmed. It also refuses to upload to R2 if GitHub's direct route does not return.

Its concurrency setting is:

```yaml
concurrency:
  group: gooning-party-cat-download
  cancel-in-progress: false
```

A new run waits rather than cancelling an active Yoink run.

## Flush

File:

```text
.github/workflows/flush.yaml
```

Display name in the Actions tab:

```text
Flush
```

Flush is manual-only. It has no schedule.

Run Flush when a failed or cancelled Yoink run may have uploaded media objects to R2 before `gallery-index.json` was written.

Flush:

- Connects directly to R2.
- Lists valid media objects under `gallery/`.
- Reads the current `gallery-index.json`.
- Adds valid R2 objects missing from the index.
- Leaves existing index entries alone.
- Deletes nothing.

Flush does not:

- Contact Reddit.
- Use Tailscale.
- Use the home IP.
- Download media again.
- Delete R2 objects.
- Remove existing index entries.

To run it:

```text
Repository
→ Actions
→ Flush
→ Run workflow
```

Use it after a suspicious upload-phase cancellation or failure. It is not needed after every normal run.

# 3. Important repository files

## `app.py`

Main collector program. It handles settings, cookies, gallery-dl, history, download and upload phases, R2 uploads, index updates, retries, and rollback behavior.

## `repair_index.py`

Used by Flush. It rebuilds missing `gallery-index.json` entries from media objects already stored in R2.

## `settings.json`

Contains ordinary collector settings and limits.

## `.github/workflows/yoink.yaml`

Scheduled and manual collector workflow.

## `.github/workflows/flush.yaml`

Manual-only R2 index repair workflow.

## `requirements.txt`

Python packages installed by GitHub Actions.

## `README.md`

Short GitHub front-page description.

## `DGD.md`

This file. It is the canonical detailed guide.

# 4. Current settings

The exact setting names matter.

## `sources`

Lists Reddit `/new/` sources in scan order. The first three can be replaced privately during a run with GitHub Secrets.

## `browser_user_agent`

One complete browser User-Agent string on one line.

## `posts_per_subreddit_per_scan`

Current value:

```json
"posts_per_subreddit_per_scan": 100
```

Maximum newest posts gallery-dl may examine per source in one run.

## `reddit_request_delay_min_seconds`

Current value:

```json
"reddit_request_delay_min_seconds": 2
```

## `reddit_request_delay_max_seconds`

Current value:

```json
"reddit_request_delay_max_seconds": 4
```

Together these create a random request delay of 2 to 4 seconds.

## `stop_after_consecutive_archived_posts`

Current value:

```json
"stop_after_consecutive_archived_posts": 15
```

Stops a source after 15 consecutive already-archived posts.

## `reddit_429_backoff_seconds`

Current value:

```json
"reddit_429_backoff_seconds": 60
```

Pause used after Reddit returns HTTP 429.

## `allowed_extensions`

Current supported set:

```json
[
  "jpg",
  "jpeg",
  "png",
  "gif",
  "webp",
  "mp4",
  "m4v",
  "webm"
]
```

## `r2_gallery_prefix`

Current value:

```json
"r2_gallery_prefix": "gallery/"
```

## `maximum_file_size_mb`

Current value:

```json
"maximum_file_size_mb": 500
```

## `download_retries`

Current value:

```json
"download_retries": 4
```

## `download_timeout_seconds`

Current value:

```json
"download_timeout_seconds": 45
```

# 5. Required GitHub Secrets

Open:

```text
Repository
→ Settings
→ Secrets and variables
→ Actions
```

Required R2 secrets:

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
```

Required Tailscale secrets for Yoink:

```text
TS_OAUTH_CLIENT_ID
TS_OAUTH_SECRET
TS_EXIT_NODE_IP
```

Required Reddit cookie secret for Yoink:

```text
REDDIT_COOKIES_BASE64
```

Optional private source secrets:

```text
REDDIT_SOURCE_1
REDDIT_SOURCE_2
REDDIT_SOURCE_3
```

Each optional source secret may contain either a subreddit name or a complete Reddit `/new/` URL.

# 6. Restore, download, and upload modes

`app.py` supports these `APP_MODE` values.

## `restore`

Downloads the prior gallery-dl archive database from R2.

## `download`

Runs while the home exit node is active. It prepares cookies and configuration, scans all sources, downloads media to temporary storage, and writes `run-state.json`.

## `upload`

Runs after the direct GitHub route returns. It uploads media, updates `gallery-index.json`, saves history, and rolls history back when uploads fail.

## `full`

Local/manual fallback that performs restore, download, and upload in one process. GitHub Actions should continue using the separate phases.

# 7. Download history and duplicate prevention

Current R2 history key:

```text
_internal/gallery-dl-archive-v0.2.1.sqlite3
```

The archive records media already processed by gallery-dl.

It is restored before downloading and saved after uploading. If an upload fails, the archive is rolled back far enough to retry uncertain media next time.

The R2 gallery index also prevents re-uploading an object key already present in the index.

This is download-history and object-key duplicate prevention. It is not perceptual image deduplication.

# 8. R2 gallery index

Current index key:

```text
gallery-index.json
```

General shape:

```json
{
  "version": 1,
  "generated_at": 1234567890,
  "count": 123,
  "items": [
    {
      "key": "gallery/example-file.jpg",
      "ext": "jpg",
      "size": 123456
    }
  ]
}
```

The Cloudflare Worker reads this file to know which R2 objects it may show.

A cancellation after media uploads but before this file is updated can leave valid R2 objects missing from the website. Flush repairs that specific condition.

# 9. What belongs in GitHub versus Cloudflare

Change this repository when it affects:

- Reddit sources.
- Scan limits and delays.
- Cookies or User-Agent handling.
- Download hosts or retries.
- Allowed extensions or file limits.
- R2 uploads, keys, or index generation.
- Yoink or Flush behavior.
- GitHub Actions scheduling.
- Tailscale routing.
- GitHub Secrets.

Change the Cloudflare Worker when it affects:

- Website layout or controls.
- Viewer behavior.
- Routes.
- Error pages.
- `robots.txt`.
- Website headers and caching.
- Serving R2 files to visitors.

A change may require both when it affects R2 folder names, index structure, or metadata shared between collection and display.

# 10. How to change the Yoink schedule

1. Open:

```text
.github/workflows/yoink.yaml
```

2. Find the `schedule` section.
3. Change the cron expression.
4. Commit the change to `main`.

GitHub may still begin scheduled runs late.

# 11. Healthy Yoink run indicators

A healthy run should show messages like:

```text
Restored prior download history from R2
Home routing is active
Scanning source
Download phase complete
Direct GitHub routing is restored
Uploaded ... -> r2://...
Updated gallery-index.json
Saved download history to R2
Direct R2 upload phase complete
```

# 12. Failure behavior

## Home route does not activate

Yoink stops before contacting Reddit.

## Direct GitHub route does not return

Yoink stops before uploading to R2.

## One source partially fails

Files already downloaded may still continue to upload.

## R2 media upload fails

The program retries. If it still fails, the failure is counted and history is rolled back far enough to retry uncertain media later.

## Yoink is cancelled during upload before the index is written

Some successfully uploaded R2 objects may be missing from `gallery-index.json`. Run Flush once.

## No prior history exists

Normal on the first run.

# 13. Documentation rule

Whenever behavior, settings, secret names, workflow names, workflow filenames, file paths, or setup steps change:

1. Update the code or workflow.
2. Update `README.md` in the same change.
3. Update `DGD.md` in the same change.
4. Do not leave references to old filenames or removed behavior.
5. Keep exact names and paths in parity with the repository.

In this project, “docs” means both `README.md` and `DGD.md`.