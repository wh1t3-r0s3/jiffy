"""Every test process gets its own virtual X display, so GTK never reaches the desktop of whoever runs the tests."""

import os
import shutil
import subprocess

import pytest

_xvfb: subprocess.Popen | None = None


def pytest_configure(config):
    """Runs before any test module imports GTK, which opens $DISPLAY on import."""
    global _xvfb
    if shutil.which("Xvfb") is None:
        raise pytest.UsageError("the tests need Xvfb: sudo apt install xvfb")
    _xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    os.environ["DISPLAY"] = f":{_xvfb.stdout.readline().strip()}"
    os.environ.pop("WAYLAND_DISPLAY", None)


def pytest_unconfigure(config):
    if _xvfb is not None:
        _xvfb.terminate()
        _xvfb.wait(timeout=5)
