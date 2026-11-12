# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""1.0.6: what makes Next up and the other long lists quicker."""

import datetime

import pytest

from conftest import FakeAddon
from resources.lib import kodi
from resources.lib.database import Store
from resources.lib.http import HttpError
from resources.lib.tmdb import DAY, Tmdb
from test_metadata import FakeHttp

SHOW = {"id": 9, "name": "Ended", "in_production": False, "overview": "x", "tagline": "y", "last_air_date": "2020-01-01",
        "last_episode_to_air": {"season_number": 2, "episode_number": 4, "name": "End", "overview": "long"},
        "seasons": [{"season_number": 1, "episode_count": 8, "overview": "long"},
                    {"season_number": 2, "episode_count": 4}], "credits": {"cast": list(range(50))}}


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def make(tmp_path, responses):
    clock = Clock()
    store = Store(str(tmp_path / "c.db"), clock=clock)
    http = FakeHttp(responses)
    return Tmdb("key", http, store, language="en-GB", today=lambda: datetime.date(2026, 1, 1)), http, store, clock


def test_settings_handle_is_shared_briefly(monkeypatch):
    opened = []
    real = kodi.xbmcaddon.Addon

    def counting(*args):
        opened.append(1)
        return real(*args)
    monkeypatch.setattr(kodi.xbmcaddon, "Addon", counting)
    monkeypatch.setattr(kodi, "_handle", (None, 0.0))
    FakeAddon.settings["play.next"] = True
    for _ in range(50):
        assert kodi.setting_bool("play.next")
    assert len(opened) == 1                                  # one handle for the whole list
    kodi.set_setting_bool("play.next", False)
    assert kodi.setting_bool("play.next") is False and len(opened) == 2     # a write: the next read opens a new one
    handle, at = kodi._handle
    monkeypatch.setattr(kodi, "_handle", (handle, at - kodi.HANDLE_KEPT_FOR - 1))
    kodi.setting_bool("play.next")
    assert len(opened) == 3                                  # and it's never kept for long
    monkeypatch.setattr(kodi, "ALWAYS_FRESH", True)          # the background service
    kodi.setting_bool("play.next")
    kodi.setting_bool("play.next")
    assert len(opened) == 5


def test_not_found_is_remembered_for_a_day(tmp_path):
    tmdb, http, store, clock = make(tmp_path, {})
    for _ in range(3):
        with pytest.raises(HttpError) as raised:
            tmdb.tv(317805)
        assert raised.value.status == 404
    assert len(http.calls) == 1
    clock.now += DAY + 1
    with pytest.raises(HttpError):
        tmdb.tv(317805)
    assert len(http.calls) == 2                              # asked again the next day


def test_other_failures_are_not_remembered(tmp_path):
    tmdb, http, store, clock = make(tmp_path, {})

    def offline(url, params=None, headers=None):
        http.calls.append(url)
        raise HttpError("Network error")
    http.get_json = offline
    for _ in range(2):
        with pytest.raises(HttpError):
            tmdb.tv(1)
    assert len(http.calls) == 2


def test_show_facts_are_small_and_last_as_long_as_the_details(tmp_path):
    tmdb, http, store, clock = make(tmp_path, {"/tv/9": SHOW})
    facts = tmdb.tv_facts(9)
    assert facts == {"id": 9, "name": "Ended", "last_air_date": "2020-01-01",
                     "last_episode_to_air": {"season_number": 2, "episode_number": 4},
                     "seasons": [{"season_number": 1, "episode_count": 8}, {"season_number": 2, "episode_count": 4}]}
    from resources.lib.marks import aired_counts
    assert aired_counts(facts) == aired_counts(SHOW) == {1: 8, 2: 4}
    reads = []
    real = store.cache_get
    store.cache_get = lambda key: (reads.append(key), real(key))[1]
    assert tmdb.tv_facts(9) == facts and reads == ["tmdb:facts:en-GB:9"]      # the full details aren't read again
    assert store.cache_time_left("tmdb:facts:en-GB:9") == pytest.approx(14 * DAY)   # an ended show: 14 days, as its details
    clock.now += 14 * DAY + 1
    assert store.cache_get("tmdb:facts:en-GB:9") is None
    tmdb.tv_facts(9)
    assert len(http.calls) == 2                              # both expired together and were fetched again
    tmdb.forget_tv(9)
    assert store.cache_get("tmdb:facts:en-GB:9") is None


def test_long_kept_titles_are_written_once_and_do_expire(tmp_path):
    tmdb, http, store, clock = make(tmp_path, {"/tv/9": SHOW})
    writes = []
    real = store.cache_set
    store.cache_set = lambda key, value, ttl: (writes.append(ttl), real(key, value, ttl))[1]
    tmdb.tv(9)
    assert writes == [DAY, 14 * DAY]
    for _ in range(5):
        clock.now += DAY
        tmdb.tv(9)
    assert writes == [DAY, 14 * DAY]                         # reading it doesn't rewrite it or push its expiry back
    clock.now += 10 * DAY
    tmdb.tv(9)
    assert len(http.calls) == 2                              # so after 14 days it's fetched afresh
