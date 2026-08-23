# constant-address round 2 — evidence logs

Every log `docs/handoff-constaddr.md` §13 quotes, tracked so the numbers are checkable from the
tree alone — the rule `docs/m1-evidence/README.md` states, which the FIRST constant-address
round did not follow (CR-2026-08 R2 found 0 of ~20 `_ca_*` logs tracked).

| file | produced by | what it certifies |
|---|---|---|
| `gate_base.log` | `scratchpad/deg_gate.py in a pristine f7a8ac7 worktree` | the BASELINE: 4 viewpoints byte-exact, the op counts round 2 is measured against |
| `gate_new.log` | `scratchpad/deg_gate.py on this tree` | 4 viewpoints byte-exact with vtxdisp + sinadisp + finesine per_entry in |
| `sweep.log` | `scratchpad/ca2_sweep.py --a <base> --b <new>` | THE GOVERNING NUMBER: 260-frame median, both binaries, and 260/260 frames byte-exact |
| `price.log` | `scratchpad/ca2_price.py` | ops/call for both arms of angle_to_x and of finesine.read_sin, every arm vacuity-checked |
| `callcount.log` | `scratchpad/ca2_callcount.py --sweep 8` | calls/frame per kernel at the gate + sweep viewpoints, with a transparency control |
| `bbox_rate.log` | `scratchpad/ca_bbox_rate.py --selftest` | C5's bbox reject rate on the sweep and contact point sets, with 3 negative controls |

⚠ `gate_base.log` and `gate_new.log` are the two sides of the same comparison, built in the
same session on the same machine. This machine's wall clock drifts ~70%, so only the OP COUNTS
in them are comparable — never the timings.

⚠ `sweep.log` is the **deg tier** (`scratchpad/deg_gate.py`'s config: no sim, no M1 loop). Its
absolute median is not comparable to the shipped-tier 29,737,005 in §12; the DELTA is.

