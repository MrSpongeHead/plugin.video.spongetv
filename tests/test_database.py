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


def test_clearing_or_trimming_the_cache_keeps_resume_points(tmp_path):
    clock = Clock()
    store = Store(str(tmp_path / "a.db"), clock=clock)
    store.resume_set("movie:7", {"position": 1200})   # the oldest entry
    clock.now += 10
    store.cache_set("tmdb:a", "y" * 100, 1000)
    clock.now += 10
    store.cache_set("tmdb:b", "z" * 100, 1000)
    store.cache_tidy(max_bytes=150)
    assert store.resume_get("movie:7") == {"position": 1200}   # not removed to fit, though oldest
    assert store.cache_get("tmdb:a") is None
    store.cache_clear()
    assert store.cache_get("tmdb:b") is None
    assert store.resume_get("movie:7") == {"position": 1200}


def test_upgrade_moves_resume_points_out_of_the_cache(tmp_path):
    """A 1.0.1 database (layout 3) keeps resume points in the cache as "resume:<key>": 1.0.2 moves them."""
    import json
    import sqlite3
    from resources.lib import database
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    for version in (1, 2, 3):
        for statement in database.MIGRATIONS[version]:
            db.execute(statement)
    db.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '3')")
    point = {"position": 1930.0, "total": 6000.0, "percent": 32.2, "saved": 1000.0}
    for key, value in (("resume:movie:7", point), ("resume:episode:50:1:2", {"position": 600}), ("tmdb:movie:7", "kept")):
        db.execute("INSERT INTO cache (key, value, expires, created, size) VALUES (?, ?, ?, ?, 1)",
                   (key, json.dumps(value), 10 ** 12, 1000.0))
    db.commit()
    db.close()
    store = Store(path, clock=Clock())
    assert store.schema_version() == database.SCHEMA_VERSION == 4
    assert store.resume_get("movie:7") == point
    assert store.resume_get("episode:50:1:2") == {"position": 600}
    assert store.cache_get("resume:movie:7") is None           # gone from the cache
    assert store.cache_get("tmdb:movie:7") == "kept"
    store.close()


def test_resume_points_are_forgotten_after_a_year(tmp_path):
    clock = Clock()
    store = Store(str(tmp_path / "a.db"), clock=clock)
    store.resume_set("movie:7", {"position": 1200})
    clock.now += 364 * 86400
    assert store.resume_get("movie:7") == {"position": 1200}
    clock.now += 2 * 86400
    assert store.resume_get("movie:7") is None
    store.resume_tidy()
    store.resume_set("movie:8", {"position": 5})
    store.resume_delete("movie:8")
    assert store.resume_get("movie:8") is None


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
