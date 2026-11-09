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
    import xbmc
    FakeAddon.settings["play.movies"] = playback.SOURCE_SELECT
    FakeDialog.script = [-1]
    call("?action=play&media=movie&tmdb_id=7")
    assert Directory.resolved is False and premiumize.resolved == []
    assert xbmc.PlayList.cleared == 1     # so Kodi doesn't say "Playback failed" or play the next item


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


def test_kodi_playback_failed_message_is_closed(monkeypatch):
    """Backing out makes Kodi say "Playback failed"; SpongeTV closes that message."""
    import xbmc
    from resources.lib import plugin
    shown = {"okdialog": True}
    monkeypatch.setattr(xbmc, "getCondVisibility", lambda cond: shown["okdialog"], raising=False)
    monkeypatch.setattr(xbmc, "getInfoLabel", lambda label: "Playback failed", raising=False)
    monkeypatch.setattr(xbmc, "getLocalizedString", lambda number: "Playback failed" if number == 16026 else "",
                        raising=False)
    closed = []
    monkeypatch.setattr(xbmc, "executebuiltin", lambda command: closed.append(command), raising=False)

    class Running:
        def abortRequested(self):
            return False

        def waitForAbort(self, seconds=0):
            return False
    assert plugin.dismiss_playback_failed(monitor=Running())
    assert closed == ["Dialog.Close(okdialog,true)"]
    shown["okdialog"] = False
    assert not plugin.dismiss_playback_failed(wait=0.3, monitor=Running())


def test_ready_line_says_when_premiumize_is_still_being_asked():
    from resources.lib import windows
    assert windows.ready_line({"ready": None}) == ""
    assert windows.ready_line({"ready": 0, "checking": 12}) == "Asking Premiumize which of 12 are ready…"
    assert windows.ready_line({"ready": 3, "checking": 4}) == "3 ready to play now (checking 4 more)"
    assert windows.ready_line({"ready": 3, "checking": 0}) == "3 ready to play now: cached in Premiumize or in your cloud"
    assert windows.ready_line({"ready": 0, "check_failed": True}) == "Couldn't ask Premiumize which are ready"


def test_last_sources_are_checked_after_the_search_ends():
    import time
    seen = []

    def checker(sources):
        seen.extend(s["hash"] for s in sources)
        for s in sources:
            s["debrid"] = "cached"

    def call_(provider, request, host_lists):
        return [src(f"F.1080p.{provider['name']}", provider["name"] * 20)]
    providers = [{"package": "P", "language": "en", "kind": "torrent", "name": n} for n in ("aa", "bb", "cc")]
    search = Search(providers, {"media": "movie"}, call=call_, checker=checker).start()
    for _ in range(200):
        if search.status()["finished"]:
            break
        time.sleep(0.01)
    for _ in range(100):                       # the checker thread finishes on its own
        if search.status()["checking"] == 0:
            break
        time.sleep(0.02)
    assert search.status()["checking"] == 0 and search.status()["ready"] == 3


def test_search_window_buttons_get_focus():
    from resources.lib import windows

    class Window:
        """Like Kodi: focusing a disabled button does nothing; buttons enable on the next refresh."""
        def __init__(self):
            self.focus, self.choose_tries, self.enabled = 0, 0, False

        def getFocusId(self):
            return self.focus

        def setFocusId(self, control):
            if control != 3001 or self.enabled:
                self.focus = control
    window = Window()
    windows.focus_buttons(window, can_choose=False)
    assert window.focus == 3002                    # nothing found yet: Cancel, so OK always does something
    windows.focus_buttons(window, can_choose=True)
    assert window.focus == 3002                    # Choose isn't enabled until the next refresh...
    window.enabled = True
    windows.focus_buttons(window, can_choose=True)
    assert window.focus == 3001                    # ...so it tries again
    windows.focus_buttons(window, can_choose=True)
    window.focus = 3002                            # then you move back to Cancel yourself
    windows.focus_buttons(window, can_choose=True)
    assert window.focus == 3002



