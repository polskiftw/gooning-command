# GParty — DGD Guide

GParty collects media into Cloudflare R2, tags it locally, serves it through a Cloudflare Worker, and includes a Windows program for reviewing and deleting duplicate media.

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
                +--> Windows GParty Tag Time
                |
                +--> Windows GParty Deduper
```

The programs agree on these names:

| Thing | Exact name |
|---|---|
| Media folder inside R2 | `gallery/` |
| Media list inside R2 | `gallery-index.json` |
| Download history inside R2 | `_internal/gallery-dl-archive-v0.2.1.sqlite3` |
| Private viewer source list inside R2 | `_internal/reddit-sources.json` |
| Private Tag Time index inside R2 | `_internal/tag-index-v1.json` |
| Worker bucket binding | `MEDIA_BUCKET` |
| Bucket-name secret | `R2_BUCKET_NAME` |

# 2. Files in the repository

| File or folder | Job |
|---|---|
| `app.py` | Merges private sources, downloads, uploads, remembers finished posts, and writes the R2 index |
| `settings.json` | Collector settings and harmless source placeholders |
| `requirements.txt` | Packages used by Yoink and Flush |
| `worker/worker.js` | Security headers around the Cloudflare Worker routes |
| `worker/viewer.js` | Viewer page, APIs, certificate check, and R2 access |
| `worker/app.js` | Viewer buttons, filters, keyboard, media behavior, and add-subreddit box |
| `worker/style.css` | Viewer appearance |
| `worker/wrangler.jsonc` | Local Wrangler settings and Worker wiring |
| `worker/repair_index.py` | Adds missing R2 objects to the index |
| `deduper/` | Windows deduper code, build recipe, configuration sample, and tests |
| `tagtime/` | Windows Tag Time code, build recipe, configuration sample, and tests |
| `.github/workflows/yoink.yml` | Collector workflow |
| `.github/workflows/flush.yml` | Index repair workflow |
| `.github/workflows/update-cf-web.yml` | Worker deployment workflow |
| `.github/workflows/build-deduper.yml` | Windows deduper build workflow |
| `.github/workflows/build-tag-time.yml` | Windows Tag Time build workflow |
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

You may keep using up to ten optional private fallback source values:

```text
REDDIT_SOURCE_1
REDDIT_SOURCE_2
REDDIT_SOURCE_3
REDDIT_SOURCE_4
REDDIT_SOURCE_5
REDDIT_SOURCE_6
REDDIT_SOURCE_7
REDDIT_SOURCE_8
REDDIT_SOURCE_9
REDDIT_SOURCE_10
```

A source value can be either:

```text
example
```

or:

```text
https://www.reddit.com/r/example/new/
```

Yoink builds a temporary private `settings.json` on the GitHub runner. The real source values are not written into the repository. You do not need another numbered secret for sources added with the viewer’s gray `+` button.

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

The optional private `REDDIT_SOURCE_*` secrets replace the placeholders during Yoink. Yoink then reads `_internal/reddit-sources.json`, adds every source entered through the private viewer, removes duplicates, and discards any harmless placeholder left over. Keep the R2 prefix as `gallery/`.

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
2. Inserts any numbered private source secrets into temporary settings.
3. Installs Python, FFmpeg, and the collector packages.
4. Reads `_internal/reddit-sources.json` directly from R2.
5. Merges, validates, deduplicates, and masks every private source.
6. Records and masks the GitHub runner IP.
7. Restores the small R2 download-history database.
8. Connects to Tailscale and selects the private exit node.
9. Confirms the public route changed.
10. Downloads new media.
11. Stops using the exit node.
12. Confirms GitHub's direct route returned.
13. Uploads media to R2.
14. Writes the gallery index and saves download history.

`app.py` supports these internal modes:

| Mode | Job |
|---|---|
| `prepare-sources` | Merges numbered secrets with the private R2 source list |
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

# 8A. Audit the live index

Run:

```text
GitHub repository
→ Actions
→ Audit Index
→ Run workflow
```

Audit Index reads `gallery-index.json` and lists the R2 gallery without changing either one. It reports only aggregate numbers. It checks duplicate keys that could make certain media more likely, malformed rows, extension mistakes, count mismatches, indexed objects missing from R2, and R2 media missing from the index. It never prints media filenames or credentials.

A green run ends with `AUDIT RESULT: CLEAN`. A red run ending with `AUDIT RESULT: PROBLEMS FOUND` means its aggregate report identified something that should be repaired or investigated.

# 9. Worker

The Worker routes are:

| Route | Job |
|---|---|
| `/` | Loads the viewer |
| `/api/random` | Picks a random indexed item using the selected filter |
| `/api/tags` | Returns the available tag names and each tag's individual count |
| `POST /api/sources` | Adds one validated subreddit to the private R2 source list |
| `/media/<encoded-key>` | Streams one indexed R2 object, including video range requests |

The Worker reads `gallery-index.json` and the private Tag Time index through `env.MEDIA_BUCKET`. It only accepts media keys beginning with `gallery/`. The private tag index itself cannot be served by `/media/`.

The Worker's in-memory index cache lasts 60 seconds. A corrected index may therefore take up to one minute to appear in the viewer.

On desktop, the left sidebar shows every discovered tag with a checkbox and that tag's individual count. With no boxes checked, random behaves exactly as before. With one box checked, random uses only media with that tag. With several checked, the media must have every checked tag. The site does not calculate or display a combined count. An impossible combination shows `Nothing matches those tags.`

The entire tag sidebar is absent on screens 700 pixels wide or narrower. Mobile sizing, tap-to-random behavior, filters, and the hardened bottom-pixel layout stay unchanged.

The viewer validates every random-item response before replacing the current media. It automatically retries temporary server failures, timeouts, empty replies, malformed JSON, and invalid media addresses up to three times. If all attempts fail, the current media stays visible and the viewer shows a useful retry message instead of Safari's generic parsing error.

## Add a subreddit from the viewer

1. Open the certificate-protected GParty viewer.
2. Tap the transparent gray **+** centered between **All** and the GitHub/email icons.
3. Type a subreddit name such as `pics`.
4. Tap **Add**.
5. Wait for `Added. Yoink will use it next run.`

You may also enter `r/pics` or a complete Reddit subreddit URL. Invalid names are rejected. Adding the same subreddit twice, including with different capitalization, does not create a duplicate.

The Worker creates `_internal/reddit-sources.json` automatically the first time this succeeds. The object stays private in R2 and never enters the gallery index. The add request must come from the same viewer page and must include a client certificate that Cloudflare reports as successfully verified.

# 10. Publish Worker changes

Run:

```text
GitHub repository
→ Actions
→ update-cf-web 3
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

