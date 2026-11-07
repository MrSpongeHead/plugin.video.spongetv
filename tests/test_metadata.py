# SPDX-License-Identifier: GPL-3.0-or-later
import datetime

import pytest

from resources.lib import artwork
from resources.lib.database import Store
from resources.lib.extras import parse_omdb_ratings
from resources.lib.http import Http, HttpError
from resources.lib.tmdb import Tmdb, TmdbError, image_url


class FakeHttp:
    def __init__(self, responses):
        self.responses = responses  # path suffix -> data (or callable(params))
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        for suffix, data in self.responses.items():
            if url.endswith(suffix):
                return data(params) if callable(data) else data
        raise HttpError("not found", 404)


def test_needs_a_key():
    with pytest.raises(TmdbError):
        Tmdb("", FakeHttp({}))


def test_lists_send_language_region_and_cache(tmp_path):
    http = FakeHttp({"/movie/now_playing": {"page": 1, "total_pages": 3, "results": []}})
    tmdb = Tmdb("key", http, Store(str(tmp_path / "c.db")), language="en-GB", region="GB")
    tmdb.movie_list("now_playing", 1)
    tmdb.movie_list("now_playing", 1)
    assert len(http.calls) == 1, "second call should come from the cache"
    url, params = http.calls[0]
    assert params["region"] == "GB" and params["language"] == "en-GB" and params["api_key"] == "key"


def test_details_use_one_request_and_english_fallback():
    http = FakeHttp({
        "/movie/7": lambda p: {"id": 7, "title": "Titre", "overview": "" if p["language"] == "fr-FR" else "English plot",
                               "tagline": "", "release_date": "2024-05-01"},
    })
    tmdb = Tmdb("key", http, None, language="fr-FR", today=lambda: datetime.date(2026, 1, 1))
    data = tmdb.movie(7)
    assert data["overview"] == "English plot"
    first_params = http.calls[0][1]
    assert "credits" in first_params["append_to_response"] and "images" in first_params["append_to_response"]
    assert first_params["include_image_language"] == "fr,en,null"


def test_image_url():
    assert image_url("/a.jpg", "w780") == "https://image.tmdb.org/t/p/w780/a.jpg"
    assert image_url(None) == ""


def test_artwork_prefers_language_and_textless_fanart():
    details = {"images": {
        "posters": [{"file_path": "/de.jpg", "iso_639_1": "de", "vote_average": 9},
                    {"file_path": "/en.jpg", "iso_639_1": "en", "vote_average": 5}],
        "backdrops": [{"file_path": "/text.jpg", "iso_639_1": "en", "vote_average": 9},
                      {"file_path": "/plain.jpg", "iso_639_1": None, "vote_average": 4}],
        "logos": [{"file_path": "/logo.png", "iso_639_1": "en", "vote_average": 5}],
    }}
    art = artwork.for_title(details, preset=1, language="en-GB")
    assert art["poster"].endswith("w780/en.jpg")
    assert art["fanart"].endswith("w1280/plain.jpg")
    assert art["landscape"].endswith("/text.jpg")
    assert art["clearlogo"].endswith("/logo.png")
    minimal = artwork.for_title(details, preset=2, language="en-GB")
    assert "clearlogo" not in minimal


def test_fanart_tv_extras_fill_gaps():
    art = artwork.for_title({"poster_path": "/p.jpg"}, preset=0, language="en",
                            fanart_data={"hdmovieclearart": [{"url": "http://x/clear.png", "lang": "en", "likes": "3"}]})
    assert art["clearart"] == "http://x/clear.png"


def test_omdb_ratings_parse():
    ratings = parse_omdb_ratings({"imdbVotes": "12,345", "Ratings": [
        {"Source": "Internet Movie Database", "Value": "7.8/10"},
        {"Source": "Rotten Tomatoes", "Value": "91%"},
        {"Source": "Metacritic", "Value": "74/100"},
    ]})
    assert ratings["imdb"] == (7.8, 12345)
    assert ratings["tomatometerallcritics"] == (9.1, 0)
    assert ratings["metacritic"] == (7.4, 0)


def test_http_honours_retry_after(monkeypatch):
    waits = []

    class Response:
        def __init__(self, status, headers=None, data=None):
            self.status_code, self.headers, self._data = status, headers or {}, data

        def json(self):
            return self._data

    responses = [Response(429, {"Retry-After": "7"}), Response(200, data={"ok": True})]
    http = Http("SpongeTV/test", sleep=waits.append)
    monkeypatch.setattr(http.session, "get", lambda *a, **k: responses.pop(0))
    assert http.get_json("https://example.invalid") == {"ok": True}
    assert waits == [7]
    assert http.session.headers["User-Agent"] == "SpongeTV/test"
