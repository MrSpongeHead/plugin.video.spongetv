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
        if url.endswith("/configuration"):
            if params["api_key"] == "good":
                return {}
            raise HttpError("Invalid API key", 401)
        if url.endswith("/search/movie"):
            hits = [{"id": 7}] if params["query"] == "matrix" else []
            return {"page": 1, "total_pages": 1, "results": hits}
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
    monkeypatch.setattr(context, "builtin_keys", lambda: {})
    FakeAddon.settings.update({"artwork.preset": 1, "tmdb.api_key": "good"})
    return calls


def call(action_query):
    router.dispatch(["plugin://plugin.video.spongetv/", "1", action_query])


def mark_wizard_done():
    app = context.App()
    app.store.set_meta("wizard_done", "1")
    app.store.close()


def test_first_run_shows_wizard_then_home(fake_tmdb):
    # English (UK), best artwork, a rejected key then a good one, no Fanart, no OMDb
    FakeDialog.script = [1, 0, "wrong", "good", False, False]
    call("")
    assert FakeAddon.settings["tmdb.api_key"] == "good"
    assert ("ok", "TMDB didn't accept that key. Check it and try again.") in FakeDialog.shown
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


def test_wizard_skip_and_read_token(fake_tmdb):
    FakeAddon.settings.pop("tmdb.api_key")
    FakeDialog.script = [-1, -1, "eyJhbGciOiJIUzI1NiJ9.long.token", "", False, False]
    call("")
    assert "tmdb.api_key" not in FakeAddon.settings
    assert ("ok", 'That looks like the long Read Access Token. Please copy the shorter "API Key" instead.') \
        in FakeDialog.shown
    assert any(m.startswith("No TMDB key saved") for kind, m in FakeDialog.shown if kind == "ok")


def test_wizard_saves_key_when_tmdb_unreachable(fake_tmdb, monkeypatch):
    def offline(self, url, params=None, headers=None):
        raise HttpError("offline")
    monkeypatch.setattr(Http, "get_json", offline)
    FakeAddon.settings.pop("tmdb.api_key")
    FakeDialog.script = [-1, -1, "abc123", False, False]
    call("")
    assert FakeAddon.settings["tmdb.api_key"] == "abc123"


def test_no_key_in_zip(tmp_path, monkeypatch):
    import zipfile
    from tools import build
    monkeypatch.setattr(build, "ROOT", build.ROOT)
    out = build.main()
    with zipfile.ZipFile(out) as archive:
        assert not any(name.endswith("_keys.json") for name in archive.namelist())


def test_new_search_asks_then_opens_results(fake_tmdb):
    mark_wizard_done()
    FakeDialog.script = ["matrix"]
    call("?action=new_search&media=movie")
    assert Directory.builtins == [
        "Container.Update(plugin://plugin.video.spongetv/?action=search&media=movie&query=matrix)"]
    call("?action=search&media=movie&query=matrix")
    assert [i[1].label for i in Directory.items] == ["Film 7"]
    Directory.items = []
    call("?action=search_menu&media=movie")
    labels = [i[1].label for i in Directory.items]
    assert "matrix" in labels and Directory.items[0][2] is False  # "New search" is not a folder


def test_search_with_no_matches_says_so(fake_tmdb):
    mark_wizard_done()
    call("?action=search&media=movie&query=zzzz")
    assert ("notification", "Nothing found") in FakeDialog.shown and Directory.ended is True


def test_cancelled_search_does_nothing(fake_tmdb):
    mark_wizard_done()
    FakeDialog.script = [""]
    call("?action=new_search&media=movie")
    assert Directory.builtins == [] and Directory.ended is None


@pytest.fixture
def fake_everything(monkeypatch):
    """Answers every TMDB call a menu can make: lists return film 7 or show 50."""
    def get_json(self, url, params=None, headers=None):
        path = url.split("/3", 1)[1]
        if path.startswith("/genre/"):
            return {"genres": [{"id": 18, "name": "Drama"}]}
        if path == "/tv/50":
            return SHOW
        if path.startswith("/tv/50/season/"):
            return SEASON_1
        if path.startswith("/movie/") and path.rsplit("/", 1)[1].isdigit():
            return movie(int(path.rsplit("/", 1)[1]))
        is_tv = "/tv" in path
        return {"page": 1, "total_pages": 2, "results": [{"id": 50 if is_tv else 7}]}
    monkeypatch.setattr(Http, "get_json", get_json)
    monkeypatch.setattr(context, "builtin_keys", lambda: {})
    FakeAddon.settings.update({"tmdb.api_key": "good"})
    mark_wizard_done()


@pytest.mark.parametrize("query", [
    "", "?action=movies", "?action=tv", "?action=search_home",
    *[f"?action=movie_list&kind={k}" for k in ("trending", "popular", "top_rated", "now_playing", "upcoming")],
    *[f"?action=tv_list&kind={k}" for k in ("trending", "popular", "top_rated", "airing_today", "on_the_air")],
    "?action=genres&media=movie", "?action=genres&media=tv",
    "?action=genre&media=movie&genre=18", "?action=genre&media=tv&genre=18",
    "?action=years&media=movie", "?action=year&media=movie&year=2020", "?action=year&media=tv&year=2020",
    "?action=search_menu&media=tv", "?action=search&media=tv&query=show", "?action=search&media=movie&query=film",
    "?action=seasons&tmdb_id=50", "?action=episodes&tmdb_id=50&season=1", "?action=all_episodes&tmdb_id=50",
    "?action=tools",
])
def test_every_menu_opens(fake_everything, query):
    call(query)
    assert Directory.ended is True, f"{query} failed"
    assert Directory.items, f"{query} listed nothing"


def test_next_page_keeps_genre_and_media(fake_everything):
    call("?action=genre&media=tv&genre=18")
    next_url = Directory.items[-1][0]
    assert "media=tv" in next_url and "genre=18" in next_url and "page=2" in next_url
