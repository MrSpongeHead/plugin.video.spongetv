# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Smart Play, Playing Next and Still Watching."""

import pytest

from conftest import FakeAddon, FakeDialog
from resources.lib import context, playback, smartplay
from test_menus import PAST, FUTURE
from test_playback import premiumize  # noqa: F401  (fixture)
from test_sources import with_test_provider, tmdb  # noqa: F401  (fixtures)

SEASON_1 = {"episodes": [{"id": 1, "name": "One", "season_number": 1, "episode_number": 1, "air_date": PAST},
                         {"id": 2, "name": "Two", "season_number": 1, "episode_number": 2, "air_date": PAST}]}
SEASON_2 = {"episodes": [{"id": 3, "name": "Three", "season_number": 2, "episode_number": 1, "air_date": PAST},
                         {"id": 4, "name": "Four", "season_number": 2, "episode_number": 2, "air_date": FUTURE}]}


@pytest.fixture
def show(premiumize, tmdb):
    tmdb.seasons[(50, 1)] = SEASON_1
    tmdb.seasons[(50, 2)] = SEASON_2
    FakeAddon.settings.update({"play.next": True, "play.next_seconds": 30, "play.still_watching": 3,
                               "play.episodes": playback.AUTO_PLAY})
    return tmdb


def test_next_episode_crosses_seasons_and_stops_at_unaired(show):
    app = context.App()
    details = app.tmdb.tv(50)
    assert smartplay.next_episode(app, details, 1, 1) == (1, 2)
    assert smartplay.next_episode(app, details, 1, 2) == (2, 1)
    assert smartplay.next_episode(app, details, 2, 1) is None          # S02E02 hasn't aired


class FakePlayer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def target(app, season, episode):
    return playback.Target(app, {"media": "episode", "tmdb_id": 50, "season": season, "episode": episode})


def test_prepares_early_then_card_offers_play_now(show, monkeypatch):
    app = context.App()
    started = []

    def fake_prepare(prepared, should_stop):
        started.append(prepared.target.key)
        prepared.link = "https://dl/next"
        prepared.done.set()
    monkeypatch.setattr(smartplay, "prepare", fake_prepare)
    player = FakePlayer()
    smart = smartplay.SmartPlay(app, target(app, 1, 1), player)
    smart.tick(100, 3000)
    assert started == []                               # too early
    smart.tick(2750, 3000)
    import time
    time.sleep(0.05)
    assert started == ["episode:50:1:2"]
    assert smart.window is None                        # the card waits for the last 30 seconds
    shown = []
    monkeypatch.setattr(smartplay.SmartPlay, "_show_card", lambda self: (shown.append(1), setattr(self, "window", Card())))
    smart.tick(2975, 3000)
    assert shown == [1]
    smart.window.choice = "now"
    smart.tick(2976, 3000)
    assert player.stopped and smart.finish(ended=False).link == "https://dl/next"


class Card:
    choice = None

    def setProperty(self, key, value):
        pass

    def getControl(self, control_id):
        raise RuntimeError("no control in tests")

    def close(self):
        pass


def test_stop_after_and_stopping_yourself(show):
    app = context.App()
    smart = smartplay.SmartPlay(app, target(app, 1, 1), FakePlayer())
    smart.choice = "stop"
    assert smart.finish(ended=True) is None
    smart = smartplay.SmartPlay(app, target(app, 1, 1), FakePlayer())
    assert smart.finish(ended=False) is None           # you pressed Stop
    assert smart.finish(ended=True) is not None        # it ran to the end


def test_no_next_for_films_or_when_switched_off(show):
    app = context.App()
    FakeAddon.settings["play.next"] = False
    assert smartplay.SmartPlay(app, target(app, 1, 1), FakePlayer()).next is None
    FakeAddon.settings["play.next"] = True
    assert smartplay.SmartPlay(app, target(app, 2, 1), FakePlayer()).next is None   # nothing aired after it


def test_still_watching():
    FakeAddon.settings["play.still_watching"] = 3
    assert smartplay.still_watching(2) == (True, False)
    FakeDialog.script = [False]
    assert smartplay.still_watching(3) == (False, True)
    FakeDialog.script = [True]
    assert smartplay.still_watching(3) == (True, True)
    FakeAddon.settings["play.still_watching"] = 0
    assert smartplay.still_watching(10) == (True, False)


def test_episodes_play_on_until_you_say_stop(show, monkeypatch):
    """Three episodes end by themselves; after the third in a row SpongeTV asks, and you say stop."""
    import xbmc
    played, follows = [], []

    def fake_follow(self, monitor=None):
        follows.append(self.target.key)
        self.ended = True
        return 100
    monkeypatch.setattr(playback.Follower, "follow", fake_follow)

    def fake_prepare(prepared, should_stop):
        prepared.link = f"https://dl/{prepared.target.key}"
        prepared.done.set()
    monkeypatch.setattr(smartplay, "prepare", fake_prepare)
    monkeypatch.setattr(smartplay.SmartPlay, "_show_card", lambda self: setattr(self, "choice", "auto"))
    monkeypatch.setattr(xbmc.Player, "play", lambda self, link, item=None: played.append(link), raising=False)
    original_tick = smartplay.SmartPlay.tick

    def finish_with_prepare(self, ended):
        original_tick(self, 2990, 3000)                 # as if the end of the episode came round
        import time
        time.sleep(0.05)
        return original_finish(self, ended)
    original_finish = smartplay.SmartPlay.finish
    monkeypatch.setattr(smartplay.SmartPlay, "finish", finish_with_prepare)
    FakeAddon.settings["play.still_watching"] = 2
    FakeDialog.script = [False]                         # "Still watching?" -> Stop
    app = context.App()
    playback.follow_episodes(app, target(app, 1, 1), "plugin://x", 0)
    assert follows == ["episode:50:1:1", "episode:50:1:2"]
    assert played == ["https://dl/episode:50:1:2"]
    assert any(kind == "yesno" for kind, _ in FakeDialog.shown)


def test_play_next_episode_of_a_show(show, monkeypatch):
    from test_menus import call
    from conftest import Directory
    seen = []
    monkeypatch.setattr(playback, "play", lambda plugin, app, target=None: seen.append(dict(plugin.params)))
    call("?action=play_show&tmdb_id=50")
    assert seen and (seen[0]["season"], seen[0]["episode"]) == (1, 1)    # not signed in: from the start
    assert Directory.resolved is None


def test_tv_context_menu_offers_play_next_episode(show):
    from test_menus import call
    from conftest import Directory
    call("?action=tv_list&kind=popular")
    menu = [label for label, _ in Directory.items[0][1].context_menu]
    assert "Play next episode" in menu
