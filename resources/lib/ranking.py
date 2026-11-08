# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Filtering and sorting sources, and saying why each one is ranked where it is.

Filters: which qualities to allow, a size limit, and tags to leave out (CAM and 3D by default),
with presets ("4K HDR", "1080p", "Data saver", "Everything") or your own choices in Settings.

Sorting: an ordered list of rules you can reorder, switch off and reset (stored in the database).
The first rule that tells two sources apart decides their order, so "Why this order" can name it.
"""

import json

from resources.lib.sources import QUALITY_RANK

# -- filters -----------------------------------------------------------------------------------
CUSTOM, PRESET_4K_HDR, PRESET_1080P, PRESET_DATA_SAVER, PRESET_EVERYTHING = range(5)
PRESETS = {
    PRESET_4K_HDR: {"qualities": {"4K"}, "require_any": {"HDR", "Dolby Vision"}, "exclude": {"CAM", "3D"},
                    "max_gb_movie": 0, "max_gb_episode": 0},
    PRESET_1080P: {"qualities": {"1080p"}, "require_any": set(), "exclude": {"CAM", "3D"},
                   "max_gb_movie": 0, "max_gb_episode": 0},
    PRESET_DATA_SAVER: {"qualities": {"1080p", "720p"}, "require_any": set(), "exclude": {"CAM", "3D", "Remux"},
                        "max_gb_movie": 4, "max_gb_episode": 1.5},
    PRESET_EVERYTHING: {"qualities": {"4K", "1080p", "720p", "SD", "CAM"}, "require_any": set(), "exclude": set(),
                        "max_gb_movie": 0, "max_gb_episode": 0},
}


def custom_filter(settings):
    """settings: callables bool_of(id) and number_of(id), so this stays testable without Kodi."""
    bool_of, number_of = settings
    qualities = {q for q, sid in (("4K", "filter.allow_4k"), ("1080p", "filter.allow_1080p"),
                                  ("720p", "filter.allow_720p"), ("SD", "filter.allow_sd")) if bool_of(sid)}
    exclude = {tag for tag, sid in (("CAM", "filter.exclude_cam"), ("3D", "filter.exclude_3d"),
                                    ("HEVC", "filter.exclude_hevc"), ("HDR", "filter.exclude_hdr"),
                                    ("Dolby Vision", "filter.exclude_dv")) if bool_of(sid)}
    if "CAM" not in exclude:
        qualities.add("CAM")
    return {"qualities": qualities, "require_any": set(), "exclude": exclude,
            "max_gb_movie": number_of("filter.max_gb_movie"), "max_gb_episode": number_of("filter.max_gb_episode")}


def apply_filter(sources, rules, media):
    limit_gb = rules["max_gb_movie"] if media == "movie" else rules["max_gb_episode"]
    kept = []
    for source in sources:
        tags = set(source.get("tags") or [])
        if source["quality"] not in rules["qualities"]:
            continue
        if source["quality"] in rules["exclude"] or tags & rules["exclude"]:
            continue
        if rules["require_any"] and not tags & rules["require_any"]:
            continue
        if limit_gb and source.get("size_mb") and source["size_mb"] > limit_gb * 1024:
            continue
        if rules.get("ready_only") and source.get("debrid") == "uncached":
            continue
        kept.append(source)
    return kept


# -- sorting -------------------------------------------------------------------------------------
# rule id -> (label key, key function: smaller sorts first)
RULES = {
    "ready": ("sortrule_ready", lambda s: {"cloud": 0, "cached": 1, "uncached": 3}.get(
        s.get("debrid"), 1 if s["type"] in ("direct", "adaptive") else 2)),
    "quality": ("sortrule_quality", lambda s: QUALITY_RANK.get(s["quality"], 99)),
    "hdr": ("sortrule_hdr", lambda s: 0 if {"HDR", "Dolby Vision"} & set(s.get("tags") or []) else 1),
    "hevc": ("sortrule_hevc", lambda s: 0 if {"HEVC", "AV1"} & set(s.get("tags") or []) else 1),
    "size_large": ("sortrule_size_large", lambda s: -(s.get("size_mb") or 0)),
    "size_small": ("sortrule_size_small", lambda s: (s.get("size_mb") or 0) or 10 ** 9),
    "seeds": ("sortrule_seeds", lambda s: -(s.get("seeds") or 0)),
    "direct": ("sortrule_direct", lambda s: {"direct": 0, "adaptive": 1, "hosters": 2, "torrent": 3}.get(s["type"], 4)),
}
DEFAULT_RULES = [("ready", True), ("quality", True), ("hdr", False), ("hevc", False), ("size_large", True),
                 ("size_small", False), ("seeds", True), ("direct", False)]


def load_rules(store):
    """[(rule id, on)] in order; any rule added in a later version is appended, switched off."""
    try:
        saved = [(r, bool(on)) for r, on in json.loads(store.get_meta("sort_rules") or "[]") if r in RULES]
    except (ValueError, TypeError):
        saved = []
    if not saved:
        return list(DEFAULT_RULES)
    known = {r for r, _ in saved}
    return saved + [(r, False) for r, _ in DEFAULT_RULES if r not in known]


def save_rules(store, rules):
    store.set_meta("sort_rules", json.dumps(rules))


def reset_rules(store):
    store.set_meta("sort_rules", "")


def _active(rules):
    return [r for r, on in rules if on]


def sort_sources(sources, rules):
    active = _active(rules)
    return sorted(sources, key=lambda s: tuple(RULES[r][1](s) for r in active))


def deciding_rule(source, previous, rules):
    """The rule that put source below previous (None if they tie on every rule)."""
    for rule in _active(rules):
        key = RULES[rule][1]
        if key(previous) != key(source):
            return rule
    return None


def size_text(size_mb):
    if not size_mb:
        return ""
    return f"{size_mb / 1024:.1f} GB" if size_mb >= 1024 else f"{size_mb:.0f} MB"
