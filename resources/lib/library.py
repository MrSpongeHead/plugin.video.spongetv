# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Your Trakt data, kept locally so menus can show watched marks and lists without asking Trakt.

One table, one row per item per part. Parts: watched, collection, ratings, hidden (hidden from
progress), dropped, favourites, watchlist, playback. Media: movie, show, season, episode.
Everything is keyed by TMDB IDs, which is what SpongeTV's menus use.
"""

import json

INSERT = ("INSERT INTO library (part, media, tmdb_id, trakt_id, show_tmdb_id, season, episode, value, at, extra) "
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")


def row(part, media, tmdb_id=None, trakt_id=None, show=None, season=None, episode=None, value=None, at="", extra=None):
    return (part, media, tmdb_id, trakt_id, show, season, episode, value, at or "",
            json.dumps(extra) if extra else None)


class Library:
    def __init__(self, store):
        self.store = store

    # -- whole parts (sync) ----------------------------------------------------------------
    def replace(self, part, media, rows):
        """Swap a part in one go, so a failed or partial download never wipes what's there."""
        self.store.replace_rows("DELETE FROM library WHERE part = ? AND media = ?", (part, media), INSERT, rows)

    def clear(self):
        self.store.execute("DELETE FROM library")

    def count(self, part=None):
        if part:
            return self.store.query("SELECT COUNT(*) FROM library WHERE part = ?", (part,))[0][0]
        return self.store.query("SELECT COUNT(*) FROM library")[0][0]

    # -- single items (actions update these straight away) ------------------------------------
    def add(self, part, media, tmdb_id=None, show=None, season=None, episode=None, value=None, at="", extra=None):
        self.remove(part, media, tmdb_id, show, season, episode)
        self.store.execute(INSERT, row(part, media, tmdb_id, None, show, season, episode, value, at, extra))

    def remove(self, part, media, tmdb_id=None, show=None, season=None, episode=None):
        if media == "episode":
            sql = "DELETE FROM library WHERE part = ? AND media = 'episode' AND show_tmdb_id = ?"
            params = [part, show]
            if season is not None:
                sql += " AND season = ?"
                params.append(season)
            if episode is not None:
                sql += " AND episode = ?"
                params.append(episode)
            self.store.execute(sql, params)
        elif media == "season":
            self.store.execute("DELETE FROM library WHERE part = ? AND media = 'season' AND show_tmdb_id = ? AND season = ?",
                               (part, show, season))
        else:
            self.store.execute("DELETE FROM library WHERE part = ? AND media = ? AND tmdb_id = ?", (part, media, tmdb_id))

    # -- questions menus ask -----------------------------------------------------------------
    def has(self, part, media, tmdb_id):
        return bool(self.store.query("SELECT 1 FROM library WHERE part = ? AND media = ? AND tmdb_id = ? LIMIT 1",
                                     (part, media, tmdb_id)))

    def ids(self, part, media, newest_first=True):
        """TMDB IDs in a part, most recent first (or Trakt's rank for lists that have one)."""
        order = "at DESC" if newest_first else "at ASC"
        rows = self.store.query(f"SELECT tmdb_id FROM library WHERE part = ? AND media = ? AND tmdb_id IS NOT NULL "
                                f"ORDER BY {order}", (part, media))
        return list(dict.fromkeys(r[0] for r in rows))

    def movie_plays(self, tmdb_id):
        rows = self.store.query("SELECT value FROM library WHERE part = 'watched' AND media = 'movie' AND tmdb_id = ?",
                                (tmdb_id,))
        return int(rows[0][0] or 0) if rows else 0

    def watched_episodes(self, show):
        """{(season, episode): (plays, last watched)} for one show."""
        rows = self.store.query("SELECT season, episode, value, at FROM library WHERE part = 'watched' "
                                "AND media = 'episode' AND show_tmdb_id = ?", (show,))
        return {(r[0], r[1]): (int(r[2] or 0), r[3]) for r in rows}

    def watched_shows(self):
        """[(show TMDB ID, last watched)] newest first."""
        rows = self.store.query("SELECT show_tmdb_id, MAX(at) FROM library WHERE part = 'watched' AND media = 'episode' "
                                "AND show_tmdb_id IS NOT NULL GROUP BY show_tmdb_id ORDER BY MAX(at) DESC")
        return [(r[0], r[1]) for r in rows]

    def collected_shows(self):
        rows = self.store.query("SELECT show_tmdb_id, MAX(at) FROM library WHERE part = 'collection' "
                                "AND media = 'episode' GROUP BY show_tmdb_id ORDER BY MAX(at) DESC")
        return [r[0] for r in rows if r[0]]

    def skipped_shows(self):
        """Shows hidden from progress or marked dropped on Trakt: left out of Next Up."""
        rows = self.store.query("SELECT tmdb_id FROM library WHERE part IN ('hidden', 'dropped') AND media = 'show'")
        return {r[0] for r in rows}

    def rating(self, media, tmdb_id=None, show=None, season=None, episode=None):
        if media == "episode":
            rows = self.store.query("SELECT value FROM library WHERE part = 'ratings' AND media = 'episode' "
                                    "AND show_tmdb_id = ? AND season = ? AND episode = ?", (show, season, episode))
        else:
            rows = self.store.query("SELECT value FROM library WHERE part = 'ratings' AND media = ? AND tmdb_id = ?",
                                    (media, tmdb_id))
        return int(rows[0][0]) if rows else 0

    def progress(self, media, tmdb_id=None, show=None, season=None, episode=None):
        """(percent watched, playback ID) of a saved resume point, or (0, None)."""
        if media == "episode":
            rows = self.store.query("SELECT value, extra FROM library WHERE part = 'playback' AND media = 'episode' "
                                    "AND show_tmdb_id = ? AND season = ? AND episode = ?", (show, season, episode))
        else:
            rows = self.store.query("SELECT value, extra FROM library WHERE part = 'playback' AND media = 'movie' "
                                    "AND tmdb_id = ?", (tmdb_id,))
        if not rows:
            return 0, None
        extra = json.loads(rows[0][1] or "{}")
        return float(rows[0][0] or 0), extra.get("playback_id")

    def in_progress(self, media):
        """Films, or (show, season, episode) triples, with a resume point, newest first."""
        if media == "movie":
            return self.ids("playback", "movie")
        rows = self.store.query("SELECT show_tmdb_id, season, episode FROM library WHERE part = 'playback' "
                                "AND media = 'episode' ORDER BY at DESC")
        return [tuple(r) for r in rows]
