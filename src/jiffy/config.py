"""User settings: one JSON file, checked on load so a hand-edited or older file can never break the app."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from jiffy import APP_NAME, PRGNAME
from jiffy.quality import LEVELS

FORMATS = ("gif", "mp4")
AFTER_SAVE = ("nothing", "open", "folder")
DEFAULT_SHORTCUT = "<Shift>Print"

# Inclusive bounds for the numeric settings; out-of-range values are clamped on load.
LIMITS = {
    "start_delay": (0, 30),
    "max_seconds": (0, 3600),
}
CHOICES = {"format": FORMATS, "quality": LEVELS, "after_save": AFTER_SAVE}


@dataclass
class Config:
    """Every user-facing setting, with its default."""

    shortcut: str = DEFAULT_SHORTCUT
    format: str = "gif"
    quality: str = "balanced"
    start_delay: int = 0
    max_seconds: int = 60
    show_cursor: bool = True
    show_border: bool = True
    copy_to_clipboard: bool = True
    after_save: str = "nothing"
    output_dir: str = ""
    first_run_done: bool = False


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / PRGNAME


def config_path() -> Path:
    return config_dir() / "config.json"


def _coerce(name: str, kind: type, value, default):
    if kind is bool:
        return value if isinstance(value, bool) else default
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        low, high = LIMITS.get(name, (None, None))
        value = int(value)
        if low is not None:
            value = min(max(value, low), high)
        return value
    if not isinstance(value, str):
        return default
    if name in CHOICES and value not in CHOICES[name]:
        return default
    return value


def from_dict(raw: dict) -> Config:
    defaults = Config()
    values = {}
    for f in fields(Config):
        default = getattr(defaults, f.name)
        values[f.name] = _coerce(f.name, type(default), raw.get(f.name, default), default)
    return Config(**values)


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return Config()
    return from_dict(raw) if isinstance(raw, dict) else Config()


def save(cfg: Config, path: Path | None = None) -> None:
    """Write atomically, so a crash mid-save leaves the previous file intact."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    tmp.replace(path)


def default_output_dir() -> Path:
    from gi.repository import GLib

    pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    return Path(pictures or Path.home() / "Pictures") / APP_NAME


def output_dir(cfg: Config) -> Path:
    return Path(os.path.expanduser(cfg.output_dir)) if cfg.output_dir else default_output_dir()
