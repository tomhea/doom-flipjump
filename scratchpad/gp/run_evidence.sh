#!/usr/bin/env bash
# S2 evidence runs, strictly one after another (each takes and releases the binary lock itself).
cd /c/Users/tomhe/Documents/doom-flipjump || exit 1
set -o pipefail
echo "== probe selftest + demo  $(date +%T)"
timeout 3600 python -u scratchpad/gp/probe.py --selftest --demo > scratchpad/gp/probe_selftest_demo.log 2>&1
echo "   rc=$?  $(date +%T)"
echo "== b0 selftest  $(date +%T)"
timeout 3600 python -u scratchpad/gp/b0.py --selftest > scratchpad/gp/b0_selftest.log 2>&1
echo "   rc=$?  $(date +%T)"
echo "== b0 on 20 viewpoints of gamespeed run 0  $(date +%T)"
timeout 3600 python -u scratchpad/gp/b0.py --from-gamespeed 0 --every 5 --count 20 \
    --json scratchpad/gp/b0_gamespeed0_x20.json > scratchpad/gp/b0_gamespeed0_x20.log 2>&1
echo "   rc=$?  $(date +%T)"
echo "== b0 view mode on all 100 frames of gamespeed runs 0 and 1  $(date +%T)"
timeout 3600 python -u scratchpad/gp/b0.py --from-gamespeed 0 1 --no-pixels \
    --json scratchpad/gp/b0_gamespeed01_view.json > scratchpad/gp/b0_gamespeed01_view.log 2>&1
echo "   rc=$?  $(date +%T)"
echo "== done  $(date +%T)"
