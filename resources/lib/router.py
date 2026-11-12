"""Routes a plugin call to the matching action."""

import importlib

from resources.lib import kodi
from resources.lib.plugin import Plugin

# Each action and where it lives, as "module.function" under resources/lib. The module is only loaded when
# its action runs: Kodi starts SpongeTV afresh for every list, and on an NVIDIA Shield loading everything
# (playback, source search, provider packages...) cost most of the time a plain menu took to open.
ACTIONS = {
    "home": "menus.home",
    "movies": "menus.movies",
    "tv": "menus.tv",
    "movie_list": "menus.movie_list",
    "tv_list": "menus.tv_list",
    "genres": "menus.genres",
    "genre": "menus.genre",
    "years": "menus.years",
    "year": "menus.year",
    "new_shows": "menus.new_shows",
    "networks": "menus.networks",
    "network": "menus.network",
    "providers": "menus.providers",
    "provider": "menus.provider",
    "set_sort": "menus.set_sort",
    "related": "menus.related",
    "cast": "menus.cast",
    "search_menu": "search.search_menu",
    "new_search": "search.new_search",
    "search": "search.search",
    "search_results": "search.search_results",
    "person": "search.person",
    "person_titles": "search.person_titles",
    "seasons": "shows.seasons",
    "episodes": "shows.episodes",
    "all_episodes": "shows.all_episodes",
    "my_movies": "mine.my_movies",
    "my_tv": "mine.my_tv",
    "library_titles": "mine.library_titles",
    "shows_in_progress": "mine.shows_in_progress",
    "next_up": "mine.next_up",
    "calendar": "mine.calendar",
    "recommended": "mine.recommended",
    "trakt_lists": "mine.trakt_lists",
    "lists": "mine.lists",
    "list_items": "mine.list_items",
    "create_list": "mine.create_list",
    "rename_list": "mine.rename_list",
    "trakt_menu": "actions.menu",
    "trakt_sign_in": "tools.trakt_sign_in",
    "trakt_sign_out": "tools.trakt_sign_out",
    "tools_sync": "tools.sync_menu",
    "sync_now": "tools.sync_now",
    "sync_forget": "tools.sync_forget",
    "sync_rebuild": "tools.sync_rebuild",
    "play": "choose.play",
    "play_show": "playback.play_show",
    "clear_resume": "actions.clear_resume",
    "save_view": "views.save_view",
    "reset_views": "views.reset_views",
    "tools_providers": "providers_menu.menu",
    "providers_open": "tools.open_providers",
    "premiumize_status": "tools.premiumize_status",
    "premiumize_sign_in": "tools.premiumize_sign_in",
    "premiumize_sign_out": "tools.premiumize_sign_out",
    "install_url": "providers_menu.install_url",
    "install_zip": "providers_menu.install_zip",
    "install_test": "providers_menu.install_test",
    "packages": "providers_menu.package_list",
    "package": "providers_menu.package",
    "providers_all": "providers_menu.providers_all",
    "provider_toggle": "providers_menu.provider_toggle",
    "package_toggle": "providers_menu.package_toggle",
    "package_settings": "providers_menu.package_settings",
    "package_update": "providers_menu.package_update",
    "package_updates": "providers_menu.package_updates",
    "package_rollback": "providers_menu.package_rollback",
    "package_uninstall": "providers_menu.package_uninstall",
    "sort_rules": "choose.sort_rules_action",
    "clear_results": "choose.clear_results",
    "window_test": "choose.window_test",
    "tools": "tools.menu",
    "tools_accounts": "tools.accounts_menu",
    "tools_caches": "tools.caches",
    "clear_cache": "tools.clear_cache",
    "clear_search": "tools.clear_search",
    "clear_all": "tools.clear_all",
    "home_menu_edit": "tools.edit_home_menu",
    "wizard": "tools.run_wizard",
    "clean_install": "tools.clean_install",
    "settings": "tools.open_settings",
}

# Actions run from a non-folder item: they do something and don't produce a listing.
NOT_DIRECTORIES = {"play", "new_search", "set_sort", "clear_cache", "clear_search", "clear_all",
                   "home_menu_edit", "wizard", "clean_install", "settings", "create_list", "rename_list",
                   "trakt_menu", "trakt_sign_in", "trakt_sign_out", "sync_now", "sync_forget", "sync_rebuild",
                   "providers_open", "clear_resume", "save_view", "reset_views", "premiumize_status", "premiumize_sign_in", "premiumize_sign_out", "install_url", "install_zip", "install_test", "providers_all", "provider_toggle",
                   "package_toggle", "package_settings", "package_update", "package_updates", "package_rollback",
                   "package_uninstall", "sort_rules", "clear_results", "window_test"}
DIRECTORY_ACTIONS = set(ACTIONS) - NOT_DIRECTORIES


def handler_for(action):
    """The function for an action, loading its module now; None for an action SpongeTV doesn't have."""
    where = ACTIONS.get(action)
    if where is None:
        return None
    module, name = where.split(".")
    return getattr(importlib.import_module(f"resources.lib.{module}"), name)


def dispatch(argv):
    plugin = Plugin(argv)
    handler = handler_for(plugin.action)
    if handler is None:
        kodi.log_error(f"Unknown action: {plugin.action}")
        plugin.fail()
        return
    from resources.lib.context import App
    from resources.lib.http import HttpError
    from resources.lib.tmdb import TmdbError
    from resources.lib.trakt import TraktError
    app = App()
    try:
        if plugin.action == "home":
            from resources.lib import wizard
            if wizard.needed(app):
                wizard.run(app)
        handler(plugin, app)
    except TmdbError:
        kodi.notify(kodi.text("no_tmdb_key"))
        _fail(plugin)
    except TraktError as error:
        from resources.lib import accounts
        kodi.log_error(f"{plugin.action} failed: {error}")
        kodi.notify(accounts.message(error))
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