The deployment configuration explicitly sets:

```toml
workers_dev = false
preview_urls = false
```

This keeps both the normal `workers.dev` address and version preview addresses disabled after every deployment. The certificate-protected custom hostname remains the intended route.

# 10A. Download GParty Tag Time

Open this permanent download link:

```text
https://github.com/polskiftw/gparty/releases/download/tag-time-windows-latest/GParty-Tag-Time-Windows.zip
```

Extract `GParty-Tag-Time-Windows.zip` into a normal folder on the Windows PC. Do not run it from inside the ZIP.

The build named **Build GParty Tag Time 1** creates the Windows app automatically whenever Tag Time code changes on `main`. It runs the tests first, builds `GParty Tag Time.exe`, and replaces the permanent download only if it still represents the newest `main` commit.

# 10B. Configure GParty Tag Time

In the extracted Tag Time folder:

1. Find `config.example.txt`.
2. Make a copy in the same folder.
3. Rename the copy exactly `config.txt`.
4. Open the deduper's existing `config.txt`.
5. Copy these four complete lines from the deduper file into the Tag Time file:

```text
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
```

The parts after each `=` must contain the same values as the deduper. Do not paste these secrets into GitHub code, README files, screenshots, or chat.

Leave the rest exactly like this:

```text
GALLERY_PREFIX=gallery/
TAG_INDEX_KEY=_internal/tag-index-v1.json
TAG_THRESHOLD=0.4
ANIMATED_FRAMES=4
PUBLISH_EVERY=100
```

The R2 token must be allowed to list and read media and write the tag index. No new bucket, Cloudflare Worker binding, Cloudflare API token, Worker secret, or dashboard setting is needed.

# 10C. Run GParty Tag Time

1. Double-click `GParty Tag Time.exe`.
2. Press the large **TAG TIME** button.
3. Leave the app open while it works. You may use the PC normally.
4. You may close Tag Time whenever you want. It finishes the current file, uploads the newest catalog, and closes.
5. Open it later and press **TAG TIME** again to continue.

The first press downloads the official JoyTag model, about 366 MB, into `data/model/`. This happens only once. Tag Time uses Windows DirectML to run on the RTX 4070 Super; it does not require a separate CUDA installation. If GPU initialization is unavailable, it can fall back to CPU.

