# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Turns TMDB data into Kodi list items using the InfoTagVideo setters (Kodi 20+)."""

import xbmc
import xbmcgui

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


def movie_item(details, art, region=None, original_titles=False, extra_ratings=None):
    title = details.get("original_title") if original_titles else details.get("title")
    item = xbmcgui.ListItem(title or details.get("title", ""), offscreen=True)
    tag = item.getVideoInfoTag()
    tag.setMediaType("movie")
    tag.setTitle(title or "")
    tag.setOriginalTitle(details.get("original_title", ""))
    tag.setPlot(details.get("overview", ""))
    tag.setTagLine(details.get("tagline", ""))
    tag.setYear(_year(details.get("release_date")))
    if details.get("release_date"):
        tag.setPremiered(details["release_date"])
    tag.setGenres([g["name"] for g in details.get("genres", [])])
    tag.setStudios([c["name"] for c in details.get("production_companies", [])][:1])
    tag.setCountries([c["name"] for c in details.get("production_countries", [])])
    tag.setDuration(int(details.get("runtime") or 0) * 60)
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
    return item


def show_item(details, art, region=None, original_titles=False, extra_ratings=None):
    title = details.get("original_name") if original_titles else details.get("name")
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
    tag.setStudios([n["name"] for n in details.get("networks", [])][:1])
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
    item.setArt(art)
    return item


def season_item(show, season, art, label):
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
    item.setArt(art)
    return item


def episode_item(show, episode, art):
    label = episode.get("name") or f"Episode {episode.get('episode_number')}"
    item = xbmcgui.ListItem(label, offscreen=True)
    tag = item.getVideoInfoTag()
    tag.setMediaType("episode")
    tag.setTitle(label)
    tag.setTvShowTitle(show.get("name", ""))
    tag.setSeason(int(episode.get("season_number") or 0))
    tag.setEpisode(int(episode.get("episode_number") or 0))
    tag.setPlot(episode.get("overview", ""))
    if episode.get("air_date"):
        tag.setFirstAired(episode["air_date"])
        tag.setPremiered(episode["air_date"])
        tag.setYear(_year(episode["air_date"]))
    tag.setDuration(int(episode.get("runtime") or 0) * 60)
    tag.setUniqueIDs({"tmdb": str(episode.get("id", ""))}, "tmdb")
    if episode.get("vote_count"):
        tag.setRating(float(episode.get("vote_average") or 0), int(episode["vote_count"]), "themoviedb", True)
    item.setArt(art)
    item.setProperty("IsPlayable", "true")
    return item


def folder_item(label, icon="", fanart="", plot=""):
    item = xbmcgui.ListItem(label, offscreen=True)
    if plot:
        item.getVideoInfoTag().setPlot(plot)
    art = {k: v for k, v in (("icon", icon), ("thumb", icon), ("poster", icon), ("fanart", fanart)) if v}
    item.setArt(art)
    return item
