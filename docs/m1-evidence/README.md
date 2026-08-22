# M1 evidence logs

Every log the PR body and `docs/handoff-m1-reset.md` quote, tracked so the evidence is verifiable
from the tree alone.

⚠ CR round 12: the body was tracked in round 8 (`docs/pr77-body.md`) and **the logs behind it were
left untracked**, so a reviewer exporting the repo could check the R1 mutation blocks (regenerable
by running the tool) but not a single R2 artifact. 23 KB of text was all that stood between "quoted"
and "checkable".

| file | produced by | what it certifies |
|---|---|---|
| `m1_gate8.log` | `scratchpad/m1_gate.py` | M1 GATE PASS — 4 viewpoints in one run + an 8-frame pristine chain, byte-exact |
| `m1_gate8_self.log` | `m1_gate.py --selftest` | the gate rejects a WRONG LOOP FRAME (frame 0 DIFFER, 1–3 exact), clean 0 / mutated 1 |
| `m1_sweep6.log` | `scratchpad/m1_sweep.py` | 260/260 byte-exact; reset 250,789 ops = 0.8% of the 30,191,585 median |
| `m1_play3.log` | `scratchpad/m1_play.py` | 100 frames from one run, 100/100 byte-exact |
| `m1_bytecheck.log` | `scratchpad/m1_bytecheck.py` | no nibble-cleared cell ever holds a value > 15, over 4 viewpoints |
| `m1_bytecheck_self.log` | `m1_bytecheck.py --selftest` | that probe rejects a planted 0xA5 (clean 0 / planted 1) |
| `m1_fpcheck.log` | `scratchpad/m1_fpcheck.py` | the build-path fingerprint assert fires against the build's OWN pass-1 table |
| `m1_wired3.log` | `scratchpad/m1_wired_build.py` | the shipped build: 4,349+1,002 cells, values_changed 0 over 10,702 |
| `m1_mutations.log` | `scratchpad/m1_mutations.py` | 15 mutations of shipped `src/`, each caught individually |
| `m1_mutations_all.log` | `m1_mutations.py --all-at-once` | the R1 FAIL block, and what it could not apply |
| `m1_pytest_full.log` | pytest | the suite |
| `m1_inventory.txt` | `scratchpad/m1_inventory.py` | the generated §9.7 table |

**These are snapshots.** They are only true of the commit that added them. `m1_inventory.py --check`
is the only one that re-verifies itself against the tree; the rest must be re-run. If you change the
code, re-run and re-copy, or delete the stale one — a tracked stale log is worse than an untracked
fresh one.
