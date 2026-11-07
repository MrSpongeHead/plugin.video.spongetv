# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Writes resources/language/resource.language.en_gb/strings.po from resources/lib/strings.py."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from resources.lib.strings import STRINGS  # noqa: E402

PO_PATH = os.path.join(ROOT, "resources", "language", "resource.language.en_gb", "strings.po")

HEADER = '''# Kodi Media Center language file
# Addon Name: SpongeTV
# Addon id: plugin.video.spongetv
# Addon Provider: MrSpongeHead
msgid ""
msgstr ""
"Project-Id-Version: plugin.video.spongetv\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: en_GB\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"
'''


def render():
    lines = [HEADER]
    for string_id, english in sorted(STRINGS.values()):
        escaped = english.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'msgctxt "#{string_id}"\nmsgid "{escaped}"\nmsgstr ""\n')
    return "\n".join(lines)


def main():
    ids = [string_id for string_id, _ in STRINGS.values()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise SystemExit(f"Duplicate string IDs: {sorted(duplicates)}")
    os.makedirs(os.path.dirname(PO_PATH), exist_ok=True)
    with open(PO_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render())
    print(f"Wrote {len(STRINGS)} strings to {os.path.relpath(PO_PATH, ROOT)}")


if __name__ == "__main__":
    main()
