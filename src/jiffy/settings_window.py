"""The settings window: a short list of plain choices. Changes apply when you press Save."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from jiffy import APP_ID, APP_NAME, __version__, autostart, config, quality, shortcuts  # noqa: E402
from jiffy.config import Config  # noqa: E402

MODIFIER_KEYS = {getattr(Gdk, f"KEY_{n}") for n in (
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R",
    "Meta_L", "Meta_R", "Hyper_L", "Hyper_R", "ISO_Level3_Shift", "Caps_Lock", "Num_Lock")}

FORMATS = (("gif", "GIF"), ("mp4", "MP4 video"))
COUNTDOWNS = ((0, "Off"), (3, "3 seconds"), (5, "5 seconds"))
LENGTHS = ((30, "30 seconds"), (60, "1 minute"), (300, "5 minutes"), (0, "No limit"))
AFTER_SAVE = (("nothing", "Just notify me"), ("open", "Open it"), ("folder", "Show it in its folder"))
CONTROL_WIDTH = 240


def seconds_label(n: int) -> str:
    return f"{n} seconds" if n < 60 or n % 60 else f"{n // 60} minutes"


class SettingsWindow(Gtk.ApplicationWindow):
    """Edits a copy of the config; Save writes it, rebinds the shortcut if it changed and calls `on_saved`."""

    def __init__(self, app: Gtk.Application, on_saved: Callable[[Config], None]):
        super().__init__(application=app, title=f"{APP_NAME} settings")
        self.on_saved = on_saved
        self.cfg = config.load()
        self.backend = shortcuts.detect()
        self.shortcut = self.cfg.shortcut
        self.capturing = False
        self.seat = Gdk.Display.get_default().get_default_seat()
        self.set_icon_name(APP_ID)
        self.set_border_width(20)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("key-press-event", self._on_key)

        self.grid = Gtk.Grid(row_spacing=10, column_spacing=16)
        self.row = 0
        self._build()

        self.status = Gtk.Label(xalign=0, wrap=True, max_width_chars=52, selectable=True)
        self.status.get_style_context().add_class("dim-label")
        save = Gtk.Button(label="Save")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._on_save)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.destroy())
        version = Gtk.Label(label=f"{APP_NAME} {__version__}", xalign=0)
        version.get_style_context().add_class("dim-label")
        buttons = Gtk.Box(spacing=8)
        buttons.pack_start(version, False, False, 0)
        buttons.pack_end(save, False, False, 0)
        buttons.pack_end(cancel, False, False, 0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.pack_start(self.grid, False, False, 0)
        outer.pack_start(self.status, False, False, 0)
        outer.pack_start(buttons, False, False, 0)
        self.add(outer)
        self._refresh_quality_hint()
        self._refresh_shortcut_status()

    # -- layout helpers

    def _section(self, title: str) -> None:
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        if self.row:
            label.set_margin_top(10)
        self.grid.attach(label, 0, self.row, 2, 1)
        self.row += 1

    def _add(self, title: str, widget: Gtk.Widget) -> None:
        name = Gtk.Label(label=title, xalign=0)
        name.set_margin_start(12)
        self.grid.attach(name, 0, self.row, 1, 1)
        if not isinstance(widget, Gtk.Switch):
            widget.set_size_request(CONTROL_WIDTH, -1)
        widget.set_halign(Gtk.Align.START)
        self.grid.attach(widget, 1, self.row, 1, 1)
        self.row += 1

    def _note(self) -> Gtk.Label:
        note = Gtk.Label(xalign=0)
        note.get_style_context().add_class("dim-label")
        self.grid.attach(note, 1, self.row, 1, 1)
        self.row += 1
        return note

    @staticmethod
    def _combo(options, current) -> Gtk.ComboBoxText:
        """A dropdown of (value, label) pairs; a current value not in the list is kept as an extra entry."""
        combo = Gtk.ComboBoxText()
        values = [str(v) for v, _ in options]
        for value, text in options:
            combo.append(str(value), text)
        if str(current) not in values and isinstance(current, int):
            combo.append(str(current), seconds_label(current))
        combo.set_active_id(str(current))
        return combo

    def _build(self) -> None:
        c = self.cfg
        self._section("Recording")
        self.shortcut_button = Gtk.Button(label=shortcuts.label(self.shortcut))
        self.shortcut_button.set_tooltip_text("Click, then press the new shortcut. Esc cancels, Backspace clears.")
        self.shortcut_button.connect("clicked", self._start_capture)
        self._add("Shortcut", self.shortcut_button)
        self.countdown = self._combo(COUNTDOWNS, c.start_delay)
        self._add("Countdown", self.countdown)
        self.length = self._combo(LENGTHS, c.max_seconds)
        self._add("Max length", self.length)
        self.cursor = Gtk.Switch(active=c.show_cursor)
        self._add("Show the cursor", self.cursor)
        self.border = Gtk.Switch(active=c.show_border)
        self._add("Red outline while recording", self.border)

        self._section("Output")
        self.format = self._combo(FORMATS, c.format)
        self.format.connect("changed", lambda *_: self._refresh_quality_hint())
        self._add("Save as", self.format)
        self.quality = self._combo(tuple(quality.LABELS.items()), c.quality)
        self.quality.connect("changed", lambda *_: self._refresh_quality_hint())
        self._add("Quality", self.quality)
        self.quality_hint = self._note()
        self.folder = Gtk.FileChooserButton(title="Save recordings to", action=Gtk.FileChooserAction.SELECT_FOLDER)
        out_dir = config.output_dir(c)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.folder.set_current_folder(str(out_dir))
        self._add("Save to", self.folder)
        self.copy = Gtk.Switch(active=c.copy_to_clipboard)
        self._add("Copy to clipboard", self.copy)
        self.after_save = self._combo(AFTER_SAVE, c.after_save)
        self._add("When it's saved", self.after_save)

        self._section("General")
        self.login = Gtk.Switch(active=autostart.is_enabled())
        self._add("Start at login", self.login)

    def _refresh_quality_hint(self) -> None:
        self.quality_hint.set_text(quality.describe(self.format.get_active_id() or "gif",
                                                    self.quality.get_active_id() or "balanced"))

    # -- shortcut capture

    def _start_capture(self, _button) -> None:
        if self.capturing:
            return
        self.capturing = True
        self.shortcut_button.set_label("Press a shortcut…")
        # An active keyboard grab outranks the desktop's own shortcuts, so even Print reaches us.
        self.seat.grab(self.get_window(), Gdk.SeatCapabilities.KEYBOARD, False, None, None, None, None)

    def _on_key(self, _w, event) -> bool:
        if not self.capturing:
            return False
        key = Gdk.keyval_to_lower(event.keyval)
        if key in MODIFIER_KEYS:
            return True
        mods = event.state & Gtk.accelerator_get_default_mod_mask()
        if key == Gdk.KEY_Escape and not mods:
            pass
        elif key == Gdk.KEY_BackSpace and not mods:
            self.shortcut = ""
        else:
            self.shortcut = Gtk.accelerator_name(key, mods)
        self.capturing = False
        self.seat.ungrab()
        self.shortcut_button.set_label(shortcuts.label(self.shortcut))
        self._refresh_shortcut_status()
        return True

    def _refresh_shortcut_status(self) -> None:
        if self.backend is None:
            self.status.set_text("Your desktop isn't set up automatically. In its keyboard settings, bind "
                                 f"this command to a key:\n{shortcuts.RECORD_COMMAND}")
            return
        taken = self.backend.conflicts(self.shortcut)
        self.status.set_text(f"{shortcuts.label(self.shortcut)} is already used by: {', '.join(taken)}. "
                             "Pick another or that one stops working." if taken else "")

    # -- save

    def _on_save(self, _button) -> None:
        c = self.cfg
        old_shortcut = c.shortcut
        c.shortcut = self.shortcut
        c.start_delay = int(self.countdown.get_active_id() or c.start_delay)
        c.max_seconds = int(self.length.get_active_id() or c.max_seconds)
        c.show_cursor = self.cursor.get_active()
        c.show_border = self.border.get_active()
        c.format = self.format.get_active_id() or c.format
        c.quality = self.quality.get_active_id() or c.quality
        c.output_dir = self.folder.get_filename() or c.output_dir
        c.copy_to_clipboard = self.copy.get_active()
        c.after_save = self.after_save.get_active_id() or c.after_save
        if self.backend is not None and c.shortcut != old_shortcut:
            try:
                self.backend.apply(c.shortcut)
            except (OSError, subprocess.SubprocessError, GLib.Error) as e:
                self.status.set_text(f"Could not set the shortcut: {e}")
                return
        if self.login.get_active() != autostart.is_enabled():
            autostart.set_enabled(self.login.get_active())
        config.save(c)
        self.on_saved(c)
        self.destroy()
