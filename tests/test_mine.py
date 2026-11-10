# SPDX-License-Identifier: GPL-3.0-or-later
"""Trakt menus, watched marks, Trakt actions, sign-in and the sync service, end to end."""

import json

import pytest

from conftest import Directory, FakeAddon, FakeDialog
from fake_trakt import FakeTrakt, token_json
from resources.lib import context, service, trakt as trakt_module
from resources.lib.http import Http
from test_menus import PAST, FUTURE, FakeTmdb, call, labels


def season(show_id, number, count, unaired_from=None):
    return {"episodes": [{"id": show_id * 100 + number * 10 + e, "name": f"Ep {e}", "season_number": number,
                          "episode_number": e, "air_date": FUTURE if unaired_from and e >= unaired_from else PAST}
                         for e in range(1, count + 1)]}


def tv(show_id, last=(2, 1), counts=(3, 2)):
    return {"id": show_id, "name": f"Show {show_id}", "first_air_date": PAST, "origin_country": ["GB"],
            "last_air_date": f"2026-0{show_id - 50}-01",
            "last_episode_to_air": {"season_number": last[0], "episode_number": last[1]},
            "seasons": [{"season_number": n + 1, "episode_count": c, "air_date": PAST} for n, c in enumerate(counts)],
            "credits": {"cast": [], "crew": []}}


def watched(show_id, pairs, day):
    return {"show": {"ids": {"tmdb": show_id}}, "seasons": [
        {"number": s, "episodes": [{"number": e, "plays": 1, "last_watched_at": f"2026-10-{day:02d}T20:00:00.000Z"}
                                   for (s2, e) in pairs if s2 == s]} for s in sorted({s for s, _ in pairs})]}


@pytest.fixture
def world(monkeypatch):
    tmdb, trakt = FakeTmdb(), FakeTrakt()
    monkeypatch.setattr(Http, "get_json", lambda self, url, params=None, headers=None: tmdb(self, url, params, headers))
    monkeypatch.setattr(Http, "send", lambda self, *a, **k: trakt(self, *a, **k))
    monkeypatch.setattr(context, "builtin_keys", lambda: {})
    real = trakt_module.Trakt

    def quick(*args, **kwargs):   # no real waiting in tests
        kwargs["sleep"] = lambda seconds: None
        return real(*args, **kwargs)
    monkeypatch.setattr(context, "Trakt", quick)
    FakeAddon.settings.update({"artwork.preset": 1, "tmdb.api_key": "good", "trakt.client_id": "client-id",
                               "trakt.token": token_json(), "trakt.username": "sponge"})
    for show_id in (51, 52, 53, 54):
        tmdb.shows[show_id] = tv(show_id)
        tmdb.seasons[(show_id, 1)] = season(show_id, 1, 3)
        tmdb.seasons[(show_id, 2)] = season(show_id, 2, 2, unaired_from=2)
    trakt.pages.update({
        "/sync/watched/shows": [watched(51, [(1, 1), (1, 2)], 5), watched(52, [(1, 1), (1, 2), (1, 3)], 7),
                                watched(53, [(1, 1), (1, 2), (1, 3), (2, 1)], 6), watched(54, [(1, 1)], 8)],
        "/sync/watched/movies": [{"plays": 1, "last_watched_at": "2026-10-01T00:00:00.000Z", "movie": {"ids": {"tmdb": 7}}}],
        "/sync/watchlist/movies": [{"rank": 1, "listed_at": "2026-10-02T00:00:00.000Z", "movie": {"ids": {"tmdb": 8}}}],
        "/sync/playback/movies": [{"progress": 40.0, "paused_at": "2099-01-01T00:00:00.000Z", "id": 77,
                                   "movie": {"ids": {"tmdb": 9}}}],
        "/users/hidden/dropped": [{"hidden_at": "2026-10-01T00:00:00.000Z", "show": {"ids": {"tmdb": 54}}}],
    })
    app = context.App()
    app.store.set_meta("wizard_done", "1")
    from resources.lib import accounts
    accounts.syncer(app).run()
    app.store.close()
    return tmdb, trakt


def fresh_app():
    return context.App()


# -- home and menus -----------------------------------------------------------------------------------
def test_home_shows_trakt_menus_when_signed_in(world):
    call("")
    assert labels() == ["Films", "TV shows", "My films", "My TV shows", "Trakt lists", "Search", "Tools"]


