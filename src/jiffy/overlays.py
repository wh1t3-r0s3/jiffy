"""The small always-on-top windows shown around a recording: the red outline, the control bar, the countdown."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from jiffy.geometry import Rect, place_beside  # noqa: E402
from jiffy.screen import monitor_rects  # noqa: E402

BORDER_PX = 2
RED = "#ff3b30"

CSS = f"""
.jiffy-border {{ background-color: {RED}; }}
.jiffy-window {{ background-color: transparent; }}
.jiffy-window.opaque {{ background-color: #1e1e22; }}
.jiffy-bar {{ background-color: #1e1e22; border: 1px solid #44444b; border-radius: 9px; padding: 5px 6px 5px 10px; }}
.jiffy-bar label {{ color: #f2f2f2; }}
.jiffy-bar .dot {{ color: {RED}; }}
.jiffy-bar .status {{ font-family: monospace; font-weight: bold; }}
.jiffy-bar button {{ min-height: 0; min-width: 0; padding: 2px 10px; border-radius: 6px;
    border: none; box-shadow: none; background-image: none; text-shadow: none; }}
.jiffy-bar button.stop {{ background-color: {RED}; }}
.jiffy-bar button.stop:hover {{ background-color: #ff6259; }}
.jiffy-bar button.stop label {{ color: #ffffff; font-weight: bold; }}
.jiffy-bar button.cancel {{ background-color: #3a3a40; }}
.jiffy-bar button.cancel:hover {{ background-color: #57575f; }}
.jiffy-bar button.cancel label {{ color: #dddddd; }}
.jiffy-countdown {{ background-color: rgba(20, 20, 22, 0.85); border-radius: 22px; padding: 6px 30px; }}
.jiffy-countdown label {{ color: #ffffff; font-size: 64px; font-weight: bold; }}
"""


def popup(title: str, rounded: bool = False) -> Gtk.Window:
    """An undecorated window the window manager leaves alone: always on top, never takes focus."""
    win = Gtk.Window(type=Gtk.WindowType.POPUP)
    win.set_title(title)
    win.set_accept_focus(False)
    if rounded:
        screen = win.get_screen()
        visual = screen.get_rgba_visual()
        win.get_style_context().add_class("jiffy-window")
        if visual is not None and screen.is_composited():
            win.set_visual(visual)
            win.set_app_paintable(True)
        else:
            win.get_style_context().add_class("opaque")
    return win


class RegionBorder:
    """A thin red outline drawn just outside the recorded region, so it never appears in the recording."""

    def __init__(self, region: Rect):
        b = BORDER_PX
        self.windows = []
        for x, y, w, h in ((region.x - b, region.y - b, region.w + 2 * b, b),
                           (region.x - b, region.bottom, region.w + 2 * b, b),
                           (region.x - b, region.y, b, region.h),
                           (region.right, region.y, b, region.h)):
            win = popup("Jiffy border")
            win.get_style_context().add_class("jiffy-border")
            win.set_default_size(w, h)
            win.move(x, y)
            self.windows.append(win)

    def show(self) -> None:
        for win in self.windows:
            win.show()

    def destroy(self) -> None:
        for win in self.windows:
            win.destroy()
        self.windows = []


class CountdownBadge:
    """The big number in the middle of the region before recording starts."""

    def __init__(self, region: Rect):
        self.region = region
        self.win = popup("Jiffy countdown", rounded=True)
        box = Gtk.Box()
        box.get_style_context().add_class("jiffy-countdown")
        self.label = Gtk.Label()
        box.add(self.label)
        self.win.add(box)
        box.show_all()

    def show(self, n: int) -> None:
        self.label.set_text(str(n))
        size = self.win.get_child().get_preferred_size()[1]
        cx, cy = self.region.center
        self.win.resize(size.width, size.height)
        self.win.move(cx - size.width // 2, cy - size.height // 2)
        self.win.show()

    def destroy(self) -> None:
        self.win.destroy()


class ControlBar:
    """The floating bar beside the region: countdown, elapsed time with Stop and Cancel, then save progress."""

    def __init__(self, region: Rect, on_stop: Callable[[], None], on_cancel: Callable[[], None]):
        self.region = region
        self.mode = ""
        self.win = popup("Jiffy bar", rounded=True)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.get_style_context().add_class("jiffy-bar")
        self.dot = Gtk.Label(label="●")
        self.dot.get_style_context().add_class("dot")
        self.status = Gtk.Label(label="0:00")
        self.status.get_style_context().add_class("status")
        self.stop_button = Gtk.Button(label="■  Stop")
        self.stop_button.get_style_context().add_class("stop")
        self.stop_button.set_tooltip_text("Stop and save (or press the shortcut again)")
        self.stop_button.connect("clicked", lambda *_: on_stop())
        cancel = Gtk.Button(label="✕")
        cancel.get_style_context().add_class("cancel")
        cancel.set_tooltip_text("Cancel and throw it away")
        cancel.connect("clicked", lambda *_: on_cancel())
        for widget in (self.dot, self.status, self.stop_button, cancel):
            box.pack_start(widget, False, False, 0)
        self.win.add(box)
        box.show_all()

    def countdown(self, seconds_left: int) -> None:
        self._show("countdown", f"Starts in {seconds_left}")

    def recording(self, elapsed: float) -> None:
        whole = int(elapsed)
        self._show("recording", f"{whole // 60}:{whole % 60:02d}")
        self.dot.set_opacity(1.0 if int(elapsed * 2) % 2 == 0 else 0.25)

    def saving(self, fraction: float | None) -> None:
        self._show("saving", "Saving…" if fraction is None else f"Saving {min(99, int(fraction * 100))}%")

    def _show(self, mode: str, text: str) -> None:
        """Update the text; re-lay out and re-place the bar only when the mode changes."""
        self.status.set_text(text)
        if mode == self.mode:
            return
        self.mode = mode
        recording = mode == "recording"
        self.status.set_width_chars(10 if mode != "recording" else 0)
        self.stop_button.set_visible(recording)
        self.dot.set_visible(recording)
        self.dot.set_opacity(1.0)
        size = self.win.get_child().get_preferred_size()[1]
        x, y = place_beside(self.region, (size.width, size.height), monitor_rects(), BORDER_PX + 6)
        self.win.resize(size.width, size.height)
        self.win.move(x, y)
        self.win.show()

    def destroy(self) -> None:
        self.win.destroy()
