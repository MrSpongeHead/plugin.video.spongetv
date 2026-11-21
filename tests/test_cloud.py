# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Release 2, stage 3: your Premiumize cloud and the tidy-up."""

import pytest

from conftest import Directory, FakeAddon, FakeDialog
from resources.lib import caching, context
from resources.lib.http import Response
from resources.lib.premiumize import Premiumize
from test_menus import call
from test_premiumize import FakePm

DAY = 86400
NOW = 1_800_000_000


class CloudPm(FakePm):
    def __init__(self):
        super().__init__()
        self.folders = {
            None: [{"id": "sp", "name": "SpongeTV", "type": "folder", "created_at": NOW - 100 * DAY},
                   {"id": "mine", "name": "My stuff", "type": "folder", "created_at": NOW - 400 * DAY},
                   {"id": "f-root", "name": "Home.Video.mkv", "type": "file", "size": 2 * 1024 ** 3,
                    "created_at": NOW - 400 * DAY}],
            "sp": [{"id": "old-film", "name": "Old.Film.mkv", "type": "file", "size": 4 * 1024 ** 3,
                    "created_at": NOW - 45 * DAY},
                   {"id": "old-pack", "name": "Show.S01", "type": "folder", "created_at": NOW - 31 * DAY},
                   {"id": "new-film", "name": "New.Film.mkv", "type": "file", "size": 3 * 1024 ** 3,
                    "created_at": NOW - 2 * DAY}],
            "mine": [{"id": "keep", "name": "Ancient.mkv", "type": "file", "size": 1, "created_at": NOW - 999 * DAY}],
        }
        self.transfer_list = [
            {"id": "t-old", "name": "Old.Film.mkv", "status": "finished", "folder_id": "sp"},
            {"id": "t-pack", "name": "Show.S01", "status": "seeding", "folder_id": "old-pack"},
            {"id": "t-mine", "name": "Mine", "status": "finished", "folder_id": "mine"},
            {"id": "t-running", "name": "Going", "status": "running", "folder_id": None},
        ]
        self.deleted = []

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        path = url.rsplit("/api/", 1)[-1]
        ok = {"status": "success"}
        if path == "folder/list":
            fid = (params or {}).get("id")
            return Response(200, dict(ok, name={"sp": "SpongeTV"}.get(fid, ""), content=self.folders.get(fid, [])), {})
        if path == "item/listall":
            return Response(200, dict(ok, files=[
                {"id": "f-root", "path": "Home.Video.mkv", "size": 2 * 1024 ** 3},
                {"id": "old-film", "path": "SpongeTV/Old.Film.mkv", "size": 4 * 1024 ** 3},
                {"id": "e1", "path": "SpongeTV/Show.S01/Show.S01E01.mkv", "size": 1024 ** 3},
                {"id": "keep", "path": "My stuff/Ancient.mkv", "size": 1}]), {})
        if path == "transfer/list":
            return Response(200, dict(ok, transfers=self.transfer_list), {})
        if path in ("item/delete", "folder/delete", "transfer/delete"):
            self.deleted.append((path, form["id"]))
            return Response(200, ok, {})
        return super().send(method, url, params, json_body, headers, max_wait, form)


@pytest.fixture
def pm(monkeypatch):
    fake = CloudPm()
    monkeypatch.setattr(context.App, "premiumize", property(lambda app: Premiumize(fake, "good", app.store,
                                                                                    clock=lambda: NOW)))
    FakeAddon.settings.update({"premiumize.api_key": "good"})
    return fake


def _labels():
    return [li.getLabel() for _, li, _ in Directory.items]


def test_the_top_of_your_cloud_with_the_space_used(pm):
    call("?action=pm_folder")
    assert _labels() == ["Space used: 7.0 GB · SpongeTV folder: 5.0 GB", "My stuff", "SpongeTV", "Home.Video.mkv"]
    menus = [li.context_menu for _, li, _ in Directory.items[1:]]
    assert all(m[0][0] == "Delete" for m in menus)
    assert "kind=folder" in menus[0][0][1] and "kind=file" in menus[2][0][1]
    call("?action=pm_folder&id=sp")                          # inside a folder: no space line
    assert _labels() == ["Show.S01", "New.Film.mkv", "Old.Film.mkv"]


def test_deleting_asks_first(pm):
    FakeDialog.script = [False]
    call("?action=pm_remove&id=old-film&kind=file&name=Old.Film.mkv")
    assert pm.deleted == []
    FakeDialog.script = [True]
    call("?action=pm_remove&id=old-film&kind=file&name=Old.Film.mkv")
    assert pm.deleted == [("item/delete", "old-film")]
    asked = [m for k, m in FakeDialog.shown if k == "yesno"]
    assert "Delete Old.Film.mkv from your Premiumize cloud?" in asked[-1]
    # deleting the SpongeTV folder itself: SpongeTV forgets it, and makes a new one when next needed
    app = context.App()
    app.store.cache_set("premiumize:spongetv_folder", "sp", 3600)
    FakeDialog.script = [True]
    call("?action=pm_remove&id=sp&kind=folder&name=SpongeTV")
    assert ("folder/delete", "sp") in pm.deleted
    assert context.App().store.cache_get("premiumize:spongetv_folder") is None


