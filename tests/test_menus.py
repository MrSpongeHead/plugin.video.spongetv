# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end plugin calls against a fake TMDB that answers every endpoint SpongeTV uses."""

import datetime

import pytest

from conftest import Directory, FakeAddon, FakeDialog
from resources.lib import airtime, context, options, router
from resources.lib.database import Store
from resources.lib.http import Http, HttpError

TODAY = datetime.date.today()
PAST = (TODAY - datetime.timedelta(days=30)).isoformat()
FUTURE = (TODAY + datetime.timedelta(days=30)).isoformat()


def movie(i, release=PAST):
    return {"id": i, "title": f"Film {i}", "overview": "Plot", "release_date": release,
            "vote_average": 7.0, "vote_count": 100, "imdb_id": f"tt{i:07d}",
            "genres": [{"id": 18, "name": "Drama"}], "runtime": 100,
            "production_companies": [{"name": "Studio A"}, {"name": "Studio B"}],
            "credits": {"cast": [{"id": 90, "name": "Ann Actor", "character": "Hero", "order": 0}],
                        "crew": [{"id": 91, "job": "Director", "name": "Dee Rector"}]},
            "images": {"posters": [], "backdrops": [], "logos": []}}


def show(i=50, first_air=PAST):
    return {"id": i, "name": f"Show {i}", "overview": "Show plot", "first_air_date": first_air,
            "in_production": True, "origin_country": ["GB"],
            "networks": [{"name": "Net A"}, {"name": "Net B"}],
            "created_by": [{"id": 92, "name": "Cree Ator"}],
            "credits": {"cast": [{"id": 90, "name": "Ann Actor", "character": "Lead"}], "crew": []},
            "external_ids": {"imdb_id": "tt0000050", "tvdb_id": 123},
            "seasons": [{"season_number": 0, "name": "Specials", "air_date": PAST},
                        {"season_number": 1, "name": "Season 1", "air_date": PAST},
                        {"season_number": 2, "name": "Season 2", "air_date": FUTURE}]}


SEASON_1 = {"episodes": [
    {"id": 1, "name": "One", "season_number": 1, "episode_number": 1, "air_date": PAST},
    {"id": 2, "name": "Two", "season_number": 1, "episode_number": 2, "air_date": FUTURE},
]}
PERSON_ACTOR = {"id": 90, "name": "Ann Actor", "known_for_department": "Acting", "biography": "Bio",
                "movie_credits": {"cast": [{"id": i, "popularity": i} for i in range(1, 26)] + [{"id": 3, "popularity": 3}],
                                  "crew": []},
                "tv_credits": {"cast": [{"id": 50, "popularity": 1}], "crew": []}}
PERSON_DIRECTOR = {"id": 91, "name": "Dee Rector", "known_for_department": "Directing",
                   "movie_credits": {"cast": [{"id": 1}], "crew": [{"id": 4, "department": "Directing"},
                                                                    {"id": 5, "department": "Writing"}]},
                   "tv_credits": {"cast": [], "crew": []}}


