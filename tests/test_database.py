# SPDX-License-Identifier: GPL-3.0-or-later
from resources.lib.database import SCHEMA_VERSION, Store


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_new_database_is_at_latest_version(tmp_path):
    store = Store(str(tmp_path / "a.db"))
    assert store.schema_version() == SCHEMA_VERSION


def test_reopening_keeps_data(tmp_path):
    path = str(tmp_path / "a.db")
    store = Store(path)
    store.set_meta("wizard_done", "1")
    store.close()
    assert Store(path).get_meta("wizard_done") == "1"


def test_cache_expires(tmp_path):
    clock = Clock()
    store = Store(str(tmp_path / "a.db"), clock=clock)
    store.cache_set("k", {"a": 1}, ttl_seconds=60)
    assert store.cache_get("k") == {"a": 1}
    clock.now += 61
    assert store.cache_get("k") is None


def test_tidy_removes_expired_then_oldest(tmp_path):
    clock = Clock()
    store = Store(str(tmp_path / "a.db"), clock=clock)
    store.cache_set("old", "x" * 100, 1)
    clock.now += 10
    store.cache_set("first", "y" * 100, 1000)
    clock.now += 10
    store.cache_set("second", "z" * 100, 1000)
    store.cache_tidy(max_bytes=150)
    assert store.cache_get("old") is None       # expired
    assert store.cache_get("first") is None     # oldest, removed to fit the limit
    assert store.cache_get("second") == "z" * 100


def test_search_history_newest_first(tmp_path):
    clock = Clock()
    store = Store(str(tmp_path / "a.db"), clock=clock)
    store.add_search("movie", "alpha")
    clock.now += 1
    store.add_search("movie", "beta")
    clock.now += 1
    store.add_search("movie", "alpha")  # searching again moves it to the top
    store.add_search("tv", "gamma")
    assert store.searches("movie") == ["alpha", "beta"]
    store.clear_searches()
    assert store.searches("movie") == []
