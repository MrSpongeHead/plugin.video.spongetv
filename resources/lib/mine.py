# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Your Trakt menus: My Films, My TV Shows (with Next Up), recommendations and Trakt lists.

Collection, watchlist, favourites, watched and progress come from the local library (kept up to
date by the sync), so they open without asking Trakt. Calendars, recommendations and lists are
read from Trakt when you open them, and cached briefly.
"""

import datetime
from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcgui

from resources.lib import airtime, kodi, listing, menus, options, shows
from resources.lib.http import HttpError
from resources.lib.marks import Marks, aired_counts, fully_watched

PER_PAGE = 20
CALENDAR_DAYS = 14
LIST_CACHE = 15 * 60


def _page(plugin, ids):
    page = plugin.int_param("page", 1)
    total = max(1, -(-len(ids) // PER_PAGE))
    chunk = ids[(page - 1) * PER_PAGE: page * PER_PAGE]
    return {"page": page, "total_pages": total, "results": [{"id": i} for i in chunk]}


def _need_sign_in(plugin):
    kodi.notify(kodi.text("trakt_not_signed_in"))
    plugin.fail()


# -- top-level menus -----------------------------------------------------------------------
def my_movies(plugin, app):
    entries = [("my_collection", "collection"), ("my_watchlist", "watchlist"), ("my_favourites", "favourites"),
               ("my_watched", "watched"), ("my_in_progress", "playback")]
    items = [menus.folder(plugin, label, action="library_titles", media="movie", part=part) for label, part in entries]
    items.append(menus.folder(plugin, "recommended", action="recommended", media="movie"))
    plugin.finish(items, category=kodi.text("my_movies"))


def my_tv(plugin, app):
    items = [menus.folder(plugin, "next_up", action="next_up"),
             menus.folder(plugin, "my_shows_in_progress", action="shows_in_progress"),
             menus.folder(plugin, "upcoming_episodes", action="calendar", when="upcoming"),
             menus.folder(plugin, "recent_episodes", action="calendar", when="recent"),
             menus.folder(plugin, "recently_watched", action="library_titles", media="tv", part="watched")]
    for label, part in (("my_collection", "collection"), ("my_watchlist", "watchlist"), ("my_favourites", "favourites")):
        items.append(menus.folder(plugin, label, action="library_titles", media="tv", part=part))
    items.append(menus.folder(plugin, "recommended", action="recommended", media="tv"))
    plugin.finish(items, category=kodi.text("my_tv"))


# -- lists from the local library ----------------------------------------------------------------
def library_titles(plugin, app):
    if not app.signed_in:
        return _need_sign_in(plugin)
    media, part = plugin.params.get("media", "movie"), plugin.params.get("part", "watchlist")
    library = app.library
    if media == "movie":
        ids = library.ids(part, "movie")
    elif part == "watched":
        ids = [show for show, _ in library.watched_shows()]
    elif part == "collection":
        ids = library.collected_shows()
    else:
        ids = library.ids(part, "show")
    menus.show_titles(plugin, app, media, _page(plugin, ids), None, action="library_titles", media=media, part=part)


def _show_details(app, show_ids):
    def load(show_id):
        try:
            return app.tmdb.tv(show_id)
        except HttpError as error:
            kodi.log(f"Show {show_id} unavailable: {error}")
            return None
    with ThreadPoolExecutor(max_workers=menus.workers()) as pool:
        return [d for d in pool.map(load, show_ids) if d]


def shows_in_progress(plugin, app):
    """Shows you've started but not finished (leaving out ones hidden from progress or dropped)."""
    if not app.signed_in:
        return _need_sign_in(plugin)
    library = app.library
    skipped = library.skipped_shows()
    started = [show for show, _ in library.watched_shows() if show not in skipped]
    marks = Marks(library)
    ids = [d["id"] for d in _show_details(app, started) if not fully_watched(*marks.show(d))]
    if not ids:
        kodi.notify(kodi.text("next_up_empty" if started else "next_up_no_history"))
    menus.show_titles(plugin, app, "tv", _page(plugin, ids), None, action="shows_in_progress")


