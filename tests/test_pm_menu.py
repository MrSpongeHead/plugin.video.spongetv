# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Release 2, stage 1: Tools > Premiumize, with the account line and your transfers."""

import pytest

from conftest import Directory, FakeAddon, FakeDialog
from resources.lib import context
from resources.lib.http import Response
from resources.lib.premiumize import Premiumize
from test_menus import call
from test_premiumize import FakePm

TRANSFERS = [
    {"id": "t1", "name": "Show.S01E01.mkv", "status": "running", "progress": 0.42, "message": "12.3 MB/s from 9 peers",
     "folder_id": None, "file_id": None, "created_at": 1700000000},
    {"id": "t2", "name": "Film.2024.mkv", "status": "finished", "progress": 1.0, "message": "",
     "folder_id": "f1", "file_id": "file9", "created_at": 1700000000},
    {"id": "t3", "name": "Show.S02.Pack", "status": "seeding", "progress": 1.0, "message": "",
     "folder_id": "f2", "file_id": None, "created_at": 1700000000},
    {"id": "t4", "name": "Broken.Thing", "status": "error", "progress": 0.0, "message": "Not enough seeders",
     "folder_id": None, "file_id": None, "created_at": 1700000000},
]


class TransfersPm(FakePm):
    def __init__(self):
        super().__init__()
        self.transfer_list = [dict(t) for t in TRANSFERS]

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        path = url.rsplit("/api/", 1)[-1]
        if path == "transfer/list":
            self.calls.append((method, path, form))
            return Response(200, {"status": "success", "transfers": self.transfer_list}, {})
        if path in ("transfer/delete", "transfer/retry"):
            self.calls.append((method, path, form))
            if form["id"] == "gone":
                return Response(200, {"status": "error", "message": "Transfer not found", "code": "not_found"}, {})
            return Response(200, {"status": "success"}, {})
        if path == "transfer/clearfinished":
            self.calls.append((method, path, form))
            return Response(200, {"status": "error", "message": "Limit", "code": "account_limit_reached"}, {}) \
                if getattr(self, "limited", False) else Response(200, {"status": "success"}, {})
        if path == "folder/list":
            self.calls.append((method, path, params))
            return Response(200, {"status": "success", "name": "Show.S02.Pack", "content": [
                {"id": "e2", "name": "Show.S02E02.mkv", "type": "file", "size": 734003200},
                {"id": "sub", "name": "Show.S02E01.srt", "type": "file", "size": 1000},
                {"id": "e1", "name": "Show.S02E01.mkv", "type": "file", "size": 734003200},
                {"id": "x", "name": "Extras", "type": "folder"}]}, {})
        return super().send(method, url, params, json_body, headers, max_wait, form)


@pytest.fixture
def pm(monkeypatch):
    fake = TransfersPm()
    monkeypatch.setattr(context.App, "premiumize", property(lambda app: Premiumize(fake, "good", app.store,
                                                                                    clock=lambda: 1000)))
    FakeAddon.settings["premiumize.api_key"] = "good"
    return fake


def _labels():
    return [li.getLabel() for _, li, _ in Directory.items]


def test_tools_has_premiumize_with_the_account_line(pm):
    call("?action=tools")
    assert "Premiumize" in _labels()
    call("?action=pm_menu")
    assert _labels() == ["Premium for 30 more days · fair use 25% used", "Transfers", "My Premiumize cloud"]


def test_transfers_list(pm):
    call("?action=pm_transfers")
    assert _labels() == ["Downloading 42% · Show.S01E01.mkv", "Finished · Film.2024.mkv",
                         "Finished · Show.S02.Pack", "Failed · Broken.Thing"]
    urls = [url for url, _, _ in Directory.items]
    folders = [is_folder for _, _, is_folder in Directory.items]
    assert "action=pm_play" in urls[1] and "id=file9" in urls[1]          # one file: plays
    assert "action=pm_folder" in urls[2] and folders[2]                    # a pack: opens its folder
    assert "action=pm_refresh" in urls[0] and "action=pm_refresh" in urls[3]
    menus = [[label for label, _ in li.context_menu] for _, li, _ in Directory.items]
    assert menus[3] == ["Retry", "Delete transfer", "Clear finished transfers", "Refresh"]
    assert menus[0] == ["Delete transfer", "Clear finished transfers", "Refresh"]
    assert Directory.items[0][1].tag.calls["setPlot"][-1][0] == "12.3 MB/s from 9 peers"