For every R2 item, Tag Time temporarily downloads one file, samples it, records its tags in `data/tag-time.sqlite3`, and removes the temporary copy. Still images use one frame. GIFs and videos use four representative frames from across the animation. Scores from those frames are combined, and tags at or above `0.4` are kept.

Tag Time immediately saves each successful file before moving to the next. A crash, reboot, closed window, bad media file, or lost connection does not erase earlier work. The next run skips unchanged completed files, tags new files, retags changed files, and retries failures. Files removed from R2 are removed from the next published catalog.

Every 100 newly completed files, and again when the run ends or pauses, Tag Time uploads:

```text
_internal/tag-index-v1.json
```

Wait up to 60 seconds for the Worker's cache, then reload the desktop viewer to see new tags or counts. Mobile never shows the tag sidebar.

# 11. Download the Windows deduper

Open this permanent download link:

```text
https://github.com/polskiftw/gparty/releases/download/windows-latest/GParty-Deduper-Windows.zip
```

Extract `GParty-Deduper-Windows.zip` into a normal folder on the PC.

The build workflow:

1. Uses a Windows GitHub runner.
2. Installs Python 3.12 and the deduper packages.
3. Runs the deduper tests.
4. Builds `GParty Deduper.exe` with PyInstaller.
5. Adds the example configuration and license.
6. Uploads the normal workflow artifact for 30 days.
7. Replaces the ZIP in the **Latest Windows Build** release.

It runs automatically when deduper code or the deduper build workflow changes on `main`. A new run cancels an older build. The publishing step also checks that it still represents the newest `main` commit before replacing the release.

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
7. Separates byte-identical SHA-256 groups into an invisible NUKE queue, automatically keeping one copy of each hash.
8. Withholds every member of those SHA groups from perceptual review for this scan.
9. Applies the current slider setting to find perceptual duplicate matches among the remaining objects.
10. Builds safe groups in which every visible queued candidate directly matches its survivor.

The first full scan is the long one. Later scans use the R2 key, ETag, size, and modified time to hash only new or changed objects.

The database lives here:

```text
data/gparty-deduper.sqlite3
```

Previews are fetched directly from R2 when a pair is shown. Stills and GIFs decode from memory. Video decoding uses a short-lived temporary file only because OpenCV requires a seekable filename; that file is deleted before the preview is displayed. There is no persistent `preview-cache` folder to manage or prune.

The database is not uploaded to R2 or GitHub.

# 14. Hashes used by the deduper

| Hash | Finds |
|---|---|
| SHA-256 | Exactly identical bytes |
| pHash | Stills that look nearly identical |
| Crop-resistant hash | Crops, borders, and reframing |
| Meta PDQ | Strong still-image perceptual matches |
| vPDQ-style frame set | Similar clips, re-encodes, and video subsequences |

For video and animated GIFs, the program samples frames, calculates a Meta PDQ hash for each useful frame, and compares the two sets in both directions. This follows the published vPDQ method while remaining buildable as a normal Windows application.

Crop-resistant hashes have their own indexed search. This lets them find a crop even when the whole-image pHash does not create a possible pair. GIF sampling uses ceiling division across the complete animation, so it stays at or below the configurable `MAX_VIDEO_FRAMES` value without simply chopping off the ending.

# 15. Slider and automatic target selection

Move the slider before pressing:

```text
SCAN
```

The slider has 100 positions:

| Direction | Result |
|---|---|
| Left | Looser; catches more possibilities and more false positives |
| Middle | Balanced starting point |
| Right | Stricter; fewer false positives and more missed duplicates |

The program uses a BK-tree for pHash and PDQ comparisons and banded frame lookup for vPDQ candidates. It does not blindly compare every object with every other object.

Exact SHA-256 duplicates are always targets, even at the strictest slider position. They are not shown as review pairs. For every repeated SHA-256 value, the program silently chooses one survivor and queues every extra copy for NUKE. The complete group is skipped by pHash, PDQ, crop, and vPDQ for that scan. After NUKE leaves one copy, that survivor is released back into perceptual matching on the next SCAN.

For each set of connected duplicate matches, the app chooses the best available survivor and queues only its direct matches. It then repeats with any remaining members, so an indirect A-to-B-to-C chain can produce multiple safe groups instead of an unverified A-to-C deletion pair. It prefers higher resolution, then longer duration, higher PDQ quality, and larger file size. The survivor is always shown on the left, and each right-side candidate is included in the next NUKE by default.

