# SPDX-License-Identifier: GPL-3.0-or-later
"""Activity-based sync: only what changed, never a half-finished part, one sync at a time."""

import pytest

from fake_trakt import FakeTrakt
from resources.lib.database import Store
from resources.lib.http import Http
from resources.lib.library import Library
from resources.lib.sync import PARTS, Syncer
from resources.lib.trakt import PAGE_LIMIT, Trakt, TraktError
from test_trakt import Clock, MemoryTokens

WATCHED_SHOWS = [{"show": {"ids": {"tmdb": 50, "trakt": 5}}, "seasons": [
    {"number": 1, "episodes": [{"number": 1, "plays": 1, "last_watched_at": "2026-01-01T20:00:00.000Z"},
                               {"number": 2, "plays": 2, "last_watched_at": "2026-01-02T20:00:00.000Z"}]}]}]
WATCHED_MOVIES = [{"plays": 1, "last_watched_at": "2026-01-03T20:00:00.000Z", "movie": {"ids": {"tmdb": 7, "trakt": 70}}},
                  {"plays": 1, "last_watched_at": "2026-01-03T20:00:00.000Z", "movie": {"ids": {"tmdb": None, "trakt": 71}}}]


@pytest.fixture
def setup(monkeypatch, tmp_path):
    server = FakeTrakt()
    monkeypatch.setattr(Http, "send", lambda self, *a, **k: server(self, *a, **k))
    server.pages.update({
        "/sync/watched/movies": WATCHED_MOVIES,
        "/sync/watched/shows": WATCHED_SHOWS,
        "/sync/watchlist/movies": [{"rank": 1, "listed_at": "2026-02-01T00:00:00.000Z", "movie": {"ids": {"tmdb": 8}}}],
        "/sync/ratings/episodes": [{"rating": 9, "rated_at": "2026-02-01T00:00:00.000Z",
                                    "episode": {"season": 1, "number": 2}, "show": {"ids": {"tmdb": 50}}}],
        "/users/hidden/dropped": [{"hidden_at": "2026-02-01T00:00:00.000Z", "show": {"ids": {"tmdb": 60}}}],
        "/sync/playback/movies": [
            {"progress": 40.5, "paused_at": "2026-10-01T00:00:00.000Z", "id": 11, "movie": {"ids": {"tmdb": 9}}},
            {"progress": 10.0, "paused_at": "2020-01-01T00:00:00.000Z", "id": 12, "movie": {"ids": {"tmdb": 10}}},
        ],
    })
    store = Store(str(tmp_path / "s.db"))
    clock = Clock(now=1_790_000_000.0)   # October 2026
    tokens = MemoryTokens({"access_token": "access-1", "refresh_token": "r", "expires_at": clock.now + 5 * 86400})
    trakt = Trakt("client-id", Http("SpongeTV/test"), tokens, store=store, clock=clock, sleep=clock.sleep)
    syncer = Syncer(trakt, store, clock=clock, resume_max_age_days=60)
    return server, syncer, Library(store), store


def test_first_sync_downloads_every_part(setup):
    server, syncer, library, _ = setup
    updated = syncer.run()
    assert len(updated) == len(PARTS)
    assert library.movie_plays(7) == 1
    assert library.watched_episodes(50) == {(1, 1): (1, "2026-01-01T20:00:00.000Z"), (1, 2): (2, "2026-01-02T20:00:00.000Z")}
    assert library.ids("watchlist", "movie") == [8]
    assert library.rating("episode", show=50, season=1, episode=2) == 9
    assert library.skipped_shows() == {60}
    assert library.progress("movie", 9) == (40.5, 11)
    assert library.progress("movie", 10) == (0, None)   # older than 60 days: left out
    assert syncer.status()[0] and syncer.status()[1] == ""


def test_next_sync_only_fetches_what_changed(setup):
    server, syncer, library, _ = setup
    syncer.run()
    server.calls.clear()
    assert syncer.run() == []
    assert server.paths("GET") == [("GET", "/sync/last_activities")]
    server.activities = {"movies": {"watched_at": "B"}, "episodes": {"watched_at": "A"}}
    assert syncer.run() == ["watched:movie"]


