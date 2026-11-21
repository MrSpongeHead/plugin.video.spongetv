# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""The caching assistant (Release 2, stage 2): having Premiumize download a source it hasn't cached.

Choosing such a source in Source Select asks: download and wait, download in the background, or cancel.
Both ways start a Premiumize transfer into a SpongeTV folder in your cloud and record it in SpongeTV's
database, so one follower (check below) handles both:

- Wait: a progress window checks every few seconds and plays the video as soon as Premiumize has it.
- Background: the background service checks every minute and tells you when it's ready, or if it failed.
  Recorded in the database, so it's followed across Kodi restarts.

Once Premiumize has finished, the source is cached, so it plays like any other ready source from then on.
A download that makes no progress for STUCK_AFTER is given up: its transfer is deleted, as Seren does.
"""

import json
import time

import xbmc
import xbmcgui

from resources.lib import kodi
from resources.lib.premiumize import PremiumizeError, magnet_for

FOLDER = "SpongeTV"
FOLDER_KEPT_FOR = 30 * 86400          # the SpongeTV folder's ID, remembered between uses
STUCK_AFTER = 3 * 3600
WAIT_CHECK_EVERY = 5                  # seconds, while you wait
FOLLOW_EVERY = 60                     # seconds, in the background service
ORPHANED_AFTER = 120                  # a "wait" download nobody has checked for this long: its window is gone
WAIT, BACKGROUND, CANCEL = range(3)

DOWNLOADING, DONE, FAILED, STUCK, GONE = "downloading", "done", "failed", "stuck", "gone"


def offered(source):
    """Can the caching assistant offer this source? Torrents Premiumize hasn't cached, with the setting on."""
    return (source.get("debrid") == "uncached" and source.get("type") == "torrent"
            and bool(source.get("hash") or source.get("magnet"))
            and kodi.setting_bool("premiumize.assist"))


def ask(source, nothing_ready=False):
    """WAIT, BACKGROUND or CANCEL."""
    options = [kodi.text("cache_wait"), kodi.text("cache_background"), kodi.text("cache_cancel")]
    heading = kodi.text("cache_nothing_ready" if nothing_ready else "cache_ask", name=source.get("release_title") or "")
    picked = xbmcgui.Dialog().select(heading, options)
    return picked if picked in (WAIT, BACKGROUND) else CANCEL


def best_offer(sources, filter_rules, sort_rules, media):
    """When nothing found is ready to play: the torrent to offer to download, the first by your sort order among
    those your filter allows (leaving aside "hide sources Premiumize hasn't cached", which would hide them all).
    None if anything is ready, or nothing can be offered."""
    from resources.lib import ranking
    from resources.lib.sources import is_ready
    if any(is_ready(s) for s in sources):
        return None
    allowed = ranking.apply_filter(sources, dict(filter_rules, ready_only=False), media)
    return next((s for s in ranking.sort_sources(allowed, sort_rules) if offered(s)), None)


# -- starting a download ---------------------------------------------------------------------------------------
def folder_id(app, fresh=False):
    """The SpongeTV folder in your Premiumize cloud, made the first time it's needed."""
    key = "premiumize:spongetv_folder"
    if not fresh:
        known = app.store.cache_get(key)
        if known:
            return known
    client = app.premiumize
    found = next((c.get("id") for c in client.folder()["content"]
                  if c.get("type") == "folder" and c.get("name") == FOLDER), None)
    found = found or client.create_folder(FOLDER)
    app.store.cache_set(key, found, FOLDER_KEPT_FOR)
    return found


def existing_folder_id(app):
    """The SpongeTV folder's ID if it exists, without making one (for the tidy-up and the space line)."""
    known = app.store.cache_get("premiumize:spongetv_folder")
    content = app.premiumize.folder()["content"]
    ids = {c.get("id") for c in content if c.get("type") == "folder" and c.get("name") == FOLDER}
    if known in ids:
        return known
    return next(iter(ids), None)


def start(app, source, title, mode):
    """Start the transfer and record it. Returns its transfer ID. Raises PremiumizeError."""
    client = app.premiumize
    src = magnet_for(source)
    try:
        transfer_id = client.create_transfer(src, folder_id(app))
    except PremiumizeError as error:
        if error.kind in ("no_key", "bad_key", "unreachable"):
            raise
        # Most likely the SpongeTV folder was deleted ("target folder not found": Premiumize's error code for
        # that isn't documented, so any refusal counts). Look it up again, making a new one, and try once more.
        kodi.log(f"Caching assistant: Premiumize refused the download ({error}); trying again with the folder looked up afresh")
        transfer_id = client.create_transfer(src, folder_id(app, fresh=True))
    if not transfer_id:
        raise PremiumizeError("failed", "Premiumize gave no transfer ID")
    app.store.download_add(transfer_id, title, source.get("release_title") or "", mode)
    kodi.log(f"Caching assistant: Premiumize is downloading {source.get('release_title')} for {title} ({mode})")
    return transfer_id


