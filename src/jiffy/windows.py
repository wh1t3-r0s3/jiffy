"""Where the visible windows are, top-most first, so one click in the selector can pick a whole window."""

from __future__ import annotations

import logging

from jiffy import PRGNAME
from jiffy.geometry import Rect

log = logging.getLogger(__name__)

ALL_DESKTOPS = 0xFFFFFFFF


def visible_windows() -> list[Rect]:
    """Rectangles of the windows on the current workspace, top-most first, in device pixels.

    Uses the window manager's stacking list and frame extents when there is one, so a pick
    includes the title bar of server-decorated windows and excludes the invisible shadow margin
    of client-decorated (GTK headerbar) ones. Without a window manager it falls back to the
    root window's children. Any X error just yields fewer windows; dragging still works.
    """
    try:
        from Xlib import X
        from Xlib import display as xdisplay
        from Xlib import error as xerror
    except ImportError:
        log.warning("python3-xlib is missing; clicking a window to select it is unavailable")
        return []
    try:
        d = xdisplay.Display()
    except Exception:  # noqa: BLE001 - python-xlib raises several unrelated types on connect
        log.exception("cannot open the X display for the window list")
        return []
    try:
        return _collect(d, X, xerror)
    finally:
        d.close()


def _collect(d, X, xerror) -> list[Rect]:
    root = d.screen().root
    atom = d.intern_atom

    def prop(window, name):
        value = window.get_full_property(atom(name), X.AnyPropertyType)
        return list(value.value) if value is not None else None

    stacking = prop(root, "_NET_CLIENT_LIST_STACKING")
    managed = bool(stacking)
    windows = ([d.create_resource_object("window", xid) for xid in stacking] if managed
               else root.query_tree().children)
    current = prop(root, "_NET_CURRENT_DESKTOP")
    current = current[0] if current else None
    hidden = atom("_NET_WM_STATE_HIDDEN")

    rects = []
    for window in reversed(windows):
        try:
            attrs = window.get_attributes()
            if attrs.map_state != X.IsViewable or (not managed and attrs.override_redirect):
                continue
            wm_class = window.get_wm_class() or ()
            if any(PRGNAME in c.lower() for c in wm_class):
                continue
            if managed:
                if hidden in (prop(window, "_NET_WM_STATE") or []):
                    continue
                desktop = prop(window, "_NET_WM_DESKTOP")
                if desktop and current is not None and desktop[0] not in (current, ALL_DESKTOPS):
                    continue
            geom = window.get_geometry()
            origin = root.translate_coords(window, 0, 0)
            x, y, w, h = origin.x, origin.y, geom.width, geom.height
            frame = prop(window, "_NET_FRAME_EXTENTS")
            if frame and len(frame) == 4:
                left, right, top, bottom = frame
                x, y, w, h = x - left, y - top, w + left + right, h + top + bottom
            shadow = prop(window, "_GTK_FRAME_EXTENTS")
            if shadow and len(shadow) == 4:
                left, right, top, bottom = shadow
                x, y, w, h = x + left, y + top, w - left - right, h - top - bottom
            if w > 0 and h > 0:
                rects.append(Rect(x, y, w, h))
        except xerror.XError:
            continue
    return rects