def test_choose_count_waits_for_premiumize_and_never_drops():
    """Sources count only once Premiumize has answered, so the count can't show 5 then fall to 1."""
    import threading
    import time
    from resources.lib import ranking
    gate = threading.Event()

    def checker(sources):
        gate.wait(5)                                 # Premiumize takes a moment to answer
        for s in sources:
            s["debrid"] = "cached" if s["hash"].startswith("aa") else "uncached"

    def call_(provider, request, host_lists):
        return [src("F.1080p.1", "aa" * 20)] + [src(f"F.1080p.{i}", f"b{i}" * 20) for i in range(2, 6)]
    rules = dict(ranking.PRESETS[ranking.PRESET_EVERYTHING], ready_only=True)
    providers = [{"package": "P", "language": "en", "kind": "torrent", "name": "a"}]
    search = Search(providers, {"media": "movie"}, call=call_, checker=checker,
                    visible=lambda sources: ranking.apply_filter(sources, rules, "movie")).start()
    seen = []
    for _ in range(20):
        seen.append(search.status()["choosable"])
        time.sleep(0.01)
    gate.set()
    for _ in range(100):
        seen.append(search.status()["choosable"])
        if seen[-1]:
            break
        time.sleep(0.02)
    assert max(seen) == 1 and seen[-1] == 1          # never 5: only the one cached copy ever counted



# -- the windows' wording, as in the mock-ups ---------------------------------------------------------------
def test_search_lines_match_the_mock_up():
    from resources.lib import windows
    status = {"searching": ["a", "b", "Your cloud", "c"], "cloud": "searching"}
    assert windows.searching_line(status) == "Still searching: 3 providers \u00b7 Premiumize cloud searching"
    status = {"searching": ["a", "b", "c"], "cloud": "finished"}
    assert windows.searching_line(status) == "Still searching: 3 providers \u00b7 Premiumize cloud finished"
    assert windows.searching_line({"searching": [], "cloud": "finished"}) == ""


def test_source_select_header_matches_the_mock_up():
    from resources.lib import ranking, windows
    from resources.lib.sources import normalise
    p = {"name": "p", "package": "P"}
    rows = [normalise({"hash": f"{i:040x}", "release_title": "F.1080p", "size": 1000}, p, "torrent") for i in range(8)]
    for n, row in enumerate(rows):
        row["debrid"] = "cached" if n < 6 else "uncached"
    assert windows.select_subheading("Film (2024)", rows, rows) == \
        "Film (2024) \u00b7 8 sources \u00b7 6 ready to play now"
    assert windows.select_subheading("Film (2024)", rows[:6], rows).endswith("\u00b7 2 hidden")
    assert windows.sort_label(ranking.DEFAULT_RULES) == "Sort: ready first"
    assert windows.sort_label([("ready", False), ("quality", True)]) == "Sort: best first"
    item = windows.list_item(dict(rows[0], type="cloud", debrid="cloud"))
    assert item.properties["from"] == "Premiumize cloud" and item.properties["status_colour"] == "FFDFFAF6"
    assert item.properties["badge_bg"] == "FF2EC4B6"


def test_playing_next_card_matches_the_mock_up():
    from resources.lib import smartplay
    values = smartplay.card_values("The Harbour", {"name": "Tidewater", "runtime": 48}, 2, 5, "")
    assert values["heading"] == "Up next" and values["episode"] == "Tidewater \u00b7 S2 \u00b7 E5 \u00b7 48 min"
    assert smartplay.card_status(True, {"quality": "1080p", "debrid": "cached"}) == \
        {"status": "Source ready: 1080p, cached", "status_colour": "FF2EC4B6"}
    assert smartplay.card_status(False, None)["status"] == "Finding a source\u2026"
    assert smartplay.countdown(12, 30) == {"ring": "spongetv-ring-16.png", "seconds": "12"}
    assert smartplay.countdown(30, 30)["ring"] == "spongetv-ring-40.png"
    assert smartplay.countdown(0, 30) == {"ring": "spongetv-ring-00.png", "seconds": "0"}


