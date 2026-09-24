#!/usr/bin/env bash
# Fetch Freedoom (BSD-licensed, redistributable) for LOCAL DEV and for CI. The full WADs are
# gitignored; only the small trimmed fixture (tests/fixtures/freedoom_assets.wad, built by
# make_assets_wad.py) is committed.
# Freedoom is the redistributable asset source for CI / golden frames / versions artifacts (D8).
#
# The test suite's expected frames come from 0.13.0's bytes, so for that version the zip and the
# WAD the tests read are both CHECKED, and a mismatch stops here instead of failing tests for the
# wrong reason. The zip's hash is the one Freedoom signs in freedoom-0.13.0-CHECKSUM on the release;
# the WAD's is the member of that zip. Another FREEDOOM_VERSION still fetches, unchecked, with a
# warning -- nothing in the suite is written against it.
set -euo pipefail
VER="${FREEDOOM_VERSION:-0.13.0}"
DEST_DIR="${1:-assets}"
ZIP="freedoom-${VER}.zip"
URL="https://github.com/freedoom/freedoom/releases/download/v${VER}/${ZIP}"

PINNED_VER="0.13.0"
ZIP_SHA256="3f9b264f3e3ce503b4fb7f6bdcb1f419d93c7b546f4df3e874dd878db9688f59"
WAD1_SHA256="7323bcc168c5a45ff10749b339960e98314740a734c30d4b9f3337001f9e703d"

sha256() {   # coreutils on Linux and Git Bash; shasum on macOS
    if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

check() {    # check <file> <expected sha256>
    local got
    got="$(sha256 "$1")"
    if [ "$got" != "$2" ]; then
        echo "REFUSED: $1 has sha256 $got, expected $2 (Freedoom ${PINNED_VER})" >&2
        exit 1
    fi
    echo "  sha256 ok: $1"
}

mkdir -p "$DEST_DIR"
echo "Fetching Freedoom ${VER} -> ${DEST_DIR}/"
curl -fSL "$URL" -o "${DEST_DIR}/${ZIP}"
cd "$DEST_DIR"
if [ "$VER" = "$PINNED_VER" ]; then
    check "$ZIP" "$ZIP_SHA256"
else
    echo "WARNING: no pinned hashes for Freedoom ${VER}; the test suite is written against ${PINNED_VER}" >&2
fi
unzip -o "$ZIP" >/dev/null
# flatten: move the wads up next to this script's dest
find . -name 'freedoom1.wad' -exec cp {} freedoom1.wad \;
find . -name 'freedoom2.wad' -exec cp {} freedoom2.wad \; 2>/dev/null || true
if [ "$VER" = "$PINNED_VER" ]; then
    check freedoom1.wad "$WAD1_SHA256"
fi
echo "Done: $(ls -1 freedoom*.wad 2>/dev/null | tr '\n' ' ')"
echo "(BSD-licensed; dev copy gitignored — commit only the trimmed fixture)"
