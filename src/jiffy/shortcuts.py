"""Binds the record shortcut in the user's desktop. One small class per desktop; add a class to support another.

The bound command is `gapplication action <app id> record`: a tiny C tool that pokes the resident
app over D-Bus (starting it if needed), so the overlay appears instantly instead of after a Python start.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402

from jiffy import APP_ID, APP_NAME, PRGNAME  # noqa: E402

log = logging.getLogger(__name__)

RECORD_COMMAND = f"gapplication action {APP_ID} record"

# Tried in order on first run when the configured shortcut is already taken.
CANDIDATES = ("<Shift>Print", "<Super><Shift>Print", "<Super><Shift>g", "<Primary><Alt><Shift>g")


def is_ours(command: str) -> bool:
    words = command.split()
    return APP_ID in command or (bool(words) and os.path.basename(words[0]) == PRGNAME)


def same_accel(a: str, b: str) -> bool:
    ka, ma = Gtk.accelerator_parse(a)
    kb, mb = Gtk.accelerator_parse(b)
    return ka != 0 and (Gdk.keyval_to_lower(ka), ma) == (Gdk.keyval_to_lower(kb), mb)


def label(accel: str) -> str:
    if not accel:
        return "None"
    key, mods = Gtk.accelerator_parse(accel)
    return Gtk.accelerator_get_label(key, mods) if key else accel


def choose(preferred: str, conflicts: Callable[[str], list[str]]) -> str:
    """The preferred shortcut if it is free, else the first free candidate, else the preferred one anyway."""
    for accel in (preferred, *CANDIDATES):
        if accel and not conflicts(accel):
            return accel
    return preferred


def _schema_exists(schema_id: str) -> bool:
    source = Gio.SettingsSchemaSource.get_default()
    return source is not None and source.lookup(schema_id, True) is not None


def _accels_in(schema_id: str) -> list[tuple[str, str]]:
    """(key name, accelerator) for every binding in a keybindings schema."""
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(schema_id, True) if source is not None else None
    if schema is None:
        return []
    settings = Gio.Settings.new(schema_id)
    found = []
    for key in schema.list_keys():
        value = settings.get_value(key)
        if value.get_type_string() == "as":
            found += [(key, v) for v in value.unpack() if v]
        elif value.get_type_string() == "s" and value.unpack():
            found.append((key, value.unpack()))
    return found


class Backend:
    """How one desktop stores custom keyboard shortcuts."""

    name = ""
    builtin_schemas: tuple[str, ...] = ()

    def available(self) -> bool:
        raise NotImplementedError

    def apply(self, accel: str) -> None:
        raise NotImplementedError

    def custom_entries(self) -> list[tuple[str, str, list[str]]]:
        """(name, command, accelerators) of every custom shortcut."""
        raise NotImplementedError

    def conflicts(self, accel: str) -> list[str]:
        """Names of other shortcuts already bound to `accel`."""
        if not accel:
            return []
        names = [key.replace("-", " ") for schema in self.builtin_schemas
                 for key, a in _accels_in(schema) if same_accel(a, accel)]
        names += [name for name, command, accels in self.custom_entries()
                  if not is_ours(command) and any(same_accel(a, accel) for a in accels)]
        return names


class CinnamonBackend(Backend):
    name = "Cinnamon"
    LIST = "org.cinnamon.desktop.keybindings"
    ENTRY = "org.cinnamon.desktop.keybindings.custom-keybinding"
    PATH = "/org/cinnamon/desktop/keybindings/custom-keybindings/{}/"
    builtin_schemas = ("org.cinnamon.desktop.keybindings.media-keys", "org.cinnamon.desktop.keybindings.wm")

    def available(self) -> bool:
        return _schema_exists(self.LIST) and _schema_exists(self.ENTRY)

    def _entry(self, slot: str) -> Gio.Settings:
        return Gio.Settings.new_with_path(self.ENTRY, self.PATH.format(slot))

    def _slots(self) -> list[str]:
        return [s for s in Gio.Settings.new(self.LIST).get_strv("custom-list") if s != "__dummy__"]

    def custom_entries(self):
        return [(e.get_string("name"), e.get_string("command"), list(e.get_strv("binding")))
                for e in map(self._entry, self._slots())]

    def apply(self, accel: str) -> None:
        listing = Gio.Settings.new(self.LIST)
        slots = list(listing.get_strv("custom-list"))
        slot = next((s for s in slots if is_ours(self._entry(s).get_string("command"))), None)
        if slot is None:
            i = 0
            while f"custom{i}" in slots:
                i += 1
            slot = f"custom{i}"
        entry = self._entry(slot)
        entry.set_string("name", APP_NAME)
        entry.set_string("command", RECORD_COMMAND)
        entry.set_strv("binding", [accel] if accel else [])
        if slot not in slots:
            listing.set_strv("custom-list", slots + [slot])
        Gio.Settings.sync()


class GnomeBackend(Backend):
    """GNOME on X11, and desktops that reuse its settings daemon (Budgie, Unity)."""

    name = "GNOME"
    LIST = "org.gnome.settings-daemon.plugins.media-keys"
    ENTRY = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
    builtin_schemas = ("org.gnome.settings-daemon.plugins.media-keys", "org.gnome.desktop.wm.keybindings",
                       "org.gnome.shell.keybindings", "org.gnome.mutter.keybindings")

    def available(self) -> bool:
        return _schema_exists(self.LIST) and _schema_exists(self.ENTRY)

    def _paths(self) -> list[str]:
        return list(Gio.Settings.new(self.LIST).get_strv("custom-keybindings"))

    def _entry(self, path: str) -> Gio.Settings:
        return Gio.Settings.new_with_path(self.ENTRY, path)

    def custom_entries(self):
        return [(e.get_string("name"), e.get_string("command"), [e.get_string("binding")])
                for e in map(self._entry, self._paths())]

    def apply(self, accel: str) -> None:
        listing = Gio.Settings.new(self.LIST)
        paths = self._paths()
        path = next((p for p in paths if is_ours(self._entry(p).get_string("command"))), None)
        if path is None:
            i = 0
            while f"{self.BASE}custom{i}/" in paths:
                i += 1
            path = f"{self.BASE}custom{i}/"
        entry = self._entry(path)
        entry.set_string("name", APP_NAME)
        entry.set_string("command", RECORD_COMMAND)
        entry.set_string("binding", accel)
        if path not in paths:
            listing.set_strv("custom-keybindings", paths + [path])
        Gio.Settings.sync()


class MateBackend(Backend):
    name = "MATE"
    ENTRY = "org.mate.control-center.keybinding"
    DIR = "/org/mate/desktop/keybindings/"
    builtin_schemas = ("org.mate.SettingsDaemon.plugins.media-keys", "org.mate.Marco.global-keybindings")

    def available(self) -> bool:
        return _schema_exists(self.ENTRY) and shutil.which("dconf") is not None

    def _slots(self) -> list[str]:
        out = subprocess.run(["dconf", "list", self.DIR], capture_output=True, text=True).stdout
        return [line.rstrip("/") for line in out.split() if line.endswith("/")]

    def _entry(self, slot: str) -> Gio.Settings:
        return Gio.Settings.new_with_path(self.ENTRY, f"{self.DIR}{slot}/")

    def custom_entries(self):
        return [(e.get_string("name"), e.get_string("action"), [e.get_string("binding")])
                for e in map(self._entry, self._slots())]

    def apply(self, accel: str) -> None:
        slots = self._slots()
        slot = next((s for s in slots if is_ours(self._entry(s).get_string("action"))), None)
        if slot is None:
            i = 0
            while f"custom{i}" in slots:
                i += 1
            slot = f"custom{i}"
        entry = self._entry(slot)
        entry.set_string("name", APP_NAME)
        entry.set_string("action", RECORD_COMMAND)
        entry.set_string("binding", accel)
        Gio.Settings.sync()


class XfceBackend(Backend):
    name = "Xfce"
    CHANNEL = "xfce4-keyboard-shortcuts"
    PREFIXES = ("/commands/custom/", "/xfwm4/custom/")

    def available(self) -> bool:
        return shutil.which("xfconf-query") is not None

    def _properties(self) -> list[tuple[str, str]]:
        out = subprocess.run(["xfconf-query", "-c", self.CHANNEL, "-l", "-v"], capture_output=True, text=True).stdout
        pairs = []
        for line in out.splitlines():
            prop, _, value = line.partition(" ")
            if prop.startswith(self.PREFIXES) and not prop.endswith("/override"):
                pairs.append((prop, value.strip()))
        return pairs

    def custom_entries(self):
        return [(value, value, [prop.rsplit("/", 1)[-1]]) for prop, value in self._properties()]

    def apply(self, accel: str) -> None:
        for prop, value in self._properties():
            if prop.startswith("/commands/custom/") and is_ours(value):
                subprocess.run(["xfconf-query", "-c", self.CHANNEL, "-p", prop, "-r"], check=False)
        if accel:
            subprocess.run(["xfconf-query", "-c", self.CHANNEL, "-p", f"/commands/custom/{accel}",
                            "-n", "-t", "string", "-s", RECORD_COMMAND], check=True)


def detect() -> Backend | None:
    """The backend for the running desktop, or None when shortcuts must be set by hand (e.g. KDE)."""
    desktops = [d.lower() for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":") if d]
    for names, backend in ((("x-cinnamon", "cinnamon"), CinnamonBackend),
                           (("mate",), MateBackend),
                           (("xfce",), XfceBackend),
                           (("gnome", "unity", "budgie", "budgie-desktop", "ubuntu"), GnomeBackend)):
        if any(d in names for d in desktops):
            candidate = backend()
            if candidate.available():
                return candidate
            log.warning("%s detected but its shortcut settings are unavailable", candidate.name)
            return None
    return None
