# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end plugin calls with fake TMDB responses."""

import datetime

import pytest

from conftest import Directory, FakeAddon, FakeDialog
from resources.lib import context, router
from resources.lib.http import Http, HttpError

TODAY = datetime.date.today()
PAST = (TODAY - datetime.timedelta(days=30)).isoformat()
FUTURE = (TODAY + datetime.timedelta(days=30)).isoformat()


def movie(i):
    return {"id": i, "title": f"Film {i}", "overview": "Plot", "release_date": "2020-01-01",
            "vote_average": 7.0, "vote_count": 100, "imdb_id": f"tt{i:07d}",
            "genres": [{"id": 18, "name": "Drama"}], "runtime": 100,
            "credits": {"cast": [{"name": "A", "character": "B", "order": 0}], "crew": [{"job": "Director", "name": "D"}]},
            "images": {"posters": [], "backdrops": [], "logos": []}}


SHOW = {"id": 50, "name": "Show", "overview": "Show plot", "first_air_date": "2019-01-01", "in_production": True,
        "external_ids": {"imdb_id": "tt0000050", "tvdb_id": 123},
        "seasons": [{"season_number": 0, "name": "Specials", "air_date": "2019-01-01"},
                    {"season_number": 1, "name": "Season 1", "air_date": "2019-01-01"},
                    {"season_number": 2, "name": "Season 2", "air_date": FUTURE}]}
SEASON_1 = {"episodes": [
    {"id": 1, "name": "One", "season_number": 1, "episode_number": 1, "air_date": PAST},
    {"id": 2, "name": "Two", "season_number": 1, "episode_number": 2, "air_date": FUTURE},
]}


@pytest.fixture
def fake_tmdb(monkeypatch):
    calls = []

    def get_json(self, url, params=None, headers=None):
        calls.append(url)
        if url.endswith("/movie/popular"):
            return {"page": 1, "total_pages": 3, "results": [{"id": i} for i in range(1, 21)]}
        if "/movie/" in url:
            return movie(int(url.rsplit("/", 1)[1]))
        if url.endswith("/tv/50/season/1"):
            return SEASON_1
        if url.endswith("/tv/50"):
            return SHOW
        raise HttpError("not found", 404)

    monkeypatch.setattr(Http, "get_json", get_json)
    monkeypatch.setattr(context, "builtin_keys", lambda: {"tmdb": "built-in"})
    FakeAddon.settings.update({"artwork.preset": 1})
    return calls


def call(action_query):
    router.dispatch(["plugin://plugin.video.spongetv/", "1", action_query])


def mark_wizard_done():
    app = context.App()
    app.store.set_meta("wizard_done", "1")
    app.store.close()


def test_first_run_shows_wizard_then_home(fake_tmdb):
    FakeDialog.script = [1, 0, False, False]  # English (UK), best artwork, no Fanart, no OMDb
    call("")
    assert FakeAddon.settings["metadata.language"] == 1
    assert FakeAddon.settings["artwork.preset"] == 0
    assert len(Directory.items) == 4 and Directory.ended is True
    Directory.items = []
    call("")  # second time: no wizard
    assert ("ok", "A few quick questions to set things up. You can change any of these later in Settings.") \
        in FakeDialog.shown
    assert len(Directory.items) == 4


def test_movie_list_has_details_and_next_page(fake_tmdb):
    mark_wizard_done()
    call("?action=movie_list&kind=popular")
    assert Directory.ended is True and Directory.content == "movies"
    films = [i for i in Directory.items if not i[2]]
    assert len(films) == 20
    url, item, is_folder = films[0]
    assert "action=play" in url and item.properties["IsPlayable"] == "true"
    tag = item.tag.calls
    assert tag["setMediaType"] == [("movie",)]
    assert tag["setUniqueIDs"][0][0] == {"tmdb": "1", "imdb": "tt0000001"}
    assert tag["setDirectors"] == [(["D"],)]
    next_page = Directory.items[-1]
    assert next_page[2] is True and "page=2" in next_page[0]
    assert next_page[1].label == "Next page (2 of 3)"


def test_seasons_hide_specials_and_unaired(fake_tmdb):
    FakeAddon.settings.update({"display.hide_specials": True, "display.hide_unaired": True})
    call("?action=seasons&tmdb_id=50")
    labels = [i[1].label for i in Directory.items]
    assert labels == ["Season 1"]


def test_episodes_hide_unaired(fake_tmdb):
    FakeAddon.settings.update({"display.hide_unaired": True})
    call("?action=episodes&tmdb_id=50&season=1")
    assert [i[1].label for i in Directory.items] == ["One"]
    assert Directory.content == "episodes"


def test_play_is_not_available_yet(fake_tmdb):
    call("?action=play&media=movie&tmdb_id=1")
    assert Directory.resolved is False
    assert ("notification", "Playback arrives in a later test build") in FakeDialog.shown


def test_missing_key_explains_and_fails(monkeypatch):
    monkeypatch.setattr(context, "builtin_keys", lambda: {})
    call("?action=movie_list&kind=popular")
    assert Directory.ended is False
    assert ("notification", "No TMDB API key. Add one in Settings, Accounts.") in FakeDialog.shown


def test_unknown_action_fails():
    call("?action=nonsense")
    assert Directory.ended is False


def test_users_key_overrides_built_in(fake_tmdb):
    FakeAddon.settings["tmdb.api_key"] = "mine"
    app = context.App()
    assert app.key("tmdb") == "mine"
