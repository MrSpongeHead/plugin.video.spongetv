# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Background service. Stage 1: keeps the cache tidy; Trakt sync arrives in stage 2."""

import os

import xbmc

from resources.lib import kodi
from resources.lib.context import DB_NAME
from resources.lib.database import Store

INTERVAL = 15 * 60  # seconds between maintenance runs
MB = 1024 * 1024


def _tidy():
    store = Store(os.path.join(kodi.ensure_profile(), DB_NAME))
    try:
        limit = max(kodi.setting_int("cache.size_mb"), 10) * MB
        store.cache_tidy(limit)
    finally:
        store.close()


def run():
    monitor = xbmc.Monitor()
    player = xbmc.Player()
    kodi.log(f"Service started (Kodi {kodi.kodi_major_version()})")
    waited = INTERVAL  # tidy straight away on start
    while not monitor.abortRequested():
        if waited >= INTERVAL and not player.isPlaying():
            try:
                _tidy()
            except Exception as error:  # never let maintenance stop the service
                kodi.log_error(f"Maintenance failed: {error}")
            waited = 0
        if monitor.waitForAbort(10):
            break
        waited += 10
    kodi.log("Service stopped")