# -- Next Up --------------------------------------------------------------------------------------
def next_episode(details, watched):
    """The first aired, unwatched episode after the one you watched most recently, or None.

    watched: {(season, episode): (plays, last watched)}. Specials are ignored."""
    regular = {k: v for k, v in watched.items() if k[0]}
    if not regular:
        return None
    last = max(regular, key=lambda k: (regular[k][1] or "", k))
    counts = aired_counts(details)
    season, episode = last
    while True:
        episode += 1
        if episode > counts.get(season, 0):
            later = [s for s in sorted(counts) if s > season and counts[s]]
            if not later:
                return None
            season, episode = later[0], 1
        if (season, episode) not in regular:
            return season, episode


def next_up_entries(app):
    """[(show details, season, episode, last watched)] in your chosen order."""
    library = app.library
    skipped = library.skipped_shows()
    watched_shows = [(show, at) for show, at in library.watched_shows() if show not in skipped]
    last_watched = dict(watched_shows)
    entries = []
    details_found = _show_details(app, [show for show, _ in watched_shows])
    for details in details_found:
        found = next_episode(details, library.watched_episodes(details["id"]))
        if found:
            entries.append((details, found[0], found[1], last_watched.get(details["id"], "")))
    kodi.log(f"Next up: {len(watched_shows) + len(skipped)} shows with watched episodes, {len(skipped)} hidden or "
             f"dropped, {len(details_found)} found on TMDB, {len(entries)} with an episode to watch next")
    if kodi.setting_int("nextup.sort") == 1:   # newest air date first
        entries.sort(key=lambda e: ((e[0].get("last_air_date") or ""), e[3]), reverse=True)
    else:                                      # most recently watched first
        entries.sort(key=lambda e: e[3], reverse=True)
    return entries


