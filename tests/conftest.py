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
        self.label2 = label2
        self.art = {}
        self.properties = {}
        self.context_menu = []
        self.tag = Recorder()

    def getLabel(self):
        return self.label

    def setLabel(self, label):
        self.label = label

    def setLabel2(self, label):
        self.label2 = label

    def addContextMenuItems(self, items, replaceItems=False):
        self.context_menu.extend(items)

    def getVideoInfoTag(self):
        return self.tag

    def setArt(self, art):
        self.art.update(art)

    def setPath(self, path):
        self.path = path

    def setProperty(self, key, value):
        self.properties[key] = value


class FakeDialog:
    script = []  # queued answers for select/yesno/input/ok, consumed in order
    shown = []
    menus = []

    def _next(self, default):
        return FakeDialog.script.pop(0) if FakeDialog.script else default

    def notification(self, heading, message, icon="", time=0, sound=True):
        FakeDialog.shown.append(("notification", message))

    def ok(self, heading, message):
        FakeDialog.shown.append(("ok", message))
        return True

    def yesno(self, heading, message, nolabel="", yeslabel="", autoclose=0, defaultbutton=None):
        FakeDialog.shown.append(("yesno", message))
        return self._next(False)

    def select(self, heading, options, preselect=-1):
        FakeDialog.shown.append(("select", heading))
        return self._next(-1)

    def input(self, heading, *args, **kwargs):
        FakeDialog.shown.append(("input", heading))
        return self._next("")

    def textviewer(self, heading, text):
        FakeDialog.shown.append(("textviewer", text))

    def browse(self, kind, heading, shares, mask="", *args, **kwargs):
        FakeDialog.shown.append(("browse", heading))
        return self._next("")

    def numeric(self, kind, heading, default=""):
        FakeDialog.shown.append(("numeric", heading))
        return self._next(default)

    def contextmenu(self, options):
        FakeDialog.shown.append(("contextmenu", tuple(options)))
        FakeDialog.menus.append(list(options))
        return self._next(-1)


class FakeProgress:
    cancel_after = None   # number of iscanceled() calls before reporting a cancel

    def create(self, heading, message=""):
        FakeDialog.shown.append(("progress", message))
        self.checks = 0

    def update(self, percent, message=""):
        pass

    def iscanceled(self):
        self.checks += 1
        return FakeProgress.cancel_after is not None and self.checks > FakeProgress.cancel_after

    def close(self):
        pass


class FakeAddon:
    settings = {}
    profile = PROFILE_DIR

    def __init__(self, addon_id=None):
        pass

    def getAddonInfo(self, key):
        return {"id": "plugin.video.spongetv", "version": "0.2.7", "path": ROOT,
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

    def setSettingBool(self, key, value):
        FakeAddon.settings[key] = bool(value)

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
        def __init__(self, *args, **kwargs):
            pass

        def abortRequested(self):
            return True

        def waitForAbort(self, seconds=0):
            return True
    xbmc.Monitor = Monitor

    class Player:
        """Plays nothing unless a test gives it a script: [(position, total), ...] then stops."""
        script = []

        def __init__(self, *args, **kwargs):
            self.positions = list(Player.script)
            self.seeks = []

        def isPlaying(self):
            return bool(getattr(self, "positions", []))

        isPlayingVideo = isPlaying

        def getTime(self):
            position = self.positions.pop(0)
            return position[0]

        def getTotalTime(self):
            return self.positions[0][1] if self.positions else 0

        def seekTime(self, seconds):
            self.seeks.append(seconds)
    xbmc.Player = Player
    xbmc.VideoStreamDetail = lambda *a, **k: ("stream", a, k)
    xbmc.PLAYLIST_VIDEO = 1
    xbmc.getCondVisibility = lambda condition: False
    xbmc.getLocalizedString = lambda number: ""

    class PlayList:
        cleared = 0

        def __init__(self, kind):
            self.kind = kind

        def clear(self):
            PlayList.cleared += 1
    xbmc.PlayList = PlayList
    xbmc.jsonrpc = []

    def execute_jsonrpc(request):
        xbmc.jsonrpc.append(request)
        return '{"id": 1, "jsonrpc": "2.0", "result": "OK"}'
    xbmc.executeJSONRPC = execute_jsonrpc

    class Window:
        properties = {}

        def __init__(self, window_id=10000):
            pass

        def setProperty(self, key, value):
            Window.properties[key] = value

        def getProperty(self, key):
            return Window.properties.get(key, "")

        def clearProperty(self, key):
            Window.properties.pop(key, None)

    xbmcaddon = types.ModuleType("xbmcaddon")
    xbmcaddon.Addon = FakeAddon

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.Window = Window
    xbmcgui.ListItem = FakeListItem
    xbmcgui.Dialog = FakeDialog
    xbmcgui.DialogProgress = FakeProgress
    xbmcgui.DialogProgressBG = FakeProgress

    class WindowXMLDialog:
        """Tests have no skin engine: opening one fails the way Kodi does, so the simple dialogs are used."""
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no skin engine in tests")
    xbmcgui.WindowXMLDialog = WindowXMLDialog

    xbmcplugin = types.ModuleType("xbmcplugin")

    def add_items(handle, items, total=0):
        Directory.items.extend(items)
        return True

    def end(handle, succeeded=True, updateListing=False, cacheToDisc=True):
        Directory.ended = succeeded
        Directory.cached = cacheToDisc

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
    FakeDialog.menus = []
    FakeProgress.cancel_after = None
    Directory.items = []
    Directory.ended = None
    Directory.content = None
    Directory.resolved = None
    Directory.builtins = []
    sys.modules["xbmc"].Player.script = []
    sys.modules["xbmc"].PlayList.cleared = 0
    sys.modules["xbmc"].jsonrpc.clear()
    sys.modules["xbmcgui"].Window.properties.clear()
    from resources.lib import kodi
    monkeypatch.setattr(kodi, "PROFILE", str(tmp_path))
    # Provider packages import from the profile folder, which is new for every test.
    path_before = list(sys.path)
    _forget_provider_modules()
    yield
    _forget_provider_modules()
    sys.path[:] = path_before


def _forget_provider_modules():
    for name in list(sys.modules):
        if name in ("providers", "providerModules") or name.startswith(("providers.", "providerModules.")):
            del sys.modules[name]
