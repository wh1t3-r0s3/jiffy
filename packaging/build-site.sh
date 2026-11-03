#!/usr/bin/env bash
# Build the download site served by GitHub Pages: a signed flat apt repository holding the
# given .deb files, the installer and its public key, and a small landing page.
#
#   packaging/build-site.sh <out-dir> <deb>...
#
# The signing key comes from $APT_SIGNING_KEY (an ASCII-armored secret key). Needs apt-ftparchive and gpg.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=$1; shift
[ -n "${APT_SIGNING_KEY:-}" ] || { echo "APT_SIGNING_KEY is not set" >&2; exit 1; }

export GNUPGHOME
GNUPGHOME=$(mktemp -d)
trap 'rm -rf "$GNUPGHOME"' EXIT
printf '%s\n' "$APT_SIGNING_KEY" | gpg --batch --quiet --import
KEY_ID=$(gpg --batch --list-secret-keys --with-colons | awk -F: '/^sec/ {print $5; exit}')

rm -rf "$OUT"
mkdir -p "$OUT/apt"
cp "$@" "$OUT/apt/"
(
    cd "$OUT/apt"
    apt-ftparchive packages . > Packages
    gzip -9kn Packages
    apt-ftparchive \
        -o APT::FTPArchive::Release::Origin=Jiffy \
        -o APT::FTPArchive::Release::Label=Jiffy \
        -o APT::FTPArchive::Release::Suite=stable \
        -o APT::FTPArchive::Release::Codename=stable \
        -o APT::FTPArchive::Release::Architectures=all \
        -o APT::FTPArchive::Release::Description="Jiffy screen-to-GIF recorder" \
        release . > Release
    gpg --batch --yes --local-user "$KEY_ID" --clearsign -o InRelease Release
    gpg --batch --yes --local-user "$KEY_ID" --armor --detach-sign -o Release.gpg Release
)
gpg --batch --export "$KEY_ID" > "$OUT/jiffy.gpg"
cp install.sh "$OUT/install.sh"
VERSION=$(dpkg-deb -f "$1" Version)
sed "s/@VERSION@/$VERSION/g" packaging/index.html > "$OUT/index.html"
cp "data/io.github.wh1t3_r0s3.Jiffy.svg" "$OUT/icon.svg"
echo "site built in $OUT (Jiffy $VERSION, key $KEY_ID)"
