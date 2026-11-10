# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Builds an installable zip in dist/.

Keys come from keys.local.json (never committed): {"trakt": "...", "tmdb": "...", "fanart": "", "omdb": ""}.
- The Trakt Client ID is always added: it isn't a secret (Trakt sends it openly with every request
  and new apps have no secret), and it lets people sign in without creating their own Trakt app.
- TMDB, Fanart.tv and OMDb keys are private, so users enter their own in the setup wizard. For
  private testing only, `--with-keys` adds them too. Never publish a zip built that way.
"""

import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_ID = "plugin.video.spongetv"
ALWAYS_INCLUDED = {"trakt", "premiumize"}   # client IDs, not secrets: needed for sign-in
INCLUDE = ["addon.xml", "main.py", "service.py", "LICENSE", "README.md", "changelog.txt", "resources"]
NEWS_LIMIT = 1500           # Kodi's schema refuses longer <news>
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def version():
    with open(os.path.join(ROOT, "addon.xml"), encoding="utf-8") as handle:
        text = handle.read()
    news = re.search(r"<news>(.*?)</news>", text, re.S)
    if news and len(news.group(1)) > NEWS_LIMIT:
        raise SystemExit(f"addon.xml <news> is {len(news.group(1))} characters; Kodi allows {NEWS_LIMIT}. "
                         "Move older entries to changelog.txt.")
    match = re.search(r'<addon[^>]*\sversion="([^"]+)"', text)
    return match.group(1)


def files():
    for entry in INCLUDE:
        path = os.path.join(ROOT, entry)
        if os.path.isfile(path):
            yield path
            continue
        for folder, dirs, names in os.walk(path):
            dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            for name in names:
                if name.endswith((".pyc", ".pyo")) or name == "_keys.json":
                    continue
                yield os.path.join(folder, name)


def main(with_keys=False):
    keys_path = os.path.join(ROOT, "keys.local.json")
    keys = {}
    if os.path.exists(keys_path):
        with open(keys_path, encoding="utf-8") as handle:
            keys = {k: v for k, v in json.load(handle).items() if v and (with_keys or k in ALWAYS_INCLUDED)}
    else:
        print("Warning: keys.local.json not found; the zip will have no built-in Trakt Client ID.")

    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", f"{ADDON_ID}-{version()}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files():
            archive.write(path, os.path.join(ADDON_ID, os.path.relpath(path, ROOT)))
        if keys:
            archive.writestr(f"{ADDON_ID}/resources/lib/_keys.json", json.dumps(keys))
    print(f"Built {os.path.relpath(out, ROOT)} with built-in keys: {', '.join(sorted(keys)) or 'none'}")
    return out


if __name__ == "__main__":
    sys.exit(0 if main(with_keys="--with-keys" in sys.argv[1:]) else 1)
