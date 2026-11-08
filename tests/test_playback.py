# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Stage 4: pressing play end to end, with the test provider and a stand-in Premiumize."""

import json

import pytest

from conftest import Directory, FakeAddon, FakeDialog
from resources.lib import context, playback, ranking
from resources.lib.premiumize import Premiumize
from resources.lib.sources import EarlyStop, Search, normalise
from test_premiumize import FakePm
from test_sources import with_test_provider, tmdb  # noqa: F401  (fixtures)
from test_menus import call


class EveryTorrentCached(FakePm):
    """Every torrent is cached; resolving gives one video named after the hash, unless told to fail."""

    def __init__(self, failing=()):
        super().__init__()
        self.failing = set(failing)
        self.resolved = []

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        path = url.rsplit("/api/", 1)[-1]
        if path == "cache/check":
            self.cached = {v: True for k, v in form if k == "items[]"}
        if path == "transfer/directdl":
            src = form["src"]
            self.resolved.append(src)
            if not any(h in src for h in self.failing):
                self.transfers[src] = [{"path": "Video.S01E01.mkv", "size": 10, "link": f"https://dl/{src[-6:]}"}]
        return super().send(method, url, params, json_body, headers, max_wait, form)


@pytest.fixture
def premiumize(with_test_provider, monkeypatch):
    fake = EveryTorrentCached()
    monkeypatch.setattr(playback, "START_WAIT", 1)
    monkeypatch.setattr(context.App, "premiumize", property(lambda app: Premiumize(fake, "good", app.store)))
    FakeAddon.settings.update({"premiumize.api_key": "good", "premiumize.torrents": True, "premiumize.hosters": True,
                               "premiumize.cloud": True, "play.attempts": 3, "sources.hide_uncached": True,
                               "early.enabled": False})
    return fake


def test_auto_play_resolves_and_follows_playback(premiumize):
    import xbmc
    FakeAddon.settings["play.movies"] = playback.AUTO_PLAY
    xbmc.Player.script = [(30, 6000), (95, 6000), (130, 6000)]
    call("?action=play&media=movie&tmdb_id=7")
    assert Directory.resolved is True
    assert len(premiumize.resolved) == 1
    store = context.App().store
    assert store.cache_get("resume:movie:7")["position"] == 130         # saved on stop
    # Kodi's own resume point is read (to avoid a second prompt) but never changed after playback:
    # changing it makes Kodi blank the list item's details
    assert [json.loads(r)["method"] for r in xbmc.jsonrpc] == ["Files.GetFileDetails"]
    import xbmcgui
    assert xbmcgui.Window.properties.get("spongetv.sync_soon") == "1"


def test_auto_play_moves_on_when_a_source_fails(premiumize, monkeypatch):
    FakeAddon.settings["play.movies"] = playback.AUTO_PLAY
    from resources.lib import choose
    real = choose.find_sources

    def first_fails(app, params, prepared=None, fresh=False):
        found = real(app, params, prepared, fresh)
        ordered = ranking.sort_sources(found[5], ranking.load_rules(app.store))
        premiumize.failing.add(ordered[0]["hash"])
        return found
    monkeypatch.setattr(choose, "find_sources", first_fails)
    call("?action=play&media=movie&tmdb_id=7")
    assert Directory.resolved is True and len(premiumize.resolved) == 2


def test_source_select_plays_what_you_pick(premiumize):
    FakeAddon.settings["play.movies"] = playback.SOURCE_SELECT
    FakeDialog.script = [2]     # the second source (row 0 is "Filter and sort")
    call("?action=play&media=movie&tmdb_id=7")
    assert Directory.resolved is True and len(premiumize.resolved) == 1


def test_backing_out_of_source_select_plays_nothing(premiumize):
    FakeAddon.settings["play.movies"] = playback.SOURCE_SELECT
    FakeDialog.script = [-1]
    call("?action=play&media=movie&tmdb_id=7")
    assert Directory.resolved is False and premiumize.resolved == []


