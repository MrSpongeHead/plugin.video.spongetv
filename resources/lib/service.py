# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Background service. Stage 1: tidies the cache at start-up and every 15 minutes (never during
playback), and checks any API key you change in Settings. Trakt sync arrives in stage 2."""

import os

import xbmc

from resources.lib import keys, kodi
from resources.lib.context import DB_NAME
from resources.lib.database import Store
from resources.lib.http import Http

INTERVAL = 15 * 60  # seconds between maintenance runs
MB = 1024 * 1024


def _store():
    return Store(os.path.join(kodi.ensure_profile(), DB_NAME))


def tidy(store):
    limit = max(kodi.setting_int("cache.size_mb"), 10) * MB
    store.cache_tidy(limit)


def check_changed_keys(store, http):
    """Check each key that changed since it was last checked, and say if a service rejects it."""
    for name, service in keys.SERVICES.items():
        value = kodi.setting_str(f"{name}.api_key").strip()
        if not value or store.get_meta(f"keycheck:{name}") == keys.fingerprint(value):
            continue
        result = keys.check(name, http, value)
        if result is None:
            continue  # couldn't reach the service: try again next time settings change
        store.set_meta(f"keycheck:{name}", keys.fingerprint(value))
        kodi.notify(kodi.text("key_accepted" if result else "key_rejected", service=service))


class Monitor(xbmc.Monitor):
    def onSettingsChanged(self):
        store = _store()
        try:
            check_changed_keys(store, Http(f"SpongeTV/{kodi.VERSION}"))
        except Exception as error:  # never let a check stop the service
            kodi.log_error(f"Key check failed: {error}")
        finally:
            store.close()


def run():
    monitor = Monitor()
    player = xbmc.Player()
    kodi.log(f"Service started (Kodi {kodi.kodi_major_version()})")
    waited = INTERVAL  # tidy straight away on start
    while not monitor.abortRequested():
        if waited >= INTERVAL and not player.isPlaying():
            store = _store()
            try:
                tidy(store)
            except Exception as error:  # never let maintenance stop the service
                kodi.log_error(f"Maintenance failed: {error}")
            finally:
                store.close()
            waited = 0
        if monitor.waitForAbort(10):
            break
        waited += 10
    kodi.log("Service stopped")