class FakeTmdb:
    """Records every call; answers like TMDB would."""

    def __init__(self):
        self.calls = []
        self.movies = {}          # id -> release date override
        self.bad_networks = {9}
        self.reject_sort = None

    def __call__(self, http_self, url, params=None, headers=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if "fanart.tv" in url:
            if params.get("api_key") == "goodfan":
                return {}
            raise HttpError("Not authorized", 401)
        if "omdbapi" in url:
            return {"Response": "True"} if params.get("apikey") == "goodomdb" else {"Response": "False", "Error": "Invalid API key!"}
        path = url.split("/3", 1)[1]
        if path == "/configuration":
            if params.get("api_key") == "good":
                return {}
            raise HttpError("Invalid API key", 401)
        if path.startswith("/genre/"):
            return {"genres": [{"id": 18, "name": "Drama"}]}
        if path.startswith("/network/"):
            network_id = int(path.rsplit("/", 1)[1])
            if network_id in self.bad_networks:
                raise HttpError("not found", 404)
            return {"id": network_id, "name": f"Net {network_id:04d}", "logo_path": "/n.png"}
        if path == "/watch/providers/tv":
            return {"results": [
                {"provider_id": 8, "provider_name": "Netflix", "display_priorities": {"GB": 2}, "logo_path": "/x.png"},
                {"provider_id": 38, "provider_name": "BBC iPlayer", "display_priorities": {"GB": 1}},
            ]}
        if path.startswith("/discover/"):
            if self.reject_sort and params.get("sort_by") == self.reject_sort:
                raise HttpError("bad sort", 422)
            is_tv = path.endswith("/tv")
            return {"page": 1, "total_pages": 2, "results": [{"id": 50 if is_tv else 7}]}
        if path.startswith("/search/"):
            kind = path.rsplit("/", 1)[1]
            if params["query"] == "nothing":
                return {"page": 1, "total_pages": 0, "total_results": 0, "results": []}
            hits = {"movie": [{"id": 7}], "tv": [{"id": 50}], "person": [{"id": 90, "name": "Ann Actor"}]}[kind]
            if params["query"] == "films only" and kind != "movie":
                hits = []
            return {"page": 1, "total_pages": 1, "total_results": len(hits), "results": hits}
        if path.startswith("/person/"):
            return PERSON_DIRECTOR if path.endswith("/91") else PERSON_ACTOR
        if path.endswith("/recommendations"):
            return {"page": 1, "total_pages": 1, "results": [] if "/movie/8/" in path else [{"id": 9}]}
        if path.endswith("/similar"):
            return {"page": 1, "total_pages": 1, "results": [{"id": 10}]}
        if path == "/tv/50" or (path.startswith("/tv/") and path[4:].isdigit()):
            return show(int(path[4:]))
        if path.startswith("/tv/50/season/"):
            return SEASON_1
        if path.startswith("/movie/") and path[7:].isdigit():
            i = int(path[7:])
            return movie(i, self.movies.get(i, PAST))
        if path.startswith("/movie/") or path.startswith("/trending/movie"):
            return {"page": 1, "total_pages": 3, "results": [{"id": i} for i in range(1, 21)]}
        if path.startswith("/tv/") or path.startswith("/trending/tv"):
            return {"page": 1, "total_pages": 1, "results": [{"id": 50}]}
        raise HttpError(f"unexpected {path}", 404)

    def discover_params(self):
        return [p for u, p in self.calls if "/discover/" in u]


@pytest.fixture
def tmdb(monkeypatch):
    fake = FakeTmdb()
    monkeypatch.setattr(Http, "get_json", lambda self, url, params=None, headers=None: fake(self, url, params, headers))
    monkeypatch.setattr(context, "builtin_keys", lambda: {})
    FakeAddon.settings.update({"artwork.preset": 1, "tmdb.api_key": "good"})
    return fake


def call(query):
    Directory.items = []
    Directory.ended = None
    router.dispatch(["plugin://plugin.video.spongetv/", "1", query])


def labels():
    return [i[1].label for i in Directory.items]


def store():
    return context.App().store


@pytest.fixture
def ready(tmdb):
    """Wizard already done."""
    s = store()
    s.set_meta("wizard_done", "1")
    s.close()
    return tmdb


# -- wizard and keys -------------------------------------------------------------------
def test_first_run_wizard_checks_tmdb_key(tmdb):
    FakeAddon.settings.pop("tmdb.api_key")
    # English (UK), best artwork, a rejected key then a good one, no Fanart, no OMDb
    FakeDialog.script = [1, 0, "wrong", "good", False, False]
    call("")
    assert FakeAddon.settings["tmdb.api_key"] == "good"
    assert ("ok", "TMDB didn't accept that key. Check it and try again.") in FakeDialog.shown
    assert FakeAddon.settings["metadata.language"] == 1 and FakeAddon.settings["artwork.preset"] == 0
    assert len(Directory.items) == 4 and Directory.ended is True
    shown_before = len(FakeDialog.shown)
    call("")  # second time: no wizard
    assert len(FakeDialog.shown) == shown_before


def test_wizard_checks_optional_keys(tmdb):
    FakeDialog.script = [-1, -1, "good", True, "badfan", "goodfan", True, "goodomdb"]
    call("")
    assert FakeAddon.settings["fanart.api_key"] == "goodfan"
    assert FakeAddon.settings["omdb.api_key"] == "goodomdb"
    assert ("ok", "Fanart.tv didn't accept that key. Check it and try again.") in FakeDialog.shown


def test_wizard_rejects_read_token_and_allows_skip(tmdb):
    FakeAddon.settings.pop("tmdb.api_key")
    FakeDialog.script = [-1, -1, "eyJhbGciOiJIUzI1NiJ9.long.token", "", False, False]
    call("")
    assert "tmdb.api_key" not in FakeAddon.settings
    assert any("Read Access Token" in m for kind, m in FakeDialog.shown if kind == "ok")
    assert any(m.startswith("No TMDB key saved") for kind, m in FakeDialog.shown if kind == "ok")


def test_wizard_saves_key_when_tmdb_unreachable(tmdb, monkeypatch):
    def offline(self, url, params=None, headers=None):
        raise HttpError("offline")
    monkeypatch.setattr(Http, "get_json", offline)
    FakeAddon.settings.pop("tmdb.api_key")
    FakeDialog.script = [-1, -1, "abc123", False, False]
    call("")
    assert FakeAddon.settings["tmdb.api_key"] == "abc123"


def test_missing_key_explains_and_fails(monkeypatch):
    monkeypatch.setattr(context, "builtin_keys", lambda: {})
    call("?action=movie_list&kind=popular")
    assert Directory.ended is False
    assert ("notification", "No TMDB API key. Add one in Settings, Accounts.") in FakeDialog.shown


def test_unknown_action_fails():
    call("?action=nonsense")
    assert Directory.ended is False


# -- every menu opens --------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "", "?action=movies", "?action=tv",
    *[f"?action=movie_list&kind={k}" for k in ("trending", "popular", "top_rated", "now_playing", "upcoming")],
    *[f"?action=tv_list&kind={k}" for k in ("trending", "popular", "top_rated", "airing_today", "on_the_air")],
    "?action=genres&media=movie", "?action=genres&media=tv",
    "?action=genre&media=movie&genre=18", "?action=genre&media=tv&genre=18",
    "?action=years&media=movie", "?action=year&media=movie&year=2020", "?action=year&media=tv&year=2020",
    "?action=new_shows", "?action=networks", "?action=network&network=213",
    "?action=providers", "?action=provider&provider=8",
    "?action=related&media=movie&tmdb_id=7", "?action=related&media=tv&tmdb_id=50",
    "?action=cast&media=movie&tmdb_id=7", "?action=cast&media=tv&tmdb_id=50",
    "?action=search_menu", "?action=search&query=matrix",
    "?action=search_results&media=movie&query=matrix", "?action=search_results&media=tv&query=matrix",
    "?action=search_results&media=person&query=matrix",
    "?action=person&person=90", "?action=person_titles&person=90&media=movie",
    "?action=seasons&tmdb_id=50", "?action=episodes&tmdb_id=50&season=1", "?action=all_episodes&tmdb_id=50",
    "?action=tools", "?action=tools_accounts", "?action=tools_caches",
])
def test_every_menu_opens(ready, query):
    call(query)
    assert Directory.ended is True, f"{query} failed"
    assert Directory.items, f"{query} listed nothing"


