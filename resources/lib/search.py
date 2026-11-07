# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""One search box for films, TV shows and people, with results grouped by type; people's pages."""

from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcgui

from resources.lib import kodi, listing, menus, options

HISTORY = "all"
GROUPS = [("movie", "group_films"), ("tv", "group_tv"), ("person", "group_people")]
PER_PAGE = 20


def search_menu(plugin, app):
    # "New search" is an action, not a folder: it asks for the words, then opens a results folder
    # whose address includes them, so Kodi never reuses an old result list or re-asks on Back.
    items = [(plugin.url(action="new_search"), listing.folder_item(options.highlight(kodi.text("new_search")), kodi.ICON, kodi.FANART), False)]
    for query in app.store.searches(HISTORY):
        items.append((plugin.url(action="search", query=query), listing.folder_item(query, kodi.ICON, kodi.FANART), True))
    items.append((plugin.url(action="clear_search"), listing.folder_item(kodi.text("clear_search_history"), kodi.ICON, kodi.FANART), False))
    plugin.finish(items, category=kodi.text("search"), cache=False)


def new_search(plugin, app):
    query = (xbmcgui.Dialog().input(kodi.text("search_heading")) or "").strip()
    if not query:
        return
    app.store.add_search(HISTORY, query)
    xbmc.executebuiltin(f"Container.Update({plugin.url(action='search', query=query)})")


def search(plugin, app):
    """Searches films, TV shows and people at once and offers one folder per group that matched."""
    query = (plugin.params.get("query") or "").strip()
    if not query:
        plugin.fail()
        return
    app.store.add_search(HISTORY, query)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = dict(zip([m for m, _ in GROUPS], pool.map(lambda g: app.tmdb.search(g[0], query, 1), GROUPS)))
    items = []
    for media, label_key in GROUPS:
        total = int(results[media].get("total_results") or 0)
        if total:
            label = kodi.text(label_key, count=total)
            url = plugin.url(action="search_results", media=media, query=query)
            items.append((url, listing.folder_item(label, kodi.ICON, kodi.FANART), True))
    if not items:
        kodi.notify(kodi.text("nothing_found"))
    plugin.finish(items, category=kodi.text("results_for", query=query))


def search_results(plugin, app):
    media, query, page = plugin.params.get("media", "movie"), (plugin.params.get("query") or "").strip(), plugin.int_param("page", 1)
    if not query or media not in ("movie", "tv", "person"):
        plugin.fail()
        return
    data = app.tmdb.search(media, query, page)
    if media == "person":
        people = [p for p in data.get("results", []) if p.get("id")]
        items = [(plugin.url(action="person", person=p["id"]), listing.person_item(p, kodi.ICON, kodi.FANART), True) for p in people]
        items += menus._next_page(plugin, data, action="search_results", media=media, query=query)
        plugin.finish(items, category=kodi.text("results_for", query=query))
        return
    menus.show_titles(plugin, app, media, data, "search", action="search_results", media=media, query=query)


# -- people -------------------------------------------------------------------------------
def _credits(person, media):
    """A person's titles: acting roles for actors, otherwise their main department's work."""
    data = person.get("movie_credits" if media == "movie" else "tv_credits") or {}
    department = person.get("known_for_department") or "Acting"
    if department == "Acting":
        entries = data.get("cast") or []
    else:
        entries = [c for c in data.get("crew") or [] if c.get("department") == department]
    seen, titles = set(), []
    for entry in sorted(entries, key=lambda e: -(e.get("popularity") or 0)):
        if entry.get("id") and entry["id"] not in seen:
            seen.add(entry["id"])
            titles.append(entry)
    return titles


def person(plugin, app):
    person_id = plugin.params.get("person")
    details = app.tmdb.person(person_id)
    photo = listing.image_url(details.get("profile_path"), "h632") or kodi.ICON
    items = []
    for media, label_key in (("movie", "group_films"), ("tv", "group_tv")):
        count = len(_credits(details, media))
        if count:
            url = plugin.url(action="person_titles", person=person_id, media=media)
            items.append((url, listing.folder_item(kodi.text(label_key, count=count), photo, kodi.FANART,
                                                   details.get("biography", "")), True))
    plugin.finish(items, category=details.get("name", ""))


def person_titles(plugin, app):
    person_id, media, page = plugin.params.get("person"), plugin.params.get("media", "movie"), plugin.int_param("page", 1)
    titles = _credits(app.tmdb.person(person_id), media)
    total_pages = max(1, -(-len(titles) // PER_PAGE))
    page_data = {"page": page, "total_pages": total_pages,
                 "results": titles[(page - 1) * PER_PAGE: page * PER_PAGE]}
    hide_menu = "movie_lists" if media == "movie" else "tv_lists"
    menus.show_titles(plugin, app, media, page_data, hide_menu, action="person_titles", person=person_id, media=media)
