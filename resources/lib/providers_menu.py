# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Tools > Providers: install, manage, update and roll back provider packages."""

import io
import os
import zipfile

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib import kodi, listing
from resources.lib.choose import packages
from resources.lib.packages import PackageError

PACKAGE_MESSAGES = {
    "too_big": "pkg_err_too_big", "not_a_zip": "pkg_err_not_a_zip", "too_many_files": "pkg_err_too_big",
    "unsafe_path": "pkg_err_unsafe", "no_meta": "pkg_err_no_meta", "bad_meta": "pkg_err_bad_meta",
    "bad_name": "pkg_err_bad_name", "no_providers": "pkg_err_no_providers", "download_failed": "pkg_err_download",
    "checksum": "pkg_err_checksum", "no_backup": "pkg_err_no_backup", "no_update_directory": "pkg_err_no_update_dir",
}
TEST_PACKAGE = os.path.join(kodi.ADDON_PATH, "resources", "test_provider", "SpongeTVTest")


def _message(error):
    return kodi.text(PACKAGE_MESSAGES.get(error.kind, "pkg_err_unknown"))


def _item(plugin, label, action, folder=False, **params):
    return plugin.url(action=action, **params), listing.folder_item(label, kodi.ICON, kodi.FANART), folder


def menu(plugin, app):
    items = [_item(plugin, kodi.text("install_from_url"), "install_url"),
             _item(plugin, kodi.text("install_from_zip"), "install_zip"),
             _item(plugin, kodi.text("install_test_provider"), "install_test"),
             _item(plugin, kodi.text("manage_packages"), "packages", True),
             _item(plugin, kodi.text("check_package_updates"), "package_updates"),
             _item(plugin, kodi.text("sort_heading"), "sort_rules"),
             _item(plugin, kodi.text("clear_source_results"), "clear_results")]
    plugin.finish(items, category=kodi.text("tools_providers"), cache=False)


# -- installing -----------------------------------------------------------------------------------------
def _confirm(package):
    lines = kodi.text("install_confirm", name=package.name, version=package.version, author=package.author)
    return xbmcgui.Dialog().yesno(kodi.text("install_heading"), lines)


def _install(app, data, checked=False):
    try:
        package = packages(app).install(data, _confirm)
    except PackageError as error:
        kodi.log_error(f"Package install refused: {error}")
        xbmcgui.Dialog().ok(kodi.text("install_heading"), _message(error))
        return None
    if package:
        found = len(packages(app).providers(package.name))
        problem = (packages(app).get(package.name) or {}).get("problem")
        text = kodi.text("installed_ok", name=package.name, version=package.version, count=found)
        if checked:
            text += "[CR]" + kodi.text("checksum_ok")
        if problem:
            text += "[CR]" + kodi.text("package_problem", problem=problem)
        xbmcgui.Dialog().ok(kodi.text("install_heading"), text)
        xbmc.executebuiltin("Container.Refresh")
    return package


def install_url(plugin, app):
    url = (xbmcgui.Dialog().input(kodi.text("enter_package_url"), defaultt=kodi.setting_str("packages.last_url")) or "").strip()
    if not url:
        return
    kodi.set_setting_str("packages.last_url", url)
    try:
        data, checked = packages(app).download(url)
    except PackageError as error:
        xbmcgui.Dialog().ok(kodi.text("install_heading"), _message(error))
        return
    _install(app, data, checked)


def install_zip(plugin, app):
    path = xbmcgui.Dialog().browse(1, kodi.text("choose_zip"), "files", ".zip")
    if not path:
        return
    with xbmcvfs.File(path) as handle:
        data = handle.readBytes()
    _install(app, bytes(data))


def zip_folder(folder):
    """A package folder as zip bytes (used for the built-in test provider)."""
    buffer = io.BytesIO()
    root = os.path.basename(folder.rstrip(os.sep))
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for here, _, names in os.walk(folder):
            for name in names:
                if name.endswith((".pyc", ".pyo")):
                    continue
                path = os.path.join(here, name)
                archive.write(path, os.path.join(root, os.path.relpath(path, folder)))
    return buffer.getvalue()


def install_test(plugin, app):
    _install(app, zip_folder(TEST_PACKAGE))


# -- managing --------------------------------------------------------------------------------------------
def package_list(plugin, app):
    manager = packages(app)
    installed = manager.installed()
    items = []
    if installed:
        items.append(_item(plugin, kodi.text("all_providers_on"), "providers_all", on="1"))
        items.append(_item(plugin, kodi.text("all_providers_off"), "providers_all", on="0"))
    for package in installed:
        providers = manager.providers(package["name"])
        on = sum(1 for p in providers if p["enabled"])
        label = kodi.text("package_row", name=package["name"], version=package["version"], on=on, total=len(providers))
        if package.get("problem"):
            label += "  " + kodi.text("package_has_problem")
        items.append(_item(plugin, label, "package", True, name=package["name"]))
    if not installed:
        kodi.notify(kodi.text("no_packages"))
    plugin.finish(items, category=kodi.text("manage_packages"), cache=False)


def providers_all(plugin, app):
    manager = packages(app)
    on = plugin.params.get("on") == "1"
    for package in manager.installed():
        manager.set_enabled(package["name"], on)
    kodi.notify(kodi.text("all_turned_on" if on else "all_turned_off"))
    xbmc.executebuiltin("Container.Refresh")