# -- following downloads -----------------------------------------------------------------------------------------
def check(app, now=None, only=None):
    """[(download, state, transfer)] for the downloads SpongeTV is following (or just the one with ID only, for
    the window you're waiting in), from one look at Premiumize's transfer list. Records the progress and when it
    last moved; a window's own check also records that it's still there ("checked")."""
    now = now or time.time()
    downloads = [d for d in app.store.downloads() if only is None or d["transfer_id"] == only]
    if not downloads:
        return []
    transfers = {t.get("id"): t for t in app.premiumize.transfers()}
    answer = []
    for download in downloads:
        transfer = transfers.get(download["transfer_id"])
        if transfer is None:
            state = GONE                          # deleted on Premiumize (in Transfers, say)
        elif transfer.get("status") in ("finished", "seeding"):
            state = DONE
        elif transfer.get("status") == "error":
            state = FAILED
        else:
            progress = float(transfer.get("progress") or 0)
            changed = now if progress > download["progress"] else download["changed"]
            fields = {"progress": progress, "changed": changed}
            if only is not None:
                fields["checked"] = now
            app.store.download_update(download["transfer_id"], **fields)
            download = dict(download, **fields)
            state = STUCK if now - changed >= STUCK_AFTER else DOWNLOADING
        answer.append((download, state, transfer))
    return answer


def _give_up(app, download, delete=True):
    app.store.download_remove(download["transfer_id"])
    if delete:
        try:
            app.premiumize.delete_transfer(download["transfer_id"])
        except PremiumizeError as error:
            kodi.log(f"Couldn't delete transfer {download['transfer_id']}: {error}")


def _ended(app, download, state, transfer):
    """Tidy up a download that has ended one way or another. Returns the message to show, or None."""
    if state == DONE:
        app.store.download_remove(download["transfer_id"])
        return kodi.text("cache_ready", title=download["title"])
    if state == GONE:
        app.store.download_remove(download["transfer_id"])
        return None
    reason = (transfer or {}).get("message") or ""
    kodi.log(f"Caching assistant: {download['release']} {state}: {reason}")
    _give_up(app, download)
    return kodi.text("cache_stuck" if state == STUCK else "cache_failed", title=download["title"])


def follow(app, now=None):
    """The background service's check of background downloads. A "wait" download whose window hasn't checked
    for a while (Kodi restarted while you were waiting, say) becomes a background one. Tells you about each
    one that has finished or failed."""
    now = now or time.time()
    for download in app.store.downloads():
        if download["mode"] == "wait" and now - download["checked"] >= ORPHANED_AFTER:
            app.store.download_update(download["transfer_id"], mode="background")
    if not any(d["mode"] == "background" for d in app.store.downloads()):
        return
    for download, state, transfer in check(app, now):
        if download["mode"] != "background" or state == DOWNLOADING:
            continue
        message = _ended(app, download, state, transfer)
        if message:
            kodi.notify(message, 8000)


def background(app, source, title):
    """Download in the background: start it, say so, and leave it to the background service."""
    try:
        start(app, source, title, "background")
    except PremiumizeError as error:
        _tell(error)
        return False
    kodi.notify(kodi.text("cache_started", title=title), 6000)
    return True


def wait(app, source, title, resolve):
    """Download and wait in a progress window. resolve(source) gives the link once Premiumize has it.
    Returns the link, or None (cancelled, failed, or Kodi closing: then it carries on in the background)."""
    try:
        transfer_id = start(app, source, title, "wait")
    except PremiumizeError as error:
        _tell(error)
        return None
    dialog = xbmcgui.DialogProgress()
    dialog.create(kodi.text("cache_waiting", title=title), source.get("release_title") or "")
    monitor = xbmc.Monitor()
    try:
        while True:
            if dialog.iscanceled():
                kodi.log(f"Caching assistant: cancelled {source.get('release_title')}")
                _give_up(app, {"transfer_id": transfer_id})
                return None
            try:
                found = check(app, only=transfer_id)
            except PremiumizeError as error:
                kodi.log(f"Caching assistant: couldn't check progress: {error}")
                found = []
            if found:
                download, state, transfer = found[0]
                if state == DOWNLOADING:
                    message = (transfer or {}).get("message") or ""
                    dialog.update(int(download["progress"] * 100),
                                  kodi.text("cache_progress", percent=int(download["progress"] * 100),
                                            name=source.get("release_title") or "", message=message))
                else:
                    text = _ended(app, download, state, transfer)
                    if state != DONE:
                        if text:
                            xbmcgui.Dialog().ok(kodi.text("tools_premiumize"), text)
                        return None
                    dialog.close()
                    try:
                        return resolve(source)
                    except PremiumizeError as error:
                        kodi.log(f"Caching assistant: downloaded, but couldn't get the link: {error}")
                        kodi.notify(kodi.text("cache_ready", title=title))
                        return None
            if monitor.waitForAbort(WAIT_CHECK_EVERY):
                app.store.download_update(transfer_id, mode="background")   # Kodi is closing: follow it later
                return None
    finally:
        dialog.close()