def test_failed_page_never_wipes_existing_data(setup):
    server, syncer, library, _ = setup
    syncer.run()
    many = [{"show": {"ids": {"tmdb": 100 + i}}, "seasons": [{"number": 1, "episodes": [{"number": 1}]}]}
            for i in range(PAGE_LIMIT + 5)]
    server.pages["/sync/watched/shows"] = many
    server.activities = {"movies": {"watched_at": "A"}, "episodes": {"watched_at": "B"}}
    server.fail[("GET", "/sync/watched/shows", 2)] = 502
    with pytest.raises(TraktError):
        syncer.run()
    assert library.watched_episodes(50)            # yesterday's marks are still there
    assert library.watched_episodes(100) == {}     # nothing half-downloaded was stored
    assert syncer.status()[1] == "unavailable"
    del server.fail[("GET", "/sync/watched/shows", 2)]
    assert "watched:episode" in syncer.run()       # tried again next time, as the activity didn't count
    assert library.watched_episodes(100)


def test_only_one_sync_at_a_time_and_a_stuck_lock_frees_itself(setup):
    server, syncer, _, store = setup
    store.set_meta("sync_lock", str(syncer.clock()))
    assert syncer.run() is None
    syncer.clock.now += 16 * 60
    assert syncer.run() is not None
    assert store.get_meta("sync_lock") == ""


def test_lock_is_released_after_an_error(setup):
    server, syncer, _, store = setup
    server.fail[("GET", "/sync/last_activities")] = 500
    with pytest.raises(TraktError):
        syncer.run()
    assert store.get_meta("sync_lock") == ""


def test_rebuild_downloads_everything_again(setup):
    server, syncer, library, _ = setup
    syncer.run()
    library.add("watchlist", "movie", 999)
    assert len(syncer.rebuild()) == len(PARTS)
    assert 999 not in library.ids("watchlist", "movie")


def test_part_trakt_does_not_offer_is_skipped(setup):
    server, syncer, library, _ = setup
    server.fail[("GET", "/users/hidden/dropped", 1)] = 404
    updated = syncer.run()
    assert "dropped:show" not in updated and "watched:movie" in updated


def test_watched_shows_ask_for_seasons_in_pages_of_100(setup):
    server, syncer, library, _ = setup
    syncer.run()
    params = server.gets("/sync/watched/shows")[0]
    assert params["extended"] == "progress" and params["limit"] == 100
    assert library.watched_episodes(50)   # the episodes really arrived


def test_progress_format_skips_episodes_not_completed(setup):
    server, syncer, library, _ = setup
    server.pages["/sync/watched/shows"] = [{"show": {"ids": {"tmdb": 50}}, "seasons": [{"number": 1, "episodes": [
        {"number": 1, "completed": True, "last_watched_at": "2026-01-01T20:00:00.000Z"},
        {"number": 2, "completed": False, "last_watched_at": None}]}]}]
    syncer.run()
    assert set(library.watched_episodes(50)) == {(1, 1)}


def test_older_sync_format_downloads_everything_again(setup):
    server, syncer, library, store = setup
    syncer.run()
    store.set_meta("sync_format", "1")      # as left by 0.2.0
    server.calls.clear()
    assert len(syncer.run()) == len(PARTS)  # same activities, but every part fetched again
    assert store.get_meta("sync_format") == "2"
    assert syncer.run() == []


def test_shows_without_a_tmdb_id_are_looked_up(setup):
    server, syncer, library, _ = setup
    server.trakt_to_tmdb[5] = 55
    server.pages["/sync/watched/shows"] = [{"show": {"ids": {"trakt": 5}}, "seasons": [
        {"number": 1, "episodes": [{"number": 1, "plays": 1, "last_watched_at": "2026-01-01T20:00:00.000Z"}]}]}]
    syncer.run()
    assert set(library.watched_episodes(55)) == {(1, 1)}
