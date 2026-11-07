# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Builds the shared services (database, HTTP, TMDB, extras) from settings and keys."""

import json
import os

from resources.lib import artwork, kodi
from resources.lib.database import Store
from resources.lib.extras import Fanart, Omdb
from resources.lib.http import Http
from resources.lib.strings import LANGUAGES
from resources.lib.tmdb import Tmdb, TmdbError

DB_NAME = "spongetv.db"


def builtin_keys():
    """Keys added to the zip at build time (never stored in the public repository)."""
    path = os.path.join(os.path.dirname(__file__), "_keys.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


class App:
    def __init__(self):
        self.store = Store(os.path.join(kodi.ensure_profile(), DB_NAME))
        self.http = Http(f"SpongeTV/{kodi.VERSION}")
        self._keys = builtin_keys()
        self._tmdb = None

    def key(self, name):
        """Your own key from Settings wins over the built-in one."""
        return kodi.setting_str(f"{name}.api_key").strip() or self._keys.get(name, "")

    @property
    def language(self):
        index = kodi.setting_int("metadata.language")
        code = LANGUAGES[index][0] if 0 <= index < len(LANGUAGES) else ""
        return code or kodi.kodi_language()

    @property
    def region(self):
        parts = self.language.split("-")
        return parts[1] if len(parts) > 1 else None

    @property
    def preset(self):
        """A preset index, or for Advanced a size table built from its own settings."""
        index = kodi.setting_int("artwork.preset")
        if index != artwork.ADVANCED:
            return index
        return artwork.advanced(kodi.setting_int("artwork.poster_size"), kodi.setting_int("artwork.fanart_size"),
                                kodi.setting_int("artwork.still_size"), kodi.setting_bool("artwork.extras"))

    @property
    def tmdb(self):
        if self._tmdb is None:
            key = self.key("tmdb")
            if not key:
                raise TmdbError("No TMDB API key")
            self._tmdb = Tmdb(key, self.http, self.store, language=self.language, region=self.region)
        return self._tmdb

    @property
    def fanart(self):
        return Fanart(self.key("fanart"), self.http, self.store)

    @property
    def omdb(self):
        return Omdb(self.key("omdb"), self.http, self.store)
