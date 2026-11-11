# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Which skin view each kind of list opens in, chosen by using it.

Kodi remembers a view for each add-on folder separately, and a folder it hasn't seen opens in whichever
view you last chose anywhere (CGUIViewStateWindowVideoNav saves add-on lists under "videofiles"). So
SpongeTV keeps one view each for films, TV shows, seasons and episodes. You pick a view from Kodi's side
menu in a SpongeTV list, then "Use this view for ..." from the context menu: SpongeTV reads the view's
number and name from the skin itself, so it works with any skin. A view saved under one skin is ignored
under another, since view numbers belong to the skin.
"""

import xbmc

from resources.lib import kodi

KINDS = ("movies", "tvshows", "seasons", "episodes")
ADDON = "plugin.video.spongetv"


def saved_view(kind):
    """The view number to open this kind of list in, or 0 for the skin's own choice."""
    view_id = kodi.setting_int(f"view.{kind}")
    skin = kodi.setting_str(f"view.{kind}_skin")
    if view_id > 0 and (not skin or skin == xbmc.getSkinDir()):
        return view_id
    return 0


def context_entry(plugin, kind):
    return kodi.text(f"ctx_view_{kind}"), f"RunPlugin({plugin.url(action='save_view', kind=kind)})"


def _current_view(monitor, wait=2.0):
    """(view number, view name) of the list showing now, once the context menu has closed; or None."""
    waited = 0.0
    while xbmc.getCondVisibility("Window.IsActive(contextmenu)") and waited < wait:
        if monitor.waitForAbort(0.1):
            return None
        waited += 0.1
    if xbmc.getInfoLabel("Container.PluginName") != ADDON:
        return None
    try:
        view_id = int(xbmc.getInfoLabel("System.CurrentControlID") or 0)
    except ValueError:
        return None
    if view_id <= 0 or not xbmc.getCondVisibility(f"Control.IsVisible({view_id})"):
        return None
    return view_id, xbmc.getInfoLabel("Container.Viewmode")


def save_view(plugin, app, monitor=None):
    kind = plugin.params.get("kind")
    if kind not in KINDS:
        return
    found = _current_view(monitor or xbmc.Monitor())
    if not found:
        kodi.log(f"Couldn't read the current view (control {xbmc.getInfoLabel('System.CurrentControlID')!r})")
        kodi.notify(kodi.text("view_not_read"))
        return
    view_id, name = found
    kodi.set_setting_int(f"view.{kind}", view_id)
    kodi.set_setting_str(f"view.{kind}_name", name)
    kodi.set_setting_str(f"view.{kind}_skin", xbmc.getSkinDir())
    view_status()
    kodi.log(f"{kind} will open in view {view_id} ({name}) with {xbmc.getSkinDir()}")
    kodi.notify(kodi.text(f"view_saved_{kind}", name=name or view_id))


def reset_views(plugin=None, app=None):
    for kind in KINDS:
        kodi.set_setting_int(f"view.{kind}", 0)
        kodi.set_setting_str(f"view.{kind}_name", "")
        kodi.set_setting_str(f"view.{kind}_skin", "")
    view_status()
    kodi.notify(kodi.text("views_reset"))


def view_status():
    """The greyed lines in Settings, Advanced, Views: the view each kind of list opens in."""
    for kind in KINDS:
        if saved_view(kind):
            name = kodi.setting_str(f"view.{kind}_name")
            text = name or kodi.text("view_number", number=kodi.setting_int(f"view.{kind}"))
        else:
            text = kodi.text("view_skin_default")
        if kodi.setting_str(f"view.{kind}_status") != text:
            kodi.set_setting_str(f"view.{kind}_status", text)
