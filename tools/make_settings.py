# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Writes resources/settings.xml from the layout below, using string IDs from strings.py."""

import os
import re
import sys
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from resources.lib.strings import LANGUAGES, STRINGS  # noqa: E402


def sid(key):
    return STRINGS[key][0]


def options(keys):
    rows = "".join(f'\n                            <option label="{sid(k)}">{i}</option>' for i, k in enumerate(keys))
    return f"\n                    <constraints>\n                        <options>{rows}\n                        </options>\n                    </constraints>"


def visible_if(setting, value):
    return (f'\n                    <dependencies>\n                        <dependency type="visible">\n'
            f'                            <condition operator="is" setting="{setting}">{value}</condition>\n'
            f'                        </dependency>\n                    </dependencies>')


def boolean(sid_, label, default, level=0, extra=""):
    return (f'                <setting id="{sid_}" type="boolean" label="{sid(label)}">\n'
            f'                    <level>{level}</level>\n                    <default>{str(default).lower()}</default>{extra}\n'
            f'                    <control type="toggle"/>\n                </setting>\n')


def choice(sid_, label, keys, default, level=0, extra=""):
    return (f'                <setting id="{sid_}" type="integer" label="{sid(label)}">\n'
            f'                    <level>{level}</level>\n                    <default>{default}</default>{options(keys)}{extra}\n'
            f'                    <control type="list" format="string"/>\n                </setting>\n')


def key(sid_, label, level=0):
    return (f'                <setting id="{sid_}" type="string" label="{sid(label)}">\n'
            f'                    <level>{level}</level>\n                    <default/>\n'
            f'                    <constraints>\n                        <allowempty>true</allowempty>\n                    </constraints>\n'
            f'                    <control type="edit" format="string">\n                        <heading>{sid(label)}</heading>\n'
            f'                    </control>\n                </setting>\n')


def hidden_text(sid_):
    """A setting SpongeTV keeps for itself (such as Trakt tokens): never shown."""
    return (f'                <setting id="{sid_}" type="string">\n'
            f'                    <level>4</level>\n                    <default/>\n'
            f'                    <constraints>\n                        <allowempty>true</allowempty>\n                    </constraints>\n'
            f'                    <visible>false</visible>\n'
            f'                    <control type="edit" format="string"/>\n                </setting>\n')


def number(sid_, label, default, minimum, maximum, step=None, slider=False, level=2, extra=""):
    step_xml = f"\n                        <step>{step}</step>" if step else ""
    control = ('<control type="slider" format="integer">\n                        <popup>false</popup>\n                    </control>'
               if slider else f'<control type="edit" format="integer">\n                        <heading>{sid(label)}</heading>\n                    </control>')
    return (f'                <setting id="{sid_}" type="integer" label="{sid(label)}">\n'
            f'                    <level>{level}</level>\n                    <default>{default}</default>{extra}\n'
            f'                    <constraints>\n                        <minimum>{minimum}</minimum>{step_xml}\n'
            f'                        <maximum>{maximum}</maximum>\n                    </constraints>\n'
            f'                    {control}\n                </setting>\n')


def action(sid_, label, plugin_action, extra=""):
    return (f'                <setting id="{sid_}" type="action" label="{sid(label)}">\n'
            f'                    <level>0</level>{extra}\n'
            f'                    <data>RunPlugin(plugin://plugin.video.spongetv/?action={escape(plugin_action)})</data>\n'
            f'                    <constraints>\n                        <allowempty>true</allowempty>\n                    </constraints>\n'
            f'                    <control type="button" format="action">\n                        <close>true</close>\n'
            f'                    </control>\n                </setting>\n')


def with_help(xml):
    """Give every setting with a help_<id> string a help attribute (the line Kodi shows at the bottom)."""
    def add(match):
        key = "help_" + match.group(1).replace(".", "_")
        if key not in STRINGS:                      # a view's status line shares the view's help
            key = key.replace("_status", "")
        return f'{match.group(0)} help="{sid(key)}"' if key in STRINGS else match.group(0)
    return re.sub(r'<setting id="([^"]+)"', add, xml)