def test_show_name_takes_the_highlight_colour(world):
    call("?action=next_up")
    assert Directory.items[0][1].label == "[COLOR FFF5A524]Show 52[/COLOR]: S02E01 Ep 1"
    world[1].calendar = [{"episode": {"season": 2, "number": 2}, "show": {"ids": {"tmdb": 51}}}]
    call("?action=calendar&when=upcoming")
    assert Directory.items[0][1].label.startswith("[COLOR FFF5A524]Show 51[/COLOR]: ")


@pytest.fixture
def plain(world):
    FakeAddon.settings["display.highlight"] = 5   # No highlight: plain labels
    return world


def test_next_up_skips_dropped_and_finished_shows(plain):
    call("?action=next_up")
    # 52 watched most recently (day 7): next is S02E01. 53 has watched every aired episode.
    # 51: next is S01E03. 54 is dropped on Trakt.
    assert labels() == ["Show 52: S02E01 Ep 1", "Show 51: S01E03 Ep 3"]
    assert "action=play" in Directory.items[0][0] and "season=2" in Directory.items[0][0]


def test_next_up_can_sort_by_newest_episodes(plain):
    world = plain
    FakeAddon.settings["nextup.sort"] = 1
    call("?action=next_up")
    assert labels() == ["Show 52: S02E01 Ep 1", "Show 51: S01E03 Ep 3"]   # 52's last air date is newer too
    world[0].shows[51]["last_air_date"] = "2026-12-01"
    call("?action=clear_cache")   # show details are cached for a day
    call("?action=next_up")
    assert labels()[0].startswith("Show 51")


def test_my_films_from_the_library(world):
    call("?action=my_movies")
    assert labels() == ["Collection", "Watchlist", "Favourites", "Watched", "In progress", "Recommended for you"]
    call("?action=library_titles&media=movie&part=watchlist")
    assert labels() == ["Film 8"]
    call("?action=library_titles&media=movie&part=playback")
    assert labels() == ["Film 9"]


def test_shows_in_progress(world):
    call("?action=shows_in_progress")
    assert sorted(labels()) == ["Show 51", "Show 52"]   # 53 finished what's aired, 54 dropped


def test_watched_marks_and_resume_points(world):
    call("?action=movie_list&kind=popular")
    films = {i[1].label: i[1] for i in Directory.items}
    assert films["Film 7"].tag.calls["setPlaycount"] == [(1,)]
    assert films["Film 9"].tag.calls["setResumePoint"] == [(2400.0, 6000)]
    # unwatched is said outright, so Kodi can't fill in its own play count (the tick stayed after Mark as unwatched)
    assert films["Film 3"].tag.calls["setPlaycount"] == [(0,)]
    resume = films["Film 3"].tag.calls["setResumePoint"][0]
    assert resume[0] == 0 and resume[1] > 0     # "none", said so Kodi can't fill in a stale one of its own


def test_show_and_season_progress(world):
    call("?action=library_titles&media=tv&part=watched")
    shows = {i[1].label: i[1] for i in Directory.items}
    assert shows["Show 51"].properties["WatchedEpisodes"] == "2" and shows["Show 51"].properties["TotalEpisodes"] == "4"
    assert "setPlaycount" in shows["Show 53"].tag.calls
    call("?action=seasons&tmdb_id=51")
    seasons = {i[1].label: i[1] for i in Directory.items}
    assert set(seasons) == {"Season 1 (2/3)", "Season 2 (0/1)"}   # in the name, so every view shows it
    assert seasons["Season 1 (2/3)"].label2 == "2 of 3 watched"
    call("?action=episodes&tmdb_id=51&season=1")
    counts = [i[1].tag.calls["setPlaycount"][0][0] for i in Directory.items]
    assert sorted(counts) == [0, 1, 1]                             # the unwatched one says 0, not nothing


def test_hide_watched_per_menu(world):
    FakeAddon.settings["hide.movie_lists.watched"] = True
    call("?action=movie_list&kind=popular")
    assert "Film 7" not in labels()
    call("?action=search_results&media=movie&query=matrix")   # search keeps its own setting
    FakeAddon.settings["hide.episodes.watched"] = True
    call("?action=episodes&tmdb_id=51&season=1")
    assert labels() == ["Ep 3"]


def test_context_menu_offers_trakt_when_signed_in(world):
    call("?action=movie_list&kind=popular")
    menu = dict(Directory.items[0][1].context_menu)
    assert "RunPlugin(" in menu["Trakt…"] and "action=trakt_menu" in menu["Trakt…"]


