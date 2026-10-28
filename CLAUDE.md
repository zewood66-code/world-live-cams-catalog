# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Public catalog for the World Live Cams Android TV app. The app's source lives in the private repo `zewood66-code/world-live-cams` (local copy: `D:\projet claude\web cam app`, whose CLAUDE.md documents the format, the sources and how to find cameras). Installed apps download `catalog.json` from this repo's raw URL on every launch. Editing it here updates every installed app without a new APK.

The user writes in French; code comments and messages shown on issues are in French.

## Files

- `catalog.json`: places → categories and cameras. Keep one camera per line, serialized like Python's `json.dumps(..., ensure_ascii=False)`, and bump `updatedAt` on each edit. Both scripts edit it as text (never re-serialize the whole file): `refresh_catalog.py` replaces `"videoId": "…"`, `add_camera.py` inserts a line.
- `.github/workflows/refresh-catalog.yml`: runs `tools/refresh_catalog.py catalog.json` hourly with the `YOUTUBE_API_KEY` secret, replaces the IDs of restarted YouTube lives, and, when the last search is over 20 h old, writes `tools/candidates.md` (YouTube lives missing from the catalog, to check by hand).
- `.github/ISSUE_TEMPLATE/add-camera.yml` + `.github/workflows/add-camera.yml`: opening an "Ajouter une caméra" issue (label `add-camera`, owner only) runs `tools/add_camera.py`. It builds the camera line, inserts it after the last camera of its row, pushes, then comments and closes the issue. On errors it comments and waits for the issue to be edited. The form's field labels must match the script's `FIELDS`; its place list and row ids are hard-coded, so new places or rows must be added to the form by hand.
- Before building a new APK, copy `catalog.json` to the app repo's `app/src/main/assets/catalog/catalog.json`, so the bundled catalog stays recent.
- This repo is public on purpose. Never put the APK, its download link or any key here.

## Commands

No build, lint or test suite. The scripts use only the standard library.

```bash
YOUTUBE_API_KEY=… python tools/refresh_catalog.py catalog.json [--discover tools/candidates.md]
# Issue body (### sections, as GitHub renders the form) -> camera added to the file; exit 1 with errors in the report
python tools/add_camera.py catalog.json --body issue.md --report report.md
```

To try `add_camera.py` without touching the real catalog, run it on a copy. Only YouTube cameras need `YOUTUBE_API_KEY`. On Windows, set `PYTHONIOENCODING=utf-8` to print accents. Python has no timezone database there, so the timezone check is skipped.

## Camera conventions

Key order matches the existing lines: `id, name, area, category, type, lat, lon`, then the source fields, then the optional `timezone, clockLabel`. Places with `"global": true` (`paradise-beaches`, `airports`) need `timezone` and `clockLabel` on every camera.

| source | id | source fields |
|---|---|---|
| YouTube (no `source` key) | slug of the name | `channel` (`/channel/<id>` URL), `match` (title phrases that survive a restart), `videoId` |
| `earthcam` | `ec-<cam>` | `page` (`…?cam=<cam>`), `cam`, `channel` {EarthCam, page}, `thumbnail` (the page's `json_base` `thumbimage`, at 512x288) |
| `earthcamshare` (app ≥ 0.6.1) | `ecs-<slug of the name>` | `page` (`https://share.earthcam.net/public/<client>/<project>/<camera>`), `channel` {EarthCam, page}, `thumbnail` (the `live` archive `image.url` from `/api/v2/public/page/<client>/<project>`, without its unchecked `?,k=` key) |
| `skyline` | `sky-<last two path parts>` | `page` (`/en/webcam/…html`), `channel` {SkylineWebcams, page}, `thumbnail` (the page's `og:image`) |
| `webcamerapl` | `wc-<slug>` | `page` (`https://<slug>.webcamera.pl/` or `…/kamera/<slug>/`), `channel` {WebCamera.pl, page}, `thumbnail` `https://static.webcamera.pl/camsbig/<slug>.jpg` |

## Concurrency

Both workflows commit to `main` and both rewrite the `updatedAt` line, so a rebase would conflict. On a rejected push, `add-camera.yml` resets to `origin/main` and reruns the script (up to 3 tries).
