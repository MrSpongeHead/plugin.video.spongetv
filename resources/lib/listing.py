# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Turns TMDB data into Kodi list items using the InfoTagVideo setters (Kodi 20+)."""

import xbmc
import xbmcgui

from resources.lib import airtime
from resources.lib.options import EPISODE_1X01, EPISODE_S01E01, Display, highlight
from resources.lib.tmdb import image_url


def _year(date_text):
    try:
        return int((date_text or "")[:4])
    except ValueError:
        return 0


def _certification_movie(details, region):
    for country in (details.get("release_dates") or {}).get("results", []):
        if country.get("iso_3166_1") == (region or "GB"):
            for release in country.get("release_dates", []):
                if release.get("certification"):
                    return release["certification"]
    return ""


def _certification_tv(details, region):
    for rating in (details.get("content_ratings") or {}).get("results", []):
        if rating.get("iso_3166_1") == (region or "GB") and rating.get("rating"):
            return rating["rating"]
    return ""


def _cast(details):
    actors = []
    for person in ((details.get("credits") or {}).get("cast") or [])[:20]:
        actors.append(xbmc.Actor(
            person.get("name", ""), person.get("character", ""), person.get("order", 0),
            image_url(person.get("profile_path"), "w185"),
        ))
    return actors


def _crew(details, job):
    return [p.get("name", "") for p in ((details.get("credits") or {}).get("crew") or []) if p.get("job") == job]


def _apply_ratings(tag, details, extra_ratings):
    if details.get("vote_count"):
        tag.setRating(float(details.get("vote_average") or 0), int(details.get("vote_count") or 0), "themoviedb", True)
    for kind, (rating, votes) in (extra_ratings or {}).items():
        tag.setRating(rating, votes, kind, False)


def _studios(names, display):
    return names[:1] if display.one_studio else names


def _with_menu(item, context_menu):
    if context_menu:
        item.addContextMenuItems(context_menu)


def _no_stream_details(tag):
    """An empty video stream stops Kodi filling the item with the resolution, codecs and audio channels it
    recorded while playing (the same as Seren does)."""
    try:
        tag.addVideoStream(xbmc.VideoStreamDetail())
    except (AttributeError, TypeError):
        pass


def _played(tag, marks, duration):
    """marks: (plays, resume percent) or (plays, percent, position, total) when SpongeTV saved the exact spot."""
    plays, percent, position, total = (tuple(marks or ()) + (0, 0, 0, 0))[:4]
    if plays:
        tag.setPlaycount(int(plays))
    if position and total:
        tag.setResumePoint(float(position), float(total))
    elif percent and duration:
        tag.setResumePoint(duration * float(percent) / 100.0, duration)


def _progress(item, tag, watched, aired):
    if aired:
        item.setProperty("TotalEpisodes", str(aired))
        item.setProperty("WatchedEpisodes", str(min(watched, aired)))
        item.setProperty("UnWatchedEpisodes", str(max(aired - watched, 0)))
        if watched >= aired:
            tag.setPlaycount(1)


def movie_item(details, art, display=None, extra_ratings=None, context_menu=None, marks=None):
    display = display or Display()
    region = display.region
    title = details.get("original_title") if display.original_titles else details.get("title")
    item = xbmcgui.ListItem(title or details.get("title", ""), offscreen=True)
    tag = item.getVideoInfoTag()
    tag.setMediaType("movie")
    tag.setTitle(title or "")
    tag.setOriginalTitle(details.get("original_title", ""))
    tag.setPlot(details.get("overview", ""))
    tag.setTagLine(details.get("tagline", ""))
    tag.setYear(_year(details.get("release_date")))
    released = airtime.local_release_date(details, region)
    if released:
        tag.setPremiered(released)
    tag.setGenres([g["name"] for g in details.get("genres", [])])
    tag.setStudios(_studios([c["name"] for c in details.get("production_companies", [])], display))
    tag.setCountries([c["name"] for c in details.get("production_countries", [])])
    duration = int(details.get("runtime") or 0) * 60
    tag.setDuration(duration)
    _played(tag, marks, duration)
    _no_stream_details(tag)
    tag.setMpaa(_certification_movie(details, region))
    tag.setDirectors(_crew(details, "Director"))
    tag.setWriters(_crew(details, "Screenplay") or _crew(details, "Writer"))
    tag.setCast(_cast(details))
    ids = {"tmdb": str(details.get("id", ""))}
    if details.get("imdb_id"):
        ids["imdb"] = details["imdb_id"]
    tag.setUniqueIDs(ids, "tmdb")
    _apply_ratings(tag, details, extra_ratings)
    item.setArt(art)
    item.setProperty("IsPlayable", "true")
    _with_menu(item, context_menu)
    return item


