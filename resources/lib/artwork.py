# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Picks artwork for a title from TMDB (and Fanart.tv when available), by preset."""

from resources.lib.tmdb import image_url

# preset index (as stored in settings) -> image sizes and whether to use extra artwork.
# Index 3 is "Advanced": the sizes come from their own settings (see context.App.preset).
PRESETS = {
    0: {"name": "best", "poster": "original", "fanart": "original", "still": "original", "extras": True},
    1: {"name": "balanced", "poster": "w780", "fanart": "w1280", "still": "w780", "extras": True},
    2: {"name": "minimal", "poster": "w342", "fanart": "w780", "still": "w300", "extras": False},
}
ADVANCED = 3
POSTER_SIZES = ["w342", "w500", "w780", "original"]
FANART_SIZES = ["w780", "w1280", "original"]
STILL_SIZES = ["w300", "original"]


def sizes(preset):
    """The size table for a preset index, or a ready-made table (from the Advanced settings)."""
    if isinstance(preset, dict):
        return preset
    return PRESETS.get(preset, PRESETS[1])


def advanced(poster_index, fanart_index, still_index, extras):
    def pick(options, index, default):
        return options[index] if 0 <= index < len(options) else default
    return {"name": "advanced", "poster": pick(POSTER_SIZES, poster_index, "w780"),
            "fanart": pick(FANART_SIZES, fanart_index, "w1280"), "still": pick(STILL_SIZES, still_index, "w300"),
            "extras": bool(extras)}


def _best(images, language):
    """Highest-voted image, preferring the display language, then English, then no text."""
    if not images:
        return None
    lang = (language or "en").split("-")[0]

    def score(image):
        code = image.get("iso_639_1")
        rank = 0 if code == lang else 1 if code == "en" else 2 if code is None else 3
        return (rank, -(image.get("vote_average") or 0), -(image.get("vote_count") or 0))

    return sorted(images, key=score)[0]


def _best_fanart(items, language):
    if not items:
        return None
    lang = (language or "en").split("-")[0]
    return sorted(items, key=lambda i: (i.get("lang") not in (lang, "en"), -int(i.get("likes", 0) or 0)))[0]


def for_title(details, preset=1, language="en-GB", fanart_data=None, fallback_fanart=""):
    """Artwork dict for a film or TV show from TMDB details (list or full)."""
    table = sizes(preset)
    images = details.get("images") or {}
    art = {}

    poster = _best(images.get("posters"), language)
    art["poster"] = image_url(poster["file_path"] if poster else details.get("poster_path"), table["poster"])
    backdrop = _best([b for b in images.get("backdrops", []) if b.get("iso_639_1") is None], language) \
        or _best(images.get("backdrops"), language)
    art["fanart"] = image_url(backdrop["file_path"] if backdrop else details.get("backdrop_path"), table["fanart"])
    landscape = _best([b for b in images.get("backdrops", []) if b.get("iso_639_1")], language)
    if landscape:
        art["landscape"] = image_url(landscape["file_path"], table["fanart"])
    if table["extras"]:
        logo = _best(images.get("logos"), language)
        if logo:
            art["clearlogo"] = image_url(logo["file_path"], "w500")

    if table["extras"] and fanart_data:
        for kodi_key, fanart_keys in (
            ("clearlogo", ("hdmovielogo", "hdtvlogo")),
            ("clearart", ("hdmovieclearart", "hdclearart")),
            ("discart", ("moviedisc",)),
            ("characterart", ("characterart",)),
        ):
            for fanart_key in fanart_keys:
                chosen = _best_fanart(fanart_data.get(fanart_key), language)
                if chosen and kodi_key not in art:
                    art[kodi_key] = chosen.get("url", "")

    art["thumb"] = art.get("poster", "")
    art["icon"] = art.get("poster", "")
    if not art.get("fanart") and fallback_fanart:
        art["fanart"] = fallback_fanart
    return {k: v for k, v in art.items() if v}


def for_episode(episode, show_art, preset=1):
    art = dict(show_art)
    still = image_url(episode.get("still_path"), sizes(preset)["still"])
    if still:
        art["thumb"] = still
        art["icon"] = still
    return art


def for_season(season, show_art, preset=1):
    art = dict(show_art)
    poster = image_url(season.get("poster_path"), sizes(preset)["poster"])
    if poster:
        art["poster"] = art["thumb"] = art["icon"] = poster
    return art
