# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Browsing menus: home, films, TV shows, genres, years, search, seasons and episodes."""

import datetime
from concurrent.futures import ThreadPoolExecutor

import xbmcgui

from resources.lib import artwork, kodi, listing
from resources.lib.http import HttpError

MAX_PAGES = 500  # TMDB never serves pages beyond this
WORKERS = 8


def _today():
    return datetime.date.today().isoformat()


def _aired(date_text):
    return bool(date_text) and date_text <= _today()


def _next_page(plugin, data, **params):
    page = int(data.get("page") or 1)
    total = min(int(data.get("total_pages") or 1), MAX_PAGES)
    if page >= total:
        return []
    url = plugin.url(**dict(params, page=page + 1))
    label = kodi.text("next_page", page=page + 1, total=total)
    return [(url, listing.folder_item(label, kodi.ICON, kodi.FANART), True)]


# -- top level ---------------------------------------------------------------------
def home(plugin, app):
    entries = [
        ("movies", plugin.url(action="movies")),
        ("tv_shows", plugin.url(action="tv")),
        ("search", plugin.url(action="search_home")),
        ("tools", plugin.url(action="tools")),
    ]
    items = [(url, listing.folder_item(kodi.text(key), kodi.ICON, kodi.FANART), True) for key, url in entries]
    plugin.finish(items, category="SpongeTV")


def movies(plugin, app):
    keys = ["trending", "popular", "top_rated", "now_playing", "upcoming"]
    items = [(plugin.url(action="movie_list", kind=k), listing.folder_item(kodi.text(k), kodi.ICON, kodi.FANART), True)
             for k in keys]
    items.append((plugin.url(action="genres", media="movie"), listing.folder_item(kodi.text("genres"), kodi.ICON, kodi.FANART), True))
    items.append((plugin.url(action="years", media="movie"), listing.folder_item(kodi.text("years"), kodi.ICON, kodi.FANART), True))
    items.append((plugin.url(action="search_menu", media="movie"), listing.folder_item(kodi.text("search_movies"), kodi.ICON, kodi.FANART), True))
    plugin.finish(items, category=kodi.text("movies"))


def tv(plugin, app):
    keys = ["trending", "popular", "top_rated", "airing_today", "on_the_air"]
    items = [(plugin.url(action="tv_list", kind=k), listing.folder_item(kodi.text(k), kodi.ICON, kodi.FANART), True)
             for k in keys]
    items.append((plugin.url(action="genres", media="tv"), listing.folder_item(kodi.text("genres"), kodi.ICON, kodi.FANART), True))
    items.append((plugin.url(action="years", media="tv"), listing.folder_item(kodi.text("years"), kodi.ICON, kodi.FANART), True))
    items.append((plugin.url(action="search_menu", media="tv"), listing.folder_item(kodi.text("search_tv"), kodi.ICON, kodi.FANART), True))
    plugin.finish(items, category=kodi.text("tv_shows"))


def search_home(plugin, app):
    items = [
        (plugin.url(action="search_menu", media="movie"), listing.folder_item(kodi.text("search_movies"), kodi.ICON, kodi.FANART), True),
        (plugin.url(action="search_menu", media="tv"), listing.folder_item(kodi.text("search_tv"), kodi.ICON, kodi.FANART), True),
    ]
    plugin.finish(items, category=kodi.text("search"))


# -- title lists ---------------------------------------------------------------------
def _details_for(app, media, summaries):
    """Fetch full details for a page of titles in parallel; fall back to the summary."""
    def fetch(summary):
        try:
            return app.tmdb.movie(summary["id"]) if media == "movie" else app.tmdb.tv(summary["id"])
        except (HttpError, KeyError) as error:
            kodi.log(f"Details failed for {media} {summary.get('id')}: {error}")
            return summary
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(fetch, summaries))


