#!/usr/bin/env bash
# Build the Debian package from this checkout into dist/jiffy_<version>_all.deb. Needs only dpkg-deb.
set -euo pipefail
cd "$(dirname "$0")/.."
read -r VERSION APP_ID < <(PYTHONPATH=src python3 -c 'import jiffy; print(jiffy.__version__, jiffy.APP_ID)')
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/jiffy"

install -d "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/lib/python3/dist-packages" \
    "$PKG/usr/share/applications" "$PKG/usr/share/dbus-1/services" "$PKG/etc/xdg/autostart" \
    "$PKG/usr/share/icons/hicolor/scalable/apps" "$PKG/usr/share/doc/jiffy"

cp -r src/jiffy "$PKG/usr/lib/python3/dist-packages/"
find "$PKG/usr/lib/python3/dist-packages/jiffy" -name '__pycache__' -prune -exec rm -rf {} +
cat > "$PKG/usr/bin/jiffy" <<'PY'
#!/usr/bin/python3
import sys

from jiffy.__main__ import main

sys.exit(main())
PY
chmod 755 "$PKG/usr/bin/jiffy"
install -m 644 "data/$APP_ID.desktop" "data/$APP_ID.Settings.desktop" "$PKG/usr/share/applications/"
install -m 644 "data/$APP_ID.service" "$PKG/usr/share/dbus-1/services/"
install -m 644 "data/$APP_ID.autostart.desktop" "$PKG/etc/xdg/autostart/$APP_ID.desktop"
install -m 644 "data/$APP_ID.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/"
install -m 644 LICENSE "$PKG/usr/share/doc/jiffy/copyright"

echo "/etc/xdg/autostart/$APP_ID.desktop" > "$PKG/DEBIAN/conffiles"
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: jiffy
Version: $VERSION
Architecture: all
Maintainer: wh1t3-r0s3 <2450661+wh1t3-r0s3@users.noreply.github.com>
Installed-Size: $(du -sk "$PKG" | cut -f1)
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, python3-xlib, ffmpeg, libglib2.0-bin
Section: graphics
Priority: optional
Homepage: https://github.com/wh1t3-r0s3/jiffy
Description: press a shortcut, drag a region, get a GIF
 Jiffy records a region of an X11 screen to a GIF or MP4 from a keyboard
 shortcut: drag a rectangle or click a window, watch the timer, press the
 shortcut again to stop. The file is saved and copied to the clipboard.
CONTROL

mkdir -p dist
dpkg-deb --root-owner-group --build "$PKG" "dist/jiffy_${VERSION}_all.deb" >/dev/null
echo "dist/jiffy_${VERSION}_all.deb"
