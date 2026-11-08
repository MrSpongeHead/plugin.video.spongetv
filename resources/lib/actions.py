# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""The "Trakt…" context menu: everything you can do to a film, show, season or episode.

Each action writes to Trakt, updates the local library straight away (so menus reflect it before
the next sync), confirms with a short notification and refreshes the list.
"""

import datetime

import xbmc
import xbmcgui

from resources.lib import accounts, kodi, mine
from resources.lib.marks import aired_counts
from resources.lib.trakt import TraktError


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Target:
    """What the menu was opened on, and the Trakt request body that identifies it."""

    def __init__(self, params):
        self.media = params.get("media", "movie")
        self.tmdb_id = _int(params.get("tmdb_id"))
        self.show = _int(params.get("show")) or (self.tmdb_id if self.media in ("tv", "show") else None)
        self.season = _int(params.get("season"))
        self.episode = _int(params.get("episode"))
        if self.media == "tv":
            self.media = "show"

    def body(self, **extra):
        if self.media == "movie":
            return {"movies": [dict({"ids": {"tmdb": self.tmdb_id}}, **extra)]}
        if self.media == "show":
            return {"shows": [dict({"ids": {"tmdb": self.show}}, **extra)]}
        if self.media == "season":
            return {"shows": [{"ids": {"tmdb": self.show}, "seasons": [dict({"number": self.season}, **extra)]}]}
        return {"shows": [{"ids": {"tmdb": self.show}, "seasons": [
            {"number": self.season, "episodes": [dict({"number": self.episode}, **extra)]}]}]}


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _choices(app, target):
    """[(label, function)] for this kind of item, reflecting its current state."""
    lib = app.library
    t = target
    choices = []
    if t.media == "movie":
        watched = lib.movie_plays(t.tmdb_id) > 0
    elif t.media == "episode":
        watched = (t.season, t.episode) in lib.watched_episodes(t.show)
    else:
        watched = False
    choices.append(("mark_unwatched", unwatch) if watched else ("mark_watched", watch))
    if t.media == "season":
        choices.append(("mark_unwatched", unwatch))
    if t.media == "show":
        choices.append(("mark_unwatched", unwatch))
    if t.media in ("movie", "show"):
        for part, add_key, remove_key in (("collection", "add_collection", "remove_collection"),
                                          ("watchlist", "add_watchlist", "remove_watchlist"),
                                          ("favourites", "add_favourites", "remove_favourites")):
            has = lib.has(part, t.media, t.tmdb_id or t.show)
            choices.append((remove_key, _toggle(part, False)) if has else (add_key, _toggle(part, True)))
        choices.append(("add_to_list", add_to_list))
        choices.append(("remove_from_list", remove_from_list))
    choices.append(("rate", rate))
    if t.media == "show":
        hidden = t.show in lib.skipped_shows()
        choices.append(("unhide_progress", unhide) if hidden else ("hide_progress", hide))
    if t.media in ("movie", "episode") and lib.progress(t.media, t.tmdb_id, t.show, t.season, t.episode)[1]:
        choices.append(("clear_progress", clear_progress))
    choices.append(("refresh_info", refresh_info))
    return choices


def menu(plugin, app):
    if not app.signed_in:
        kodi.notify(kodi.text("trakt_not_signed_in"))
        return
    target = Target(plugin.params)
    choices = _choices(app, target)
    picked = xbmcgui.Dialog().contextmenu([kodi.text(label) for label, _ in choices])
    if picked < 0:
        return
    label, action = choices[picked]
    try:
        done = action(app, target)
    except TraktError as error:
        kodi.notify(accounts.message(error))
        return
    if done:
        kodi.notify(done if isinstance(done, str) else kodi.text("done_" + label))
        xbmc.executebuiltin("Container.Refresh")


# -- local updates ---------------------------------------------------------------------------------
def _episodes_of(app, target):
    """[(season, episode)] aired for a show or season, from TMDB."""
    counts = aired_counts(app.tmdb.tv(target.show))
    seasons = [target.season] if target.media == "season" else sorted(counts)
    return [(s, e) for s in seasons for e in range(1, counts.get(s, 0) + 1)]


def _mark_local(app, target, watched):
    lib = app.library
    if target.media == "movie":
        if watched:
            lib.add("watched", "movie", target.tmdb_id, value=lib.movie_plays(target.tmdb_id) + 1, at=_now())
        else:
            lib.remove("watched", "movie", target.tmdb_id)
        lib.remove("playback", "movie", target.tmdb_id)
        return
    if target.media == "episode":
        pairs = [(target.season, target.episode)]
    else:
        pairs = _episodes_of(app, target)
    if not watched:
        if target.media == "show":
            lib.remove("watched", "episode", show=target.show)
        else:
            for s, e in pairs:
                lib.remove("watched", "episode", show=target.show, season=s, episode=e)
        return
    now = _now()
    for s, e in pairs:
        lib.add("watched", "episode", show=target.show, season=s, episode=e, value=1, at=now)
        lib.remove("playback", "episode", show=target.show, season=s, episode=e)


# -- the actions -------------------------------------------------------------------------------------
def watch(app, target):
    app.trakt.post("/sync/history", target.body())
    _mark_local(app, target, True)
    return True


def unwatch(app, target):
    app.trakt.post("/sync/history/remove", target.body())
    _mark_local(app, target, False)
    return kodi.text("done_mark_unwatched")


def _toggle(part, add):
    path = {"collection": "/sync/collection", "watchlist": "/sync/watchlist", "favourites": "/sync/favorites"}[part]

    def act(app, target):
        app.trakt.post(path if add else path + "/remove", target.body())
        tmdb_id = target.tmdb_id or target.show
        if add:
            app.library.add(part, target.media, tmdb_id, at=_now())
        else:
            app.library.remove(part, target.media, tmdb_id)
        return kodi.text(("done_add_" if add else "done_remove_") + part)
    return act


def add_to_list(app, target):
    return _list_change(app, target, add=True)


def remove_from_list(app, target):
    return _list_change(app, target, add=False)


def _list_change(app, target, add):
    own = mine.my_lists_for_picker(app)
    if not own:
        kodi.notify(kodi.text("no_lists"))
        return False
    picked = xbmcgui.Dialog().select(kodi.text("choose_list"), [name for _, name in own])
    if picked < 0:
        return False
    list_id, name = own[picked]
    path = f"/users/me/lists/{list_id}/items" + ("" if add else "/remove")
    app.trakt.post(path, target.body())
    app.store.cache_delete_matching(f"trakt:list:%:{list_id}:%")   # every saved page, whoever's name is in it
    return kodi.text("done_added_to_list" if add else "done_removed_from_list", name=name)


def rate(app, target):
    current = app.library.rating(target.media, target.tmdb_id or target.show, target.show, target.season, target.episode)
    options = [kodi.text("rating_value", value=n) for n in range(10, 0, -1)]
    if current:
        options.append(kodi.text("remove_rating"))
    picked = xbmcgui.Dialog().select(kodi.text("rate_heading"), options)
    if picked < 0:
        return False
    if picked == 10:
        app.trakt.post("/sync/ratings/remove", target.body())
        _store_rating(app, target, None)
        return kodi.text("done_remove_rating")
    value = 10 - picked
    app.trakt.post("/sync/ratings", target.body(rating=value))
    _store_rating(app, target, value)
    return kodi.text("done_rated", value=value)


def _store_rating(app, target, value):
    lib = app.library
    if target.media in ("movie", "show"):
        lib.remove("ratings", target.media, target.tmdb_id or target.show)
        if value:
            lib.add("ratings", target.media, target.tmdb_id or target.show, value=value, at=_now())
    else:
        lib.remove("ratings", target.media, show=target.show, season=target.season,
                   episode=target.episode if target.media == "episode" else None)
        if value:
            lib.add("ratings", target.media, show=target.show, season=target.season,
                    episode=target.episode if target.media == "episode" else None, value=value, at=_now())


def hide(app, target):
    app.trakt.post("/users/hidden/progress_watched", target.body())
    app.library.add("hidden", "show", target.show, at=_now())
    return True


def unhide(app, target):
    app.trakt.post("/users/hidden/progress_watched/remove", target.body())
    app.library.remove("hidden", "show", target.show)
    app.library.remove("dropped", "show", target.show)
    return True


def clear_progress(app, target):
    _, playback_id = app.library.progress(target.media, target.tmdb_id, target.show, target.season, target.episode)
    if playback_id:
        app.trakt.delete(f"/sync/playback/{playback_id}")
    if target.media == "movie":
        app.library.remove("playback", "movie", target.tmdb_id)
    else:
        app.library.remove("playback", "episode", show=target.show, season=target.season, episode=target.episode)
    return True


def refresh_info(app, target):
    """Forget the cached TMDB details for this title, so they're fetched fresh."""
    if target.media == "movie":
        app.tmdb.forget_movie(target.tmdb_id)
    else:
        app.tmdb.forget_tv(target.show)
    return True
