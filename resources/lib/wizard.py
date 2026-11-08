# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""First-run setup wizard: language, artwork quality and API keys, each key checked as it's entered."""

import xbmcgui

from resources.lib import accounts, keys, kodi
from resources.lib.strings import LANGUAGES

DONE_FLAG = "wizard_done"


def needed(app):
    return app.store.get_meta(DONE_FLAG) != "1"


def _language_labels():
    return [kodi.text(key) for _, key in LANGUAGES]


def _enter_key(app, dialog, name, attempts=3):
    """Ask for a key, check it with the service, save it. Returns True if a key was saved."""
    title = kodi.text("wizard_title")
    service = keys.SERVICES[name]
    value = kodi.setting_str(f"{name}.api_key").strip()
    for _ in range(attempts):
        value = (dialog.input(kodi.text("wizard_key_enter", service=service), defaultt=value) or "").strip()
        if not value:
            return False
        if name == "tmdb" and keys.looks_like_read_token(value):
            dialog.ok(title, kodi.text("wizard_tmdb_token"))
            value = ""
            continue
        result = keys.check(name, app.http, value)
        if result is False:
            dialog.ok(title, kodi.text("key_rejected", service=service))
            continue
        # Record the check first, so the service doesn't check the same key again when the setting changes.
        app.store.set_meta(f"keycheck:{name}", keys.fingerprint(value) if result else "")
        kodi.set_setting_str(f"{name}.api_key", value)
        if result is None:
            dialog.ok(title, kodi.text("key_unchecked", service=service))
        return True
    return False


def _optional_key(app, dialog, name, question_key):
    if dialog.yesno("SpongeTV", kodi.text(question_key), nolabel=kodi.text("no"), yeslabel=kodi.text("yes")):
        _enter_key(app, dialog, name)


def run(app):
    dialog = xbmcgui.Dialog()
    dialog.ok(kodi.text("wizard_title"), kodi.text("wizard_intro"))

    choice = dialog.select(kodi.text("wizard_language"), _language_labels(),
                           preselect=max(kodi.setting_int("metadata.language"), 0))
    if choice >= 0:
        kodi.set_setting_int("metadata.language", choice)

    presets = [kodi.text("preset_best"), kodi.text("preset_balanced"), kodi.text("preset_minimal")]
    current = kodi.setting_int("artwork.preset")
    choice = dialog.select(kodi.text("wizard_artwork"), presets, preselect=current if current < 3 else 1)
    if choice >= 0:
        kodi.set_setting_int("artwork.preset", choice)

    dialog.ok(kodi.text("wizard_title"), kodi.text("wizard_tmdb_ask"))
    if not _enter_key(app, dialog, "tmdb"):
        dialog.ok(kodi.text("wizard_title"), kodi.text("wizard_tmdb_skipped"))
    _optional_key(app, dialog, "fanart", "wizard_fanart_ask")
    _optional_key(app, dialog, "omdb", "wizard_omdb_ask")

    if not app.signed_in and dialog.yesno("SpongeTV", kodi.text("wizard_trakt_ask"),
                                          nolabel=kodi.text("not_now"), yeslabel=kodi.text("yes")):
        if accounts.ask_client_id(app, dialog):
            accounts.sign_in(app, dialog)

    app.store.set_meta(DONE_FLAG, "1")
    dialog.ok(kodi.text("wizard_title"), kodi.text("wizard_done"))
