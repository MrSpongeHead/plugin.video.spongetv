# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Browsing menus: home, films, TV shows, discovery lists, networks, streaming services, related titles."""

import datetime
from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcgui

from resources.lib import airtime, artwork, kodi, listing, options
from resources.lib.http import HttpError
from resources.lib.marks import Marks, fully_watched
from resources.lib.tmdb import image_url

MAX_PAGES = 500  # TMDB never serves pages beyond this
NEW_SHOW_DAYS = 90

# TV networks offered under TV shows. Names and logos come from TMDB when the menu opens,
# so each entry is always labelled with what TMDB holds for that ID.
NETWORKS = [213, 1024, 2552, 2739, 49, 3186, 453, 4330, 3353, 4, 332, 9, 26, 1063, 174, 88, 6, 16, 2, 19,
            67, 318, 71]


def workers():
    return min(max(kodi.setting_int("perf.workers") or 8, 2), 16)


def folder(plugin, label_key, icon=None, **params):
    return plugin.url(**params), listing.folder_item(kodi.text(label_key), icon or kodi.ICON, kodi.FANART), True


def _next_page(plugin, data, **params):
    page = int(data.get("page") or 1)
    total = min(int(data.get("total_pages") or 1), MAX_PAGES)
    if page >= total:
        return []
    url = plugin.url(**dict(params, page=page + 1))
    label = options.highlight(kodi.text("next_page", page=page + 1, total=total))
    return [(url, listing.folder_item(label, kodi.ICON, kodi.FANART), True)]


# -- top level ---------------------------------------------------------------------
def home(plugin, app):
    order, hidden_items = options.home_layout(app.store)
    signed_in, has_app = app.signed_in, app.trakt.configured
    items = []
    for key in order:
        if key in hidden_items:
            continue
        if (key in options.NEEDS_SIGN_IN and not signed_in) or (key in options.NEEDS_TRAKT_APP and not has_app):
            continue
        label_key, action = options.HOME_ITEMS[key]
        items.append(folder(plugin, label_key, action=action))
    plugin.finish(items, category="SpongeTV")


def movies(plugin, app):
    items = [folder(plugin, k, action="movie_list", kind=k)
             for k in ("trending", "popular", "top_rated", "now_playing", "upcoming")]
    items += [folder(plugin, "genres", action="genres", media="movie"),
              folder(plugin, "years", action="years", media="movie"),
              folder(plugin, "search", action="search_menu")]
    plugin.finish(items, category=kodi.text("movies"))


def tv(plugin, app):
    items = [folder(plugin, k, action="tv_list", kind=k)
             for k in ("trending", "popular", "top_rated", "airing_today", "on_the_air")]
    items += [folder(plugin, "new_shows", action="new_shows"),
              folder(plugin, "networks", action="networks"),
              folder(plugin, "streaming_services", action="providers"),
              folder(plugin, "genres", action="genres", media="tv"),
              folder(plugin, "years", action="years", media="tv"),
              folder(plugin, "search", action="search_menu")]
    plugin.finish(items, category=kodi.text("tv_shows"))


# -- title lists ---------------------------------------------------------------------
def _details_for(app, media, summaries):
    """Fetch full details for a page of titles in parallel; fall back to the summary."""
    def fetch(summary):
        try:
            return app.tmdb.movie(summary["id"]) if media == "movie" else app.tmdb.tv(summary["id"])
        except (HttpError, KeyError) as error:
            kodi.log(f"Details failed for {media} {summary.get('id')}: {error}")
            return summary
    with ThreadPoolExecutor(max_workers=workers()) as pool:
        return list(pool.map(fetch, summaries))


def _is_out(details, media, display):
    """True if a title hasn't been released or aired here yet."""
    if media == "movie":
        return not airtime.is_released(airtime.local_release_date(details, display.region))
    return not airtime.has_aired(details.get("first_air_date"), details.get("origin_country"))


def trakt_entry(plugin, **params):
    return kodi.text("trakt_menu"), f"RunPlugin({plugin.url(action='trakt_menu', **params)})"


def context_menu(plugin, media, tmdb_id, signed_in=False):
    related = plugin.url(action="related", media=media, tmdb_id=tmdb_id)
    cast = plugin.url(action="cast", media=media, tmdb_id=tmdb_id)
    entries = [trakt_entry(plugin, media=media, tmdb_id=tmdb_id)] if signed_in else []
    return entries + [(kodi.text("related_titles"), f"Container.Update({related})"),
                      (kodi.text("cast_and_crew"), f"Container.Update({cast})")]


def marks_for(app):
    return Marks(app.library if app.signed_in else None)