# -- films and shows -----------------------------------------------------------------------
def test_film_list_items(ready):
    call("?action=movie_list&kind=popular")
    assert Directory.content == "movies"
    films = [i for i in Directory.items if not i[2]]
    assert len(films) == 20
    url, item, _ = films[0]
    assert "action=play" in url and item.properties["IsPlayable"] == "true"
    assert item.tag.calls["setUniqueIDs"][0][0] == {"tmdb": "1", "imdb": "tt0000001"}
    assert item.tag.calls["setStudios"] == [(["Studio A"],)]
    menu = dict(item.context_menu)
    assert "action=related" in menu["Related titles"] and "action=cast" in menu["Cast and crew"]
    assert Directory.items[-1][1].label == "[COLOR FFF5A524]Next page (2 of 3)[/COLOR]"


def test_all_studios_and_no_highlight(ready):
    FakeAddon.settings.update({"display.all_studios": True, "display.highlight": 5})
    call("?action=movie_list&kind=popular")
    assert Directory.items[0][1].tag.calls["setStudios"] == [(["Studio A", "Studio B"],)]
    assert Directory.items[-1][1].label == "Next page (2 of 3)"


def test_hide_unreleased_is_per_menu(ready):
    ready.movies[2] = FUTURE
    call("?action=movie_list&kind=popular")
    assert "Film 2" in labels()
    FakeAddon.settings["hide.movie_lists.unreleased"] = True
    call("?action=movie_list&kind=popular")
    assert "Film 2" not in labels()
    call("?action=movie_list&kind=upcoming")  # Coming soon is exempt
    assert "Film 2" in labels()
    call("?action=search_results&media=movie&query=matrix")  # search has its own setting
    assert labels() == ["Film 7"]


