# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Seasons and episodes, with the Seasons and Episodes hide settings and time-zone-aware air dates."""

from concurrent.futures import ThreadPoolExecutor

from resources.lib import airtime, artwork, kodi, listing, menus, options
from resources.lib.http import HttpError


def _visible_seasons(show):
    hide_specials = options.hidden("seasons", "specials")
    hide_unaired = options.hidden("seasons", "unaired")
    countries = show.get("origin_country")
    seasons = []
    for season in show.get("seasons", []):
        if hide_specials and season.get("season_number") == 0:
            continue
        if hide_unaired and not airtime.has_aired(season.get("air_date"), countries):
            continue
        seasons.append(season)
    return seasons


def _show_art(app, show):
    extra = {}
    if artwork.sizes(app.preset)["extras"]:
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
    hide_unaired = options.hidden("episodes", "unaired")
    countries = show.get("origin_country")
    display = options.display(app)

    def load(number):
        try:
            return app.tmdb.season(show["id"], number)
        except HttpError as error:
            kodi.log(f"Season {number} failed: {error}")
            return {}
    with ThreadPoolExecutor(max_workers=menus.workers()) as pool:
        season_data = list(pool.map(load, season_numbers))
    items = []
    for data in season_data:
        for episode in data.get("episodes", []):
            if hide_unaired and not airtime.has_aired(episode.get("air_date"), countries):
                continue
            art = artwork.for_episode(episode, show_art, app.preset)
            url = plugin.url(action="play", media="episode", tmdb_id=show["id"],
                             season=episode.get("season_number"), episode=episode.get("episode_number"))
            fallback = kodi.text("episode_number", number=episode.get("episode_number"))
            items.append((url, listing.episode_item(show, episode, art, display, fallback), False))
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
