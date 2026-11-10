# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Trakt sync: download only the parts of your Trakt data whose "last activity" time changed.

Each part is fetched in full (every page) and only then swapped in locally, so a failed or
interrupted sync never wipes watched marks. Only one sync runs at a time; the lock frees
itself if a sync crashes.
"""

import datetime
import json
import time

from resources.lib import kodi
from resources.lib.library import Library, row
from resources.lib.trakt import TraktError

LOCK_STALE = 15 * 60
# Bumped whenever the way a part is downloaded changes, so the next sync fetches everything again.
# 2: watched shows need extended=progress for their seasons (Trakt API change, 3 July 2026).
SYNC_FORMAT = "2"
PROGRESS_LIMIT = 100   # Trakt caps extended=progress pages at 100 items

# (part, media, activity keys that mean this part changed, Trakt path, extra query)
PARTS = [
    ("watched", "movie", [("movies", "watched_at")], "/sync/watched/movies", {}),
    # Since 3 July 2026 watched shows only include seasons and episodes with extended=progress.
    ("watched", "episode", [("episodes", "watched_at")], "/sync/watched/shows", {"extended": "progress"}),
    ("collection", "movie", [("movies", "collected_at")], "/sync/collection/movies", {}),
    ("collection", "episode", [("episodes", "collected_at")], "/sync/collection/shows", {}),
    ("ratings", "movie", [("movies", "rated_at")], "/sync/ratings/movies", {}),
    ("ratings", "show", [("shows", "rated_at")], "/sync/ratings/shows", {}),
    ("ratings", "season", [("seasons", "rated_at")], "/sync/ratings/seasons", {}),
    ("ratings", "episode", [("episodes", "rated_at")], "/sync/ratings/episodes", {}),
    ("watchlist", "movie", [("movies", "watchlisted_at")], "/sync/watchlist/movies", {}),
    ("watchlist", "show", [("shows", "watchlisted_at")], "/sync/watchlist/shows", {}),
    ("favourites", "movie", [("movies", "favorited_at")], "/sync/favorites/movies", {}),
    ("favourites", "show", [("shows", "favorited_at")], "/sync/favorites/shows", {}),
    ("hidden", "show", [("shows", "hidden_at")], "/users/hidden/progress_watched", {"type": "show"}),
    ("dropped", "show", [("shows", "dropped_at"), ("shows", "hidden_at")], "/users/hidden/dropped", {}),
    ("playback", "movie", [("movies", "paused_at")], "/sync/playback/movies", {}),
    ("playback", "episode", [("episodes", "paused_at")], "/sync/playback/episodes", {}),
]


def _tmdb(item):
    return ((item or {}).get("ids") or {}).get("tmdb")


def _trakt(item):
    return ((item or {}).get("ids") or {}).get("trakt")


def _old(when, max_age_days, now):
    try:
        moment = datetime.datetime.fromisoformat((when or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return max_age_days > 0 and now - moment > max_age_days * 86400


def rows_for(part, media, entries, resume_max_age_days=0, now=None):
    """Turn Trakt's response for a part into library rows."""
    now = now or time.time()
    rows = []
    for e in entries:
        if part in ("watched", "collection") and media == "movie":
            rows.append(row(part, "movie", _tmdb(e.get("movie")), _trakt(e.get("movie")),
                            value=e.get("plays", 1), at=e.get("last_watched_at") or e.get("collected_at")))
        elif part in ("watched", "collection") and media == "episode":
            show = _tmdb(e.get("show"))
            if not show:
                continue
            for season in e.get("seasons") or []:
                for ep in season.get("episodes") or []:
                    # The progress format may list every aired episode with completed true/false.
                    if ep.get("completed") is False or ep.get("plays") == 0:
                        continue
                    rows.append(row(part, "episode", show=show, season=season.get("number"), episode=ep.get("number"),
                                    value=ep.get("plays") or 1, at=ep.get("last_watched_at") or ep.get("collected_at")))
        elif part == "ratings":
            if media in ("movie", "show"):
                rows.append(row(part, media, _tmdb(e.get(media)), _trakt(e.get(media)), value=e.get("rating"),
                                at=e.get("rated_at")))
            elif media == "season":
                rows.append(row(part, "season", show=_tmdb(e.get("show")), season=(e.get("season") or {}).get("number"),
                                value=e.get("rating"), at=e.get("rated_at")))
            else:
                ep = e.get("episode") or {}
                rows.append(row(part, "episode", show=_tmdb(e.get("show")), season=ep.get("season"),
                                episode=ep.get("number"), value=e.get("rating"), at=e.get("rated_at")))
        elif part in ("watchlist", "favourites"):
            item = e.get(media)
            rows.append(row(part, media, _tmdb(item), _trakt(item), value=e.get("rank"), at=e.get("listed_at")))
        elif part in ("hidden", "dropped"):
            rows.append(row(part, "show", _tmdb(e.get("show")), _trakt(e.get("show")),
                            at=e.get("hidden_at") or e.get("dropped_at")))
        elif part == "playback":
            if _old(e.get("paused_at"), resume_max_age_days, now):
                continue   # stale resume points are left out
            extra = {"playback_id": e.get("id")}
            if media == "movie":
                rows.append(row(part, "movie", _tmdb(e.get("movie")), value=e.get("progress"), at=e.get("paused_at"),
                                extra=extra))
            else:
                ep = e.get("episode") or {}
                rows.append(row(part, "episode", show=_tmdb(e.get("show")), season=ep.get("season"),
                                episode=ep.get("number"), value=e.get("progress"), at=e.get("paused_at"), extra=extra))
    return [r for r in rows if r[2] or r[4]]   # need a TMDB ID for the item or its show


