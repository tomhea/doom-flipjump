# The M7 ledger: one row per phase-1+ rung (docs/handoff-gameplay.md section 10)

Every rung declares its kill criteria HERE, before its first build, and fills its row after. The
row: ops attributed to the rung's own code (`profx`), the binding delta on the frozen combat set v2
(`scratchpad/gp/b0_scenarios.py`, (mean + p80)/2 against B0 17,760,774 / proxy 18,107,313), size,
ms/frame (`msframe.py`, ship-gate section 2), the pin report (`pinreport.py`). The standing
kill rules (handoff section 10): attributed ops > 1.25x the rung's budget -> redesign; the
cumulative projection > 22M minus the remaining budgets minus a 15% reserve -> stop for the owner.

## P1.1 pin protection (class S) -- declared 2026-09-27, before the build

**What**: flipjump `BlockPool(heat=)` (tomhea/flipjump#363) + `build_blocked.py --pin-heat` with
the heat list of blocked27's profile (`heatsites.py`, top 20 groups); the same program as blocked27.

**Budget**: ESTIMATE -1.27M ops/frame (heat-ordered indices, `profx/heatindex.py`); no new code.

**Kill criteria** (any one -> the binary does not ship):
1. `m2_std_gate` or `m3_gate` not byte-exact.
2. `pinreport.py`: a hot word of the list not pinned.
3. `msframe.py --against shipped`: B SLOWER (ship-gate section 2). NOT SEPARATED ships only with the
   stated reason "foundation for P3" (the handoff's clause), never SLOWER.
4. The build's heat report: a hot group unmatched, ambiguous or without a block (the pool raises).

**Row** (2026-09-27, `build/doom_e1m1_blocked28.fjm`, sha256 `9fe88c6187a82921`; logs in
`docs/ship-evidence/blocked28_*`):

| measure | blocked27 | P1.1 (blocked28) | delta |
|---|---|---|---|
| gamespeed binding (ops/frame) | 17,665,168 | 16,357,904 | -1,307,264 (-7.4%) |
| combat set v2 binding (b0_scenarios) | 17,760,774 | 16,448,992 | -1,311,782 (-7.4%) |
| ... with strafe's collision (proxy) | 18,107,313 | 16,794,857 | -1,312,456 |
| ms/frame (msframe, one quiet run) | 75.2 | 73.4 | NOT SEPARATED (all 5 pairs faster, x1.025) |
| fj ops/s | 242.4 M | 229.8 M | -5.2% |
| size (% of 2^27) | 32.23% | 32.21% | -24,510 words |
| hot words pinned (pinreport) | 20/20 | 20/20 (19 bases moved, by design) | 0 lost |

**Verdict against the kill criteria:** 1 m2_std_gate PASS, m3_gate PASS (221 frames byte-exact, 0
differ); 2 pinreport 20/20 pinned, exit 0; 3 msframe NOT SEPARATED, never slower -- ships as the
foundation for P3; 4 heat report: 20 hot groups matched, 0 missing, 0 ambiguous, 35,894/35,894
listed sites took their index. The ESTIMATE was -1.27M; measured -1.31M on both metrics.
Attributed ops (profx): n/a -- the rung adds no code.

## P1.2 player collision cells (class S) -- declared 2026-09-27, before the build

**What**: the player's `check_position` stops walking the 256-unit blockmap through packed tables
(`hex.read_table_packed`, ~6.8K ops per line tested, ~576K per check) and runs a CELL instead: a
jump tree on the 16.16 position finds the 32-unit cell, the cell's stub calls one stub per
candidate line, and each line stub XORs its constants into fixed argument cells and calls ONE
shared line test (`sim.line_test`: PIT_CheckLine with no conversions). A cell lists every line whose
bbox a box centred anywhere in the cell can touch -- exact interval arithmetic at 16.16, so the
verdict equals the oracle's all-lines sweep by construction. A door line reads `dstate` against its
pass state at test time; the one-bit `lnrow` wflip goes. Design: `docs/gp-collision-cells.md`.

**Budget**: -1.0 .. -1.4M ops/frame on the binding metric (handoff section 10). ESTIMATE from
phase 0: one try ~613K today (MEASURED: seed walk 35.4K + check_position 576K); on cells ~40-45K,
dominated by the unchanged seed walk.

**Kill criteria** (any one -> the binary does not ship):
1. `tests/host/test_collision_cells.py`: a cell missing a line some box in it can touch (the
   corner check, with its mutated-entry control), or the cell model disagreeing with
   `ReferenceModel.check_position` on the sample (refusals and door states included).
2. `tests/fj/test_collision_fj.py`: the emitted cell routine disagreeing with the oracle.
3. `m2_std_gate` or `m3_gate` not byte-exact.
4. `msframe.py --against shipped`: B SLOWER. NOT SEPARATED ships only as "foundation for P3".
5. The reclaim: gamespeed binding down by less than 0.8M ops/frame (the budget's low end / 1.25)
   -> redesign before shipping.
6. Size over 35% of 2^27, or `pinreport.py`: a hot word of the heat list not pinned.

**Row** (2026-09-27, `build/doom_e1m1_blocked29.fjm`, sha256 `a90f172ee718be63`; logs in
`docs/ship-evidence/blocked29_*`):

| measure | shipped (P1.1, blocked28) | P1.2 (blocked29) | delta |
|---|---|---|---|
| gamespeed binding (ops/frame) | 16,357,904 | 14,780,831 | -1,577,073 (-9.6%) |
| combat set v2 binding (b0_scenarios) | 16,448,992 | 15,485,242 | -963,750 (-5.9%) |
| ... with strafe's collision (proxy) | 16,794,857 | 15,519,673 | -1,275,184 (-7.6%) |
| collision ops/frame (profx, gamespeed games) | 1,475,186 (blocked27's profile; the same program) | 122,218 | -1,352,968 (-91.7%) |
| ms/frame (msframe, one quiet run) | 74.0 | 64.4 | B FASTER (all 5 pairs, median x1.155) |
| fj ops/s | 227.8 M | 235.4 M | +3.3% |
| size (% of 2^27) | 32.21% | 27.35% | -6,522,370 words |
| hot words pinned (pinreport) | 20/20 | 20/20 (4 re-keyed by their heat key; 19 bases moved) | 0 lost |

**Verdict against the kill criteria:** 1 `test_collision_cells.py` passes, with its mutated-entry
control and the oracle sample (`p12_r1_pass.log`); 2 `tests/fj/test_collision_fj.py` passes (the same
log); 3 m2_std_gate PASS, m3_gate PASS (`blocked29_gates.log`); 4 msframe B FASTER, x1.155 in all 5
pairs; 5 the reclaim is -1.58M on the binding, past the budget's high end (-1.4M); 6 size 27.35%, and
pinreport 20/20 pinned, 0 lost. The ESTIMATE was -1.0 .. -1.4M; measured -1.58M on gamespeed, -0.96M
on set v2 (-1.28M counting strafe's collision, which B0 leaves out). Attributed ops (profx phases,
the same ten games): collision 122,218 ops/frame -- one player try 50,818, of which the unchanged
seed walk is 31,838; 2.40 tries a frame.
