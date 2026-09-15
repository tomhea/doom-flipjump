#!/usr/bin/env bash
# A/B huge pages on the real binary, ALTERNATING, with repeats.
#
# Necessary because single samples have been worthless all session: the same binary and the same
# work measured 53-125 M fj/s on Windows while the L1 clock yardstick stayed flat. Alternate so
# any drift hits both arms equally, and report every sample rather than a chosen one.
set -uo pipefail
DST=$HOME/fj/flipjump-151
FJM=${1:-/mnt/c/Users/tomhe/Documents/doom-flipjump/build/doom_e1m1_blocked25.fjm}
FRAMES=${2:-10}
REPS=${3:-3}

cd "$DST"
cp /mnt/c/Users/tomhe/Documents/doom-flipjump/scratchpad/12m/wsl_speed.py .

for i in $(seq 1 "$REPS"); do
  echo "--- rep $i ---"
  PYTHONPATH="$DST" python3 wsl_speed.py "$FJM" "$FRAMES" 2>&1 \
    | grep -E 'AnonHugePages|fj/s|ms/frame' | sed 's/^/  THP     /'
  FLIPJUMP_NO_LARGE_PAGES=1 PYTHONPATH="$DST" python3 wsl_speed.py "$FJM" "$FRAMES" 2>&1 \
    | grep -E 'AnonHugePages|fj/s|ms/frame' | sed 's/^/  no-THP  /'
done
