#!/usr/bin/env bash
# Fetch Freedoom (BSD-licensed, redistributable) for LOCAL DEV. The full WADs are gitignored; only the
# small trimmed fixture (tests/fixtures/freedoom_assets.wad, built by make_assets_wad.py) is committed.
# Freedoom is the redistributable asset source for CI / golden frames / versions artifacts (D8).
set -euo pipefail
VER="${FREEDOOM_VERSION:-0.13.0}"
DEST_DIR="${1:-assets}"
ZIP="freedoom-${VER}.zip"
URL="https://github.com/freedoom/freedoom/releases/download/v${VER}/${ZIP}"
mkdir -p "$DEST_DIR"
echo "Fetching Freedoom ${VER} -> ${DEST_DIR}/"
curl -fSL "$URL" -o "${DEST_DIR}/${ZIP}"
cd "$DEST_DIR"
unzip -o "$ZIP" >/dev/null
# flatten: move the wads up next to this script's dest
find . -name 'freedoom1.wad' -exec cp {} freedoom1.wad \;
find . -name 'freedoom2.wad' -exec cp {} freedoom2.wad \; 2>/dev/null || true
echo "Done: $(ls -1 freedoom*.wad 2>/dev/null | tr '\n' ' ')"
echo "(BSD-licensed; dev copy gitignored — commit only the trimmed fixture)"