def status(sid_, label):
    """A greyed-out line SpongeTV fills in itself, such as which account you're signed in to."""
    return (f'                <setting id="{sid_}" type="string" label="{sid(label)}">\n'
            f'                    <level>0</level>\n                    <default/>\n                    <enable>false</enable>\n'
            f'                    <constraints>\n                        <allowempty>true</allowempty>\n                    </constraints>\n'
            f'                    <control type="edit" format="string">\n                        <heading>{sid(label)}</heading>\n'
            f'                    </control>\n                </setting>\n')


def hidden_text(sid_):
    """Text SpongeTV keeps for itself: never shown."""
    return (f'                <setting id="{sid_}" type="string">\n'
            f'                    <level>4</level>\n                    <default/>\n'
            f'                    <constraints>\n                        <allowempty>true</allowempty>\n                    </constraints>\n'
            f'                    <visible>false</visible>\n'
            f'                    <control type="edit" format="string"/>\n                </setting>\n')


def hidden_flag(sid_):
    """A yes/no SpongeTV keeps for itself, for showing the right buttons: never shown."""
    return (f'                <setting id="{sid_}" type="boolean">\n'
            f'                    <level>4</level>\n                    <default>false</default>\n'
            f'                    <visible>false</visible>\n'
            f'                    <control type="toggle"/>\n                </setting>\n')


def group(gid, label, body):
    return f'            <group id="{gid}" label="{sid(label)}">\n{body}            </group>\n'


def category(cid, label, body):
    return f'        <category id="{cid}" label="{sid(label)}">\n{body}        </category>\n'


