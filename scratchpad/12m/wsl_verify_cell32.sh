#!/usr/bin/env bash
# Rebuild the engine on Linux from the CURRENT source (stages A-C of the 4-byte-cell change
# were never built there) and prove the 4-byte path is live and correct under Linux too:
# same op count as Windows for the same 8 game frames (199,640,392), cell_bytes == 4.
set -uo pipefail
bash /mnt/c/Users/tomhe/Documents/doom-flipjump/scratchpad/12m/wsl_build.sh 2>&1 | tail -4
echo "=== 4-byte cells on Linux: expect ops 199,640,392 for 8 game frames, cell_bytes 4 ==="
cd ~/fj/flipjump-151
cp /mnt/c/Users/tomhe/Documents/doom-flipjump/scratchpad/12m/wsl_speed.py .
PYTHONPATH=. python3 -c 'from flipjump.interpreter import _fjcore; m=_fjcore.Memory(32); print("cell_bytes attribute present:", hasattr(m, "cell_bytes"))'
PYTHONPATH=. python3 wsl_speed.py /mnt/c/Users/tomhe/Documents/doom-flipjump/build/doom_e1m1_blocked25.fjm 8 2>&1 \
  | grep -E 'ops |storage_mode|large_pages|AnonHuge|fj/s|ms/frame'
echo "--- forced 8-byte control (must give the SAME ops) ---"
FLIPJUMP_CELL64=1 PYTHONPATH=. python3 wsl_speed.py /mnt/c/Users/tomhe/Documents/doom-flipjump/build/doom_e1m1_blocked25.fjm 8 2>&1 \
  | grep -E 'ops |fj/s'
