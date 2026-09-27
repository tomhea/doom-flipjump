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
