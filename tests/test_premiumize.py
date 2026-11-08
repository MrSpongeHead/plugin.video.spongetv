# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Premiumize with an API key, against recorded-style responses."""

import pytest

from resources.lib.database import Store
from resources.lib.http import HttpError, Response
from resources.lib.premiumize import Premiumize, PremiumizeError, cache_item, episode_pattern, pick_file
from resources.lib.sources import normalise

API = "https://www.premiumize.me/api/"


class FakePm:
    """Answers like Premiumize: business errors come back as HTTP 200 with status "error"."""

    def __init__(self, key="good"):
        self.key = key
        self.calls = []
        self.cached = {}
        self.transfers = {}
        self.files = []
        self.down = False

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        path = url.replace(API, "")
        self.calls.append((method, path, form))
        if self.down:
            raise HttpError("Network error")
        if headers.get("Authorization") != f"Bearer {self.key}":
            return Response(200, {"status": "error", "message": "Not logged in.", "code": "auth_required"}, {})
        if path == "account/info":
            return Response(200, {"status": "success", "customer_id": 42, "premium_until": 1000 + 30 * 86400,
                                  "limit_used": 0.25}, {})
        if path == "cache/check":
            items = [v for k, v in form if k == "items[]"]
            return Response(200, {"status": "success", "response": [self.cached.get(i, False) for i in items],
                                  "filename": ["" for _ in items], "filesize": ["" for _ in items]}, {})
        if path == "services/list":
            return Response(200, {"status": "success", "directdl": ["rapidgator.net"], "cache": ["1fichier.com"],
                                  "aliases": {"rapidgator.net": ["rg.to"]}}, {})
        if path == "transfer/directdl":
            if form["src"] not in self.transfers:
                return Response(200, {"status": "error", "message": "Not cached", "code": "not_cached"}, {})
            return Response(200, {"status": "success", "content": self.transfers[form["src"]]}, {})
        if path == "item/listall":
            return Response(200, {"status": "success", "files": self.files}, {})
        if path == "item/details":
            return Response(200, {"status": "success", "id": params["id"], "link": f"https://dl/{params['id']}"}, {})
        return Response(404, None, {})


def pm(fake=None, key="good", store=None):
    return Premiumize(fake or FakePm(), key, store=store, clock=lambda: 1000)


def torrent(title, h):
    return normalise({"hash": h, "release_title": title, "size": 1000}, {"name": "p", "package": "P"}, "torrent")


def test_account_and_days_left():
    client = pm()
    account = client.account()
    assert account["limit_used"] == 0.25 and client.days_left(account) == 30
    assert client.days_left({"premium_until": None}) is None


def test_missing_or_wrong_key():
    with pytest.raises(PremiumizeError) as error:
        pm(key="").account()
    assert error.value.kind == "no_key"
    with pytest.raises(PremiumizeError) as error:
        pm(key="wrong").account()
    assert error.value.kind == "bad_key"


def test_network_trouble_is_not_a_bad_key():
    fake = FakePm()
    fake.down = True
    with pytest.raises(PremiumizeError) as error:
        pm(fake).account()
    assert error.value.kind == "unreachable"


def test_cache_check_in_batches_and_mark_ready(tmp_path):
    fake = FakePm()
    sources = [torrent(f"Film.1080p.{i}", f"{i:040x}") for i in range(150)]
    fake.cached = {f"magnet:?xt=urn:btih:{i:040x}": i % 2 == 0 for i in range(150)}
    hoster = normalise({"url": "https://rg.to/file/abc", "release_title": "Film.720p", "host": "rg.to"},
                       {"name": "h", "package": "P"}, "hosters")
    unsupported = normalise({"url": "https://nowhere.example/x", "release_title": "Film.720p"},
                            {"name": "h", "package": "P"}, "hosters")
    fake.cached["https://rg.to/file/abc"] = True
    store = Store(str(tmp_path / "t.db"))
    pm(fake, store=store).mark_ready(sources + [hoster, unsupported])
    assert sum(1 for c in fake.calls if c[1] == "cache/check") == 2
    assert sources[0]["debrid"] == "cached" and sources[1]["debrid"] == "uncached"
    assert hoster["debrid"] == "cached" and not unsupported.get("debrid")
    pm(fake, store=store).hosts()
    assert sum(1 for c in fake.calls if c[1] == "services/list") == 1     # hosts kept for a day
    store.close()


