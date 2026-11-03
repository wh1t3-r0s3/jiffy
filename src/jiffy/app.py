"""The resident app: answers the shortcut, runs recordings, owns the clipboard and sends notifications."""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from jiffy import APP_ID, APP_NAME, config, shortcuts  # noqa: E402
from jiffy.clipboard import FileClipboard  # noqa: E402
from jiffy.config import Config  # noqa: E402
from jiffy.overlays import CSS  # noqa: E402
from jiffy.session import Session, clean_stale_sessions  # noqa: E402
from jiffy.settings_window import SettingsWindow  # noqa: E402

log = logging.getLogger(__name__)

UPGRADE_SETTLE_SECONDS = 3


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class JiffyApp(Gtk.Application):
    """One instance per desktop session. The shortcut, the menu entries and the `jiffy` command all
    reach it through D-Bus actions, so it is always the same process doing the work.
    """

    def __init__(self):
        flags = getattr(Gio.ApplicationFlags, "DEFAULT_FLAGS", Gio.ApplicationFlags.FLAGS_NONE)
        super().__init__(application_id=APP_ID, flags=flags)
        self.cfg = Config()
        self.active: Session | None = None
        self.sessions: set[Session] = set()
        self.clipboard: FileClipboard | None = None
        self.settings_window: SettingsWindow | None = None
        self.package_monitor: Gio.FileMonitor | None = None
        self.upgrade_pending = False
        self.restart_requested = False

    # -- lifecycle

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        GLib.set_application_name(APP_NAME)
        self.hold()
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.cfg = config.load()
        self.clipboard = FileClipboard()
        clean_stale_sessions()
        for name, handler, param in (
            ("record", self._on_record, None),
            ("stop", self._on_stop, None),
            ("cancel", self._on_cancel, None),
            ("settings", self._on_settings, None),
            ("setup", self._on_setup, None),
            ("quit", self._on_quit, None),
            ("open-file", self._on_open_file, "s"),
            ("show-file", self._on_show_file, "s"),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new(param) if param else None)
            action.connect("activate", handler)
            self.add_action(action)
        self._watch_for_upgrade()
        if not self.cfg.first_run_done:
            GLib.idle_add(self._first_run)
        log.info("ready")

    def do_activate(self) -> None:
        """Nothing to show: Jiffy lives in the background until its shortcut is pressed."""

    # -- actions

    def _on_record(self, *_args) -> None:
        if self.active is not None and self.active.live:
            self.active.toggle()
            return
        self.cfg = config.load()
        session = Session(self.cfg, self._on_saved, self._on_failed, self._on_ended)
        self.active = session
        self.sessions.add(session)
        session.start()

    def _on_stop(self, *_args) -> None:
        if self.active is not None and self.active.live:
            self.active.stop()

    def _on_cancel(self, *_args) -> None:
        for session in list(self.sessions):
            session.cancel()

    def _on_settings(self, *_args) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self, self._on_settings_saved)
            self.settings_window.connect("destroy", self._on_settings_closed)
            self.settings_window.show_all()
        self.settings_window.present()

    def _on_settings_saved(self, cfg: Config) -> None:
        self.cfg = cfg

    def _on_settings_closed(self, *_args) -> None:
        self.settings_window = None

    def _on_setup(self, *_args) -> None:
        self._bind_shortcut(announce=True)

    def _on_quit(self, *_args) -> None:
        self._on_cancel()
        self.release()
        self.quit()

    def _on_open_file(self, _action, param: GLib.Variant) -> None:
        self._launch_uri(Gio.File.new_for_path(param.unpack()).get_uri())

    def _on_show_file(self, _action, param: GLib.Variant) -> None:
        path = param.unpack()
        uri = Gio.File.new_for_path(path).get_uri()

        def shown(bus: Gio.DBusConnection, result) -> None:
            try:
                bus.call_finish(result)
            except GLib.Error:
                self._launch_uri(Gio.File.new_for_path(str(Path(path).parent)).get_uri())
        Gio.bus_get_sync(Gio.BusType.SESSION).call(
            "org.freedesktop.FileManager1", "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1",
            "ShowItems", GLib.Variant("(ass)", ([uri], "")), None, Gio.DBusCallFlags.NONE, 5000, None, shown)

    # -- session callbacks

    def _on_saved(self, session: Session, path: Path) -> None:
        copied = self.cfg.copy_to_clipboard and self.clipboard.copy(path)
        kind = "MP4" if path.suffix == ".mp4" else "GIF"
        body = f"{path.name}  ·  {human_size(path.stat().st_size)}  ·  {session.duration:.1f}s"
        if copied:
            body += "\nCopied: paste it anywhere with Ctrl+V"
        target = GLib.Variant("s", str(path))
        note = Gio.Notification.new(f"{kind} saved")
        note.set_body(body)
        note.set_icon(Gio.FileIcon.new(Gio.File.new_for_path(str(path))) if kind == "GIF"
                      else Gio.ThemedIcon.new("video-x-generic"))
        note.set_default_action_and_target("app.open-file", target)
        note.add_button_with_target("Open", "app.open-file", target)
        note.add_button_with_target("Show in folder", "app.show-file", target)
        self.send_notification("saved", note)
        if self.cfg.after_save == "open":
            self.activate_action("open-file", target)
        elif self.cfg.after_save == "folder":
            self.activate_action("show-file", target)

    def _on_failed(self, _session: Session, title: str, detail: str) -> None:
        note = Gio.Notification.new(f"{APP_NAME}: {title}")
        note.set_body(detail or "No details were reported.")
        note.set_icon(Gio.ThemedIcon.new("dialog-error"))
        note.set_priority(Gio.NotificationPriority.HIGH)
        self.send_notification("error", note)

    def _on_ended(self, session: Session) -> None:
        self.sessions.discard(session)
        if self.active is session:
            self.active = None
        if self.upgrade_pending and not self.sessions:
            self._restart_for_upgrade()

    # -- first run and shortcut

    def _first_run(self) -> bool:
        self._bind_shortcut(announce=True)
        return False

    def _bind_shortcut(self, announce: bool) -> None:
        cfg = config.load()
        backend = shortcuts.detect()
        note = Gio.Notification.new(f"{APP_NAME} is ready")
        if backend is None:
            note.set_body(f"Bind this command to a key in your keyboard settings:\n{shortcuts.RECORD_COMMAND}")
        else:
            cfg.shortcut = shortcuts.choose(cfg.shortcut, backend.conflicts)
            try:
                backend.apply(cfg.shortcut)
                note.set_body(f"Press {shortcuts.label(cfg.shortcut)} to record a GIF. Press it again to stop.")
            except (OSError, GLib.Error) as e:
                log.exception("could not bind the shortcut")
                note.set_body(f"Could not set the shortcut ({e}). Open {APP_NAME} settings to pick one.")
        cfg.first_run_done = True
        config.save(cfg)
        self.cfg = cfg
        if announce:
            note.set_icon(Gio.ThemedIcon.new(APP_ID))
            note.set_default_action("app.settings")
            note.add_button("Settings", "app.settings")
            self.send_notification("ready", note)

    # -- upgrades

    def _watch_for_upgrade(self) -> None:
        """When the installed package is upgraded, restart into the new version once nothing is recording."""
        package_dir = Path(__file__).resolve().parent
        if not str(package_dir).startswith("/usr/"):
            return
        self.package_monitor = Gio.File.new_for_path(str(package_dir)).monitor_directory(
            Gio.FileMonitorFlags.NONE, None)
        self.package_monitor.connect("changed", self._on_package_changed)

    def _on_package_changed(self, *_args) -> None:
        if self.upgrade_pending:
            return
        self.upgrade_pending = True

        def settle() -> bool:
            if not self.sessions:
                self._restart_for_upgrade()
            return False
        GLib.timeout_add_seconds(UPGRADE_SETTLE_SECONDS, settle)

    def _restart_for_upgrade(self) -> None:
        log.info("%s was updated; restarting into the new version", APP_NAME)
        self.restart_requested = True
        self._on_quit()

    # -- helpers

    @staticmethod
    def _launch_uri(uri: str) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as e:
            log.warning("could not open %s: %s", uri, e.message)
