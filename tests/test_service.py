# SPDX-License-Identifier: GPL-3.0-or-later
"""The background service checks API keys you change in Settings."""

from conftest import FakeAddon, FakeDialog
from resources.lib import service
from resources.lib.database import Store
from resources.lib.http import HttpError


class FakeHttp:
    def __init__(self, reachable=True):
        self.reachable = reachable
        self.calls = 0

    def get_json(self, url, params=None, headers=None):
        self.calls += 1
        if not self.reachable:
            raise HttpError("offline")
        if params.get("api_key") == "good" or params.get("apikey") == "good":
            return {}
        raise HttpError("Invalid", 401)


def test_changed_keys_are_checked_once(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    http = FakeHttp()
    FakeAddon.settings.update({"tmdb.api_key": "good", "fanart.api_key": "bad"})
    service.check_changed_keys(store, http)
    assert ("notification", "TMDB key accepted") in FakeDialog.shown
    assert ("notification", "Fanart.tv didn't accept that key. Check it and try again.") in FakeDialog.shown
    calls = http.calls
    service.check_changed_keys(store, http)  # nothing changed: no new checks
    assert http.calls == calls


def test_unreachable_service_is_checked_again_later(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    FakeAddon.settings["omdb.api_key"] = "good"
    service.check_changed_keys(store, FakeHttp(reachable=False))
    assert FakeDialog.shown == []
    service.check_changed_keys(store, FakeHttp())
    assert ("notification", "OMDb key accepted") in FakeDialog.shown


def test_service_starts_and_stops():
    service.run()  # the stand-in Monitor reports Kodi closing straight away
