# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Trakt sign-in and sign-out, running a sync, and turning Trakt errors into plain messages."""

import json

import xbmc
import xbmcgui

from resources.lib import kodi
from resources.lib.sync import Syncer
from resources.lib.trakt import TraktError

MESSAGES = {
    "signed_out": "trakt_err_signed_out",
    "forbidden": "trakt_err_forbidden",
    "account_limit": "trakt_err_account_limit",
    "locked": "trakt_err_locked",
    "vip": "trakt_err_vip",
    "not_found": "trakt_err_not_found",
    "rate": "trakt_err_rate",
    "unavailable": "trakt_err_unavailable",
    "network": "trakt_err_unavailable",
    "sign_in_denied": "trakt_err_denied",
    "sign_in_expired": "trakt_err_expired",
    "sign_in_limit": "trakt_err_limit",
    "bad_client_id": "trakt_err_client_id",
}


def message(error):
    return message_for(getattr(error, "kind", ""))


def message_for(kind):
    return kodi.text(MESSAGES.get(kind, "trakt_err_unavailable"))


def syncer(app):
    return Syncer(app.trakt, app.store, resume_max_age_days=kodi.setting_int("trakt.resume_max_age"))


def ask_client_id(app, dialog):
    value = (dialog.input(kodi.text("trakt_enter_client_id"), defaultt=kodi.setting_str("trakt.client_id")) or "").strip()
    if value:
        kodi.set_setting_str("trakt.client_id", value)
        app._trakt = None   # rebuild the client with the new ID
    return value


# -- the status lines in Settings, Accounts -------------------------------------------------------------
NO_PREMIUM = "no premium"


def _token(setting_id, field):
    try:
        return json.loads(kodi.setting_str(setting_id) or "{}").get(field)
    except (ValueError, AttributeError):
        return None


def account_status(days=None):
    """Fill in who you're signed in as in Settings, Accounts, and show only the buttons that apply.
    days: Premiumize days of premium left if just found out (NO_PREMIUM for a free account); None keeps
    the figure already shown. Only writes what changed, as each write tells the service settings changed."""
    trakt_on = bool(_token("trakt.token", "refresh_token") or _token("trakt.token", "access_token"))
    name = kodi.setting_str("trakt.username")
    trakt_text = ((kodi.text("status_trakt_as", name=name) if name else kodi.text("status_signed_in"))
                  if trakt_on else kodi.text("status_not_signed_in"))
    pm_on = bool(_token("premiumize.token", "access_token") or kodi.setting_str("premiumize.api_key").strip())
    shown = kodi.setting_str("premiumize.status")
    if not pm_on:
        pm_text = kodi.text("status_not_signed_in")
    elif days == NO_PREMIUM:
        pm_text = kodi.text("status_pm_free")
    elif days is not None:
        pm_text = kodi.text("status_pm_days", days=days)
    elif shown and shown != kodi.text("status_not_signed_in"):
        pm_text = shown                      # keep the days left from the last check
    else:
        pm_text = kodi.text("status_signed_in")
    for setting_id, value in (("trakt.status", trakt_text), ("premiumize.status", pm_text)):
        if kodi.setting_str(setting_id) != value:
            kodi.set_setting_str(setting_id, value)
    for setting_id, value in (("trakt.signed_in", trakt_on), ("premiumize.signed_in", pm_on)):
        if kodi.setting_bool(setting_id) != value:
            kodi.set_setting_bool(setting_id, value)


def sign_in(app, dialog=None):
    """Device sign-in: show the code, wait for you to approve it on trakt.tv, then sync."""
    dialog = dialog or xbmcgui.Dialog()
    if not app.trakt.configured and not ask_client_id(app, dialog):
        dialog.ok("SpongeTV", kodi.text("trakt_need_client_id"))
        return False
    trakt = app.trakt
    try:
        code = trakt.device_code()
    except TraktError as error:
        kind = "bad_client_id" if error.status in (401, 403, 404) else error.kind
        dialog.ok("SpongeTV", kodi.text(MESSAGES.get(kind, "trakt_err_unavailable")))
        return False
    progress = xbmcgui.DialogProgress()
    progress.create(kodi.text("trakt_sign_in"), kodi.text("trakt_sign_in_steps", url=code.get("verification_url", "trakt.tv/activate"),
                                                         code=code.get("user_code", "")))
    try:
        done = trakt.poll_device(code, should_stop=progress.iscanceled)
    except TraktError as error:
        progress.close()
        dialog.ok("SpongeTV", message(error))
        return False
    progress.close()
    if not done:
        return False
    try:
        name = trakt.username()
    except TraktError:
        name = ""
    kodi.set_setting_str("trakt.username", name)
    account_status()
    kodi.notify(kodi.text("trakt_signed_in_as", name=name) if name else kodi.text("trakt_signed_in"))
    run_sync(app, force=True, visible=True)
    return True


