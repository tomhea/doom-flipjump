# HANDOFF: the 26M campaign — getting the median frame back under control

Owner directive (2026-08-14): **median 26M fj ops/frame, and get there BEFORE the CR.**

M14 shipped input, simulation, collision and moving things — and roughly tripled the median frame.
This document is the reduction back. Written for a session with no prior context: everything you
need is here or pointed at from here. Read §0, §1 and §2 before touching anything.

⚠ **§2 says this plan does not currently reach 26M, and §10 lists where it is thin.** Those two
sections are the result of auditing the plan against itself; read them before believing the rest.

---

## 0. The two numbers you must not confuse

This campaign exists partly because I quoted one of these against the other and produced a
misleading answer.

| | what it measures | pre-M14 value |
|---|---|---|
| **the SWEEP MEDIAN** | 260 frames, walkable grid, 65 points × 4 angles | **22.94M** (worst 48.46M) |
| **the four `deg_gate` viewpoints** | hard frames chosen to stress the degradation knobs | **33.5 / 35.5 / 42.8 / 45.2M** |

The gate viewpoints sit near the **top** of the distribution — roughly 1.5–2× the median. Every M14
number in the repo before this campaign was a gate viewpoint. **The target is the MEDIAN.**

⚠ The sweep runs **keys=0**, so the player sim is a no-op and **collision never runs**. The median
therefore does NOT include M14-d's ~11.6M-per-moving-tic. That is the honest shape of a renderer
sweep, but say so whenever you quote it. Report both or neither.

## 1. Where things stand

Branch `m13opt3-early-out`, tip **`f54300e`**. The campaign so far, every step gated byte-exact:

| step | commit | median | mean | p90 | worst | <26M |
|---|---|---|---|---|---|---|
| certified, pre-M14 | — | 22.94M | 22.58M | — | 48.46M | — |
| M14-e as shipped | `45b7190` | **60.29M** | 62.01M | 82.52M | 97.01M | 0% |
| + binding round-trips | `1202393` | **38.48M** | 40.21M | 60.36M | 74.78M | 15% |
| + clear & per-leaf reads deleted | `f54300e` | **36.68M** | 38.17M | 58.08M | 71.67M | 18% |
| **target** | | **26.00M** | | | | |

**−10.7M still to find.**

### Where the remaining +13.74M over 22.94M sits

It reconciles to within ~0.3M — but ⚠ **only two of these five are directly measured** (see §10.3).
The rest are derived, estimated or extrapolated, and are marked:

| component | ops | instrument |
|---|---|---|
| `thing_load` × ~117 loaded things @ 45,934 | **~5.4M** | per-call cost MEASURED (`m14_thload_split.py`, `nozlt` = today's macro); the ×117 is derived |
| `bind_things`, warm | **~3.2M** | ESTIMATED: `_bind.py` WARM 5.20M minus a ~2M probe-dump subtraction that is itself a guess |
| *unattributed residual* (labelled the per-leaf walk) | **~2.5M** | NOT MEASURED — a leftover, and the label is probably wrong about why; see §10.2 |
| §4b full-precision `wall_x_range_m` | **~2.2M** | EXTRAPOLATED from gate viewpoints at M14-c; never measured at the median on this build |
| the wire (positions + bindings, in and out) | **~0.4M** | §2.1 of `handoff-m14.md`, 73.6 ops/byte in, 54 out |

⚠ **~117 is DERIVED, not counted.** It comes from dividing a residual by the measured per-call
cost. It has been consistent across three sweeps, but if a lever underdelivers, **count the calls
directly before believing the model** — that is the one number in this table without its own
instrument.

## 2. ⚠ THE PLAN AS WRITTEN DOES NOT REACH 26M. Read this before starting.

I audited my own arithmetic and it does not close. Two independent ways of checking say the same
thing.

**By subtraction.** Need `36.68 − 26.00 = 10.68M`. Best case of all four levers is
`C 2.2 + D 2.4 + B 3.5 + E 2.2 = 10.30M` — **short by 0.38M even if every one lands at its optimistic
estimate**, and three of the four estimates are soft. (The first draft of this document said
"~10.9M against a 10.7M need"; that was stale — I revised lever D down to a NET figure after its own
wire cost and never re-added the total.)

**By budget, which is the more useful framing.** A 26M median allows everything M14 added a total of
**+3.06M** over the certified 22.94M renderer. M14 currently costs **+13.70M**. So the campaign has
to remove **78% of the entire milestone's cost**. Component by component, if every lever lands:

| | today | after levers | |
|---|---|---|---|
| `thing_load` | 5.4M | ~1.0M | lever B, optimistic |
| `bind_things` warm | 3.2M | ~0.2M | lever D |
| unattributed residual | 2.5M | ~0.3M | lever C, *if* the label is right — see below |
| §4b precision | 2.2M | **2.2M** | lever E is *unproven* |
| the wire | 0.4M | 0.4M | irreducible |
| | **13.7M** | **4.1M** | against a **3.06M** budget → **OVER** |

**⚠ THEREFORE LEVER E IS LOAD-BEARING, NOT OPTIONAL.** If §4b's ~2.2M cannot be reduced, 26M is out
of reach no matter how well B, C and D go. Its feasibility is the single biggest unknown in this
plan and it is currently last in the work order. **Consider pricing it early** (it needs no build —
the row-rule audit is reading `projection.fj` and counting nonzero nibbles).

**What to do about the gap.** Do NOT close it by turning a `DEG_*` knob: fidelity is the owner's
call and the owner has twice chosen detail over the op line (`e1m1-15m-campaign` memory). The honest
options, in order: (a) find a fifth lever — candidates in §10; (b) reach 26M and report which
component ended where; (c) come back with the measured shortfall and let the owner decide between
the number and the picture. **(c) is a legitimate outcome of this campaign, not a failure.**

## 2b. The four remaining levers, cheapest and safest first

### Lever C — the per-leaf head check, at a BAKED address (~2.2M, very low risk) ← DO THIS FIRST

Every seg-carrying leaf currently does `hex.set w/4, cur_ss, {s}` + `stl.fcall thing_pass_leaf`,
and `thing_pass` then does `ptr_index` into `sshead` and reads the head — 682 times a frame, almost
all of them finding an empty leaf (only ~132 leaves hold things).

**But `s` is a compile-time constant at the call site**, so `sshead + s*2*dw` is a compile-time
ADDRESS. The leaf can test the head with no pointer math and no fcall at all:

```
hex.if0 2, sshead + {s}*2*dw, ss{cid}_nothings     // baked address; 0 = empty (see §3)
hex.set w/4, cur_ss, {s}
hex.set 4, ss_flr, {floor}
hex.set 4, ss_ltb, {ltbase}
stl.fcall thing_pass_leaf, tp_ret
ss{cid}_nothings:
```

Only leaves that actually hold things pay the call. **Do this one first** — it is a ~6-line emitter
change, it cannot move a pixel (the callee's first act is the same test), and it makes the sweep
after it a clean read on the others.

⚠ **ITS BUDGET RESTS ON A LABEL I ASSIGNED WITHOUT EVIDENCE.** The 2.5M in §1 is a *residual* — what
was left after subtracting the four measured components — and I called it "the `thing_pass` per-leaf
walk". That may be wrong, and there is a specific reason to doubt it: **the BSP walk does not visit
all 682 leaves.** It runs front-to-back and stops when the frame is claimed (the `full` latch), so
the visited count per frame is well under 682 — which would make 2.5M / (visited leaves) an
implausibly large per-leaf cost and mean the residual is mostly something else. **Measure the
visited-leaf count and the real per-leaf cost before budgeting this lever at 2.2M.** The cheap way:
add a counter to `subsector_action` in a throwaway build, or diff a build whose `thing_pass_leaf`
call is stubbed out.

⚠ **`subsector_action` IS SHARED WITH THE STATIC PATH.** The snippet above must live strictly inside
the `moving_things` branch. Run `cr/emit_hash_vs_head.py` after this change specifically — it is the
one lever that edits a function the shipped binary also goes through.

### Lever D — the leaf LISTS round-trip too (~3.0M, medium risk)

`bind_things` still rebuilds `sshead`/`thnext` from scratch every frame. The bindings already
round-trip (§3); the lists can too, by the same argument — they are world state, and fj has none
between frames. Then a frame with nothing moving does **zero** binding work, and a moved thing
costs one unlink + one insert, which is DOOM's `P_UnsetThingPosition`/`P_SetThingPosition` exactly.

⚠ **THE ORDERING IS THE TRAP.** Today the lists are built by prepending in DESCENDING thing index,
which makes traversal ASCENDING — and ascending order is what makes a static thing claim the same
front-to-back sprite slot it always has. An incremental insert that PREPENDS breaks that and moves
pixels. **The insert must be a SORTED insert** (walk until the next index exceeds `t`). Lists
average 1.9 entries and top out at 13, so the walk is nothing.

Wire cost: `sshead` is 682 entries and `thnext` 251, but see §3 — a wire-filled array needs the
16-nibble-slot accessor, so budget 8 bytes/entry in unless you narrow it. That is ~7.5KB each way,
~0.6M ops. **Net saving is therefore ~2.4M, not 3.0M** — price it before building it.

⚠ **THE COLD FRAME GETS WORSE, and that is fine but must be stated.** With the lists relayed, a cold
start (level load, or any frame the host cannot supply lists for) does the full re-locate *and* the
full rebuild. Cold is already ~61M today (`--cold` on the sweep); it happens once per level load, not
per frame. Keep `m14_sweep.py --cold` in the report so the number is visible rather than hidden.

⚠ **`bind_things` still has to run for the DIRTY things.** This lever does not delete the macro; it
changes it from "rebuild everything" to "unlink + sorted-insert what moved". Do not let the shape of
the win tempt you into skipping the rebuild entirely when nothing is dirty — the lists must still be
*read* off the wire into the arrays each frame, which is the ~0.6M above.

### Lever B — `thing_load` becomes lazy (~3.5M, highest risk, most invasive)

45,934 ops per loaded thing, paid *before* the projection has decided anything, and the baked path
it replaced cost ~0. Measured split of what remains:

| | ops | share |
|---|---|---|
| `read_table_packed 22` + its 13 field extractions | 29,938 | 65% |
| the position accessor (`shl_hex` + `ptr_index` + `read_hex 16`) | 16,995 | 35% |

The plan: load position first, let `frame.thing_record_body`'s existing early rejects fire (behind
the view, beyond `sp_tzmax`, below the min-size bar), and load the other nine fields only for
survivors. If ~25 of ~117 survive: 117×~29k + 25×~46k ≈ 4.6M against 5.4M — **only ~0.8M** unless
the reject also avoids the row read, which needs `sp_tzmax` in a separate narrow table.

⚠ **PRICE THIS BEFORE BUILDING IT.** The saving depends entirely on the survivor count, which is
not measured. `thing_record_body` is one of the most intricate macros in the repo and splitting its
call sequence is the riskiest change in this document. **Count the survivors first** (instrument
the oracle: how many things per frame pass each reject at the sweep's 260 viewpoints?). If the
answer is "most of them survive", **this lever does not exist** and the campaign is short by ~3.5M
— which is a finding to report, not a reason to turn a knob.

⚠ **IT CAN MOVE PIXELS THROUGH THE BUDGETS, WHICH IS THE REAL DANGER.** `thing_record_body` does not
just reject — it *spends*: `n_thing`/`n_mon` against `THING_BUDGET`/`MONSTER_BUDGET`, the `degfl`
graduated-acceptance path, the `n_hd` HD counter, and the monotone `tstop` latch. Those are consumed
**in the order things are visited**. Any restructuring that changes *when* a thing is rejected
relative to when it spends a budget changes which things get drawn — byte-exactness dies and the
symptom is a sprite missing in a crowded room, i.e. exactly the M13 failure class. The split must be
**reject-before-spend, in the same order**, and the gate's crowded viewpoint (664, 291, 0x18000000 —
the sprite-overlap frame) is the one that will catch it.

### Lever E — §4b's precision cost (~2.2M, feasibility unknown)

`proj.wall_x_range_m` went to full 16.16 in M14-c because the M13-mapmul narrowing read the view
position's INTEGER MAP SLICE, which is bit-identical only while `viewx = m<<16` — true of every
gate, test and golden in repo history, and false from the player's second step. See §4b of
`handoff-m14.md`; **do not re-litigate the fix, it is correct.**

What is open is whether the *full-precision* form can be cheaper. The row rule (a multiply costs one
schoolbook row per nonzero nibble of the SECOND operand — see the `fj-cost-model` memory) says the
operand order and width are worth auditing. A runtime conditional on "low nibbles are zero" is NOT
the answer: during play the player is fractional essentially always.

⚠ **THE 2.2M IS AN ESTIMATE, NOT A MEASUREMENT ON THIS BUILD.** It is "+9–10% of 22.94M", taken from
the four gate viewpoints when the fix shipped in M14-c. Nobody has measured §4b's cost at the median
on the current binary. Since §2 shows this lever is load-bearing, **measure it properly first**: build
once with the map-slice form restored (knowingly wrong, measurement-only, never committed) and sweep
it. That is one 25-minute build for the number that decides whether the campaign can succeed.

⚠ **DO NOT SHIP THE MAP-SLICE FORM.** It is byte-exact only at integer view positions, which the sim
violates from the player's second step. It is a measuring instrument here and nothing else.

---

## 3. What M14-e's perf work already changed (read before editing `sim.fj`)

- **`thss[t]` round-trips on the wire.** `0xFFFF` = "the host moved this one, re-locate it".
  Everything else is last frame's answer and is trusted. fj still COMPUTES every binding; the host
  only carries it between frames, and a wrong one diverges against the oracle immediately because
  the oracle derives it from position independently.
- **The empty sentinel is `0`, and the lists store `t + 1`.** A bare `hex.vec` is zero-filled and
  one run is one frame — fj self-modifies, so the host reloads the pristine image every frame and
  anything baked is re-initialised for free. That is why `bind_things` has **no clear loop at all**.
- **`ss_flr` / `ss_ltb` are baked by the leaf**, not read from tables. Both are properties of the
  subsector, fixed at level load. `ssflr`, `sslgt` and `ltbase` are no longer emitted at all.
- **The wire** (`doomfj.wireformat` is the SSOT): positions 8 bytes/thing in; bindings 2 bytes/thing
  in and **4 out** (`emit_bytes4` is the emitter this protocol has). `StreamScreen` needs
  `n_things=` to know the `THING_CMD` block's length.

## 4. ⚠ fj traps this campaign paid for — read before writing pointer or `rep` code

Every one of these cost at least one wasted build or probe cycle.

1. **`hex.input` does NOT fill an array that `ptr_index` + `read_byte` addresses.** The wire writes a
   hex.vec (nibble per slot); read_byte addresses something else. `scratchpad/_ptrunit.py` shows a
   write_byte/read_byte array round-tripping while a wire-filled one reads back garbage. The
   accessor that works — and the only one proven on a wire-filled array — is in `_ptrunit2.py`:
   **nibble offset = index × 16 via `shl_hex 1`, then `read_hex` / `write_hex`.** This is the same
   trap the POSITION array hit; it is now four instances.
2. **`hex.write_hex 4, ptr, src` DOES round-trip.** This corrects the older `fj-lessons` note that
   the 3-arg overload writes a single nibble — verified in `_ptrunit2.py`.
3. **`rep(n, i)` with `n` a macro PARAMETER silently expands to NOTHING.** `rep` needs a literal.
   The tell is the assembled binary getting SMALLER after you add unrolled work.
4. **`rep(c, i) ;label` is a syntax error.** There is no compile-time `if` built that way.
5. **Running pointers KILL THE PROGRAM** — `hex.add w/4, ptr, k` per iteration then `read_byte`
   through it. Reproduced in `_ptrunit.py`.
6. **`ptr + n*dw` offsets the POINTER CELL's own address**, not the address it points to. It cannot
   reach a field inside a pointed-to record.
7. **UNROLLING IS A TRAP AT THIS SCALE.** 251 inlined copies of a ~25-line macro, or 682 unrolled
   `hex.set`s, or 682 baked `hex.vec` lines, each took a probe from seconds to **30–40+ minutes** to
   assemble. The assembler is ~cubic in unrolled ops; heavy code belongs in a shared `stl.fcall`
   leaf. **This killed two otherwise-correct optimisations.**
8. **`read_table_packed`'s cost barely depends on the index width** — 69,503 ops at the emitter's
   real widths vs 68,571 at a hard-coded 4. Do not optimise the width; do reduce the number of reads.
9. **Anything handed to a `w/4`-wide `mov` must itself be `w/4`.** `ptr_index` does `mov w/4` out of
   its index. Three defects of this one family in M14-e alone.

## 5. ⚠ Method traps — these cost more than the fj ones

1. **A STALE BASELINE IS NOT A CONTROL.** `cr/emit_hash.py` compares against a *stored* hash; after
   a run of milestones it reports DIFF for every config regardless of the change under review, so it
   reads as evidence and is noise. Use **`cr/emit_hash_vs_head.py`**, which self-baselines (emits
   the certified AND shipped config twice in one process, worktree vs HEAD) and ships an R9
   `--selftest`. It caught a real defect the day it was written: an unconditional `""` appended to a
   parts list still costs a newline.
2. **VACUITY CONTROLS MUST BE TWO-SIDED.** The M14-e gate counts BOTH leaf re-bindings AND tics whose
   pixels changed. Counting bindings alone passed a mover set (`i % 8 == 0`) whose 31 things were all
   off-screen — 22 leaf changes, 0 frames changed. Movers are now the 30 things nearest spawn.
3. **`python -m pytest tests/host -q` IS NOT the ~1-minute run the ladder claims.** Nothing deselects
   `test_build_wall_renderer_e1m1_flat`, so a bare run sits on a ~70-minute build at test 45 and
   looks exactly like a hang. Use:
   `--deselect tests/host/test_e1m1_integration.py::test_build_wall_renderer_e1m1_flat` → **242
   passed in 93s**. (This is written down in the `m14-handoff` memory too, and I still lost 40
   minutes to it.)
4. **A probe must use the EMITTER's real parameters.** The first `thing_load` breakdown hard-coded a
   4-nibble index width where the emitter passes 2 and 3 — it was measuring a program nobody builds.
   It happened not to matter; next time it will.

## 6. The instruments

| tool | cost | what it answers |
|---|---|---|
| `scratchpad/m14_sweep.py <fjm> --things [--cold] [--csv f]` | ~5 min | **THE TARGET METRIC.** 260-frame median on the binary wire. `--cold` feeds all-dirty bindings (a cold start) instead of the steady state. |
| `scratchpad/m14_gate.py 10 --things [--collide]` | ~25 min build + ~10 min | **THE PROOF.** phase 1 byte-exact ×4 + cold-vs-warm identical pixels; phase 2 N relayed tics, frame AND state AND bindings vs the oracle; two-sided vacuity controls. |
| `scratchpad/cr/emit_hash_vs_head.py [--selftest]` | ~15 min | the shipped path is unchanged (14/14 parts hash-identical, certified + shipped configs) |
| `scratchpad/_bind.py` | ~3 min | `bind_things` COLD vs WARM: identical lists, and the cache is actually taken |
| `scratchpad/_tpass.py` | ~2 min | every leaf visits exactly its things, in ascending order |
| `scratchpad/m14_thload_split.py` | ~5 min | where `thing_load`'s ops go, by ablation, with a linearity control and a sum check |
| `scratchpad/m14_thload_cost.py` | ~3 min | `thing_load` per-call cost, k-sweep |
| `scratchpad/_ptrunit.py` / `_ptrunit2.py` | seconds | the pointer/accessor semantics in §4 |
| `pytest tests/host -q --deselect …e1m1_flat` | 93s | 242 host tests |

⚠ **ONE HEAVY BUILD AT A TIME** (CLAUDE.md rule 1). Two concurrent E1M1 builds die silently — exit
255, empty output, no error. The `--things` build is ~18.6MB and takes ~25 minutes; it is cached at
`scratchpad/fjmcache/m14_bin[_coll][_things].fjm` and the gate reuses it unless you pass `--rebuild`.
**The cache key must name every flag that changes the binary** — that was a real bug.

## 7. The order I would work in

⚠ Revised after the §2 audit: **the two unknowns that decide whether 26M is reachable now come
first**, because both are cheap and either can end the campaign early with an honest answer.

1. **Price lever E** (no build — read `projection.fj` and audit the multiply widths against the row
   rule; then ONE measurement build with the map-slice form restored). §2 shows the target is
   unreachable if this is zero, so learn it before spending days on B/C/D.
2. **Count lever B's survivors** on the oracle at the sweep's 260 viewpoints. No build.
3. **Attribute the 2.5M residual** — is it really the per-leaf walk? Count VISITED leaves, which is
   far fewer than 682. No build, or one stubbed build. Lever C's whole budget depends on this.
4. **Lever C.** ~6 emitter lines. Build, gate, sweep, plus `emit_hash_vs_head` (it touches
   `subsector_action`, which the shipped path also goes through).
5. **Lever D**, with the sorted insert. Build, gate, sweep. The gate's phase-1 cold-vs-warm check is
   what will catch an ordering mistake.
6. **Lever B** if step 2 says it pays, else report the shortfall.
7. **Lever E** for real, if steps 1–6 leave a gap it can close.

Steps 1–3 are a day of cheap measurement that de-risks a week of building. **If they say 26M is out
of reach, stop and report — that is the right outcome, not a failure.**

Gate and sweep after **each** lever, not at the end. Every step so far has been byte-exact; the
moment one is not, the previous sweep is the bisect point and the previous commit is a clean revert
— keep each lever as one self-contained commit so that stays true.

## 7b. Acceptance criteria — what "done" means

The campaign is complete when **all** of these hold, reported together:

1. `m14_sweep.py … --things` median **< 26,000,000** on the 260-frame grid, with min / mean / p90 /
   worst and the `<26M` percentage quoted alongside it.
2. `m14_gate.py 10 --things` **PASS**: phase 1 byte-exact ×4, cold-vs-warm identical pixels, phase 2
   10/10 relayed tics byte-exact with bindings matching the oracle, and **both** vacuity controls
   non-zero.
3. `m14_gate.py 10 --things --collide` **PASS** — see §10.4. This path has NOT been gated once during
   the campaign.
4. `pytest tests/host -q --deselect …test_build_wall_renderer_e1m1_flat` → **242 passed**.
5. `cr/emit_hash_vs_head.py` → **14/14 parts identical**, so the shipped binary is provably untouched.
6. The `--cold` sweep number reported too, so the level-load cost is visible rather than hidden.

⚠ **The median is the target; the WORST case is not covered by it.** Worst is 71.67M today and no
lever above targets the tail specifically. A 26M median with a ~50M worst still means visible
hitching. Flag that to the owner once the median lands — do not silently accept it, and do not
silently fix it with a `DEG_*` knob.

## 8. ⚠ THE CR DEBT — owed, and explicitly deferred

**36 commits are unreviewed** — everything since `54da396` (the last CR, 2026-08-12): all of M14
plus this campaign. The owner's instruction is the reduction first, **then** the CR. Do not close
this campaign without flagging that the CR is still outstanding.

M14 is well *gated*, which is not the same as reviewed: gates prove the mirrors agree, CR catches
what a passing gate is happy to ship. This milestone's own history — a budget that bound and
smudged pixels, two vacuous controls, three pointer defects, a stale-baseline non-control — is the
argument for actually doing it.

## 9. Honest limits carried forward from M14-e

- **Things move on the INTEGER grid.** fj carries a thing at full 16.16, but the oracle's
  `thing_positions` override writes the integer `t.x`/`t.y` a WAD thing has. Lifting it means giving
  the oracle's thing record 16.16 coordinates — §4b's bug in the other mirror.
- **Every seg-carrying leaf calls `thing_pass`**, not only the ones that can hold a thing. Gating on
  `thing_live_subsectors` would save the empty walks but a thing landing outside the gate would
  silently vanish — the exact failure class M14-a exists to prevent. **Lever C solves this the safe
  way** (a runtime head test at a baked address) and should be preferred to any emit-time prune.
- **The art is one still frame** — no walk cycle, no 8-way facing. A moving monster slides.

## 10. ⚠ Known gaps in THIS PLAN — found by auditing it, not by building against it

These are the places the plan is thin. They are listed because a handoff that hides its own soft
spots is worse than no handoff.

**10.1 The arithmetic does not close.** §2. Short by 0.38M in the best case, and much more if lever
B or E underdelivers. Named candidates for a fifth lever, none priced:
 * **split the 22-byte thing row** into a hot part (what the projection's rejects read) and a cold
   part (what only a drawing thing needs), so even the non-lazy path reads less. Cheaper and far
   less invasive than lever B proper, and partly independent of it.
 * **narrow the `thss` wire slot.** It is 16 nibbles for a 4-nibble value because that is the one
   accessor proven on a wire-filled array (§4.1). A cheaper index scaling (×4 without a multiply)
   would cut the wire and the read. Small — tens of k, not M — but real.
 * **the position accessor** (16,995/call, ~2.0M total) has had no attempt at all. `read_hex 16`
   reads the whole 16.16 pair when the rejects may only need one coordinate first.
 * **attack the certified 22.94M baseline itself.** Out of scope for this campaign and squarely the
   owner's fidelity call, but it is where the remaining headroom actually is.

**10.2 The residual is unattributed.** §2b lever C. 2.5M of the 13.7M has a label, not a measurement,
and the label is probably wrong about *why* (682 leaves are emitted; far fewer are visited).

**10.3 Three of five cost components have soft numbers.** `~117 loaded things` is derived; the
`~2M` probe-dump subtraction in `bind_things` warm is estimated; §4b's `2.2M` is extrapolated from
gate viewpoints at a different milestone. **Only `thing_load`'s per-call cost and the sweep medians
are directly measured.** Treat the rest as hypotheses with error bars.

**10.4 `--collide` has never been gated in this campaign.** Every lever changes `bind_things`,
`thing_pass` or `subsector_action`; collision rides the same binary through `player_sim`. The
`m14_bin_coll.fjm` cache does not currently exist and `m14_bin.fjm` is **STALE — built 04:20, the
§4b fix landed 04:49 — delete it rather than use it as a baseline.** Gate `--things --collide` at
least once before declaring done (§7b.3).

**10.5 No lever targets the TAIL.** Worst is 71.67M. A 26M median can coexist with 50M+ spikes. §7b
flags it; nobody has decided what the tail requirement is.

**10.6 The oracle should not change, and if a lever needs it to, stop.** Every lever here is fj-side.
The oracle defines byte-exactness; editing it to make a lever work is how a mirror silently stops
being a mirror. The one legitimate oracle change on the horizon is unrelated (16.16 thing positions,
§9).

**10.7 fps is never mentioned.** The whole campaign is in ops/frame because that is what diffs
deterministically. The walker runs ~96–127M fj ops/s (`e1m1-15m-campaign` memory), so 26M is roughly
4–5 fps. **If the owner's actual goal is a frame rate rather than an op count, 26M may be the wrong
target** and that is worth asking before spending the week.

**10.8 Nothing here re-blesses the certified artefacts.** `deg_gate.py`'s header still carries
pre-M14-a op counts, and no new certified binary hash has been published since `b_272d37507ca58434`.
When the campaign lands, the certified numbers and the archived `.fjm` need updating — that is part
of closing it, and it is not in any lever above.