def test_cache_item():
    assert cache_item(torrent("x", "ab" * 20)) == "magnet:?xt=urn:btih:" + "ab" * 20


@pytest.mark.parametrize("name, season, episode, hit", [
    ("Show.S02E03.1080p.mkv", 2, 3, True), ("Show.s2e3.mkv", 2, 3, True), ("Show.2x03.mkv", 2, 3, True),
    ("Show.S02E13.mkv", 2, 3, False), ("Show.S12E03.mkv", 2, 3, False), ("Show Season 2 Episode 3.mkv", 2, 3, True),
])
def test_episode_pattern(name, season, episode, hit):
    assert bool(episode_pattern(season, episode).search(name)) is hit


def test_pick_file_from_a_season_pack():
    content = [{"path": "Pack/Show.S01E01.mkv", "size": 900, "link": "l1"},
               {"path": "Pack/Show.S01E02.mkv", "size": 800, "link": "l2"},
               {"path": "Pack/Sample/Show.S01E02.sample.mkv", "size": 50, "link": "s"},
               {"path": "Pack/Show.S01E02.nfo", "size": 1, "link": "n"}]
    assert pick_file(content, 1, 2)["link"] == "l2"
    assert pick_file(content, 1, 9) is None
    assert pick_file(content)["link"] == "l1"                     # a film: the largest video
    assert pick_file([{"path": "Odd name.mkv", "size": 5, "link": "x"}], 1, 2)["link"] == "x"


def test_resolve():
    fake = FakePm()
    source = torrent("Show.S01.1080p", "cd" * 20)
    fake.transfers[f"magnet:?xt=urn:btih:{'cd' * 20}"] = [{"path": "Show.S01E04.mkv", "size": 10, "link": "ep4"}]
    assert pm(fake).resolve(source, 1, 4) == "ep4"
    with pytest.raises(PremiumizeError) as error:
        pm(fake).resolve(source, 1, 5)
    assert error.value.kind == "no_file"
    with pytest.raises(PremiumizeError) as error:
        pm(fake).resolve(torrent("Other", "ef" * 20))
    assert error.value.kind == "failed"


def test_cloud_search():
    fake = FakePm()
    fake.files = [{"id": "a", "name": "The.Lighthouse.Keeper.2024.1080p.mkv", "path": "The.Lighthouse.Keeper.2024.1080p.mkv",
                   "size": 5},
                  {"id": "b", "name": "The.Lighthouse.Keeper.2019.mkv", "path": "The.Lighthouse.Keeper.2019.mkv", "size": 5},
                  {"id": "c", "name": "Show.S01E02.mkv", "path": "Show/Show.S01E02.mkv", "size": 5}]
    films = pm(fake).cloud_search({"simple_info": {"title": "The Lighthouse Keeper", "year": "2024"}})
    assert [f["id"] for f in films] == ["a"]
    episodes = pm(fake).cloud_search({"simple_info": {"show_title": "Show", "season_number": "1",
                                                      "episode_number": "2"}})
    assert [f["id"] for f in episodes] == ["c"]
    assert pm(fake).cloud_link("c") == "https://dl/c"


def test_daily_expiry_warning(tmp_path, monkeypatch):
    from conftest import FakeAddon, FakeDialog
    from resources.lib import service
    fake = FakePm()
    store = Store(str(tmp_path / "t.db"))
    FakeAddon.settings["premiumize.api_key"] = "good"
    now = 1000 + 25 * 86400          # 5 days before premium_until
    assert service.check_premiumize(store, fake, now) == 5
    assert ("notification", "Your Premiumize account expires in 5 days") in FakeDialog.shown
    assert service.check_premiumize(store, fake, now + 60) is None    # once a day
    store.close()