def render():
    general = group("display", "grp_display",
                    choice("metadata.language", "set_language", [k for _, k in LANGUAGES], 0)
                    + boolean("metadata.original_titles", "set_original_titles", False)
                    + choice("display.episode_label", "set_episode_label", ["ep_title", "ep_1x01", "ep_s01e01"], 0)
                    + boolean("display.flatten_seasons", "set_flatten", False)
                    + boolean("display.all_studios", "set_all_studios", False)
                    + choice("display.highlight", "set_highlight",
                             ["colour_amber", "colour_teal", "colour_mint", "colour_blue", "colour_white", "colour_none"], 0)
                    + boolean("general.notification_sound", "set_notification_sound", True))
    general += group("hide", "grp_hide",
                     boolean("hide.movie_lists.unreleased", "set_hide_movie_lists", False)
                     + boolean("hide.tv_lists.unaired", "set_hide_tv_lists", False)
                     + boolean("hide.search.unreleased", "set_hide_search", False)
                     + boolean("hide.seasons.specials", "set_hide_seasons_specials", False)
                     + boolean("hide.seasons.unaired", "set_hide_seasons_unaired", True)
                     + boolean("hide.episodes.unaired", "set_hide_episodes_unaired", True)
                     + boolean("hide.movie_lists.watched", "set_hide_movie_lists_watched", False)
                     + boolean("hide.tv_lists.watched", "set_hide_tv_lists_watched", False)
                     + boolean("hide.search.watched", "set_hide_search_watched", False)
                     + boolean("hide.seasons.watched", "set_hide_seasons_watched", False)
                     + boolean("hide.episodes.watched", "set_hide_episodes_watched", False))
    general += group("trakt", "grp_trakt",
                     number("trakt.sync_minutes", "set_sync_minutes", 15, 5, 120, step=5, slider=True, level=0)
                     + choice("nextup.sort", "set_nextup_sort", ["nextup_last_watched", "nextup_air_date"], 0)
                     + number("trakt.resume_max_age", "set_resume_max_age", 60, 0, 365, step=15, slider=True, level=0))
    advanced_only = visible_if("artwork.preset", 3)
    # The Advanced sizes sit in the same group as the preset, straight under it: Kodi shows and hides
    # settings as you change the preset, but never hides a group's heading, even when it's empty.
    art = group("artwork", "cat_artwork",
                choice("artwork.preset", "set_artwork_preset",
                       ["preset_best", "preset_balanced", "preset_minimal", "preset_advanced"], 1)
                + choice("artwork.poster_size", "set_poster_size",
                        ["size_small_342", "size_medium_500", "size_large_780", "size_original"], 2, extra=advanced_only)
                 + choice("artwork.fanart_size", "set_fanart_size",
                          ["size_medium_780", "size_large_1280", "size_original"], 1, extra=advanced_only)
                 + choice("artwork.still_size", "set_still_size", ["size_small_300", "size_original"], 0, extra=advanced_only)
                 + boolean("artwork.extras", "set_extras", True, extra=advanced_only))
    accounts = group("trakt_account", "grp_trakt_account",
                     status("trakt.status", "set_account_status") + hidden_flag("trakt.signed_in")
                     + action("action.trakt_sign_in", "trakt_sign_in", "trakt_sign_in",
                              extra=visible_if("trakt.signed_in", "false"))
                     + action("action.trakt_sign_out", "trakt_sign_out", "trakt_sign_out",
                              extra=visible_if("trakt.signed_in", "true"))
                     # SpongeTV's own Client ID is built in: these are only for your own Trakt app (Expert level)
                     + key("trakt.client_id", "set_trakt_client_id", level=3)
                     + key("trakt.client_secret", "set_trakt_client_secret", level=3)
                     + hidden_text("trakt.token") + hidden_text("trakt.username"))
    accounts += group("premiumize", "grp_premiumize",
                      status("premiumize.status", "set_account_status") + hidden_flag("premiumize.signed_in")
                      + action("action.pm_sign_in", "pm_sign_in", "premiumize_sign_in",
                               extra=visible_if("premiumize.signed_in", "false"))
                      + action("action.pm_sign_out", "pm_sign_out", "premiumize_sign_out",
                               extra=visible_if("premiumize.signed_in", "true"))
                      + boolean("premiumize.torrents", "set_pm_torrents", True)
                      + boolean("premiumize.hosters", "set_pm_hosters", True)
                      + boolean("premiumize.cloud", "set_pm_cloud", True)
                      + action("action.premiumize_status", "premiumize_status", "premiumize_status",
                               extra=visible_if("premiumize.signed_in", "true"))
                      # Expert level: an API key instead of signing in, or your own registered client ID
                      + key("premiumize.api_key", "set_premiumize_key", level=3)
                      + key("premiumize.client_id", "set_pm_client_id", level=3)
                      + hidden_text("premiumize.token"))
    accounts += group("keys", "grp_keys", key("tmdb.api_key", "set_tmdb_key") + key("fanart.api_key", "set_fanart_key")
                      + key("omdb.api_key", "set_omdb_key") + action("action.wizard", "run_wizard", "wizard"))
    custom_only = visible_if("filter.preset", 0)
    sources = group("search", "grp_search",
                    number("sources.timeout", "set_timeout", 30, 10, 120, step=5, slider=True, level=0)
                    + boolean("early.enabled", "set_early_enabled", True)
                    + choice("early.quality", "set_early_quality", ["q_4k", "q_1080p", "q_720p", "q_sd"], 1,
                             extra=visible_if("early.enabled", "true"))
                    + number("early.count", "set_early_count", 5, 1, 50, step=1, slider=True, level=0)
                    + number("sources.cache_hours", "set_cache_hours", 3, 0, 24, step=1, slider=True, level=0)
                    + boolean("sources.hide_uncached", "set_hide_uncached", True))
    # The custom filter settings share the preset's group, so nothing is left behind when they hide.
    sources += group("filter", "grp_filter",
                     choice("filter.preset", "set_filter_preset", ["preset_custom", "preset_4k_hdr", "preset_1080p",
                                                                   "preset_data_saver", "preset_everything"], 0)
                     + boolean("filter.allow_4k", "set_allow_4k", True, extra=custom_only)
                     + boolean("filter.allow_1080p", "set_allow_1080p", True, extra=custom_only)
                     + boolean("filter.allow_720p", "set_allow_720p", True, extra=custom_only)
                     + boolean("filter.allow_sd", "set_allow_sd", True, extra=custom_only)
                     + boolean("filter.exclude_cam", "set_exclude_cam", True, extra=custom_only)
                     + boolean("filter.exclude_3d", "set_exclude_3d", True, extra=custom_only)
                     + boolean("filter.exclude_hevc", "set_exclude_hevc", False, extra=custom_only)
                     + boolean("filter.exclude_hdr", "set_exclude_hdr", False, extra=custom_only)
                     + boolean("filter.exclude_dv", "set_exclude_dv", False, extra=custom_only)
                     + number("filter.max_gb_movie", "set_max_gb_movie", 0, 0, 100, step=1, slider=True, level=0)
                     .replace("</level>", "</level>" + custom_only, 1)
                     + number("filter.max_gb_episode", "set_max_gb_episode", 0, 0, 50, step=1, slider=True, level=0)
                     .replace("</level>", "</level>" + custom_only, 1))
    sources += group("sorting", "grp_sorting", action("action.sort_rules", "edit_sort_rules", "sort_rules"))
    sources += group("packages", "grp_packages",
                     choice("packages.updates", "set_package_updates", ["updates_off", "updates_tell", "updates_install"], 1)
                     + action("action.providers", "open_providers", "providers_open")
                     + hidden_text("packages.last_url"))
    playback = group("play_choice", "grp_play_choice",
                     choice("play.movies", "set_play_movies", ["play_source_select", "play_auto"], 0)
                     + choice("play.episodes", "set_play_episodes", ["play_source_select", "play_auto"], 0)
                     + number("play.attempts", "set_play_attempts", 3, 1, 10, step=1, slider=True, level=0))
    playback += group("play_next", "grp_play_next",
                      boolean("play.next", "set_play_next", True)
                      + number("play.next_seconds", "set_next_seconds", 30, 10, 120, step=5, slider=True, level=0)
                      + boolean("play.next_credits", "set_next_credits", True)
                      + number("play.credits_delay", "set_credits_delay", 5, 0, 30, step=5, slider=True, level=0,
                               extra=visible_if("play.next_credits", "true"))
                      + number("play.still_watching", "set_still_watching", 3, 0, 10, step=1, slider=True, level=0))
    views = "".join(status(f"view.{v}_status", f"set_view_{v}")
                    + number(f"view.{v}", f"set_view_{v}", 0, 0, 99999, level=4, extra="\n                    <visible>false</visible>")
                    + hidden_text(f"view.{v}_name") + hidden_text(f"view.{v}_skin")
                    for v in ("movies", "tvshows", "seasons", "episodes"))
    views += action("action.reset_views", "reset_views", "reset_views")
    advanced = group("views", "grp_views", views)
    advanced += group("performance", "grp_performance",
                      number("perf.workers", "set_workers", 8, 2, 16, step=1, slider=True)
                      + boolean("perf.menu_cache", "set_menu_cache", True, level=2))
    advanced += group("maintenance", "grp_maintenance",
                      number("cache.size_mb", "set_cache_size", 100, 10, 1000, step=10, slider=True)
                      + action("action.clear_cache", "clear_cache", "clear_cache")
                      + action("action.clear_all", "clear_all_caches", "clear_all"))
    advanced += group("windows", "grp_windows", boolean("windows.simple", "set_windows_simple", False))
    advanced += group("developer", "grp_developer", boolean("developer.window_tests", "set_window_tests", False, level=3))
    body = (category("general", "cat_general", general) + category("artwork", "cat_artwork", art)
            + category("sources", "cat_sources", sources)
            + category("playback", "cat_playback", playback)
            + category("accounts", "cat_accounts", accounts) + category("advanced", "cat_advanced", advanced))
    return ('<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n<settings version="1">\n'
            '    <section id="plugin.video.spongetv">\n' + body + '    </section>\n</settings>\n')


if __name__ == "__main__":
    with open(os.path.join(ROOT, "resources", "settings.xml"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(with_help(render()))
    print("Wrote resources/settings.xml")
