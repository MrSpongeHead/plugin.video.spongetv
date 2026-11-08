# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Pressing play: resume prompt, find sources, Auto Play or Source Select, resolve, play, then follow along.

Any source that fails to resolve moves on to the next one. While playing, SpongeTV scrobbles to Trakt and
saves its own resume point every few seconds. Kodi keeps its own resume point too (after three minutes)
and asks about it itself, so SpongeTV only asks when Kodi won't: you only ever see one prompt. SpongeTV
leaves Kodi's record alone after playback, because changing it makes Kodi blank the list item's details.
"""

import json
import time

import xbmc
import xbmcgui

from resources.lib import airtime, artwork, choose, kodi, listing, options, ranking, windows
from resources.lib.premiumize import PremiumizeError
from resources.lib.sources import movie_request

SOURCE_SELECT, AUTO_PLAY = 0, 1
SAVE_EVERY = 10            # seconds between local resume point saves
WATCHED_AT = 90            # percent: past this, the resume point is cleared
MIN_RESUME = 60            # seconds: don't offer to resume from the first minute
START_WAIT = 60            # seconds to wait for Kodi to start playing


# -- what's being played ----------------------------------------------------------------------------------
class Target:
    """A film or one episode, with the TMDB details SpongeTV needs to search, label and scrobble it."""

    def __init__(self, app, params):
        self.media = params.get("media", "movie")
        self.tmdb_id = int(params.get("tmdb_id") or 0)
        self.season = int(params.get("season") or 0)
        self.episode = int(params.get("episode") or 0)
        if self.media == "movie":
            self.details = app.tmdb.movie(self.tmdb_id)
            self.show, self.episode_details = None, None
            runtime = int(self.details.get("runtime") or 0)
        else:
            self.show = app.tmdb.tv(self.tmdb_id)
            episodes = app.tmdb.season(self.tmdb_id, self.season).get("episodes", [])
            self.episode_details = next((e for e in episodes if int(e.get("episode_number") or 0) == self.episode),
                                        {"season_number": self.season, "episode_number": self.episode, "name": ""})
            runtime = int(self.episode_details.get("runtime") or 0) or int(
                (self.show.get("episode_run_time") or [0])[0] or 0)
        self.runtime_seconds = runtime * 60

    @classmethod
    def sample(cls):
        """A made-up film for the developer window tests: no TMDB needed."""
        target = cls.__new__(cls)
        target.media, target.tmdb_id, target.season, target.episode = "movie", 0, 0, 0
        target.details = {"id": 0, "title": "The Lighthouse Keeper", "release_date": "2024-05-01", "runtime": 112,
                          "imdb_id": "tt0000000", "overview": "A made-up film for SpongeTV's window tests.",
                          "genres": [{"name": "Drama"}]}
        target.show = target.episode_details = None
        target.runtime_seconds = 112 * 60
        target.prepared = (movie_request(target.details), choose.SAMPLE_TITLE, "2024 \u00b7 1 h 52 min \u00b7 Drama",
                           kodi.ICON, kodi.FANART)
        return target

    prepared = None

    @property
    def key(self):
        return (f"movie:{self.tmdb_id}" if self.media == "movie"
                else f"episode:{self.tmdb_id}:{self.season}:{self.episode}")

    def trakt_body(self, progress):
        if self.media == "movie":
            return {"movie": {"ids": {"tmdb": self.tmdb_id}}, "progress": round(progress, 2)}
        return {"show": {"ids": {"tmdb": self.tmdb_id}}, "episode": {"season": self.season, "number": self.episode},
                "progress": round(progress, 2)}

    def list_item(self, app, link):
        display = options.display(app)
        if self.media == "movie":
            art = artwork.for_title(self.details, app.preset, app.language, None, kodi.FANART)
            item = listing.movie_item(self.details, art, display)
        else:
            show_art = artwork.for_title(self.show, app.preset, app.language, None, kodi.FANART)
            art = artwork.for_episode(self.episode_details, show_art, app.preset)
            item = listing.episode_item(self.show, self.episode_details, art, display)
        item.setPath(link)
        return item


# -- resume points ------------------------------------------------------------------------------------------
def resume_key(target):
    return f"resume:{target.key}"


def saved_position(app, target):
    """Seconds to resume from: SpongeTV's own point, or Trakt's percentage of the runtime."""
    own = app.store.cache_get(resume_key(target))
    if own and own.get("position", 0) >= MIN_RESUME:
        return float(own["position"])
    if target.media == "movie":
        percent, _ = app.library.progress("movie", target.tmdb_id)
    else:
        percent, _ = app.library.progress("episode", show=target.tmdb_id, season=target.season, episode=target.episode)
    seconds = percent / 100 * target.runtime_seconds
    return seconds if seconds >= MIN_RESUME and percent < WATCHED_AT else 0


def clock_text(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def ask_resume(position):
    """0 = start over, the position to resume from, or None if you backed out."""
    if not position:
        return 0
    picked = xbmcgui.Dialog().contextmenu([kodi.text("resume_from", time=clock_text(position)), kodi.text("start_over")])
    if picked < 0:
        return None
    return position if picked == 0 else 0


def clear_kodi_resume(url):
    """Kodi saves its own resume point for add-on videos, which would ask a second time. Clear it."""
    request = {"jsonrpc": "2.0", "id": 1, "method": "Files.SetFileDetails",
               "params": {"file": url, "media": "video", "resume": {"position": 0, "total": 0}}}
    answer = xbmc.executeJSONRPC(json.dumps(request))
    try:
        return json.loads(answer).get("result") == "OK"
    except ValueError:
        return False


def kodi_resume(url):
    """Kodi's own saved resume point for this play address (seconds), or 0. Kodi shows it on the list item
    and asks "Resume from…" itself when you choose the item."""
    request = {"jsonrpc": "2.0", "id": 1, "method": "Files.GetFileDetails",
               "params": {"file": url, "media": "video", "properties": ["resume"]}}
    try:
        answer = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        return float(answer["result"]["filedetails"]["resume"]["position"] or 0)
    except (ValueError, KeyError, TypeError):
        return 0


# -- choosing and resolving -----------------------------------------------------------------------------------
def mode_for(media):
    return kodi.setting_int("play.movies" if media == "movie" else "play.episodes")


def resolve_link(app, target, source):
    if source.get("type") in ("direct", "adaptive"):
        return source["url"]
    if source.get("type") == "cloud":
        return app.premiumize.cloud_link(source["url"].split(":", 1)[1])
    return app.premiumize.resolve(source, *((target.season, target.episode) if target.media == "episode" else ()))


def resolve_first(app, target, candidates, attempts, progress=None):
    """Try candidates in order until one resolves. Returns (source, link) or (None, None)."""
    tried = 0
    for source in candidates:
        if tried >= attempts:
            break
        if source.get("debrid") == "uncached":
            continue   # Premiumize would have to download it first (release 2's caching assistant)
        tried += 1
        if progress:
            progress(tried, source)
        try:
            return source, resolve_link(app, target, source)
        except PremiumizeError as error:
            kodi.log(f"Couldn't resolve {source.get('release_title')}: {error}")
            if error.kind in ("no_key", "bad_key"):
                raise   # no other source will do better: play() explains
    return None, None


def pick_and_resolve(app, target, found):
    """Auto Play or Source Select, then resolve with fall-through. Returns (source, link) or (None, None)."""
    request, title, meta, poster, fanart, results, clear = found
    ordered = ranking.sort_sources(ranking.apply_filter(results, choose.filter_rules()[1], target.media),
                                   ranking.load_rules(app.store))
    attempts = max(1, kodi.setting_int("play.attempts") or 3)
    dialog = xbmcgui.DialogProgress()

    def resolving(number, source):
        if not dialog_open[0]:
            dialog.create(kodi.text("getting_link"), "")
            dialog_open[0] = True
        dialog.update(int(100 * (number - 1) / attempts), kodi.text("trying_source", number=number,
                      quality=source["quality"], name=source.get("release_title") or ""))
    dialog_open = [False]

    def finish(answer):
        if dialog_open[0]:
            dialog.close()
            dialog_open[0] = False
        return answer

    if mode_for(target.media) == AUTO_PLAY:
        source, link = resolve_first(app, target, ordered, attempts, resolving)
        finish(None)
        if link:
            return source, link
        kodi.notify(kodi.text("auto_play_failed"))
    chooser = windows.Chooser(results, target.media, title, meta, poster, fanart, choose.filter_rules,
                              lambda: ranking.load_rules(app.store),
                              {"filter": choose.pick_filter, "sort": lambda: choose.edit_sort_rules(app.store),
                               "clear": clear})
    while True:
        picked = windows.choose_source(chooser)
        if picked == windows.SEARCH_AGAIN:
            return windows.SEARCH_AGAIN, None
        if not picked:
            return None, None
        shown = chooser.visible()
        rest = shown[shown.index(picked) + 1:] if picked in shown else []
        source, link = resolve_first(app, target, [picked] + rest, attempts, resolving)
        finish(None)
        if link:
            return source, link
        kodi.notify(kodi.text("source_failed"))


# -- following playback -----------------------------------------------------------------------------------------
class Follower(xbmc.Player):
    """Scrobbles to Trakt and keeps SpongeTV's resume point while the video plays."""

    def __init__(self, app, target, url, start_at=0, clock=time.monotonic):
        super().__init__()
        self.app, self.target, self.url, self.start_at, self.clock = app, target, url, start_at, clock
        self.paused = False
        self.events = []
        self.on_tick = None          # Smart Play: called with (position, total) about once a second
        self.ended = False           # reached the end by itself (not stopped)

    def onAVStarted(self):
        self.events.append("started")

    def onPlayBackPaused(self):
        self.events.append("paused")

    def onPlayBackResumed(self):
        self.events.append("resumed")

    def onPlayBackStopped(self):
        self.events.append("stopped")

    def onPlayBackEnded(self):
        self.events.append("ended")
        self.ended = True

    def _scrobble(self, action, percent):
        if not self.app.signed_in or not self.target.tmdb_id:
            return   # not signed in, or the made-up window-test film
        try:
            self.app.trakt.scrobble(action, self.target.trakt_body(percent))
        except Exception as error:   # never let Trakt stop playback
            kodi.log_error(f"Scrobble {action} failed: {error}")

    def follow(self, monitor=None):
        """Wait for playback, then follow it to the end. Returns the last percentage watched."""
        monitor = monitor or xbmc.Monitor()
        waited = 0.0
        while not self.isPlayingVideo() and "started" not in self.events:
            if monitor.waitForAbort(0.5) or waited > START_WAIT or "stopped" in self.events:
                return 0
            waited += 0.5
        if self.start_at:
            try:
                if abs(self.getTime() - self.start_at) > 10:   # Kodi didn't use StartOffset: seek instead
                    self.seekTime(float(self.start_at))
            except RuntimeError:
                pass
        total = self._total()
        position = self.start_at or 0.0
        self._scrobble("start", self._percent(position, total))
        last_save = self.clock()
        while self.isPlayingVideo():
            try:
                position = self.getTime()
                total = self._total() or total
            except RuntimeError:
                break
            for event in self._take_events():
                if event == "paused":
                    self._scrobble("pause", self._percent(position, total))
                    self.save(position, total)
                elif event == "resumed":
                    self._scrobble("start", self._percent(position, total))
            if self.clock() - last_save >= SAVE_EVERY:
                self.save(position, total)
                last_save = self.clock()
            if self.on_tick:
                try:
                    self.on_tick(position, total)
                except Exception as error:   # Smart Play trouble must never stop playback
                    kodi.log_error(f"Smart Play: {error}")
                    self.on_tick = None
            if monitor.waitForAbort(1):
                break
        percent = self._percent(position, total)
        self._scrobble("stop", percent)
        self.save(position, total, finished=True)
        xbmcgui.Window(10000).setProperty("spongetv.sync_soon", "1")
        return percent

    def _take_events(self):
        events, self.events = self.events, []
        return [e for e in events if e in ("paused", "resumed")]

    def _total(self):
        try:
            return self.getTotalTime() or self.target.runtime_seconds
        except RuntimeError:
            return self.target.runtime_seconds

    @staticmethod
    def _percent(position, total):
        return min(100.0, 100.0 * position / total) if total else 0.0

    def save(self, position, total, finished=False):
        percent = self._percent(position, total)
        key = resume_key(self.target)
        if percent >= WATCHED_AT or position < MIN_RESUME:
            if finished:
                self.app.store.cache_delete(key)
            return
        self.app.store.cache_set(key, {"position": position, "total": total, "percent": percent}, 365 * 86400)


