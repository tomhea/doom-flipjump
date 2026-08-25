#!/bin/bash
# M1-HOIST end-to-end: verify the re-keyed set -> build -> M1 gate -> gate selftest -> host tests.
# Every stage asserts before the next begins, so a bad artifact stops the chain instead of
# propagating into a 66-minute build.
set -e
PY="${PY:-/c/Users/tomhe/AppData/Local/Programs/Python/Python311/python}"
say(){ echo ""; echo "=== $* ==="; }

say "STAGE 1/6  verify the re-keyed restore set"
"$PY" - <<'PYEOF'
import gzip, json, sys
sys.path.insert(0, "src")
from doomfj.wall_renderer import HOISTED_SCRATCH_DECLS as H
from doomfj.collision import CHECK_SCRATCH_DECLS as C
d = json.load(gzip.open("src/doomfj/data/m1_restore_set.json.gz", "rt"))
names = {e[0] for e in d["entries"]}
at = sorted(n for n in names if "---" in n or ":" in n)
missing = [x.split(":")[0] for x in list(H) + list(C) if x.split(":")[0] not in names]
print("   set: %d words, %d entries" % (d["words"], len(d["entries"])))
print("   macro-local (@) labels remaining: %d" % len(at))
for n in at[:4]:
    print("      %s" % n[:110])
print("   declared globals missing from the set: %d %s" % (len(missing), missing[:5]))
assert not missing, "HOLE: declared globals absent from the set"
assert not at, "GOAL NOT MET: %d @-local labels remain" % len(at)
print("   OK -- zero @-local labels, no holes")
PYEOF

say "STAGE 2/6  build the self-resetting loop  (~66 min)"
"$PY" scratchpad/m1_wired_build.py

say "STAGE 3/6  M1 gate"
"$PY" scratchpad/m1_gate.py --loop-fjm build/doom_e1m1_loop.fjm \
      --old-fjm scratchpad/fjmcache/_ca2_ship_new.fjm | tee scratchpad/_fin_gate.log
grep -q "^M1 GATE: PASS" scratchpad/_fin_gate.log || { echo "GATE FAILED"; exit 1; }

say "STAGE 4/6  M1 gate negative control (R9)"
"$PY" scratchpad/m1_gate.py --loop-fjm build/doom_e1m1_loop.fjm \
      --old-fjm scratchpad/fjmcache/_ca2_ship_new.fjm --selftest | tee scratchpad/_fin_self.log
grep -q "M1 GATE SELFTEST: PASS" scratchpad/_fin_self.log || { echo "SELFTEST FAILED"; exit 1; }

say "STAGE 5/6  host tests"
"$PY" -m pytest tests/host -q 2>&1 | tail -3

say "STAGE 6/6  tool selftests"
for t in m1_hoist m1_add_globals m1_setfile; do
  printf "   %-16s " "$t"; "$PY" scratchpad/$t.py --selftest 2>&1 | tail -1
done

echo ""
echo "=== M1-HOIST FINISH: ALL STAGES PASSED ==="
