# HANDOFF: the 15M campaign — the median frame, and the fps it buys

Owner directive (2026-08-14): **median 15M fj ops/frame — the number that buys the wanted frame
rate.** Then the CR (§13).

⚠ **This supersedes the 26M plan.** 26M was my own reading of the goal and it was the wrong target:
the owner's goal is a frame rate, and 15M is what delivers it. Read §0–§3 before touching anything;
they change what the campaign *is*, not just its number.

---

## 0. What 15M means, and the number to sanity-check first

The walker sustains **~96–127M fj ops/s** (measured; C-level `freeze`/`reset` in the flipjump-151
clone — see the `e1m1-15m-campaign` memory, which also says 300M/s is NOT reachable at this image
size: ~300MB working set, C-loop locality bound).

| median ops/frame | fps |
|---|---|
| 36.68M — today | 2.6 – 3.5 |
| 26M — the old target | 3.7 – 4.9 |
| **15M — the goal** | **6.4 – 8.5** |
| 12M | 8.0 – 10.6 |
| 10M | 9.6 – 12.7 |

⚠ **CONFIRM THIS BEFORE SPENDING THE CAMPAIGN.** 15M buys 6.4–8.5 fps, not 10+. If the wanted rate
is double figures the target is ~10–12M, which is a materially harder campaign. Ask; do not assume.

## 1. ⚠ YOU HAVE BEEN MEASURING THE WRONG MAP

Every M14 gate, sweep and number in this repo's recent history — **including all of mine** — is on
`tests/fixtures/freedoom_e1m1.wad`. **`scripts/walk_e1m1.py` ships `tests/fixtures/e1m1_lite.wad`.**

| | segs | nodes | leaves | drawable things |
|---|---|---|---|---|
| `freedoom_e1m1.wad` (stock — what deg_gate and m14_gate build) | 2057 | 681 | 682 | **251** |
| `e1m1_lite.wad` (**what actually ships**) | 1378 | 470 | 471 | **197** |

The lite map is ~2/3 the geometry and ~4/5 the things. That matters twice over:

* **M14's overhead scales with things and leaves** (0.78× and 0.69×), so it is materially cheaper on
  the map that runs.
* **The historical 15M result was on LITE.** The `e1m1-15m-campaign` memory records
  `Lite v2 median 20.7M / STOCK on the same 260 frames median 22.6M` — the two are not
  interchangeable and were never claimed to be. `walk_e1m1.py`'s own comment calls stock "canonical
  for goldens".

**⚠ STEP 0 OF THIS CAMPAIGN IS TO DECIDE WHICH MAP THE 15M TARGET IS ON, AND MEASURE IT THERE.**
If the deliverable is what `walk_e1m1.py` runs, the target is lite and a chunk of the gap may already
be illusory. If the owner wants stock playable, say so and the budget below gets harder. **Do not
mix them in one report again** — that is the same error as quoting a gate viewpoint against a median
(§4), one level up.

## 2. The budget, and why this is not "undo M14"

| | median |
|---|---|
| certified renderer, pre-M14 (stock) | **22.94M** |
| M14 as it stands (stock) | **36.68M** |
| **target** | **15.00M** |

**15M is BELOW the pre-M14 baseline.** So removing every single op M14 added still leaves the
campaign ~8M short. This is two campaigns stacked:

* **Phase 1 — remove M14's +13.74M.** Best case with the four known levers is ~4.1M remaining (§5),
  and that was already short of the old 26M target.
* **Phase 2 — cut the base renderer from 22.94M to ~14M**, a 39% cut of a renderer that has already
  been through a dedicated optimisation campaign.

Phase 2 is the campaign. Phase 1 is the warm-up.

## 3. ⚠ THIS IS A REVIVAL, AND THE HISTORY DECIDES THE PLAN

**15M is not a new goal.** It is the standing owner directive from 2026-08-01: *"use the e1m1 and
optimize it to be about ~15M fj/frame. it's a must have goal."* — with visual compromises, algorithm
replacement, and modifying the level "a bit" **explicitly allowed**.