# -- the play action ---------------------------------------------------------------------------------------------
def play(plugin, app, target=None):
    playable = plugin.handle >= 0     # Kodi is waiting for setResolvedUrl
    resolved = False
    try:
        windows.close_busy()
        try:
            target = target or Target(app, plugin.params)
        except Exception as error:
            kodi.log_error(f"Couldn't load details to play: {error}")
            kodi.notify(kodi.text("tmdb_unreachable"))
            return
        if plugin.params.get("kr") or (playable and kodi_resume(plugin.url_now)):
            start_at = 0   # chosen from a list showing a resume point: Kodi has already asked and resumes itself
        else:
            start_at = ask_resume(saved_position(app, target))
            if start_at is None:
                return
        fresh = plugin.params.get("fresh") == "1"   # "Search for sources again"
        while True:
            found = choose.find_sources(app, plugin.params, target.prepared, fresh=fresh)
            if not found:
                return
            try:
                source, link = pick_and_resolve(app, target, found)
            except PremiumizeError as error:
                xbmcgui.Dialog().ok(kodi.text("grp_premiumize"),
                                    kodi.text("pm_no_key" if error.kind == "no_key" else "pm_bad_key"))
                return
            if source != windows.SEARCH_AGAIN:
                break
            fresh = True                              # "Search again" in Source Select
        if not link:
            return
        item = target.list_item(app, link)
        if start_at:
            item.setProperty("StartOffset", str(int(start_at)))   # Kodi starts there; follow() checks it did
        if playable:
            plugin.resolve(item)
        else:   # started some other way (RunPlugin): play it ourselves
            xbmc.Player().play(link, item)
        resolved = True
        kodi.log(f"Playing {target.key} from {source.get('provider')}: {source.get('release_title')}")
        follow_episodes(app, target, plugin.url_now, start_at)
    finally:
        if not resolved and playable:
            plugin.resolve_nothing()


