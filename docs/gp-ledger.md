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

**Row**: (filled after the build)

| measure | blocked27 | P1.1 | delta |
|---|---|---|---|
| gamespeed binding (ops/frame) | 17,665,168 | | |
| combat set v2 binding (b0_scenarios) | 17,760,774 | | |
| ms/frame (msframe, quiet box) | 74.7 | | |
| size (% of 2^27) | 32.23% | | |
| hot words pinned (pinreport) | 20/20 | | |
