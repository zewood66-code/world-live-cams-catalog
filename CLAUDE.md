# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Public catalog for the World Live Cams Android TV app. The app's source lives in the private repo `zewood66-code/world-live-cams` (local copy: `D:\projet claude\web cam app`, whose CLAUDE.md documents the format and sources). Installed apps download `catalog.json` from this repo's raw URL on every launch. Editing it here updates every installed app without a new APK.

- `catalog.json`: places → categories and cameras. Keep one camera per line, serialized like Python's `json.dumps(..., ensure_ascii=False)`, and bump `updatedAt` on each edit. `tools/refresh_catalog.py` rewrites `"videoId": "…"` with a plain text replace.
- `.github/workflows/refresh-catalog.yml`: runs `tools/refresh_catalog.py catalog.json` hourly with the `YOUTUBE_API_KEY` secret, replaces the IDs of restarted YouTube lives, and once a day writes `tools/candidates.md`.
- `.github/ISSUE_TEMPLATE/add-camera.yml` + `.github/workflows/add-camera.yml`: opening an "Ajouter une caméra" issue (owner only) runs `tools/add_camera.py`, which builds the camera line, inserts it after the last camera of its row, pushes, then comments and closes the issue. On errors it comments and waits for the issue to be edited. Field labels are shared with the script's `FIELDS`; new places or rows must be added to the form by hand.
- Before building a new APK, copy `catalog.json` to the app repo's `app/src/main/assets/catalog/catalog.json`, so the bundled catalog stays recent.
- This repo is public on purpose. Never put the APK, its download link or any key here.