# -- Trakt actions -----------------------------------------------------------------------------------
def test_mark_film_watched(world):
    FakeDialog.script = [0]   # "Mark as watched"
    call("?action=trakt_menu&media=movie&tmdb_id=8")
    assert FakeDialog.menus[0][0] == "Mark as watched"
    assert world[1].posted("/sync/history") == [{"movies": [{"ids": {"tmdb": 8}}]}]
    assert fresh_app().library.movie_plays(8) == 1
    assert ("notification", "Marked as watched") in FakeDialog.shown
    assert "Container.Refresh" in Directory.builtins


def test_watchlist_toggle_reflects_state(world):
    FakeDialog.script = [2]
    call("?action=trakt_menu&media=movie&tmdb_id=8")
    assert FakeDialog.menus[0][2] == "Remove from watchlist"
    assert world[1].posted("/sync/watchlist/remove") == [{"movies": [{"ids": {"tmdb": 8}}]}]
    assert fresh_app().library.ids("watchlist", "movie") == []


def test_mark_season_watched_updates_every_episode(world):
    FakeDialog.script = [0]
    call("?action=trakt_menu&media=season&show=51&season=1")
    assert world[1].posted("/sync/history") == [{"shows": [{"ids": {"tmdb": 51}, "seasons": [{"number": 1}]}]}]
    assert set(fresh_app().library.watched_episodes(51)) == {(1, 1), (1, 2), (1, 3)}


def test_rate_an_episode(world):
    call("?action=trakt_menu&media=episode&show=51&season=1&episode=1")
    options = FakeDialog.menus[0]
    FakeDialog.script = [options.index("Rate…"), 1]   # 9 / 10
    call("?action=trakt_menu&media=episode&show=51&season=1&episode=1")
    body = world[1].posted("/sync/ratings")[0]
    assert body == {"shows": [{"ids": {"tmdb": 51}, "seasons": [{"number": 1, "episodes": [{"number": 1, "rating": 9}]}]}]}
    assert fresh_app().library.rating("episode", show=51, season=1, episode=1) == 9


def test_hide_a_show_from_next_up(plain):
    world = plain
    call("?action=trakt_menu&media=tv&tmdb_id=51")
    options = FakeDialog.menus[0]
    FakeDialog.script = [options.index("Hide from Next up and progress")]
    call("?action=trakt_menu&media=tv&tmdb_id=51")
    assert world[1].posted("/users/hidden/progress_watched") == [{"shows": [{"ids": {"tmdb": 51}}]}]
    call("?action=next_up")
    assert labels() == ["Show 52: S02E01 Ep 1"]


def test_clear_a_resume_point(world):
    call("?action=trakt_menu&media=movie&tmdb_id=9")
    options = FakeDialog.menus[0]
    FakeDialog.script = [options.index("Clear resume point")]
    call("?action=trakt_menu&media=movie&tmdb_id=9")
    assert ("DELETE", "/sync/playback/77") in world[1].paths("DELETE")
    assert fresh_app().library.progress("movie", 9) == (0, None)


def test_trakt_error_is_explained(world):
    world[1].fail[("POST", "/sync/history")] = 426
    FakeDialog.script = [0]
    call("?action=trakt_menu&media=movie&tmdb_id=8")
    assert ("notification", "This needs Trakt VIP.") in FakeDialog.shown
    assert fresh_app().library.movie_plays(8) == 0


# -- lists, calendars and recommendations --------------------------------------------------------------
def test_lists_with_counts_items_and_create(world):
    server = world[1]
    server.lists = [{"name": "Favourites 2026", "item_count": 2, "ids": {"trakt": 5}, "user": {"ids": {"slug": "sponge"}}}]
    server.list_items["/users/sponge/lists/5/items"] = [
        {"type": "show", "show": {"ids": {"tmdb": 51}}}, {"type": "movie", "movie": {"ids": {"tmdb": 7}}},
        {"type": "person", "person": {"ids": {"tmdb": 90}}}]
    call("?action=trakt_lists")
    assert labels()[0].endswith("Create a new list[/COLOR]")
    call("?action=lists&source=0")
    assert labels() == ["Favourites 2026 (2)"]
    assert server.gets("/users/me/lists")[0]["limit"] == 250   # your own lists: every page
    call("?action=list_items&user=sponge&list_id=5")
    assert labels() == ["Show 51", "Film 7"]   # the list's own order; people left out
    FakeDialog.script = ["Watch next"]
    call("?action=create_list")
    assert server.posted("/users/me/lists") == [{"name": "Watch next", "privacy": "private"}]


