# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""The current plugin call: its parameters, URL building and directory output."""

from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcplugin

from resources.lib import kodi


class Plugin:
    def __init__(self, argv):
        self.base = argv[0]
        self.handle = int(argv[1]) if len(argv) > 1 else -1
        query = argv[2][1:] if len(argv) > 2 and argv[2].startswith("?") else ""
        self.params = dict(parse_qsl(query))
        self.action = self.params.get("action", "home")

    def url(self, **params):
        clean = {k: v for k, v in params.items() if v is not None}
        return f"{self.base}?{urlencode(clean)}"

    def int_param(self, name, default=0):
        try:
            return int(self.params.get(name, default))
        except ValueError:
            return default

    def finish(self, items, content="", category="", view_setting="", cache=True):
        """items: list of (url, ListItem, is_folder)."""
        if category:
            xbmcplugin.setPluginCategory(self.handle, category)
        if content:
            xbmcplugin.setContent(self.handle, content)
        xbmcplugin.addDirectoryItems(self.handle, items, len(items))
        cache = cache and kodi.setting_bool("perf.menu_cache")
        xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=cache)
        view_id = kodi.setting_int(view_setting) if view_setting else 0
        if view_id > 0:
            xbmc.executebuiltin(f"Container.SetViewMode({view_id})")

    def fail(self):
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)

    def resolve_nothing(self):
        """End a play request without playing (used until playback arrives)."""
        import xbmcgui
        xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
