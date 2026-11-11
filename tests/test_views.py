# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Choosing the view each kind of list opens in."""

import pytest

from conftest import Directory, FakeAddon

from resources.lib import views


class FakePlugin:
    def __init__(self, **params):
        self.params = params

    def url(self, **params):
        return "plugin://plugin.video.spongetv/?" + "&".join(f"{k}={v}" for k, v in params.items())


class Quiet:
    def waitForAbort(self, seconds=0):
        return False


@pytest.fixture
def kodi_screen(monkeypatch):
    """A SpongeTV episode list in Estuary's List view (control 50), the context menu already closed."""
    import xbmc
    state = {"skin": "skin.estuary", "labels": {"Container.PluginName": "plugin.video.spongetv",
                                                "System.CurrentControlID": "50", "Container.Viewmode": "List"},
             "visible": {"Control.IsVisible(50)"}}
    monkeypatch.setattr(xbmc, "getSkinDir", lambda: state["skin"], raising=False)
    monkeypatch.setattr(xbmc, "getInfoLabel", lambda label: state["labels"].get(label, ""), raising=False)
    monkeypatch.setattr(xbmc, "getCondVisibility", lambda c: c in state["visible"], raising=False)
    notes = []
    monkeypatch.setattr(views.kodi, "notify", lambda message, *a: notes.append(message))
    FakeAddon.settings.clear()
    return state, notes


def test_using_a_view_saves_its_number_name_and_skin(kodi_screen):
    state, notes = kodi_screen
    views.save_view(FakePlugin(kind="episodes"), None, monitor=Quiet())
    s = FakeAddon.settings
    assert (s["view.episodes"], s["view.episodes_name"], s["view.episodes_skin"]) == (50, "List", "skin.estuary")
    assert s["view.episodes_status"] == "List" and s["view.movies_status"] == "Skin default"
    assert notes == ["Episodes will now open in List view"]
    assert views.saved_view("episodes") == 50 and views.saved_view("movies") == 0


def test_a_view_saved_under_another_skin_is_ignored(kodi_screen):
    state, _ = kodi_screen
    views.save_view(FakePlugin(kind="seasons"), None, monitor=Quiet())
    state["skin"] = "skin.arctic.zephyr.mod"
    assert views.saved_view("seasons") == 0                 # view numbers belong to the skin
    views.view_status()
    assert FakeAddon.settings["view.seasons_status"] == "Skin default"
    state["skin"] = "skin.estuary"
    assert views.saved_view("seasons") == 50


def test_nothing_saved_when_the_view_cant_be_read(kodi_screen):
    state, notes = kodi_screen
    state["labels"]["Container.PluginName"] = "plugin.video.seren"   # not a SpongeTV list
    views.save_view(FakePlugin(kind="movies"), None, monitor=Quiet())
    assert "view.movies" not in FakeAddon.settings and "Couldn't tell" in notes[0]
    state["labels"]["Container.PluginName"] = "plugin.video.spongetv"
    state["labels"]["System.CurrentControlID"] = "9000"                # the side menu, not a list
    views.save_view(FakePlugin(kind="movies"), None, monitor=Quiet())
    assert "view.movies" not in FakeAddon.settings


def test_reset_goes_back_to_the_skin(kodi_screen):
    views.save_view(FakePlugin(kind="tvshows"), None, monitor=Quiet())
    views.reset_views()
    assert views.saved_view("tvshows") == 0
    assert FakeAddon.settings["view.tvshows_status"] == "Skin default"


def test_lists_offer_the_entry_and_open_in_the_saved_view(kodi_screen, monkeypatch):
    import xbmc
    import xbmcgui
    from resources.lib.plugin import Plugin
    views.save_view(FakePlugin(kind="episodes"), None, monitor=Quiet())
    issued = []
    monkeypatch.setattr(xbmc, "executebuiltin", lambda b, *a: issued.append(b), raising=False)
    Directory.items.clear()
    plugin = Plugin(["plugin://plugin.video.spongetv/", "1", "?action=episodes"])
    item = xbmcgui.ListItem("Episode 1")
    plugin.finish([("plugin://x", item, False)], content="episodes", view_setting="view.episodes")
    assert item.context_menu[-1][0] == "Use this view for episodes"
    assert "action=save_view" in item.context_menu[-1][1] and "kind=episodes" in item.context_menu[-1][1]
    assert issued == ["Container.SetViewMode(50)"]
    menu_item = xbmcgui.ListItem("Genres")
    plugin.finish([("plugin://y", menu_item, True)], category="Films")
    assert menu_item.context_menu == []                     # plain menus don't offer it