def test_upcoming_episodes_calendar(plain, monkeypatch):
    world = plain
    from resources.lib import airtime
    monkeypatch.setattr(airtime, "local_offset_seconds", lambda: 0)
    world[1].calendar = [{"first_aired": FUTURE + "T21:00:00.000Z", "episode": {"season": 2, "number": 2},
                          "show": {"ids": {"tmdb": 51}}}]
    call("?action=calendar&when=upcoming")
    import datetime
    day = datetime.date.fromisoformat(FUTURE)
    expected = f"{airtime.DAYS[day.weekday()]} {day.day} {airtime.MONTHS[day.month - 1]} 21:00"
    assert labels() == [f"{expected} \u00b7 Show 51: S02E02 Ep 2"]


def test_recent_episodes_show_when_they_aired(plain, monkeypatch):
    world = plain
    from resources.lib import airtime
    monkeypatch.setattr(airtime, "local_offset_seconds", lambda: 0)
    import datetime
    yesterday = (airtime.local_today() - datetime.timedelta(days=1)).isoformat()
    world[1].calendar = [{"first_aired": yesterday + "T20:00:00.000Z", "episode": {"season": 1, "number": 1},
                          "show": {"ids": {"tmdb": 51}}}]
    call("?action=calendar&when=recent")
    assert labels() == ["Yesterday 20:00 \u00b7 Show 51: S01E01 Ep 1"]


def test_recommendations(world):
    world[1].recommendations["movies"] = [{"title": "x", "ids": {"tmdb": 3}}, {"ids": {"tmdb": None}}]
    call("?action=recommended&media=movie")
    assert labels() == ["Film 3"]
    params = world[1].gets("/recommendations/movies")[0]
    assert params["ignore_collected"] == "true"


# -- account and sync ---------------------------------------------------------------------------------
def test_sign_in_from_tools(world):
    FakeAddon.settings["trakt.token"] = ""
    world[1].device_statuses = [400, 200]
    call("?action=trakt_sign_in")
    assert json.loads(FakeAddon.settings["trakt.token"])["access_token"] == "access-2"
    assert FakeAddon.settings["trakt.username"] == "sponge"
    assert any("ABCD1234" in m for kind, m in FakeDialog.shown if kind == "progress")
    assert ("notification", "Signed in to Trakt as sponge") in FakeDialog.shown


def test_sign_in_needs_a_client_id(world):
    FakeAddon.settings.update({"trakt.token": "", "trakt.client_id": ""})
    FakeDialog.script = [""]
    call("?action=trakt_sign_in")
    assert any(m.startswith("This copy of SpongeTV has no Trakt Client ID built in") for kind, m in FakeDialog.shown if kind == "ok")


def test_wizard_offers_trakt(world):
    FakeAddon.settings.update({"trakt.token": ""})
    app = fresh_app()
    app.store.set_meta("wizard_done", "")
    app.store.close()
    world[1].device_statuses = [200]
    FakeDialog.script = [-1, -1, "good", False, False, True, "client-id"]
    call("")
    assert json.loads(FakeAddon.settings["trakt.token"])["access_token"]
    assert labels()[2] == "My films"


def test_sign_out_forgets_local_data(world):
    FakeDialog.script = [True]
    call("?action=trakt_sign_out")
    assert FakeAddon.settings["trakt.token"] == "" and fresh_app().library.count() == 0
    call("")
    assert "My films" not in labels()


def test_sync_menu_shows_status(world):
    call("?action=tools_sync")
    assert labels()[0] == "Sync now" and labels()[1].startswith("Last sync: ")
    world[1].fail[("GET", "/sync/last_activities")] = 503
    call("?action=sync_now")
    call("?action=tools_sync")
    assert "Last problem: Couldn't reach Trakt" in labels()[1]


def test_service_scheduler_backs_off_and_wakes():
    scheduler = service.Scheduler(15, now=0)
    assert not scheduler.due(29) and scheduler.due(30)
    scheduler.finished(30, ok=False)
    assert scheduler.next_sync == 30 + 1800
    scheduler.finished(100, ok=False)
    assert scheduler.next_sync == 100 + 3600
    for _ in range(5):
        scheduler.finished(200, ok=False)
    assert scheduler.next_sync == 200 + service.MAX_BACKOFF
    scheduler.soon(300, delay=30)
    assert scheduler.next_sync == 330
    scheduler.finished(330, ok=True)
    assert scheduler.next_sync == 330 + 900


