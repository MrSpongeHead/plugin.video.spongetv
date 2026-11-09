# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Stage 3: provider packages, the source search, filtering and sorting, and the play flow."""

import hashlib
import io
import json
import os
import zipfile

import pytest

from conftest import ROOT, Directory, FakeAddon, FakeDialog
from resources.lib import choose, context, providers_menu, ranking, router, windows
from resources.lib.database import Store
from resources.lib.http import Response
from resources.lib.packages import Package, PackageError, Packages, version_tuple
from resources.lib.sources import (EarlyStop, Search, episode_request, movie_request, normalise, quality_of,
                                   request_key, tags_of)
from test_menus import FakeTmdb, call  # noqa: F401  (fixtures below reuse the fake TMDB)

TEST_PACKAGE = os.path.join(ROOT, "resources", "test_provider", "SpongeTVTest")
TEMPLATE = "/mnt/user-data/attachments/897bceda-c72b-50ef-8ed7-c6d955fa3203/65a58153-MrSpongeHeadScrapers-1.0.0-demo.zip"


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    yield s
    s.close()


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def test_package(name="Demo", version="1.0.0", extra=None, **meta):
    files = {f"{name}/meta.json": json.dumps({"name": name, "author": "me", "version": version, **meta}),
             f"{name}/providers/{name}/__init__.py": "",
             f"{name}/providers/{name}/en/__init__.py": "def get_torrent():\n    return ['one']\n"
                                                         "def get_hosters():\n    return []\n",
             f"{name}/providers/{name}/en/torrent/__init__.py": "",
             f"{name}/providers/{name}/en/torrent/one.py":
                 f"class sources:\n    def movie(self, title, year, imdb=None, **kw):\n"
                 f"        return [{{'hash': 'ab' * 20, 'release_title': title + '.{version}.1080p.WEB', 'size': 2000}}]\n"}
    files.update(extra or {})
    return make_zip(files)


test_package.__test__ = False   # a helper, not a test


# -- packages -------------------------------------------------------------------------------------
def test_version_tuple():
    assert version_tuple("1.10.0") > version_tuple("1.9.9")
    assert version_tuple("2") == (2,)


def test_install_the_test_provider_finds_its_providers(store, tmp_path):
    manager = Packages(store, str(tmp_path))
    package = manager.install(providers_menu.zip_folder(TEST_PACKAGE))
    assert package.name == "SpongeTVTest"
    names = sorted(p["name"] for p in manager.providers("SpongeTVTest"))
    assert names == ["broken", "sample", "slow", "testvideo"]
    enabled = {p["name"]: p["enabled"] for p in manager.providers()}
    assert enabled == {"broken": 1, "sample": 1, "slow": 1, "testvideo": 0}    # the test video starts off
    assert manager.settings("SpongeTVTest")[0]["id"] == "example"


@pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="the user's template zip isn't attached here")
def test_install_the_real_template(store, tmp_path):
    manager = Packages(store, str(tmp_path))
    with open(TEMPLATE, "rb") as handle:
        manager.install(handle.read())
    assert len(manager.providers()) >= 10


@pytest.mark.parametrize("files, kind", [
    ({"Demo/../evil.py": ""}, "unsafe_path"),
    ({"/abs/meta.json": "{}"}, "unsafe_path"),
    ({"readme.txt": "hi"}, "no_meta"),
    ({"Demo/meta.json": json.dumps({"name": "Demo"})}, "bad_meta"),
    ({"Demo/meta.json": json.dumps({"name": "bad-name", "author": "a", "version": "1"})}, "bad_name"),
    ({"Demo/meta.json": json.dumps({"name": "Demo", "author": "a", "version": "1"})}, "no_providers"),
])
def test_unsafe_or_broken_packages_are_refused(files, kind):
    with pytest.raises(PackageError) as error:
        Package(make_zip(files))
    assert error.value.kind == kind


