# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Tools > Premiumize: your account at a glance and your transfers (Release 2, stage 1).

A transfer is something Premiumize is fetching into your cloud. Finished ones open to their files, which play
straight from your cloud. Nothing here is linked to a film or episode, so it isn't scrobbled to Trakt.
"""

import xbmc
import xbmcgui

from resources.lib import kodi, listing
from resources.lib.premiumize import PremiumizeError, is_video

STATUS = {"queued": "pm_queued", "running": "pm_downloading", "seeding": "pm_finished",
          "finished": "pm_finished", "error": "pm_failed"}
DONE = ("finished", "seeding")
IN_PROGRESS = ("queued", "running")


def _error(error):
    from resources.lib.tools import premiumize_message
    kodi.log(f"Premiumize: {error}")
    kodi.notify(premiumize_message(error))


def size_text(size):
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def _account_line(app):
    """("Premium for 30 more days · fair use 25% used", ok) from Premiumize, or its error message."""
    client = app.premiumize
    try:
        account = client.account()
    except PremiumizeError as error:
        from resources.lib.tools import premiumize_message
        return premiumize_message(error)
    days = client.days_left(account)
    used = round(account["limit_used"] * 100)
    if days is None:
        return kodi.text("pm_account_free", used=used)
    app.store.cache_set("premiumize:days_left", days, 3600)
    return kodi.text("pm_account_line", days=days, used=used)


def menu(plugin, app):
    if not app.premiumize.ready:
        kodi.notify(kodi.text("pm_no_key"))
        items = [(plugin.url(action="premiumize_sign_in"),
                  listing.folder_item(kodi.text("pm_sign_in"), kodi.ICON, kodi.FANART), False)]
        plugin.finish(items, category=kodi.text("tools_premiumize"), cache=False)
        return
    items = [
        (plugin.url(action="premiumize_status"),
         listing.folder_item(_account_line(app), kodi.ICON, kodi.FANART), False),
        (plugin.url(action="pm_transfers"), listing.folder_item(kodi.text("pm_transfers"), kodi.ICON, kodi.FANART), True),
    ]
    plugin.finish(items, category=kodi.text("tools_premiumize"), cache=False)


def _transfer_label(transfer):
    status = transfer.get("status") or ""
    text = kodi.text(STATUS.get(status, "pm_queued"))
    if status == "running":
        text += f" {round(float(transfer.get('progress') or 0) * 100)}%"
    return f"{text} · {transfer.get('name') or '?'}"


def _transfer_menu(plugin, transfer):
    entries = []
    status = transfer.get("status")
    tid, name = transfer.get("id"), transfer.get("name") or ""
    if status == "error":
        entries.append((kodi.text("pm_retry"), f"RunPlugin({plugin.url(action='pm_retry', id=tid)})"))
    entries.append((kodi.text("pm_delete_transfer"),
                    f"RunPlugin({plugin.url(action='pm_delete', id=tid, status=status, name=name)})"))
    entries.append((kodi.text("pm_clear_finished"), f"RunPlugin({plugin.url(action='pm_clear')})"))
    entries.append((kodi.text("pm_refresh"), "Container.Refresh"))
    return entries


def transfers(plugin, app):
    try:
        found = app.premiumize.transfers()
    except PremiumizeError as error:
        _error(error)
        plugin.fail()
        return
    if not found:
        kodi.notify(kodi.text("pm_transfers_none"))
    items = []
    for transfer in found:
        status = transfer.get("status")
        item = listing.folder_item(_transfer_label(transfer), kodi.ICON, kodi.FANART,
                                   plot=transfer.get("message") or "")
        listing.add_to_menu(item, _transfer_menu(plugin, transfer))
        if status in DONE and transfer.get("file_id"):
            item.setProperty("IsPlayable", "true")
            items.append((plugin.url(action="pm_play", id=transfer["file_id"]), item, False))
        elif status in DONE and transfer.get("folder_id"):
            items.append((plugin.url(action="pm_folder", id=transfer["folder_id"]), item, True))
        else:
            # still going, or failed: selecting it shows the latest progress
            items.append((plugin.url(action="pm_refresh"), item, False))
    plugin.finish(items, category=kodi.text("pm_transfers"), cache=False)


def folder(plugin, app):
    """A folder in your cloud: subfolders, then the videos in it (other files, such as subtitles, are left out)."""
    try:
        found = app.premiumize.folder(plugin.params.get("id"))
    except PremiumizeError as error:
        _error(error)
        plugin.fail()
        return
    content = found["content"]
    folders = [c for c in content if c.get("type") == "folder"]
    videos = [c for c in content if c.get("type") == "file" and is_video(c.get("name") or "")]
    items = []
    for sub in sorted(folders, key=lambda c: (c.get("name") or "").lower()):
        items.append((plugin.url(action="pm_folder", id=sub.get("id")),
                      listing.folder_item(sub.get("name") or "?", kodi.ICON, kodi.FANART), True))
    for video in sorted(videos, key=lambda c: (c.get("name") or "").lower()):
        item = listing.folder_item(video.get("name") or "?", kodi.ICON, kodi.FANART, plot=size_text(video.get("size")))
        item.setProperty("IsPlayable", "true")
        items.append((plugin.url(action="pm_play", id=video.get("id")), item, False))
    plugin.finish(items, category=found["name"] or kodi.text("tools_premiumize"), cache=False)


def play(plugin, app):
    """Play one file from your cloud."""
    try:
        link = app.premiumize.cloud_link(plugin.params.get("id"))
    except PremiumizeError as error:
        _error(error)
        link = None
    if not link:
        plugin.resolve_nothing()
        return
    plugin.resolve(xbmcgui.ListItem(path=link, offscreen=True))


def _act(action, done_key):
    try:
        action()
    except PremiumizeError as error:
        _error(error)
        return
    kodi.notify(kodi.text(done_key))
    xbmc.executebuiltin("Container.Refresh")


def retry(plugin, app):
    _act(lambda: app.premiumize.retry_transfer(plugin.params.get("id")), "pm_done_retry")


def delete(plugin, app):
    if plugin.params.get("status") in IN_PROGRESS and not xbmcgui.Dialog().yesno(
            kodi.text("tools_premiumize"), kodi.text("pm_delete_running", name=plugin.params.get("name") or "")):
        return
    _act(lambda: app.premiumize.delete_transfer(plugin.params.get("id")), "pm_done_delete")


def clear_finished(plugin, app):
    _act(app.premiumize.clear_finished, "pm_done_clear")


def refresh(plugin, app):
    xbmc.executebuiltin("Container.Refresh")
