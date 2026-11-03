"""ffmpeg command lines for capturing the screen and encoding the result. Pure functions, unit-tested.

Capture writes a lossless intermediate file so encoding can make a good palette from the whole clip
and so one recording can be encoded into any output format.
"""

from __future__ import annotations

from pathlib import Path

from jiffy.geometry import Rect

# Hard cap on any capture, so a capture process orphaned by a crash cannot fill the disk.
CAPTURE_CEILING_SECONDS = 2 * 60 * 60

BASE = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
PROGRESS = ["-progress", "pipe:1", "-nostats"]


def capture_cmd(display: str, region: Rect, fps: int, cursor: bool, out: Path, max_seconds: int) -> list[str]:
    """Record `region` of X display `display` until ffmpeg reads 'q' on stdin or the time limit hits.

    x11grab captures from the moment it opens, but ffmpeg spends its first second or so measuring the
    frame rate before it writes anything; a 'q' in that window discards the clip. Progress lines on
    stdout ("frame=N") tell the caller when writing has begun and a 'q' is safe.
    """
    limit = max_seconds if max_seconds > 0 else CAPTURE_CEILING_SECONDS
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "x11grab", "-draw_mouse", "1" if cursor else "0",
        "-framerate", str(fps), "-video_size", f"{region.w}x{region.h}",
        "-i", f"{display}+{region.x},{region.y}",
        "-t", str(min(limit, CAPTURE_CEILING_SECONDS)),
        "-c:v", "libx264rgb", "-preset", "ultrafast", "-qp", "0",
        *PROGRESS, str(out),
    ]


def video_filter(fps: int, width: int, max_width: int, even: bool = False) -> str:
    """fps normalisation plus an optional downscale; `even` rounds sizes to even numbers for H.264."""
    parts = [f"fps={fps}"]
    if max_width > 0 and width > max_width:
        parts.append(f"scale={max_width}:-2:flags=lanczos" if even else f"scale={max_width}:-1:flags=lanczos")
    elif even:
        parts.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
    return ",".join(parts)


def _source(src: Path, seconds: float) -> list[str]:
    """Input options reading only the first `seconds` of the capture: the time the user actually recorded."""
    return ["-t", f"{seconds:.3f}", "-i", str(src)]


def frame_count(line: str) -> int | None:
    """The frame count from a `-progress` line, or None for other lines."""
    key, _, value = line.strip().partition("=")
    if key != "frame":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def gif_palette_cmd(src: Path, seconds: float, palette: Path, vf: str, colors: int) -> list[str]:
    graph = f"{vf},palettegen=max_colors={colors}:stats_mode=full"
    return [*BASE, *_source(src, seconds), "-vf", graph, *PROGRESS, str(palette)]


def gif_encode_cmd(src: Path, seconds: float, palette: Path, out: Path, vf: str, dither: str) -> list[str]:
    graph = f"[0:v]{vf}[v];[v][1:v]paletteuse=dither={dither}:diff_mode=rectangle"
    return [*BASE, *_source(src, seconds), "-i", str(palette), "-lavfi", graph, "-loop", "0",
            *PROGRESS, str(out)]


def mp4_encode_cmd(src: Path, seconds: float, out: Path, vf: str, crf: int) -> list[str]:
    return [*BASE, *_source(src, seconds), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
            "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", *PROGRESS, str(out)]


def parse_progress_seconds(line: str) -> float | None:
    """Seconds of output written so far, from one line of `-progress` output; None for other lines."""
    key, _, value = line.strip().partition("=")
    if key not in ("out_time_us", "out_time_ms"):
        return None
    try:
        return max(0, int(value)) / 1_000_000
    except ValueError:
        return None
