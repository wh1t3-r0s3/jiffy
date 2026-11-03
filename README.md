# Jiffy

Press a shortcut, drag a region, get a GIF. For Linux desktops on X11: Linux Mint, Ubuntu, Debian.

- **Shortcut to start, same shortcut to stop.** A small bar beside the region shows the timer, with Stop and Cancel.
- **Pick what to record** by dragging a rectangle, clicking a window, or pressing Space for the whole screen. Esc cancels.
- **The cursor is recorded.** A red outline marks the region while recording, outside the frame so it never shows up in the GIF.
- **Ready to paste.** The finished file is saved, copied to the clipboard (Ctrl+V pastes it into chat apps, browsers and file managers) and announced with Open and Show-in-folder buttons.
- **No uploading.** Nothing leaves your machine.

## Install

```sh
curl -fsSL https://wh1t3-r0s3.github.io/jiffy/install.sh | bash
```

This adds Jiffy's signed package source, installs Jiffy, and sets up its keyboard shortcut. It tells you which key it picked:
**Shift+Print** when that is free, otherwise the next free one of Shift+Super+Print, Shift+Super+G or Ctrl+Alt+Shift+G.
After that, updates arrive with your normal system updates. A running Jiffy restarts itself into the new version as soon as it is not recording.

To remove it:

```sh
curl -fsSL https://wh1t3-r0s3.github.io/jiffy/install.sh | bash -s -- --uninstall
```

Packages are signed with key `A86E FA75 9935 61CD 08B8 15E3 DAC1 EFFF A520 B383`.

## Use

| | |
|---|---|
| Start recording | the shortcut, or *Jiffy* in the menu, or `jiffy` |
| Stop | the shortcut again, or the Stop button |
| Cancel | Esc while selecting, or the Cancel button while recording |
| Settings | *Jiffy Settings* in the menu, or `jiffy settings` |

Recordings go to `~/Pictures/Jiffy` unless you choose another folder.

### Settings

| Setting | Default | |
|---|---|---|
| Shortcut | Shift+Print | Click it, then press the new keys. |
| Countdown | Off | 3 or 5 seconds before recording starts. |
| Max length | 1 minute | Stops on its own after this. |
| Show the cursor | On | |
| Red outline while recording | On | |
| Save as | GIF | or MP4 video, much smaller for long clips |
| Quality | Balanced | **Small file**, **Balanced** or **Sharp**: one choice that sets frame rate, size cap and colours together. The window shows what each means. |
| Save to | ~/Pictures/Jiffy | |
| Copy to clipboard | On | |
| When it's saved | Just notify me | or open the file, or show it in its folder |
| Start at login | On | Keeps Jiffy ready so the shortcut responds instantly. |

Settings live in `~/.config/jiffy/config.json`.

### Desktops

The shortcut is set up automatically on Cinnamon, GNOME, Budgie, Unity, MATE and Xfce. On other desktops, bind a key to
`gapplication action io.github.wh1t3_r0s3.Jiffy record` (or `jiffy record`) in your keyboard settings.
Wayland sessions are not supported: Jiffy captures the screen through X11.

## Develop

Jiffy is Python 3.10+ with GTK 3 through PyGObject, and runs ffmpeg to capture and encode. On Mint, Ubuntu or Debian:

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-xlib ffmpeg libglib2.0-bin \
                 python3-pytest xvfb x11-apps x11-utils xdotool xclip
jiffy quit                                # stop an installed copy first, if you have one
PYTHONPATH=src python3 -m jiffy --foreground
PYTHONPATH=src python3 -m jiffy record    # from another terminal, or bind a key to it
```

Tests:

```sh
python3 -m pytest -q                       # unit tests
python3 -m pytest -q -m e2e tests/e2e      # drives the real app on a virtual X display
```

Every test run gets its own virtual X display (and the end-to-end tests a private session bus too), so tests never touch your desktop.

### How it fits together

One resident app per desktop session (`app.py`) owns the shortcut's actions, the clipboard and notifications. The
shortcut runs `gapplication action … record`, which reaches the running app over D-Bus instantly or starts it on demand.

| Module | Does |
|---|---|
| `app.py` | the resident app: actions, notifications, first-run setup, restart after an upgrade |
| `session.py` | one recording from selection to saved file: countdown, capture, stop, encode |
| `selector.py` | the full-screen region and window picker |
| `overlays.py` | the outline, the countdown badge and the Stop/Cancel bar |
| `ffmpeg.py` | every ffmpeg command line, kept pure so it is unit-tested |
| `quality.py` | what Small file, Balanced and Sharp mean for each format |
| `shortcuts.py` | binding the shortcut on each desktop, and spotting keys that are already taken |
| `config.py`, `settings_window.py` | settings on disk and the window that edits them |
| `clipboard.py`, `windows.py`, `screen.py`, `geometry.py`, `autostart.py` | the small pieces those use |

### Release

1. Bump `__version__` in `src/jiffy/__init__.py` and commit.
2. Tag and push: `git tag v1.2.0 && git push origin main v1.2.0`.

The release workflow tests that commit, publishes the `.deb` as a GitHub release, and updates the apt repository on
GitHub Pages. Everyone who installed Jiffy gets the update with their next system update.

## License

MIT
