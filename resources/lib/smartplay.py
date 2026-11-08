# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Smart Play, Playing Next and Still Watching.

While an episode plays, SpongeTV quietly finds and resolves the next one, so it can start straight
away. Near the end the Playing Next card offers "Play now" or "Stop after this episode". After a set
number of episodes in a row, it asks whether you're still watching before carrying on.
"""

import threading

import xbmc
import xbmcgui

from resources.lib import airtime, choose, context, kodi, ranking, windows
from resources.lib.premiumize import PremiumizeError
from resources.lib.sources import Search
from resources.lib.tmdb import image_url

PREPARE_BEFORE = 300        # seconds before the end to start finding the next episode
NEXT_XML = "spongetv-playingnext.xml"


def next_episode(app, show, season, episode):
    """(season, episode) of the next aired episode after this one, or None. Specials are skipped."""
    countries = show.get("origin_country")
    numbers = sorted(s.get("season_number") for s in show.get("seasons") or [] if s.get("season_number"))
    for number in [n for n in numbers if n >= season]:
        episodes = app.tmdb.season(show["id"], number).get("episodes", [])
        for item in sorted(episodes, key=lambda e: e.get("episode_number") or 0):
            if number == season and (item.get("episode_number") or 0) <= episode:
                continue
            if not airtime.has_aired(item.get("air_date"), countries):
                return None
            return number, int(item["episode_number"])
    return None


class Prepared:
    """The next episode, and (once found) a source and a link that plays."""

    def __init__(self, target):
        self.target = target
        self.source = None
        self.link = None
        self.done = threading.Event()


def prepare(prepared, should_stop):
    """Runs in the background: a quiet search (no windows), then resolve the best source."""
    from resources.lib import playback
    app = context.App()
    try:
        target = prepared.target
        request, *_ = choose._request_for(app, {"media": "episode", "tmdb_id": target.tmdb_id,
                                                "season": target.season, "episode": target.episode})
        providers = choose.packages(app).providers(enabled_only=True)
        if app.premiumize.ready and kodi.setting_bool("premiumize.cloud"):
            providers = providers + [choose.CLOUD_PROVIDER]
        checker = choose._checker(app)
        search = Search(providers, request, timeout=max(kodi.setting_int("sources.timeout"), 5),
                        early_stop=choose.early_stop(ready_only=checker is not None),
                        host_lists=choose._host_lists(app), call=choose._call_with_cloud(app), checker=checker).start()
        search.wait(should_stop=should_stop)
        search.check_new()
        ordered = ranking.sort_sources(ranking.apply_filter(search.results(), choose.filter_rules()[1], "episode"),
                                       ranking.load_rules(app.store))
        prepared.source, prepared.link = playback.resolve_first(app, target, ordered,
                                                               max(1, kodi.setting_int("play.attempts") or 3))
    except (PremiumizeError, Exception) as error:   # the normal play flow will try again at the end
        kodi.log(f"Smart Play couldn't prepare the next episode: {error}")
    finally:
        app.store.close()
        prepared.done.set()


class PlayingNextWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.choice = None          # "now" or "stop"

    def onClick(self, control_id):
        if control_id == 4001:
            self.choice = "now"
        elif control_id == 4002:
            self.choice = "stop"
        self.close()

    def onAction(self, action):
        if action.getId() in windows.BACK_ACTIONS:
            self.close()            # just hides the card; the next episode still plays


class SmartPlay:
    """Watches one episode's playback and decides what happens at the end."""

    def __init__(self, app, target, player):
        self.app, self.target, self.player = app, target, player
        self.enabled = kodi.setting_bool("play.next")
        self.card_seconds = max(10, kodi.setting_int("play.next_seconds") or 30)
        self.prepared = None
        self.window = None
        self.choice = None
        self.next = None
        self.cancelled = False
        if self.enabled and target.media == "episode" and target.tmdb_id:
            found = next_episode(app, target.show, target.season, target.episode)
            if found:
                from resources.lib import playback
                self.next = found
                self.next_target = playback.Target(app, {"media": "episode", "tmdb_id": target.tmdb_id,
                                                         "season": found[0], "episode": found[1]})

    def tick(self, position, total):
        if not self.next or not total:
            return
        left = total - position
        if left <= PREPARE_BEFORE and self.prepared is None:
            self.prepared = Prepared(self.next_target)
            threading.Thread(target=prepare, args=(self.prepared, lambda: self.cancelled), daemon=True).start()
        if left <= self.card_seconds and self.window is None and self.choice is None:
            self._show_card()
        if self.window is not None:
            self._update_card(left)
            if self.window.choice:
                self.choice = self.window.choice
                self._close_card()
                if self.choice == "now":
                    self.player.stop()

    def _show_card(self):
        try:
            self.window = PlayingNextWindow(NEXT_XML, kodi.ADDON_PATH, "Default", "1080i")
        except RuntimeError as error:
            kodi.log_error(f"Playing Next window unavailable: {error}")
            self.window = None
            self.choice = "auto"
            return
        episode = self.next_target.episode_details
        values = {"heading": kodi.text("playing_next"), "show": self.target.show.get("name", ""),
                  "episode": kodi.text("next_episode_line", season=self.next[0], episode=self.next[1],
                                       title=episode.get("name") or ""),
                  "thumb": image_url(episode.get("still_path"), "w300") or "",
                  "play_now": kodi.text("play_now"), "stop_after": kodi.text("stop_after")}
        for key, value in values.items():
            self.window.setProperty(key, value)
        self.window.show()

    def _update_card(self, left):
        ready = self.prepared and self.prepared.done.is_set()
        status = (kodi.text("next_ready") if ready and self.prepared.link
                  else kodi.text("next_not_found") if ready else kodi.text("next_finding"))
        self.window.setProperty("status", kodi.text("next_countdown", seconds=max(0, int(left)), status=status))
        try:
            self.window.getControl(4100).setPercent(100 * max(0.0, left) / self.card_seconds)
        except (RuntimeError, TypeError):
            pass

    def _close_card(self):
        if self.window is not None:
            self.window.close()
            del self.window
            self.window = None

    def finish(self, ended):
        """After playback: returns the next episode's Prepared to play, or None to stop."""
        self._close_card()
        if not self.next or self.choice == "stop":
            self.cancelled = True
            return None
        if not ended and self.choice != "now":
            self.cancelled = True     # you stopped it yourself
            return None
        if self.prepared is None:
            self.prepared = Prepared(self.next_target)
            self.prepared.done.set()
        return self.prepared


def still_watching(count):
    """(carry on?, asked?) after <count> episodes in a row. Asks once that reaches the setting (0 = never)."""
    limit = kodi.setting_int("play.still_watching")
    if not limit or count < limit:
        return True, False
    return bool(xbmcgui.Dialog().yesno(kodi.text("still_watching_heading"), kodi.text("still_watching", count=count),
                                       nolabel=kodi.text("stop"), yeslabel=kodi.text("keep_watching"),
                                       autoclose=60000)), True


def wait_for(prepared, monitor, seconds=20):
    """Give a search that's still running a little longer once the episode has ended."""
    waited = 0
    while not prepared.done.is_set() and waited < seconds and not monitor.abortRequested():
        xbmc.sleep(250)
        waited += 0.25
