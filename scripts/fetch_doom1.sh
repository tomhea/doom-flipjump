#!/usr/bin/env bash
# Fetch the DOOM shareware IWAD (doom1.wad) for LOCAL DEV ONLY (gitignored target; D8).
# CI, golden frames, and versions/ artifacts use Freedoom (redistributable) — NEVER this WAD.
set -euo pipefail
DEST="${1:-assets/doom1.wad}"
URL="${DOOM1_WAD_URL:-https://distro.ibiblio.org/slitaz/sources/packages/d/doom1.wad}"
mkdir -p "$(dirname "$DEST")"
echo "Fetching doom1.wad -> $DEST"
curl -fSL "$URL" -o "$DEST"
if command -v sha1sum >/dev/null 2>&1; then sha1sum "$DEST"; else shasum "$DEST"; fi
echo "Done. (shareware; dev-only; gitignored)"