def first_episode(app, show):
    """(season, episode) to start a show from: after your last watched episode, else the first aired."""
    from resources.lib import mine, smartplay
    if app.signed_in:
        found = mine.next_episode(show, app.library.watched_episodes(show["id"]))
        if found:
            return found
        if app.library.watched_episodes(show["id"]):
            return None   # watched everything that's aired
    seasons = sorted(s["season_number"] for s in show.get("seasons") or [] if s.get("season_number"))
    if not seasons:
        return None
    episodes = app.tmdb.season(show["id"], seasons[0]).get("episodes", [])
    if episodes and airtime.has_aired(episodes[0].get("air_date"), show.get("origin_country")):
        return seasons[0], int(episodes[0]["episode_number"])
    return smartplay.next_episode(app, show, seasons[0], 0)


def play_show(plugin, app):
    """A show's "Play next episode": the next one you haven't watched (Seren's "resume a show")."""
    try:
        show = app.tmdb.tv(plugin.params.get("tmdb_id"))
    except Exception:
        kodi.notify(kodi.text("tmdb_unreachable"))
        plugin.resolve_nothing()
        return
    found = first_episode(app, show)
    if not found:
        kodi.notify(kodi.text("nothing_next"))
        plugin.resolve_nothing()
        return
    plugin.params.update({"media": "episode", "season": found[0], "episode": found[1]})
    play(plugin, app)


