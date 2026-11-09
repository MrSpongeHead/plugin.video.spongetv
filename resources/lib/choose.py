# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Pressing play: find sources (or use recent results), then Source Select.

Stage 3 stops at your choice; turning a source into a playable link (Premiumize) and playing it
arrives in stage 4."""

import re

import xbmcgui

from resources.lib import artwork, kodi, ranking, windows
from resources.lib import sources as found_sources
from resources.lib.http import HttpError
from resources.lib.packages import Packages
from resources.lib.premiumize import PremiumizeError
from resources.lib.sources import EarlyStop, Search, Source, episode_request, movie_request, request_key

EARLY_QUALITIES = ["4K", "1080p", "720p", "SD"]
PRESET_KEYS = ["preset_custom", "preset_4k_hdr", "preset_1080p", "preset_data_saver", "preset_everything"]


def packages(app):
    manager = Packages(app.store, kodi.PROFILE, app.http)
    manager.ensure_import_path()
    return manager


def early_stop(ready_only=False):
    index = kodi.setting_int("early.quality")
    quality = EARLY_QUALITIES[index] if 0 <= index < len(EARLY_QUALITIES) else "1080p"
    return EarlyStop(kodi.setting_bool("early.enabled"), quality, kodi.setting_int("early.count") or 5, ready_only)


# -- filters ---------------------------------------------------------------------------------------
def filter_rules():
    """(label for the Filter button, the rules)"""
    preset = kodi.setting_int("filter.preset")
    if preset in ranking.PRESETS:
        return kodi.text(PRESET_KEYS[preset]), dict(ranking.PRESETS[preset],
                                                    ready_only=kodi.setting_bool("sources.hide_uncached"))
    rules = ranking.custom_filter((kodi.setting_bool, lambda sid: float(kodi.setting_int(sid))))
    return kodi.text("preset_custom"), dict(rules, ready_only=kodi.setting_bool("sources.hide_uncached"))


def pick_filter():
    """Choose a filter preset. True if it changed."""
    current = kodi.setting_int("filter.preset")
    picked = xbmcgui.Dialog().select(kodi.text("filter_heading"), [kodi.text(k) for k in PRESET_KEYS], preselect=current)
    if picked < 0 or picked == current:
        return False
    kodi.set_setting_int("filter.preset", picked)
    return True


# -- sort rules -------------------------------------------------------------------------------------
def edit_sort_rules(store):
    """Reorder, switch off or reset the sort rules. True if anything changed."""
    dialog = xbmcgui.Dialog()
    rules = ranking.load_rules(store)
    changed, selected = False, 0
    while True:
        rows = []
        for position, (rule, on) in enumerate(rules, 1):
            name = kodi.text(ranking.RULES[rule][0])
            rows.append(kodi.text("sort_row_on" if on else "sort_row_off", position=position, name=name))
        rows.append(kodi.text("sort_reset"))
        picked = dialog.select(kodi.text("sort_heading"), rows, preselect=selected)
        if picked < 0:
            return changed
        if picked == len(rules):
            ranking.reset_rules(store)
            rules = ranking.load_rules(store)
            changed = True
            continue
        rule, on = rules[picked]
        action = dialog.select(kodi.text(ranking.RULES[rule][0]),
                               [kodi.text("move_up"), kodi.text("move_down"), kodi.text("switch_off" if on else "switch_on")])
        selected = picked
        if action == 0 and picked > 0:
            rules[picked - 1], rules[picked] = rules[picked], rules[picked - 1]
            selected = picked - 1
        elif action == 1 and picked < len(rules) - 1:
            rules[picked + 1], rules[picked] = rules[picked], rules[picked + 1]
            selected = picked + 1
        elif action == 2:
            rules[picked] = (rule, not on)
        else:
            continue
        ranking.save_rules(store, rules)
        changed = True


def sort_rules_action(plugin, app):
    edit_sort_rules(app.store)


# -- the play flow ------------------------------------------------------------------------------------
def _request_for(app, params):
    """(request, title shown, meta line, poster, fanart) for a film or an episode."""
    media = params.get("media", "movie")
    if media == "movie":
        details = app.tmdb.movie(params.get("tmdb_id"))
        art = artwork.for_title(details, app.preset, app.language, None, kodi.FANART)
        year = (details.get("release_date") or "")[:4]
        title = f"{details.get('title', '')} ({year})" if year else details.get("title", "")
        runtime = int(details.get("runtime") or 0)
        meta = " · ".join(x for x in (year, kodi.text("runtime", hours=runtime // 60, minutes=runtime % 60) if runtime
                                            else "", ", ".join(g["name"] for g in details.get("genres", [])[:2])) if x)
        return movie_request(details), title, meta, art.get("poster", ""), art.get("fanart", "")
    show = app.tmdb.tv(params.get("tmdb_id"))
    season, number = int(params.get("season") or 0), int(params.get("episode") or 0)
    episodes = app.tmdb.season(show["id"], season).get("episodes", [])
    episode = next((e for e in episodes if int(e.get("episode_number") or 0) == number),
                   {"season_number": season, "episode_number": number, "name": ""})
    art = artwork.for_title(show, app.preset, app.language, None, kodi.FANART)
    title = f"{show.get('name', '')} S{season:02d}E{number:02d}"
    meta = " · ".join(x for x in (episode.get("name") or "", (episode.get("air_date") or "")[:4]) if x)
    return episode_request(show, episode), title, meta, art.get("poster", ""), art.get("fanart", "")


CLOUD_PROVIDER = {"package": "Premiumize", "language": "en", "kind": "cloud", "name": "Your cloud"}


def _call_with_cloud(app):
    """Providers as usual, plus your Premiumize cloud as one more 'provider'."""
    def call(provider, request, host_lists):
        if provider["kind"] != "cloud":
            return found_sources.call_provider(provider, request, host_lists)
        return [{"url": f"pmcloud:{f['id']}", "release_title": f["name"], "size": f["size"] / 1048576, "debrid": "cloud"}
                for f in app.premiumize.cloud_search(request)]
    return call


def _host_lists(app):
    if not kodi.setting_bool("premiumize.hosters") or not app.premiumize.ready:
        return [], []
    try:
        return app.premiumize.hosts(), []
    except PremiumizeError as error:
        kodi.log(f"Couldn't get Premiumize's hosters: {error}")
        return [], []


def _checker(app):
    """Marks sources ready / not cached with Premiumize, or None without an API key."""
    client = app.premiumize
    if not client.ready:
        return None
    use_torrents, use_hosters = kodi.setting_bool("premiumize.torrents"), kodi.setting_bool("premiumize.hosters")

    def check(sources):
        wanted = [s for s in sources if (s["type"] == "torrent" and use_torrents) or (s["type"] == "hosters" and use_hosters)]
        client.mark_ready(wanted)
    return check


def find_sources(app, params, prepared=None, fresh=False):
    """Search (or reuse recent results). Returns (request, title, meta, poster, fanart, results, clear) or None.
    prepared: (request, title, meta, poster, fanart) instead of looking the title up on TMDB (window tests)."""
    try:
        request, title, meta, poster, fanart = prepared or _request_for(app, params)
    except HttpError:
        kodi.notify(kodi.text("tmdb_unreachable"))
        return None
    manager = packages(app)
    providers = manager.providers(enabled_only=True)
    key = request_key(request)
    hours = kodi.setting_int("sources.cache_hours")
    if fresh:
        app.store.cache_delete(key)   # "Search again": forget what was found before
    saved = app.store.cache_get(key) if hours > 0 and not fresh else None
    if saved:
        results = [Source(s) for s in saved]
        for source in results:   # results saved by an older version may have a cinema recording labelled 1080p
            if re.search(found_sources.CAM_PATTERN, found_sources._words(source.get("release_title"))):
                source["quality"] = "CAM"
        checker = _checker(app)
        if checker:    # readiness changes faster than the results: check again
            try:
                checker([s for s in results if s.get("debrid") != "cloud"])
            except PremiumizeError as error:
                kodi.log(f"Couldn't check saved sources: {error}")
    else:
        if app.premiumize.ready and kodi.setting_bool("premiumize.cloud"):
            providers = providers + [CLOUD_PROVIDER]
        if not providers:
            kodi.notify(kodi.text("no_providers"))
            return None
        checker = _checker(app)
        early = early_stop(ready_only=checker is not None)
        search = Search(providers, request, timeout=max(kodi.setting_int("sources.timeout"), 5), early_stop=early,
                        host_lists=_host_lists(app), call=_call_with_cloud(app), checker=checker,
                        record=lambda p, status, count: p["kind"] == "cloud" or manager.record_result(
                            p["package"], p["kind"], p["name"], status, count)).start()
        outcome = windows.run_search(search, title, fanart, early)
        if outcome == "cancelled":
            return None
        search.check_new()
        results = search.results()
        if results and hours > 0:
            app.store.cache_set(key, [dict(s) for s in results], hours * 3600)
    if not results:
        kodi.notify(kodi.text("no_sources_found"))
        return None

    def clear():
        app.store.cache_delete(key)
        kodi.notify(kodi.text("results_cleared"))
    return request, title, meta, poster, fanart, results, clear


def play(plugin, app):
    from resources.lib import playback
    playback.play(plugin, app)


def clear_results(plugin, app):
    app.store.cache_delete_matching("sources:%")
    kodi.notify(kodi.text("results_cleared"))


# -- window tests (developer setting) ------------------------------------------------------------------
SAMPLE_TITLE = "The Lighthouse Keeper (2024)"


def sample_sources():
    raw = [("2160p.UHD.BluRay.HDR.HEVC.Atmos", 18400, 140, "cached"), ("2160p.WEB-DL.DV.HDR.HEVC.5.1", 21000, 95, "cached"),
           ("1080p.WEB-DL.H264.5.1", 8200, 0, "cloud"), ("1080p.WEB-DL.HEVC.5.1", 4600, 220, "cached"),
           ("1080p.BluRay.x264.5.1", 9100, 310, "cached"), ("1080p.WEBRip.HEVC", 2900, 60, "uncached"),
           ("720p.WEB-DL.x264", 1400, 80, ""), ("480p.DVDRip.x264", 700, 12, "")]
    provider = {"name": "Test provider", "package": "SpongeTVTest"}
    out = []
    for i, (variant, size, seeds, debrid) in enumerate(raw):
        source = found_sources.normalise({"hash": f"{i:040x}", "release_title": f"The.Lighthouse.Keeper.2024.{variant}",
                                          "size": size, "seeds": seeds}, provider, "torrent")
        source["debrid"] = debrid
        out.append(source)
    return out


def window_test(plugin, app):
    """Open a window with made-up data, to check how it looks (Settings, Advanced, developer)."""
    which = plugin.params.get("window", "select")
    if which == "next":   # the Playing Next card, counting down from 20 seconds
        from resources.lib import smartplay
        import xbmc
        window = smartplay.PlayingNextWindow(smartplay.NEXT_XML, kodi.ADDON_PATH, "Default", "1080i")
        values = {"heading": kodi.text("playing_next"), "show": "Harbour Lights",
                  "episode": kodi.text("next_episode_line", season=2, episode=5, title="The Long Tide"),
                  "thumb": kodi.FANART, "play_now": kodi.text("play_now"), "stop_after": kodi.text("stop_after")}
        for key, value in values.items():
            window.setProperty(key, value)
        window.show()
        monitor = xbmc.Monitor()
        for tenth in range(200, -1, -1):
            status = kodi.text("next_ready") if tenth < 150 else kodi.text("next_finding")
            window.setProperty("status", kodi.text("next_countdown", seconds=tenth // 10, status=status))
            try:
                window.getControl(4100).setPercent(tenth / 2)
            except (RuntimeError, TypeError):
                pass
            if window.choice or monitor.waitForAbort(0.1):
                break
        window.close()
        del window
        return
    if which == "play":   # the real play pipeline for a made-up film (no TMDB needed)
        from resources.lib import playback
        playback.play(plugin, app, target=playback.Target.sample())
        return
    if which == "live":   # a real search with your providers, for a made-up film (no TMDB needed)
        request = movie_request({"id": 0, "title": "The Lighthouse Keeper", "release_date": "2024-05-01",
                                 "imdb_id": "tt0000000"})
        manager = packages(app)
        early = early_stop()
        search = Search(manager.providers(enabled_only=True), request, timeout=max(kodi.setting_int("sources.timeout"), 5),
                        early_stop=early).start()
        if windows.run_search(search, SAMPLE_TITLE, kodi.FANART, early) == "cancelled" or not search.results():
            kodi.notify(kodi.text("no_sources_found"))
            return
        chooser = windows.Chooser(search.results(), "movie", SAMPLE_TITLE, "", kodi.ICON, kodi.FANART, filter_rules,
                                  lambda: ranking.load_rules(app.store),
                                  {"filter": pick_filter, "sort": lambda: edit_sort_rules(app.store), "clear": lambda: None})
        windows.choose_source(chooser)
        return
    if which == "search":
        class FakeSearch:
            def __init__(self):
                self.polls = 0

            def status(self):
                self.polls += 1
                step = min(self.polls, 40)
                return {"elapsed": step * 0.2, "total": 7, "done": min(step // 6, 7),
                        "counts": {"4K": 1, "1080p": 2 + step // 20, "720p": 1, "Other": 0}, "found": 4 + step // 20,
                        "finished": self.polls > 60, "early": (3, 5), "searching": ["bubblesearch", "coral", "slow"],
                        "stopped_early": False}

            def cancel(self):
                pass

            def stop_now(self):
                pass
        windows.run_search(FakeSearch(), SAMPLE_TITLE, kodi.FANART, EarlyStop(True, "1080p", 5))
        return
    chooser = windows.Chooser(sample_sources(), "movie", SAMPLE_TITLE, "2024 · 1 h 52 min · Drama",
                              kodi.ICON, kodi.FANART, filter_rules, lambda: ranking.load_rules(app.store),
                              {"filter": pick_filter, "sort": lambda: edit_sort_rules(app.store), "clear": lambda: None})
    windows.choose_source(chooser)
