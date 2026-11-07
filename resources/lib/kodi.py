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


def log_error(message):
    log(message, xbmc.LOGERROR)


def setting_str(setting_id):
    return ADDON.getSettingString(setting_id)


def setting_bool(setting_id):
    return ADDON.getSettingBool(setting_id)


def setting_int(setting_id):
    return ADDON.getSettingInt(setting_id)


def set_setting_str(setting_id, value):
    ADDON.setSettingString(setting_id, value)


def set_setting_int(setting_id, value):
    ADDON.setSettingInt(setting_id, value)


def notify(message, time_ms=4000):
    xbmcgui.Dialog().notification("SpongeTV", message, ICON, time_ms)


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