**It was MET.** 2026-08-02, commit `c0899e2`: **median 14.45M, 53% of 260 frames under 15M**
(E1M1-lite + bbox wedge cull + W1 walls + bands-as-code, all four visual features, every monster,
7 gates byte-exact). M13-W1R then shipped at **median 14.91M / 51% under 15M**.

**Then it was undone by CORRECTNESS, not by carelessness.** From the campaign memory:

| what landed | median | why |
|---|---|---|
| goal met | 14.45M → 14.91M | |
| sprite-vanish fix (`08e0d81`) | → **20.07M** | the bug was *suppressing real sprite work*; owner's frame went 13→39 things |
| V5-DROP (`2720484`) | → **22.78M** | drop-off lips; pools and stair treads were invisible |
| | | *"COMBINED HONEST BILL … the old numbers were cheating (hidden sprites, invisible drop-offs)"* |
| DEG-knob ladder (`8f30eb6`) | → **19.96M** | bake/knob-only levers, no correctness change |
| P2b field-flip fix (`4fc028a`) | → 21.52M | correctness |
| SPR-NEAR (`b91d3b3`) | → 22.19M | owner chose detail |
| smudge fix (`740a408`, `902f92e`) | → **22.94M** | correctness |

**So: 15M has never been achieved with today's correctness.** The 14.45M number was, in the repo's
own words, cheating. Any plan that quietly targets "get back to 14.45M" is targeting a number that
was wrong.

⚠ **AND THE REPO ALREADY CONCLUDED WHERE THE FLOOR IS:** *"HONEST FLOOR: a hard 25M cap needs
VISIBLE near-content loss"* — that was for the **worst frame**, with documented options (HD-strip
budget under load ~2–3M crowd; K=1 stacks / `STEP_SEG_BUDGET` 8, −2–5M stairs, visible; count
budgets; harsher DEG knobs). A **15M median with correctness intact** is a strictly harder ask than
the one that conclusion was written about.

## 4. ⚠ THE QUESTION ONLY THE OWNER CAN ANSWER

The 2026-08-01 directive **permits visual compromise**. But across 2026-08-04 → 08-11 the owner
**twice chose detail over the op line** — SPR-NEAR (sprite quality follows distance, +0.67M) and
declining the harsher C/D knob options, with the note *"their sprites-always-visible ask is newer
and explicit → do not silently degrade"*.

**Those two positions now conflict**, and 15M cannot be planned without resolving it:

> **Is 15M worth giving picture back for — and if so, which picture?** The concrete, priced options
> are in §7. Each has a named visible cost. **Nothing in this campaign should silently turn a
> `DEG_*` knob** — that is what "do not silently degrade" means — but with an explicit answer, knobs
> become the cheapest levers available.

If the answer is "no visible loss", say now that 15M is very unlikely and let the owner pick between
the frame rate and the picture. That is a legitimate outcome (§14).

---

## 5. PHASE 1 — remove M14's overhead (target: +13.74M → ~1M)

The four levers, their budgets, and their traps are unchanged from the 26M plan and are detailed
below in §5a–§5d. Summary and honesty markers:

| lever | est. | confidence | risk |
|---|---|---|---|
| **C** per-leaf head check at a baked address | ~2.2M | **low** — rests on an unattributed residual (§5a) | very low |
| **D** leaf lists round-trip | ~2.4M net | medium | medium — the SORTED insert (§5b) |
| **B** lazy `thing_load` | ~3.5M **or ~0.8M** | **low** — survivor count unmeasured | **high** — can move pixels via the budgets |
| **E** §4b precision | ~2.2M | **low** — extrapolated, never measured at the median | unknown |

**Only `thing_load`'s per-call cost (45,934, measured) and the sweep medians are hard numbers.** The
`~117 loaded things/frame` is derived; the `bind_things` warm figure subtracts an estimated ~2M of
probe overhead; §4b's 2.2M is extrapolated from gate viewpoints at a different milestone.

