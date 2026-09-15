#!/usr/bin/env bash
# Run the DOOM binary under WSL with the engine built there, and report whether the kernel
# actually granted huge pages. See wsl_speed.py for why this is the privilege-free route.
set -uo pipefail
DST=$HOME/fj/flipjump-151
FJM=${1:-/mnt/c/Users/tomhe/Documents/doom-flipjump/build/doom_e1m1_blocked25.fjm}
FRAMES=${2:-14}

cd "$DST"
cp /mnt/c/Users/tomhe/Documents/doom-flipjump/scratchpad/12m/wsl_speed.py .

echo "=== THP=madvise (default): the engine asks via MADV_HUGEPAGE ==="
PYTHONPATH="$DST" python3 wsl_speed.py "$FJM" "$FRAMES"
echo
echo "=== control: FLIPJUMP_NO_LARGE_PAGES=1 forces the plain-malloc fallback ==="
FLIPJUMP_NO_LARGE_PAGES=1 PYTHONPATH="$DST" python3 wsl_speed.py "$FJM" "$FRAMES"