def test_not_a_zip_is_refused():
    with pytest.raises(PackageError) as error:
        Package(b"this is not a zip")
    assert error.value.kind == "not_a_zip"


def test_saying_no_installs_nothing(store, tmp_path):
    manager = Packages(store, str(tmp_path))
    assert manager.install(test_package(), confirm=lambda p: False) is None
    assert manager.installed() == []


def test_update_keeps_provider_switches_and_can_roll_back(store, tmp_path):
    manager = Packages(store, str(tmp_path))
    manager.install(test_package(version="1.0.0"))
    manager.set_enabled("Demo", False, "torrent", "one")
    manager.install(test_package(version="1.1.0"))
    assert manager.get("Demo")["version"] == "1.1.0"
    assert manager.providers("Demo")[0]["enabled"] == 0
    assert manager.can_roll_back("Demo")
    assert manager.roll_back("Demo") == "1.0.0"
    assert manager.get("Demo")["version"] == "1.0.0"
    assert manager.can_roll_back("Demo")       # and you can go forward again
    assert manager.roll_back("Demo") == "1.1.0"


def test_uninstall_removes_everything(store, tmp_path):
    manager = Packages(store, str(tmp_path))
    manager.install(test_package())
    manager.uninstall("Demo")
    assert manager.installed() == [] and manager.providers() == []
    assert not os.path.exists(tmp_path / "providers" / "Demo")


class FakeHttp:
    def __init__(self, files):
        self.files = files

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None):
        if url in self.files:
            body = self.files[url]
            return Response(200, None, {}, body if isinstance(body, bytes) else body.encode())
        return Response(404, None, {}, b"")


def test_download_checks_a_published_checksum(store, tmp_path):
    data = test_package()
    good = FakeHttp({"https://x/demo.zip": data, "https://x/demo.zip.sha256": hashlib.sha256(data).hexdigest()})
    assert Packages(store, str(tmp_path), good).download("https://x/demo.zip") == (data, True)
    unchecked = FakeHttp({"https://x/demo.zip": data})
    assert Packages(store, str(tmp_path), unchecked).download("https://x/demo.zip") == (data, False)
    bad = FakeHttp({"https://x/demo.zip": data, "https://x/demo.zip.sha256": "0" * 64})
    with pytest.raises(PackageError) as error:
        Packages(store, str(tmp_path), bad).download("https://x/demo.zip")
    assert error.value.kind == "checksum"


def test_updates_are_found_and_installed(store, tmp_path):
    http = FakeHttp({"https://x/meta.json": json.dumps({"name": "Demo", "author": "me", "version": "1.2.0"}),
                     "https://x/zips/Demo-1.2.0.zip": test_package(version="1.2.0")})
    manager = Packages(store, str(tmp_path), http)
    manager.install(test_package(remote_meta="https://x/meta.json", update_directory="https://x/zips/"))
    updates = manager.available_updates()
    assert [(p["name"], r["version"]) for p, r in updates] == [("Demo", "1.2.0")]
    manager.update(*updates[0])
    assert manager.get("Demo")["version"] == "1.2.0"
    assert manager.available_updates() == []


def test_package_settings(store, tmp_path):
    manager = Packages(store, str(tmp_path))
    manager.install(providers_menu.zip_folder(TEST_PACKAGE))
    manager.set_setting("SpongeTVTest", "example", "False")
    assert manager.settings("SpongeTVTest")[0]["value"] == "False"


def test_spongetv_never_has_modules_packages_import_first():
    """Provider packages try resources.lib.common and resources.lib.modules (Seren's) before their own."""
    for name in ("common", "modules"):
        assert not os.path.exists(os.path.join(ROOT, "resources", "lib", name))
        assert not os.path.exists(os.path.join(ROOT, "resources", "lib", name + ".py"))