# 16. Single-screen review

The application never leaves its single working screen. Exact SHA groups are intentionally absent from this screen. Each perceptual pair shows:

- The automatically selected survivor on the left
- The candidate scheduled for deletion on the right
- Each R2 key
- Each file size
- Dimensions
- Video length when available
- Similarity score
- Why the pair matched

The controls are:

| Button | Result |
|---|---|
| `SCAN` | Inventories, hashes, detects, and queues duplicate candidates |
| `PREVIOUS` | Shows the previous pair |
| `NEXT` | Shows the next pair |
| `EXCLUDE FROM THIS NUKE` | Spares the right candidate for this scan and immediately advances |
| `NUKE SHA ONLY` | Immediately deletes only invisible exact-SHA extras and leaves perceptual targets queued |
| `NUKE` | Immediately deletes invisible SHA extras and all non-excluded right candidates |

The keyboard Left and Right arrow keys perform the same navigation as PREVIOUS and NEXT. Navigation wraps at both ends. There are no delete-side selectors, skip button, separate review screen, or confirmation dialogs.

Review navigation and **EXCLUDE FROM THIS NUKE** remain active while later matching stages run. The bottom progress line separately shows completed and total work for pHash, PDQ, crop-resistant matching, and vPDQ, plus a full-check percentage. It also shows how many exact SHA extras are waiting invisibly for NUKE.

An exclusion remains visible if revisited, but lasts only until the next SCAN. A new scan rebuilds the candidate queue and makes the object eligible again if it still matches.

Pairs are ordered from the least likely accepted duplicate to the most likely duplicate. The current slider position decides which matches are accepted when SCAN begins.

# 17. NUKE

NUKE performs the queued R2 deletions.

It:

1. Keeps exactly one object from every repeated SHA-256 group and deletes the invisible extra copies along with all non-excluded perceptual targets.
2. Records each success or failure in local SQLite.
3. Marks confirmed deletions locally.
4. Removes confirmed deleted keys from `gallery-index.json`.
5. Reports the number of deleted objects and reclaimed bytes.

NUKE begins immediately when clicked. It does not open a confirmation dialog.

**NUKE SHA ONLY** uses the same permanent R2 deletion and gallery-index cleanup path, but receives only the invisible exact-SHA queue. It does not delete or alter any perceptual review target. The normal **NUKE** receives both queues.

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
- Current-scan exclusions
- Deletion queue
- Deletion history and survivors
- Any gallery-index cleanup still needing a retry

# 19. Routine use

Normal cleanup session:

1. Open `GParty Deduper.exe`.
2. Set the slider.
3. Press **SCAN**.
4. Review available left/right perceptual pairs with the buttons or keyboard arrows while later comparison stages continue if desired.
5. Press **EXCLUDE FROM THIS NUKE** on any right-side candidate that should be spared.
6. Press **NUKE** when ready.
7. Wait up to 60 seconds for the Worker cache to refresh.

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

For Tag Time:

```text
python -m venv .venv-tag-time
.venv-tag-time\Scripts\activate
pip install -r tagtime\requirements-build.txt
python -m unittest discover -s tagtime\tests -v
python -m tagtime.main
```

Build the Tag Time EXE:

```text
cd tagtime
pyinstaller --clean --noconfirm GPartyTagTime.spec
```

# 22. Wiring checklist

| Producer or setting | Consumer | Must match |
|---|---|---|
| `settings.json`: `r2_gallery_prefix` | Worker, Flush, deduper | `gallery/` |
| `app.py`: index key | Worker, Flush, deduper | `gallery-index.json` |
| Deploy workflow binding | `worker/worker.js` | `MEDIA_BUCKET` |
| GitHub R2 bucket secret | Collector, Flush, deployment | `R2_BUCKET_NAME` |
| Deduper `R2_BUCKET_NAME` | The same R2 library | Same bucket |
| Viewer `POST /api/sources` | Yoink `prepare-sources` mode | `_internal/reddit-sources.json` |
| Tag Time `TAG_INDEX_KEY` | Worker `TAG_INDEX_KEY` | `_internal/tag-index-v1.json` |
| Tag Time R2 settings | Deduper R2 settings | Same four values and same bucket |

# 23. License

GParty uses the PolyForm Noncommercial License 1.0.0. Commercial use requires written permission from the copyright holder.

Copyright © 2026 polskiftw.
