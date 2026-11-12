# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""The current plugin call: its parameters, URL building and directory output."""

from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcplugin

from resources.lib import kodi


def dismiss_playback_failed(wait=3.0, monitor=None):
    """Kodi counts a play request ended without a video as a failure, and after a few (or 20 seconds)
    shows "Playback failed: one or more items failed to play", although you only backed out. Kodi has no
    way to turn that off, so close that message if it appears in the next few seconds."""
    monitor = monitor or xbmc.Monitor()
    waited = 0.0
    while waited < wait and not monitor.abortRequested():
        if xbmc.getCondVisibility("Window.IsActive(okdialog)") and \
                xbmc.getInfoLabel("Control.GetLabel(1)") == xbmc.getLocalizedString(16026):
            xbmc.executebuiltin("Dialog.Close(okdialog,true)")
            return True
        if monitor.waitForAbort(0.1):
            break
        waited += 0.1
    return False


class Plugin:
    def __init__(self, argv):
        self.base = argv[0]
        self.handle = int(argv[1]) if len(argv) > 1 else -1
        query = argv[2][1:] if len(argv) > 2 and argv[2].startswith("?") else ""
        self.query = query
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
        from resources.lib import listing, timing, views
        timing.step("preparing")
        if content in views.KINDS:
            entry = [views.context_entry(self, content)]
            for _, list_item, _ in items:
                listing.add_to_menu(list_item, entry)     # after the item's own entries, never over them
        listing._MENUS.clear()
        xbmcplugin.addDirectoryItems(self.handle, items, len(items))
        cache = cache and kodi.setting_bool("perf.menu_cache")
        xbmcplugin.endOfDirectory(self.handle, succeeded=True, cacheToDisc=cache)
        timing.step(f"handing {len(items)} rows to Kodi")
        kind = view_setting.split(".", 1)[1] if view_setting.startswith("view.") else ""
        view_id = views.saved_view(kind) if kind in views.KINDS else 0
        if view_id > 0:
            xbmc.executebuiltin(f"Container.SetViewMode({view_id})")

    def fail(self):
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)

    @property
    def url_now(self):
        """This call's own plugin:// URL (what Kodi files resume points against)."""
        return f"{self.base}{'?' + self.query if self.query else ''}"

    def resolve(self, item):
        """Hand Kodi the playable item for this play request."""
        xbmcplugin.setResolvedUrl(self.handle, True, item)

    def resolve_nothing(self):
        """End a play request without playing (nothing found, cancelled or failed).

        Kodi may have queued the item in its video playlist (for example with "Play next video
        automatically" on). Ending a queued item without a video makes Kodi say "Playback failed" and
        try the next item, so empty the queue first, as Seren does."""
        import xbmcgui
        xbmc.PlayList(xbmc.PLAYLIST_VIDEO).clear()
        xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem(offscreen=True))
        xbmc.executebuiltin("Dialog.Close(busydialog)")
        xbmc.executebuiltin("Dialog.Close(busydialognocancel)")
        dismiss_playback_failed()