Phase 1's own ceiling, if every lever lands optimistically, is M14 ≈ 4.1M — **not the ~1M this
campaign needs.** Phase 1 alone cannot reach even 26M (that was the 26M plan's fatal arithmetic).
Under a 15M target, **Phase 1 is necessary but nowhere near sufficient**, which is why Phase 2 is
where the effort belongs.

### 5a. Lever C — the per-leaf head check, at a BAKED address

Every seg-carrying leaf does `hex.set w/4, cur_ss, {s}` + `stl.fcall thing_pass_leaf`, and
`thing_pass` then `ptr_index`es into `sshead`. But `s` is a compile-time constant at the call site,
so `sshead + s*2*dw` is a compile-time ADDRESS:

```
hex.if0 2, sshead + {s}*2*dw, ss{cid}_nothings     // baked address; 0 = empty (see §8)
hex.set w/4, cur_ss, {s}
hex.set 4, ss_flr, {floor}
hex.set 4, ss_ltb, {ltbase}
stl.fcall thing_pass_leaf, tp_ret
ss{cid}_nothings:
```

⚠ **ITS BUDGET RESTS ON A LABEL I ASSIGNED WITHOUT EVIDENCE.** The 2.5M it targets is a *residual*.
The BSP walk does **not** visit all 682 leaves — it runs front-to-back and stops when the frame is
claimed (`full`), so the visited count is far lower and the residual is probably mostly something
else. **Count visited leaves before budgeting this.**

⚠ **`subsector_action` IS SHARED WITH THE STATIC PATH.** Keep the snippet strictly inside the
`moving_things` branch and run `cr/emit_hash_vs_head.py` after this lever specifically.

### 5b. Lever D — the leaf lists round-trip

The bindings already round-trip (§8); the lists can too. A frame with nothing moving then does zero
binding work; a moved thing costs one unlink + one insert — DOOM's
`P_UnsetThingPosition`/`P_SetThingPosition`.

⚠ **THE ORDERING IS THE TRAP.** Lists are built by prepending in DESCENDING index so traversal is
ASCENDING, and ascending order is what makes a static thing claim the same front-to-back sprite slot.
**The insert must be a SORTED insert.** Lists average 1.9 and top out at 13.

⚠ Wire cost ~0.6M (a wire-filled array needs the 16-nibble-slot accessor, §11.1) — hence ~2.4M net,
not 3.0M. The lists must still be *read* each frame. The cold frame gets worse; report
`m14_sweep.py --cold` alongside.

### 5c. Lever B — lazy `thing_load`

45,934 ops per loaded thing: `read_table_packed 22` + 13 field extractions = 29,938; the position
accessor = 16,995. Load position first, let `frame.thing_record_body`'s existing rejects fire, load
the rest only for survivors.

⚠ **PRICE IT FIRST — count the survivors.** If most survive, this lever does not exist.

⚠ **IT CAN MOVE PIXELS THROUGH THE BUDGETS.** `thing_record_body` doesn't just reject, it *spends*:
`n_thing`/`n_mon` against `THING_BUDGET`/`MONSTER_BUDGET`, `degfl` graduated acceptance, `n_hd`, and
the monotone `tstop`. Those are consumed **in visit order**. Restructuring when a thing is rejected
relative to when it spends changes which things draw — the M13 sprite-vanish failure class. The
split must be **reject-before-spend, in the same order**; the crowded gate viewpoint
(664, 291, 0x18000000) is what catches it.

### 5d. Lever E — §4b's precision cost

`proj.wall_x_range_m` went to full 16.16 because the M13-mapmul narrowing read the view position's
INTEGER MAP SLICE — bit-identical only while `viewx = m<<16`, false from the player's second step.
See §4b of `handoff-m14.md`; **the fix is correct, do not re-litigate it.** Open question is whether
the full-precision form can be cheaper (row rule: cost ∝ nonzero nibbles of the SECOND operand).

⚠ 2.2M is **extrapolated**, never measured at the median on this build. Measure it: one build with
the map-slice form restored (measurement only, **never committed** — it is byte-exact only at integer
view positions).

## 6. PHASE 2 — the base renderer, 22.94M → ~14M

**This is the campaign.** It has no plan yet, and writing one is the first real task. What exists:

* **The prior campaign's lever list**, already priced and partly rejected, in the
  `e1m1-15m-campaign` memory — the DEG ladder (22.78 → 19.96 in four knob/bake rungs), W1 flat-lit
  walls (−3.5–5.5M at two measured viewpoints, but W1R shipped *deliberately* for looks), bands-as-
  code, the bbox wedge cull, far cull 3000, HD-strip budgets, K=1 stacks, `STEP_SEG_BUDGET` 8.
* **`EXP-11`, the column-scaling renderer** — the one *architectural* idea recorded as capable of
  closing a worst-frame gap that feature compromises cannot. Never built. If 15M needs a structural
  answer rather than knobs, this is the candidate, and it is a large piece of work.
* **Existing decomposition research**: *"tail = crowd frames (104 near HD strips) vs geometry frames
  (floor 33.4M with things OFF); ablation builds: things 2–17M, stack 4–9.5M/frame; nnls prices
  strip 84k / record 171k / p2seg 52k / mark 24k"*. `scratchpad/bench.py --knob` patches constants
  on both sides for measurement.

⚠ **DO NOT START PHASE 2 BY BUILDING.** Start by re-deriving where the 22.94M goes *today* — the
ablation numbers above predate several correctness fixes. A fresh decomposition (things off / stack
off / steps off / planes off, one sweep each) is a day and tells you whether 15M is a knob campaign,
an architecture campaign, or impossible.

## 7. The fidelity menu — priced, for the §4 decision

From the campaign memory, each with its measured cost and its **visible** consequence. These are for
the owner to accept or veto individually, not for me to apply.

| option | est. saving | what it costs, visibly |
|---|---|---|
| harsher DEG knobs (the 22.78→19.96 ladder, already shipped) | *already taken* | — |
| HD-strip budget under load | ~2–3M on crowd frames | near sprites lose detail in crowds |
| K=1 stacks globally / `STEP_SEG_BUDGET` 8 | 2–5M on stairs | stair/step faces thin out — **visible** |
| W1 flat-lit walls instead of W1R | 3.5–5.5M (2 viewpoints) | walls lose the randomized texture the owner asked for |
| count budgets (EXP-8 look) | — | fewer things drawn per frame |
| level modification ("a bit", per the directive) | up to ~2M | lite is already this; more means changing the map |

## 8. What M14-e's perf work already changed (read before editing `sim.fj`)

- **`thss[t]` round-trips on the wire.** `0xFFFF` = "the host moved this one, re-locate it".
  fj still COMPUTES every binding; a wrong one diverges against the oracle immediately.
- **The empty sentinel is `0`, and the lists store `t + 1`.** A bare `hex.vec` is zero-filled and one
  run is one frame — the host reloads the pristine image every frame, so baked data re-initialises
  for free. `bind_things` has **no clear loop at all**.
- **`ss_flr` / `ss_ltb` are baked by the leaf.** `ssflr`, `sslgt` and `ltbase` are no longer emitted.
- **The wire** (`doomfj.wireformat` is the SSOT): positions 8 bytes/thing in; bindings 2 bytes in,
  **4 out**. `StreamScreen` needs `n_things=`.


## 9. The work order

⚠ **Everything cheap and decisive comes first.** Three of the four Phase-1 levers rest on unmeasured
numbers, and Phase 2 has no plan at all. Do not build until steps 1–5 are answered.

1. **Ask the owner §0 and §4** — the fps this target is meant to buy, and whether picture is on the
   table. Both change the campaign. Cost: one message.
2. **Settle the MAP (§1)** and re-baseline there. One build + one sweep if it is lite.
3. **Re-decompose the base 22.94M** (§6) — ablation sweeps, things/stack/steps/planes off. A day.
   This is what says whether 15M is knobs, architecture, or impossible.
4. **Price lever E** (§5d) and **count lever B's survivors** (§5c). No builds, then one.
5. **Attribute the 2.5M residual** (§5a) — count visited leaves.
6. Then Phase 1 levers C → D → B → E, one self-contained commit each, gate + sweep after every one.
7. Then Phase 2, planned from step 3's numbers.

Steps 1–5 are ~2 days of measurement and messages that de-risk weeks of building, and any of them
can end the campaign early with an honest answer.

## 9b. Acceptance criteria — what "done" means

1. `m14_sweep.py … --things` median **< 15,000,000** **on the agreed map**, with min / mean / p90 /
   worst and the `<15M` share quoted alongside.
2. `m14_gate.py 10 --things` **PASS** — byte-exact ×4, cold-vs-warm identical pixels, 10/10 relayed
   tics, both vacuity controls non-zero.
3. `m14_gate.py 10 --things --collide` **PASS** — never gated once in this campaign (§14.4).
4. `pytest tests/host -q --deselect …test_build_wall_renderer_e1m1_flat` → **242 passed**.
5. `cr/emit_hash_vs_head.py` → **14/14 identical**, shipped binary provably untouched — *unless* a
   Phase-2 lever deliberately changes it, in which case re-certify instead.
6. The `--cold` sweep reported, so level-load cost is visible.
7. **The measured fps**, not just the op count — this campaign exists for the frame rate (§0).
8. Any fidelity option from §7 that was taken is named explicitly in the commit and the report.

⚠ **The median is the target; the TAIL is not covered by it.** Worst is 71.67M today. A 15M median
can coexist with 40M+ spikes, which is visible hitching. Decide the tail requirement with the owner.

## 10. The instruments

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

## 11. ⚠ fj traps this campaign paid for — read before writing pointer or `rep` code

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

## 12. ⚠ Method traps — these cost more than the fj ones

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

## 13. ⚠ THE CR DEBT — owed, and explicitly deferred

**36 commits are unreviewed** — everything since `54da396` (the last CR, 2026-08-12): all of M14 plus
the reduction so far. The owner's instruction is the reduction first, **then** the CR. Do not close
this campaign without flagging that the CR is still outstanding, and note that Phase 2 will add to
the pile.

M14 is well *gated*, which is not the same as reviewed: gates prove the mirrors agree, CR catches
what a passing gate is happy to ship. This milestone's own history — a budget that bound and smudged
pixels, two vacuous controls, three pointer defects, a stale-baseline non-control — is the argument
for actually doing it.

## 14. ⚠ Known gaps in THIS PLAN

**14.1 Phase 2 has no plan, only a lever list.** §6. Everything that decides whether 15M is reachable
lives there, and it is the least-specified part of this document. The fresh decomposition (§9 step 3)
is the first real task of the campaign.

**14.2 Phase 1's arithmetic never closed even for 26M.** Best case leaves M14 at ~4.1M; a 15M budget
wants ~1M. Three of four levers rest on unmeasured numbers (§5). Assume Phase 1 delivers less than
its headline.

**14.3 Only two numbers in the whole cost model are directly measured** — `thing_load`'s per-call
cost and the sweep medians. `~117 loaded things`, the `bind_things` warm figure and §4b's 2.2M are
derived, estimated and extrapolated respectively.

**14.4 `--collide` has never been gated in this campaign.** Every lever touches `bind_things`,
`thing_pass` or `subsector_action`, and collision rides the same binary. `m14_bin_coll.fjm` does not
currently exist, and **`m14_bin.fjm` is STALE** — built 04:20, the §4b fix landed 04:49. Delete it
rather than baseline against it.

**14.5 The map question may invalidate parts of this document.** §1. If the target moves to lite,
every absolute number here (36.68M, 22.94M, 13.74M, the per-component split) must be re-measured —
they are all stock. The *structure* of the plan survives; the numbers do not.

**14.6 No lever targets the TAIL.** Worst is 71.67M. §9b.

**14.7 The oracle should not change, and if a lever needs it to, stop.** Every Phase-1 lever is
fj-side. Phase 2 fidelity options are different — those change *both* mirrors deliberately and in
the same commit, which is the normal contract, not an exception to it.

**14.8 Nothing here re-blesses the certified artefacts.** `deg_gate.py`'s header still carries
pre-M14-a op counts and no new certified binary hash has been published since `b_272d37507ca58434`.
Part of closing the campaign, not in any lever.

**14.9 fps is quoted from a memory, not measured this session.** The 96–127M ops/s figure comes from
the `e1m1-15m-campaign` memory. §9b.7 requires measuring the real thing before declaring the goal
met — an op count is a proxy for the deliverable, not the deliverable.