# -- reading release names --------------------------------------------------------------------------
@pytest.mark.parametrize("title, quality", [
    ("Film.2024.2160p.WEB-DL.HDR.HEVC", "4K"), ("Film 2024 1080p BluRay", "1080p"), ("Film.720p.x264", "720p"),
    ("Film.2024.HDCAM", "CAM"), ("Film.DVDRip", "SD"), ("Film.UHD.Remux", "4K"),
    ("Film.2024.1080p.HDCAM.x264", "CAM"), ("Film 2024 HDTS 720p", "CAM"), ("Film.2024.DVDSCR.XviD", "CAM"),
    ("Film.2024.1080p.HD-TS", "CAM"), ("Film.2024.HDTC.1080p", "CAM"), ("Film.2024.WEBSCR.720p", "CAM"),
    ("Film.2024.1080p.WEB-DL.DTS-HD.5.1", "1080p"), ("Shots.Fired.2024.1080p.WEB", "1080p"),
])
def test_quality_of(title, quality):
    assert quality_of(title) == quality


def test_tags_of():
    assert tags_of("Film.2160p.DV.HDR10.HEVC.Atmos.7.1") == ["Dolby Vision", "HDR", "HEVC", "Atmos", "7.1"]
    assert tags_of("Film.1080p.x264.DD5.1")[:1] == ["H.264"]


def test_normalise():
    provider = {"name": "p", "package": "P"}
    source = normalise({"magnet": "magnet:?xt=urn:btih:ABCDEF&dn=x", "release_title": "Film.1080p.HEVC", "size": "1500",
                        "seeds": "12", "package": "season"}, provider, "torrent")
    assert source["hash"] == "abcdef" and source["quality"] == "1080p" and source["size_mb"] == 1500.0
    assert source["seeds"] == 12 and source["pack"] == "season" and "HEVC" in source["tags"]
    assert normalise({"release_title": "no hash"}, provider, "torrent") is None
    assert normalise({"release_title": "no url"}, provider, "direct") is None
    assert normalise({"url": "https://x", "quality": "720p", "release_title": "x"}, provider, "direct")["quality"] == "720p"


def test_requests_are_built_like_serens():
    movie = movie_request({"id": 5, "title": "Mr. Film", "original_title": "Monsieur Film", "release_date": "2024-02-01",
                           "imdb_id": "tt1", "production_countries": [{"iso_3166_1": "GB"}]})
    assert movie["simple_info"] == {"title": "Mr. Film", "year": "2024", "aliases": ["Monsieur Film", "Mr Film"],
                                    "country": "gb"}
    assert request_key(movie) == "sources:movie:5"
    show = {"id": 7, "name": "Show", "first_air_date": "2020-01-01", "origin_country": ["US"],
            "seasons": [{"season_number": 0, "episode_count": 3}, {"season_number": 1, "episode_count": 10},
                        {"season_number": 2, "episode_count": 8}], "external_ids": {"imdb_id": "tt7", "tvdb_id": 70}}
    episode = episode_request(show, {"season_number": 2, "episode_number": 3, "name": "Three"})
    simple = episode["simple_info"]
    assert (simple["season_number"], simple["episode_number"], simple["absolute_number"]) == ("2", "3", "13")
    assert simple["no_seasons"] == "2" and simple["no_episodes"] == "18"
    assert request_key(episode) == "sources:episode:7:2:3"


# -- the search ---------------------------------------------------------------------------------------
PROVIDERS = [{"package": "P", "language": "en", "kind": "torrent", "name": n} for n in ("a", "b", "bad", "slow")]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def fake_call(results, hang=()):
    import threading
    gate = threading.Event()

    def call(provider, request, host_lists):
        if provider["name"] == "bad":
            raise ValueError("provider bug")
        if provider["name"] in hang:
            gate.wait(5)
            return [{"hash": "ff" * 20, "release_title": "late.2160p"}]
        return results.get(provider["name"], [])
    call.gate = gate
    return call


def run(search, clock=None, steps=200):
    import time
    for _ in range(steps):
        status = search.status()
        if status["finished"]:
            return status
        if clock:
            clock.now += 1
        time.sleep(0.01)
    return search.status()