# -- code sign-in ---------------------------------------------------------------------------------------
class FakeDevice:
    """Premiumize's /token: pending twice, asks to slow down once, then approves."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.forms = []

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        self.forms.append(form)
        if form.get("response_type") == "device_code":
            if form["client_id"] != "400":
                return Response(400, {"error": "invalid_client"}, {})
            return Response(200, {"device_code": "dev", "user_code": "ABCD-EFGH", "expires_in": 600, "interval": 5,
                                  "verification_uri": "https://www.premiumize.me/device"}, {})
        status, body = self.answers.pop(0)
        return Response(status, body, {})


def test_device_code_and_bad_client_id():
    from resources.lib.premiumize import device_code
    assert device_code(FakeDevice([]), "400")["user_code"] == "ABCD-EFGH"
    with pytest.raises(PremiumizeError) as error:
        device_code(FakeDevice([]), "999")
    assert error.value.kind == "bad_client_id"
    with pytest.raises(PremiumizeError) as error:
        device_code(FakeDevice([]), "")
    assert error.value.kind == "no_client_id"


def test_poll_waits_slows_down_then_signs_in():
    from resources.lib.premiumize import poll_device
    now = [1000.0]
    fake = FakeDevice([(400, {"error": "authorization_pending"}), (400, {"error": "slow_down"}),
                       (400, {"error": "authorization_pending"}),
                       (200, {"access_token": "tok", "token_type": "Bearer", "expires_in": 3600, "scope": "full"})])
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds
    token = poll_device(fake, "400", {"device_code": "dev", "interval": 5, "expires_in": 600},
                        sleep=sleep, clock=lambda: now[0])
    assert token["access_token"] == "tok" and token["expires_at"] == int(now[0]) + 3600
    assert sum(slept) == 5 + 5 + 10 + 10          # waited longer after "slow down"
    assert fake.forms[-1] == {"grant_type": "device_code", "code": "dev", "client_id": "400"}


def test_poll_refused_expired_and_cancelled():
    from resources.lib.premiumize import poll_device
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds
    code = {"device_code": "dev", "interval": 5, "expires_in": 600}
    with pytest.raises(PremiumizeError) as error:
        poll_device(FakeDevice([(400, {"error": "access_denied"})]), "400", code, sleep=sleep, clock=lambda: now[0])
    assert error.value.kind == "denied"
    assert poll_device(FakeDevice([(400, {"error": "invalid_grant"})]), "400", code, sleep=sleep,
                       clock=lambda: now[0]) is None
    assert poll_device(FakeDevice([]), "400", code, should_stop=lambda: True, sleep=sleep, clock=lambda: now[0]) is None


def test_sign_in_wins_over_api_key_and_sign_out(tmp_path, monkeypatch):
    import json
    from conftest import FakeAddon, FakeDialog
    from resources.lib import accounts, context, premiumize
    monkeypatch.setattr(context, "builtin_keys", lambda: {"premiumize": "400"})
    monkeypatch.setattr(premiumize, "device_code", lambda http, cid: {"device_code": "d", "user_code": "AB-CD"})
    monkeypatch.setattr(premiumize, "poll_device", lambda http, cid, code, should_stop: {"access_token": "tok",
                                                                                           "expires_at": None})
    FakeAddon.settings["premiumize.api_key"] = "key"
    app = context.App()
    assert app.premiumize_client_id == "400" and app.premiumize.api_key == "key"
    monkeypatch.setattr(premiumize.Premiumize, "account", lambda self: {"premium_until": None, "limit_used": 0})
    assert accounts.premiumize_sign_in(app)
    assert json.loads(FakeAddon.settings["premiumize.token"])["access_token"] == "tok"
    assert app.premiumize.api_key == "tok"          # the sign-in is used ahead of the API key
    FakeDialog.script = [True]
    assert accounts.premiumize_sign_out(app)
    assert app.premiumize.api_key == "key"


def test_daily_check_warns_before_the_sign_in_ends(tmp_path):
    import json
    from conftest import FakeAddon, FakeDialog
    from resources.lib import service
    store = Store(str(tmp_path / "t.db"))
    fake = FakePm(key="tok")
    now = 1000 + 25 * 86400
    FakeAddon.settings["premiumize.token"] = json.dumps({"access_token": "tok", "expires_at": now + 3 * 86400})
    service.check_premiumize(store, fake, now)
    assert ("notification", "Your Premiumize sign-in ends in 3 days. Sign in again in Tools, Accounts.") in FakeDialog.shown
    store.close()
