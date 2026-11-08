# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Background service.

- Tidies the cache at start-up and every 15 minutes.
- Syncs with Trakt shortly after start-up, then every few minutes (Settings, General, Trakt),
  after waking from sleep, and when your Trakt settings change. Each sync downloads only what
  changed, refreshes a token that's close to expiring, and sends scrobbles queued while offline.
- Never runs maintenance or syncs during playback, and waits longer after each failed sync.
- Checks any API key you change in Settings.
"""

import json
import os

import xbmc

from resources.lib import accounts, keys, kodi
from resources.lib.context import DB_NAME, App
from resources.lib.database import Store
from resources.lib.http import Http
from resources.lib.trakt import TraktError

TICK = 10                     # seconds between checks
MAINTENANCE_EVERY = 15 * 60
FIRST_SYNC_AFTER = 30
MAX_BACKOFF = 2 * 3600
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


def trakt_state():
    """What, in Settings, should trigger a sync when it changes: the app and who's signed in."""
    try:
        signed_in = bool(json.loads(kodi.setting_str("trakt.token") or "{}").get("refresh_token"))
    except ValueError:
        signed_in = False
    return kodi.setting_str("trakt.client_id"), kodi.setting_str("trakt.username"), signed_in


class Scheduler:
    """Decides when to sync. Pure logic, so it can be tested without Kodi's clock."""

    def __init__(self, interval_minutes, now):
        self.interval = max(int(interval_minutes or 15), 5) * 60
        self.next_sync = now + FIRST_SYNC_AFTER
        self.failures = 0

    def due(self, now):
        return now >= self.next_sync

    def soon(self, now, delay=5):
        self.next_sync = min(self.next_sync, now + delay)

    def finished(self, now, ok):
        if ok:
            self.failures = 0
            self.next_sync = now + self.interval
        else:
            self.failures += 1
            self.next_sync = now + min(self.interval * (2 ** self.failures), MAX_BACKOFF)


def sync_once():
    """One sync if you're signed in. Returns True on success (or nothing to do), False on failure."""
    app = App()
    try:
        if not app.signed_in:
            return True
        app.trakt.refresh_if_due()
        accounts.syncer(app).run()   # None means another sync was already running: that's fine
        return True
    except TraktError as error:
        kodi.log_error(f"Trakt sync failed: {error}")
        if error.kind == "signed_out":
            kodi.notify(accounts.message(error))
        return False
    finally:
        app.store.close()


class Monitor(xbmc.Monitor):
    def __init__(self, scheduler, clock):
        super().__init__()
        self.scheduler = scheduler
        self.clock = clock
        self.state = trakt_state()

    def onSettingsChanged(self):
        store = _store()
        try:
            check_changed_keys(store, Http(f"SpongeTV/{kodi.VERSION}"))
        except Exception as error:  # never let a check stop the service
            kodi.log_error(f"Key check failed: {error}")
        finally:
            store.close()
        state = trakt_state()
        if state != self.state:
            self.state = state
            self.scheduler.soon(self.clock())

    def onNotification(self, sender, method, data):
        if method == "System.OnWake":
            self.scheduler.soon(self.clock(), delay=30)


def run(clock=None):
    import time
    clock = clock or time.time
    scheduler = Scheduler(kodi.setting_int("trakt.sync_minutes"), clock())
    monitor = Monitor(scheduler, clock)
    player = xbmc.Player()
    kodi.log(f"Service started (Kodi {kodi.kodi_major_version()})")
    last_tidy = 0
    while not monitor.abortRequested():
        now = clock()
        if not player.isPlaying():
            if now - last_tidy >= MAINTENANCE_EVERY:
                store = _store()
                try:
                    tidy(store)
                except Exception as error:  # never let maintenance stop the service
                    kodi.log_error(f"Maintenance failed: {error}")
                finally:
                    store.close()
                last_tidy = now
            if scheduler.due(now):
                try:
                    ok = sync_once()
                except Exception as error:
                    kodi.log_error(f"Sync failed unexpectedly: {error}")
                    ok = False
                scheduler.finished(clock(), ok)
        if monitor.waitForAbort(TICK):
            break
    kodi.log("Service stopped")
