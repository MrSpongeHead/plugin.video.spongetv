# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Routes a plugin call to the matching action."""

from resources.lib import kodi, menus, tools, wizard
from resources.lib.context import App
from resources.lib.http import HttpError
from resources.lib.plugin import Plugin
from resources.lib.tmdb import TmdbError

ACTIONS = {
    "home": menus.home,
    "movies": menus.movies,
    "tv": menus.tv,
    "search_home": menus.search_home,
    "movie_list": menus.movie_list,
    "tv_list": menus.tv_list,
    "genres": menus.genres,
    "genre": menus.genre,
    "years": menus.years,
    "year": menus.year,
    "search_menu": menus.search_menu,
    "search": menus.search,
    "new_search": menus.new_search,
    "seasons": menus.seasons,
    "episodes": menus.episodes,
    "all_episodes": menus.all_episodes,
    "play": menus.play,
    "tools": tools.menu,
    "clear_cache": tools.clear_cache,
    "clear_search": tools.clear_search,
    "wizard": tools.run_wizard,
    "clean_install": tools.clean_install,
    "settings": tools.open_settings,
}

# Actions that produce a directory listing (and so must end it, even on failure).
DIRECTORY_ACTIONS = set(ACTIONS) - {"play", "new_search", "clear_cache", "clear_search", "wizard", "clean_install", "settings"}


def dispatch(argv):
    plugin = Plugin(argv)
    handler = ACTIONS.get(plugin.action)
    if handler is None:
        kodi.log_error(f"Unknown action: {plugin.action}")
        plugin.fail()
        return
    app = App()
    try:
        if plugin.action == "home" and wizard.needed(app):
            wizard.run(app)
        handler(plugin, app)
    except TmdbError:
        kodi.notify(kodi.text("no_tmdb_key"))
        _fail(plugin)
    except HttpError as error:
        kodi.log_error(f"{plugin.action} failed: {error}")
        kodi.notify(kodi.text("tmdb_unreachable"))
        _fail(plugin)


def _fail(plugin):
    if plugin.action in DIRECTORY_ACTIONS:
        plugin.fail()
    elif plugin.action == "play":
        plugin.resolve_nothing()
