# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Release 2, stage 2: the caching assistant."""

import pytest

import xbmc
from conftest import FakeAddon, FakeDialog, FakeProgress
from resources.lib import caching, context, playback
from resources.lib.http import Response
from resources.lib.premiumize import Premiumize
from test_premiumize import FakePm

SOURCE = {"type": "torrent", "hash": "abc123", "release_title": "Film.2024.1080p", "debrid": "uncached",
          "quality": "1080p"}


class DownloadingPm(FakePm):
    """Premiumize with a cloud and transfers that move on as a test says."""

    def __init__(self):
        super().__init__()
        self.root = []
        self.made = []
        self.list = {}          # transfer ID -> transfer
        self.next_id = 0

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        path = url.rsplit("/api/", 1)[-1]
        ok = {"status": "success"}
        if path == "folder/list":
            self.calls.append((method, path, params))
            return Response(200, dict(ok, name="", content=self.root), {})
        if path == "folder/create":
            self.calls.append((method, path, form))
            self.made.append(form["name"])
            self.root.append({"id": "spongetv-folder", "name": form["name"], "type": "folder"})
            return Response(200, dict(ok, id="spongetv-folder"), {})
        if path == "transfer/create":
            self.calls.append((method, path, form))
            if form.get("folder_id") == "deleted-folder":
                # as Premiumize answered on the Shield (19 November 2026); its error code isn't documented
                return Response(200, {"status": "error", "message": "target folder not found"}, {})
            self.next_id += 1
            tid = f"t{self.next_id}"
            self.list[tid] = {"id": tid, "name": "Film.2024.1080p", "status": "running", "progress": 0.0, "message": ""}
            return Response(200, dict(ok, id=tid, name="Film.2024.1080p"), {})
        if path == "transfer/list":
            return Response(200, dict(ok, transfers=list(self.list.values())), {})
        if path == "transfer/delete":
            self.calls.append((method, path, form))
            self.list.pop(form["id"], None)
            return Response(200, ok, {})
        return super().send(method, url, params, json_body, headers, max_wait, form)

    def move(self, tid, **fields):
        self.list[tid].update(fields)


@pytest.fixture
def pm(monkeypatch):
    fake = DownloadingPm()
    monkeypatch.setattr(context.App, "premiumize", property(lambda app: Premiumize(fake, "good", app.store)))
    FakeAddon.settings.update({"premiumize.api_key": "good", "premiumize.assist": True})
    return fake


def test_offered_only_for_uncached_torrents_with_the_setting_on(pm):
    assert caching.offered(SOURCE)
    assert not caching.offered(dict(SOURCE, debrid="cached"))
    assert not caching.offered({"type": "hoster", "url": "https://x", "debrid": "uncached"})
    FakeAddon.settings["premiumize.assist"] = False
    assert not caching.offered(SOURCE)


def test_the_spongetv_folder_is_made_once_and_remembered(pm):
    app = context.App()
    assert caching.folder_id(app) == "spongetv-folder"
    assert caching.folder_id(app) == "spongetv-folder"
    assert pm.made == ["SpongeTV"]
    assert len([c for c in pm.calls if c[1] == "folder/list"]) == 1
    # one already there (made earlier, or by hand) is used, not a second
    pm2 = DownloadingPm()
    pm2.root = [{"id": "mine", "name": "SpongeTV", "type": "folder"}]
    app.store.cache_delete("premiumize:spongetv_folder")
    app2 = context.App()
    type(app2).premiumize = property(lambda a: Premiumize(pm2, "good", a.store))
    assert caching.folder_id(app2) == "mine" and pm2.made == []


def test_a_deleted_folder_is_made_again(pm):
    app = context.App()
    app.store.cache_set("premiumize:spongetv_folder", "deleted-folder", 3600)
    caching.start(app, SOURCE, "Film (2024)", "background")
    assert pm.made == ["SpongeTV"]
    assert [d["title"] for d in app.store.downloads()] == ["Film (2024)"]


def test_wait_plays_when_premiumize_has_it(pm, monkeypatch):
    ticks = []

    class Monitor:
        def waitForAbort(self, seconds):
            ticks.append(seconds)
            pm.move("t1", progress=0.5 * len(ticks))
            if len(ticks) == 2:
                pm.move("t1", status="finished", progress=1.0)
            return False
    monkeypatch.setattr(caching.xbmc, "Monitor", Monitor)
    app = context.App()
    link = caching.wait(app, SOURCE, "Film (2024)", lambda source: "https://dl/film")
    assert link == "https://dl/film"
    assert ticks == [caching.WAIT_CHECK_EVERY] * 2
    sent = [c for c in pm.calls if c[1] == "transfer/create"][0][2]
    assert sent == {"src": "magnet:?xt=urn:btih:abc123", "folder_id": "spongetv-folder"}
    assert app.store.downloads() == []


