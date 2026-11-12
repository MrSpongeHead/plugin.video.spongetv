# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Thin wrapper around Kodi's modules, so the rest of SpongeTV is easy to test."""

import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.strings import STRINGS

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
VERSION = ADDON.getAddonInfo("version")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
ICON = os.path.join(ADDON_PATH, "resources", "media", "icon.png")
FANART = os.path.join(ADDON_PATH, "resources", "media", "fanart.jpg")


def text(key, **values):
    """Localised string by key, falling back to the built-in English."""
    string_id, english = STRINGS[key]
    value = ADDON.getLocalizedString(string_id) or english
    return value.format(**values) if values else value


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[{ADDON_ID}] {message}", level)


def log_debug(message):
    """Only in Kodi's log when debug logging is on: routine detail."""
    log(message, xbmc.LOGDEBUG)


def log_timing(argv, started, code_loaded):
    """How long this list or action took, then the steps and counts noted on the way (see timing.py)."""
    import sys
    import time
    from resources.lib import timing
    done = time.perf_counter()
    log_debug(f"Timing {(argv[2] if len(argv) > 2 else '')[:90] or '(main menu)'}: "
              f"{(done - started) * 1000:.0f} ms in all, {(code_loaded - started) * 1000:.0f} ms of it "
              f"starting up{' (used the network)' if 'requests' in sys.modules else ''}")
    for line in timing.summary():
        log_debug(line)


def log_error(message):
    log(message, xbmc.LOGERROR)


HANDLE_KEPT_FOR = 5      # seconds
ALWAYS_FRESH = False     # the background service sets this: it runs for hours and must see every change at once
_handle = (None, 0.0)


def _settings():
    """The handle settings are read through. Opening one costs milliseconds (far more than the read), and a
    list reads settings dozens of times, so one handle is shared for a few seconds. Not for longer: a
    long-lived handle can return settings as they were when it was opened (such as an old Trakt token)."""
    global _handle
    import time
    handle, opened = _handle
    now = time.monotonic()
    if handle is None or ALWAYS_FRESH or now - opened > HANDLE_KEPT_FOR:
        handle = xbmcaddon.Addon(ADDON_ID)
        _handle = (handle, now)
    return handle


def _changed():
    """After writing a setting: the next read opens a new handle."""
    global _handle
    _handle = (None, 0.0)


def setting_str(setting_id):
    return _settings().getSettingString(setting_id)


def setting_bool(setting_id):
    return _settings().getSettingBool(setting_id)


def setting_int(setting_id):
    return _settings().getSettingInt(setting_id)


def set_setting_str(setting_id, value):
    _settings().setSettingString(setting_id, value)
    _changed()


def set_setting_int(setting_id, value):
    _settings().setSettingInt(setting_id, value)
    _changed()


def set_setting_bool(setting_id, value):
    _settings().setSettingBool(setting_id, bool(value))
    _changed()


def notify(message, time_ms=4000):
    sound = setting_bool("general.notification_sound")
    xbmcgui.Dialog().notification("SpongeTV", message, ICON, time_ms, sound)


def kodi_major_version():
    """Kodi's major version, read at run time rather than from a fixed list."""
    build = xbmc.getInfoLabel("System.BuildVersion")
    try:
        return int(build.split(".")[0])
    except (ValueError, IndexError):
        return 0


def kodi_language():
    """Kodi's interface language as a TMDB-style code, e.g. 'en-GB'."""
    language = xbmc.getLanguage(xbmc.ISO_639_1) or "en"
    # Kodi gives no country code here, so pick each language's home country.
    country = {"en": "GB", "pt": "PT", "es": "ES", "fr": "FR", "de": "DE"}.get(language, "")
    return f"{language}-{country}" if country else language


def ensure_profile():
    os.makedirs(PROFILE, exist_ok=True)
    return PROFILE
