"""Command line. `jiffy` starts or stops a recording; `jiffy settings`, `jiffy setup` and friends do what they say.

Every command is forwarded over D-Bus to the one resident Jiffy, starting it in the background when
it is not running yet. `--background` (login autostart) and `--foreground` (development) host it.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time

from jiffy import APP_ID, APP_NAME, PRGNAME, __version__

COMMANDS = ("record", "stop", "cancel", "settings", "setup", "quit")
OBJECT_PATH = "/" + APP_ID.replace(".", "/")
START_TIMEOUT_SECONDS = 10


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=PRGNAME, description=f"{APP_NAME}: record a region of the screen to a GIF.")
    parser.add_argument("command", nargs="?", default="record", choices=COMMANDS,
                        help="record (default: start, or stop if recording), stop, cancel, settings, "
                             "setup (bind the shortcut), quit")
    parser.add_argument("--background", action="store_true", help="start the resident app and return")
    parser.add_argument("--foreground", action="store_true", help="run the resident app in this terminal")
    parser.add_argument("--gapplication-service", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser.parse_args(argv)


def run_app(service: bool) -> int:
    from jiffy.app import JiffyApp

    app = JiffyApp()
    status = app.run([PRGNAME, "--gapplication-service"] if service else [PRGNAME])
    if app.restart_requested:
        os.execv(sys.executable, [sys.executable, "-m", PRGNAME, "--background"])
    return status


def send(action: str) -> int:
    """Run an action in the resident app, starting it first if neither it nor D-Bus activation is there."""
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    request = GLib.Variant("(sava{sv})", (action, [], {}))

    def call() -> None:
        bus.call_sync(APP_ID, OBJECT_PATH, "org.freedesktop.Application", "ActivateAction", request,
                      None, Gio.DBusCallFlags.NONE, 5000, None)

    try:
        call()
        return 0
    except GLib.Error as e:
        if "ServiceUnknown" not in (Gio.DBusError.get_remote_error(e) or ""):
            print(f"{PRGNAME}: {e.message}", file=sys.stderr)
            return 1
    subprocess.Popen([sys.executable, "-m", PRGNAME, "--background"], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.1)
        try:
            call()
            return 0
        except GLib.Error:
            continue
    print(f"{PRGNAME}: {APP_NAME} did not start", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.DEBUG if os.environ.get("JIFFY_DEBUG") else logging.INFO,
                        format=f"{PRGNAME}: %(levelname)s %(name)s: %(message)s")
    if args.gapplication_service:
        return run_app(service=True)
    if args.foreground:
        return run_app(service=False)
    if args.background:
        if os.fork() == 0:
            os.setsid()
            os._exit(run_app(service=False))
        return 0
    status = send(args.command)
    if status == 0 and args.command == "setup":
        report_shortcut()
    return status


def report_shortcut() -> None:
    """After `jiffy setup`, print the shortcut the resident app bound. The D-Bus call returns only
    once the action has run, so the config already holds it.
    """
    from jiffy import config, shortcuts

    cfg = config.load()
    if not cfg.first_run_done:
        print(f"{APP_NAME} could not set its shortcut. Run `{PRGNAME} settings` to pick one.", file=sys.stderr)
    elif shortcuts.detect() is None:
        print(f"{APP_NAME} is ready. Your desktop needs the shortcut set by hand: in its keyboard settings, "
              f"bind a key to\n  {shortcuts.RECORD_COMMAND}")
    else:
        print(f"{APP_NAME} is ready. Press {shortcuts.label(cfg.shortcut)} to record a GIF, and again to stop.")


if __name__ == "__main__":
    sys.exit(main())
