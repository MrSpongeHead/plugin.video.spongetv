# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""SpongeTV and its test stand-ins checked against Kodi's real Python interface.

The tests run against stand-ins for Kodi's modules (conftest.py). A stand-in that is kinder than Kodi hides
bugs, so this file checks, against Kodistubs (Kodi 21's interface, generated from Kodi's own documentation):
  - every Kodi function, class, method and keyword SpongeTV's code uses exists in Kodi;
  - every method a stand-in offers exists in Kodi with those parameter names.
Skipped when Kodistubs isn't installed (pip install "Kodistubs>=21,<22").
"""

import ast
import glob
import importlib.util
import inspect
import os
import sysconfig

import pytest

import conftest

ROOT = conftest.ROOT
MODULES = ("xbmc", "xbmcgui", "xbmcplugin", "xbmcaddon", "xbmcvfs")


def _load_stubs():
    found = {}
    for name in MODULES:
        path = os.path.join(sysconfig.get_paths()["purelib"], name + ".py")
        if not os.path.exists(path):
            return None
        spec = importlib.util.spec_from_file_location("kodistub_" + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        found[name] = module
    return found


STUBS = _load_stubs()
pytestmark = pytest.mark.skipif(STUBS is None, reason="Kodistubs not installed")


def sources():
    paths = glob.glob(os.path.join(ROOT, "resources", "lib", "*.py")) + [os.path.join(ROOT, n) for n in ("main.py", "service.py")]
    for path in sorted(paths):
        with open(path, encoding="utf-8") as handle:
            yield os.path.relpath(path, ROOT), ast.parse(handle.read())


def params_of(callable_):
    try:
        signature = inspect.signature(callable_)
    except (TypeError, ValueError):
        return None
    return {name for name in signature.parameters if name != "self"}


def module_attr(node):
    """("xbmc", "Player") for the expression xbmc.Player, else None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in MODULES:
        return node.value.id, node.attr
    return None


def test_everything_spongetv_uses_from_kodi_exists():
    problems = []
    for path, tree in sources():
        for node in ast.walk(tree):
            used = module_attr(node)
            if used and not hasattr(STUBS[used[0]], used[1]):
                problems.append(f"{path}:{node.lineno} {used[0]}.{used[1]} isn't in Kodi")
            if not isinstance(node, ast.Call):
                continue
            target = module_attr(node.func)
            if target and hasattr(STUBS[target[0]], target[1]):                     # xbmc.log(..., level=...)
                thing = getattr(STUBS[target[0]], target[1])
                allowed = params_of(thing.__init__ if inspect.isclass(thing) else thing)
                for keyword in node.keywords:
                    if allowed is not None and keyword.arg and keyword.arg not in allowed:
                        problems.append(f"{path}:{node.lineno} {target[0]}.{target[1]}() has no '{keyword.arg}'")
            # xbmcgui.Dialog().ok(...), xbmc.Player().play(...)
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call):
                owner = module_attr(node.func.value.func)
                if owner and inspect.isclass(getattr(STUBS[owner[0]], owner[1], None)):
                    cls = getattr(STUBS[owner[0]], owner[1])
                    method = getattr(cls, node.func.attr, None)
                    if method is None:
                        problems.append(f"{path}:{node.lineno} {owner[1]}.{node.func.attr}() isn't in Kodi")
                        continue
                    allowed = params_of(method)
                    for keyword in node.keywords:
                        if allowed is not None and keyword.arg and keyword.arg not in allowed:
                            problems.append(f"{path}:{node.lineno} {owner[1]}.{node.func.attr}() has no '{keyword.arg}'")
    assert problems == []


