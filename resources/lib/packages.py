# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Provider packages: install, check, update, roll back, uninstall, and list their providers.

The format is Seren's, so a package built from your template works unchanged:

    <Name>/meta.json                       name, author, version (required); remote_meta,
                                            update_directory, settings, setup_extension (optional)
    <Name>/providers/<Name>/<lang>/__init__.py   get_torrent(), get_hosters(), optional get_adaptive(),
                                                  get_direct(): lists of provider module names
    <Name>/providerModules/<Name>/...      shared code the providers import

Packages are installed into SpongeTV's data folder as providers/<Name> and providerModules/<Name>,
and that folder goes on Python's import path, which is how the packages import themselves
("providers.<Name>.en.torrent.x", "providerModules.<Name>.core").

Provider packages run code on your device, so before installing SpongeTV shows the package's
name, version and author and asks you to confirm, and refuses zips that are oversized, have
unsafe paths or links, or a missing or malformed meta.json. If the publisher puts a
SHA-256 checksum next to the zip (<url>.sha256), it must match.

NOTE: packages first try to import Seren's own helpers (resources.lib.common, resources.lib.modules)
and fall back to Kodi's logging and an in-memory store when those aren't there. SpongeTV's code
also lives in resources.lib, so it must never gain modules with those names.
"""

import hashlib
import importlib
import io
import json
import os
import re
import shutil
import stat
import sys
import time
import zipfile

from resources.lib.http import HttpError

MAX_DOWNLOAD = 50 * 1024 * 1024          # bytes
MAX_UNPACKED = 200 * 1024 * 1024
MAX_FILES = 5000
KINDS = [("torrent", "get_torrent"), ("hosters", "get_hosters"), ("adaptive", "get_adaptive"), ("direct", "get_direct")]


class PackageError(Exception):
    """kind names the plain-English message to show; detail is for the log."""

    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def version_tuple(text):
    return tuple(int(n) for n in re.findall(r"\d+", str(text or ""))) or (0,)


def _safe_member(name):
    parts = name.replace("\\", "/").split("/")
    return not (name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or ".." in parts)


class Package:
    """A validated zip, read into memory, ready to install."""

    def __init__(self, data):
        if len(data) > MAX_DOWNLOAD:
            raise PackageError("too_big", f"{len(data)} bytes")
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as error:
            raise PackageError("not_a_zip", str(error)) from error
        self.data = data
        infos = self.zip.infolist()
        if len(infos) > MAX_FILES:
            raise PackageError("too_many_files", str(len(infos)))
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise PackageError("too_big", "unpacked size")
        for info in infos:
            if not _safe_member(info.filename):
                raise PackageError("unsafe_path", info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise PackageError("unsafe_path", f"link: {info.filename}")
        names = [i.filename.replace("\\", "/") for i in infos]
        # meta.json at the top, or inside one top-level folder (as in your template)
        if "meta.json" in names:
            self.root = ""
        else:
            roots = {n.split("/", 1)[0] for n in names if "/" in n}
            if len(roots) != 1 or f"{next(iter(roots))}/meta.json" not in names:
                raise PackageError("no_meta")
            self.root = next(iter(roots)) + "/"
        self.files = {n[len(self.root):]: info for n, info in zip(names, infos)
                      if n.startswith(self.root) and not n.endswith("/")}
        try:
            self.meta = json.loads(self.zip.read(self.root + "meta.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise PackageError("bad_meta", str(error)) from error
        if not isinstance(self.meta, dict):
            raise PackageError("bad_meta", "not an object")
        for field in ("name", "author", "version"):
            if not isinstance(self.meta.get(field), str) or not self.meta[field].strip():
                raise PackageError("bad_meta", f"missing {field}")
        self.name = self.meta["name"].strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.name):
            raise PackageError("bad_name", self.name)
        # Only providers/<Name> and providerModules/<Name> are ever installed; anything else in the
        # zip (README, docs, another package's folders) is left out.
        self.skipped = [p for p in self.files if not self._installs(p)]
        if not any(p.startswith(f"providers/{self.name}/") for p in self.files):
            raise PackageError("no_providers", self.name)

    def _installs(self, path):
        parts = path.split("/")
        return len(parts) > 2 and parts[0] in ("providers", "providerModules") and parts[1] == self.name

    @property
    def version(self):
        return self.meta["version"].strip()

    @property
    def author(self):
        return self.meta["author"].strip()

    def extract_to(self, folder):
        """Writes providers/<Name> and providerModules/<Name> under folder."""
        for path, info in self.files.items():
            if not self._installs(path):
                continue
            target = os.path.join(folder, *path.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with self.zip.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)


class Packages:
    def __init__(self, store, data_folder, http=None, clock=time.time):
        self.store = store
        self.folder = data_folder
        self.http = http
        self.clock = clock

    # -- places ------------------------------------------------------------------------------
    def _dir(self, *parts):
        return os.path.join(self.folder, *parts)

    def ensure_import_path(self):
        """Packages import themselves as top-level "providers" and "providerModules"."""
        for top in ("providers", "providerModules"):
            os.makedirs(self._dir(top), exist_ok=True)
            init = self._dir(top, "__init__.py")
            if not os.path.exists(init):
                open(init, "w").close()
        if self.folder not in sys.path:
            sys.path.append(self.folder)

    def forget_modules(self, name):
        """Drop a package's already-imported modules, so a new version is really used."""
        for module in list(sys.modules):
            if module in (f"providers.{name}", f"providerModules.{name}") or \
                    module.startswith((f"providers.{name}.", f"providerModules.{name}.")):
                del sys.modules[module]
        importlib.invalidate_caches()

    # -- reading -------------------------------------------------------------------------------
    def installed(self):
        rows = self.store.query("SELECT name, author, version, remote_meta, update_directory, installed, "
                                "previous_version, problem FROM packages ORDER BY name COLLATE NOCASE")
        keys = ("name", "author", "version", "remote_meta", "update_directory", "installed", "previous_version", "problem")
        return [dict(zip(keys, r)) for r in rows]

    def get(self, name):
        return next((p for p in self.installed() if p["name"] == name), None)

    def providers(self, package=None, enabled_only=False):
        sql = "SELECT package, language, kind, name, enabled, last_status, last_count, last_time FROM providers"
        where, params = [], []
        if package:
            where.append("package = ?")
            params.append(package)
        if enabled_only:
            where.append("enabled = 1")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY package, kind, name"
        keys = ("package", "language", "kind", "name", "enabled", "last_status", "last_count", "last_time")
        return [dict(zip(keys, r)) for r in self.store.query(sql, params)]

    # -- getting a zip -----------------------------------------------------------------------------
    def download(self, url):
        """The zip's bytes, checked against <url>.sha256 if the publisher provides one."""
        if self.http is None:
            raise PackageError("download_failed", "no connection")
        try:
            response = self.http.send("GET", url, max_wait=10)
        except HttpError as error:
            raise PackageError("download_failed", str(error)) from error
        if response.status != 200 or response.content is None:
            raise PackageError("download_failed", f"HTTP {response.status}")
        data = response.content
        if len(data) > MAX_DOWNLOAD:
            raise PackageError("too_big", f"{len(data)} bytes")
        expected = self._published_checksum(url)
        if expected and hashlib.sha256(data).hexdigest().lower() != expected:
            raise PackageError("checksum", url)
        return data, bool(expected)

    def _published_checksum(self, url):
        try:
            response = self.http.send("GET", url + ".sha256", max_wait=5)
        except HttpError:
            return None
        if response.status != 200 or not response.content:
            return None
        found = re.search(rb"\b[0-9a-fA-F]{64}\b", response.content[:4096])
        return found.group(0).decode().lower() if found else None

    # -- installing --------------------------------------------------------------------------------
    def install(self, data, confirm=lambda package: True):
        """Validate, ask, then install (keeping the previous version for roll back). Returns the
        Package, or None if you said no."""
        package = Package(data)
        if not confirm(package):
            return None
        self.ensure_import_path()
        name = package.name
        staging = self._dir("package_staging", name)
        shutil.rmtree(staging, ignore_errors=True)
        package.extract_to(staging)
        previous = self.get(name)
        if previous:
            self._backup(name, previous)
        for top in ("providers", "providerModules"):
            target = self._dir(top, name)
            shutil.rmtree(target, ignore_errors=True)
            if os.path.isdir(os.path.join(staging, top, name)):
                shutil.move(os.path.join(staging, top, name), target)
        shutil.rmtree(self._dir("package_staging"), ignore_errors=True)
        os.makedirs(self._dir("package_meta"), exist_ok=True)
        with open(self._dir("package_meta", name + ".json"), "w", encoding="utf-8") as handle:
            json.dump(package.meta, handle)
        meta = package.meta
        self.store.execute("INSERT OR REPLACE INTO packages (name, author, version, remote_meta, update_directory, installed, "
                           "previous_version, meta, problem) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')",
                           (name, package.author, package.version, meta.get("remote_meta", "") or "",
                            meta.get("update_directory", "") or "", self.clock(),
                            previous["version"] if previous else (self.get(name) or {}).get("previous_version"),
                            json.dumps(meta)))
        self._create_settings(name, meta.get("settings") or [])
        self.forget_modules(name)
        self.refresh(name)
        self._run_setup_extension(name, meta.get("setup_extension"))
        return package

    def _backup(self, name, previous):
        backup = self._dir("package_backups", name)
        shutil.rmtree(backup, ignore_errors=True)
        os.makedirs(backup, exist_ok=True)
        for top in ("providers", "providerModules"):
            if os.path.isdir(self._dir(top, name)):
                shutil.copytree(self._dir(top, name), os.path.join(backup, top, name))
        meta_file = self._dir("package_meta", name + ".json")
        if os.path.exists(meta_file):
            shutil.copy(meta_file, os.path.join(backup, "meta.json"))

    def can_roll_back(self, name):
        return os.path.exists(self._dir("package_backups", name, "meta.json"))

    def roll_back(self, name):
        """Swap the installed version and the previous one."""
        backup = self._dir("package_backups", name)
        if not self.can_roll_back(name):
            raise PackageError("no_backup", name)
        with open(os.path.join(backup, "meta.json"), encoding="utf-8") as handle:
            old_meta = json.load(handle)
        current = self.get(name)
        swap = self._dir("package_swap", name)
        shutil.rmtree(swap, ignore_errors=True)
        for top in ("providers", "providerModules"):
            if os.path.isdir(self._dir(top, name)):
                shutil.move(self._dir(top, name), os.path.join(swap, top, name))
            if os.path.isdir(os.path.join(backup, top, name)):
                shutil.move(os.path.join(backup, top, name), self._dir(top, name))
        shutil.rmtree(backup, ignore_errors=True)
        if current:   # the version you rolled back from becomes the one you can return to
            os.makedirs(backup, exist_ok=True)
            for top in ("providers", "providerModules"):
                if os.path.isdir(os.path.join(swap, top, name)):
                    shutil.move(os.path.join(swap, top, name), os.path.join(backup, top, name))
            shutil.copy(self._dir("package_meta", name + ".json"), os.path.join(backup, "meta.json"))
        shutil.rmtree(self._dir("package_swap"), ignore_errors=True)
        with open(self._dir("package_meta", name + ".json"), "w", encoding="utf-8") as handle:
            json.dump(old_meta, handle)
        self.store.execute("UPDATE packages SET version = ?, previous_version = ?, remote_meta = ?, update_directory = ?, "
                           "meta = ? WHERE name = ?",
                           (old_meta.get("version", ""), current["version"] if current else None,
                            old_meta.get("remote_meta", "") or "", old_meta.get("update_directory", "") or "",
                            json.dumps(old_meta), name))
        self.forget_modules(name)
        self.refresh(name)
        return old_meta.get("version", "")

    def uninstall(self, name):
        for top in ("providers", "providerModules"):
            shutil.rmtree(self._dir(top, name), ignore_errors=True)
        shutil.rmtree(self._dir("package_backups", name), ignore_errors=True)
        meta_file = self._dir("package_meta", name + ".json")
        if os.path.exists(meta_file):
            os.remove(meta_file)
        for table in ("packages", "providers", "package_settings"):
            column = "name" if table == "packages" else "package"
            self.store.execute(f"DELETE FROM {table} WHERE {column} = ?", (name,))
        self.forget_modules(name)

    # -- providers in a package ------------------------------------------------------------------
    def discover(self, name):
        """[(language, kind, provider)] as the package lists them."""
        self.ensure_import_path()
        root = self._dir("providers", name)
        found = []
        for language in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            if not os.path.isfile(os.path.join(root, language, "__init__.py")):
                continue
            module = importlib.import_module(f"providers.{name}.{language}")
            for kind, function in KINDS:
                listing = getattr(module, function, None)
                if callable(listing):
                    for provider in listing() or []:
                        found.append((language, kind, str(provider)))
        return found

    def refresh(self, name):
        """Re-read a package's providers, keeping each one's on/off choice."""
        try:
            found = self.discover(name)
            problem = "" if found else "no providers listed"
        except Exception as error:   # a package's own code failed to load
            found, problem = [], f"{type(error).__name__}: {error}"
        enabled = {(p["language"], p["kind"], p["name"]): p["enabled"] for p in self.providers(name)}
        rows = self.store.query("SELECT meta FROM packages WHERE name = ?", (name,))
        try:
            meta = json.loads(rows[0][0] or "{}") if rows else {}
        except ValueError:
            meta = {}
        off = set(meta.get("off_by_default") or [])   # SpongeTV's own extra: providers that start switched off
        self.store.execute("DELETE FROM providers WHERE package = ?", (name,))
        for language, kind, provider in found:
            default = 0 if f"{kind}/{provider}" in off else 1
            self.store.execute("INSERT INTO providers (package, language, kind, name, enabled) VALUES (?, ?, ?, ?, ?)",
                               (name, language, kind, provider, enabled.get((language, kind, provider), default)))
        self.store.execute("UPDATE packages SET problem = ? WHERE name = ?", (problem, name))
        return found

    def set_enabled(self, package, enabled, kind=None, name=None):
        sql, params = "UPDATE providers SET enabled = ? WHERE package = ?", [1 if enabled else 0, package]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if name:
            sql += " AND name = ?"
            params.append(name)
        self.store.execute(sql, params)

    def record_result(self, package, kind, name, status, count):
        self.store.execute("UPDATE providers SET last_status = ?, last_count = ?, last_time = ? "
                           "WHERE package = ? AND kind = ? AND name = ?", (status, count, self.clock(), package, kind, name))

    # -- package settings (declared in meta.json) -----------------------------------------------------
    def _create_settings(self, name, settings):
        kept = {row[0]: row[1] for row in self.store.query("SELECT id, value FROM package_settings WHERE package = ?", (name,))}
        self.store.execute("DELETE FROM package_settings WHERE package = ?", (name,))
        for setting in settings:
            if not isinstance(setting, dict) or "id" not in setting or setting.get("type") not in ("str", "int", "bool"):
                continue
            value = kept.get(setting["id"], str(setting.get("default", {"str": "", "int": 0, "bool": False}[setting["type"]])))
            self.store.execute("INSERT INTO package_settings (package, id, type, label, value, visible) VALUES (?, ?, ?, ?, ?, ?)",
                               (name, setting["id"], setting["type"], setting.get("label", setting["id"]), value,
                                1 if setting.get("visible", True) else 0))

    def settings(self, name, visible_only=True):
        sql = "SELECT id, type, label, value FROM package_settings WHERE package = ?"
        if visible_only:
            sql += " AND visible = 1"
        return [dict(zip(("id", "type", "label", "value"), r)) for r in self.store.query(sql, (name,))]

    def set_setting(self, name, setting_id, value):
        self.store.execute("UPDATE package_settings SET value = ? WHERE package = ? AND id = ?", (str(value), name, setting_id))

    def _run_setup_extension(self, name, script):
        """An optional set-up script a package can name in meta.json (as in Seren)."""
        if not script or not re.fullmatch(r"[A-Za-z0-9_.]+", str(script)):
            return
        module = str(script)[:-3] if str(script).endswith(".py") else str(script)
        for top in ("providers", "providerModules"):
            try:
                importlib.import_module(f"{top}.{name}.{module}")
                return
            except ImportError:
                continue
            except Exception as error:   # the script itself failed: the package still installs
                self.store.execute("UPDATE packages SET problem = ? WHERE name = ?", (f"set-up script: {error}", name))
                return

    # -- updates ---------------------------------------------------------------------------------------
    def available_updates(self):
        """[(installed package, newer remote meta)] for packages that publish a remote_meta."""
        updates = []
        for package in self.installed():
            if not package["remote_meta"] or self.http is None:
                continue
            try:
                response = self.http.send("GET", package["remote_meta"], max_wait=10)
                remote = json.loads(response.content.decode("utf-8")) if response.status == 200 else None
            except (HttpError, ValueError, AttributeError, UnicodeDecodeError):
                continue
            if not isinstance(remote, dict) or remote.get("name") != package["name"]:
                continue
            if version_tuple(remote.get("version")) > version_tuple(package["version"]):
                updates.append((package, remote))
        return updates

    def update(self, package, remote, confirm=lambda p: True):
        """Seren's convention: <update_directory><name>-<version>.zip"""
        directory = remote.get("update_directory") or package.get("update_directory") or ""
        if not directory:
            raise PackageError("no_update_directory", package["name"])
        data, _ = self.download(f"{directory}{package['name']}-{remote['version']}.zip")
        return self.install(data, confirm)
