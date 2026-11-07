# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Shared HTTP helper: one session, a SpongeTV User-Agent, timeouts and polite retries."""

import time

import requests


class HttpError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Http:
    MAX_WAIT = 30  # never sleep longer than this for a Retry-After

    def __init__(self, user_agent, timeout=15, retries=2, sleep=time.sleep):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep

    def get_json(self, url, params=None, headers=None):
        """GET a JSON document. Retries on 429 (honouring Retry-After) and on 5xx."""
        attempt = 0
        while True:
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as error:
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

    @staticmethod
    def _retry_after(response):
        try:
            return max(1, int(float(response.headers.get("Retry-After", "5"))))
        except ValueError:
            return 5