def test_classes_built_on_kodis_only_use_what_kodi_gives_them():
    """A class extending xbmc.Player, xbmc.Monitor or a Kodi window: its on...() callbacks must be ones Kodi
    calls, and any self.method() it doesn't define itself must come from Kodi's class."""
    problems = []
    for path, tree in sources():
        classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        for cls in classes.values():
            bases = [module_attr(b) for b in cls.bases]
            kodi_bases = [getattr(STUBS[b[0]], b[1], None) for b in bases if b]
            if not kodi_bases or None in kodi_bases:
                continue
            own = {n.name for n in ast.walk(cls) if isinstance(n, ast.FunctionDef)}
            for n in ast.walk(cls):                          # self.x = ..., and self.a, self.b = ...
                if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                        own |= {a.attr for a in ast.walk(t) if isinstance(a, ast.Attribute)}
            own |= {t.id for n in cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
            for name in sorted(n for n in own if n.startswith("on") and n[2:3].isupper()):
                if not any(hasattr(base, name) for base in kodi_bases):
                    problems.append(f"{path} {cls.name}.{name}: Kodi never calls this")
            for node in ast.walk(cls):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
                    name = node.func.attr
                    if name not in own and not any(hasattr(base, name) for base in kodi_bases):
                        problems.append(f"{path}:{node.lineno} {cls.name} calls self.{name}(), which Kodi's class lacks")
    assert problems == []


def _kodi_style(name):
    return name[:1].islower() and any(c.isupper() for c in name) and "_" not in name


def test_kodi_style_method_names_exist_somewhere_in_kodi():
    """A wide net for calls on Kodi objects whose type can't be told from the code (list items, info tags,
    controls...): any camelCase method SpongeTV calls must exist on some Kodi class or module."""
    known = set()
    for module in STUBS.values():
        known |= set(dir(module))
        for _, cls in inspect.getmembers(module, inspect.isclass):
            known |= set(dir(cls))
    ours = set()
    for _, tree in sources():
        ours |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    python_own = {"fromisoformat", "isoformat", "setdefault", "startswith", "endswith", "fetchall", "fetchone",
                  "executemany", "executescript", "isdigit", "splitlines", "getLogger", "setDaemon", "isAlive",
                  "extractall", "namelist", "getroot", "findall", "iterfind", "partition", "rpartition",
                  "casefold", "isalnum", "isspace", "zfill", "hexdigest", "getvalue", "readlines", "writelines",
                  "isfile", "isdir", "makedirs", "listdir", "rmtree", "copyfile", "copytree", "getmtime", "getsize",
                  "isabs", "splitext", "basename", "dirname", "abspath", "normpath", "relpath", "urlencode",
                  "urlparse", "parse_qs", "parse_qsl", "urljoin", "urlsplit", "infolist", "testzip", "getinfo",
                  "isatty", "getpid", "isinstance", "fromtimestamp", "utcfromtimestamp", "strftime", "timestamp",
                  "astimezone", "utcoffset", "toordinal", "weekday", "isoweekday", "isocalendar", "fromordinal",
                  "bit_length", "to_bytes", "from_bytes", "isupper", "islower", "istitle", "swapcase", "expandtabs",
                  "maketrans", "isidentifier", "isprintable", "isascii", "isdecimal", "isnumeric", "isalpha"}
    problems = []
    for path, tree in sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and _kodi_style(node.func.attr):
                name = node.func.attr
                if name not in known and name not in ours and name not in python_own:
                    problems.append(f"{path}:{node.lineno} .{name}()")
    assert problems == []


STAND_INS = {
    "FakeListItem": ("xbmcgui", "ListItem"), "FakeDialog": ("xbmcgui", "Dialog"),
    "FakeProgress": ("xbmcgui", "DialogProgress"), "FakeAddon": ("xbmcaddon", "Addon"),
}


def _check_stand_in(fake, real, label, problems):
    for name, method in inspect.getmembers(fake, inspect.isfunction):
        if name.startswith("_"):
            continue
        if not hasattr(real, name):
            problems.append(f"{label}.{name}() isn't in Kodi")
            continue
        wanted, offered = params_of(getattr(real, name)), params_of(method)
        if wanted is None or offered is None:
            continue
        extra = {p for p in offered if p not in wanted and p not in ("args", "kwargs")}
        # a stand-in may name a positional differently; only keyword-style names must match Kodi's
        signature = inspect.signature(method)
        extra = {p for p in extra if signature.parameters[p].default is not inspect.Parameter.empty}
        if extra:
            problems.append(f"{label}.{name}() takes {sorted(extra)}, which Kodi's doesn't")


def test_stand_ins_offer_nothing_kodi_lacks():
    import sys
    problems = []
    for fake_name, (module, real_name) in STAND_INS.items():
        _check_stand_in(getattr(conftest, fake_name), getattr(STUBS[module], real_name), fake_name, problems)
    for module, names in (("xbmc", ("Monitor", "Player", "PlayList", "Actor")), ("xbmcgui", ("Window",))):
        for name in names:
            _check_stand_in(getattr(sys.modules[module], name), getattr(STUBS[module], name), f"{module}.{name}", problems)
    for module in MODULES:                                    # module-level functions and constants
        for name in dir(sys.modules[module]):
            if not name.startswith("_") and name not in ("jsonrpc",) and not hasattr(STUBS[module], name):
                problems.append(f"{module}.{name} isn't in Kodi")
    assert problems == []


# -- names Kodi only understands as text: labels, conditions and built-in commands -------------------------
import json
import re

with open(os.path.join(ROOT, "tests", "kodi21_names.json"), encoding="utf-8") as _handle:
    KODI_NAMES = json.load(_handle)

NAME = re.compile(r"\b(Container|ListItem|Player|System|Window|Control|Skin|VideoPlayer)(?:\(\d*\))?\.([A-Za-z0-9]+)")


def _texts():
    """Every piece of text in SpongeTV's code and windows that could hold a Kodi name."""
    for path, tree in sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                yield f"{path}:{node.lineno}", node.value
    for path in sorted(glob.glob(os.path.join(ROOT, "resources", "skins", "*", "*", "*.xml"))):
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                yield f"{os.path.relpath(path, ROOT)}:{number}", line


def test_labels_conditions_and_commands_are_ones_kodi_knows():
    """A misspelt label or condition doesn't fail in Kodi: it's quietly empty or false. So check the spelling
    here, against the names in Kodi 21's source."""
    builtins = set(KODI_NAMES["builtins"])
    special = set(KODI_NAMES["special"])
    notices = {"System.OnWake"}          # a notification Kodi sends (JSON-RPC System.OnWake), not a label
    problems, seen = [], 0
    for where, text in _texts():
        for group, name in NAME.findall(text):
            seen += 1
            known = set(KODI_NAMES["labels"].get(group.lower(), ()))
            if (name.lower() in known or name.lower() in special or f"{group}.{name}".lower() in builtins
                    or f"{group}.{name}" in notices):
                continue
            problems.append(f"{where} {group}.{name}")
    assert seen > 30 and problems == []


def test_commands_run_from_menus_are_built_ins():
    command = re.compile(r"^(RunPlugin|PlayMedia|ActivateWindow|Action|Notification|RunScript|ReplaceWindow)\(")
    used = set()
    for _, text in _texts():
        match = re.match(r"^([A-Za-z.]+)\(", text)
        if match and (command.match(text) or "." in match.group(1)):
            used.add(match.group(1))
    used = {u for u in used if u.split(".")[0] in ("RunPlugin", "PlayMedia", "ActivateWindow", "Action", "Container",
                                                    "Dialog", "Addon", "Notification", "RunScript", "ReplaceWindow")}
    assert used and {u for u in used if u.lower() not in KODI_NAMES["builtins"]} == set()


def test_info_tag_stand_in_matches_kodi():
    real = STUBS["xbmc"].InfoTagVideo
    setters = {name for name in dir(real) if name.startswith("set")}
    assert set(conftest.INFO_TAG_SETTERS) == setters
    for name, kinds in conftest.INFO_TAG_SETTERS.items():
        assert len(kinds) == len(params_of(getattr(real, name))), name
