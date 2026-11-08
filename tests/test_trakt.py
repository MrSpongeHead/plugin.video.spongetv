# SPDX-License-Identifier: GPL-3.0-or-later
"""The Trakt client: sign-in, tokens, paging, rate limits and error handling."""

import pytest

from fake_trakt import FakeTrakt
from resources.lib.database import Store
from resources.lib.http import Http
from resources.lib.trakt import PAGE_LIMIT, READ_BUDGET, Trakt, TraktError


class MemoryTokens:
    def __init__(self, tokens=None):
        self.value = dict(tokens or {})

    def load(self):
        return dict(self.value)

    def save(self, tokens):
        self.value = dict(tokens)

    def clear(self):
        self.value = {}


class Clock:
    def __init__(self, now=1_000_000_000.0):
        self.now = now
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def server(monkeypatch):
    fake = FakeTrakt()
    monkeypatch.setattr(Http, "send", lambda self, *a, **k: fake(self, *a, **k))
    return fake


def client(tokens=None, secret="", store=None, clock=None):
    clock = clock or Clock()
    signed_in = {"access_token": "access-1", "refresh_token": "refresh-1", "expires_at": clock.now + 5 * 86400}
    return Trakt("client-id", Http("SpongeTV/test"), MemoryTokens(signed_in if tokens is None else tokens),
                 client_secret=secret, store=store, clock=clock, sleep=clock.sleep), clock


# -- sign-in -----------------------------------------------------------------------------------------
def test_device_sign_in_uses_auth_host_and_no_secret(server):
    server.device_statuses = [400, 400, 429, 200]
    trakt, clock = client(tokens={})
    code = trakt.device_code()
    assert code["user_code"] == "ABCD1234"
    assert trakt.poll_device(code) is True
    assert trakt.signed_in
    assert clock.slept == [5, 5, 5, 6]   # slowed down after the 429
    auth_calls = [c for c in server.calls if "auth.trakt.tv" in c[1]]
    assert len(auth_calls) == 5
    assert all("client_secret" not in (c[3] or {}) for c in auth_calls)
    assert auth_calls[1][3] == {"code": "dev", "client_id": "client-id"}


def test_secret_is_sent_when_you_have_one(server):
    trakt, _ = client(tokens={}, secret="shh")
    trakt.poll_device(trakt.device_code())
    assert server.calls[-1][3]["client_secret"] == "shh"


@pytest.mark.parametrize("status,kind", [(418, "sign_in_denied"), (410, "sign_in_expired"),
                                         (409, "sign_in_expired"), (403, "sign_in_limit"), (420, "sign_in_limit")])
def test_device_sign_in_failures(server, status, kind):
    server.device_statuses = [400, status]
    trakt, _ = client(tokens={})
    with pytest.raises(TraktError) as error:
        trakt.poll_device(trakt.device_code())
    assert error.value.kind == kind and not trakt.signed_in


def test_device_sign_in_can_be_cancelled(server):
    server.device_statuses = [400] * 10
    trakt, _ = client(tokens={})
    checks = iter([False, False, False, True])
    assert trakt.poll_device(trakt.device_code(), should_stop=lambda: next(checks)) is False


def test_device_code_expires(server):
    server.device_statuses = [400] * 500
    trakt, _ = client(tokens={})
    with pytest.raises(TraktError) as error:
        trakt.poll_device(trakt.device_code())
    assert error.value.kind == "sign_in_expired"


# -- tokens ---------------------------------------------------------------------------------------
def test_token_close_to_expiry_is_refreshed_first(server):
    clock = Clock()
    trakt, _ = client(tokens={"access_token": "access-1", "refresh_token": "refresh-1", "expires_at": clock.now + 3600},
                      clock=clock)
    trakt.get("/users/settings", auth=True)
    assert server.paths()[0] == ("POST", "/oauth/token")
    assert trakt.tokens.load()["access_token"] == "access-2"   # the new pair is saved straight away
    assert server.calls[0][3]["grant_type"] == "refresh_token"


def test_401_refreshes_once_and_retries(server):
    server.valid_tokens = {"other"}       # Trakt no longer accepts access-1
    trakt, _ = client()
    assert trakt.get("/users/settings", auth=True)["user"]["username"] == "sponge"
    assert [p for _, p in server.paths()] == ["/users/settings", "/oauth/token", "/users/settings"]


def test_signs_out_only_when_the_refresh_is_refused(server):
    server.valid_tokens = set()
    server.refresh_status = 400
    trakt, _ = client()
    with pytest.raises(TraktError) as error:
        trakt.get("/users/settings", auth=True)
    assert error.value.kind == "signed_out" and not trakt.signed_in