def test_search_collects_and_survives_a_broken_provider():
    results = {"a": [{"hash": "aa" * 20, "release_title": "F.1080p", "seeds": 5}],
               "b": [{"hash": "AA" * 20, "release_title": "F.1080p", "seeds": 9},
                     {"hash": "bb" * 20, "release_title": "F.720p"}]}
    recorded = []
    search = Search(PROVIDERS[:3], {"media": "movie"}, call=fake_call(results),
                    record=lambda p, s, c: recorded.append((p["name"], s, c))).start()
    status = run(search)
    assert status["found"] == 2                     # the same hash from two providers counts once
    assert max(s["seeds"] for s in search.results()) == 9   # keeping the better-seeded copy
    assert search.statuses["P/torrent/bad"] == "failed"
    assert sorted(recorded) == [("a", "found", 1), ("b", "found", 2), ("bad", "failed", 0)]


def test_search_times_out_slow_providers():
    clock = Clock()
    call = fake_call({"a": [{"hash": "aa" * 20, "release_title": "F.1080p"}]}, hang=("slow",))
    search = Search([PROVIDERS[0], PROVIDERS[3]], {"media": "movie"}, timeout=5, call=call, clock=clock).start()
    status = run(search, clock)
    call.gate.set()
    assert status["finished"] and search.statuses["P/torrent/slow"] == "timed out"
    assert status["found"] == 1


def test_early_stop():
    call = fake_call({"a": [{"hash": f"{i:040x}", "release_title": "F.1080p"} for i in range(3)],
                      "b": [{"hash": f"{i + 9:040x}", "release_title": "F.4K"} for i in range(2)]}, hang=("slow",))
    search = Search([PROVIDERS[0], PROVIDERS[1], PROVIDERS[3]], {"media": "movie"}, call=call,
                    early_stop=EarlyStop(True, "1080p", 5)).start()
    status = run(search)
    call.gate.set()
    assert status["finished"] and status["stopped_early"]
    assert search.statuses["P/torrent/slow"] == "stopped"
    assert EarlyStop(True, "1080p", 5).progress([{"quality": "720p"}]) == 0


def test_choose_now_stops_waiting():
    call = fake_call({"a": [{"hash": "aa" * 20, "release_title": "F.1080p"}]}, hang=("slow",))
    search = Search([PROVIDERS[0], PROVIDERS[3]], {"media": "movie"}, call=call).start()
    run(search, steps=20)
    search.stop_now()
    call.gate.set()
    assert search.status()["finished"] and len(search.results()) == 1


# -- filtering and sorting --------------------------------------------------------------------------
def src(title, size=1000, seeds=0, debrid="", kind="torrent"):
    s = normalise({"hash": hashlib.sha1(title.encode()).hexdigest(), "url": "https://x/" + title,
                   "release_title": title, "size": size, "seeds": seeds}, {"name": "p", "package": "P"}, kind)
    s["debrid"] = debrid
    return s


def test_presets_filter():
    sources = [src("A.2160p.HDR"), src("B.2160p"), src("C.1080p"), src("D.720p", 900), src("E.HDCAM"), src("F.1080p.3D"),
               src("G.1080p", 6000)]
    names = lambda rules, media="movie": [s["release_title"][0] for s in ranking.apply_filter(sources, rules, media)]  # noqa
    assert names(ranking.PRESETS[ranking.PRESET_4K_HDR]) == ["A"]
    assert names(ranking.PRESETS[ranking.PRESET_1080P]) == ["C", "G"]
    assert names(ranking.PRESETS[ranking.PRESET_DATA_SAVER]) == ["C", "D"]
    assert names(ranking.PRESETS[ranking.PRESET_DATA_SAVER], "episode") == ["C", "D"]
    assert len(names(ranking.PRESETS[ranking.PRESET_EVERYTHING])) == 7


