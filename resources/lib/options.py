# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""User choices that shape menus: display style, per-menu hiding, sorting and the home menu."""

import json
from dataclasses import dataclass

from resources.lib import kodi

# -- display ---------------------------------------------------------------------------
EPISODE_TITLE, EPISODE_1X01, EPISODE_S01E01 = 0, 1, 2

# Highlight colours for special items (Next page, Sort, search groups). Index = setting value.
HIGHLIGHTS = ["FFF5A524", "FF2EC4B6", "FFDFFAF6", "FF6FA8FF", "FFFFFFFF", ""]


@dataclass
class Display:
    region: str = "GB"
    original_titles: bool = False
    one_studio: bool = True
    episode_style: int = EPISODE_TITLE


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
    "search": ("search", "search_menu"),
    "tools": ("tools", "tools"),
}
HOME_DEFAULT = ["movies", "tv", "search", "tools"]
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
