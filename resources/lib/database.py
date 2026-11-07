# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""SpongeTV's local SQLite store: versioned layout, expiring cache and search history.

Each schema change is a new numbered migration, so an update upgrades the
database in place instead of wiping it.
"""

import json
import os
import sqlite3
import threading
import time

MIGRATIONS = {
    1: [
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
        "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
        "expires REAL NOT NULL, created REAL NOT NULL, size INTEGER NOT NULL)",
        "CREATE INDEX IF NOT EXISTS cache_expires ON cache (expires)",
        "CREATE TABLE IF NOT EXISTS search_history (kind TEXT NOT NULL, query TEXT NOT NULL, "
        "searched REAL NOT NULL, PRIMARY KEY (kind, query))",
    ],
}
SCHEMA_VERSION = max(MIGRATIONS)


class Store:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self._lock = threading.RLock()
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    # -- layout ---------------------------------------------------------------
    def _migrate(self):
        with self._lock, self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            current = int(self.get_meta("schema_version") or 0)
            for version in sorted(v for v in MIGRATIONS if v > current):
                for statement in MIGRATIONS[version]:
                    self._db.execute(statement)
                self._set_meta_unlocked("schema_version", str(version))

    def schema_version(self):
        return int(self.get_meta("schema_version") or 0)

    def get_meta(self, key, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        with self._lock, self._db:
            self._set_meta_unlocked(key, value)

    def _set_meta_unlocked(self, key, value):
        self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # -- cache ------------------------------------------------------------------
    def cache_get(self, key):
        with self._lock:
            row = self._db.execute("SELECT value, expires FROM cache WHERE key = ?", (key,)).fetchone()
        if not row or row[1] < self.clock():
            return None
        return json.loads(row[0])

    def cache_set(self, key, value, ttl_seconds):
        data = json.dumps(value, separators=(",", ":"))
        now = self.clock()
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires, created, size) VALUES (?, ?, ?, ?, ?)",
                (key, data, now + ttl_seconds, now, len(data)),
            )

    def cache_size(self):
        with self._lock:
            return self._db.execute("SELECT COALESCE(SUM(size), 0) FROM cache").fetchone()[0]

    def cache_tidy(self, max_bytes):
        """Drop expired entries, then the oldest ones until under max_bytes."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM cache WHERE expires < ?", (self.clock(),))
            total = self._db.execute("SELECT COALESCE(SUM(size), 0) FROM cache").fetchone()[0]
            if total <= max_bytes:
                return
            for key, size in self._db.execute("SELECT key, size FROM cache ORDER BY created").fetchall():
                self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
                total -= size
                if total <= max_bytes:
                    break

    def cache_clear(self):
        with self._lock, self._db:
            self._db.execute("DELETE FROM cache")

    # -- search history -----------------------------------------------------------
    def add_search(self, kind, query):
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO search_history (kind, query, searched) VALUES (?, ?, ?)",
                (kind, query, self.clock()),
            )

    def searches(self, kind, limit=20):
        with self._lock:
            rows = self._db.execute(
                "SELECT query FROM search_history WHERE kind = ? ORDER BY searched DESC LIMIT ?", (kind, limit)
            ).fetchall()
        return [row[0] for row in rows]

    def clear_searches(self):
        with self._lock, self._db:
            self._db.execute("DELETE FROM search_history")

    def close(self):
        with self._lock:
            self._db.close()