def test_custom_filter_reads_settings():
    values = {"filter.allow_4k": False, "filter.allow_1080p": True, "filter.allow_720p": True, "filter.allow_sd": False,
              "filter.exclude_cam": True, "filter.exclude_hevc": True, "filter.max_gb_movie": 5}
    rules = ranking.custom_filter((lambda k: values.get(k, False), lambda k: values.get(k, 0)))
    assert rules["qualities"] == {"1080p", "720p"} and "HEVC" in rules["exclude"] and rules["max_gb_movie"] == 5


def test_sort_rules_order_and_reason(store):
    a, b, c = src("A.1080p", 4000, 10, "cached"), src("B.2160p", 9000, 50), src("C.1080p", 8000, 99, "cached")
    rules = ranking.load_rules(store)
    ordered = ranking.sort_sources([a, b, c], rules)
    assert [s["release_title"][0] for s in ordered] == ["C", "A", "B"]   # ready first, then larger
    assert ranking.deciding_rule(ordered[1], ordered[0], rules) == "size_large"
    ranking.save_rules(store, [("quality", True), ("ready", True)])
    assert ranking.load_rules(store)[:2] == [("quality", True), ("ready", True)]
    assert len(ranking.load_rules(store)) == len(ranking.RULES)   # rules missing from the saved list come back, off
    assert [s["release_title"][0] for s in ranking.sort_sources([a, b, c], ranking.load_rules(store))] == ["B", "A", "C"]  # A and C tie: found order
    ranking.reset_rules(store)
    assert ranking.load_rules(store) == ranking.DEFAULT_RULES


def test_sort_rule_editor_moves_and_switches(store):
    # pick rule 2 (quality), move it up; pick the new rule 2 (ready), switch it off; then close
    FakeDialog.script = [1, 0, 1, 2, -1]
    assert choose.edit_sort_rules(store)
    rules = ranking.load_rules(store)
    assert rules[0] == ("quality", True) and rules[1] == ("ready", False)


def test_size_text():
    assert ranking.size_text(512) == "512 MB"
    assert ranking.size_text(2048) == "2.0 GB"
    assert ranking.size_text(0) == ""


# -- windows (the simple versions; the skin windows are checked in Kodi) ------------------------------
def test_search_properties():
    status = {"elapsed": 65, "total": 4, "done": 1, "counts": {"4K": 1, "1080p": 2, "720p": 0, "Other": 3}, "found": 6,
              "early": (3, 5), "searching": ["a", "b"], "finished": False}
    lines, percent = windows.search_properties(status, "Film", EarlyStop(True, "1080p", 5))
    assert percent == 25 and lines["elapsed"] == "1:05" and lines["can_choose"] == "1"
    assert lines["early_line"] == "Stop early: 3 of 5 1080p sources found"
    assert lines["choose_label"] == "Choose from 6" and lines["searching_line"] == "Still searching: a, b"
    status = dict(status, choosable=1)              # your filter hides 5 of the 6
    lines, _ = windows.search_properties(status, "Film", EarlyStop(True, "1080p", 5))
    assert lines["choose_label"] == "Choose from 1"
    assert lines["providers_line"] == "1 of 4 providers finished · 5 hidden by your filter"
    status = dict(status, choosable=0)
    lines, _ = windows.search_properties(status, "Film", EarlyStop(True, "1080p", 5))
    assert lines["choose_label"] == "Waiting for sources…" and lines["can_choose"] == ""


def test_status_words():
    assert windows.status_of(src("A", debrid="cached")) == ("Ready", "cached")
    assert windows.status_of(src("A")) == ("Not checked", "unchecked")
    assert windows.status_of(src("A", kind="direct")) == ("Direct", "cached")
    item = windows.list_item(src("Film.2160p.HDR", 9000, 4))
    assert item.properties["quality"] == "4K" and item.properties["size"] == "8.8 GB"
    assert item.label2 == "HDR · 4 seeds"


