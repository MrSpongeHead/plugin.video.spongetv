# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""TMDB (API v3) client: lists, search, details and seasons, cached locally."""

import datetime
import hashlib
import json

from resources.lib.http import HttpError

BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/"

HOUR = 3600
NOT_FOUND = {"spongetv": "not found on TMDB"}
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
            if cached == NOT_FOUND:
                raise HttpError(f"HTTP 404 from {BASE + path} (TMDB's answer earlier today)", 404)
            if cached is not None:
                return cached
        try:
            data = self.http.get_json(BASE + path, params=dict(query, api_key=self.api_key))
        except HttpError as error:
            # TMDB has nothing at this address (a show it has removed, say): don't ask again on every visit
            if error.status == 404 and self.store is not None and ttl:
                self.store.cache_set(cache_key, NOT_FOUND, DAY)
            raise
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

    def discover(self, media, page=1, sort_by="popularity.desc", filters=None):
        """Discover with any TMDB filters. Sorting by rating ignores titles with few votes, and
        sorting by date ignores far-future placeholders. If TMDB rejects a sort, fall back to popularity."""
        params = {"page": page, "sort_by": sort_by}
        params.update({k: v for k, v in (filters or {}).items() if v not in (None, "")})
        if sort_by.startswith("vote_average"):
            params.setdefault("vote_count.gte", 200 if media == "movie" else 100)
        if sort_by.startswith(("primary_release_date", "first_air_date")):
            key = "primary_release_date.lte" if media == "movie" else "first_air_date.lte"
            params.setdefault(key, self._today().isoformat())
        try:
            return self._get(f"/discover/{media}", params)
        except HttpError as error:
            if sort_by == "popularity.desc" or error.status not in (400, 422):
                raise
            return self.discover(media, page, "popularity.desc", filters)

    def search(self, media, query, page=1):
        """media: movie, tv or person."""
        return self._get(f"/search/{media}", {"query": query, "page": page}, ttl=HOUR)

    def recommendations(self, media, tmdb_id, page=1):
        """TMDB's recommendations, or similar titles when it has none."""
        data = self._get(f"/{media}/{tmdb_id}/recommendations", {"page": page}, ttl=DAY)
        if page == 1 and not data.get("results"):
            data = self._get(f"/{media}/{tmdb_id}/similar", {"page": page}, ttl=DAY)
        return data

    def network(self, network_id):
        return self._get(f"/network/{network_id}", ttl=30 * DAY)

    def watch_providers(self, media, region):
        """Streaming services available in a region, in TMDB's display order for that region."""
        data = self._get(f"/watch/providers/{media}", {"watch_region": region}, ttl=7 * DAY)
        providers = data.get("results", [])

        def order(provider):
            return (provider.get("display_priorities") or {}).get(region, provider.get("display_priority", 999))
        return sorted(providers, key=order)

    def person(self, person_id):
        data = self._get(f"/person/{person_id}", {"append_to_response": "movie_credits,tv_credits"}, ttl=7 * DAY)
        return self._with_english_fallback(f"/person/{person_id}", data, ("biography",))

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
        params = self._tv_params()
        data = self._get(f"/tv/{tv_id}", params, ttl=DAY)
        data = self._with_english_fallback(f"/tv/{tv_id}", data, ("overview", "tagline"))
        if not data.get("in_production") and self.store is not None:
            self._refresh_ttl(f"/tv/{tv_id}", params, data, 14 * DAY)
        return data

    def tv_facts(self, tv_id):
        """The few facts Next up and Shows in progress need about a show, kept beside its full details and
        for exactly as long, so a list over every show you've watched needn't read each one in full."""
        if self.store is None:
            return _facts(self.tv(tv_id))
        key = f"tmdb:facts:{self.language}:{tv_id}"
        facts = self.store.cache_get(key)
        if facts is None:
            details = self.tv(tv_id)
            facts = _facts(details)
            left = self.store.cache_time_left(self._cache_key(f"/tv/{tv_id}", self._query(self._tv_params())))
            self.store.cache_set(key, facts, max(left, HOUR))
        return facts

    def forget_movie(self, movie_id):
        self._forget(f"/movie/{movie_id}", {"append_to_response": "credits,images,external_ids,release_dates",
                                             "include_image_language": self._image_languages()})

    def forget_tv(self, tv_id):
        self._forget(f"/tv/{tv_id}", self._tv_params())
        if self.store is not None:
            self.store.cache_delete(f"tmdb:facts:{self.language}:{tv_id}")

    def _tv_params(self):
        return {"append_to_response": "credits,images,external_ids,content_ratings",
                "include_image_language": self._image_languages()}

    def _forget(self, path, params):
        if self.store is not None:
            self.store.cache_delete(self._cache_key(path, self._query(params)))
            self.store.cache_delete(self._cache_key(path, self._query(None, "en-US")))

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
        """Keep a title that rarely changes for longer. Done once, when it has just been fetched (so it still
        has a day or less to run): rewriting it on every read would cost time and stop it ever being refreshed."""
        key = self._cache_key(path, self._query(params))
        if self.store.cache_time_left(key) <= DAY:
            self.store.cache_set(key, data, ttl)


def _facts(details):
    last = details.get("last_episode_to_air") or {}
    return {
        "id": details.get("id"),
        "name": details.get("name"),
        "last_air_date": details.get("last_air_date"),
        "last_episode_to_air": {"season_number": last.get("season_number"),
                                "episode_number": last.get("episode_number")} if last else None,
        "seasons": [{"season_number": s.get("season_number"), "episode_count": s.get("episode_count")}
                    for s in details.get("seasons") or []],
    }


def image_url(path, size="original"):
    return f"{IMAGE_BASE}{size}{path}" if path else ""


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None