def test_resume_prompt_and_seek(premiumize, monkeypatch):
    import xbmc
    FakeAddon.settings["play.movies"] = playback.AUTO_PLAY
    context.App().store.cache_set("resume:movie:7", {"position": 1930, "total": 6000, "percent": 32}, 3600)
    seeks = []
    monkeypatch.setattr(xbmc.Player, "seekTime", lambda self, s: seeks.append(s))
    xbmc.Player.script = [(2, 6000), (1931, 6000)]   # Kodi ignored StartOffset, so SpongeTV seeks
    FakeDialog.script = [0]     # Resume from 32:10
    call("?action=play&media=movie&tmdb_id=7")
    assert ("contextmenu", ("Resume from 32:10", "Start from the beginning")) in FakeDialog.shown
    assert seeks == [1930]


def test_watching_to_the_end_clears_the_resume_point(premiumize):
    import xbmc
    FakeAddon.settings["play.movies"] = playback.AUTO_PLAY
    store = context.App().store
    store.cache_set("resume:movie:7", {"position": 1930, "total": 6000, "percent": 32}, 3600)
    FakeDialog.script = [1]     # Start from the beginning
    xbmc.Player.script = [(100, 6000), (5900, 6000)]
    call("?action=play&media=movie&tmdb_id=7")
    assert context.App().store.cache_get("resume:movie:7") is None


def test_episode_from_a_season_pack(premiumize):
    FakeAddon.settings["play.episodes"] = playback.AUTO_PLAY
    call("?action=play&media=episode&tmdb_id=50&season=1&episode=1")
    assert Directory.resolved is True


def test_clock_text():
    assert playback.clock_text(1930) == "32:10"
    assert playback.clock_text(3725) == "1:02:05"


# -- readiness during the search -------------------------------------------------------------------------
def src(title, h):
    return {"hash": h, "release_title": title}


def test_search_marks_readiness_and_early_stop_counts_only_ready():
    import time
    cached = {"aa" * 20, "bb" * 20}

    def checker(sources):
        for s in sources:
            s["debrid"] = "cached" if s["hash"] in cached else "uncached"

    def call_(provider, request, host_lists):
        return [src("F.1080p.a", "aa" * 20), src("F.1080p.b", "bb" * 20), src("F.1080p.c", "cc" * 20)]
    providers = [{"package": "P", "language": "en", "kind": "torrent", "name": "a"}]
    search = Search(providers, {"media": "movie"}, call=call_, checker=checker,
                    early_stop=EarlyStop(True, "1080p", 3, ready_only=True)).start()
    for _ in range(100):
        if search.status()["finished"]:
            break
        time.sleep(0.01)
    search.check_new()
    status = search.status()
    assert status["ready"] == 2 and not status["stopped_early"]       # only 2 of the 3 are ready
    assert sorted(s["debrid"] for s in search.results()) == ["cached", "cached", "uncached"]


def test_hide_uncached_filter():
    provider = {"name": "p", "package": "P"}
    a = normalise(src("F.1080p", "aa" * 20), provider, "torrent")
    b = normalise(src("F.720p", "bb" * 20), provider, "torrent")
    a["debrid"], b["debrid"] = "cached", "uncached"
    rules = dict(ranking.PRESETS[ranking.PRESET_EVERYTHING], ready_only=True)
    assert ranking.apply_filter([a, b], rules, "movie") == [a]


# -- one resume prompt, and clearing it ------------------------------------------------------------------
def test_kodi_asks_so_spongetv_does_not(premiumize):
    """From a list item that shows a resume point, Kodi asks itself; SpongeTV mustn't ask a second time."""
    FakeAddon.settings["play.movies"] = playback.AUTO_PLAY
    context.App().store.cache_set("resume:movie:7", {"position": 1930, "total": 6000, "percent": 32}, 3600)
    call("?action=play&media=movie&tmdb_id=7&kr=1")
    assert not any(kind == "contextmenu" for kind, _ in FakeDialog.shown)
    assert Directory.resolved is True