def test_picking_a_source_premiumize_hasnt_cached(premiumize, monkeypatch):
    """You're told it isn't cached, and the next ready source below it plays; with none ready below,
    you're told so and stay in Source Select."""
    from conftest import FakeDialog
    from resources.lib import windows
    app = context.App()
    target = playback.Target(app, {"media": "movie", "tmdb_id": 603})
    sources = [{"release_title": "A", "quality": "4K", "debrid": "uncached", "type": "torrent", "hash": "a"},
               {"release_title": "B", "quality": "4K", "debrid": "cached", "type": "torrent", "hash": "b"},
               {"release_title": "C", "quality": "4K", "debrid": "uncached", "type": "torrent", "hash": "c"}]
    picks = [sources[2], sources[0]]

    class FakeChooser:
        def __init__(self, *args):
            pass

        def visible(self):
            return sources
    monkeypatch.setattr(windows, "Chooser", FakeChooser)
    monkeypatch.setattr(windows, "choose_source", lambda chooser: picks.pop(0))
    monkeypatch.setattr(playback, "mode_for", lambda media: playback.SOURCE_SELECT)
    monkeypatch.setattr(playback, "resolve_link", lambda app, target, source: f"https://dl/{source['hash']}")
    FakeDialog.shown.clear()
    source, link = playback.pick_and_resolve(app, target, (None, "Film", "", "", "", sources, None))
    assert link == "https://dl/b"
    assert [m for kind, m in FakeDialog.shown if kind == "notification"] == [
        "Not cached on Premiumize, and none below it is ready. Choose another.",
        "Not cached on Premiumize: playing the next ready source"]


class FakeTrakt:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def scrobble(self, action, body):
        if self.fail:
            raise RuntimeError("Trakt said no")
        self.sent.append((action, body.get("progress")))


def follow_film(monkeypatch, script, trakt):
    import xbmc
    app = context.App()
    monkeypatch.setattr(context.App, "signed_in", property(lambda self: True))
    monkeypatch.setattr(context.App, "trakt", property(lambda self: trakt))
    app.library.add("playback", "movie", 7, value=32.0, at="2026-11-01T00:00:00.000Z")   # Trakt's old resume point
    xbmc.Player.script = script
    follower = playback.Follower(app, playback.Target(app, {"media": "movie", "tmdb_id": 7}), "plugin://x")
    follower.follow()
    return app, follower


def test_watching_a_film_to_the_end_marks_it_watched_straight_away(premiumize, monkeypatch):
    trakt = FakeTrakt()
    app, follower = follow_film(monkeypatch, [(1930, 6000), (5990, 6000)], trakt)
    assert follower.watched and trakt.sent[-1][0] == "stop"
    assert app.library.movie_plays(7) == 1                     # the tick shows without waiting for a sync
    assert app.library.progress("movie", 7)[0] in (0, None)    # and Trakt's old resume point has gone
    assert app.store.cache_get("resume:movie:7") is None


def test_stopping_part_way_keeps_it_unwatched(premiumize, monkeypatch):
    app, follower = follow_film(monkeypatch, [(100, 6000), (3000, 6000)], FakeTrakt())
    assert not follower.watched and app.library.movie_plays(7) == 0
    assert app.store.cache_get("resume:movie:7")["position"] == 3000


def test_past_80_percent_counts_as_watched_like_trakt(premiumize, monkeypatch):
    app, follower = follow_film(monkeypatch, [(100, 6000), (4900, 6000)], FakeTrakt())   # 82%
    assert follower.watched and app.library.movie_plays(7) == 1
    assert app.store.cache_get("resume:movie:7") is None


def test_not_marked_here_if_trakt_refused_the_scrobble(premiumize, monkeypatch):
    app, follower = follow_film(monkeypatch, [(100, 6000), (5990, 6000)], FakeTrakt(fail=True))
    assert follower.watched and app.library.movie_plays(7) == 0   # the next sync decides


def test_list_reloads_after_something_was_watched(premiumize, monkeypatch):
    import xbmc
    monkeypatch.setattr(xbmc, "getInfoLabel",
                        lambda label: "plugin://plugin.video.spongetv/?action=movies" if label == "Container.FolderPath"
                        else "", raising=False)
    playback.refresh_when_back(xbmc.Monitor(), wait=1)
    assert "Container.Refresh" in Directory.builtins
    Directory.builtins.clear()
    monkeypatch.setattr(xbmc, "getInfoLabel", lambda label: "videodb://movies/", raising=False)
    playback.refresh_when_back(xbmc.Monitor(), wait=1)
    assert "Container.Refresh" not in Directory.builtins      # not SpongeTV's list: leave it alone