def title_items(plugin, app, media, summaries, hide_menu=None):
    """List items for films or shows; hide_menu names the menu whose hide settings apply."""
    details = _details_for(app, media, summaries)
    display = options.display(app)
    table = artwork.sizes(app.preset)
    fanart_api, omdb_api = app.fanart, app.omdb
    what = "unreleased" if media == "movie" else "unaired"
    hide_unreleased = bool(hide_menu) and options.hidden(hide_menu, what)
    hide_watched = bool(hide_menu) and options.hidden(hide_menu, "watched")
    marks = marks_for(app)
    signed_in = marks.active
    items = []
    for d in details:
        if hide_unreleased and _is_out(d, media, display):
            continue
        mark = marks.movie(d.get("id")) if media == "movie" else marks.show(d)
        watched = mark[0] > 0 if media == "movie" else fully_watched(*mark)
        if hide_watched and watched:
            continue
        external = d.get("external_ids") or {}
        imdb_id = d.get("imdb_id") or external.get("imdb_id")
        extra_art = {}
        if table["extras"] and fanart_api.api_key:
            extra_art = fanart_api.movie(d.get("id")) if media == "movie" else fanart_api.tv(external.get("tvdb_id"))
        art = artwork.for_title(d, app.preset, app.language, extra_art, kodi.FANART)
        ratings = omdb_api.ratings(imdb_id) if omdb_api.api_key else {}
        menu = context_menu(plugin, media, d.get("id"), signed_in)
        if media == "movie":
            li = listing.movie_item(d, art, display, ratings, menu, mark)
            items.append((plugin.url(action="play", media="movie", tmdb_id=d.get("id")), li, False))
        else:
            li = listing.show_item(d, art, display, ratings, menu, mark)
            next_action = "all_episodes" if kodi.setting_bool("display.flatten_seasons") else "seasons"
            items.append((plugin.url(action=next_action, tmdb_id=d.get("id")), li, True))
    return items


def show_titles(plugin, app, title_media, data, hide_menu=None, lead_items=None, kodi_cache=True, **page_params):
    """page_params build the Next page link and may include their own media=."""
    results = [r for r in data.get("results", []) if r.get("id")]
    items = list(lead_items or [])
    items += title_items(plugin, app, title_media, results, hide_menu)
    items += _next_page(plugin, data, **page_params)
    content = "movies" if title_media == "movie" else "tvshows"
    view = "view.movies" if title_media == "movie" else "view.tvshows"
    plugin.finish(items, content=content, view_setting=view, cache=kodi_cache)


def movie_list(plugin, app):
    kind, page = plugin.params.get("kind", "popular"), plugin.int_param("page", 1)
    # "Coming soon" is about unreleased films, so the hide setting doesn't apply to it.
    hide_menu = None if kind == "upcoming" else "movie_lists"
    show_titles(plugin, app, "movie", app.tmdb.movie_list(kind, page), hide_menu, action="movie_list", kind=kind)


def tv_list(plugin, app):
    kind, page = plugin.params.get("kind", "popular"), plugin.int_param("page", 1)
    show_titles(plugin, app, "tv", app.tmdb.tv_list(kind, page), "tv_lists", action="tv_list", kind=kind)


# -- sortable discovery lists (genre, year, network, streaming service, new shows) -----------
def _sorted_list(plugin, app, list_media, list_key, filters, **page_params):
    """page_params build the Next page link and may include their own media=."""
    media = list_media
    page = plugin.int_param("page", 1)
    sort_by = options.sort_for(app.store, list_key, media)
    data = app.tmdb.discover(media, page=page, sort_by=sort_by, filters=filters)
    label = options.highlight(kodi.text("sort_by", sort=options.sort_label(media, sort_by)))
    sort_item = (plugin.url(action="set_sort", media=media, key=list_key),
                 listing.folder_item(label, kodi.ICON, kodi.FANART), False)
    lead = [sort_item] if page == 1 else []
    show_titles(plugin, app, media, data, "movie_lists" if media == "movie" else "tv_lists", lead, **page_params)


def set_sort(plugin, app):
    media, list_key = plugin.params.get("media", "movie"), plugin.params.get("key", "")
    choices = options.SORTS[media]
    current = options.sort_for(app.store, list_key, media)
    index = xbmcgui.Dialog().select(kodi.text("sort_title_heading"), [kodi.text(label) for _, label in choices],
                                    preselect=[value for value, _ in choices].index(current))
    if index >= 0:
        options.set_sort(app.store, list_key, choices[index][0])
        xbmc.executebuiltin("Container.Refresh")


def genres(plugin, app):
    media = plugin.params.get("media", "movie")
    items = [(plugin.url(action="genre", media=media, genre=g["id"]), listing.folder_item(g["name"], kodi.ICON, kodi.FANART), True)
             for g in app.tmdb.genres(media)]
    plugin.finish(items, category=kodi.text("genres"))


