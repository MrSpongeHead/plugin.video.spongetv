# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Builds an installable zip in dist/.

The zip contains no API keys: users enter their own in the setup wizard.
For private testing only, `--with-keys` adds keys from keys.local.json (never committed),
which looks like: {"tmdb": "...", "fanart": "", "omdb": ""}. Never publish a zip built that way.
"""

import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_ID = "plugin.video.spongetv"
INCLUDE = ["addon.xml", "main.py", "service.py", "LICENSE", "README.md", "resources"]
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def version():
    with open(os.path.join(ROOT, "addon.xml"), encoding="utf-8") as handle:
        match = re.search(r'<addon[^>]*\sversion="([^"]+)"', handle.read())
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
    if not with_keys:
        pass
    elif os.path.exists(keys_path):
        with open(keys_path, encoding="utf-8") as handle:
            keys = {k: v for k, v in json.load(handle).items() if v}
    else:
        print("Warning: keys.local.json not found; the zip will have no built-in API keys.")

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
