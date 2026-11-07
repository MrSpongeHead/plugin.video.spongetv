# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Tools menu: clear caches, search history, setup wizard, clean install, settings."""

import os

import xbmc
import xbmcgui

from resources.lib import kodi, listing, wizard
from resources.lib.context import DB_NAME


def menu(plugin, app):
    entries = [
        ("clear_cache", "clear_cache"),
        ("clear_search_history", "clear_search"),
        ("run_wizard", "wizard"),
        ("clean_install", "clean_install"),
        ("settings", "settings"),
    ]
    items = [(plugin.url(action=action), listing.folder_item(kodi.text(label), kodi.ICON, kodi.FANART), False)
             for label, action in entries]
    plugin.finish(items, category=kodi.text("tools"), cache=False)


def clear_cache(plugin, app):
    app.store.cache_clear()
    kodi.notify(kodi.text("cache_cleared"))


def clear_search(plugin, app):
    app.store.clear_searches()
    kodi.notify(kodi.text("search_cleared"))
    xbmc.executebuiltin("Container.Refresh")


def run_wizard(plugin, app):
    wizard.run(app)


def open_settings(plugin, app):
    kodi.ADDON.openSettings()


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
