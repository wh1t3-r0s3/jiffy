"""Rectangle math for the selector, the recording border and the control bar. Pure Python, no GTK."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in screen pixels; `right` and `bottom` are exclusive."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @classmethod
    def from_corners(cls, x0: int, y0: int, x1: int, y1: int) -> Rect:
        """The rectangle spanning two corner pixels, both included, in any order."""
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        return cls(left, top, right - left + 1, bottom - top + 1)

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def contains_rect(self, other: Rect) -> bool:
        return (self.x <= other.x and self.y <= other.y
                and other.right <= self.right and other.bottom <= self.bottom)

    def intersects(self, other: Rect) -> bool:
        return (self.x < other.right and other.x < self.right
                and self.y < other.bottom and other.y < self.bottom)

    def intersection(self, other: Rect) -> Rect | None:
        x, y = max(self.x, other.x), max(self.y, other.y)
        right, bottom = min(self.right, other.right), min(self.bottom, other.bottom)
        if right <= x or bottom <= y:
            return None
        return Rect(x, y, right - x, bottom - y)

    def inflate(self, n: int) -> Rect:
        return Rect(self.x - n, self.y - n, self.w + 2 * n, self.h + 2 * n)

    def scaled(self, factor: float) -> Rect:
        """Convert between logical and device pixels on a scaled (HiDPI) screen."""
        x, y = round(self.x * factor), round(self.y * factor)
        return Rect(x, y, round(self.right * factor) - x, round(self.bottom * factor) - y)


def place_beside(region: Rect, size: tuple[int, int], monitors: list[Rect], gap: int) -> tuple[int, int]:
    """Where to put a small window (the control bar) so it sits next to `region` but never over it.

    Tries below, above, right and left of the region on its own monitor, then the bottom of any
    other monitor, and only falls back to the region's inside corner when nothing else fits.
    """
    bw, bh = size
    home = next((m for m in monitors if m.contains(*region.center)), monitors[0] if monitors else region)

    def clamp_x(x: int) -> int:
        return min(max(x, home.x), home.right - bw)

    candidates = [
        (clamp_x(region.right - bw), region.bottom + gap),
        (clamp_x(region.right - bw), region.y - bh - gap),
        (region.right + gap, region.bottom - bh),
        (region.x - bw - gap, region.bottom - bh),
    ]
    candidates += [(m.x + (m.w - bw) // 2, m.bottom - bh - 60) for m in monitors if m != home]
    keep_clear = region.inflate(gap - 1) if gap > 0 else region
    for x, y in candidates:
        spot = Rect(x, y, bw, bh)
        if any(m.contains_rect(spot) for m in monitors) and not spot.intersects(keep_clear):
            return x, y
    return region.right - bw - 8, region.bottom - bh - 8
