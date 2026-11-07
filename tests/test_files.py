# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks that addon.xml, settings.xml, strings.po and the code agree with each other."""

import os
import re
import xml.etree.ElementTree as ET

from conftest import ROOT
from resources.lib.strings import LANGUAGES, STRINGS
from resources.lib.options import HIDE
from tools import make_settings, make_strings


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def test_addon_xml():
    addon = ET.fromstring(read("addon.xml"))
    assert addon.get("id") == "plugin.video.spongetv"
    assert re.fullmatch(r"\d+\.\d+\.\d+", addon.get("version"))
    assert addon.find(".//license").text == "GPL-3.0-or-later"
    for asset in addon.find(".//assets"):
        assert os.path.exists(os.path.join(ROOT, asset.text)), asset.text


def test_strings_po_is_up_to_date():
    assert read("resources", "language", "resource.language.en_gb", "strings.po") == make_strings.render()


def test_settings_xml_is_up_to_date():
    assert read("resources", "settings.xml") == make_settings.render()


def test_string_ids_unique():
    ids = [i for i, _ in STRINGS.values()]
    assert len(ids) == len(set(ids))


def test_settings_labels_exist_and_code_settings_are_defined():
    settings = ET.fromstring(read("resources", "settings.xml"))
    known_ids = {str(i) for i, _ in STRINGS.values()}
    defined = set()
    for element in settings.iter():
        label = element.get("label")
        if label is not None:
            assert label in known_ids, f"label {label} has no string"
        if element.tag == "setting":
            defined.add(element.get("id"))
        if element.tag == "heading":
            assert element.text in known_ids
    code = "".join(read("resources", "lib", name) for name in os.listdir(os.path.join(ROOT, "resources", "lib"))
                   if name.endswith(".py"))
    used = set(re.findall(r'setting_(?:str|bool|int)\("([a-z_.]+)"\)', code))
    used |= {f"{name}.api_key" for name in ("tmdb", "fanart", "omdb")}
    used |= set(re.findall(r'view_setting="([a-z_.]+)"', code))
    used |= set(re.findall(r'setting_(?:str|bool|int)\("([a-z_.]+)"', code))
    used |= set(HIDE.values())
    missing = used - defined
    assert not missing, f"settings used in code but not defined: {missing}"


def test_language_options_match_setting():
    settings = ET.fromstring(read("resources", "settings.xml"))
    setting = next(s for s in settings.iter("setting") if s.get("id") == "metadata.language")
    options = setting.findall(".//option")
    assert len(options) == len(LANGUAGES)
    for option, (_, key) in zip(options, LANGUAGES):
        assert option.get("label") == str(STRINGS[key][0])
