# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Watched marks, resume points and progress counts for list items, from the local Trakt library.

Aired episode counts come from TMDB's show details ("last episode to air"), so they need no extra
requests. Specials (season 0) don't count towards a show's progress.
"""


def aired_counts(details):
    """{season number: episodes aired so far} for regular seasons."""
    last = details.get("last_episode_to_air") or {}
    last_season, last_episode = last.get("season_number"), last.get("episode_number")
    counts = {}
    for season in details.get("seasons") or []:
        number = season.get("season_number")
        if not number:
            continue
        if last_season is None or number > last_season:
            counts[number] = 0
        elif number < last_season:
            counts[number] = int(season.get("episode_count") or 0)
        else:
            counts[number] = int(last_episode or 0)
    return counts


class Marks:
    """Answers "how watched is this?" for menus. Without a Trakt sign-in, everything is unwatched."""

    def __init__(self, library=None):
        self.library = library

    @property
    def active(self):
        return self.library is not None

    def _own(self, key):
        """SpongeTV's own resume point (saved while playing): (percent, position, total) or None."""
        saved = self.library.store.cache_get(f"resume:{key}")
        if saved and saved.get("position") and saved.get("total"):
            return saved.get("percent", 0), saved["position"], saved["total"]
        return None

    def movie(self, tmdb_id):
        """(plays, resume percent), or (plays, percent, position, total) from SpongeTV's own resume point"""
        if not self.library:
            return 0, 0
        plays = self.library.movie_plays(tmdb_id)
        own = self._own(f"movie:{tmdb_id}")
        return (plays,) + own if own else (plays, self.library.progress("movie", tmdb_id)[0])

    def _show_episodes(self, show_id):
        return self.library.watched_episodes(show_id) if self.library else {}

    def show(self, details):
        """(watched episodes, aired episodes) across regular seasons."""
        if not self.library:
            return 0, 0
        counts = aired_counts(details)
        watched = self._show_episodes(details.get("id"))
        done = sum(1 for (s, e) in watched if s and s in counts and e <= counts[s])
        return done, sum(counts.values())

    def season(self, details, number):
        if not self.library:
            return 0, 0
        aired = aired_counts(details).get(number, 0) if number else 0
        watched = [e for (s, e) in self._show_episodes(details.get("id")) if s == number]
        if not number:   # specials: count what's been watched against what exists
            return len(watched), 0
        return sum(1 for e in watched if e <= aired), aired

    def episode(self, show_id, season, episode):
        """(plays, resume percent), or (plays, percent, position, total) from SpongeTV's own resume point"""
        if not self.library:
            return 0, 0
        plays = self._show_episodes(show_id).get((season, episode), (0, ""))[0]
        own = self._own(f"episode:{show_id}:{season}:{episode}")
        return (plays,) + own if own else (plays, self.library.progress("episode", show=show_id, season=season,
                                                                         episode=episode)[0])


def fully_watched(watched, aired):
    return aired > 0 and watched >= aired