def test_seasons_and_episodes_have_their_own_hide_settings(ready):
    FakeAddon.settings.update({"hide.seasons.specials": True, "hide.seasons.unaired": True,
                               "hide.episodes.unaired": False})
    call("?action=seasons&tmdb_id=50")
    assert labels() == ["Season 1"]
    call("?action=episodes&tmdb_id=50&season=1")
    assert labels() == ["One", "Two"]
    FakeAddon.settings["hide.episodes.unaired"] = True
    call("?action=episodes&tmdb_id=50&season=1")
    assert labels() == ["One"]


@pytest.mark.parametrize("style,expected", [(0, "One"), (1, "1x01. One"), (2, "S01E01 One")])
def test_episode_label_styles(ready, style, expected):
    FakeAddon.settings["display.episode_label"] = style
    call("?action=episodes&tmdb_id=50&season=1")
    assert Directory.items[0][1].label == expected
    assert Directory.items[0][1].tag.calls["setTitle"] == [("One",)]


def test_related_falls_back_to_similar(ready):
    call("?action=related&media=movie&tmdb_id=7")
    assert labels() == ["Film 9"]
    call("?action=related&media=movie&tmdb_id=8")
    assert labels() == ["Film 10"]


def test_tv_cast_includes_creator(ready):
    call("?action=cast&media=tv&tmdb_id=50")
    assert labels() == ["Ann Actor", "Cree Ator"]
    assert Directory.items[1][1].label2 == "Creator"


def test_cast_lists_actors_and_director(ready):
    call("?action=cast&media=movie&tmdb_id=7")
    assert labels() == ["Ann Actor", "Dee Rector"]
    assert Directory.items[0][1].label2 == "Hero"
    assert "action=person&person=90" in Directory.items[0][0]


# -- discovery lists and sorting -----------------------------------------------------------
def test_sort_is_remembered_per_list(ready):
    call("?action=genre&media=movie&genre=18")
    assert Directory.items[0][1].label == "[COLOR FFF5A524]Sort: Popularity[/COLOR]"
    assert ready.discover_params()[-1]["sort_by"] == "popularity.desc"
    FakeDialog.script = [1]  # Rating
    call("?action=set_sort&media=movie&key=genre:movie:18")
    assert "Container.Refresh" in Directory.builtins
    call("?action=genre&media=movie&genre=18")
    params = ready.discover_params()[-1]
    assert params["sort_by"] == "vote_average.desc" and params["vote_count.gte"] == 200
    assert Directory.items[0][1].label.endswith("Sort: Rating[/COLOR]")
    call("?action=genre&media=movie&genre=35")  # another list keeps its own sort
    assert ready.discover_params()[-1]["sort_by"] == "popularity.desc"


def test_rejected_sort_falls_back_to_popularity(ready):
    ready.reject_sort = "title.asc"
    s = store()
    options.set_sort(s, "year:movie:2020", "title.asc")
    s.close()
    call("?action=year&media=movie&year=2020")
    assert Directory.ended is True
    assert [p["sort_by"] for p in ready.discover_params()] == ["title.asc", "popularity.desc"]


def test_sort_item_only_on_first_page(ready):
    call("?action=genre&media=movie&genre=18&page=2")
    assert not Directory.items[0][1].label.startswith("[COLOR")


def test_new_shows_are_from_the_last_90_days(ready):
    call("?action=new_shows")
    params = ready.discover_params()[-1]
    end = datetime.date.fromisoformat(params["first_air_date.lte"])
    start = datetime.date.fromisoformat(params["first_air_date.gte"])
    assert end == airtime.local_today() and (end - start).days == 90


def test_networks_named_by_tmdb_sorted_and_missing_dropped(ready):
    call("?action=networks")
    names = labels()
    assert "Net 0009" not in names and names == sorted(names) and len(names) == 22
    call("?action=network&network=213")
    assert ready.discover_params()[-1]["with_networks"] == "213"


def test_streaming_services_in_region_order(ready):
    FakeAddon.settings["metadata.language"] = 1  # English (UK) -> region GB
    call("?action=providers")
    assert labels() == ["BBC iPlayer", "Netflix"]
    call("?action=provider&provider=38")
    params = ready.discover_params()[-1]
    assert params["with_watch_providers"] == "38" and params["watch_region"] == "GB"


