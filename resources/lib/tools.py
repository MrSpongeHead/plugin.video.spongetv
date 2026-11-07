# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Tools menu, grouped: Accounts, Caches, Home menu, Clean install, Settings.

Trakt sync tools and provider tools join their own groups in later stages."""

import os

import xbmc
import xbmcgui

from resources.lib import kodi, listing, options, wizard
from resources.lib.context import DB_NAME


def _item(plugin, label_key, action, is_folder=False):
    return plugin.url(action=action), listing.folder_item(kodi.text(label_key), kodi.ICON, kodi.FANART), is_folder


def menu(plugin, app):
    items = [
        _item(plugin, "tools_accounts", "tools_accounts", True),
        _item(plugin, "tools_caches", "tools_caches", True),
        _item(plugin, "customise_home", "home_menu_edit"),
        _item(plugin, "clean_install", "clean_install"),
        _item(plugin, "settings", "settings"),
    ]
    plugin.finish(items, category=kodi.text("tools"), cache=False)


def accounts(plugin, app):
    items = [_item(plugin, "run_wizard", "wizard"), _item(plugin, "settings", "settings")]
    plugin.finish(items, category=kodi.text("tools_accounts"), cache=False)


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
    """Every cache SpongeTV keeps. Later stages add their caches (provider results etc.) here."""
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
