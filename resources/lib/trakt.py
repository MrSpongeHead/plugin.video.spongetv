# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""The one Trakt client: every call goes through here, so Trakt's 2026 rules live in one place.

- Sign-in uses the device code flow on auth.trakt.tv (required from 1 February 2027). Apps
  created since October 2026 have no Client Secret; one is sent only if you've entered it.
- Access tokens last 7 days and refresh tokens are single-use: a new pair is saved the moment
  Trakt returns it.
- Lists are paged with limit=250 and fetched until a page comes back empty (or repeats, in
  case Trakt ignores the page number); pagination headers are never relied on.
- Rate limits (Standard tier): signed-in reads stay under 500 per 5 minutes, writes are spaced
  a second apart, and a 429 waits exactly as long as Retry-After says.
- 401 means the login may be invalid: refresh once and retry; sign out only if the refresh
  itself is refused. 403, 420, 423, 426 and 5xx get a clear message and never sign you out.
"""

import collections
import json
import time

from resources.lib.http import HttpError

API = "https://api.trakt.tv"
AUTH = "https://auth.trakt.tv"
REDIRECT_URI = "http://localhost"
PAGE_LIMIT = 250
MAX_PAGES = 400
READ_BUDGET = 450            # of Trakt's 500 per 5 minutes, leaving room for other calls
READ_WINDOW = 300
WRITE_GAP = 1.0
REFRESH_MARGIN = 24 * 3600   # refresh when a token has less than a day left


class TraktError(Exception):
    """kind is one of: signed_out, forbidden, account_limit, locked, vip, not_found, rate,
    unavailable, network, sign_in_denied, sign_in_expired, sign_in_limit."""

    def __init__(self, kind, status=None, detail=""):
        super().__init__(f"Trakt {kind} ({status}): {detail}")
        self.kind = kind
        self.status = status


STATUS_KINDS = {401: "signed_out", 403: "forbidden", 404: "not_found", 420: "account_limit",
                423: "locked", 426: "vip", 429: "rate"}


class Trakt:
    def __init__(self, client_id, http, tokens, client_secret="", store=None, clock=time.time, sleep=time.sleep):
        """tokens: an object with load() -> dict, save(dict) and clear(). store (optional) keeps
        the time of the last write, so writes stay a second apart across Kodi's processes."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = http
        self.tokens = tokens
        self.store = store
        self.clock = clock
        self.sleep = sleep
        self._reads = collections.deque()

    # -- state -----------------------------------------------------------------------
    @property
    def configured(self):
        return bool(self.client_id)

    @property
    def signed_in(self):
        return bool(self.tokens.load().get("access_token"))

    def _credentials(self, body):
        body = dict(body, client_id=self.client_id)
        if self.client_secret:
            body["client_secret"] = self.client_secret
        return body

    def _headers(self, token=None):
        headers = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": self.client_id}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    # -- sign-in -------------------------------------------------------------------------
    def device_code(self):
        """{'device_code', 'user_code', 'verification_url', 'expires_in', 'interval'}"""
        response = self._send("POST", AUTH + "/oauth/device/code", body={"client_id": self.client_id})
        if response.status != 200 or not isinstance(response.data, dict):
            raise self._error(response.status, "device code")
        return response.data

    def poll_device(self, code, should_stop=lambda: False):
        """Poll until you approve, deny, or the code expires. Returns True when signed in,
        False if stopped; raises TraktError for denial, expiry or a refusal."""
        interval = max(int(code.get("interval") or 5), 1)
        deadline = self.clock() + int(code.get("expires_in") or 600)
        while self.clock() < deadline:
            if should_stop():
                return False
            self.sleep(interval)
            if should_stop():
                return False
            response = self._send("POST", AUTH + "/oauth/device/token",
                                  body=self._credentials({"code": code["device_code"]}))
            status = response.status
            if status == 200 and isinstance(response.data, dict):
                self._save_tokens(response.data)
                return True
            if status == 400:          # waiting for you to enter the code
                continue
            if status == 429:          # polling too fast
                interval += 1
                continue
            if status in (404, 409, 410):
                raise TraktError("sign_in_expired", status)
            if status == 418:
                raise TraktError("sign_in_denied", status)
            if status in (403, 420):
                raise TraktError("sign_in_limit", status)
            raise self._error(status, "device token")
        raise TraktError("sign_in_expired", 410)

    def refresh(self):
        tokens = self.tokens.load()
        if not tokens.get("refresh_token"):
            raise TraktError("signed_out", 401)
        body = self._credentials({"refresh_token": tokens["refresh_token"], "redirect_uri": REDIRECT_URI,
                                  "grant_type": "refresh_token"})
        response = self._send("POST", AUTH + "/oauth/token", body=body)
        if response.status == 200 and isinstance(response.data, dict):
            self._save_tokens(response.data, tokens.get("username", ""))
            return
        if response.status in (400, 401):
            # Refresh tokens work once. If another part of SpongeTV (the background service or a
            # menu) refreshed at the same moment, use the pair it saved rather than signing out.
            latest = self.tokens.load()
            if latest.get("refresh_token") and latest["refresh_token"] != tokens["refresh_token"]:
                return
            self.tokens.clear()   # Trakt refused the refresh: the login really is invalid
            raise TraktError("signed_out", response.status)
        raise self._error(response.status, "refresh")

    def sign_out(self):
        tokens = self.tokens.load()
        if tokens.get("access_token"):
            try:
                self._send("POST", AUTH + "/oauth/revoke", body=self._credentials({"token": tokens["access_token"]}))
            except TraktError:
                pass  # signing out locally matters more than telling Trakt
        self.tokens.clear()

    def _save_tokens(self, data, username=""):
        created = int(data.get("created_at") or self.clock())
        self.tokens.save({"access_token": data.get("access_token", ""), "refresh_token": data.get("refresh_token", ""),
                          "expires_at": created + int(data.get("expires_in") or 7 * 24 * 3600),
                          "username": username})

    def _access_token(self):
        tokens = self.tokens.load()
        if not tokens.get("access_token"):
            raise TraktError("signed_out", 401)
        if tokens.get("expires_at", 0) - self.clock() < REFRESH_MARGIN:
            self.refresh()
            tokens = self.tokens.load()
        return tokens["access_token"]

    def refresh_if_due(self):
        """For the background service: refresh a token that's close to expiring."""
        if self.signed_in:
            self._access_token()

    # -- requests ------------------------------------------------------------------------
    def _send(self, method, url, params=None, body=None, token=None):
        try:
            return self.http.send(method, url, params=params, json_body=body, headers=self._headers(token), max_wait=60)
        except HttpError as error:
            raise TraktError("network", None, str(error)) from error

    def _error(self, status, what):
        kind = STATUS_KINDS.get(status, "unavailable")
        return TraktError(kind, status, what)

    def _wait_for_read_budget(self):
        now = self.clock()
        while self._reads and now - self._reads[0] > READ_WINDOW:
            self._reads.popleft()
        if len(self._reads) >= READ_BUDGET:
            self.sleep(READ_WINDOW - (now - self._reads[0]) + 1)
        self._reads.append(self.clock())

    def _space_writes(self):
        last = float((self.store.get_meta("trakt_last_write") if self.store else None) or getattr(self, "_last_write", 0))
        gap = WRITE_GAP - (self.clock() - last)
        if gap > 0:
            self.sleep(gap)
        now = self.clock()
        self._last_write = now
        if self.store:
            self.store.set_meta("trakt_last_write", str(now))

    def request(self, method, path, params=None, body=None, auth=False, _retried=False):
        token = self._access_token() if auth else None
        if method == "GET":
            if auth:
                self._wait_for_read_budget()
        else:
            self._space_writes()
        response = self._send(method, API + path, params, body, token)
        status = response.status
        if 200 <= status < 300:
            return response.data
        if status == 401 and auth and not _retried:
            self.refresh()   # signs out only if Trakt refuses the refresh
            return self.request(method, path, params, body, auth, _retried=True)
        raise self._error(status, f"{method} {path}")

    def get(self, path, params=None, auth=False):
        return self.request("GET", path, params, auth=auth)

    def post(self, path, body, auth=True):
        return self.request("POST", path, body=body, auth=auth)

    def put(self, path, body, auth=True):
        return self.request("PUT", path, body=body, auth=auth)

    def delete(self, path, auth=True):
        return self.request("DELETE", path, auth=auth)

    def get_all(self, path, params=None, auth=True):
        """Every page, in Trakt's order. Stops at an empty page, or a page identical to the last
        one (in case paging is ignored), never trusting pagination headers or the limit."""
        items, previous = [], None
        for page in range(1, MAX_PAGES + 1):
            batch = self.get(path, dict(params or {}, page=page, limit=PAGE_LIMIT), auth=auth) or []
            if not batch:
                break
            fingerprint = json.dumps(batch, sort_keys=True)
            if fingerprint == previous:
                break
            previous = fingerprint
            items.extend(batch)
        return items

    # -- account ---------------------------------------------------------------------------
    def username(self):
        settings = self.get("/users/settings", auth=True) or {}
        name = (settings.get("user") or {}).get("username", "")
        tokens = self.tokens.load()
        if tokens and name and tokens.get("username") != name:
            self.tokens.save(dict(tokens, username=name))
        return name

    # -- scrobbling (wired to playback in stage 4) ------------------------------------------------
    def scrobble(self, action, body):
        """action: start, pause or stop. Queued for later if Trakt can't be reached."""
        try:
            return self.post(f"/scrobble/{action}", body)
        except TraktError as error:
            if error.status == 409:          # already scrobbled recently: nothing to do
                return None
            if error.kind in ("network", "unavailable", "rate") and self.store is not None:
                self.store.execute("INSERT INTO scrobble_queue (action, body, created) VALUES (?, ?, ?)",
                                   (action, json.dumps(body), self.clock()))
                return None
            raise

    def send_queued_scrobbles(self):
        """Send scrobbles made while offline, oldest first; stops at the first that still fails."""
        if self.store is None:
            return 0
        sent = 0
        for row_id, action, body in self.store.query("SELECT id, action, body FROM scrobble_queue ORDER BY id"):
            try:
                self.post(f"/scrobble/{action}", json.loads(body))
            except TraktError as error:
                # Keep it for later if Trakt is unreachable or you're signed out; drop it if Trakt
                # says it's already recorded (409) or refuses it outright.
                if error.status != 409 and error.kind in ("network", "unavailable", "rate", "signed_out"):
                    break
            self.store.execute("DELETE FROM scrobble_queue WHERE id = ?", (row_id,))
            sent += 1
        return sent
