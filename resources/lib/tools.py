# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Tools menu, grouped: Accounts, Caches, Home menu, Clean install, Settings.

Trakt sync tools and provider tools join their own groups in later stages."""

import os

import xbmc
import xbmcgui

from resources.lib import accounts, kodi, listing, options, wizard
from resources.lib.context import DB_NAME


def _item(plugin, label_key, action, is_folder=False):
    return plugin.url(action=action), listing.folder_item(kodi.text(label_key), kodi.ICON, kodi.FANART), is_folder


def menu(plugin, app):
    items = [
        _item(plugin, "tools_accounts", "tools_accounts", True),
        _item(plugin, "tools_sync", "tools_sync", True),
        _item(plugin, "tools_providers", "tools_providers", True),
        _item(plugin, "tools_caches", "tools_caches", True),
        _item(plugin, "customise_home", "home_menu_edit"),
        _item(plugin, "clean_install", "clean_install"),
        _item(plugin, "settings", "settings"),
    ]
    if kodi.setting_bool("developer.window_tests"):
        items.append((plugin.url(action="window_test", window="select"),
                      listing.folder_item(kodi.text("window_test_select"), kodi.ICON, kodi.FANART), False))
        items.append((plugin.url(action="window_test", window="search"),
                      listing.folder_item(kodi.text("window_test_search"), kodi.ICON, kodi.FANART), False))
        items.append((plugin.url(action="window_test", window="live"),
                      listing.folder_item(kodi.text("window_test_live"), kodi.ICON, kodi.FANART), False))
    plugin.finish(items, category=kodi.text("tools"), cache=False)


def accounts_menu(plugin, app):
    if app.signed_in:
        name = kodi.setting_str("trakt.username")
        label = kodi.text("trakt_sign_out_as", name=name) if name else kodi.text("trakt_sign_out")
        trakt_item = (plugin.url(action="trakt_sign_out"), listing.folder_item(label, kodi.ICON, kodi.FANART), False)
    else:
        trakt_item = _item(plugin, "trakt_sign_in", "trakt_sign_in")
    items = [trakt_item, _item(plugin, "run_wizard", "wizard"), _item(plugin, "settings", "settings")]
    plugin.finish(items, category=kodi.text("tools_accounts"), cache=False)


def sync_menu(plugin, app):
    if not app.signed_in:
        items = [_item(plugin, "trakt_sign_in", "trakt_sign_in")]
        plugin.finish(items, category=kodi.text("tools_sync"), cache=False)
        return
    last, error = accounts.syncer(app).status()
    status = kodi.text("sync_last", when=last) if last else kodi.text("sync_never")
    if error:
        status += "  " + kodi.text("sync_last_error", error=accounts.message_for(error))
    items = [_item(plugin, "sync_now", "sync_now"),
             (plugin.url(action="tools_sync"), listing.folder_item(status, kodi.ICON, kodi.FANART), True),
             _item(plugin, "sync_forget", "sync_forget"),
             _item(plugin, "sync_rebuild", "sync_rebuild")]
    plugin.finish(items, category=kodi.text("tools_sync"), cache=False)


def trakt_sign_in(plugin, app):
    if accounts.sign_in(app):
        xbmc.executebuiltin("Container.Refresh")


def trakt_sign_out(plugin, app):
    accounts.sign_out(app)


def sync_now(plugin, app):
    accounts.run_sync(app, visible=True)
    xbmc.executebuiltin("Container.Refresh")


def sync_forget(plugin, app):
    accounts.syncer(app).forget()
    kodi.notify(kodi.text("sync_forgotten"))


def sync_rebuild(plugin, app):
    if not xbmcgui.Dialog().yesno("SpongeTV", kodi.text("sync_rebuild_confirm")):
        return
    app.library.clear()
    accounts.syncer(app).forget()
    accounts.run_sync(app, force=True, visible=True)
    xbmc.executebuiltin("Container.Refresh")


def caches(plugin, app):
    items = [_item(plugin, "clear_cache", "clear_cache"),
             _item(plugin, "clear_search_history", "clear_search"),
             _item(plugin, "clear_all_caches", "clear_all")]
    plugin.finish(items, category=kodi.text("tools_caches"), cache=False)


def clear_cache(plugin, app):
    app.store.cache_clear()
    kodi.notify(kodi.text("cache_cleared"))


def clear_search(plugin, app):
    app.store.clear_searches()
    kodi.notify(kodi.text("search_cleared"))
    xbmc.executebuiltin("Container.Refresh")


def clear_all(plugin, app):
    """Every cache SpongeTV keeps (Trakt lists and calendars live in the main cache). Later stages
    add their caches (provider results etc.) here. Your Trakt library isn't a cache: see Sync."""
    app.store.cache_clear()
    app.store.clear_searches()
    kodi.notify(kodi.text("all_caches_cleared"))


def run_wizard(plugin, app):
    wizard.run(app)


def open_settings(plugin, app):
    kodi.ADDON.openSettings()


def edit_home_menu(plugin, app):
    """Pick an item, then move it up or down, or hide or show it. Repeats until you back out."""
    dialog = xbmcgui.Dialog()
    order, hidden_items = options.home_layout(app.store)
    selected = 0
    while True:
        rows = []
        for key in order:
            name = kodi.text(options.HOME_ITEMS[key][0])
            rows.append(kodi.text("home_hidden_row", name=name) if key in hidden_items else name)
        rows.append(kodi.text("home_reset"))
        choice = dialog.select(kodi.text("customise_home"), rows, preselect=selected)
        if choice < 0:
            break
        if choice == len(order):
            options.reset_home_layout(app.store)
            order, hidden_items = options.home_layout(app.store)
            continue
        key = order[choice]
        actions = [kodi.text("move_up"), kodi.text("move_down")]
        if key not in options.ALWAYS_SHOWN:
            actions.append(kodi.text("show_item") if key in hidden_items else kodi.text("hide_item"))
        action = dialog.select(kodi.text(options.HOME_ITEMS[key][0]), actions)
        selected = choice
        if action == 0 and choice > 0:
            order[choice - 1], order[choice] = order[choice], order[choice - 1]
            selected = choice - 1
        elif action == 1 and choice < len(order) - 1:
            order[choice + 1], order[choice] = order[choice], order[choice + 1]
            selected = choice + 1
        elif action == 2:
            hidden_items.symmetric_difference_update({key})
        options.save_home_layout(app.store, order, hidden_items)
    xbmc.executebuiltin("Container.Refresh")


def clean_install(plugin, app):
    dialog = xbmcgui.Dialog()
    if not dialog.yesno("SpongeTV", kodi.text("clean_install_confirm")):
        return
    keep = dialog.yesno("SpongeTV", kodi.text("clean_install_keep"),
                        nolabel=kodi.text("remove"), yeslabel=kodi.text("keep"))
    app.store.close()
    for name in os.listdir(kodi.PROFILE):
        if name.startswith(DB_NAME) or (not keep and name == "settings.xml"):
            try:
                os.remove(os.path.join(kodi.PROFILE, name))
            except OSError as error:
                kodi.log_error(f"Clean install could not remove {name}: {error}")
    dialog.ok("SpongeTV", kodi.text("clean_install_done"))


def open_providers(plugin, app):
    """From Settings: open Tools, Providers and sources."""
    xbmc.executebuiltin("ActivateWindow(Videos,plugin://plugin.video.spongetv/?action=tools_providers,return)")