def test_a_folder_lists_subfolders_then_videos(pm):
    call("?action=pm_folder&id=f2")
    assert _labels() == ["Extras", "Show.S02E01.mkv", "Show.S02E02.mkv"]   # no subtitles
    assert Directory.items[1][1].tag.calls["setPlot"][-1][0] == "700.0 MB"


def test_play_a_cloud_file(pm):
    call("?action=pm_play&id=file9")
    assert Directory.resolved is True


def test_retry_delete_and_clear(pm):
    call("?action=pm_retry&id=t4")
    assert ("POST", "transfer/retry", {"id": "t4"}) in pm.calls
    assert ("notification", "Transfer restarted") in FakeDialog.shown
    # deleting something still downloading asks first
    FakeDialog.script = [False]
    call("?action=pm_delete&id=t1&status=running&name=Show.S01E01.mkv")
    assert not any(c[1] == "transfer/delete" for c in pm.calls)
    FakeDialog.script = [True]
    call("?action=pm_delete&id=t1&status=running&name=Show.S01E01.mkv")
    assert ("POST", "transfer/delete", {"id": "t1"}) in pm.calls
    call("?action=pm_delete&id=t2&status=finished")                      # finished: no question
    assert ("POST", "transfer/delete", {"id": "t2"}) in pm.calls
    call("?action=pm_clear")
    assert ("notification", "Finished transfers cleared") in FakeDialog.shown


def test_premiumize_errors_are_explained(pm):
    call("?action=pm_delete&id=gone&status=finished")
    assert ("notification", "Transfer not found") in FakeDialog.shown
    pm.limited = True
    call("?action=pm_clear")
    assert ("notification", "Premiumize says your fair-use points or download slots have run out.") in FakeDialog.shown


def test_not_signed_in(monkeypatch):
    FakeAddon.settings["premiumize.api_key"] = ""
    call("?action=pm_menu")
    assert _labels() == ["Sign in to Premiumize"]


class RefusingPm(TransfersPm):
    refusing = True

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        if self.refusing and "/api/" in url:
            return Response(401, {"status": "error", "message": "Not logged in."}, {})
        return super().send(method, url, params, json_body, headers, max_wait, form)


def test_a_refused_sign_in_offers_sign_in_again_everywhere(monkeypatch):
    import json
    from resources.lib import accounts
    fake = RefusingPm()
    monkeypatch.setattr(context.App, "premiumize", property(lambda app: Premiumize(
        fake, "good", app.store, clock=lambda: 1000, on_answer=accounts.premiumize_answered)))
    FakeAddon.settings.update({"premiumize.token": json.dumps({"access_token": "old-token", "expires_at": 10 ** 10}),
                               "premiumize.api_key": "", "premiumize.status": "Premium for 30 more days"})
    call("?action=pm_menu")
    labels = _labels()
    assert labels[0] == "Sign in to Premiumize again"
    assert labels[1] == "Premiumize didn't accept SpongeTV's sign-in or API key. Sign in again in Tools, Accounts and API keys."
    assert FakeAddon.settings["premiumize.refused"] is True
    assert FakeAddon.settings["premiumize.status"] == "Sign-in no longer accepted"
    assert FakeAddon.settings.get("premiumize.signed_in", False) is False   # Settings shows its Sign in button
    call("?action=tools_accounts")
    assert "Sign in to Premiumize again" in _labels() and "Sign out of Premiumize" in _labels()
    # Premiumize accepts it again (or a new sign-in): back to normal
    fake.refusing = False
    call("?action=pm_menu")
    assert _labels()[0].startswith("Premium for")
    assert FakeAddon.settings["premiumize.refused"] is False
    assert FakeAddon.settings["premiumize.signed_in"] is True
    assert FakeAddon.settings["premiumize.status"] != "Sign-in no longer accepted"