# -- search and people ------------------------------------------------------------------------
def test_one_search_box_groups_results(ready):
    FakeDialog.script = ["matrix"]
    call("?action=new_search")
    assert Directory.builtins == ["Container.Update(plugin://plugin.video.spongetv/?action=search&query=matrix)"]
    call("?action=search&query=matrix")
    assert labels() == ["Films (1)", "TV shows (1)", "People (1)"]
    call("?action=search&query=films only")
    assert labels() == ["Films (1)"]
    call("?action=search_menu")
    assert "matrix" in labels() and Directory.items[0][2] is False  # "New search" is not a folder


def test_search_with_no_matches_says_so(ready):
    call("?action=search&query=nothing")
    assert ("notification", "Nothing found") in FakeDialog.shown and Directory.ended is True


def test_cancelled_search_does_nothing(ready):
    FakeDialog.script = [""]
    call("?action=new_search")
    assert Directory.builtins == [] and Directory.ended is None


def test_actor_page_and_their_films(ready):
    call("?action=person&person=90")
    assert labels() == ["Films (25)", "TV shows (1)"]  # duplicates counted once
    call("?action=person_titles&person=90&media=movie")
    films = [i for i in Directory.items if not i[2]]
    assert len(films) == 20 and films[0][1].label == "Film 25"  # most popular first
    assert "page=2" in Directory.items[-1][0]
    call("?action=person_titles&person=90&media=movie&page=2")
    assert len(Directory.items) == 5


def test_director_page_uses_their_department(ready):
    call("?action=person&person=91")
    assert labels() == ["Films (1)"]
    call("?action=person_titles&person=91&media=movie")
    assert labels() == ["Film 4"]


# -- home menu and tools ---------------------------------------------------------------------
def test_home_menu_can_be_reordered_and_hidden(ready):
    # Pick "TV shows" -> Hide; pick "Search" -> Move up; then back out.
    FakeDialog.script = [1, 2, 2, 0, -1]
    call("?action=home_menu_edit")
    call("")
    assert labels() == ["Films", "Search", "Tools"]
    FakeDialog.script = [4, -1]  # Reset to default
    call("?action=home_menu_edit")
    call("")
    assert labels() == ["Films", "TV shows", "Search", "Tools"]


def test_tools_cannot_be_hidden(ready):
    FakeDialog.script = [3, 2, -1]  # Tools -> third action doesn't exist
    call("?action=home_menu_edit")
    call("")
    assert "Tools" in labels()


def test_tools_are_grouped_and_clear_all_clears_everything(ready):
    call("?action=tools")
    assert labels() == ["Accounts and API keys", "Caches", "Customise home menu", "Clean install", "Settings"]
    call("?action=tools_caches")
    assert labels() == ["Clear cache", "Clear search history", "Clear all caches"]
    s = store()
    s.cache_set("x", 1, 100)
    s.add_search("all", "q")
    s.close()
    call("?action=clear_all")
    s = store()
    assert s.cache_get("x") is None and s.searches("all") == []
    assert ("notification", "All caches cleared") in FakeDialog.shown


def test_play_is_not_available_yet(ready):
    call("?action=play&media=movie&tmdb_id=1")
    assert Directory.resolved is False
    assert ("notification", "Playback arrives in a later test build") in FakeDialog.shown


def test_advanced_artwork_sizes(ready):
    FakeAddon.settings.update({"artwork.preset": 3, "artwork.poster_size": 0, "artwork.fanart_size": 2,
                               "artwork.still_size": 1, "artwork.extras": False})
    preset = context.App().preset
    assert preset == {"name": "advanced", "poster": "w342", "fanart": "original", "still": "original", "extras": False}


def test_no_key_in_zip():
    import zipfile
    from tools import build
    out = build.main()
    with zipfile.ZipFile(out) as archive:
        assert not any(name.endswith("_keys.json") for name in archive.namelist())


def test_store_is_shared(tmp_path):
    s = Store(str(tmp_path / "x.db"))
    options.save_home_layout(s, ["search", "movies"], {"tv"})
    order, hidden_items = options.home_layout(s)
    assert order == ["search", "movies", "tv", "tools"] and hidden_items == {"tv"}
