# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""SpongeTV's own windows: source search progress and Source Select, plus simple-dialog versions.

The windows are Kodi skin files in resources/skins/Default/1080i. If one can't be opened, or you've
chosen simple dialogs in Settings, Kodi's standard progress and list dialogs are used instead.
"""

import time

import xbmc
import xbmcgui

from resources.lib import kodi, ranking
from resources.lib.sources import is_ready

SEARCH_AGAIN = "search again"   # what choose_source returns when you ask for a fresh search
BACK_ACTIONS = {9, 10, 92, 216, 247, 257, 275, 61467, 61448}
CONTEXT_ACTIONS = {117}
INFO_ACTIONS = {11}
SEARCH_XML = "spongetv-sourcesearch.xml"
SELECT_XML = "spongetv-sourceselect.xml"


def use_simple():
    return kodi.setting_bool("windows.simple")


def close_busy():
    """Kodi shows a spinner while a video is waiting to start; it would sit over SpongeTV's windows."""
    xbmc.executebuiltin("Dialog.Close(busydialog)")
    xbmc.executebuiltin("Dialog.Close(busydialognocancel)")


def _elapsed(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def searching_line(status):
    """'Still searching: 3 providers · Premiumize cloud finished'."""
    names = [n for n in status["searching"] if n != CLOUD_NAME]
    parts = []
    if names:
        parts.append(kodi.text("still_searching_n", count=len(names)))
    cloud = status.get("cloud")
    if cloud and (parts or cloud == "searching"):
        parts.append(kodi.text("cloud_searching" if cloud == "searching" else "cloud_finished"))
    if not parts:
        return ""
    return kodi.text("still_searching", names=" \u00b7 ".join(parts))


CLOUD_NAME = "Your cloud"


def providers_line(status):
    """'4 of 7 providers finished', and how many found sources your filter hides, so the counts add up."""
    line = kodi.text("providers_finished", done=status["done"], total=status["total"])
    # sources Premiumize hasn't answered for yet are neither shown nor hidden yet
    hidden = status["found"] - status.get("choosable", status["found"]) - (status.get("checking") or 0)
    return line + kodi.text("hidden_by_filter", count=hidden) if hidden > 0 else line


def ready_line(status):
    """How many can play straight away, saying so while Premiumize is still being asked."""
    if status.get("ready") is None:
        return ""
    if status.get("check_failed"):
        return kodi.text("ready_check_failed")
    checking = status.get("checking") or 0
    if checking and not status["ready"]:
        return kodi.text("ready_checking", count=checking)
    if checking:
        return kodi.text("ready_now_checking", count=status["ready"], more=checking)
    return kodi.text("ready_now_explained", count=status["ready"])


CHECK_GRACE = 5   # seconds the window stays after the search, while Premiumize answers about the last sources


def search_properties(status, title, early):
    """What the progress window shows, worked out from Search.status(). Shared by both versions."""
    found = status["found"]
    choosable = status.get("choosable", found)   # what Source Select will show, after your filter
    lines = {
        "heading": kodi.text("finding_sources"),
        "title": title,
        "elapsed": _elapsed(status["elapsed"]),
        "providers_line": providers_line(status),
        "count_4k": str(status["counts"]["4K"]),
        "count_1080p": str(status["counts"]["1080p"]),
        "count_720p": str(status["counts"]["720p"]),
        "count_other": str(status["counts"]["Other"]),
        "other_label": kodi.text("quality_other"),
        "ready_line": ready_line(status),
        "logo": kodi.ICON,
        "early_line": (kodi.text("early_stop_line", got=min(status["early"][0], status["early"][1]),
                                 count=status["early"][1], quality=early.quality)
                       if status["early"] else kodi.text("early_stop_off")),
        "searching_line": searching_line(status),
        "choose_label": kodi.text("choose_from", count=choosable) if choosable else kodi.text("waiting_for_sources"),
        "can_choose": "1" if choosable else "",
        "choose_outline": "FFF5A524" if choosable else "00FFFFFF",   # the amber outline only once it can be chosen
        "cancel_label": kodi.text("cancel"),
    }
    percent = int(100 * status["done"] / status["total"]) if status["total"] else 100
    return lines, percent


class SearchWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.choose_now = False
        self.cancelled = False
        self.choose_tries = 0

    def onClick(self, control_id):
        if control_id == 3001:
            self.choose_now = True
        elif control_id == 3002:
            self.cancelled = True

    def onAction(self, action):
        if action.getId() in BACK_ACTIONS:
            self.cancelled = True


def run_search(search, title, fanart, early, monitor=None):
    """Show progress until the search finishes, you choose early, or you cancel.
    Returns "done", "chosen" or "cancelled"."""
    monitor = monitor or xbmc.Monitor()
    if not use_simple():
        try:
            return _run_search_window(search, title, fanart, early, monitor)
        except RuntimeError as error:   # the skin file couldn't be opened: fall back
            kodi.log_error(f"Source search window unavailable: {error}")
    return _run_search_simple(search, title, early, monitor)


def focus_buttons(window, can_choose):
    """Kodi can't focus "Choose from N found" while it's disabled (nothing found yet), so the window would
    open with nothing focused and OK would do nothing. Focus Cancel at first, then move to Choose once
    there's something to choose. Kodi enables the button on its next screen refresh, so moving there can
    fail the first time: keep trying for a couple of seconds, until Choose has the focus."""
    try:
        focused = window.getFocusId()
    except (RuntimeError, TypeError):
        focused = 0
    if focused == 3001:
        window.choose_tries = CHOOSE_TRIES          # done: from now on, focus is yours to move
    if can_choose and window.choose_tries < CHOOSE_TRIES and focused in (0, 3002):
        window.choose_tries += 1
        window.setFocusId(3001)
    elif focused not in (3001, 3002):
        window.setFocusId(3002)


CHOOSE_TRIES = 10   # polls (a fifth of a second each)


def _run_search_window(search, title, fanart, early, monitor):
    window = SearchWindow(SEARCH_XML, kodi.ADDON_PATH, "Default", "1080i")
    window.setProperty("fanart", fanart or "")
    window.show()
    outcome = "done"
    finished_at = None
    try:
        while not monitor.abortRequested():
            status = search.status()
            lines, percent = search_properties(status, title, early)
            for key, value in lines.items():
                window.setProperty(key, value)
            try:
                window.getControl(3100).setPercent(percent)
            except (RuntimeError, TypeError):
                pass
            focus_buttons(window, bool(lines["can_choose"]))
            if window.cancelled:
                search.cancel()
                outcome = "cancelled"
                break
            if window.choose_now:
                search.stop_now()
                outcome = "chosen"
                break
            if status["finished"]:
                finished_at = finished_at or time.monotonic()
                if not status.get("checking") or time.monotonic() - finished_at > CHECK_GRACE:
                    break
            if monitor.waitForAbort(0.2):
                break
    finally:
        window.close()
        del window
    return outcome


def _run_search_simple(search, title, early, monitor):
    dialog = xbmcgui.DialogProgress()
    dialog.create(kodi.text("finding_sources"), title)
    outcome = "done"
    try:
        while not monitor.abortRequested():
            status = search.status()
            lines, percent = search_properties(status, title, early)
            dialog.update(percent, "[CR]".join(x for x in (title, lines["providers_line"], kodi.text(
                "found_so_far", count=status.get("choosable", status["found"])), lines["early_line"]) if x))
            if dialog.iscanceled():
                if status.get("choosable", status["found"]):
                    search.stop_now()
                    outcome = "chosen"
                else:
                    search.cancel()
                    outcome = "cancelled"
                break
            if status["finished"] or monitor.waitForAbort(0.2):
                break
    finally:
        dialog.close()
    return outcome


# -- Source Select ----------------------------------------------------------------------------------
def status_of(source):
    """(words, kind) for the Status column."""
    if source.get("debrid") == "cloud":
        return kodi.text("status_cloud"), "cloud"
    if source.get("debrid") == "cached":
        return kodi.text("status_cached"), "cached"
    if source.get("debrid") == "uncached":
        return kodi.text("status_uncached"), "uncached"
    if source["type"] in ("direct", "adaptive"):
        return kodi.text("status_direct"), "cached"
    return kodi.text("status_unchecked"), "unchecked"


def details_line(source):
    parts = list(source.get("tags") or [])
    if source.get("pack") in ("season", "show"):
        parts.append(kodi.text("pack_" + source["pack"]))
    if source["type"] == "torrent" and source.get("seeds"):
        parts.append(kodi.text("seeds", count=source["seeds"]))
    return " · ".join(parts)


AMBER, TEAL, MINT, MUTED, NAVY_DEEP, TEXT = "FFF5A524", "FF2EC4B6", "FFDFFAF6", "FF8FA6C4", "FF0A1428", "FFEAF2FB"
BADGES = {"4K": (AMBER, NAVY_DEEP), "1080p": (TEAL, NAVY_DEEP), "720p": ("FF2C4468", TEXT)}
STATUS_COLOURS = {"cloud": MINT, "cached": TEAL, "uncached": MUTED, "unchecked": MUTED}


def list_item(source):
    item = xbmcgui.ListItem(source.get("release_title") or source.get("url", ""), details_line(source), offscreen=True)
    words, kind = status_of(source)
    badge_bg, badge_fg = BADGES.get(source["quality"], ("FF3A4A60", TEXT))
    item.setProperty("quality", source["quality"])
    item.setProperty("badge_bg", badge_bg)
    item.setProperty("badge_fg", badge_fg)
    item.setProperty("size", ranking.size_text(source.get("size_mb")))
    item.setProperty("status", words)
    item.setProperty("status_kind", kind)
    item.setProperty("status_colour", STATUS_COLOURS[kind])
    item.setProperty("from", kodi.text("from_cloud") if source.get("type") == "cloud" else source.get("provider", ""))
    return item


def simple_label(source):
    words, _ = status_of(source)
    bits = [source["quality"], ranking.size_text(source.get("size_mb")), words, source.get("provider", "")]
    return " · ".join(b for b in bits if b) + "  " + (source.get("release_title") or "")


def select_subheading(title, shown, everything):
    """'The Lighthouse Keeper (2024) · 8 sources · 6 ready to play now', saying when your filter hides some."""
    parts = [title, kodi.text("n_sources", count=len(shown))]
    if any(s.get("debrid") for s in everything):      # Premiumize was asked
        parts.append(kodi.text("ready_now", count=sum(1 for s in shown if is_ready(s))))
    if len(shown) < len(everything):
        parts.append(kodi.text("n_hidden", count=len(everything) - len(shown)))
    return " \u00b7 ".join(parts)


def sort_label(rules):
    """'Sort: ready first', from your first sort rule that's on."""
    first = next((rule for rule, on in rules if on), None)
    return kodi.text("sort_short_" + first) if first else kodi.text("sort_button")


class Chooser:
    """What Source Select needs: all sources, how to filter and sort them, and the menu actions."""

    def __init__(self, sources, media, title, meta, poster, fanart, filter_rules, sort_rules, actions):
        self.all = sources
        self.media = media
        self.title, self.meta, self.poster, self.fanart = title, meta, poster, fanart
        self.filter_rules = filter_rules     # callable -> (label, rules)
        self.sort_rules = sort_rules         # callable -> [(rule, on)]
        self.actions = actions               # {"filter": f(), "sort": f(), "clear": f()}

    def visible(self):
        _, rules = self.filter_rules()
        return ranking.sort_sources(ranking.apply_filter(self.all, rules, self.media), self.sort_rules())

    def why(self, shown, index):
        rules = self.sort_rules()
        source = shown[index]
        lines = [kodi.text("why_position", position=index + 1, total=len(shown))]
        if index:
            rule = ranking.deciding_rule(source, shown[index - 1], rules)
            lines.append(kodi.text("why_below", rule=kodi.text(ranking.RULES[rule][0])) if rule
                         else kodi.text("why_tie"))
        else:
            lines.append(kodi.text("why_top"))
        lines.append("")
        lines.append(kodi.text("why_rules"))
        number = 0
        for rule, on in rules:
            if on:
                number += 1
                lines.append(f"{number}. {kodi.text(ranking.RULES[rule][0])}")
        lines.append("")
        lines.append(kodi.text("why_filter", filter=self.filter_rules()[0]))
        return "[CR]".join(lines)


class SourceSelectWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.chooser = kwargs.get("chooser")
        self.choice = None
        self.shown = []

    def onInit(self):
        self.fill()

    def fill(self):
        chooser = self.chooser
        self.shown = chooser.visible()
        label, _ = chooser.filter_rules()
        values = {
            "heading": kodi.text("choose_a_source"), "logo": kodi.ICON,
            "subheading": select_subheading(chooser.title, self.shown, chooser.all),
            "filter_label": kodi.text("filter_button", name=label),
            "sort_label": sort_label(chooser.sort_rules()),
            "title": chooser.title, "meta": chooser.meta, "poster": chooser.poster or "", "fanart": chooser.fanart or "",
            "play_best": kodi.text("play_best"),
            "col_quality": kodi.text("col_quality"), "col_release": kodi.text("col_release"),
            "col_size": kodi.text("col_size"), "col_status": kodi.text("col_status"), "col_from": kodi.text("col_from"),
            "hints": kodi.text("select_hints"),
        }
        for key, value in values.items():
            self.setProperty(key, value)
        control = self.getControl(1000)
        control.reset()
        control.addItems([list_item(s) for s in self.shown])
        self.setFocusId(1000 if self.shown else 2002)

    def onClick(self, control_id):
        if control_id == 1000 and self.shown:
            self.choice = self.shown[self.getControl(1000).getSelectedPosition()]
            self.close()
        elif control_id == 2001 and self.shown:
            self.choice = self.shown[0]
            self.close()
        elif control_id == 2002:
            if self.chooser.actions["filter"]():
                self.fill()
        elif control_id == 2003:
            if self.chooser.actions["sort"]():
                self.fill()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in BACK_ACTIONS:
            self.close()
        elif action_id in CONTEXT_ACTIONS:
            options = [kodi.text("menu_filter"), kodi.text("menu_sort"), kodi.text("search_again")]
            if self.getFocusId() == 1000 and self.shown:
                options.append(kodi.text("why_heading"))   # for remotes without an Info button
            picked = xbmcgui.Dialog().contextmenu(options)
            if picked == 0 and self.chooser.actions["filter"]():
                self.fill()
            elif picked == 1 and self.chooser.actions["sort"]():
                self.fill()
            elif picked == 2:
                self.choice = SEARCH_AGAIN
                self.close()
            elif picked == 3:
                self.show_why()
        elif action_id in INFO_ACTIONS and self.getFocusId() == 1000 and self.shown:
            self.show_why()

    def show_why(self):
        index = self.getControl(1000).getSelectedPosition()
        xbmcgui.Dialog().textviewer(kodi.text("why_heading"), self.chooser.why(self.shown, index))


def choose_source(chooser):
    """Returns the source you picked, or None."""
    if not use_simple():
        try:
            window = SourceSelectWindow(SELECT_XML, kodi.ADDON_PATH, "Default", "1080i", chooser=chooser)
            window.doModal()
            choice = window.choice
            del window
            return choice
        except RuntimeError as error:
            kodi.log_error(f"Source Select window unavailable: {error}")
    while True:
        shown = chooser.visible()
        label, _ = chooser.filter_rules()
        rows = [kodi.text("simple_filter_sort", name=label)] + [simple_label(s) for s in shown]
        picked = xbmcgui.Dialog().select(kodi.text("select_subheading", title=chooser.title, count=len(shown),
                                                   total=len(chooser.all)), rows)
        if picked < 0:
            return None
        if picked == 0:
            options = [kodi.text("menu_filter"), kodi.text("menu_sort"), kodi.text("search_again")]
            which = xbmcgui.Dialog().select(kodi.text("menu_filter_sort"), options)
            if which == 0:
                chooser.actions["filter"]()
            elif which == 1:
                chooser.actions["sort"]()
            elif which == 2:
                return SEARCH_AGAIN
            continue
        return shown[picked - 1]
