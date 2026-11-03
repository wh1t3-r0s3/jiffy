"""Puts a saved file on the clipboard the way a file manager's Copy does, so Ctrl+V pastes the file itself."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402

URI_LIST, FILE_MANAGER, TEXT = 1, 2, 3
TARGETS = (
    ("text/uri-list", URI_LIST),                 # browsers, chat apps
    ("x-special/gnome-copied-files", FILE_MANAGER),  # Nemo, Nautilus, Caja
    ("UTF8_STRING", TEXT),                       # terminals and text fields get the path
    ("text/plain;charset=utf-8", TEXT),
)


class FileClipboard:
    """Owns the clipboard while the resident app runs, serving the last saved file in several formats."""

    def __init__(self):
        self.path: Path | None = None
        self.widget = Gtk.Invisible()
        self.widget.realize()
        self.widget.connect("selection-get", self._on_get)

    def copy(self, path: Path) -> bool:
        self.path = path
        clipboard = Gdk.SELECTION_CLIPBOARD
        Gtk.selection_clear_targets(self.widget, clipboard)
        for name, info in TARGETS:
            Gtk.selection_add_target(self.widget, clipboard, Gdk.Atom.intern(name, False), info)
        return Gtk.selection_owner_set(self.widget, clipboard, Gdk.CURRENT_TIME)

    def _on_get(self, _widget, data: Gtk.SelectionData, info: int, _time: int) -> None:
        if self.path is None:
            return
        uri = Gio.File.new_for_path(str(self.path)).get_uri()
        if info == URI_LIST:
            data.set(data.get_target(), 8, f"{uri}\r\n".encode())
        elif info == FILE_MANAGER:
            data.set(data.get_target(), 8, f"copy\n{uri}".encode())
        else:
            data.set_text(str(self.path), -1)
