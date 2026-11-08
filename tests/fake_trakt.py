# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for Trakt's API, answering through Http.send like the real thing would."""

import json

from resources.lib.http import HttpError, Response


class FakeTrakt:
    def __init__(self):
        self.calls = []                 # (method, url, params, body, headers)
        self.valid_tokens = {"access-1"}
        self.next_token = 2
        self.device_statuses = [200]    # what /oauth/device/token answers, in turn
        self.refresh_status = 200
        self.activities = {"movies": {"watched_at": "A"}, "episodes": {"watched_at": "A"}}
        self.pages = {}                 # path -> full list of items (paged on request)
        self.ignore_paging = set()      # paths that return everything on every page
        self.fail = {}                  # (method, path) -> status, or (method, path, page) -> status
        self.offline = False
        self.lists = []
        self.list_items = {}
        self.calendar = []
        self.recommendations = {"movies": [], "shows": []}
        self.trakt_to_tmdb = {}

    # Http.send signature
    def __call__(self, http_self, method, url, params=None, json_body=None, headers=None, max_wait=None):
        params = dict(params or {})
        self.calls.append((method, url, params, json_body, dict(headers or {})))
        if self.offline:
            raise HttpError("offline")
        if url.startswith("https://auth.trakt.tv"):
            return self._auth(url[len("https://auth.trakt.tv"):], json_body or {})
        path = url[len("https://api.trakt.tv"):]
        for key in ((method, path, params.get("page")), (method, path)):
            if key in self.fail:
                return Response(self.fail[key], None, {})
        token = (headers or {}).get("Authorization", "").replace("Bearer ", "")
        if token and token not in self.valid_tokens:
            return Response(401, None, {})
        if method == "GET":
            return Response(200, self._get(path, params), {})
        if method == "DELETE":
            return Response(204, None, {})
        if method == "POST" and path == "/users/me/lists":
            self.lists.append({"name": json_body["name"], "item_count": 0, "ids": {"trakt": 900 + len(self.lists)}})
        return Response(201, {}, {})

    def _auth(self, path, body):
        if path == "/oauth/device/code":
            return Response(200, {"device_code": "dev", "user_code": "ABCD1234", "verification_url": "https://trakt.tv/activate",
                                  "expires_in": 600, "interval": 5}, {})
        if path == "/oauth/device/token":
            status = self.device_statuses.pop(0) if self.device_statuses else 400
            return Response(status, self._new_tokens() if status == 200 else None, {})
        if path == "/oauth/token":
            if self.refresh_status != 200:
                return Response(self.refresh_status, None, {})
            return Response(200, self._new_tokens(), {})
        if path == "/oauth/revoke":
            return Response(200, {}, {})
        return Response(404, None, {})

    def _new_tokens(self):
        token = f"access-{self.next_token}"
        self.next_token += 1
        self.valid_tokens.add(token)
        return {"access_token": token, "refresh_token": f"refresh-{token}", "expires_in": 7 * 24 * 3600,
                "created_at": 2_000_000_000}

    def _get(self, path, params):
        if path == "/sync/last_activities":
            return self.activities
        if path == "/users/settings":
            return {"user": {"username": "sponge"}}
        if path.startswith("/calendars/my/shows/"):
            return self.calendar
        if path.startswith("/shows/") and path[7:].isdigit():
            return {"title": "x", "ids": {"trakt": int(path[7:]), "tmdb": self.trakt_to_tmdb.get(int(path[7:]))}}
        if path.startswith("/recommendations/"):
            return self.recommendations[path.rsplit("/", 1)[1]]
        if path == "/users/me/lists":
            return self._paged(self.lists, params)
        if path.endswith("/items") and path.startswith("/users/"):
            return self._paged(self.list_items.get(path, []), params)
        items = self.pages.get(path, [])
        if path.startswith("/sync/watched/shows") and params.get("extended") != "progress":
            # Trakt since 3 July 2026: no seasons unless extended=progress is requested
            items = [{k: v for k, v in item.items() if k != "seasons"} for item in items]
        if params.get("extended") == "progress" and int(params.get("limit", 10)) > 100:
            params = dict(params, limit=100)   # Trakt caps progress pages at 100
        if path in self.ignore_paging:
            return items
        return self._paged(items, params)

    @staticmethod
    def _paged(items, params):
        if "page" not in params:
            return items
        page, limit = int(params["page"]), int(params.get("limit", 10))
        return items[(page - 1) * limit: page * limit]

    # helpers for assertions
    def paths(self, method=None):
        return [(m, u.split(".tv", 1)[1]) for m, u, *_ in self.calls if method in (None, m)]

    def posted(self, path):
        return [b for m, u, p, b, h in self.calls if m == "POST" and u.endswith(path)]

    def gets(self, path):
        return [p for m, u, p, b, h in self.calls if m == "GET" and u.endswith(path)]


def token_json(access="access-1", expires_at=4_000_000_000, username="sponge"):
    return json.dumps({"access_token": access, "refresh_token": "refresh-1", "expires_at": expires_at, "username": username})
