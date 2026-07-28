# 🐾 GParty

A small personal media collector that checks configured Reddit sources, downloads new media through a home internet connection, and stores the results in Cloudflare R2 for a separate Cloudflare Worker website to display.

> **GitHub collects it. R2 stores it. Cloudflare shows it.**

## What this repository does

- Runs automatically with GitHub Actions.
- Restores the prior download-history database from R2.
- Connects to a private Tailscale network.
- Routes Reddit and media downloads through a Tailscale-compatible home router or other exit node.
- Checks each configured subreddit for recent posts.
- Uses cookies and a browser User-Agent instead of Reddit OAuth.
- Downloads supported images, GIFs, and videos.
- Leaves the home route before uploading anything to R2.
- Uploads new files and updates `gallery-index.json`.
- Saves download history so later runs skip archived content.
- Masks detected public IP addresses in GitHub Actions logs.

## What this repository does not do

This repository is not the public website.

The Cloudflare Worker controls the viewer, buttons, fullscreen behavior, filters, error pages, website routes, and how visitors receive files from R2.

## Current flow

```text
GitHub Actions
    ↓
Restore download history from R2
    ↓
Connect through Tailscale and a home exit node
    ↓
Check Reddit and download new media
    ↓
Return to the normal GitHub network route
    ↓
Upload files and the updated history to R2
    ↓
Cloudflare Worker reads R2 and displays the website
```

## Important files

| File | Purpose |
|---|---|
| `app.py` | Collector, downloader, archive, R2 upload, and index logic |
| `settings.json` | Ordinary user-editable behavior and limits |
| `.github/workflows/download-cats.yml` | Schedule, environment, Tailscale routing, secrets, and run phases |
| `requirements.txt` | Python packages installed by GitHub Actions |
| `DGD.md` | Literal setup, settings, behavior, and troubleshooting guide |

## Private source overrides

The workflow supports these optional GitHub Secrets:

```text
REDDIT_SOURCE_1
REDDIT_SOURCE_2
REDDIT_SOURCE_3
```

When a matching secret exists, it privately replaces that source during the run and GitHub masks the value in logs. When it is missing, the workflow falls back to the matching entry in `settings.json`.

The secret may contain either a subreddit name:

```text
example
```

or a complete listing URL:

```text
https://www.reddit.com/r/example/new/
```

## Documentation

Open **[`DGD.md`](DGD.md)** for the full spoon-fed guide, including every setting, every secret name, the schedule, the collector phases, and what belongs in GitHub versus Cloudflare.

## License

This project is licensed under the **[PolyForm Noncommercial License 1.0.0](LICENSE)**.

Noncommercial use is permitted under the license. Commercial use requires separate prior written permission from the copyright holder.

Copyright © 2026 polskiftw.

---

Made for one tiny, stubborn personal archive that would rather keep running than become an enterprise platform. ✨