def _tell(error):
    from resources.lib.tools import premiumize_message
    kodi.log(f"Caching assistant: couldn't start the download: {error}")
    xbmcgui.Dialog().ok(kodi.text("tools_premiumize"), premiumize_message(error))


# -- the tidy-up (Release 2, stage 3) -----------------------------------------------------------------------------
TIDY_DAYS = (7, 14, 30, 60, 90)       # the choices in Settings, in order
TIDY_EVERY = 86400


def tidy_days():
    index = kodi.setting_int("premiumize.tidy_days")
    return TIDY_DAYS[index] if 0 <= index < len(TIDY_DAYS) else 30


def tidy(app, now=None, days=None):
    """Delete what's in the SpongeTV folder (files and folders, a season pack's say) older than the given days,
    then clear the finished transfers that went into it. Only ever touches the SpongeTV folder and its transfers;
    downloads still in progress have nothing in the folder yet, and their transfers are left alone.
    Returns how many things were deleted."""
    now = now or time.time()
    days = days or tidy_days()
    client = app.premiumize
    folder = existing_folder_id(app)
    if not folder:
        return 0
    content = client.folder(folder)["content"]
    cutoff = now - days * 86400
    deleted = 0
    for entry in content:
        created = entry.get("created_at")
        if not created or float(created) >= cutoff:
            continue
        try:
            if entry.get("type") == "folder":
                client.delete_folder(entry["id"])
            else:
                client.delete_item(entry["id"])
            deleted += 1
            kodi.log(f"Tidy-up: deleted {entry.get('name')} from the SpongeTV folder")
        except PremiumizeError as error:
            kodi.log(f"Tidy-up: couldn't delete {entry.get('name')}: {error}")
    ours = {folder} | {e.get("id") for e in content if e.get("type") == "folder"}
    following = {d["transfer_id"] for d in app.store.downloads()}
    for transfer in client.transfers():
        if (transfer.get("status") in ("finished", "seeding") and transfer.get("folder_id") in ours
                and transfer.get("id") not in following):
            try:
                client.delete_transfer(transfer["id"])
            except PremiumizeError as error:
                kodi.log(f"Tidy-up: couldn't clear transfer {transfer.get('name')}: {error}")
    return deleted


def daily_tidy(app, now=None):
    """The background service's call: at most once a day, and only with the setting on."""
    now = now or time.time()
    if not kodi.setting_bool("premiumize.tidy") or not app.premiumize.ready:
        return None
    if now - float(app.store.get_meta("premiumize:last_tidy") or 0) < TIDY_EVERY:
        return None
    app.store.set_meta("premiumize:last_tidy", str(now))
    return run_tidy(app, now)


def run_tidy(app, now=None, say_nothing_deleted=False):
    """Tidy now, record it for the "Last tidy-up" line and say what went. Used by the daily run and by
    Tidy up now (which leaves the daily run's timing alone)."""
    now = now or time.time()
    deleted = tidy(app, now)
    app.store.set_meta("premiumize:last_tidy_result", json.dumps({"at": now, "deleted": deleted}))
    if deleted:
        kodi.notify(kodi.text("pm_tidied_one") if deleted == 1 else kodi.text("pm_tidied", count=deleted), 6000)
    elif say_nothing_deleted:
        kodi.notify(kodi.text("pm_tidied_none", days=tidy_days()))
    return deleted


def last_tidy_line(app):
    """For Tools > Premiumize while the tidy-up is on: "Last tidy-up: 20 November 2026, 00:12 · 1 deleted"."""
    try:
        last = json.loads(app.store.get_meta("premiumize:last_tidy_result") or "null")
    except ValueError:
        last = None
    if not last:
        return kodi.text("pm_last_tidy_none")
    import datetime
    from resources.lib import status
    when = datetime.datetime.fromtimestamp(float(last["at"]))
    return kodi.text("pm_last_tidy", when=f"{status.nice_date(when.date().isoformat())}, {when:%H:%M}",
                     count=int(last.get("deleted") or 0))
