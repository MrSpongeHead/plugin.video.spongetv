# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Seasons and episodes, with the Seasons and Episodes hide settings and time-zone-aware air dates."""

from concurrent.futures import ThreadPoolExecutor

from resources.lib import airtime, artwork, kodi, listing, menus, options
from resources.lib.http import HttpError
from resources.lib.marks import fully_watched


def _visible_seasons(show, marks=None):
    hide_specials = options.hidden("seasons", "specials")
    hide_unaired = options.hidden("seasons", "unaired")
    hide_watched = marks is not None and marks.active and options.hidden("seasons", "watched")
    countries = show.get("origin_country")
    seasons = []
    for season in show.get("seasons", []):
        number = season.get("season_number")
        if hide_specials and number == 0:
            continue
        if hide_unaired and not airtime.has_aired(season.get("air_date"), countries):
            continue
        if hide_watched and number and fully_watched(*marks.season(show, number)):
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
    marks = menus.marks_for(app)
    items = []
    for season in _visible_seasons(show, marks):
        number = season.get("season_number", 0)
        label = kodi.text("specials") if number == 0 else (season.get("name") or kodi.text("season", number=number))
        art = artwork.for_season(season, show_art, app.preset)
        url = plugin.url(action="episodes", tmdb_id=tmdb_id, season=number)
        mark = marks.season(show, number)
        progress = kodi.text("season_progress", watched=mark[0], aired=mark[1]) if marks.active and mark[1] else ""
        if progress:
            # In the name itself: Kodi replaces the second column with whatever the list is sorted by.
            label = kodi.text("season_with_count", name=label, watched=min(mark[0], mark[1]), aired=mark[1])
        menu = [menus.trakt_entry(plugin, media="season", show=show["id"], season=number)] if marks.active else None
        items.append((url, listing.season_item(show, season, art, label, mark, progress, menu), True))
    plugin.finish(items, content="seasons", category=show.get("name", ""), view_setting="view.seasons",
                  cache=False)  # shows watched status: no Kodi copy, or going back shows it stale


def _episode_items(plugin, app, show, show_art, season_numbers, only=None, show_in_label=False):
    """only: optional {(season, episode)} to keep, in that order (Next Up, calendars)."""
    hide_unaired = options.hidden("episodes", "unaired") and only is None
    hide_watched = options.hidden("episodes", "watched") and only is None
    countries = show.get("origin_country")
    display = options.display(app)
    marks = menus.marks_for(app)

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
            season, number = episode.get("season_number"), episode.get("episode_number")
            if only is not None and (season, number) not in only:
                continue
            if hide_unaired and not airtime.has_aired(episode.get("air_date"), countries):
                continue
            mark = marks.episode(show["id"], season, number)
            if hide_watched and mark[0]:
                continue
            art = artwork.for_episode(episode, show_art, app.preset)
            asks = "1" if mark[1] else None   # Kodi asks "Resume from…" itself for this item
            url = plugin.url(action="play", media="episode", tmdb_id=show["id"], season=season, episode=number, kr=asks)
            fallback = kodi.text("episode_number", number=number)
            menu = [menus.trakt_entry(plugin, media="episode", show=show["id"], season=season, episode=number)] \
                if marks.active else []
            has_resume = bool(mark[1]) or menus.own_resume(app, f"episode:{show['id']}:{season}:{number}")
            menu += menus.play_entries(plugin, has_resume, media="episode", tmdb_id=show["id"], season=season,
                                       episode=number)
            items.append((url, listing.episode_item(show, episode, art, display, fallback, mark if marks.active else None, menu,
                                                              show_in_label), False))
    return items


def episodes(plugin, app):
    show = app.tmdb.tv(plugin.params.get("tmdb_id"))
    items = _episode_items(plugin, app, show, _show_art(app, show), [plugin.int_param("season", 1)])
    plugin.finish(items, content="episodes", category=show.get("name", ""), view_setting="view.episodes",
                  cache=False)  # shows watched status: no Kodi copy, or going back shows it stale


def all_episodes(plugin, app):
    show = app.tmdb.tv(plugin.params.get("tmdb_id"))
    numbers = [s.get("season_number", 0) for s in _visible_seasons(show, menus.marks_for(app))]
    items = _episode_items(plugin, app, show, _show_art(app, show), numbers)
    plugin.finish(items, content="episodes", category=show.get("name", ""), view_setting="view.episodes",
                  cache=False)  # shows watched status: no Kodi copy, or going back shows it stale
