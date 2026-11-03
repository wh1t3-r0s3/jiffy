"""The region picker: a full-screen overlay to drag a rectangle, click a window, or take a whole screen."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from jiffy.geometry import Rect  # noqa: E402
from jiffy.screen import monitor_rects  # noqa: E402
from jiffy.windows import visible_windows  # noqa: E402

log = logging.getLogger(__name__)

ACCENT = (1.0, 0.23, 0.19)
DIM = 0.38
DRAG_THRESHOLD = 3
HINT = "Drag to select   ·   Click a window   ·   Space: whole screen   ·   Esc: cancel"
GRAB_ATTEMPTS = 20


class Selector:
    """One region pick. Calls `on_done` once with the chosen rectangle in device pixels, or None if cancelled.

    On a composited desktop the overlay is translucent, so animations stay visible while you aim;
    without a compositor it shows a frozen screenshot instead.
    """

    def __init__(self, on_done: Callable[[Rect | None], None]):
        self.on_done = on_done
        self.finished = False
        root = Gdk.get_default_root_window()
        _, _, width, height = root.get_geometry()
        self.scale = root.get_scale_factor()
        self.screen = Rect(0, 0, width, height)
        self.monitors = monitor_rects() or [self.screen]
        self.windows = [r.scaled(1 / self.scale) for r in visible_windows()]
        self.pointer = self.screen.center
        self.press: tuple[int, int] | None = None
        self.dragging = False

        gdk_screen = Gdk.Screen.get_default()
        visual = gdk_screen.get_rgba_visual()
        self.live = gdk_screen.is_composited() and visual is not None
        self.frozen = None if self.live else Gdk.pixbuf_get_from_window(root, 0, 0, width, height)

        win = Gtk.Window(type=Gtk.WindowType.POPUP)
        win.set_title("Jiffy selector")
        if self.live:
            win.set_visual(visual)
        win.set_app_paintable(True)
        win.set_default_size(width, height)
        win.move(0, 0)
        win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                       | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        win.connect("draw", self._on_draw)
        win.connect("button-press-event", self._on_press)
        win.connect("button-release-event", self._on_release)
        win.connect("motion-notify-event", self._on_motion)
        win.connect("key-press-event", self._on_key)
        self.win = win
        self.seat = Gdk.Display.get_default().get_default_seat()

    # -- lifecycle

    def show(self) -> None:
        self.win.show_all()
        _, x, y = self.seat.get_pointer().get_position()
        self.pointer = (x, y)
        self._grab(GRAB_ATTEMPTS)

    def _grab(self, attempts_left: int) -> bool:
        """Take the pointer and keyboard; another app may briefly hold a grab, so retry for a moment."""
        if self.finished:
            return False
        cursor = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "crosshair")
        status = self.seat.grab(self.win.get_window(), Gdk.SeatCapabilities.ALL, False, cursor, None, None, None)
        if status == Gdk.GrabStatus.SUCCESS:
            self.win.queue_draw()
            return False
        if attempts_left <= 1:
            log.warning("could not grab the pointer and keyboard (%s); giving up", status)
            self._finish(None)
            return False
        GLib.timeout_add(30, self._grab, attempts_left - 1)
        return False

    def _finish(self, rect: Rect | None) -> None:
        if self.finished:
            return
        self.finished = True
        self.seat.ungrab()
        self.win.destroy()
        if rect is not None:
            rect = rect.intersection(self.screen)
        if rect is not None:
            rect = rect.scaled(self.scale)
        self.on_done(rect)

    def cancel(self) -> None:
        self._finish(None)

    # -- targets

    def _monitor_at(self, x: int, y: int) -> Rect:
        return next((m for m in self.monitors if m.contains(x, y)), self.monitors[0])

    def _hover_target(self) -> Rect:
        x, y = self.pointer
        for rect in self.windows:
            if rect.contains(x, y):
                return rect.intersection(self.screen) or self._monitor_at(x, y)
        return self._monitor_at(x, y)

    def _drag_rect(self) -> Rect:
        return Rect.from_corners(*self.press, *self.pointer)

    def current(self) -> Rect:
        return self._drag_rect() if self.dragging else self._hover_target()

    # -- events

    def _on_press(self, _w, event) -> bool:
        if event.button == 3:
            self._finish(None)
        elif event.button == 1:
            self.press = (int(event.x_root), int(event.y_root))
            self.dragging = False
        return True

    def _on_motion(self, _w, event) -> bool:
        self.pointer = (int(event.x_root), int(event.y_root))
        if self.press and not self.dragging:
            dx, dy = self.pointer[0] - self.press[0], self.pointer[1] - self.press[1]
            self.dragging = math.hypot(dx, dy) > DRAG_THRESHOLD
        self.win.queue_draw()
        return True

    def _on_release(self, _w, event) -> bool:
        if event.button != 1 or self.press is None:
            return True
        self.pointer = (int(event.x_root), int(event.y_root))
        self._finish(self.current())
        return True

    def _on_key(self, _w, event) -> bool:
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self._finish(None)
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._finish(self.current())
        elif key == Gdk.KEY_space:
            self._finish(self._monitor_at(*self.pointer))
        elif key in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down):
            step = 10 if event.state & Gdk.ModifierType.SHIFT_MASK else 1
            dx = {Gdk.KEY_Left: -step, Gdk.KEY_Right: step}.get(key, 0)
            dy = {Gdk.KEY_Up: -step, Gdk.KEY_Down: step}.get(key, 0)
            x = min(max(self.pointer[0] + dx, 0), self.screen.w - 1)
            y = min(max(self.pointer[1] + dy, 0), self.screen.h - 1)
            self.seat.get_pointer().warp(Gdk.Screen.get_default(), x, y)
        return True

    # -- drawing

    def _on_draw(self, _w, cr) -> bool:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        if self.frozen is not None:
            Gdk.cairo_set_source_pixbuf(cr, self.frozen, 0, 0)
        else:
            cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        sel = self.current()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, self.screen.w, self.screen.h)
        cr.rectangle(sel.x, sel.y, sel.w, sel.h)
        cr.set_source_rgba(0, 0, 0, DIM)
        cr.fill()

        cr.set_line_width(2)
        cr.set_source_rgba(*ACCENT, 1.0 if self.dragging else 0.85)
        cr.rectangle(sel.x - 1, sel.y - 1, sel.w + 2, sel.h + 2)
        cr.stroke()

        monitor = self._monitor_at(*self.pointer)
        if not self.dragging:
            px, py = self.pointer
            cr.set_line_width(1)
            cr.set_source_rgba(1, 1, 1, 0.35)
            cr.move_to(monitor.x, py + 0.5)
            cr.line_to(monitor.right, py + 0.5)
            cr.move_to(px + 0.5, monitor.y)
            cr.line_to(px + 0.5, monitor.bottom)
            cr.stroke()

        device = sel.scaled(self.scale)
        label_y = sel.bottom + 8 if sel.bottom + 34 < monitor.bottom else sel.y + 8
        self._pill(cr, f"{device.w} × {device.h}", sel.x, label_y, monitor)
        self._pill(cr, HINT, monitor.x + monitor.w // 2, monitor.y + 24, monitor, centered=True)
        return True

    def _pill(self, cr, text: str, x: int, y: int, bounds: Rect, centered: bool = False) -> None:
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription.from_string("Sans Bold 10"))
        layout.set_text(text, -1)
        tw, th = layout.get_pixel_size()
        pad_x, pad_y = 10, 5
        w, h = tw + 2 * pad_x, th + 2 * pad_y
        if centered:
            x -= w // 2
        x = min(max(x, bounds.x + 4), bounds.right - w - 4)
        y = min(max(y, bounds.y + 4), bounds.bottom - h - 4)
        radius = h / 2
        cr.new_sub_path()
        cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, math.pi / 2)
        cr.arc(x + radius, y + radius, radius, math.pi / 2, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgba(0.08, 0.08, 0.09, 0.88)
        cr.fill()
        cr.move_to(x + pad_x, y + pad_y)
        cr.set_source_rgba(1, 1, 1, 0.95)
        PangoCairo.show_layout(cr, layout)