def test_why_explains_the_position(store):
    sources = [src("A.1080p", 4000), src("B.1080p", 3000)]
    chooser = windows.Chooser(sources, "movie", "Film", "", "", "", lambda: ("Everything",
                              ranking.PRESETS[ranking.PRESET_EVERYTHING]), lambda: ranking.load_rules(store), {})
    shown = chooser.visible()
    text = chooser.why(shown, 1)
    assert "number 2 of 2" in text and "Larger files first" in text and "Filter in use: Everything" in text


# -- the play flow, end to end with the test provider -------------------------------------------------
@pytest.fixture
def with_test_provider(tmdb, monkeypatch):
    s = context.App().store
    s.set_meta("wizard_done", "1")
    from resources.lib import kodi
    manager = Packages(s, kodi.PROFILE)
    manager.install(providers_menu.zip_folder(TEST_PACKAGE))
    manager.set_enabled("SpongeTVTest", False, "torrent", "slow")
    s.close()
    FakeAddon.settings.update({"sources.timeout": 10, "sources.cache_hours": 3, "filter.preset": ranking.PRESET_EVERYTHING})

    class Running:   # the stand-in Monitor says Kodi is closing; the search needs one that keeps going
        def abortRequested(self):
            return False

        def waitForAbort(self, seconds=0):
            import time
            time.sleep(min(seconds, 0.05))
            return False
    monkeypatch.setattr(windows.xbmc, "Monitor", Running)
    return tmdb


@pytest.fixture
def tmdb(monkeypatch):
    from resources.lib.http import Http
    fake = FakeTmdb()
    monkeypatch.setattr(Http, "get_json", lambda self, url, params=None, headers=None: fake(self, url, params, headers))
    monkeypatch.setattr(context, "builtin_keys", lambda: {})
    FakeAddon.settings.update({"artwork.preset": 1, "tmdb.api_key": "good"})
    return fake


def test_play_searches_then_offers_sources(with_test_provider):
    FakeDialog.script = [1]    # the first source (row 0 is "Filter and sort")
    call("?action=play&media=movie&tmdb_id=7")
    assert Directory.resolved is False
    # without a Premiumize API key the torrent can't be played, and SpongeTV says how to fix that
    assert ("ok", "Sign in to Premiumize in Tools, Accounts, or in Settings, Accounts.") in FakeDialog.shown
    s = context.App().store
    saved = s.cache_get("sources:movie:7")
    assert saved and all(x["provider"] == "sample" for x in saved)
    providers = {p["name"]: p for p in Packages(s, "").providers("SpongeTVTest")}
    assert providers["sample"]["last_status"] == "found" and providers["broken"]["last_status"] == "failed"


def test_play_reuses_saved_results(with_test_provider, monkeypatch):
    call("?action=play&media=movie&tmdb_id=7")
    monkeypatch.setattr(choose, "Search", lambda *a, **k: pytest.fail("should reuse the saved results"))
    call("?action=play&media=movie&tmdb_id=7")
    call("?action=clear_results")
    assert context.App().store.cache_get("sources:movie:7") is None


def test_play_an_episode(with_test_provider):
    FakeDialog.script = [1]
    call("?action=play&media=episode&tmdb_id=50&season=1&episode=1")
    assert any("Sign in to Premiumize" in m for kind, m in FakeDialog.shown if kind == "ok")


def test_providers_menu_lists_packages(with_test_provider):
    call("?action=tools_providers")
    assert "Install the SpongeTV test provider" in [i[1].label for i in Directory.items]
    call("?action=packages")
    labels = [i[1].label for i in Directory.items]
    assert labels[:2] == ["Turn every provider on", "Turn every provider off"]
    assert labels[2] == "SpongeTVTest 1.1.0  (2 of 4 on)"
    call("?action=package&name=SpongeTVTest")
    labels = [i[1].label for i in Directory.items]
    assert any(label.startswith("[Off]  slow") for label in labels)
    assert "Package settings" in labels and "Uninstall" in labels


