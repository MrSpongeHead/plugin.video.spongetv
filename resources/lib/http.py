# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Shared HTTP helper: one session, a SpongeTV User-Agent, timeouts and polite retries."""

import threading
import time

# The requests library takes about 0.6 seconds to load on an NVIDIA Shield, every time Kodi runs SpongeTV
# for a list. Most menus, and lists whose details are already saved, never touch the network, so it's only
# loaded when a request is first made.
_lock = threading.Lock()


def _requests():
    import requests
    return requests


class HttpError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Response:
    """What send() returns: the status, the decoded JSON body (or None), the headers and the raw bytes."""

    def __init__(self, status, data, headers, content=None):
        self.status = status
        self.data = data
        self.headers = headers or {}
        self.content = content


class Http:
    MAX_WAIT = 30  # never sleep longer than this for a Retry-After

    def __init__(self, user_agent, timeout=15, retries=2, sleep=time.sleep):
        self.user_agent = user_agent
        self._session = None
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep

    @property
    def session(self):
        """One connection pool for every request, made (and requests loaded) on first use."""
        if self._session is None:
            with _lock:
                if self._session is None:
                    session = _requests().Session()
                    session.headers["User-Agent"] = self.user_agent
                    self._session = session
        return self._session

    @session.setter
    def session(self, value):
        self._session = value

    def get_json(self, url, params=None, headers=None):
        """GET a JSON document. Retries on 429 (honouring Retry-After) and on 5xx."""
        attempt = 0
        while True:
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except _requests().RequestException as error:
                if attempt < self.retries:
                    attempt += 1
                    self.sleep(2 ** attempt)
                    continue
                raise HttpError(f"Network error: {error}") from error

            status = response.status_code
            if status == 429 and attempt < self.retries:
                attempt += 1
                self.sleep(min(self._retry_after(response), self.MAX_WAIT))
                continue
            if status >= 500 and attempt < self.retries:
                attempt += 1
                self.sleep(2 ** attempt)
                continue
            if status >= 400:
                raise HttpError(f"HTTP {status} from {url}", status)
            try:
                return response.json()
            except ValueError as error:
                raise HttpError(f"Invalid JSON from {url}", status) from error

    def send(self, method, url, params=None, json_body=None, headers=None, max_wait=None, form=None):
        """Any request, returning a Response for every HTTP status so the caller can decide.

        Network errors are retried; 429 waits as long as Retry-After asks (up to max_wait);
        5xx is retried. Raises HttpError only when the network itself fails."""
        max_wait = self.MAX_WAIT if max_wait is None else max_wait
        attempt = 0
        while True:
            try:
                response = self.session.request(method, url, params=params, json=json_body, data=form, headers=headers,
                                                timeout=self.timeout)
            except _requests().RequestException as error:
                if attempt < self.retries:
                    attempt += 1
                    self.sleep(2 ** attempt)
                    continue
                raise HttpError(f"Network error: {error}") from error
            status = response.status_code
            if status == 429 and attempt < self.retries:
                wait = self._retry_after(response)
                if wait <= max_wait:
                    attempt += 1
                    self.sleep(wait)
                    continue
            if status >= 500 and attempt < self.retries:
                attempt += 1
                self.sleep(2 ** attempt)
                continue
            try:
                data = response.json() if response.content else None
            except ValueError:
                data = None
            return Response(status, data, dict(response.headers), response.content)

    @staticmethod
    def _retry_after(response):
        try:
            return max(1, int(float(response.headers.get("Retry-After", "5"))))
        except ValueError:
            return 5