def show_item(details, art, display=None, extra_ratings=None, context_menu=None, marks=None):
    display = display or Display()
    region = display.region
    title = details.get("original_name") if display.original_titles else details.get("name")
    item = xbmcgui.ListItem(title or details.get("name", ""), offscreen=True)
    tag = item.getVideoInfoTag()
    tag.setMediaType("tvshow")
    tag.setTitle(title or "")
    tag.setTvShowTitle(details.get("name", ""))
    tag.setOriginalTitle(details.get("original_name", ""))
    tag.setPlot(details.get("overview", ""))
    tag.setYear(_year(details.get("first_air_date")))
    if details.get("first_air_date"):
        tag.setPremiered(details["first_air_date"])
    tag.setGenres([g["name"] for g in details.get("genres", [])])
    tag.setStudios(_studios([n["name"] for n in details.get("networks", [])], display))
    tag.setMpaa(_certification_tv(details, region))
    tag.setTvShowStatus(details.get("status", ""))
    tag.setCast(_cast(details))
    ids = {"tmdb": str(details.get("id", ""))}
    external = details.get("external_ids") or {}
    if external.get("imdb_id"):
        ids["imdb"] = external["imdb_id"]
    if external.get("tvdb_id"):
        ids["tvdb"] = str(external["tvdb_id"])
    tag.setUniqueIDs(ids, "tmdb")
    _apply_ratings(tag, details, extra_ratings)
    _progress(item, tag, *(marks or (0, 0)))
    item.setArt(art)
    _with_menu(item, context_menu)
    return item


def season_item(show, season, art, label, marks=None, progress_label="", context_menu=None):
    item = xbmcgui.ListItem(label, offscreen=True)
    tag = item.getVideoInfoTag()
    tag.setMediaType("season")
    tag.setTitle(label)
    tag.setTvShowTitle(show.get("name", ""))
    tag.setSeason(int(season.get("season_number") or 0))
    tag.setPlot(season.get("overview") or show.get("overview", ""))
    if season.get("air_date"):
        tag.setPremiered(season["air_date"])
        tag.setYear(_year(season["air_date"]))
    _progress(item, tag, *(marks or (0, 0)))
    if progress_label:
        item.setLabel2(progress_label)
    item.setArt(art)
    _with_menu(item, context_menu)
    return item


def episode_label(episode, style, fallback):
    name = episode.get("name") or fallback
    season, number = int(episode.get("season_number") or 0), int(episode.get("episode_number") or 0)
    if style == EPISODE_1X01:
        return f"{season}x{number:02d}. {name}"
    if style == EPISODE_S01E01:
        return f"S{season:02d}E{number:02d} {name}"
    return name


def episode_item(show, episode, art, display=None, fallback_title="", marks=None, context_menu=None, show_in_label=False):
    display = display or Display()
    title = episode.get("name") or fallback_title or f"Episode {episode.get('episode_number')}"
    label = episode_label(episode, display.episode_style, title)
    if show_in_label:   # lists that mix shows (Next up, calendars): the show name in your highlight colour
        label = f"{highlight(show.get('name', ''))}: {episode_label(episode, display.episode_style or EPISODE_S01E01, title)}"
    item = xbmcgui.ListItem(label, offscreen=True)
    tag = item.getVideoInfoTag()
    tag.setMediaType("episode")
    tag.setTitle(title)
    tag.setTvShowTitle(show.get("name", ""))
    tag.setSeason(int(episode.get("season_number") or 0))
    tag.setEpisode(int(episode.get("episode_number") or 0))
    tag.setPlot(episode.get("overview", ""))
    if episode.get("air_date"):
        tag.setFirstAired(episode["air_date"])
        tag.setPremiered(episode["air_date"])
        tag.setYear(_year(episode["air_date"]))
    duration = int(episode.get("runtime") or 0) * 60
    tag.setDuration(duration)
    _played(tag, marks, duration)
    _no_stream_details(tag)
    tag.setUniqueIDs({"tmdb": str(episode.get("id", ""))}, "tmdb")
    if episode.get("vote_count"):
        tag.setRating(float(episode.get("vote_average") or 0), int(episode["vote_count"]), "themoviedb", True)
    item.setArt(art)
    item.setProperty("IsPlayable", "true")
    _with_menu(item, context_menu)
    return item


def person_item(person, fallback_icon="", fanart=""):
    item = xbmcgui.ListItem(person.get("name", ""), offscreen=True)
    known_for = [t.get("title") or t.get("name") for t in person.get("known_for", []) if t.get("title") or t.get("name")]
    plot = person.get("biography") or ", ".join(known_for)
    role = person.get("character") or person.get("job") or person.get("known_for_department") or ""
    if role:
        item.setLabel2(role)
    if plot:
        item.getVideoInfoTag().setPlot(plot)
    photo = image_url(person.get("profile_path"), "h632") or fallback_icon
    item.setArt({k: v for k, v in (("icon", photo), ("thumb", photo), ("poster", photo), ("fanart", fanart)) if v})
    return item


def folder_item(label, icon="", fanart="", plot=""):
    item = xbmcgui.ListItem(label, offscreen=True)
    if plot:
        item.getVideoInfoTag().setPlot(plot)
    art = {k: v for k, v in (("icon", icon), ("thumb", icon), ("poster", icon), ("fanart", fanart)) if v}
    item.setArt(art)
    return item
