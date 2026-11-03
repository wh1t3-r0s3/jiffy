"""One recording, start to finish: pick a region, count down, capture, encode, save."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib  # noqa: E402

from jiffy import PRGNAME, config, ffmpeg, quality  # noqa: E402
from jiffy.config import Config  # noqa: E402
from jiffy.geometry import Rect  # noqa: E402
from jiffy.overlays import ControlBar, CountdownBadge, RegionBorder  # noqa: E402
from jiffy.screen import scale_factor  # noqa: E402
from jiffy.selector import Selector  # noqa: E402

log = logging.getLogger(__name__)

SETTLE_MS = 150          # let the compositor repaint after an overlay closes, so it never lands in a frame
STOP_GRACE_MS = 8000     # after asking ffmpeg to stop, wait this long before interrupting it
PALETTE_SHARE = 0.25     # share of the GIF save progress spent building the palette


class State(Enum):
    SELECTING = "selecting"
    COUNTDOWN = "countdown"
    RECORDING = "recording"
    ENCODING = "encoding"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


LIVE = {State.SELECTING, State.COUNTDOWN, State.RECORDING}
ENDED = {State.DONE, State.CANCELLED, State.FAILED}


def cache_root() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / PRGNAME


def clean_stale_sessions() -> None:
    """Remove work folders a crash left behind, stopping any capture that outlived its app."""
    root = cache_root()
    if not root.is_dir():
        return
    for workdir in root.iterdir():
        try:
            pid = int((workdir / "capture.pid").read_text())
            if str(workdir).encode() in Path(f"/proc/{pid}/cmdline").read_bytes():
                os.kill(pid, signal.SIGKILL)
        except (OSError, ValueError):
            pass
        shutil.rmtree(workdir, ignore_errors=True)


class Session:
    """One recording: drives the selector, the overlays and the ffmpeg processes through each state.

    Callbacks: `on_saved(session, path)` when the file is in the output folder,
    `on_failed(session, title, detail)` on any error, and `on_ended(session)` exactly once at the end.
    """

    _count = 0

    def __init__(self, cfg: Config,
                 on_saved: Callable[[Session, Path], None],
                 on_failed: Callable[[Session, str, str], None],
                 on_ended: Callable[[Session], None]):
        Session._count += 1
        self.cfg = cfg
        self.preset = quality.preset(cfg.format, cfg.quality)
        self.on_saved, self.on_failed, self.on_ended = on_saved, on_failed, on_ended
        self.state = State.SELECTING
        self.workdir = cache_root() / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{Session._count}"
        self.raw = self.workdir / "capture.mkv"
        self.palette = self.workdir / "palette.png"
        self.log_path = self.workdir / "ffmpeg.log"
        self.result: Path | None = None
        self.region = Rect(0, 0, 0, 0)          # logical pixels, for windows
        self.region_device = Rect(0, 0, 0, 0)   # device pixels, for ffmpeg
        self.selector: Selector | None = None
        self.bar: ControlBar | None = None
        self.border: RegionBorder | None = None
        self.badge: CountdownBadge | None = None
        self.capture: Gio.Subprocess | None = None
        self.running: set[Gio.Subprocess] = set()
        self.cancellable = Gio.Cancellable()
        self.timers: set[int] = set()
        self.started = 0.0
        self.duration = 0.0
        self.capture_writing = False
        self.stop_requested = False
        self.countdown_left = 0

    @property
    def live(self) -> bool:
        """Still selecting, counting down or recording (as opposed to saving or finished)."""
        return self.state in LIVE

    # -- public controls

    def start(self) -> None:
        self.selector = Selector(self._on_region)
        self.selector.show()

    def toggle(self) -> None:
        """What the shortcut does mid-session: stop a recording, abort a countdown or a selection."""
        if self.state is State.RECORDING:
            self.stop()
        else:
            self.cancel()

    def stop(self) -> None:
        if self.state is State.COUNTDOWN:
            self.cancel()
        elif self.state is State.RECORDING:
            self._finish_recording()
            self._ask_capture_to_stop()

    def cancel(self) -> None:
        if self.state in ENDED:
            return
        if self.selector is not None:
            self.selector.cancel()
        else:
            self._end(State.CANCELLED)

    # -- selection and countdown

    def _on_region(self, rect: Rect | None) -> None:
        self.selector = None
        if rect is None:
            self._end(State.CANCELLED)
            return
        self.region_device = rect
        self.region = rect.scaled(1 / scale_factor())
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.bar = ControlBar(self.region, self.stop, self.cancel)
        if self.cfg.show_border:
            self.border = RegionBorder(self.region)
            self.border.show()
        if self.cfg.start_delay > 0:
            self._start_countdown(self.cfg.start_delay)
        else:
            self._after(SETTLE_MS, self._start_capture)

    def _start_countdown(self, seconds: int) -> None:
        self.state = State.COUNTDOWN
        self.countdown_left = seconds
        self.badge = CountdownBadge(self.region)
        self.badge.show(seconds)
        self.bar.countdown(seconds)
        self._every(1000, self._countdown_tick)

    def _countdown_tick(self) -> bool:
        if self.state is not State.COUNTDOWN:
            return False
        self.countdown_left -= 1
        if self.countdown_left > 0:
            self.badge.show(self.countdown_left)
            self.bar.countdown(self.countdown_left)
            return True
        self.badge.destroy()
        self.badge = None
        self._after(SETTLE_MS, self._start_capture)
        return False

    # -- capture

    def _start_capture(self) -> None:
        if self.state not in (State.SELECTING, State.COUNTDOWN):
            return
        cmd = ffmpeg.capture_cmd(os.environ.get("DISPLAY", ":0"), self.region_device, self.preset.fps,
                                 self.cfg.show_cursor, self.raw, self.cfg.max_seconds)
        try:
            self.capture = self._spawn(cmd, stdin=True, stdout=True)
        except GLib.Error as e:
            self._fail("Could not start recording", e.message)
            return
        (self.workdir / "capture.pid").write_text(self.capture.get_identifier() or "")
        self.state = State.RECORDING
        self.started = time.monotonic()
        self.bar.recording(0)
        self._read_lines(self.capture, self._on_capture_progress)
        self.capture.wait_async(self.cancellable, self._on_capture_exit)
        self._every(250, self._recording_tick)
        log.info("recording %s at %d fps", self.region_device, self.preset.fps)

    def _on_capture_progress(self, line: str) -> None:
        frames = ffmpeg.frame_count(line)
        if frames and not self.capture_writing:
            self.capture_writing = True
            log.debug("capture writing after %.2fs", time.monotonic() - self.started)
            if self.stop_requested:
                self._send_quit()

    def _recording_tick(self) -> bool:
        if self.state is not State.RECORDING:
            return False
        self.bar.recording(time.monotonic() - self.started)
        return True

    def _finish_recording(self) -> None:
        """Leave the recording state: freeze the duration, drop the border, show the saving bar."""
        self.duration = time.monotonic() - self.started
        if self.cfg.max_seconds > 0:
            self.duration = min(self.duration, self.cfg.max_seconds)
        self.state = State.ENCODING
        if self.border is not None:
            self.border.destroy()
            self.border = None
        self.bar.saving(None)

    def _ask_capture_to_stop(self) -> None:
        """Stop ffmpeg cleanly, deferring until it has started writing (see `ffmpeg.capture_cmd`)."""
        self.stop_requested = True
        if self.capture_writing:
            self._send_quit()
        proc = self.capture

        def interrupt() -> None:
            if proc in self.running:
                proc.send_signal(signal.SIGINT)
        self._after(STOP_GRACE_MS, interrupt)

    def _send_quit(self) -> None:
        try:
            pipe = self.capture.get_stdin_pipe()
            pipe.write_bytes(GLib.Bytes.new(b"q"), None)
            pipe.close(None)
        except GLib.Error:
            pass

    def _on_capture_exit(self, proc: Gio.Subprocess, result) -> None:
        if not self._reap(proc, result):
            return
        (self.workdir / "capture.pid").unlink(missing_ok=True)
        clean = proc.get_if_exited() and proc.get_exit_status() == 0
        if self.state is State.RECORDING:
            if not clean:
                self._fail("Recording stopped unexpectedly", self._log_tail())
                return
            self._finish_recording()   # ffmpeg reached the "stop after" limit by itself
        if self.state is not State.ENCODING:
            return
        if not self.raw.exists() or self.raw.stat().st_size == 0:
            self._fail("Nothing was recorded", self._log_tail() or "The recording was too short.")
            return
        self._encode()

    # -- encoding

    def _encode(self) -> None:
        p = self.preset
        mp4 = self.cfg.format == "mp4"
        vf = ffmpeg.video_filter(p.fps, self.region_device.w, p.max_width, even=mp4)
        if mp4:
            self.result = self.workdir / "out.mp4"
            self._run_step(ffmpeg.mp4_encode_cmd(self.raw, self.duration, self.result, vf, p.crf),
                           0.0, 1.0, self._encoded)
            return
        self.result = self.workdir / "out.gif"

        def second_pass() -> None:
            self._run_step(ffmpeg.gif_encode_cmd(self.raw, self.duration, self.palette, self.result, vf, p.dither),
                           PALETTE_SHARE, 1.0, self._encoded)
        self._run_step(ffmpeg.gif_palette_cmd(self.raw, self.duration, self.palette, vf, p.colors),
                       0.0, PALETTE_SHARE, second_pass)

    def _run_step(self, cmd: list[str], start: float, end: float, then: Callable[[], None]) -> None:
        if self.state is not State.ENCODING:
            return
        try:
            proc = self._spawn(cmd, stdout=True)
        except GLib.Error as e:
            self._fail("Could not save the recording", e.message)
            return
        self._follow_progress(proc, start, end)

        def done(p: Gio.Subprocess, result) -> None:
            if not self._reap(p, result) or self.state is not State.ENCODING:
                return
            if p.get_if_exited() and p.get_exit_status() == 0:
                then()
            else:
                self._fail("Could not save the recording", self._log_tail())
        proc.wait_async(self.cancellable, done)

    def _follow_progress(self, proc: Gio.Subprocess, start: float, end: float) -> None:
        def on_line(line: str) -> None:
            seconds = ffmpeg.parse_progress_seconds(line)
            if seconds is not None and self.duration > 0 and self.state is State.ENCODING:
                self.bar.saving(start + (end - start) * min(1.0, seconds / self.duration))
        self._read_lines(proc, on_line)

    def _read_lines(self, proc: Gio.Subprocess, on_line: Callable[[str], None]) -> None:
        """Feed each line of a process's stdout to `on_line`, without blocking the UI."""
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

        def next_line(s: Gio.DataInputStream, result) -> None:
            try:
                line, _length = s.read_line_finish_utf8(result)
            except GLib.Error:
                return
            if line is None or self.state in ENDED:
                return
            on_line(line)
            s.read_line_async(GLib.PRIORITY_DEFAULT, self.cancellable, next_line)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, self.cancellable, next_line)

    def _encoded(self) -> None:
        try:
            final = self._move_to_output()
        except OSError as e:
            self._fail("Could not save the recording", str(e))
            return
        log.info("saved %s", final)
        self._teardown_windows()
        self.on_saved(self, final)
        self._end(State.DONE)

    def _move_to_output(self) -> Path:
        out_dir = config.output_dir(self.cfg)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        suffix = self.result.suffix
        final = out_dir / f"jiffy-{stamp}{suffix}"
        n = 2
        while final.exists():
            final = out_dir / f"jiffy-{stamp}-{n}{suffix}"
            n += 1
        shutil.move(self.result, final)
        return final

    # -- plumbing

    def _spawn(self, cmd: list[str], stdin: bool = False, stdout: bool = False) -> Gio.Subprocess:
        flags = Gio.SubprocessFlags.STDIN_PIPE if stdin else Gio.SubprocessFlags.NONE
        flags |= Gio.SubprocessFlags.STDOUT_PIPE if stdout else Gio.SubprocessFlags.STDOUT_SILENCE
        launcher = Gio.SubprocessLauncher.new(flags)
        launcher.set_stderr_file_path(str(self.log_path))
        proc = launcher.spawnv(cmd)
        self.running.add(proc)
        return proc

    def _reap(self, proc: Gio.Subprocess, result) -> bool:
        """Finish an async wait; False when the session was cancelled meanwhile."""
        self.running.discard(proc)
        try:
            proc.wait_finish(result)
        except GLib.Error:
            return False
        return True

    def _log_tail(self) -> str:
        try:
            lines = [ln for ln in self.log_path.read_text(errors="replace").splitlines() if ln.strip()]
        except OSError:
            return ""
        return lines[-1][:300] if lines else ""

    def _after(self, ms: int, fn: Callable[[], None]) -> None:
        def once() -> bool:
            self.timers.discard(source)
            fn()
            return False
        source = GLib.timeout_add(ms, once)
        self.timers.add(source)

    def _every(self, ms: int, fn: Callable[[], bool]) -> None:
        def tick() -> bool:
            keep = fn()
            if not keep:
                self.timers.discard(source)
            return keep
        source = GLib.timeout_add(ms, tick)
        self.timers.add(source)

    def _fail(self, title: str, detail: str) -> None:
        if self.state in ENDED:
            return
        log.error("%s: %s", title, detail)
        self.on_failed(self, title, detail)
        self._end(State.FAILED)

    def _teardown_windows(self) -> None:
        for attr in ("badge", "border", "bar"):
            widget = getattr(self, attr)
            if widget is not None:
                widget.destroy()
                setattr(self, attr, None)

    def _end(self, state: State) -> None:
        if self.state in ENDED:
            return
        self.state = state
        for proc in list(self.running):
            proc.force_exit()
        self.running.clear()
        self.cancellable.cancel()
        for source in list(self.timers):
            GLib.source_remove(source)
        self.timers.clear()
        self._teardown_windows()
        shutil.rmtree(self.workdir, ignore_errors=True)
        self.on_ended(self)