def test_tidy_only_touches_old_things_in_the_spongetv_folder(pm):
    app = context.App()
    assert caching.tidy(app, now=NOW, days=30) == 2
    assert sorted(pm.deleted) == [("folder/delete", "old-pack"), ("item/delete", "old-film"),
                                  ("transfer/delete", "t-old"), ("transfer/delete", "t-pack")]
    # nothing outside the folder: "mine" (999 days old) and its transfer, the running transfer, the new film
    pm.deleted.clear()
    assert caching.tidy(app, now=NOW, days=90) == 0
    assert all(kind == "transfer/delete" for kind, _ in pm.deleted)


def test_no_spongetv_folder_no_tidy(pm):
    pm.folders[None] = [f for f in pm.folders[None] if f["id"] != "sp"]
    assert caching.tidy(context.App(), now=NOW, days=7) == 0
    assert pm.deleted == []


def test_daily_tidy_only_when_on_and_once_a_day(pm):
    app = context.App()
    FakeAddon.settings.update({"premiumize.tidy": False, "premiumize.tidy_days": 2})
    assert caching.daily_tidy(app, now=NOW) is None and pm.deleted == []
    FakeAddon.settings["premiumize.tidy"] = True
    assert caching.daily_tidy(app, now=NOW) == 2              # 30 days: the film and the pack
    assert ("notification", "Tidy-up: 2 old downloads deleted from the SpongeTV folder") in FakeDialog.shown
    assert caching.daily_tidy(app, now=NOW + 3600) is None    # not again the same day
    assert caching.daily_tidy(app, now=NOW + DAY + 1) is not None
    FakeAddon.settings["premiumize.tidy_days"] = 0
    assert caching.tidy_days() == 7


def test_only_the_details_line_scrolls():
    import os
    from conftest import ROOT
    xml = open(os.path.join(ROOT, "resources", "skins", "Default", "1080i", "spongetv-sourceselect.xml")).read()
    focused = xml[xml.index("<focusedlayout"):]
    assert "<label>$INFO[ListItem.Label2]</label>\n                    <scroll>true</scroll>" in focused
    assert "<label>$INFO[ListItem.Label]</label>\n                    <scroll>" not in focused


def test_last_tidy_line_and_one_download_in_the_singular(pm):
    import datetime
    app = context.App()
    FakeAddon.settings.update({"premiumize.tidy": True, "premiumize.tidy_days": 2})
    call("?action=pm_menu")
    assert _labels()[-2] == "Last tidy-up: not run yet"
    pm.folders["sp"] = [f for f in pm.folders["sp"] if f["id"] != "old-pack"]     # only the film is old
    assert caching.daily_tidy(app, now=NOW) == 1
    assert ("notification", "Tidy-up: 1 old download deleted from the SpongeTV folder") in FakeDialog.shown
    call("?action=pm_menu")
    when = datetime.datetime.fromtimestamp(NOW)
    assert _labels()[-2] == f"Last tidy-up: {when.day} {when:%B} {when.year}, {when:%H:%M} · 1 deleted"
    # nothing to delete the next day: still recorded
    pm.folders["sp"] = [f for f in pm.folders["sp"] if f["id"] != "old-film"]     # it went yesterday
    caching.daily_tidy(app, now=NOW + DAY + 1)
    call("?action=pm_menu")
    assert _labels()[-2].endswith("· 0 deleted")
    FakeAddon.settings["premiumize.tidy"] = False
    call("?action=pm_menu")
    assert not any(label.startswith("Last tidy-up") for label in _labels())


def test_tidy_up_now(pm, monkeypatch):
    monkeypatch.setattr(caching.time, "time", lambda: NOW)
    FakeAddon.settings.update({"premiumize.tidy": True, "premiumize.tidy_days": 2})
    app = context.App()
    app.store.set_meta("premiumize:last_tidy", str(NOW))      # the daily run has just happened
    call("?action=pm_menu")
    assert _labels()[-2:] == ["Last tidy-up: not run yet", "Tidy up now"]
    FakeDialog.script = [False]
    call("?action=pm_tidy_now")
    assert pm.deleted == []
    FakeDialog.script = [True]
    call("?action=pm_tidy_now")
    asked = [m for k, m in FakeDialog.shown if k == "yesno"]
    assert "older than 30 days, now?" in asked[-1]
    assert ("folder/delete", "old-pack") in pm.deleted and ("item/delete", "old-film") in pm.deleted
    assert ("notification", "Tidy-up: 2 old downloads deleted from the SpongeTV folder") in FakeDialog.shown
    assert context.App().store.get_meta("premiumize:last_tidy") == str(NOW)   # the daily timing is left alone
    call("?action=pm_menu")
    assert _labels()[-2].endswith("· 2 deleted")
    # nothing old enough: says so
    pm.folders["sp"] = [f for f in pm.folders["sp"] if f["id"] == "new-film"]
    FakeDialog.script = [True]
    call("?action=pm_tidy_now")
    assert ("notification", "Tidy-up: nothing in the SpongeTV folder is older than 30 days") in FakeDialog.shown
    FakeAddon.settings["premiumize.tidy"] = False
    call("?action=pm_menu")
    assert "Tidy up now" not in _labels()
