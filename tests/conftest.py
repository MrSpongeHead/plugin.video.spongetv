# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Stand-ins for Kodi's Python modules, so tests run without Kodi."""

import os
import sys
import tempfile
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PROFILE_DIR = tempfile.mkdtemp(prefix="spongetv-test-")


class Recorder:
    """Accepts any setX(...) call and remembers the arguments."""

    def __init__(self):
        self.calls = {}

    def __getattr__(self, name):
        if name.startswith("set"):
            def record(*args, **kwargs):
                self.calls.setdefault(name, []).append(args)
            return record
        raise AttributeError(name)


class FakeListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label = label
        self.art = {}
        self.properties = {}
        self.tag = Recorder()

    def getVideoInfoTag(self):
        return self.tag

    def setArt(self, art):
        self.art.update(art)

    def setProperty(self, key, value):
        self.properties[key] = value


class FakeDialog:
    script = []  # queued answers for select/yesno/input/ok, consumed in order
    shown = []

    def _next(self, default):
        return FakeDialog.script.pop(0) if FakeDialog.script else default

    def notification(self, heading, message, icon="", time=0):
        FakeDialog.shown.append(("notification", message))

    def ok(self, heading, message):
        FakeDialog.shown.append(("ok", message))
        return True

    def yesno(self, heading, message, nolabel="", yeslabel=""):
        FakeDialog.shown.append(("yesno", message))
        return self._next(False)

    def select(self, heading, options, preselect=-1):
        FakeDialog.shown.append(("select", heading))
        return self._next(-1)

    def input(self, heading, *args, **kwargs):
        FakeDialog.shown.append(("input", heading))
        return self._next("")


class FakeAddon:
    settings = {}
    profile = PROFILE_DIR

    def __init__(self, addon_id=None):
        pass

    def getAddonInfo(self, key):
        return {"id": "plugin.video.spongetv", "version": "0.1.0", "path": ROOT,
                "profile": FakeAddon.profile, "name": "SpongeTV"}[key]

    def getLocalizedString(self, string_id):
        return ""

    def getSettingString(self, key):
        return str(FakeAddon.settings.get(key, ""))

    def getSettingBool(self, key):
        return bool(FakeAddon.settings.get(key, False))

    def getSettingInt(self, key):
        return int(FakeAddon.settings.get(key, 0))

    def setSettingString(self, key, value):
        FakeAddon.settings[key] = value

    def setSettingInt(self, key, value):
        FakeAddon.settings[key] = value

    def openSettings(self):
        pass


class Directory:
    """What the last plugin call sent to Kodi."""
    items = []
    ended = None
    content = None
    resolved = None
    builtins = []


def _install_stubs():
    xbmc = types.ModuleType("xbmc")
    xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 0, 1, 2, 3
    xbmc.ISO_639_1 = 0
    xbmc.log = lambda message, level=1: None
    xbmc.getInfoLabel = lambda label: "21.1 (21.1.0) Git:20240804" if label == "System.BuildVersion" else ""
    xbmc.getLanguage = lambda fmt=0, region=False: "en"
    xbmc.executebuiltin = lambda command, wait=False: Directory.builtins.append(command)

    class Actor:
        def __init__(self, name="", role="", order=0, thumbnail=""):
            self.name, self.role, self.order, self.thumbnail = name, role, order, thumbnail
    xbmc.Actor = Actor

    class Monitor:
        def abortRequested(self):
            return True

        def waitForAbort(self, seconds=0):
            return True
    xbmc.Monitor = Monitor

    class Player:
        def isPlaying(self):
            return False
    xbmc.Player = Player

    xbmcaddon = types.ModuleType("xbmcaddon")
    xbmcaddon.Addon = FakeAddon

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.ListItem = FakeListItem
    xbmcgui.Dialog = FakeDialog

    xbmcplugin = types.ModuleType("xbmcplugin")

    def add_items(handle, items, total=0):
        Directory.items.extend(items)
        return True

    def end(handle, succeeded=True, updateListing=False, cacheToDisc=True):
        Directory.ended = succeeded

    xbmcplugin.addDirectoryItems = add_items
    xbmcplugin.endOfDirectory = end
    xbmcplugin.setContent = lambda handle, content: setattr(Directory, "content", content)
    xbmcplugin.setPluginCategory = lambda handle, category: None
    xbmcplugin.setResolvedUrl = lambda handle, succeeded, item: setattr(Directory, "resolved", succeeded)

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda path: path

    for module in (xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs):
        sys.modules[module.__name__] = module


_install_stubs()


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    """Each test starts with empty settings, an empty profile and no recorded output."""
    FakeAddon.settings = {}
    FakeDialog.script = []
    FakeDialog.shown = []
    Directory.items = []
    Directory.ended = None
    Directory.content = None
    Directory.resolved = None
    Directory.builtins = []
    from resources.lib import kodi
    monkeypatch.setattr(kodi, "PROFILE", str(tmp_path))
    yield