def test_window_tests_appear_only_for_developers(with_test_provider):
    call("?action=tools")
    assert not any("Window test" in i[1].label for i in Directory.items)
    FakeAddon.settings["developer.window_tests"] = True
    call("?action=tools")
    assert sum("Window test" in i[1].label for i in Directory.items) == 5
    FakeDialog.script = [-1]
    call("?action=window_test&window=select")    # falls back to the simple dialog in tests, and closes


def test_every_router_action_has_a_handler():
    assert all(callable(h) for h in router.ACTIONS.values())
    assert router.NOT_DIRECTORIES <= set(router.ACTIONS)


def test_package_update_check(store, tmp_path, monkeypatch):
    from resources.lib import kodi, service
    monkeypatch.setattr(kodi, "PROFILE", str(tmp_path))
    http = FakeHttp({"https://x/meta.json": json.dumps({"name": "Demo", "author": "me", "version": "1.2.0"}),
                     "https://x/zips/Demo-1.2.0.zip": test_package(version="1.2.0")})
    Packages(store, str(tmp_path), http).install(test_package(remote_meta="https://x/meta.json",
                                                              update_directory="https://x/zips/"))
    assert service.check_packages(store, http, 10 ** 6, mode=service.UPDATES_OFF) == []
    assert service.check_packages(store, http, 10 ** 6, mode=service.UPDATES_TELL) == ["Demo 1.2.0"]
    assert service.check_packages(store, http, 10 ** 6 + 60, mode=service.UPDATES_INSTALL) == []   # once a day
    assert service.check_packages(store, http, 10 ** 6 + 90000, mode=service.UPDATES_INSTALL) == ["Demo 1.2.0"]
    assert Packages(store, str(tmp_path)).get("Demo")["version"] == "1.2.0"


def test_providers_import_one_at_a_time(store, tmp_path):
    """Many providers of one package starting together must not deadlock Python's imports."""
    import threading
    from resources.lib import sources
    manager = Packages(store, str(tmp_path))
    manager.install(providers_menu.zip_folder(TEST_PACKAGE))
    manager.ensure_import_path()
    errors = []
    providers = [p for p in manager.providers() if p["name"] in ("sample", "broken", "testvideo")] * 4

    def load(provider):
        try:
            sources.provider_module(provider)
        except Exception as error:   # noqa: BLE001 - any failure is the bug
            errors.append(error)
    threads = [threading.Thread(target=load, args=(p,)) for p in providers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert errors == []



def test_provider_label_doesnt_hide_a_cam():
    """A provider may label a cinema recording 1080p; the release name still says CAM."""
    source = normalise({"hash": "ab" * 20, "release_title": "Film.2024.1080p.HDCAM", "quality": "1080p"},
                       {"name": "p", "package": "P"}, "torrent")
    assert source["quality"] == "CAM"
    custom = ranking.custom_filter((lambda k: k != "filter.exclude_hevc", lambda k: 0))
    assert ranking.apply_filter([source], custom, "movie") == []



def test_early_stop_and_counts_use_only_what_your_filter_shows():
    import time
    results = {"a": [{"hash": f"{i:040x}", "release_title": "F.1080p.WEB", "size": 9000} for i in range(6)]}
    hide_cam = lambda sources: [s for s in sources if s["size_mb"] < 5000]  # noqa: E731  (a 5 GB size limit)
    call = fake_call(results, hang=("slow",))
    search = Search([PROVIDERS[0], PROVIDERS[3]], {"media": "movie"}, call=call, visible=hide_cam,
                    early_stop=EarlyStop(True, "1080p", 5)).start()
    for _ in range(30):
        status = search.status()
        time.sleep(0.01)
    call.gate.set()
    assert status["found"] == 6 and status["choosable"] == 0
    assert not status["stopped_early"]              # six copies your filter hides don't count towards it