def test_cancelling_the_wait_deletes_the_transfer(pm, monkeypatch):
    monkeypatch.setattr(caching.xbmc, "Monitor", lambda: type("M", (), {"waitForAbort": lambda self, s: False})())
    FakeProgress.cancel_after = 1
    try:
        assert caching.wait(context.App(), SOURCE, "Film (2024)", lambda s: "x") is None
    finally:
        FakeProgress.cancel_after = None
    assert ("POST", "transfer/delete", {"id": "t1"}) in pm.calls
    assert context.App().store.downloads() == []


def test_a_failed_wait_says_so(pm, monkeypatch):
    def fail(self, seconds):
        pm.move("t1", status="error", message="Not enough seeders")
        return False
    monkeypatch.setattr(caching.xbmc, "Monitor", lambda: type("M", (), {"waitForAbort": fail})())
    assert caching.wait(context.App(), SOURCE, "Film (2024)", lambda s: "x") is None
    assert ("ok", "Premiumize couldn't download Film (2024)") in [(k, m) for k, m in FakeDialog.shown]
    assert context.App().store.downloads() == []


def test_other_refusals_still_explained_after_one_retry(pm, monkeypatch):
    app = context.App()
    real = pm.send

    def refuse(method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        if url.endswith("transfer/create"):
            pm.calls.append((method, "transfer/create", form))
            return Response(200, {"status": "error", "message": "Limit", "code": "account_limit_reached"}, {})
        return real(method, url, params, json_body, headers, max_wait, form)
    pm.send = refuse
    assert not caching.background(app, SOURCE, "Film (2024)")
    assert len([c for c in pm.calls if c[1] == "transfer/create"]) == 2
    assert ("ok", "Premiumize says your fair-use points or download slots have run out.") in \
        [(k, m) for k, m in FakeDialog.shown]
    assert app.store.downloads() == []


def test_kodi_closing_while_waiting_carries_on_in_the_background(pm):
    # the test Monitor reports Kodi closing straight away
    assert caching.wait(context.App(), SOURCE, "Film (2024)", lambda s: "x") is None
    assert [d["mode"] for d in context.App().store.downloads()] == ["background"]
    assert "t1" in pm.list


def test_background_downloads_are_followed_until_ready(pm):
    app = context.App()
    assert caching.background(app, SOURCE, "Film (2024)")
    assert ("notification", "Premiumize is downloading Film (2024). SpongeTV will tell you when it's ready.") \
        in FakeDialog.shown
    caching.follow(app, now=10 ** 9)
    assert len(app.store.downloads()) == 1                 # still going: nothing said
    pm.move("t1", status="seeding", progress=1.0)
    caching.follow(app, now=10 ** 9 + 60)
    assert ("notification", "Ready to play: Film (2024)") in FakeDialog.shown
    assert app.store.downloads() == []
    assert "t1" in pm.list                                 # the transfer itself is left for Transfers


def test_stuck_failed_and_gone_downloads(pm):
    app = context.App()
    start = app.store.clock()
    for title in ("Stuck", "Failed", "Gone"):
        caching.start(app, SOURCE, title, "background")
    pm.move("t1", progress=0.2)
    caching.follow(app, now=start + 10)                    # progress noted
    pm.move("t2", status="error", message="Dead torrent")
    del pm.list["t3"]                                      # deleted in Transfers
    caching.follow(app, now=start + 10 + caching.STUCK_AFTER)
    shown = [m for k, m in FakeDialog.shown if k == "notification"]
    assert "Premiumize's download of Stuck stopped making progress, so it was cancelled" in shown
    assert "Premiumize couldn't download Failed" in shown
    assert not any("Gone" in m for m in shown)
    assert app.store.downloads() == []
    assert "t1" not in pm.list and "t2" not in pm.list     # given up: deleted on Premiumize too


def test_a_wait_whose_window_has_gone_becomes_a_background_download(pm):
    app = context.App()
    caching.start(app, SOURCE, "Film (2024)", "wait")
    started = app.store.downloads()[0]["checked"]
    caching.follow(app, now=started + 30)
    assert app.store.downloads()[0]["mode"] == "wait"      # its window is still checking
    pm.move("t1", status="finished", progress=1.0)
    caching.follow(app, now=started + 30)
    assert app.store.downloads()                           # the window reports it, not the service
    caching.follow(app, now=started + caching.ORPHANED_AFTER + 1)
    assert app.store.downloads() == []
    assert ("notification", "Ready to play: Film (2024)") in FakeDialog.shown


class Chooser:
    def __init__(self, *args):
        self.all = [SOURCE, dict(SOURCE, hash="ready", debrid="cached", release_title="Ready.One")]

    def visible(self):
        return self.all


def _found():
    return ({}, "Film (2024)", {}, "", "", [SOURCE], lambda: None)


def test_source_select_offers_the_assistant(pm, monkeypatch):
    monkeypatch.setattr(playback.windows, "Chooser", Chooser)
    picks = [SOURCE]
    monkeypatch.setattr(playback.windows, "choose_source", lambda chooser: picks.pop(0) if picks else None)
    target = type("T", (), {"media": "movie"})()
    FakeDialog.script = [caching.BACKGROUND]
    assert playback.pick_and_resolve(context.App(), target, _found()) == (None, None)
    assert [d["title"] for d in context.App().store.downloads()] == ["Film (2024)"]
    # Cancel goes back to Source Select (here: nothing more picked)
    picks[:] = [SOURCE]
    FakeDialog.script = [caching.CANCEL]
    assert playback.pick_and_resolve(context.App(), target, _found()) == (None, None)
    assert len(context.App().store.downloads()) == 1
    # with the assistant off, the old way: on to the next ready source
    FakeAddon.settings["premiumize.assist"] = False
    picks[:] = [SOURCE]
    monkeypatch.setattr(playback, "resolve_first", lambda app, target, sources, attempts, progress=None:
                        (sources[1], "https://dl/ready"))
    assert playback.pick_and_resolve(context.App(), target, _found())[1] == "https://dl/ready"
    assert any("playing the next ready source" in m for k, m in FakeDialog.shown if k == "notification")


def test_nothing_ready_offers_the_best_uncached_torrent(pm, monkeypatch):
    from resources.lib import choose, ranking
    worse = dict(SOURCE, hash="worse", release_title="Film.2024.720p", quality="720p", size_mb=900)
    better = dict(SOURCE, hash="better", release_title="Film.2024.1080p", quality="1080p", size_mb=4000)
    cam = dict(SOURCE, hash="cam", release_title="Film.2024.CAM", quality="CAM", size_mb=700)
    unchecked = {"type": "hosters", "url": "https://h/x", "release_title": "Hoster", "quality": "1080p"}
    FakeAddon.settings.update({"filter.preset": 0, "filter.allow_1080p": True, "filter.allow_720p": True,
                               "filter.exclude_cam": True, "sources.hide_uncached": True})
    rules = choose.filter_rules()[1]                                   # "hide not cached" on, CAM excluded
    sort = ranking.load_rules(context.App().store)
    assert caching.best_offer([worse, better, unchecked], rules, sort, "movie")["hash"] == "better"
    assert caching.best_offer([worse, dict(better, debrid="cached")], rules, sort, "movie") is None   # one is ready
    FakeAddon.settings["premiumize.assist"] = False
    assert caching.best_offer([worse, better], rules, sort, "movie") is None
    FakeAddon.settings["premiumize.assist"] = True
    # in pick_and_resolve: asked before Source Select, with its own heading
    monkeypatch.setattr(playback.windows, "Chooser", Chooser)
    monkeypatch.setattr(playback.windows, "choose_source", lambda chooser: None)
    target = type("T", (), {"media": "movie"})()
    found = ({}, "Film (2024)", {}, "", "", [worse, better, cam], lambda: None)
    FakeDialog.script = [caching.BACKGROUND]
    assert playback.pick_and_resolve(context.App(), target, found) == (None, None)
    assert [d["release"] for d in context.App().store.downloads()] == ["Film.2024.1080p"]
    # Cancel carries on to Source Select as before
    FakeDialog.script = [caching.CANCEL]
    opened = []
    monkeypatch.setattr(playback.windows, "choose_source", lambda chooser: opened.append(1))
    playback.pick_and_resolve(context.App(), target, found)
    assert opened == [1]


def test_details_line_puts_pack_and_seeds_first():
    from resources.lib import windows
    source = {"type": "torrent", "pack": "season", "seeds": 42, "tags": ["HDR", "HEVC", "Atmos"]}
    assert windows.details_line(source) == "Season pack · 42 seeds · HDR · HEVC · Atmos"
