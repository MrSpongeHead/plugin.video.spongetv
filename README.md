# SpongeTV

SpongeTV is a Kodi video add-on for Kodi 21 "Omega" and later. It brings together
Trakt syncing, TMDB metadata, Premiumize and your own provider packages in one place.

- **Add-on ID:** `plugin.video.spongetv`
- **Requires:** Kodi 21 or later
- **Licence:** GPL-3.0-or-later (see [LICENSE](LICENSE))

## Status

Release 1 is being built in five stages:

1. Foundations: skeleton, settings, setup wizard, local database, TMDB metadata and menus
2. Trakt: sign-in, sync, scrobbling, Next Up and context menu actions
3. Sources: provider package install and manager, source search, Source Select
4. Premiumize and playback: resolving, cloud search, resume, Smart Play and dialogs
5. Polish: background service, maintenance, error handling, artwork

## Installing a test build

1. Download the zip for the stage you are testing.
2. In Kodi, go to **Settings > Add-ons > Install from zip file** and choose the zip.
   (The first time, Kodi asks you to allow **Unknown sources** in **Settings > System > Add-ons**.)

## Provider packages

SpongeTV does not include any providers. It can install provider packages you supply
(from a URL or a local zip) in the same package format used by Seren-compatible packages.

## Developing

- Tests: `python3 -m pytest tests` (no Kodi or network needed).
- Build a zip: `python3 tools/build.py` (writes to `dist/`). Built-in API keys are read from
  `keys.local.json`, which is not stored in this repository.

Copyright (C) 2026 MrSpongeHead