def _title_items(plugin, app, media, summaries):
    details = _details_for(app, media, summaries)
    preset = app.preset
    original = kodi.setting_bool("metadata.original_titles")
    fanart_api, omdb_api = app.fanart, app.omdb
    use_extras = artwork.PRESETS.get(preset, artwork.PRESETS[1])["extras"]
    items = []
    for d in details:
        external = d.get("external_ids") or {}
        imdb_id = d.get("imdb_id") or external.get("imdb_id")
        extra_art = {}
        if use_extras and fanart_api.api_key:
            extra_art = fanart_api.movie(d.get("id")) if media == "movie" else fanart_api.tv(external.get("tvdb_id"))
        art = artwork.for_title(d, preset, app.language, extra_art, kodi.FANART)
        ratings = omdb_api.ratings(imdb_id) if omdb_api.api_key else {}
        if media == "movie":
            li = listing.movie_item(d, art, app.region, original, ratings)
            url = plugin.url(action="play", media="movie", tmdb_id=d.get("id"))
            items.append((url, li, False))
        else:
            li = listing.show_item(d, art, app.region, original, ratings)
            next_action = "all_episodes" if kodi.setting_bool("display.flatten_seasons") else "seasons"
            url = plugin.url(action=next_action, tmdb_id=d.get("id"))
            items.append((url, li, True))
    return items


def _show_titles(plugin, app, media, data, **page_params):
    results = [r for r in data.get("results", []) if r.get("id")]
    items = _title_items(plugin, app, media, results)
    items += _next_page(plugin, data, **page_params)
    content = "movies" if media == "movie" else "tvshows"
    view = "view.movies" if media == "movie" else "view.tvshows"
    plugin.finish(items, content=content, view_setting=view)


def movie_list(plugin, app):
    kind, page = plugin.params.get("kind", "popular"), plugin.int_param("page", 1)
    _show_titles(plugin, app, "movie", app.tmdb.movie_list(kind, page), action="movie_list", kind=kind)


def tv_list(plugin, app):
    kind, page = plugin.params.get("kind", "popular"), plugin.int_param("page", 1)
    _show_titles(plugin, app, "tv", app.tmdb.tv_list(kind, page), action="tv_list", kind=kind)


def genres(plugin, app):
    media = plugin.params.get("media", "movie")
    items = [(plugin.url(action="genre", media=media, genre=g["id"]), listing.folder_item(g["name"], kodi.ICON, kodi.FANART), True)
             for g in app.tmdb.genres(media)]
    plugin.finish(items, category=kodi.text("genres"))


def genre(plugin, app):
    media, genre_id, page = plugin.params.get("media", "movie"), plugin.params.get("genre"), plugin.int_param("page", 1)
    data = app.tmdb.discover(media, page=page, genre=genre_id)
    _show_titles(plugin, app, media, data, action="genre", media=media, genre=genre_id)


def years(plugin, app):
    media = plugin.params.get("media", "movie")
    this_year = datetime.date.today().year
    items = [(plugin.url(action="year", media=media, year=y), listing.folder_item(str(y), kodi.ICON, kodi.FANART), True)
             for y in range(this_year, 1919, -1)]
    plugin.finish(items, category=kodi.text("years"))


def year(plugin, app):
    media, year_value, page = plugin.params.get("media", "movie"), plugin.params.get("year"), plugin.int_param("page", 1)
    data = app.tmdb.discover(media, page=page, year=year_value)
    _show_titles(plugin, app, media, data, action="year", media=media, year=year_value)


# -- search ------------------------------------------------------------------------------
def search_menu(plugin, app):
    media = plugin.params.get("media", "movie")
    items = [(plugin.url(action="search", media=media), listing.folder_item(kodi.text("new_search"), kodi.ICON, kodi.FANART), True)]
    for query in app.store.searches(media):
        items.append((plugin.url(action="search", media=media, query=query), listing.folder_item(query, kodi.ICON, kodi.FANART), True))
    items.append((plugin.url(action="clear_search"), listing.folder_item(kodi.text("clear_search_history"), kodi.ICON, kodi.FANART), False))
    plugin.finish(items, category=kodi.text("search_movies" if media == "movie" else "search_tv"), cache=False)


