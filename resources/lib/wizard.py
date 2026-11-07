# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""First-run setup wizard: language, artwork quality and optional API keys."""

import xbmcgui

from resources.lib import kodi
from resources.lib.strings import LANGUAGES

DONE_FLAG = "wizard_done"


def needed(app):
    return app.store.get_meta(DONE_FLAG) != "1"


def _language_labels():
    return [kodi.text(key) for _, key in LANGUAGES]


def _ask_key(dialog, question_key, setting_id):
    if dialog.yesno("SpongeTV", kodi.text(question_key), nolabel=kodi.text("no"), yeslabel=kodi.text("yes")):
        value = dialog.input(kodi.text("wizard_enter_key")).strip()
        if value:
            kodi.set_setting_str(setting_id, value)


def run(app):
    dialog = xbmcgui.Dialog()
    dialog.ok(kodi.text("wizard_title"), kodi.text("wizard_intro"))

    choice = dialog.select(kodi.text("wizard_language"), _language_labels(),
                           preselect=max(kodi.setting_int("metadata.language"), 0))
    if choice >= 0:
        kodi.set_setting_int("metadata.language", choice)

    presets = [kodi.text("preset_best"), kodi.text("preset_balanced"), kodi.text("preset_minimal")]
    choice = dialog.select(kodi.text("wizard_artwork"), presets, preselect=kodi.setting_int("artwork.preset"))
    if choice >= 0:
        kodi.set_setting_int("artwork.preset", choice)

    if not app.key("tmdb"):
        _ask_key(dialog, "wizard_tmdb_ask", "tmdb.api_key")
    _ask_key(dialog, "wizard_fanart_ask", "fanart.api_key")
    _ask_key(dialog, "wizard_omdb_ask", "omdb.api_key")

    app.store.set_meta(DONE_FLAG, "1")
    dialog.ok(kodi.text("wizard_title"), kodi.text("wizard_done"))
