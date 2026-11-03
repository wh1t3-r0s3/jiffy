"""Start-at-login switch: a per-user autostart entry that either launches Jiffy or hides the system one."""

from __future__ import annotations

import os
from pathlib import Path

from jiffy import APP_ID, APP_NAME, PRGNAME

ENTRY = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Keeps {APP_NAME} ready so the shortcut responds instantly
Exec={PRGNAME} --background
Icon={APP_ID}
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


def user_entry() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / f"{APP_ID}.desktop"


def is_enabled() -> bool:
    try:
        text = user_entry().read_text()
    except OSError:
        return True
    return "Hidden=true" not in text and "X-GNOME-Autostart-enabled=false" not in text


def set_enabled(enabled: bool) -> None:
    path = user_entry()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ENTRY if enabled else ENTRY + "Hidden=true\n")
