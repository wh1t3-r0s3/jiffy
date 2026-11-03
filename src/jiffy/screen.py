"""Monitor layout of the X screen, in GTK's logical pixels."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk  # noqa: E402

from jiffy.geometry import Rect  # noqa: E402


def monitor_rects() -> list[Rect]:
    display = Gdk.Display.get_default()
    rects = []
    for i in range(display.get_n_monitors()):
        g = display.get_monitor(i).get_geometry()
        rects.append(Rect(g.x, g.y, g.width, g.height))
    return rects


def scale_factor() -> int:
    return Gdk.get_default_root_window().get_scale_factor()
