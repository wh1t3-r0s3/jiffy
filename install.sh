#!/usr/bin/env bash
# Jiffy installer for Debian, Ubuntu and Linux Mint.
#
# Adds the Jiffy package source, so updates arrive with your normal system updates,
# installs Jiffy, and sets up its keyboard shortcut.
#
#   Install:    curl -fsSL https://wh1t3-r0s3.github.io/jiffy/install.sh | bash
#   Uninstall:  curl -fsSL https://wh1t3-r0s3.github.io/jiffy/install.sh | bash -s -- --uninstall
set -euo pipefail

BASE="${JIFFY_BASE:-https://wh1t3-r0s3.github.io/jiffy}"
KEYRING=/etc/apt/keyrings/jiffy.gpg
SOURCE=/etc/apt/sources.list.d/jiffy.list

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'jiffy installer: %s\n' "$*" >&2; exit 1; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null || die "run this as root or install sudo"
    SUDO="sudo"
fi

# Everything runs from main, called on the last line, so bash has read the whole script before any
# command runs: under `curl | bash`, apt would otherwise read the rest of the script from stdin.
main() {
if [ "${1:-}" = "--uninstall" ]; then
    if command -v jiffy >/dev/null; then jiffy quit >/dev/null 2>&1 || true; fi
    $SUDO apt-get remove -y jiffy </dev/null || true
    $SUDO rm -f "$SOURCE" "$KEYRING"
    say "Jiffy is removed. Your recordings and settings (~/.config/jiffy) were left alone."
    exit 0
fi

command -v apt-get >/dev/null || die "this installer is for Debian, Ubuntu and Linux Mint (it needs apt)"
command -v curl >/dev/null || die "curl is required"
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    say "Note: Jiffy records X11 desktops. In a Wayland session it cannot capture the screen."
fi

say "Adding the Jiffy package source"
$SUDO install -d -m 0755 /etc/apt/keyrings
curl -fsSL "$BASE/jiffy.gpg" | $SUDO tee "$KEYRING" >/dev/null
echo "deb [signed-by=$KEYRING] $BASE/apt ./" | $SUDO tee "$SOURCE" >/dev/null

say "Installing Jiffy"
$SUDO apt-get update </dev/null
$SUDO apt-get install -y jiffy </dev/null

if [ "$(id -u)" -ne 0 ] && [ -n "${DISPLAY:-}" ]; then
    jiffy setup </dev/null
else
    say "Jiffy is installed. From your desktop session, run: jiffy setup"
fi
}

main "$@"
