# HANDOFF: the 26M campaign — getting the median frame back under control

Owner directive (2026-08-14): **median 26M fj ops/frame, and get there BEFORE the CR.**

M14 shipped input, simulation, collision and moving things — and roughly tripled the median frame.
This document is the reduction back. Written for a session with no prior context: everything you
need is here or pointed at from here. Read §0 and §1 before touching anything.

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

All measured, and it reconciles to within ~0.3M:

| component | ops | instrument |
|---|---|---|
| `thing_load` × ~117 loaded things @ 45,934 | **~5.4M** | `m14_thload_split.py` (`nozlt` variant = today's macro) |
| `bind_things`, warm | **~3.2M** | `_bind.py` WARM 5.20M minus ~2M of probe dump loop |
| `thing_pass` per-leaf walk, 682 leaves | **~2.5M** | the residual; see lever C, which is exactly this |
| §4b full-precision `wall_x_range_m` | **~2.2M** | +9–10% of 22.94M, measured when it shipped |
| the wire (positions + bindings, in and out) | **~0.4M** | §2.1 of `handoff-m14.md`, 73.6 ops/byte in, 54 out |

⚠ **~117 is DERIVED, not counted.** It comes from dividing a residual by the measured per-call
cost. It has been consistent across three sweeps, but if a lever underdelivers, **count the calls
directly before believing the model** — that is the one number in this table without its own
instrument.

## 2. The four remaining levers, cheapest and safest first

Together these come to ~10.9M against a 10.7M need. **There is no slack.** If one underdelivers,
say the number — do not reach for a `DEG_*` knob. Fidelity is the owner's call, and the owner has
twice chosen detail over the op line (see `e1m1-15m-campaign` memory).

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

### Lever E — §4b's precision cost (~2.2M, feasibility unknown)

`proj.wall_x_range_m` went to full 16.16 in M14-c because the M13-mapmul narrowing read the view
position's INTEGER MAP SLICE, which is bit-identical only while `viewx = m<<16` — true of every
gate, test and golden in repo history, and false from the player's second step. See §4b of
`handoff-m14.md`; **do not re-litigate the fix, it is correct.**

What is open is whether the *full-precision* form can be cheaper. The row rule (a multiply costs one
schoolbook row per nonzero nibble of the SECOND operand — see the `fj-cost-model` memory) says the
operand order and width are worth auditing. A runtime conditional on "low nibbles are zero" is NOT
the answer: during play the player is fractional essentially always.

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

1. **Lever C.** ~6 emitter lines, cannot move a pixel, ~2.2M. Build, gate, sweep.
2. **Count the survivors** for lever B, on the oracle, at the sweep's 260 viewpoints. No build. This
   decides whether the campaign can reach 26M at all, so learn it early and cheaply.
3. **Lever D**, with the sorted insert. Build, gate, sweep. The gate's phase-1 cold-vs-warm check is
   what will catch an ordering mistake.
4. **Lever B** if step 2 says it pays, else report the shortfall.
5. **Lever E** if still short.

Gate and sweep after **each** lever, not at the end. Every step so far has been byte-exact; the
moment one is not, the previous sweep is the bisect point.

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
