# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Checks API keys with each service. True = accepted, False = rejected, None = couldn't check."""

import hashlib

from resources.lib.http import HttpError

TMDB_CHECK = "https://api.themoviedb.org/3/configuration"
FANART_CHECK = "https://webservice.fanart.tv/v3/movies/603"   # The Matrix: always present
OMDB_CHECK = "https://www.omdbapi.com/"

SERVICES = {"tmdb": "TMDB", "fanart": "Fanart.tv", "omdb": "OMDb"}


def _check(http, url, params):
    try:
        data = http.get_json(url, params=params)
    except HttpError as error:
        return False if error.status in (401, 403) else None
    if isinstance(data, dict) and data.get("Response") == "False" and "key" in str(data.get("Error", "")).lower():
        return False   # OMDb sometimes reports a bad or unactivated key in the body
    return True


def check(name, http, key):
    if name == "tmdb":
        return _check(http, TMDB_CHECK, {"api_key": key})
    if name == "fanart":
        return _check(http, FANART_CHECK, {"api_key": key})
    if name == "omdb":
        return _check(http, OMDB_CHECK, {"apikey": key, "i": "tt0133093"})
    raise ValueError(name)


def looks_like_read_token(value):
    """The long TMDB 'API Read Access Token' (starts eyJ...) is not the short v3 API key we need."""
    return value.startswith("eyJ") or len(value) > 40


def fingerprint(key):
    return hashlib.sha1(key.encode("utf-8")).hexdigest()
