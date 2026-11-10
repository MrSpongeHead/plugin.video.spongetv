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
    assert read("resources", "settings.xml") == make_settings.with_help(make_settings.render())


def test_string_ids_unique_and_in_the_add_on_range():
    ids = [i for i, _ in STRINGS.values()]
    assert len(ids) == len(set(ids))
    assert all(30000 <= i <= 30999 for i in ids), "Kodi reserves 30000-30999 for add-on strings"


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


def test_settings_that_appear_conditionally_share_a_group_with_their_switch():
    """Kodi never hides a group heading, so a group of only conditional settings leaves an empty heading."""
    settings = ET.fromstring(read("resources", "settings.xml"))
    for group in settings.iter("group"):
        members = group.findall("setting")
        own_ids = {s.get("id") for s in members}
        for setting in members:
            for condition in setting.iter("condition"):
                assert condition.get("setting") in own_ids, \
                    f"{setting.get('id')} depends on {condition.get('setting')} in another group"


def test_no_strptime_anywhere():
    """datetime.strptime can fail inside Kodi ("'NoneType' object is not callable" after its first use in a
    session), so SpongeTV parses dates with fromisoformat instead."""
    import glob
    import re
    for path in glob.glob(os.path.join(ROOT, "resources", "lib", "*.py")):
        code = "\n".join(line.split("#")[0] for line in open(path, encoding="utf-8"))
        assert not re.search(r"strptime\s*\(", code), path
