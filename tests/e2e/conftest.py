"""A throwaway desktop for end-to-end tests: Xvfb, a private D-Bus that can start Jiffy on demand,
and private config/cache/output folders. Nothing touches the real session."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jiffy import APP_ID

SRC = Path(__file__).resolve().parents[2] / "src"
REQUIRED = ("Xvfb", "dbus-daemon", "ffmpeg", "ffprobe", "xdotool", "xwininfo", "xeyes", "gapplication", "xclip")


def wait_for(predicate, timeout=10.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    raise TimeoutError(f"timed out waiting for {predicate}")


class Desktop:
    """Handles for driving the test desktop the way a user would."""

    def __init__(self, env: dict, root: Path):
        self.env = env
        self.root = root
        self.out = root / "out"
        self.config_file = root / "config" / "jiffy" / "config.json"

    def run(self, *args, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(args, env=self.env, capture_output=True, text=True, timeout=30, check=False, **kwargs)

    def action(self, name: str) -> None:
        result = self.run("gapplication", "action", APP_ID, name)
        assert result.returncode == 0, result.stderr

    def configure(self, **values) -> None:
        cfg = json.loads(self.config_file.read_text())
        cfg.update(values)
        self.config_file.write_text(json.dumps(cfg))

    def window_titles(self) -> str:
        return self.run("xwininfo", "-root", "-tree").stdout

    def wait_window(self, title: str, present: bool = True, timeout: float = 10.0) -> None:
        wait_for(lambda: (f'"{title}"' in self.window_titles()) == present, timeout)

    def xdotool(self, *args: str) -> None:
        self.run("xdotool", *args)

    def drag(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.xdotool("mousemove", str(x0), str(y0), "mousedown", "1")
        time.sleep(0.1)
        self.xdotool("mousemove", str((x0 + x1) // 2), str((y0 + y1) // 2))
        time.sleep(0.1)
        self.xdotool("mousemove", str(x1), str(y1))
        time.sleep(0.1)
        self.xdotool("mouseup", "1")

    def outputs(self) -> list[Path]:
        return sorted(self.out.glob("*"), key=lambda p: p.stat().st_mtime)

    def wait_output(self, count: int, timeout: float = 30.0) -> Path:
        wait_for(lambda: len(self.outputs()) >= count, timeout, 0.2)
        return self.outputs()[-1]

    def probe(self, path: Path) -> dict:
        info = self.run("ffprobe", "-v", "error", "-count_frames", "-show_entries",
                        "stream=codec_name,width,height,nb_read_frames", "-of", "json", str(path))
        return json.loads(info.stdout)["streams"][0]


@pytest.fixture(scope="session")
def desktop(tmp_path_factory):
    missing = [tool for tool in REQUIRED if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"missing tools: {', '.join(missing)}")
    root = tmp_path_factory.mktemp("desktop")
    for sub in ("config/jiffy", "data/dbus-1/services", "cache", "runtime", "out"):
        (root / sub).mkdir(parents=True)
    (root / "runtime").chmod(0o700)
    (root / "config/jiffy/config.json").write_text(json.dumps({"output_dir": str(root / "out")}))
    (root / f"data/dbus-1/services/{APP_ID}.service").write_text(
        f"[D-BUS Service]\nName={APP_ID}\nExec={sys.executable} -m jiffy --gapplication-service\n")

    xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "1600x1000x24", "-nolisten", "tcp"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    display = f":{xvfb.stdout.readline().strip()}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DBUS_", "XDG_", "WAYLAND"))}
    env.update(DISPLAY=display, XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
               XDG_CACHE_HOME=str(root / "cache"), XDG_RUNTIME_DIR=str(root / "runtime"),
               XDG_CURRENT_DESKTOP="X-Cinnamon", PYTHONPATH=str(SRC), JIFFY_DEBUG="1", GSETTINGS_BACKEND="memory")
    bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    env["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().strip()
    helpers = [subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
               for cmd in (["xclock", "-update", "1", "-geometry", "300x300+100+100"],
                           ["xeyes", "-geometry", "200x150+700+500"])
               if shutil.which(cmd[0])]
    d = Desktop(env, root)
    wait_for(lambda: '"xeyes"' in d.window_titles())
    yield d
    d.run("gapplication", "action", APP_ID, "quit")
    for proc in (*helpers, bus, xvfb):
        proc.terminate()
    for proc in (*helpers, bus, xvfb):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(autouse=True)
def fresh_settings(desktop):
    desktop.configure(format="gif", quality="balanced", start_delay=0, max_seconds=60)