def test_own_resume_point_reaches_the_list_item():
    from resources.lib import listing
    from resources.lib.database import Store
    from resources.lib.library import Library
    from resources.lib.marks import Marks
    import tempfile, os
    store = Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    store.cache_set("resume:movie:7", {"position": 1930.0, "total": 6000.0, "percent": 32.2}, 3600)
    mark = Marks(Library(store)).movie(7)
    assert mark == (0, 32.2, 1930.0, 6000.0)
    item = listing.movie_item({"id": 7, "title": "Film", "runtime": 98}, {}, marks=mark)
    assert item.getVideoInfoTag().calls["setResumePoint"] == [(1930.0, 6000.0)]
    store.close()


def test_clear_resume_point_clears_all_three(premiumize, monkeypatch):
    import xbmc
    from resources.lib import actions
    app = context.App()
    app.store.cache_set("resume:episode:50:1:2", {"position": 600, "total": 3000, "percent": 20}, 3600)
    target = actions.Target({"media": "episode", "show": "50", "season": "1", "episode": "2"})
    monkeypatch.setattr(app.library, "progress", lambda *a, **k: (0, None))
    assert actions.clear_progress(app, target)
    assert app.store.cache_get("resume:episode:50:1:2") is None
    cleared = [json.loads(r)["params"]["file"] for r in xbmc.jsonrpc]
    assert "plugin://plugin.video.spongetv/?action=play&media=episode&tmdb_id=50&season=1&episode=2" in cleared
    assert "plugin://plugin.video.spongetv/?action=play&media=episode&tmdb_id=50&season=1&episode=2&kr=1" in cleared



# -- searching again ---------------------------------------------------------------------------------------
def test_search_again_from_the_context_menu_ignores_saved_results(premiumize, monkeypatch):
    from resources.lib import choose
    FakeAddon.settings["play.movies"] = playback.AUTO_PLAY
    call("?action=play&media=movie&tmdb_id=7")
    searches = []
    real = choose.Search
    monkeypatch.setattr(choose, "Search", lambda *a, **k: searches.append(1) or real(*a, **k))
    call("?action=play&media=movie&tmdb_id=7")
    assert searches == []                                  # saved results reused
    call("?action=play&media=movie&tmdb_id=7&fresh=1")
    assert searches == [1] and Directory.resolved is True  # a fresh search, then played


def test_search_again_from_source_select(premiumize, monkeypatch):
    from resources.lib import choose
    FakeAddon.settings["play.movies"] = playback.SOURCE_SELECT
    searches = []
    real = choose.Search
    monkeypatch.setattr(choose, "Search", lambda *a, **k: searches.append(1) or real(*a, **k))
    FakeDialog.script = [0, 2, 1]     # "Filter and sort" row -> "Search for sources again" -> then the first source
    call("?action=play&media=movie&tmdb_id=7")
    assert searches == [1, 1] and Directory.resolved is True


def test_context_menus_offer_search_again_and_clear_resume(premiumize):
    from test_menus import call as list_call
    app = context.App()
    app.store.cache_set("resume:movie:7", {"position": 600, "total": 6000, "percent": 10}, 3600)
    list_call("?action=movie_list&kind=popular")
    menus = {i[1].label: [label for label, _ in i[1].context_menu] for i in Directory.items}
    film = next(m for m in menus.values() if "Clear resume point" in m)
    assert "Search for sources again" in film
    call("?action=clear_resume&media=movie&tmdb_id=7")
    assert app.store.cache_get("resume:movie:7") is None



def test_kodi_resume_point_means_kodi_asks(premiumize, monkeypatch):
    """Kodi saved its own resume point (after 3 minutes) and asks about it itself: SpongeTV mustn't."""
    import xbmc
    FakeAddon.settings["play.movies"] = playback.AUTO_PLAY
    context.App().store.cache_set("resume:movie:7", {"position": 1930, "total": 6000, "percent": 32}, 3600)
    monkeypatch.setattr(xbmc, "executeJSONRPC", lambda request: json.dumps(
        {"result": {"filedetails": {"resume": {"position": 1930.0, "total": 6000.0}}}}))
    call("?action=play&media=movie&tmdb_id=7")
    assert not any(kind == "contextmenu" for kind, _ in FakeDialog.shown)
    assert Directory.resolved is True
