# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Optional extras: Fanart.tv artwork and OMDb ratings. Both are skipped without a key."""

from resources.lib.http import HttpError

FANART_BASE = "https://webservice.fanart.tv/v3"
OMDB_BASE = "https://www.omdbapi.com/"
WEEK = 7 * 24 * 3600


class Fanart:
    def __init__(self, api_key, http, store=None):
        self.api_key = api_key
        self.http = http
        self.store = store

    def movie(self, tmdb_id):
        return self._fetch(f"/movies/{tmdb_id}", f"fanart:movie:{tmdb_id}")

    def tv(self, tvdb_id):
        # Fanart.tv indexes TV shows by TVDB ID, which TMDB supplies in external_ids.
        return self._fetch(f"/tv/{tvdb_id}", f"fanart:tv:{tvdb_id}") if tvdb_id else {}

    def _fetch(self, path, cache_key):
        if not self.api_key:
            return {}
        if self.store is not None:
            cached = self.store.cache_get(cache_key)
            if cached is not None:
                return cached
        try:
            data = self.http.get_json(FANART_BASE + path, params={"api_key": self.api_key})
        except HttpError:
            data = {}  # not found or service down: just no extra artwork
        if self.store is not None:
            self.store.cache_set(cache_key, data, WEEK)
        return data


class Omdb:
    def __init__(self, api_key, http, store=None):
        self.api_key = api_key
        self.http = http
        self.store = store

    def ratings(self, imdb_id):
        """{'imdb': (rating, votes), 'tomatometerallcritics': (rating, 0), 'metacritic': (rating, 0)}."""
        if not self.api_key or not imdb_id:
            return {}
        cache_key = f"omdb:{imdb_id}"
        data = self.store.cache_get(cache_key) if self.store is not None else None
        if data is None:
            try:
                data = self.http.get_json(OMDB_BASE, params={"i": imdb_id, "apikey": self.api_key})
            except HttpError:
                data = {}
            if self.store is not None:
                self.store.cache_set(cache_key, data, WEEK)  # ratings change slowly
        return parse_omdb_ratings(data)


def parse_omdb_ratings(data):
    ratings = {}
    try:
        votes = int(str(data.get("imdbVotes", "0")).replace(",", ""))
    except ValueError:
        votes = 0
    for item in data.get("Ratings", []) or []:
        source, value = item.get("Source", ""), item.get("Value", "")
        try:
            if source == "Internet Movie Database":
                ratings["imdb"] = (float(value.split("/")[0]), votes)
            elif source == "Rotten Tomatoes":
                ratings["tomatometerallcritics"] = (float(value.rstrip("%")) / 10, 0)
            elif source == "Metacritic":
                ratings["metacritic"] = (float(value.split("/")[0]) / 10, 0)
        except ValueError:
            continue
    return ratings
