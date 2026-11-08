# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Background service.

- Tidies the cache at start-up and every 15 minutes.
- Syncs with Trakt shortly after start-up, then every few minutes (Settings, General, Trakt),
  after waking from sleep, and when your Trakt settings change. Each sync downloads only what
  changed, refreshes a token that's close to expiring, and sends scrobbles queued while offline.
- Never runs maintenance or syncs during playback, and waits longer after each failed sync.
- Checks any API key you change in Settings.
- Once a day, checks provider packages for updates and tells you, or installs them
  (Settings, Sources, Provider packages).
"""

import json
import os

import xbmc
import xbmcgui

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
PACKAGE_CHECK_EVERY = 24 * 3600
PACKAGE_CHECK_AFTER = 5 * 60   # not straight away at start-up
UPDATES_OFF, UPDATES_TELL, UPDATES_INSTALL = range(3)


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


def check_packages(store, http, now, mode=None):
    """Daily provider package update check. Returns the names updated or ready to update."""
    mode = kodi.setting_int("packages.updates") if mode is None else mode
    if mode == UPDATES_OFF:
        return []
    last = float(store.get_meta("packages:last_check") or 0)
    if now - last < PACKAGE_CHECK_EVERY:
        return []
    store.set_meta("packages:last_check", str(now))
    from resources.lib.packages import PackageError, Packages
    manager = Packages(store, kodi.PROFILE, http)
    updates = manager.available_updates()
    if not updates:
        return []
    if mode == UPDATES_TELL:
        names = [f"{p['name']} {r.get('version')}" for p, r in updates]
        kodi.notify(kodi.text("packages_updates_ready", names=", ".join(names)), 8000)
        return names
    done = []
    for package, remote in updates:
        try:
            if manager.update(package, remote):
                done.append(f"{package['name']} {remote.get('version')}")
        except PackageError as error:
            kodi.log_error(f"Package update failed for {package['name']}: {error}")
    if done:
        kodi.notify(kodi.text("packages_updated", names=", ".join(done)), 8000)
    return done


EXPIRY_WARN_DAYS = 7


def check_premiumize(store, http, now):
    """Once a day: warn when the Premiumize account has a week or less left. Returns the days left."""
    from resources.lib.premiumize import Premiumize, PremiumizeError
    try:
        token = json.loads(kodi.setting_str("premiumize.token") or "{}")
    except ValueError:
        token = {}
    bearer = token.get("access_token") or kodi.setting_str("premiumize.api_key")
    client = Premiumize(http, bearer, clock=lambda: now)
    if not client.ready or now - float(store.get_meta("premiumize:last_check") or 0) < PACKAGE_CHECK_EVERY:
        return None
    store.set_meta("premiumize:last_check", str(now))
    if token.get("expires_at"):   # the code sign-in has an end date: say so a week ahead
        days_to_sign_in = int((token["expires_at"] - now) // 86400)
        if days_to_sign_in <= EXPIRY_WARN_DAYS:
            kodi.notify(kodi.text("pm_sign_in_again", days=max(0, days_to_sign_in)), 8000)
    try:
        account = client.account()
    except PremiumizeError as error:
        if error.kind == "bad_key":
            kodi.notify(kodi.text("pm_sign_in_expired" if token.get("access_token") else "pm_bad_key"), 8000)
        return None
    days = client.days_left(account)
    if days is not None and days <= EXPIRY_WARN_DAYS:
        kodi.notify(kodi.text("pm_expiring", days=days), 8000)
    return days


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
    package_check_at = clock() + PACKAGE_CHECK_AFTER
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
            if now >= package_check_at:
                package_check_at = now + 3600   # look again in an hour; the check itself runs daily
                store = _store()
                try:
                    check_premiumize(store, Http(f"SpongeTV/{kodi.VERSION}"), now)
                    check_packages(store, Http(f"SpongeTV/{kodi.VERSION}"), now)
                except Exception as error:  # never let a check stop the service
                    kodi.log_error(f"Package update check failed: {error}")
                finally:
                    store.close()
            home = xbmcgui.Window(10000)
            if home.getProperty("spongetv.sync_soon"):   # something was just watched: catch up with Trakt
                home.clearProperty("spongetv.sync_soon")
                scheduler.soon(now)
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