class Syncer:
    def __init__(self, trakt, store, clock=time.time, resume_max_age_days=0):
        self.trakt = trakt
        self.store = store
        self.library = Library(store)
        self.clock = clock
        self.resume_max_age_days = resume_max_age_days

    # -- lock --------------------------------------------------------------------------------
    def _take_lock(self):
        held = float(self.store.get_meta("sync_lock") or 0)
        if held and self.clock() - held < LOCK_STALE:
            return False
        self.store.set_meta("sync_lock", str(self.clock()))
        return True

    def _release_lock(self):
        self.store.set_meta("sync_lock", "")

    # -- state shown in Tools ---------------------------------------------------------------------
    def status(self):
        return self.store.get_meta("sync_last") or "", self.store.get_meta("sync_error") or ""

    def forget(self):
        """Clear last sync times, so the next sync downloads everything."""
        for part, media, *_ in PARTS:
            self.store.set_meta(f"sync_part:{part}:{media}", "")

    def rebuild(self):
        self.library.clear()
        self.forget()
        return self.run(force=True)

    # -- safety checks on what Trakt sends ---------------------------------------------------------
    def _fill_show_ids(self, entries, max_lookups=300):
        """Shows arriving without a TMDB ID (a slimmer format) are looked up by their Trakt ID."""
        lookups = 0
        for entry in entries:
            show = entry.get("show") or {}
            ids = show.get("ids") or {}
            if ids.get("tmdb") or not ids.get("trakt") or lookups >= max_lookups:
                continue
            key = f"trakt:show_ids:{ids['trakt']}"
            found = self.store.cache_get(key)
            if found is None:
                lookups += 1
                try:
                    found = (self.trakt.get(f"/shows/{ids['trakt']}") or {}).get("ids") or {}
                except TraktError:
                    found = {}
                self.store.cache_set(key, found, 30 * 86400)
            ids.update({k: v for k, v in found.items() if v})
            show["ids"] = ids
            entry["show"] = show

    @staticmethod
    def _check_seasons(part, entries):
        without = sum(1 for e in entries if not e.get("seasons"))
        kodi.log_debug(f"Trakt {part}: {len(entries)} shows, {without} without seasons")
        if entries and without == len(entries):
            kodi.log_error(f"Trakt {part}: no show came with its seasons; episode marks can't be read")

    # -- the sync -------------------------------------------------------------------------------
    def run(self, force=False, progress=None):
        """Returns the list of parts updated, or None if another sync was already running."""
        if not self._take_lock():
            return None
        updated = []
        try:
            if self.store.get_meta("sync_format") != SYNC_FORMAT:
                self.forget()   # the download changed: fetch every part again once
                force = True
            activities = self.trakt.get("/sync/last_activities", auth=True) or {}
            for index, (part, media, keys, path, params) in enumerate(PARTS):
                if progress:
                    progress(index, len(PARTS))
                marker = json.dumps([(activities.get(a) or {}).get(b) for a, b in keys])
                key = f"sync_part:{part}:{media}"
                if not force and self.store.get_meta(key) == marker:
                    continue
                try:
                    limit = PROGRESS_LIMIT if params.get("extended") == "progress" else None
                    entries = self.trakt.get_all(path, params, **({"limit": limit} if limit else {}))
                    if media == "episode":
                        self._fill_show_ids(entries)
                        if part == "watched":       # resume points come as single episodes, never seasons
                            self._check_seasons(part, entries)
                except TraktError as error:
                    if error.kind == "not_found":      # a part Trakt doesn't offer this account
                        self.store.set_meta(key, marker)
                        continue
                    raise
                self.library.replace(part, media, rows_for(part, media, entries, self.resume_max_age_days, self.clock()))
                self.store.set_meta(key, marker)
                updated.append(f"{part}:{media}")
            self.trakt.send_queued_scrobbles()
            self.store.set_meta("sync_format", SYNC_FORMAT)
            self.store.set_meta("sync_last", datetime.datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d %H:%M"))
            self.store.set_meta("sync_error", "")
            return updated
        except TraktError as error:
            self.store.set_meta("sync_error", error.kind)
            raise
        finally:
            self._release_lock()