@pytest.mark.parametrize("status,kind", [(403, "forbidden"), (420, "account_limit"), (423, "locked"),
                                         (426, "vip"), (500, "unavailable"), (503, "unavailable")])
def test_other_errors_never_sign_you_out(server, status, kind):
    server.fail[("GET", "/sync/watchlist/movies")] = status
    trakt, _ = client()
    with pytest.raises(TraktError) as error:
        trakt.get("/sync/watchlist/movies", auth=True)
    assert error.value.kind == kind and trakt.signed_in


def test_network_failure_is_reported_not_signed_out(server):
    server.offline = True
    trakt, _ = client()
    with pytest.raises(TraktError) as error:
        trakt.get("/sync/last_activities", auth=True)
    assert error.value.kind == "network" and trakt.signed_in


def test_sign_out_revokes_and_forgets(server):
    trakt, _ = client()
    trakt.sign_out()
    assert ("POST", "/oauth/revoke") in server.paths() and not trakt.signed_in


# -- requests ------------------------------------------------------------------------------------------
def test_headers(server):
    trakt, _ = client()
    trakt.get("/users/settings", auth=True)
    headers = server.calls[-1][4]
    assert headers["trakt-api-version"] == "2" and headers["trakt-api-key"] == "client-id"
    assert headers["Authorization"] == "Bearer access-1"
    assert trakt.http.session.headers["User-Agent"] == "SpongeTV/test"


def test_paging_continues_until_an_empty_page(server):
    server.pages["/sync/watched/movies"] = [{"n": i} for i in range(PAGE_LIMIT * 2 + 7)]
    trakt, _ = client()
    items = trakt.get_all("/sync/watched/movies")
    assert len(items) == PAGE_LIMIT * 2 + 7
    pages = server.gets("/sync/watched/movies")
    assert [p["page"] for p in pages] == [1, 2, 3, 4] and all(p["limit"] == PAGE_LIMIT for p in pages)


def test_paging_stops_if_trakt_ignores_the_page_number(server):
    server.pages["/sync/playback/movies"] = [{"n": 1}, {"n": 2}]
    server.ignore_paging.add("/sync/playback/movies")
    trakt, _ = client()
    assert len(trakt.get_all("/sync/playback/movies")) == 2
    assert len(server.gets("/sync/playback/movies")) == 2


def test_reads_stay_within_the_budget(server):
    trakt, clock = client()
    for _ in range(READ_BUDGET + 1):
        trakt.get("/users/settings", auth=True)
    assert clock.slept and clock.slept[-1] > 200   # waited for the 5-minute window to move on


def test_writes_are_a_second_apart(server, tmp_path):
    store = Store(str(tmp_path / "t.db"))
    clock = Clock()
    trakt, _ = client(store=store, clock=clock)
    trakt.post("/sync/history", {"movies": []})
    trakt.post("/sync/history", {"movies": []})
    assert clock.slept == [1.0]


# -- scrobbling ------------------------------------------------------------------------------------------
def test_scrobbles_are_queued_offline_and_sent_later(server, tmp_path):
    store = Store(str(tmp_path / "t.db"))
    trakt, _ = client(store=store)
    server.offline = True
    trakt.scrobble("stop", {"movie": {"ids": {"tmdb": 7}}, "progress": 95})
    assert store.query("SELECT COUNT(*) FROM scrobble_queue")[0][0] == 1
    server.offline = False
    attempts_offline = len(server.calls)
    assert trakt.send_queued_scrobbles() == 1
    resent = [c for c in server.calls[attempts_offline:] if c[1].endswith("/scrobble/stop")]
    assert [c[3] for c in resent] == [{"movie": {"ids": {"tmdb": 7}}, "progress": 95}]
    assert store.query("SELECT COUNT(*) FROM scrobble_queue")[0][0] == 0


def test_already_scrobbled_is_not_an_error(server, tmp_path):
    server.fail[("POST", "/scrobble/stop")] = 409
    trakt, _ = client(store=Store(str(tmp_path / "t.db")))
    assert trakt.scrobble("stop", {"progress": 90}) is None


def test_refresh_race_uses_the_other_processs_new_tokens(server):
    """Another process refreshed first, so Trakt refuses our (now used) refresh token."""
    server.valid_tokens = {"access-9"}
    server.refresh_status = 400
    trakt, _ = client()

    class Racing(MemoryTokens):
        loads = 0

        def load(self):
            Racing.loads += 1
            if Racing.loads > 2:   # by the time Trakt answers, the other process has saved a new pair
                return {"access_token": "access-9", "refresh_token": "refresh-9", "expires_at": 4_000_000_000}
            return super().load()
    trakt.tokens = Racing(trakt.tokens.value)
    assert trakt.get("/users/settings", auth=True)["user"]["username"] == "sponge"
    assert trakt.signed_in
