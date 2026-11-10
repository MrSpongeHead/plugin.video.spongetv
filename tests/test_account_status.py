# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""The status lines and buttons in Settings, Accounts."""

import json

from conftest import FakeAddon

from resources.lib import accounts


def settings(**values):
    FakeAddon.settings.clear()
    FakeAddon.settings.update(values)
    return FakeAddon.settings


def test_not_signed_in_shows_sign_in_buttons_only():
    s = settings()
    accounts.account_status()
    assert s["trakt.status"] == "Not signed in" and s.get("trakt.signed_in", False) is False
    assert s["premiumize.status"] == "Not signed in" and s.get("premiumize.signed_in", False) is False


def test_signed_in_to_both():
    s = settings(**{"trakt.token": json.dumps({"access_token": "a", "refresh_token": "r"}), "trakt.username": "Steven",
                    "premiumize.token": json.dumps({"access_token": "p"})})
    accounts.account_status(days=528)
    assert s["trakt.status"] == "Signed in as Steven" and s["trakt.signed_in"] is True
    assert s["premiumize.status"] == "Signed in: 528 days of premium left" and s["premiumize.signed_in"] is True
    accounts.account_status()                       # e.g. at start-up: keeps the days from the last check
    assert s["premiumize.status"] == "Signed in: 528 days of premium left"


def test_api_key_counts_as_signed_in_and_free_accounts_say_so():
    s = settings(**{"premiumize.api_key": " key "})
    accounts.account_status()
    assert s["premiumize.status"] == "Signed in" and s["premiumize.signed_in"] is True
    accounts.account_status(days=accounts.NO_PREMIUM)
    assert s["premiumize.status"] == "Signed in: no premium"


def test_signing_out_clears_the_days():
    s = settings(**{"premiumize.token": json.dumps({"access_token": "p"})})
    accounts.account_status(days=10)
    s["premiumize.token"] = ""
    accounts.account_status()
    assert s["premiumize.status"] == "Not signed in" and s.get("premiumize.signed_in", False) is False
    s["premiumize.token"] = json.dumps({"access_token": "q"})
    accounts.account_status()
    assert s["premiumize.status"] == "Signed in"     # not the old account's days


def test_only_changes_are_written(monkeypatch):
    settings()
    accounts.account_status()
    writes = []
    monkeypatch.setattr(accounts.kodi, "set_setting_str", lambda k, v: writes.append(k))
    monkeypatch.setattr(accounts.kodi, "set_setting_bool", lambda k, v: writes.append(k))
    accounts.account_status()
    assert writes == []      # each write makes Kodi tell the service settings changed
