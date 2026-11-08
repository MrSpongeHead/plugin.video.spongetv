# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Premiumize: account status, cache checks, turning a source into a playable link, and your cloud.

You sign in with a code at premiumize.me/device (SpongeTV's own client ID), or, at the Expert settings
level, with your account's API key. Either is sent as a Bearer token. https://http.premiumize.me/api
"""

import re

from resources.lib.http import HttpError

API = "https://www.premiumize.me/api"
CACHE_BATCH = 100            # Premiumize doesn't publish a limit; this keeps each request modest
HOSTS_SECONDS = 24 * 3600
VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts", ".m2ts", ".webm", ".mpg", ".mpeg")
ANY_EPISODE = re.compile(r"s\d+[\W_]*e\d+|(?<!\d)\d{1,2}x\d{2}(?!\d)", re.I)
SAMPLE = re.compile(r"(^|[\W_])(sample|trailer|extras?|featurettes?)([\W_]|$)", re.I)


class PremiumizeError(Exception):
    """kind: no_key, bad_key, not_premium, unreachable, failed, no_file, no_client_id, bad_client_id, denied"""

    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def magnet_for(source):
    if source.get("magnet"):
        return source["magnet"]
    return f"magnet:?xt=urn:btih:{source['hash']}"


def cache_item(source):
    """What a cache check asks about: a plain magnet link for torrents (Premiumize's documentation asks
    for links), the link itself for everything else."""
    return f"magnet:?xt=urn:btih:{source['hash']}" if source.get("type") == "torrent" else source.get("url")


def episode_pattern(season, episode):
    s, e = int(season), int(episode)
    return re.compile(rf"(?:s0*{s}[\W_]*e0*{e}(?!\d)|(?<!\d)0*{s}x0*{e}(?!\d)|season[\W_]*0*{s}[\W_]*episode[\W_]*0*{e}(?!\d))",
                      re.I)


def is_video(path):
    return path.lower().endswith(VIDEO_EXTENSIONS) and not SAMPLE.search(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])


def pick_file(content, season=None, episode=None):
    """The file to play from a transfer: for an episode, the one named for it (season packs);
    for a film, the largest video. None if nothing fits."""
    videos = [f for f in content if is_video(f.get("path") or "") and f.get("link")]
    if season is not None and episode is not None:
        pattern = episode_pattern(season, episode)
        matches = [f for f in videos if pattern.search(f["path"].rsplit("/", 1)[-1]) or pattern.search(f["path"])]
        if matches:
            return max(matches, key=lambda f: int(f.get("size") or 0))
        if len(videos) == 1 and not ANY_EPISODE.search(videos[0]["path"]):
            return videos[0]        # a single-episode release whose file name doesn't say which
        return None
    return max(videos, key=lambda f: int(f.get("size") or 0)) if videos else None


class Premiumize:
    def __init__(self, http, api_key, store=None, clock=None):
        self.http = http
        self.api_key = (api_key or "").strip()
        self.store = store
        import time
        self.clock = clock or time.time

    @property
    def ready(self):
        return bool(self.api_key)

    # -- requests -----------------------------------------------------------------------------------
    def _call(self, method, path, params=None, form=None):
        if not self.api_key:
            raise PremiumizeError("no_key")
        try:
            response = self.http.send(method, f"{API}/{path}", params=params, form=form,
                                      headers={"Authorization": f"Bearer {self.api_key}"})
        except HttpError as error:
            raise PremiumizeError("unreachable", str(error)) from error
        data = response.data if isinstance(response.data, dict) else {}
        if response.status in (401, 403) or _is_auth_error(data):
            raise PremiumizeError("bad_key", data.get("message", ""))
        if response.status >= 500 or response.status == 429:
            raise PremiumizeError("unreachable", f"HTTP {response.status}")
        if data.get("status") != "success":
            raise PremiumizeError("failed", data.get("message") or f"HTTP {response.status}")
        return data

    # -- account ---------------------------------------------------------------------------------------
    def account(self):
        """{"premium_until": unix time or None, "limit_used": 0..1, "customer_id": ...}"""
        data = self._call("GET", "account/info")
        return {"customer_id": data.get("customer_id"), "premium_until": data.get("premium_until"),
                "limit_used": float(data.get("limit_used") or 0)}

    def days_left(self, account):
        until = account.get("premium_until")
        if not until:
            return None
        return max(0, int((int(until) - self.clock()) // 86400))

    # -- what's ready ----------------------------------------------------------------------------------
    def check_cache(self, items):
        """{item: True/False} for each link or hash; items Premiumize didn't answer for are left out."""
        items = [i for i in dict.fromkeys(items) if i]
        answer = {}
        for start in range(0, len(items), CACHE_BATCH):
            batch = items[start:start + CACHE_BATCH]
            data = self._call("POST", "cache/check", form=[("items[]", i) for i in batch])
            flags = data.get("response") or []
            for item, flag in zip(batch, flags):
                answer[item] = bool(flag)
        return answer

    def mark_ready(self, sources):
        """Set source["debrid"] to cached / uncached for torrents and hoster links Premiumize supports."""
        hosts = self.hosts()
        wanted = []
        for source in sources:
            if source.get("debrid") == "cloud":
                continue
            if source.get("type") == "hosters" and not _host_supported(source, hosts):
                continue
            if source.get("type") in ("torrent", "hosters"):
                wanted.append(source)
        flags = self.check_cache([cache_item(s) for s in wanted])
        for source in wanted:
            item = cache_item(source)
            if item in flags:
                source["debrid"] = "cached" if flags[item] else "uncached"
        return sources

    def hosts(self):
        """Hoster names Premiumize can download from (kept for a day)."""
        key = "premiumize:hosts"
        if self.store:
            saved = self.store.cache_get(key)
            if saved is not None:
                return saved
        data = self._call("GET", "services/list")
        names = set(data.get("directdl") or []) | set(data.get("cache") or [])
        for aliases in (data.get("aliases") or {}).values():
            names |= set(aliases or [])
        hosts = sorted(n.lower() for n in names if n)
        if self.store:
            self.store.cache_set(key, hosts, HOSTS_SECONDS)
        return hosts

    # -- playing ----------------------------------------------------------------------------------------
    def resolve(self, source, season=None, episode=None):
        """A direct link for the source (the right file from a season pack). Raises PremiumizeError."""
        if source.get("type") in ("direct", "adaptive"):
            return source["url"]
        src = magnet_for(source) if source.get("type") == "torrent" else source.get("url")
        if source.get("debrid") == "cloud" and source.get("url"):
            return source["url"]
        data = self._call("POST", "transfer/directdl", form={"src": src})
        chosen = pick_file(data.get("content") or [], season, episode)
        if not chosen:
            raise PremiumizeError("no_file")
        return chosen["link"]

    # -- your cloud ---------------------------------------------------------------------------------------
    def cloud_search(self, request):
        """Videos already in your Premiumize cloud that match the film or episode."""
        info = request.get("simple_info") or {}
        title = info.get("show_title") or info.get("title") or ""
        words = [w for w in re.split(r"[\W_]+", title.lower()) if w]
        if not words:
            return []
        files = self._call("GET", "item/listall").get("files") or []
        found = []
        season, episode = info.get("season_number"), info.get("episode_number")
        pattern = episode_pattern(season, episode) if season and episode else None
        year = info.get("year")
        for f in files:
            path = f.get("path") or f.get("name") or ""
            if not is_video(path):
                continue
            flat = re.split(r"[\W_]+", path.lower())
            if not all(w in flat for w in words):
                continue
            if pattern and not pattern.search(path):
                continue
            if not pattern and year and year not in flat:
                continue
            found.append({"id": f.get("id"), "name": f.get("name") or path.rsplit("/", 1)[-1],
                          "size": int(f.get("size") or 0)})
        return found

    def cloud_link(self, item_id):
        data = self._call("GET", "item/details", params={"id": item_id})
        return data.get("link") or data.get("stream_link")


def _is_auth_error(data):
    if data.get("status") != "error":
        return False
    text = f"{data.get('code', '')} {data.get('message', '')}".lower()
    return any(word in text for word in ("auth", "login", "logged in", "api key", "apikey", "customer_id", "token"))


def _host_supported(source, hosts):
    host = (source.get("host") or "").lower()
    if not host:
        url = source.get("url") or ""
        match = re.match(r"https?://(?:www\.)?([^/:]+)", url)
        host = match.group(1).lower() if match else ""
    return any(host == h or host.endswith("." + h) or host.split(".")[0] == h.split(".")[0] for h in hosts)


# -- signing in with a code (device sign-in) ------------------------------------------------------------
TOKEN_URL = "https://www.premiumize.me/token"
DEVICE_URL = "premiumize.me/device"


def device_code(http, client_id):
    """Ask Premiumize for a code to show. {"user_code", "device_code", "verification_uri", "expires_in", "interval"}"""
    if not client_id:
        raise PremiumizeError("no_client_id")
    try:
        response = http.send("POST", TOKEN_URL, form={"response_type": "device_code", "client_id": client_id})
    except HttpError as error:
        raise PremiumizeError("unreachable", str(error)) from error
    data = response.data if isinstance(response.data, dict) else {}
    if response.status != 200 or not data.get("device_code"):
        if response.status in (400, 401, 403):
            raise PremiumizeError("bad_client_id", data.get("error") or f"HTTP {response.status}")
        raise PremiumizeError("unreachable", f"HTTP {response.status}")
    return data


def poll_device(http, client_id, code, should_stop=lambda: False, sleep=None, clock=None):
    """Wait for you to approve the code at premiumize.me/device.
    Returns {"access_token", "expires_at"}, or None if you cancelled or the code ran out."""
    import time
    sleep = sleep or time.sleep
    clock = clock or time.time
    interval = max(int(code.get("interval") or 5), 1)
    deadline = clock() + int(code.get("expires_in") or 600)
    while clock() < deadline:
        for _ in range(interval * 4):          # check for Cancel every quarter of a second
            if should_stop():
                return None
            sleep(0.25)
        try:
            response = http.send("POST", TOKEN_URL, form={"grant_type": "device_code", "code": code["device_code"],
                                                          "client_id": client_id})
        except HttpError:
            continue                            # a network blip: keep waiting
        data = response.data if isinstance(response.data, dict) else {}
        if response.status == 200 and data.get("access_token"):
            expires_in = data.get("expires_in")
            return {"access_token": data["access_token"],
                    "expires_at": int(clock() + int(expires_in)) if expires_in else None}
        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise PremiumizeError("denied")
        if error in ("invalid_grant", "expired_token"):
            return None
        if response.status >= 500 or response.status == 429:
            continue
        raise PremiumizeError("failed", error or f"HTTP {response.status}")
    return None
