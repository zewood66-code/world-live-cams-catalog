# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Public catalog for the World Live Cams Android TV app. The app's source lives in the private repo `zewood66-code/world-live-cams` (local copy: `D:\projet claude\web cam app`, whose CLAUDE.md documents the format, the sources and how to find cameras). Installed apps download `catalog.json` from this repo's raw URL on every launch. Editing it here updates every installed app without a new APK.

The user writes in French; code comments and messages shown on issues are in French.

## Files

- `catalog.json`: places → categories and cameras. Keep one camera per line, serialized like Python's `json.dumps(..., ensure_ascii=False)`, and bump `updatedAt` on each edit. Both scripts edit it as text (never re-serialize the whole file): `refresh_catalog.py` replaces `"videoId": "…"`, `add_camera.py` inserts a line.
- `.github/workflows/refresh-catalog.yml`: runs `tools/refresh_catalog.py catalog.json` hourly with the `YOUTUBE_API_KEY` secret, replaces the IDs of restarted YouTube lives, and, when the last search is over 20 h old, writes `tools/candidates.md` (YouTube lives missing from the catalog, to check by hand).
- `tools/watch_earthcam.py` (same hourly workflow, no API key) adds and removes short-lived EarthCam event cams on its own. It reads the EarthCam directory for the catalog's states and countries, plus the `json_base` of every EarthCam page in the catalog and of `WATCHED_PAGES`.
  - **Adding**: a cam that is online and missing from both the catalog and `tools/earthcam_ignored.txt` is added to its place's `events` row when it looks like an event and has an HLS stream and coordinates. It looks like an event when it was found on a page that is already read, its URL contains `/events/`, or its title has one of the `EVENT_WORDS`. Other new cams are only listed in `tools/earthcam.md`.
  - **Removing**: an EarthCam cam in an `events` row that is offline or gone from its page is listed. It is removed if it is still off on the next run.
  - **State**: `tools/earthcam.md` has no timestamp, so it only changes when its lists change. It also serves as the script's memory between runs. A source that fails keeps its previous lines.
  - **Notifications**: after a successful push, additions, removals and new lines are posted as a comment, mentioning the owner, on the open issue labelled `earthcam` (created if missing). If the push fails, the next run redoes the same work.
  - **Reading pages**: pages are read through a catalog camera's `?cam=` URL, because some pages (Statue of Liberty) leave `json_base` empty without it.
  - **Dismissing a cam**: remove it from the catalog and add its EarthCam id to `earthcam_ignored.txt`, or it will be added back.
- Every place except the global ones has an `events` row ("Holidays & events") listed first. It holds short-lived cams (holidays, parades, New Year's Eve). The app hides empty rows, so the row only shows while it holds cameras.
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