def next_up(plugin, app):
    if not app.signed_in:
        return _need_sign_in(plugin)
    entries = next_up_entries(app)
    if not entries:
        kodi.notify(kodi.text("next_up_empty" if app.library.watched_shows() else "next_up_no_history"))
    page = plugin.int_param("page", 1)
    chunk = entries[(page - 1) * PER_PAGE: page * PER_PAGE]
    items = _episode_rows(plugin, app, [(d, s, e) for d, s, e, _ in chunk])
    total = max(1, -(-len(entries) // PER_PAGE))
    items += menus._next_page(plugin, {"page": page, "total_pages": total}, action="next_up")
    plugin.finish(items, content="episodes", category=kodi.text("next_up"), view_setting="view.episodes", cache=False)


def _episode_rows(plugin, app, wanted):
    """List items for (show details, season, episode[, when]) entries, keeping their order.
    when, if given, goes at the start of the line ("Tomorrow 02:00 · Show: S01E05 …")."""
    def build(entry):
        details, season, episode = entry[:3]
        when = entry[3] if len(entry) > 3 else ""
        rows = shows._episode_items(plugin, app, details, shows._show_art(app, details), [season],
                                    only={(season, episode)}, show_in_label=True)
        if not rows:
            return None
        if when:
            rows[0][1].setLabel(f"{when} \u00b7 {rows[0][1].getLabel()}")
        return rows[0]
    with ThreadPoolExecutor(max_workers=menus.workers()) as pool:
        return [r for r in pool.map(build, wanted) if r]


# -- calendars ------------------------------------------------------------------------------------
def calendar(plugin, app):
    """Upcoming: the next fortnight. Recent: the last fortnight. From the shows you watch on Trakt."""
    if not app.signed_in:
        return _need_sign_in(plugin)
    when = plugin.params.get("when", "upcoming")
    today = airtime.local_today()
    start = today if when == "upcoming" else today - datetime.timedelta(days=CALENDAR_DAYS)
    entries = _cached(app, f"trakt:calendar:{start}", lambda: app.trakt.get(
        f"/calendars/my/shows/{start.isoformat()}/{CALENDAR_DAYS}", auth=True) or [])
    if when == "recent":
        entries = list(reversed(entries))
    wanted, details_by_id = [], {}
    words = {k: kodi.text(k) for k in ("today", "tomorrow", "yesterday")}
    show_ids = list(dict.fromkeys(((e.get("show") or {}).get("ids") or {}).get("tmdb") for e in entries))
    for details in _show_details(app, [s for s in show_ids if s]):
        details_by_id[details["id"]] = details
    for entry in entries:
        show_id = ((entry.get("show") or {}).get("ids") or {}).get("tmdb")
        episode = entry.get("episode") or {}
        if show_id in details_by_id:
            when = airtime.when_label(entry.get("first_aired"), words)
            wanted.append((details_by_id[show_id], episode.get("season"), episode.get("number"), when))
    items = _episode_rows(plugin, app, wanted)
    label = "upcoming_episodes" if when == "upcoming" else "recent_episodes"
    plugin.finish(items, content="episodes", category=kodi.text(label), view_setting="view.episodes")


def _cached(app, key, fetch, ttl=LIST_CACHE):
    data = app.store.cache_get(key)
    if data is None:
        data = fetch()
        app.store.cache_set(key, data, ttl)
    return data


# -- recommendations ---------------------------------------------------------------------------------
def recommended(plugin, app):
    if not app.signed_in:
        return _need_sign_in(plugin)
    media = plugin.params.get("media", "movie")
    kind = "movies" if media == "movie" else "shows"
    entries = _cached(app, f"trakt:recommended:{kind}", lambda: app.trakt.get(
        f"/recommendations/{kind}", {"limit": 100, "ignore_collected": "true", "ignore_watchlisted": "true"},
        auth=True) or [])
    ids = [(e.get("ids") or {}).get("tmdb") for e in entries]
    hide_menu = "movie_lists" if media == "movie" else "tv_lists"
    menus.show_titles(plugin, app, media, _page(plugin, [i for i in ids if i]), hide_menu,
                      action="recommended", media=media)


# -- Trakt lists -------------------------------------------------------------------------------------
LIST_SOURCES = [("my_lists", "/users/me/lists", True), ("liked_lists", "/users/likes/lists", True),
                ("trending_lists", "/lists/trending", False), ("popular_lists", "/lists/popular", False)]
# Trending and popular lists run to thousands of pages: read them one page at a time as you browse.
PAGED_SOURCES = {"/lists/trending", "/lists/popular"}
LISTS_PER_PAGE = 50


def _more_page(plugin, page, **params):
    """A "Next page" item for lists whose total Trakt doesn't promise to tell us."""
    url = plugin.url(**dict(params, page=page + 1))
    label = options.highlight(kodi.text("next_page_plain", page=page + 1))
    return [(url, listing.folder_item(label, kodi.ICON, kodi.FANART), True)]


def trakt_lists(plugin, app):
    items = []
    if app.signed_in:
        items.append((plugin.url(action="create_list"),
                      listing.folder_item(options.highlight(kodi.text("create_list")), kodi.ICON, kodi.FANART), False))
    for index, (label, _, needs_sign_in) in enumerate(LIST_SOURCES):
        if needs_sign_in and not app.signed_in:
            continue
        items.append(menus.folder(plugin, label, action="lists", source=index))
    plugin.finish(items, category=kodi.text("trakt_lists"))


def lists(plugin, app):
    index = plugin.int_param("source", 0)
    label, path, needs_sign_in = LIST_SOURCES[index]
    if needs_sign_in and not app.signed_in:
        return _need_sign_in(plugin)
    page = plugin.int_param("page", 1)
    if path in PAGED_SOURCES:
        entries = _cached(app, f"trakt:lists:{path}:{page}", lambda: app.trakt.get(
            path, {"page": page, "limit": LISTS_PER_PAGE}) or [])
    else:
        entries = _cached(app, f"trakt:lists:{path}", lambda: app.trakt.get_all(path, auth=app.signed_in))
    items = []
    own = path == "/users/me/lists"
    for entry in entries:
        trakt_list = entry.get("list", entry)   # liked/trending/popular wrap the list
        user = ((trakt_list.get("user") or {}).get("ids") or {}).get("slug") or "me"
        list_id = (trakt_list.get("ids") or {}).get("trakt")
        if not list_id:
            continue
        name = kodi.text("list_with_count", name=trakt_list.get("name", ""), count=trakt_list.get("item_count", 0))
        url = plugin.url(action="list_items", user=user, list_id=list_id)
        item = listing.folder_item(name, kodi.ICON, kodi.FANART, trakt_list.get("description") or "")
        if own:
            rename = plugin.url(action="rename_list", list_id=list_id)
            item.addContextMenuItems([(kodi.text("rename_list"), f"RunPlugin({rename})")])
        items.append((url, item, True))
    if path in PAGED_SOURCES and len(entries) >= LISTS_PER_PAGE:
        items += _more_page(plugin, page, action="lists", source=index)
    plugin.finish(items, category=kodi.text(label))


def list_items(plugin, app):
    """A list's films and shows in the list's own order (Trakt sorts it), one Trakt page per screen,
    so even a list of thousands opens straight away."""
    user, list_id = plugin.params.get("user", "me"), plugin.params.get("list_id")
    page = plugin.int_param("page", 1)
    path = f"/users/{user}/lists/{list_id}/items"
    entries = _cached(app, f"trakt:list:{user}:{list_id}:{page}", lambda: app.trakt.get(
        path, {"page": page, "limit": PER_PAGE}, auth=app.signed_in) or [])
    ordered = [(e.get("type"), ((e.get(e.get("type")) or {}).get("ids") or {}).get("tmdb")) for e in entries]
    ordered = [(kind, i) for kind, i in ordered if kind in ("movie", "show") and i]
    built = {}
    for kind, media in (("movie", "movie"), ("show", "tv")):
        ids = [i for k, i in ordered if k == kind]
        built[kind] = iter(menus.title_items(plugin, app, media, [{"id": i} for i in ids]))
    items = [i for i in (next(built[k], None) for k, _ in ordered) if i]
    if len(entries) >= PER_PAGE:
        items += _more_page(plugin, page, action="list_items", user=user, list_id=list_id)
    plugin.finish(items, content="videos")


def create_list(plugin, app):
    name = (xbmcgui.Dialog().input(kodi.text("new_list_name")) or "").strip()
    if not name:
        return
    app.trakt.post("/users/me/lists", {"name": name, "privacy": "private"})
    app.store.cache_set("trakt:lists:/users/me/lists", None, 0)
    kodi.notify(kodi.text("list_created", name=name))
    xbmc.executebuiltin("Container.Refresh")


def rename_list(plugin, app):
    list_id = plugin.params.get("list_id")
    name = (xbmcgui.Dialog().input(kodi.text("rename_list")) or "").strip()
    if not name:
        return
    app.trakt.put(f"/users/me/lists/{list_id}", {"name": name})
    app.store.cache_set("trakt:lists:/users/me/lists", None, 0)
    kodi.notify(kodi.text("list_renamed", name=name))
    xbmc.executebuiltin("Container.Refresh")


def my_lists_for_picker(app):
    """[(list ID, name)] of your own lists, for "Add to list"."""
    entries = _cached(app, "trakt:lists:/users/me/lists", lambda: app.trakt.get_all("/users/me/lists"))
    return [((e.get("ids") or {}).get("trakt"), e.get("name", "")) for e in entries or [] if (e.get("ids") or {}).get("trakt")]

