# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""User choices that shape menus: display style, per-menu hiding, sorting and the home menu."""

import json

from resources.lib import kodi

# -- display ---------------------------------------------------------------------------
EPISODE_TITLE, EPISODE_1X01, EPISODE_S01E01 = 0, 1, 2

# Highlight colours for special items (Next page, Sort, search groups). Index = setting value.
HIGHLIGHTS = ["FFF5A524", "FF2EC4B6", "FFDFFAF6", "FF6FA8FF", "FFFFFFFF", ""]


class Display:
    """How titles are shown. (A plain class: Python's dataclasses took a while to load on every list.)"""

    def __init__(self, region="GB", original_titles=False, one_studio=True, episode_style=EPISODE_TITLE):
        self.region = region
        self.original_titles = original_titles
        self.one_studio = one_studio
        self.episode_style = episode_style


def display(app):
    return Display(
        region=app.region or "GB",
        original_titles=kodi.setting_bool("metadata.original_titles"),
        one_studio=not kodi.setting_bool("display.all_studios"),
        episode_style=kodi.setting_int("display.episode_label"),
    )


def highlight(text):
    index = kodi.setting_int("display.highlight")
    colour = HIGHLIGHTS[index] if 0 <= index < len(HIGHLIGHTS) else HIGHLIGHTS[0]
    return f"[COLOR {colour}]{text}[/COLOR]" if colour else text


# -- hiding, set separately for each kind of menu -----------------------------------------
# (menu, what) -> setting id. Defaults live in settings.xml.
HIDE = {
    ("movie_lists", "unreleased"): "hide.movie_lists.unreleased",
    ("tv_lists", "unaired"): "hide.tv_lists.unaired",
    ("search", "unreleased"): "hide.search.unreleased",
    ("seasons", "specials"): "hide.seasons.specials",
    ("seasons", "unaired"): "hide.seasons.unaired",
    ("episodes", "unaired"): "hide.episodes.unaired",
    # Stage 2: watched items (needs a Trakt sign-in)
    ("movie_lists", "watched"): "hide.movie_lists.watched",
    ("tv_lists", "watched"): "hide.tv_lists.watched",
    ("search", "watched"): "hide.search.watched",
    ("seasons", "watched"): "hide.seasons.watched",
    ("episodes", "watched"): "hide.episodes.watched",
}


def hidden(menu, what):
    setting = HIDE.get((menu, what))
    return bool(setting) and kodi.setting_bool(setting)


# -- sorting, remembered for each list ----------------------------------------------------
SORTS = {
    "movie": [("popularity.desc", "sort_popularity"), ("vote_average.desc", "sort_rating"),
              ("primary_release_date.desc", "sort_newest"), ("title.asc", "sort_title")],
    "tv": [("popularity.desc", "sort_popularity"), ("vote_average.desc", "sort_rating"),
           ("first_air_date.desc", "sort_newest"), ("name.asc", "sort_title")],
}
DEFAULT_SORT = "popularity.desc"


def sort_for(store, list_key, media):
    chosen = store.get_meta(f"sort:{list_key}")
    return chosen if chosen in dict(SORTS[media]) else DEFAULT_SORT


def set_sort(store, list_key, value):
    store.set_meta(f"sort:{list_key}", value)


def sort_label(media, value):
    return kodi.text(dict(SORTS[media]).get(value, "sort_popularity"))


# -- home menu --------------------------------------------------------------------------
# key -> (string key, action). Tools can't be hidden, so there's always a way back to settings.
HOME_ITEMS = {
    "movies": ("movies", "movies"),
    "tv": ("tv_shows", "tv"),
    "my_movies": ("my_movies", "my_movies"),
    "my_tv": ("my_tv", "my_tv"),
    "trakt_lists": ("trakt_lists", "trakt_lists"),
    "search": ("search", "search_menu"),
    "tools": ("tools", "tools"),
}
HOME_DEFAULT = ["movies", "tv", "my_movies", "my_tv", "trakt_lists", "search", "tools"]
NEEDS_SIGN_IN = {"my_movies", "my_tv"}      # shown only when you're signed in to Trakt
NEEDS_TRAKT_APP = {"trakt_lists"}           # public lists work with just a Client ID
ALWAYS_SHOWN = {"tools"}


def home_layout(store):
    """(order, hidden) with any new items appended, unknown ones dropped."""
    try:
        saved = json.loads(store.get_meta("home_menu") or "{}")
    except ValueError:
        saved = {}
    order = [k for k in saved.get("order", []) if k in HOME_ITEMS]
    order += [k for k in HOME_DEFAULT if k not in order]
    hidden_items = {k for k in saved.get("hidden", []) if k in HOME_ITEMS and k not in ALWAYS_SHOWN}
    return order, hidden_items


def save_home_layout(store, order, hidden_items):
    store.set_meta("home_menu", json.dumps({"order": order, "hidden": sorted(hidden_items)}))


def reset_home_layout(store):
    store.set_meta("home_menu", "")