def genre(plugin, app):
    media, genre_id = plugin.params.get("media", "movie"), plugin.params.get("genre")
    _sorted_list(plugin, app, media, f"genre:{media}:{genre_id}", {"with_genres": genre_id},
                 action="genre", media=media, genre=genre_id)


def years(plugin, app):
    media = plugin.params.get("media", "movie")
    this_year = datetime.date.today().year
    items = [(plugin.url(action="year", media=media, year=y), listing.folder_item(str(y), kodi.ICON, kodi.FANART), True)
             for y in range(this_year, 1919, -1)]
    plugin.finish(items, category=kodi.text("years"))


def year(plugin, app):
    media, year_value = plugin.params.get("media", "movie"), plugin.params.get("year")
    key = "primary_release_year" if media == "movie" else "first_air_date_year"
    _sorted_list(plugin, app, media, f"year:{media}:{year_value}", {key: year_value},
                 action="year", media=media, year=year_value)


def new_shows(plugin, app):
    today = airtime.local_today()
    filters = {"first_air_date.gte": (today - datetime.timedelta(days=NEW_SHOW_DAYS)).isoformat(),
               "first_air_date.lte": today.isoformat()}
    _sorted_list(plugin, app, "tv", "new_shows", filters, action="new_shows")


def networks(plugin, app):
    def load(network_id):
        try:
            return app.tmdb.network(network_id)
        except HttpError as error:
            kodi.log(f"Network {network_id} unavailable: {error}")
            return None
    with ThreadPoolExecutor(max_workers=workers()) as pool:
        found = [n for n in pool.map(load, NETWORKS) if n and n.get("name")]
    items = []
    for network in sorted(found, key=lambda n: n["name"].lower()):
        logo = image_url(network.get("logo_path"), "w500") or kodi.ICON
        url = plugin.url(action="network", network=network.get("id"))
        items.append((url, listing.folder_item(network["name"], logo, kodi.FANART), True))
    plugin.finish(items, category=kodi.text("networks"))


def network(plugin, app):
    network_id = plugin.params.get("network")
    _sorted_list(plugin, app, "tv", f"network:{network_id}", {"with_networks": network_id},
                 action="network", network=network_id)


def providers(plugin, app):
    region = app.region or "GB"
    items = []
    for provider in app.tmdb.watch_providers("tv", region)[:40]:
        logo = image_url(provider.get("logo_path"), "w300") or kodi.ICON
        url = plugin.url(action="provider", provider=provider.get("provider_id"))
        items.append((url, listing.folder_item(provider.get("provider_name", ""), logo, kodi.FANART), True))
    plugin.finish(items, category=kodi.text("streaming_services"))


def provider(plugin, app):
    provider_id, region = plugin.params.get("provider"), app.region or "GB"
    filters = {"with_watch_providers": provider_id, "watch_region": region,
               "with_watch_monetization_types": "flatrate|free|ads"}
    _sorted_list(plugin, app, "tv", f"provider:{region}:{provider_id}", filters,
                 action="provider", provider=provider_id)


# -- related titles and cast (from a title's context menu) ---------------------------------
def related(plugin, app):
    media, tmdb_id, page = plugin.params.get("media", "movie"), plugin.params.get("tmdb_id"), plugin.int_param("page", 1)
    data = app.tmdb.recommendations(media, tmdb_id, page)
    if page == 1 and not data.get("results"):
        kodi.notify(kodi.text("nothing_found"))
    hide_menu = "movie_lists" if media == "movie" else "tv_lists"
    show_titles(plugin, app, media, data, hide_menu, action="related", media=media, tmdb_id=tmdb_id)


def cast(plugin, app):
    media, tmdb_id = plugin.params.get("media", "movie"), plugin.params.get("tmdb_id")
    details = app.tmdb.movie(tmdb_id) if media == "movie" else app.tmdb.tv(tmdb_id)
    credits_ = details.get("credits") or {}
    people = list((credits_.get("cast") or [])[:30])
    seen = {p.get("id") for p in people}
    for person in (details.get("created_by") or []) + (credits_.get("crew") or []):
        if person.get("job", "Creator") in ("Director", "Screenplay", "Writer", "Creator") and person.get("id") not in seen:
            people.append(dict(person, job=person.get("job", "Creator")))
            seen.add(person.get("id"))
    items = [(plugin.url(action="person", person=p.get("id")), listing.person_item(p, kodi.ICON, kodi.FANART), True)
             for p in people if p.get("id")]
    plugin.finish(items, category=details.get("title") or details.get("name", ""))


def play(plugin, app):
    plugin.resolve_nothing()
    kodi.notify(kodi.text("playback_later"))