def _last_result(provider):
    status = provider.get("last_status")
    if not status:
        return kodi.text("last_never")
    if status == "found":
        return kodi.text("last_found", count=provider.get("last_count") or 0)
    return kodi.text("last_" + status.replace(" ", "_"))


def package(plugin, app):
    manager = packages(app)
    name = plugin.params.get("name")
    info = manager.get(name)
    if not info:
        plugin.fail()
        return
    items = []
    if info.get("problem"):
        items.append(_item(plugin, kodi.text("package_problem", problem=info["problem"]), "package", True, name=name))
    for provider in manager.providers(name):
        state = kodi.text("on" if provider["enabled"] else "off")
        label = kodi.text("provider_row", state=state, name=provider["name"], kind=provider["kind"],
                          result=_last_result(provider))
        items.append(_item(plugin, label, "provider_toggle", package=name, kind=provider["kind"], provider=provider["name"],
                           on="0" if provider["enabled"] else "1"))
    items.append(_item(plugin, kodi.text("package_all_on"), "package_toggle", name=name, on="1"))
    items.append(_item(plugin, kodi.text("package_all_off"), "package_toggle", name=name, on="0"))
    if manager.settings(name):
        items.append(_item(plugin, kodi.text("package_settings"), "package_settings", name=name))
    if info.get("remote_meta"):
        items.append(_item(plugin, kodi.text("check_one_update"), "package_update", name=name))
    if manager.can_roll_back(name):
        items.append(_item(plugin, kodi.text("roll_back", version=info.get("previous_version") or "?"), "package_rollback",
                           name=name))
    items.append(_item(plugin, kodi.text("uninstall"), "package_uninstall", name=name))
    plugin.finish(items, category=f"{name} {info['version']}", cache=False)


def provider_toggle(plugin, app):
    packages(app).set_enabled(plugin.params["package"], plugin.params.get("on") == "1",
                              plugin.params.get("kind"), plugin.params.get("provider"))
    xbmc.executebuiltin("Container.Refresh")


def package_toggle(plugin, app):
    packages(app).set_enabled(plugin.params["name"], plugin.params.get("on") == "1")
    xbmc.executebuiltin("Container.Refresh")


def package_settings(plugin, app):
    manager = packages(app)
    name = plugin.params["name"]
    dialog = xbmcgui.Dialog()
    while True:
        settings = manager.settings(name)
        rows = [f"{s['label']}: {s['value']}" for s in settings]
        picked = dialog.select(kodi.text("package_settings"), rows)
        if picked < 0:
            return
        setting = settings[picked]
        if setting["type"] == "bool":
            value = "False" if setting["value"] == "True" else "True"
        elif setting["type"] == "int":
            value = dialog.numeric(0, setting["label"], setting["value"]) or setting["value"]
        else:
            value = dialog.input(setting["label"], defaultt=setting["value"])
        manager.set_setting(name, setting["id"], value)


def package_update(plugin, app):
    manager = packages(app)
    name = plugin.params["name"]
    updates = [u for u in manager.available_updates() if u[0]["name"] == name]
    if not updates:
        xbmcgui.Dialog().ok(kodi.text("install_heading"), kodi.text("no_update", name=name))
        return
    try:
        if manager.update(*updates[0], confirm=_confirm):
            kodi.notify(kodi.text("updated_to", name=name, version=updates[0][1].get("version")))
            xbmc.executebuiltin("Container.Refresh")
    except PackageError as error:
        xbmcgui.Dialog().ok(kodi.text("install_heading"), _message(error))


def package_updates(plugin, app):
    manager = packages(app)
    updates = manager.available_updates()
    if not updates:
        kodi.notify(kodi.text("all_packages_current"))
        return
    for installed, remote in updates:
        if xbmcgui.Dialog().yesno(kodi.text("install_heading"), kodi.text(
                "update_available", name=installed["name"], old=installed["version"], new=remote.get("version"))):
            try:
                manager.update(installed, remote, confirm=lambda p: True)
                kodi.notify(kodi.text("updated_to", name=installed["name"], version=remote.get("version")))
            except PackageError as error:
                xbmcgui.Dialog().ok(kodi.text("install_heading"), _message(error))


def package_rollback(plugin, app):
    manager = packages(app)
    name = plugin.params["name"]
    info = manager.get(name) or {}
    if not xbmcgui.Dialog().yesno(kodi.text("install_heading"), kodi.text(
            "roll_back_confirm", name=name, version=info.get("previous_version") or "?")):
        return
    try:
        version = manager.roll_back(name)
    except PackageError as error:
        xbmcgui.Dialog().ok(kodi.text("install_heading"), _message(error))
        return
    kodi.notify(kodi.text("rolled_back", name=name, version=version))
    xbmc.executebuiltin("Container.Refresh")


def package_uninstall(plugin, app):
    name = plugin.params["name"]
    if not xbmcgui.Dialog().yesno(kodi.text("install_heading"), kodi.text("uninstall_confirm", name=name)):
        return
    packages(app).uninstall(name)
    kodi.notify(kodi.text("uninstalled", name=name))
    xbmc.executebuiltin("Container.Update(plugin://plugin.video.spongetv/?action=packages,replace)")