def sign_out(app, dialog=None):
    dialog = dialog or xbmcgui.Dialog()
    if not dialog.yesno("SpongeTV", kodi.text("trakt_sign_out_confirm")):
        return False
    app.trakt.sign_out()
    app.library.clear()
    syncer(app).forget()
    kodi.set_setting_str("trakt.username", "")
    account_status()
    kodi.notify(kodi.text("trakt_signed_out"))
    xbmc.executebuiltin("Container.Refresh")
    return True


def run_sync(app, force=False, visible=False):
    """Run a sync now. visible shows a progress window (first sync, "Sync now")."""
    progress = None
    if visible:
        progress = xbmcgui.DialogProgressBG()
        progress.create("SpongeTV", kodi.text("trakt_syncing"))

    def report(done, total):
        if progress:
            progress.update(int(100 * done / max(total, 1)))
    try:
        result = syncer(app).run(force=force, progress=report)
    except TraktError as error:
        if visible:
            kodi.notify(message(error))
        return False
    finally:
        if progress:
            progress.close()
    if visible:
        kodi.notify(kodi.text("trakt_sync_busy") if result is None else kodi.text("trakt_sync_done"))
    return result is not None


# -- Premiumize -------------------------------------------------------------------------------------------
PM_MESSAGES = {"no_client_id": "pm_err_no_client_id", "bad_client_id": "pm_err_bad_client_id", "denied": "pm_err_denied",
               "unreachable": "pm_unreachable", "failed": "pm_unreachable"}


def premiumize_sign_in(app, dialog=None):
    """Code sign-in: show the code, wait for you to approve it at premiumize.me/device."""
    from resources.lib import premiumize
    dialog = dialog or xbmcgui.Dialog()
    client_id = app.premiumize_client_id
    try:
        code = premiumize.device_code(app.http, client_id)
    except premiumize.PremiumizeError as error:
        dialog.ok(kodi.text("grp_premiumize"), kodi.text(PM_MESSAGES.get(error.kind, "pm_unreachable")))
        return False
    url = code.get("verification_uri") or premiumize.DEVICE_URL
    progress = xbmcgui.DialogProgress()
    progress.create(kodi.text("pm_sign_in"), kodi.text("pm_sign_in_steps", url=url.replace("https://", ""),
                                                       code=code.get("user_code", "")))
    try:
        token = premiumize.poll_device(app.http, client_id, code, should_stop=progress.iscanceled)
    except premiumize.PremiumizeError as error:
        progress.close()
        dialog.ok(kodi.text("grp_premiumize"), kodi.text(PM_MESSAGES.get(error.kind, "pm_unreachable")))
        return False
    progress.close()
    if not token:
        return False
    kodi.set_setting_str("premiumize.token", json.dumps(token))
    app.store.set_meta("premiumize:last_check", "0")      # the daily check looks at the new sign-in straight away
    try:
        client = app.premiumize
        days = client.days_left(client.account())
    except Exception:   # signed in either way; the status can wait
        days = None
    account_status(days)
    kodi.notify(kodi.text("pm_signed_in_days", days=days) if days is not None else kodi.text("pm_signed_in"))
    return True


def premiumize_sign_out(app, dialog=None):
    dialog = dialog or xbmcgui.Dialog()
    if not dialog.yesno(kodi.text("grp_premiumize"), kodi.text("pm_sign_out_confirm")):
        return False
    kodi.set_setting_str("premiumize.token", "")
    app.store.cache_delete("premiumize:days_left")
    account_status()
    kodi.notify(kodi.text("pm_signed_out"))
    xbmc.executebuiltin("Container.Refresh")
    return True
