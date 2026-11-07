# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""TMDB (API v3) client: lists, search, details and seasons, cached locally."""

import datetime
import hashlib
import json

BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/"

HOUR = 3600
DAY = 24 * HOUR

MOVIE_LISTS = {
    "trending": "/trending/movie/week",
    "popular": "/movie/popular",
    "top_rated": "/movie/top_rated",
    "now_playing": "/movie/now_playing",
    "upcoming": "/movie/upcoming",
}
TV_LISTS = {
    "trending": "/trending/tv/week",
    "popular": "/tv/popular",
    "top_rated": "/tv/top_rated",
    "airing_today": "/tv/airing_today",
    "on_the_air": "/tv/on_the_air",
}


class TmdbError(Exception):
    pass


class Tmdb:
    def __init__(self, api_key, http, store=None, language="en-GB", region="GB", today=None):
        if not api_key:
            raise TmdbError("No TMDB API key")
        self.api_key = api_key
        self.http = http
        self.store = store
        self.language = language or "en-GB"
        self.region = region
        self._today = today or datetime.date.today

    # -- low level ---------------------------------------------------------------
    def _query(self, params, language=None):
        query = {"language": language or self.language}
        query.update(params or {})
        return query

    @staticmethod
    def _cache_key(path, query):
        return "tmdb:" + hashlib.sha1((path + json.dumps(query, sort_keys=True)).encode("utf-8")).hexdigest()

    def _get(self, path, params=None, ttl=6 * HOUR, language=None):
        query = self._query(params, language)
        cache_key = self._cache_key(path, query)
        if self.store is not None:
            cached = self.store.cache_get(cache_key)
            if cached is not None:
                return cached
        data = self.http.get_json(BASE + path, params=dict(query, api_key=self.api_key))
        if self.store is not None and ttl:
            self.store.cache_set(cache_key, data, ttl)
        return data

    # -- lists and search -----------------------------------------------------------
    def movie_list(self, kind, page=1):
        params = {"page": page}
        if kind in ("now_playing", "upcoming") and self.region:
            params["region"] = self.region
        return self._get(MOVIE_LISTS[kind], params)

    def tv_list(self, kind, page=1):
        return self._get(TV_LISTS[kind], {"page": page})

    def genres(self, media):
        return self._get(f"/genre/{media}/list", ttl=7 * DAY).get("genres", [])

    def discover(self, media, page=1, genre=None, year=None):
        params = {"page": page, "sort_by": "popularity.desc"}
        if genre:
            params["with_genres"] = genre
        if year:
            params["primary_release_year" if media == "movie" else "first_air_date_year"] = year
        return self._get(f"/discover/{media}", params)

    def search(self, media, query, page=1):
        return self._get(f"/search/{media}", {"query": query, "page": page}, ttl=HOUR)

    # -- details -----------------------------------------------------------------
    def movie(self, movie_id):
        params = {
            "append_to_response": "credits,images,external_ids,release_dates",
            "include_image_language": self._image_languages(),
        }
        data = self._get(f"/movie/{movie_id}", params, ttl=DAY)
        data = self._with_english_fallback(f"/movie/{movie_id}", data, ("overview", "tagline"))
        released = _parse_date(data.get("release_date"))
        if released and (self._today() - released).days > 365 and self.store is not None:
            # Older films rarely change: keep them for a month.
            self._refresh_ttl(f"/movie/{movie_id}", params, data, 30 * DAY)
        return data

    def tv(self, tv_id):
        params = {
            "append_to_response": "credits,images,external_ids,content_ratings",
            "include_image_language": self._image_languages(),
        }
        data = self._get(f"/tv/{tv_id}", params, ttl=DAY)
        data = self._with_english_fallback(f"/tv/{tv_id}", data, ("overview", "tagline"))
        if not data.get("in_production") and self.store is not None:
            self._refresh_ttl(f"/tv/{tv_id}", params, data, 14 * DAY)
        return data

    def season(self, tv_id, season_number):
        return self._get(f"/tv/{tv_id}/season/{season_number}", ttl=DAY)

    # -- helpers -------------------------------------------------------------------
    def _image_languages(self):
        lang = self.language.split("-")[0]
        return ",".join(dict.fromkeys([lang, "en", "null"]))

    def _with_english_fallback(self, path, data, fields):
        """Fill empty translated fields from the English version."""
        if self.language.startswith("en") or all(data.get(f) for f in fields):
            return data
        english = self._get(path, ttl=7 * DAY, language="en-US")
        for field in fields:
            if not data.get(field):
                data[field] = english.get(field, "")
        return data

    def _refresh_ttl(self, path, params, data, ttl):
        self.store.cache_set(self._cache_key(path, self._query(params)), data, ttl)


def image_url(path, size="original"):
    return f"{IMAGE_BASE}{size}{path}" if path else ""


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None