def follow_episodes(app, target, url, start_at):
    """Follow playback, then keep going with the next episode for as long as Smart Play says so."""
    from resources.lib import smartplay
    monitor = xbmc.Monitor()
    in_a_row = 1          # episodes watched in a row, including this one
    while True:
        follower = Follower(app, target, url, start_at)
        smart = smartplay.SmartPlay(app, target, follower)
        follower.on_tick = smart.tick
        try:
            follower.follow(monitor)
            ended = follower.ended
        finally:
            del follower   # Kodi players must be released before the script ends
        prepared = smart.finish(ended)
        if prepared is None or monitor.abortRequested():
            return
        carry_on, asked = smartplay.still_watching(in_a_row)
        if not carry_on:
            return
        in_a_row = 1 if asked else in_a_row + 1
        smartplay.wait_for(prepared, monitor)
        target, start_at = prepared.target, 0
        link = prepared.link
        if not link:   # nothing ready: the normal way, with the search window and Source Select
            found = choose.find_sources(app, {"media": "episode", "tmdb_id": target.tmdb_id,
                                              "season": target.season, "episode": target.episode})
            if not found:
                return
            try:
                _, link = pick_and_resolve(app, target, found)
            except PremiumizeError:
                return
            if not link:
                return
        url = link   # played directly, so Kodi files its resume point against the link
        xbmc.Player().play(link, target.list_item(app, link))

