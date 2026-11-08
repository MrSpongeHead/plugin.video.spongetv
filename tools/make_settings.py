# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Writes resources/settings.xml from the layout below, using string IDs from strings.py."""

import os
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


def key(sid_, label):
    return (f'                <setting id="{sid_}" type="string" label="{sid(label)}">\n'
            f'                    <level>0</level>\n                    <default/>\n'
            f'                    <constraints>\n                        <allowempty>true</allowempty>\n                    </constraints>\n'
            f'                    <control type="edit" format="string">\n                        <heading>{sid(label)}</heading>\n'
            f'                    </control>\n                </setting>\n')


def number(sid_, label, default, minimum, maximum, step=None, slider=False, level=2):
    step_xml = f"\n                        <step>{step}</step>" if step else ""
    control = ('<control type="slider" format="integer">\n                        <popup>false</popup>\n                    </control>'
               if slider else f'<control type="edit" format="integer">\n                        <heading>{sid(label)}</heading>\n                    </control>')
    return (f'                <setting id="{sid_}" type="integer" label="{sid(label)}">\n'
            f'                    <level>{level}</level>\n                    <default>{default}</default>\n'
            f'                    <constraints>\n                        <minimum>{minimum}</minimum>{step_xml}\n'
            f'                        <maximum>{maximum}</maximum>\n                    </constraints>\n'
            f'                    {control}\n                </setting>\n')


def action(sid_, label, plugin_action):
    return (f'                <setting id="{sid_}" type="action" label="{sid(label)}">\n'
            f'                    <level>0</level>\n'
            f'                    <data>RunPlugin(plugin://plugin.video.spongetv/?action={escape(plugin_action)})</data>\n'
            f'                    <constraints>\n                        <allowempty>true</allowempty>\n                    </constraints>\n'
            f'                    <control type="button" format="action">\n                        <close>true</close>\n'
            f'                    </control>\n                </setting>\n')


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
                     + boolean("hide.episodes.unaired", "set_hide_episodes_unaired", True))
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
    accounts = group("keys", "grp_keys", key("tmdb.api_key", "set_tmdb_key") + key("fanart.api_key", "set_fanart_key")
                     + key("omdb.api_key", "set_omdb_key") + action("action.wizard", "run_wizard", "wizard"))
    views = "".join(number(f"view.{v}", f"set_view_{v}", 0, 0, 9999) for v in ("movies", "tvshows", "seasons", "episodes"))
    advanced = group("views", "grp_views", views)
    advanced += group("performance", "grp_performance",
                      number("perf.workers", "set_workers", 8, 2, 16, step=1, slider=True)
                      + boolean("perf.menu_cache", "set_menu_cache", True, level=2))
    advanced += group("maintenance", "grp_maintenance",
                      number("cache.size_mb", "set_cache_size", 100, 10, 1000, step=10, slider=True)
                      + action("action.clear_cache", "clear_cache", "clear_cache")
                      + action("action.clear_all", "clear_all_caches", "clear_all"))
    body = (category("general", "cat_general", general) + category("artwork", "cat_artwork", art)
            + category("accounts", "cat_accounts", accounts) + category("advanced", "cat_advanced", advanced))
    return ('<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n<settings version="1">\n'
            '    <section id="plugin.video.spongetv">\n' + body + '    </section>\n</settings>\n')


if __name__ == "__main__":
    with open(os.path.join(ROOT, "resources", "settings.xml"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render())
    print("Wrote resources/settings.xml")
