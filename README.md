# SpongeTV

SpongeTV is a video add-on for Kodi 21 "Omega" and later. It brings together TMDB for titles and
artwork, Trakt for your watched history, Premiumize for playing sources, and the provider packages
you choose to install, in one place.

- **Add-on ID:** `plugin.video.spongetv`
- **Requires:** Kodi 21 or later
- **Current release:** 1.0.0 (see [changelog.txt](changelog.txt) for every change)
- **Licence:** GPL-3.0-or-later (see [LICENSE](LICENSE))

## What it does

- **Browse** films and TV shows from TMDB: trending, popular, genres, years, networks, streaming
  services, cast and crew, and search.
- **Trakt:** sign in with a code, then your watched history, resume points, lists, Next up and
  calendar follow you between devices. Mark things watched or unwatched, rate them, and add them to
  your watchlist, collection or lists from the context menu. What you watch is scrobbled as you go.
- **Sources:** search the provider packages you install, finish early once enough good sources are
  ready, and choose in Source Select, with filters (quality, size, CAM copies, HDR and more) and your
  own sort order.
- **Premiumize:** sign in with a code. SpongeTV checks what Premiumize already has ready, picks the
  right file from season packs, and can play from your Premiumize cloud.
- **Playback:** resume where you left off (on any device, through Trakt). Smart Play finds a source
  for the next episode while you watch, shows Playing Next near the end, or when the end credits start
  if the episode's chapters mark them, and asks if you're still watching after a few episodes.
- **Your views:** choose the view each kind of list opens in, from the list itself.

## Installing

The easiest way is from the MrSpongeHead Repository, so Kodi keeps SpongeTV up to date:

1. **Settings > File manager > Add source.** Enter
   `https://mrspongehead.github.io/repository.mrspongehead/` and name it `mrspongehead`.
2. **Settings > Add-ons > Install from zip file > mrspongehead** and choose
   `repository.mrspongehead-x.y.z.zip`. (The first time, Kodi asks you to allow **Unknown sources**
   in **Settings > System > Add-ons**.)
3. **Install from repository > MrSpongeHead Repository > Video add-ons > SpongeTV.**

You can also install a single release zip from the
[releases page](https://github.com/MrSpongeHead/plugin.video.spongetv/releases) with
**Install from zip file**, but it then won't update by itself.

## Setting up

The setup wizard opens the first time you start SpongeTV (and again from
**Settings > Accounts > Run setup wizard again**). You'll need:

- **A TMDB API key**, which is free from [themoviedb.org](https://www.themoviedb.org/settings/api).
  SpongeTV needs it for titles, plots and artwork. It isn't included in SpongeTV, so each person uses
  their own.
- **A Trakt account** (free) for watched history, resume points, lists and Next up.
- **A Premiumize premium account** to play most sources.

Optional extras, under **Settings > Accounts**: a free **Fanart.tv** personal key for more clear logos
and clear art, and a free **OMDb** key for IMDb, Rotten Tomatoes and Metacritic ratings.

Every setting explains itself in the line at the bottom of the settings screen.

## Provider packages

SpongeTV includes no providers. It installs provider packages you supply, from a link or a zip,
in the same format as Seren-compatible packages: **Tools > Providers and sources**.

## Developing

- Tests: `python3 -m pytest tests` (no Kodi or network needed).
- Build a zip: `python3 tools/build.py` (writes to `dist/`). The zip contains SpongeTV's Trakt and
  Premiumize app IDs but never a TMDB key.

Copyright (C) 2026 MrSpongeHead
