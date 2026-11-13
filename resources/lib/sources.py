# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Source search: ask every enabled provider for a film or episode, in parallel.

- Calls match Seren's exactly: torrent, adaptive and direct providers get
  sources().movie(title, year, imdb, simple_info=..., info=...) or sources().episode(simple_info, info);
  hoster providers get source().movie/tvshow/episode for a page, then sources(url, hostDict, hostprDict).
  simple_info is built the way Seren builds it (numbers as text).
- Each provider runs in its own thread with its own error trap, so one failing provider can't stop
  the search, and one that runs past the time limit is marked "timed out" and ignored.
- Early stop: once enough good sources are found (e.g. 5 at 1080p or better), the search finishes.
- Results from every provider are tidied into one shape, with quality and tags (HDR, HEVC…) read
  from the release title when the provider didn't say.
"""

import importlib
import queue
import re
import threading
import time
import traceback

from resources.lib import kodi

QUALITIES = ["4K", "1080p", "720p", "SD", "CAM"]
QUALITY_RANK = {q: i for i, q in enumerate(QUALITIES)}

# CAM comes first: a cinema recording is often labelled with a resolution too ("1080p HDCAM"), and it's
# still a cinema recording. Screeners count as CAM, as they're hidden by the same setting.
CAM_PATTERN = (r"\b(cam|camrip|hdcam|hdcamrip|hqcam|ts|tsrip|telesync|hdts|tc|hdtc|telecine|scr|screener|"
               r"dvdscr|bdscr|webscr|hdscr|pdvd|predvd)\b")
_QUALITY_PATTERNS = [
    ("CAM", CAM_PATTERN),
    ("4K", r"\b(2160p|4k|uhd)\b"),
    ("1080p", r"\b(1080p|1080i|fhd)\b"),
    ("720p", r"\b720p\b"),
]
_TAG_PATTERNS = [
    ("Dolby Vision", r"\b(dolby[ .-]?vision|dovi|dv)\b"),
    ("HDR", r"\b(hdr|hdr10|hdr10\+|hdr10plus)\b"),
    ("HEVC", r"\b(x265|h\.?265|hevc)\b"),
    ("AV1", r"\bav1\b"),
    ("H.264", r"\b(x264|h\.?264|avc)\b"),
    ("Remux", r"\bremux\b"),
    ("3D", r"\b3d\b"),
    ("Atmos", r"\batmos\b"),
    ("7.1", r"\b7[ .]1\b"),
    ("5.1", r"\b5[ .]1\b"),
]


def _words(title):
    return re.sub(r"[\[\]().,_+-]", " ", (title or "").lower())


def quality_of(title):
    words = _words(title)
    for quality, pattern in _QUALITY_PATTERNS:
        if re.search(pattern, words):
            return quality
    return "SD"


def tags_of(title):
    words = _words(title).replace(" 5 1", " 5.1").replace(" 7 1", " 7.1")
    found = [tag for tag, pattern in _TAG_PATTERNS if re.search(pattern, words)]
    if "Dolby Vision" in found and "HDR" not in found and re.search(r"\bhdr", words):
        found.append("HDR")
    return found


def _quality_from_provider(value):
    text = str(value or "").upper().replace("P", "p")
    for quality in QUALITIES:
        if quality.upper() == text.upper():
            return quality
    return None


class Source(dict):
    """One result, in one shape whatever the provider returned. A dict, so it caches as JSON."""

    @property
    def key(self):
        return (self.get("hash") or self.get("url") or self.get("release_title", "")).lower()


def normalise(raw, provider, kind):
    """Turn a provider's result into a Source, or None if it's unusable."""
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("release_title") or raw.get("name") or "")
    torrent_hash = str(raw.get("hash") or "").lower()
    if kind == "torrent" and not torrent_hash:
        magnet = str(raw.get("magnet") or "")
        found = re.search(r"btih:([0-9a-zA-Z]+)", magnet)
        torrent_hash = found.group(1).lower() if found else ""
        if not torrent_hash:
            return None
    url = str(raw.get("url") or "")
    if kind != "torrent" and not url:
        return None
    try:
        size_mb = float(raw.get("size") or 0)
    except (TypeError, ValueError):
        size_mb = 0.0
    try:
        seeds = int(raw.get("seeds") or 0)
    except (TypeError, ValueError):
        seeds = 0
    # The release name wins over the provider's own label when it says it's a cinema recording or screener
    quality = "CAM" if re.search(CAM_PATTERN, _words(title)) else (
        _quality_from_provider(raw.get("quality")) or quality_of(title))
    extra = str(raw.get("info") or "")
    tags = tags_of(title + " " + (extra if isinstance(raw.get("info"), str) else " ".join(raw.get("info") or [])))
    return Source(type=kind, provider=provider["name"], package=provider["package"], release_title=title,
                  hash=torrent_hash, magnet=str(raw.get("magnet") or ""), url=url, size_mb=size_mb, seeds=seeds,
                  quality=quality, tags=tags, pack=str(raw.get("package") or "single"),
                  debrid=raw.get("debrid") or "", host=str(raw.get("source") or raw.get("host") or ""))


# -- what providers are given -------------------------------------------------------------------
def _aliases(title, original, more):
    """Other names a release might go by: the original title, then any given (Trakt's), without repeats."""
    names = []
    for name in [original] + list(more or []):
        if name and name != title and name not in names:
            names.append(name)
    return names


def season_airing(show, season, episodes=(), today=None):
    """Is this season still being broadcast? As Seren tells providers: about the season asked for, not the
    show. Providers such as a4kScrapers search only for the single episode when told it is, and add season
    and complete-series packs when it isn't, so saying it of every season of a show still in production
    would hide the packs that older episodes are found in."""
    import datetime
    today = today or datetime.date.today().isoformat()
    upcoming = show.get("next_episode_to_air") or {}
    if upcoming and int(upcoming.get("season_number") or 0) == int(season):
        return True
    return any((e.get("air_date") or "") > today for e in episodes or [])


def movie_request(details, aliases=()):
    """Seren's _build_simple_movie_info plus the info dict, from TMDB details."""
    year = (details.get("release_date") or "")[:4]
    title = details.get("title") or details.get("original_title") or ""
    aliases = _aliases(title, details.get("original_title"), aliases)
    country = ((details.get("production_countries") or [{}])[0] or {}).get("iso_3166_1", "")
    simple = {"title": title, "year": str(year), "aliases": list(aliases), "country": country.lower()}
    if "." in title:
        simple["aliases"].append(title.replace(".", ""))
    info = {"info": {"title": title, "year": year, "imdb_id": details.get("imdb_id") or
                     (details.get("external_ids") or {}).get("imdb_id"), "tmdb_id": details.get("id"),
                     "originaltitle": details.get("original_title"), "country_origin": country.lower(),
                     "genre": [g.get("name") for g in details.get("genres") or []]}}
    return {"media": "movie", "title": title, "year": year, "imdb": info["info"]["imdb_id"],
            "tmdb_id": details.get("id"), "simple_info": simple, "info": info}


def episode_request(show, episode, airing=None, aliases=()):
    """Seren's _build_simple_show_info plus the info dict, from TMDB show and episode details.
    airing: is the episode's season still being broadcast (worked out from the show if not given)."""
    year = (show.get("first_air_date") or "")[:4]
    title = show.get("name") or show.get("original_name") or ""
    aliases = _aliases(title, show.get("original_name"), aliases)
    country = (show.get("origin_country") or [""])[0]
    genres = [g.get("name", "") for g in show.get("genres") or []]
    seasons = [s for s in show.get("seasons") or [] if s.get("season_number")]
    season, number = int(episode.get("season_number") or 0), int(episode.get("episode_number") or 0)
    absolute = sum(int(s.get("episode_count") or 0) for s in seasons if s["season_number"] < season) + number
    simple = {"show_title": title, "episode_title": episode.get("name") or "", "year": str(year),
              "season_number": str(season), "episode_number": str(number), "show_aliases": list(aliases),
              "country": country.lower(), "no_seasons": str(len(seasons)),
              "absolute_number": str(absolute), "is_airing": bool(season_airing(show, season) if airing is None else airing),
              "no_episodes": str(sum(int(s.get("episode_count") or 0) for s in seasons)),
              "isanime": any(x in g.lower() for g in genres for x in ("anime", "animation"))}
    if "." in title:
        simple["show_aliases"].append(title.replace(".", ""))
    external = show.get("external_ids") or {}
    info = {"info": {"tvshowtitle": title, "title": episode.get("name"), "originaltitle": episode.get("name"),
                     "season": season, "episode": number, "year": year, "tvshow.year": year,
                     "imdb_id": external.get("imdb_id"), "tvdb_id": external.get("tvdb_id"), "tmdb_id": show.get("id"),
                     "premiered": episode.get("air_date"), "aired": episode.get("air_date"),
                     "country_origin": country.lower(), "genre": genres, "aliases": list(aliases),
                     "mediatype": "episode",
                     # Seren copies the show's IDs into each episode as tvshow.<id>; providers that look
                     # an episode up by the show's IMDb ID read tvshow.imdb_id
                     "tvshow.imdb_id": external.get("imdb_id"), "tvshow.tmdb_id": show.get("id"),
                     "tvshow.tvdb_id": external.get("tvdb_id")},
            "showInfo": {"ids": {"imdb": external.get("imdb_id"), "tmdb": show.get("id"),
                                 "tvdb": external.get("tvdb_id")}},
            "season_count": len(seasons), "episode_count": simple["no_episodes"], "absoluteNumber": absolute,
            "is_airing": simple["is_airing"]}
    return {"media": "episode", "title": title, "year": year, "imdb": external.get("imdb_id"),
            "tmdb_id": show.get("id"), "season": season, "episode": number, "simple_info": simple, "info": info}


def request_key(request):
    if request["media"] == "movie":
        return f"sources:movie:{request['tmdb_id']}"
    return f"sources:episode:{request['tmdb_id']}:{request['season']}:{request['episode']}"


# -- calling one provider -------------------------------------------------------------------------
IMPORT_LOCK = threading.Lock()


def provider_module(provider):
    """Import a provider's module. One import at a time: providers of one package share modules, and
    importing them from several threads at once can deadlock inside Python's import system."""
    name = f"providers.{provider['package']}.{provider['language']}.{provider['kind']}.{provider['name']}"
    with IMPORT_LOCK:
        return importlib.import_module(name)


def call_provider(provider, request, host_lists=([], [])):
    """Run one provider and return its raw results. Raises whatever the provider raises."""
    module = provider_module(provider)
    simple, info = request["simple_info"], request["info"]
    if provider["kind"] == "hosters":
        source = module.source()
        if request["media"] == "movie":
            if not hasattr(source, "movie"):
                return []
            url = source.movie(request["imdb"], request["title"], request["title"], simple.get("aliases", []), request["year"])
        else:
            if not hasattr(source, "tvshow"):
                return []
            show_url = source.tvshow(request["imdb"], info["info"].get("tvdb_id"), request["title"], request["title"],
                                     simple.get("show_aliases", []), request["year"])
            url = source.episode(show_url, request["imdb"], info["info"].get("tvdb_id"), simple.get("episode_title"),
                                 info["info"].get("premiered"), str(request["season"]), str(request["episode"]))
        if not url:
            return []
        return source.sources(url, host_lists[0], host_lists[1]) or []
    sources = module.sources()
    if request["media"] == "movie":
        if not hasattr(sources, "movie"):
            return []
        try:
            return sources.movie(request["title"], str(request["year"]), request["imdb"], simple_info=simple, info=info) or []
        except TypeError:   # older providers don't take the IMDb ID (as Seren handles it)
            return sources.movie(request["title"], str(request["year"]), simple_info=simple, info=info) or []
    if not hasattr(sources, "episode"):
        return []
    return sources.episode(simple, info) or []


# -- the search ---------------------------------------------------------------------------------------
def is_ready(source):
    """Playable straight away: in your cloud, cached at Premiumize, or a direct link."""
    return source.get("debrid") in ("cloud", "cached") or source.get("type") in ("direct", "adaptive")


class EarlyStop:
    """"Stop after <count> sources at <quality> or better." count 0 = never stop early."""

    def __init__(self, enabled=True, quality="1080p", count=5, ready_only=False):
        self.enabled = enabled and count > 0
        self.quality = quality
        self.count = count
        self.ready_only = ready_only   # with Premiumize, only sources that can play straight away count

    def good(self, source):
        if self.ready_only and not is_ready(source):
            return False
        return QUALITY_RANK.get(source["quality"], 99) <= QUALITY_RANK.get(self.quality, 99)

    def progress(self, sources):
        return sum(1 for s in sources if self.good(s))

    def met(self, sources):
        return self.enabled and self.progress(sources) >= self.count


class Search:
    """Runs providers in the background. Poll status() from the window; read results() at the end."""

    CHECK_EVERY = 0.5

    def __init__(self, providers, request, timeout=30, early_stop=None, host_lists=([], []), call=call_provider,
                 clock=time.time, record=None, checker=None, visible=None):
        self.providers = list(providers)
        self.visible = visible     # the sources your filter lets through (what Source Select will show)
        self.request = request
        self.timeout = timeout
        self.early_stop = early_stop or EarlyStop(enabled=False)
        self.host_lists = host_lists
        self.call = call
        self.clock = clock
        self.record = record or (lambda provider, status, count: None)
        self._queue = queue.Queue()
        self._sources = {}
        self.statuses = {self._label(p): "waiting" for p in self.providers}
        self._lock = threading.Lock()
        self.cancelled = False
        self.stopped_early = False
        self.started = None
        self.checker = checker            # marks sources ready or not (Premiumize); may raise
        self._checked = set()
        self._check_lock = threading.Lock()
        self.check_failed = False

    @staticmethod
    def _label(provider):
        return f"{provider['package']}/{provider['kind']}/{provider['name']}"

    def start(self):
        self.started = self.clock()
        for provider in self.providers:
            self.statuses[self._label(provider)] = "searching"
            threading.Thread(target=self._run, args=(provider,), daemon=True).start()
        if self.checker:
            threading.Thread(target=self._keep_checking, daemon=True).start()
        return self

    def _keep_checking(self):
        while not self.cancelled and not self.check_failed:
            finished = self.finished
            self.check_new()
            if finished:          # one last check after the end, for sources that arrived at the last moment
                return
            time.sleep(self.CHECK_EVERY)

    def check_new(self):
        """Ask the checker about sources it hasn't seen yet. Safe to call from any thread."""
        if not self.checker or self.check_failed:
            return
        with self._check_lock:
            with self._lock:
                new = [s for k, s in self._sources.items() if k not in self._checked]
            if not new:
                return
            try:
                self.checker(new)
            except Exception as error:   # Premiumize trouble: keep the sources, just unchecked
                kodi.log_error(f"Checking sources failed: {error}")
                self.check_failed = True
            with self._lock:
                self._checked.update(s.key for s in new)

    def _run(self, provider):
        try:
            raw = self.call(provider, self.request, self.host_lists)
            self._queue.put((provider, "ok", list(raw or [])))
        except Exception as error:   # a provider's own failure must never stop the search
            kodi.log(f"Provider {self._label(provider)} failed: {error}\n{traceback.format_exc(limit=3)}")
            self._queue.put((provider, "failed", []))

    def _collect(self):
        while True:
            try:
                provider, outcome, raw = self._queue.get_nowait()
            except queue.Empty:
                return
            label = self._label(provider)
            if self.statuses.get(label) != "searching":
                continue   # finished after the time limit or after the search ended: ignored
            found = 0
            for item in raw:
                source = normalise(item, provider, provider["kind"])
                if source is None:
                    continue
                found += 1
                with self._lock:
                    existing = self._sources.get(source.key)
                    if existing is None or (source["seeds"] > existing["seeds"]):
                        self._sources[source.key] = source
            status = "failed" if outcome == "failed" else ("found" if found else "none")
            self.statuses[label] = status
            self.record(provider, status, found)

    def _time_out(self):
        if self.started is None or self.clock() - self.started < self.timeout:
            return
        for provider in self.providers:
            label = self._label(provider)
            if self.statuses[label] == "searching":
                self.statuses[label] = "timed out"
                self.record(provider, "timed out", 0)

    @property
    def finished(self):
        return all(s != "searching" for s in self.statuses.values())

    def cancel(self):
        self.cancelled = True
        self._finish_now()

    def stop_now(self):
        """"Choose from N found": stop waiting and use what's been found."""
        self._finish_now()

    def _finish_now(self):
        self._collect()
        for label, status in self.statuses.items():
            if status == "searching":
                self.statuses[label] = "stopped"

    def status(self):
        """A snapshot for the progress window, and a step of the search's bookkeeping."""
        self._collect()
        if not self.finished and self.early_stop.met(self.choosable()):
            self.stopped_early = True
            self._finish_now()
        self._time_out()
        sources = self.results()
        counts = {q: 0 for q in ("4K", "1080p", "720p")}
        counts["Other"] = 0
        for source in sources:
            counts[source["quality"] if source["quality"] in counts else "Other"] += 1
        done = sum(1 for s in self.statuses.values() if s != "searching")
        return {"elapsed": self.clock() - (self.started or self.clock()), "total": len(self.providers),
                "done": done, "counts": counts, "found": len(sources), "finished": self.finished,
                "choosable": len(self.choosable()),
                "early": (self.early_stop.progress(self.choosable()), self.early_stop.count)
                if self.early_stop.enabled else None,
                "searching": [label.split("/")[-1] for label, s in self.statuses.items() if s == "searching"],
                "stopped_early": self.stopped_early,
                "ready": sum(1 for s in sources if is_ready(s)) if self.checker else None,
                "checking": (sum(1 for s in sources if s.key not in self._checked)
                             if self.checker and not self.check_failed and not self.cancelled else 0),
                "check_failed": self.check_failed,
                "cloud": next(("searching" if state == "searching" else "finished"
                               for label, state in self.statuses.items() if label.split("/")[1] == "cloud"), None)}

    def results(self):
        with self._lock:
            return list(self._sources.values())

    def choosable(self):
        """The sources Source Select will show: everything, unless a filter was given. While Premiumize is
        being asked, a source only counts once it has answered for it, so the count doesn't jump up and
        then drop back when the uncached ones are hidden."""
        sources = self.results()
        if self.checker and not self.check_failed and not self.cancelled:
            with self._lock:
                checked = set(self._checked)
            sources = [s for s in sources if s.key in checked]
        return self.visible(sources) if self.visible else sources

    def wait(self, poll=0.2, sleep=time.sleep, should_stop=lambda: False):
        """Run to the end without a window (tests, and the simple fallback)."""
        while True:
            status = self.status()
            if status["finished"] or should_stop():
                return status
            sleep(poll)