def test_service_sync_once(world):
    world[1].activities = {"movies": {"watched_at": "Z"}}
    assert service.sync_once() is True
    world[1].fail[("GET", "/sync/last_activities")] = 500
    assert service.sync_once() is False


def test_next_up_says_why_when_empty(world):
    from resources.lib.library import Library
    app = fresh_app()
    Library(app.store).replace("watched", "episode", [])
    app.store.close()
    call("?action=next_up")
    assert labels() == []
    assert ("notification", "No watched episodes from Trakt yet. Try Tools, Trakt sync, Sync now.") in FakeDialog.shown


def test_trending_lists_load_one_page_at_a_time(world):
    server = world[1]
    server.pages["/lists/trending"] = [{"list": {"name": f"L{i}", "item_count": i, "ids": {"trakt": 1000 + i},
                                                 "user": {"ids": {"slug": "x"}}}} for i in range(120)]
    call("?action=lists&source=2")
    assert len(server.gets("/lists/trending")) == 1           # one request, not every page
    assert len(labels()) == 51 and labels()[-1].endswith("Next page (2)[/COLOR]")
    call("?action=lists&source=2&page=3")
    assert len(labels()) == 20                                 # last page: no Next page


def test_big_list_opens_one_page_at_a_time_and_updates_after_adding(world):
    server = world[1]
    server.lists = [{"name": "Big", "item_count": 45, "ids": {"trakt": 5}}]
    server.list_items["/users/sponge/lists/5/items"] = [{"type": "movie", "movie": {"ids": {"tmdb": i}}}
                                                         for i in range(1, 46)]
    call("?action=list_items&user=sponge&list_id=5")
    assert len(server.gets("/users/sponge/lists/5/items")) == 1
    assert labels()[0] == "Film 1" and labels()[-1].endswith("Next page (2)[/COLOR]")
    server.list_items["/users/sponge/lists/5/items"].insert(0, {"type": "movie", "movie": {"ids": {"tmdb": 99}}})
    call("?action=trakt_menu&media=movie&tmdb_id=99")
    FakeDialog.script = [FakeDialog.menus[0].index("Add to a list\u2026"), 0]
    call("?action=trakt_menu&media=movie&tmdb_id=99")
    call("?action=list_items&user=sponge&list_id=5")
    assert labels()[0] == "Film 99"                            # not an out-of-date saved copy


def test_list_deleted_on_trakt_disappears_straight_away(world):
    server = world[1]
    server.lists = [{"name": "Keep", "item_count": 0, "ids": {"trakt": 1}},
                    {"name": "Delete me", "item_count": 0, "ids": {"trakt": 2}}]
    call("?action=lists&source=0")
    assert labels() == ["Keep (0)", "Delete me (0)"]
    server.lists.pop()                     # deleted on trakt.tv
    call("?action=lists&source=0")
    assert labels() == ["Keep (0)"]


def test_built_in_client_id_means_no_client_id_to_enter(world, monkeypatch):
    monkeypatch.setattr(context, "builtin_keys", lambda: {"trakt": "built-in-id"})
    FakeAddon.settings.update({"trakt.client_id": "", "trakt.token": ""})
    assert fresh_app().trakt.client_id == "built-in-id"
    world[1].device_statuses = [200]
    call("?action=trakt_sign_in")
    assert not any(kind == "input" for kind, _ in FakeDialog.shown)
    assert json.loads(FakeAddon.settings["trakt.token"])["access_token"]
    FakeAddon.settings["trakt.client_id"] = "my-own-app"   # your own app overrides it
    assert fresh_app().trakt.client_id == "my-own-app"


def test_wizard_with_built_in_client_id(world, monkeypatch):
    monkeypatch.setattr(context, "builtin_keys", lambda: {"trakt": "built-in-id"})
    FakeAddon.settings.update({"trakt.client_id": "", "trakt.token": ""})
    app = fresh_app()
    app.store.set_meta("wizard_done", "")
    app.store.close()
    world[1].device_statuses = [200]
    FakeDialog.script = [-1, -1, "good", False, False, True]   # ...then "Connect to Trakt?" Yes
    call("")
    assert json.loads(FakeAddon.settings["trakt.token"])["access_token"]
    assert FakeAddon.settings["trakt.client_id"] == ""   # nothing typed, nothing saved