def search(plugin, app):
    media = plugin.params.get("media", "movie")
    query = plugin.params.get("query")
    if not query:
        query = xbmcgui.Dialog().input(kodi.text("search_movies" if media == "movie" else "search_tv")).strip()
        if not query:
            plugin.fail()
            return
    app.store.add_search(media, query)
    page = plugin.int_param("page", 1)
    data = app.tmdb.search(media, query, page)
    if not data.get("results"):
        kodi.notify(kodi.text("nothing_found"))
    _show_titles(plugin, app, media, data, action="search", media=media, query=query)


# -- seasons and episodes ---------------------------------------------------------------
def _visible_seasons(show):
    hide_specials = kodi.setting_bool("display.hide_specials")
    hide_unaired = kodi.setting_bool("display.hide_unaired")
    seasons = []
    for season in show.get("seasons", []):
        if hide_specials and season.get("season_number") == 0:
            continue
        if hide_unaired and not _aired(season.get("air_date")):
            continue
        seasons.append(season)
    return seasons


def _show_art(app, show):
    extra = {}
    if artwork.PRESETS.get(app.preset, artwork.PRESETS[1])["extras"]:
        extra = app.fanart.tv((show.get("external_ids") or {}).get("tvdb_id"))
    return artwork.for_title(show, app.preset, app.language, extra, kodi.FANART)


def seasons(plugin, app):
    tmdb_id = plugin.params.get("tmdb_id")
    show = app.tmdb.tv(tmdb_id)
    show_art = _show_art(app, show)
    items = []
    for season in _visible_seasons(show):
        number = season.get("season_number", 0)
        label = kodi.text("specials") if number == 0 else (season.get("name") or kodi.text("season", number=number))
        art = artwork.for_season(season, show_art, app.preset)
        url = plugin.url(action="episodes", tmdb_id=tmdb_id, season=number)
        items.append((url, listing.season_item(show, season, art, label), True))
    plugin.finish(items, content="seasons", category=show.get("name", ""), view_setting="view.seasons")


def _episode_items(plugin, app, show, show_art, season_numbers):
    hide_unaired = kodi.setting_bool("display.hide_unaired")

    def load(number):
        try:
            return app.tmdb.season(show["id"], number)
        except HttpError as error:
            kodi.log(f"Season {number} failed: {error}")
            return {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        season_data = list(pool.map(load, season_numbers))
    items = []
    for data in season_data:
        for episode in data.get("episodes", []):
            if hide_unaired and not _aired(episode.get("air_date")):
                continue
            art = artwork.for_episode(episode, show_art, app.preset)
            url = plugin.url(action="play", media="episode", tmdb_id=show["id"],
                             season=episode.get("season_number"), episode=episode.get("episode_number"))
            items.append((url, listing.episode_item(show, episode, art), False))
    return items


def episodes(plugin, app):
    show = app.tmdb.tv(plugin.params.get("tmdb_id"))
    items = _episode_items(plugin, app, show, _show_art(app, show), [plugin.int_param("season", 1)])
    plugin.finish(items, content="episodes", category=show.get("name", ""), view_setting="view.episodes")


def all_episodes(plugin, app):
    show = app.tmdb.tv(plugin.params.get("tmdb_id"))
    numbers = [s.get("season_number", 0) for s in _visible_seasons(show)]
    items = _episode_items(plugin, app, show, _show_art(app, show), numbers)
    plugin.finish(items, content="episodes", category=show.get("name", ""), view_setting="view.episodes")


def play(plugin, app):
    plugin.resolve_nothing()
    kodi.notify(kodi.text("playback_later"))
