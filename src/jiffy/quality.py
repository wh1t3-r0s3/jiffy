"""Quality presets: one setting that picks frame rate, size cap and colour depth together, per output format."""

from __future__ import annotations

from dataclasses import dataclass

LEVELS = ("small", "balanced", "sharp")
LABELS = {"small": "Small file", "balanced": "Balanced", "sharp": "Sharp"}


@dataclass(frozen=True)
class Preset:
    """Everything a quality level decides. `max_width` 0 keeps the recorded size."""

    fps: int
    max_width: int
    colors: int = 256        # GIF palette size
    dither: str = "bayer:bayer_scale=5"
    crf: int = 23            # MP4 quality, lower is better


PRESETS = {
    ("gif", "small"): Preset(fps=10, max_width=720, colors=128),
    ("gif", "balanced"): Preset(fps=15, max_width=1280),
    ("gif", "sharp"): Preset(fps=25, max_width=0, dither="sierra2_4a"),
    ("mp4", "small"): Preset(fps=24, max_width=1280, crf=28),
    ("mp4", "balanced"): Preset(fps=30, max_width=0, crf=23),
    ("mp4", "sharp"): Preset(fps=60, max_width=0, crf=18),
}


def preset(fmt: str, level: str) -> Preset:
    return PRESETS.get((fmt, level), PRESETS[("gif", "balanced")])


def describe(fmt: str, level: str) -> str:
    """One line for the settings window, e.g. '15 fps · up to 1280 px wide'."""
    p = preset(fmt, level)
    size = f"up to {p.max_width} px wide" if p.max_width else "full size"
    extra = f" · {p.colors} colours" if fmt == "gif" and p.colors < 256 else ""
    return f"{p.fps} fps · {size}{extra}"
