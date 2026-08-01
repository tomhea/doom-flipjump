# Frame-cost experiments — what worked, what didn't, and why

One row per experiment. **A result only counts if the frame is byte-exact** (or the deviation is
named and accepted); a number from a build that changed the picture is not a number. Prices are
E1M1, lines tier WPX+FT1+plane_near, at the three gate viewpoints unless stated.

Method rules this repo has already paid for:
* **price a kernel by ADDING it**, never by stubbing it — a stub prices itself plus everything
  downstream (`fj-cost-model`, the `noproj` retraction);
* **divide measured totals by MEASURED counts**, never modelled ones;
* at ~40M characters of program, **a ±1M frame delta is layout noise**, not signal (V4-A's spawn
  came out 856k "cheaper" purely from the bank growing the program).

---

## Baseline (start of the campaign)

| build | spawn | courtyard | tree | worst (-309,-44) |
|---|---:|---:|---:|---:|
| V1+V2 | 23,536,484 | 20,134,978 | — | 26,405,793 |
| +V3 step faces | 26,545,502 | 27,604,046 | — | 32,137,393 |
| +V4-A record half | 25,689,298 | 28,722,844 | 25,058,919 | 36,992,405 |

Owner's band: 30–35M on the worst frame is acceptable, 25–30M hoped for on a typical one.
**The worst viewpoint is the problem.**

Where the frame goes (ablation, `fj-cost-model`, pre-V3/V4):

| component | spawn | worst |
|---|---:|---:|
| BSP walk skeleton + per-seg xorby + startup/present | 3.88M | 3.91M |
| the wedge cull | 2.02M | 2.11M |
| all `point_to_angle` (post-ATANDISP) | ~1.70M | ~2.00M |
| WPX wall texture detail (vs a flat wall) | 2.86M | 1.69M |
| ceiling/floor band emit | 1.58M | 1.67M |
| residue: per-column loop, occlusion prescan, emit framing | 5.47M | 13.84M |

**The biggest single named item is two `hex.fixed_div 8,4` per pass-2 seg inside
`proj.wall_scale_setup_m` — 2.16M spawn / 3.93M worst.** `hex.fixed_div 8,4` is 38,500 ops, the
dearest primitive in the table.

---

## Experiment log

_(entries appended below as they are run)_

### V4 STATUS at the start of the campaign (2026-07-31)

`things=True` **renders**, and is **BYTE-EXACT at spawn and at the courtyard**. Two viewpoints still
differ: the tree (1,930 px / 95 columns) and the worst sweep point (35 px / 9 columns). The stream
itself is clean everywhere — 160/160 columns decoded, **zero** structural anomalies — so this is a
content/selection mismatch, not a malformed frame.

Six real bugs were found getting here, and five of them are the SAME class — **a value used at the
wrong width or the wrong scale**. Worth having in front of you before writing more fj:

| bug | symptom | why |
|---|---|---|
| `projection*0x10000` | frame differed by EXACTLY its sprite pixels | `proj` already carries the `<<16`; the second shift truncated xscale to 0, so every thing failed projection |
| `hex.add 8, dst, <hex.vec 2>` (x3) | ditto | an 8-nibble add reads EIGHT nibbles of its source, dragging the neighbouring registers in as high nibbles |
| block index shifted twice | ditto | the record stored `blk*32` into a 4-nibble slot (overflow) and the emit shifted again |
| `blkstride/8-1` for a ×32 shift | garbage pairs | ×32 needs 5 bit-shifts, not 3 |
| `hex.add w/4, ptr, sbase` on a SLOT offset | a creeping cycle of pairs through the whole bank | a slot offset must be scaled by `dw` to become an address — use `ptr_index`, which does it |
| missing `byte.emit y2r` | frame ended early / IndexError | a pair is TWO bytes; emitting only the colour desynchronises the stream |

**The tool that found them was not another build.** `scratchpad/v4_check.py` now caches the
assembled `.fjm` keyed on a hash of the sources, and `--trace` decodes the 0x0B stream and reports
the first structural anomaly. Diagnosis went from ~10 minutes per hypothesis to seconds.

**RESOLVED — V4 is now BYTE-EXACT at all four viewpoints.** The seventh bug was the same shape as
the sixth: fj's BSP walk drops subtrees with no one-sided seg **twice over** — `_lines_prune` at
compile time and `_lines_plane_gate`'s `tsstop` node gate at RUNTIME. Making a thing-carrying leaf
count as live for the compile-time prune alone changed nothing, because the runtime gate was still
skipping the node; the sprites in E1M1's open, purely two-sided courtyard were never projected.
Both predicates now treat a thing-carrying leaf as live.

**Any pruning a feature does not know about is a feature that silently does not run.** That is the
general form, and it will bite the next per-subsector feature too.

---

## EXP-1 — `slopediv_recip`: `read_table_packed 3` → D4 dispatch ✅ **KEEP**

The dispatch lever's **fourth** application (after tantoangle, slopediv_recip8 and xtoviewangle).
`proj.scale_recip_div` opened with a `read_table_packed 3` (~247@ = 3 × `read_byte_and_inc` plus a
`mul_const`); it runs twice per pass-2 seg, twice per step-face seg and once per projected thing.
Threaded as a COMPILE-TIME `disp` flag so the non-lines tiers, which have no `srdisp` table, keep
the packed read.

| viewpoint | before | after | delta |
|---|---:|---:|---:|
| spawn | 28,104,383 | 28,026,843 | **−77,540** |
| courtyard | 36,010,624 | 34,662,751 | **−1,347,873** |
| tree | 45,252,666 | 43,458,960 | **−1,793,706** |
| worst | 39,448,264 | 38,468,873 | **−979,391** |

**BYTE-EXACT at all four.** Cost: +1.06M characters of program (41.70M → 42.76M).

The spawn delta is small because spawn has few pass-2 segs and no visible things; the lever scales
with the number of *projections*, which is exactly what a sprite-heavy frame has most of. That makes
it worth more, not less, once enemies are in.

## EXP-1a — attribution: what V4 actually costs (`--nothings` build) 📏

Building the same tree with `things=False` gives V4's price at every viewpoint cleanly (both frames
byte-exact, so neither number is contaminated):

| viewpoint | V3 only | V3+V4 | **V4 costs** |
|---|---:|---:|---:|
| spawn | 25,896,401 | 28,026,843 | +2.13M |
| courtyard | 27,112,631 | 34,662,751 | +7.55M |
| **tree** | **17,917,814** | **43,458,960** | **+25.54M** |
| worst | 31,389,542 | 38,468,873 | +7.08M |

**The tree viewpoint is the whole problem** — a cheap 17.9M frame becomes 43.5M once 24 large,
near billboards are projected and recorded. That is also the frame most like a future firefight, so
it is the right one to optimise against.

`scratchpad/v4_check.py --nothings` builds and gates the no-things tier; both binaries stay in the
cache, so the pair can be re-measured for free after any change.

## EXP-2 — reject before the divide, and test the cheaper flag first ✅ **KEEP**

Two independent reorderings, both **free** (they change no result, only when work happens):

1. `proj.project_thing` ran DOOM's `|tx| > tz<<2` off-screen reject AFTER `FixedDiv(projection, tz)`.
   The test needs only `tz` and `tx`, and rejects exactly the same set either way — so moving it
   BEFORE the divide costs nothing and saves a `hex.fixed_div 8,4` (**38,500 ops**, the dearest
   primitive in the table) for every thing that is off-screen. At a viewpoint where the budget binds,
   most things reached are off-screen.
2. The record loop read `drawn[x]` then `sprflag[x]`. The conjunction is symmetric, so reading the
   SPRITE flag first means a column a nearer thing already claimed costs one byte read, not two.

| viewpoint | before | after | delta |
|---|---:|---:|---:|
| spawn | 28,026,843 | 28,051,295 | +24,452 (noise) |
| courtyard | 34,662,751 | 34,333,993 | **−328,758** |
| tree | 43,458,960 | 40,714,308 | **−2,744,652** |
| worst | 38,468,873 | 38,030,062 | **−438,811** |

**BYTE-EXACT at all four.** Zero added program text.

The lesson generalises past this kernel: **an early-out is worth what it skips, so it belongs as
early as its inputs allow — not where the reference implementation happens to put it.** DOOM does
the divide first because on a 486 the divide was not 38,500× a compare.

## EXP-2a — where V4's cost sits: RECORD vs EMIT (`--reconly` build) 📏

New ablate `sprnoemit` keeps the record half and never reads the fragments back. The frame is then
identical to a things=False build — byte-exact — so the delta prices the record half ALONE, by
subtraction from a correct frame rather than by stubbing something the rest of the frame depends on.

| viewpoint | no things | record only | full | **record** | **emit** |
|---|---:|---:|---:|---:|---:|
| spawn | 25,896,401 | 27,375,283 | 28,051,295 | +1.48M | +0.68M |
| courtyard | 27,112,631 | 31,414,759 | 34,333,993 | +4.30M | +2.92M |
| **tree** | 17,917,814 | 32,606,272 | 40,714,308 | **+14.69M** | **+8.11M** |
| worst | 31,389,542 | 36,582,246 | 38,030,062 | +5.19M | +1.45M |

The record half is roughly twice the emit half everywhere. That is where to spend.

## EXP-3 — two record/emit micro-levers: one wins, one LOSES ❌ **half reverted**

Bundled two byte-exact changes and measured **+420k at the tree** — a regression. Splitting them:

| variant | tree | vs EXP-2 |
|---|---:|---:|
| EXP-2 (baseline) | 40,714,308 | — |
| hoist + empty-fragment fast path | 41,133,941 | +419,633 ❌ |
| **hoist alone** | **40,594,163** | **−120,145** ✅ |

* **KEPT — hoist the per-thing block base out of the column loop.** `blk = (sp_base + bucket) + u*BUCKETS`,
  and `(sp_base + bucket)` is constant per thing. −120k tree, −50k courtyard, 0 at spawn.
* **REVERTED — a one-region fast path for EMPTY fragments** (a billboard that projects entirely off
  the view still takes the sprite path, because it must suppress the column's step faces, but has
  no runs to walk). Cost **+540k at the tree**. Two reasons, both worth remembering: empty fragments
  turned out to be RARE, so the added compare was nearly pure overhead; and `emit_region(0, VIEW_H)`
  is not cheaper than `emit_region(0, sy1)` + `emit_region(sy1, VIEW_H)` — the split version's
  pieces each exit early against a narrow window, while the single wide region walks everything.

**A "fast path" for a case you have not counted is a slow path.** The empty-fragment population was
assumed, never measured; the measurement would have cost one Python probe against the cached binary.

## EXP-3a — where the RECORD half's 14.7M goes (`thingtwice` doubling) 📏

New ablate `thingtwice` runs `proj.project_thing` a SECOND time with the same operands into dead
registers. The frame stays byte-exact, so the delta is that kernel alone.

| viewpoint | baseline | doubled | **all projections cost** |
|---|---:|---:|---:|
| spawn | 28,051,295 | 28,168,607 | +0.12M |
| courtyard | 34,284,050 | 37,176,207 | +2.89M |
| **tree** | 40,594,163 | 52,527,377 | **+11.93M** |
| worst | 38,025,214 | 42,149,824 | +4.12M |

**81% of the record half is the projection itself**, not the per-column store. Every thing in the
level gets projected at an open viewpoint — the BSP bounds *which subsectors* are visited, not how
many things they hold — so the per-thing cost is what matters, and there are 250 of them.

## EXP-4 — the two dearest lines in `project_thing` ✅ **KEEP**

1. **ROW RULE, operand order.** `fixed_mul_lo` runs one schoolbook row per nonzero nibble of the
   SECOND operand. All four multiplies had a dense 16.16 finesine value there and `tr_x`/`tr_y` —
   differences of `(map unit << 16)`, so their low FOUR nibbles are always zero — as the first.
   Swapped. Commutative, same low product: **bit-identical**.
2. **`hex.fixed_div 8,4` → the shared block-FP reciprocal** (`proj.scale_recip_div`). 38,500 ops
   against ~12k, for every thing that survives the FOV reject. NOT bit-identical, so the ORACLE
   takes the same path — the same re-bless the wall scale took at M13-scalerecip, not something fj
   invented on its own.

| viewpoint | before | after | delta |
|---|---:|---:|---:|
| spawn | 28,051,295 | 27,836,730 | −214,565 |
| courtyard | 34,284,050 | 33,899,355 | −384,695 |
| **tree** | 40,594,163 | **38,476,150** | **−2,118,013** |
| worst | 38,025,214 | 37,099,879 | −925,335 |

**BYTE-EXACT at all four** (the tree's oracle hash moves with the re-bless, and fj matches it).

### Campaign so far

| | spawn | courtyard | tree | worst |
|---|---:|---:|---:|---:|
| V4 complete | 28,104,383 | 36,010,624 | 45,252,666 | 39,448,264 |
| **after EXP-1..4** | **27,836,730** | **33,899,355** | **38,476,150** | **37,099,879** |
| | −0.27M | −2.11M | **−6.78M** | −2.35M |

## EXP-5 — cache sin/cos of the VIEW angle across things ✅ **KEEP** (and one idea that cannot work)

`project_thing` re-derived `finesine[viewangle>>20]` and its cosine on every call, though the view
angle is constant for the frame and the leaf runs once per THING. A macro's locals are program
statics, so the cache is a 1-nibble flag and nothing else.

| viewpoint | before | after | delta |
|---|---:|---:|---:|
| spawn | 27,836,730 | 27,823,804 | −12,926 |
| courtyard | 33,899,355 | 33,859,325 | −40,030 |
| tree | 38,476,150 | **37,933,652** | **−542,498** |
| worst | 37,099,879 | 37,003,252 | −96,627 |

**BYTE-EXACT at all four.** Predicted −2.1M, delivered −0.54M: a `finesine` lookup with
`result_nibbles=8` is NOT eight independent dispatches — `per_result_nibble` mode shares most of the
walk. Worth recording, because the same wrong model would over-value every other wide-result table.

### ❌ Bundled with it and REVERTED: constant vectors instead of per-call `hex.set`

`project_thing` did six `hex.set 8, c*, <compile-time expr>` per call (~250 ops each). Replacing them
with initialised declarations — `cminz: hex.vec 8, minz` — **does not assemble**: the assembler does
not count a `hex.vec` INITIALISER as a use of a macro parameter, so `minz`, `projection`, `centerx`,
`centery`, `vieww` and `viewh` all became "unused labels", which is a hard error.

**`hex.vec n, <expr>` cannot carry a macro parameter.** To hoist a parameter-derived constant out of
a hot macro it has to be passed in already-materialised, or set once behind a flag like the sin/cos
cache above.

## EXP-6 — per-column fragment slot as HEX CELLS instead of packed bytes ❌ **REVERTED**

The record half writes six bytes per fragment and the emit reads them back. `write_byte` is 41@ and
`write_hex` is `w(0.75@+5)+20@+39`, so one hex cell — eight nibbles, four bytes' worth — costs about
what 1.3 byte writes do. Two cells should replace six byte writes and six byte reads.

**It does not render.** The tree lost every sprite pixel again (2,013 px, the exact sprite count) and
picked up 11 non-monotone pairs. The layouts look self-consistent on paper — 16 slots per column,
two 8-slot cells, the same index arithmetic on both sides — so the mismatch is somewhere in how a
packed-BYTE array (one dw slot holds a whole byte) and a hex cell (one dw slot holds one NIBBLE)
share an address space, and it was not worth more build cycles for a lever worth ~1M.

Reverted; the EXP-5 binary was still in the cache, so re-verifying the revert took seconds.

**If it is retried:** prove the storage model in Python first, the way `scratchpad/v3_slotmodel.py`
did for V3 — write a cell, read it back through the same address arithmetic, and check the bytes,
before spending a build.

---

## Campaign summary

| | spawn | courtyard | tree | worst |
|---|---:|---:|---:|---:|
| V4 complete (start) | 28,104,383 | 36,010,624 | 45,252,666 | 39,448,264 |
| after EXP-1..5 | 27,823,804 | 33,859,325 | 37,933,652 | 37,003,252 |
| **after EXP-7 + EXP-8 (shipped)** | **27,631,269** | **33,820,592** | **31,826,978** | **35,216,185** |
| | −0.47M | −2.19M | **−13.43M (−30%)** | **−4.23M (−11%)** |

Every step byte-exact. Six experiments kept, two reverted, and both reverts are written up above
because the reasons generalise. Only EXP-8 changes the picture (41 px at the tree, 19 at the worst
point, 0 elsewhere) and it is the one the owner signed off on.

### What is left, ranked by measured upside

1. **`project_thing`, still ~9M at the tree.** Every one of E1M1's 250 things is projected at an
   open viewpoint — the BSP bounds which subsectors are visited, not how many things they hold. A
   conservative reject cheaper than the four multiplies is the biggest single lever left. ⚠ The
   obvious ones do NOT work: a distance bound can only ACCEPT (tz is not bounded below by the
   distance), and the seg path's `wedge_reject` is not conservative for a sprite, which has width
   the centre point does not know about.
2. **The emit half, 8.1M at the tree.** A fragmented column walks the ceiling list, the wall
   run-list and the floor list TWICE — once per region. Walking each list once and emitting around
   the sprite is a real restructure, but it is where the emit's cost is.
3. ~~**`THING_BUDGET`.**~~ **DONE — 16, see EXP-8 below.**
4. **V3's step faces, +5.7M at the worst viewpoint**, have had no optimisation pass at all. With the
   budget applied this is the largest single item at the frame that is still at the band's edge.

## EXP-7 — an EXACT far-thing reject, before the lateral multiplies ✅ **KEEP**

`h = wph * PROJECTION / tz`, so `tz > (wph * PROJECTION) << 16` forces `h == 0` — which
`project_thing` already rejects, but only after two more multiplies and a reciprocal. Baking that
threshold per thing (`sp_tzmax`) moves the reject to immediately after `tz`.

**Verified before building**, exhaustively against `_scale_recip_div` over every sprite height and a
sweep of `tz`: zero violations, and the boundary is exact — no safety margin needed. So the frame
cannot change, and it did not.

Counted (of 250 things): the new test rejects **76 at spawn, 12 at the courtyard, 30 at the tree,
68 at the worst point**, each saving ~20k ops.

| viewpoint | before | after | delta |
|---|---:|---:|---:|
| spawn | 27,823,804 | 27,631,269 | **−192,535** |
| courtyard | 33,859,325 | 33,820,592 | −38,733 |
| tree | 37,933,652 | **37,224,868** | **−708,784** |
| worst | 37,003,252 | **36,433,309** | **−569,943** |

**BYTE-EXACT at all four**, and `tests/fj/test_lines_render.py` 11/11 +
`tests/fj/test_projection_kernels.py` 16/16 green on the tree this landed on.

This is the same shape as EXP-2's reordering and the generalisation is worth stating plainly:
**a rejection test belongs as early as its inputs allow, and the cheapest exact one you can derive
is usually not the one the reference implementation uses.** DOOM rejects on height at the very end
because on a 486 nothing in that chain cost 20,000 times a compare.

## EXP-8 — the `THING_BUDGET` cost curve 📏 **measured → APPLIED (16), 2026-08-01**

The straight knob. Both builds byte-exact against their own oracle.

| viewpoint | budget 24 | budget 16 | delta |
|---|---:|---:|---:|
| spawn | 27,631,269 | 27,631,269 | 0 |
| courtyard | 33,820,592 | 33,820,592 | 0 |
| **tree** | 37,224,868 | **31,826,978** | **−5,397,890** |
| **worst** | 36,433,309 | **35,216,185** | **−1,217,124** |

Two things fall out of this, and the first is more useful than the second:

* **The budget does not bind at spawn or the courtyard at all** — those viewpoints have fewer than 16
  projectable things, so the two builds are identical to the op. It only costs where it earns.
* At 16, **both sprite-heavy viewpoints land inside the owner's 30–35M band** (31.8M and 35.2M),
  against 37.2M / 36.4M at 24.

### What it actually costs in PICTURE (`scratchpad/thing_budget_demo.py`, oracle-side, seconds)

⚠ My first write-up of this said the budget "drops the eight furthest things at a crowded
viewpoint", which counted right and implied wrong. Rendered:

| viewpoint | things projectable | budget 24 | budget 16 | budget 8 |
|---|---:|---|---|---|
| spawn | 0 | — | — | — |
| courtyard | 12 | 0 px | 0 px | 122 px |
| tree | 30 | **0 px** | 41 px | 421 px |
| worst | 51 | 85 px | 104 px | 141 px |

(px = pixels differing from the unbounded frame, out of 16,000.)

* **At the courtyard and spawn the budget never binds** — 12 and 0 projectable things.
* **At the tree, 24 is already LOSSLESS.** Thirty things project; the six the budget turns away are
  behind geometry or off-screen and change nothing. Dropping to 16 costs **41 pixels — 0.26% of the
  frame — for −5.4M ops.**
* **At the worst viewpoint the shipped 24 already costs 85 px** (51 project, 24 get in). Going to 16
  costs 19 pixels more and −1.2M ops.

**So the honest recommendation is 16, not 24.** The trade at the tree is 41 pixels against 5.4M ops,
and at the worst viewpoint 19 pixels against 1.2M — and 16 is what puts both frames inside the
owner's 30–35M band. Still the owner's call, because it is a picture change, but the earlier framing
("this is the lever that costs picture") overstated it: what the budget drops are, almost entirely,
things that were never visible.

### EXP-8a — ⚠ the budget's real cost is not pixels, it is WHICH things (`scratchpad/thing_census.py`)

EXP-8 priced the budget in pixels (41 at the tree, 19 at the worst point) and concluded the trade was
cheap. **Pixels are the wrong metric**, and the census says so. It instruments the real render —
`project_thing` wrapped, budget lifted — so the log is exactly the ordered list of things the frame
considered under the REAL stop conditions. (A standalone replay of the selection loop over-counts
wildly: the loop's other stop, `n_claimed == VIEW_W`, usually fires FIRST. At spawn it stops the walk
after 5 things, which is why the budget costs literally nothing there.)

| viewpoint | reached | project | budget 16 turns away |
|---|---:|---:|---|
| spawn | 5 | 0 | nothing |
| courtyard | 21 | 12 | nothing |
| tree | 193 | 30 | 14 — 5 of them MONSTERS |
| worst | 90 | 51 | **35 — 24 of them MONSTERS** |

**And the order slots are handed out in is NOT distance order.** Budget slots go in walk-arrival
order = BSP front-to-back BY SUBSECTOR, and a thing sits anywhere inside its subsector, so arrival
is not monotone in distance to the thing. Measured at the worst viewpoint:

```
slot  euclid  h px  type          slot  euclid  h px  type
   1    1238     1  BON2            42     204     8  BON1   <- the NEAREST thing in the frame
   4     937     1  BON1            46    1066     4  POSS
   6     900     1  BON1            48    1195     4  TROO
  16    1349     1  ROCK            51    1228     4  POSS
```

Six ONE-PIXEL bonus dots hold slots 1-6. Dropped: 24 monsters — four of them 4 px tall at ~1100
units — and the nearest object in the whole frame, an 8 px pickup at 204 units, which arrives at
slot 42. So the budget is not "drops the furthest things"; it is "drops whatever the BSP happens to
reach late", and that includes large near ones.

The pixel count stays small because the dropped monsters are mostly 1-2 px. That is precisely why
the metric misleads: **a monster that vanishes costs 2 pixels and all of the gameplay.**

Also found: E1M1 carries 292 things (53 monsters / 120 pickups / 107 decor / 12 starts). V4 can draw
250 of them — including 52 of the 53 monsters. **Type 58 (spectre) has no `THING_SPRITE` entry and
is never drawn at any budget**, which is a gap independent of this knob.

### Where that points (cheapest first, none of it built yet)

1. **A minimum-SIZE reject.** EXP-7 bakes `sp_tzmax = wph * PROJECTION` — past that depth the sprite
   projects to zero rows, tested before the two lateral multiplies and the reciprocal.
   `wph * PROJECTION / 2` is the IDENTICAL test for "fewer than 2 rows": one baked constant, one
   compare, no new code shape, exhaustively verifiable in Python the way EXP-7's was. At the worst
   viewpoint it clears ~13 of the 16 things now holding slots — it makes the frame CHEAPER and the
   selection BETTER at the same time. Changes the picture (1 px sprites disappear), so it is the
   owner's call.
2. **Category-aware slots.** Thing type is compile-time known, so reserve part of the budget for
   monsters: a second counter and one compare in `frame.thing_record_body`.
3. Then the structural items — the resumable emit walker, the tighter screen reject.

### APPLIED — the owner took 16 (2026-08-01)

`reference_model.THING_BUDGET = 16`. One constant: the oracle reads the module global and the fj
emit passes the same value to `frame.thing_record_body`, so there is nothing to keep in step.
Re-gated on a fresh build (`scratchpad/v4_check.py --emit`, cache miss, 441 s assemble) — the ops
reproduce EXP-8's measurement **to the op**, and all four viewpoints are **BYTE-EXACT** against the
budget-16 oracle:

| viewpoint | shipped ops | vs budget 24 |
|---|---:|---:|
| spawn | 27,631,269 | 0 |
| courtyard | 33,820,592 | 0 |
| tree | **31,826,978** | −5,397,890 |
| worst | **35,216,185** | −1,217,124 |

The worst frame sits at the very top of the 30–35M band, so it is the one still worth spending on;
the tree now has ~3M of headroom it did not have.


---

## EXP-9 — the 15M campaign: where the frame ACTUALLY is, and why knobs cannot get there 📏

Target: every viewpoint under **15M ops/frame** (owner, 2026-08-01 — "they will notice a slow game").
Starting point after the V4 selection policy: 27.8M spawn / 33.7M courtyard / 34.5M tree / 39.2M worst.

### The measurement that ended the search: cost is nearly RESOLUTION-INDEPENDENT

`Config` is fully W/H-derived, so a smaller viewport is a one-line experiment and the oracle follows.
Built and ran at 96x60 (36% of the pixels):

| viewpoint | 160x100 | 96x60 | fitted `ops = FIXED + k*pixels` |
|---|---:|---:|---|
| spawn | 27,772,447 | 21,837,506 | **FIXED ~18.5M**, k ~579/px |
| worst | 39,156,918 | 31,606,532 | **FIXED ~27.4M**, k ~737/px |

**Cutting 64% of the pixels bought 21%.** ~27M of the worst frame does not care how many pixels
there are, so **no resolution short of absurd reaches 15M** — a 1x1 frame would still cost ~27M.
That single build retired the whole "make the viewport smaller" family.

⚠ It also surfaced a real bug: at 96x60 (TEXTURE_DOWNSCALE=3) spawn is byte-exact but the other
three viewpoints DIFFER. Something in the lines renderer does not follow `cfg` at odd downscales.
Not chased — the tier is not wanted — but it is a genuine latent defect at any non-2 downscale.

### Where the fixed cost is

~150 segs survive the cull per frame and each pays `wall_setup` + `wall_scale_setup` at roughly
**190k ops** (`scratchpad/bboxcull_probe2.py`'s stage accounting). 150 x 190k ~ 28M — that IS the
fixed cost. The walk itself visits all 2057 segs at every viewpoint, but a seg past the `full` flag
costs only a test, so the walk skeleton is minor next to the per-seg setup.

The dearest primitive lever is already spent: `hex.fixed_div 8,4` (38,500 ops) is GONE from the wall
scale path (M13-scalerecip); the only two left in `projection.fj` are inside slope_div/point_to_dist.

### Knobs, measured (all byte-exact)

| tier | spawn | courtyard | tree | worst |
|---|---:|---:|---:|---:|
| shipped | 27,772,447 | 33,671,882 | 34,541,408 | 39,156,918 |
| PNEAR_SEG_BUDGET 64 + STEP_SEG_BUDGET 8 | 27,772,440 | **34,526,560** | 34,185,505 | 36,591,853 |

−2.57M on the worst frame, **+855k on the courtyard**, and ~750 px of floor-attribution damage there
(the "grey floor / yellow sides" bug partially returning). **NOT SHIPPED**: it spends picture on a
step that does not reach the target anyway. `PNEAR_SEG_BUDGET` below 64 is not available at all —
32 costs 7,587 px at spawn and 13,016 at the courtyard (`scratchpad/knob_probe.py`).

### Three levers killed by measurement, before any fj was written

* **Ditto columns** (collapse a column identical to its left neighbour): only **2-8%** of emitted
  pairs repeat once WPX per-pixel wall detail is on. `scratchpad/ditto_count.py`'s 58% was a
  different key on an older tier.
* **`WPX_RUN_CAP`**: costs 700-2,100 px at cap 8 and does not touch the dominant cost. ⚠ The first
  run of this probe reported "0 px at every cap" — `wpx_strip(..., cap=WPX_RUN_CAP)` is a KEYWORD
  DEFAULT, bound at def-time, so patching the module global changed nothing. Same class as the
  import-binding trap `scratchpad/bench.py` documents. **Patch `__kwdefaults__`, or trust nothing.**
* **V1 grain**: turning it OFF *increases* run count 2-7%. It is not the stream driver.

### What would actually reach 15M

Only a **per-seg pipeline re-architecture** — the ~190k setup paid ~150 times. Everything else is
noise against it. Ranked, with honest uncertainty:

1. **Halve the per-seg setup.** No single primitive is left to swap; this is a restructure of
   `wall_setup`/`wall_scale_setup`, most likely by hoisting per-SUBSECTOR invariants out of the
   per-seg path. Upside if it lands: ~14M off the worst frame. This is the only lever of the
   required size.
2. **Cull segs before the setup, not after.** ~150 reach it; DOOM's solidsegs would reject more.
   `scratchpad/cull_levers.py` measured node-AABB culling at ~35% of the population.
3. Resolution + knobs on top: ~7.5M + ~2.5M, both with picture cost, both only worth spending once
   (1) has landed and the fixed cost is no longer the whole frame.

**Not attempted deliberately**: reaching 15M by deleting features. Dropping V3 step faces (-5.7M)
makes stairs invisible, and dropping sprites makes monsters invisible — the owner asked for a fast
game that is still fun, and those two are the fun.


## EXP-10 — ⚠ EXP-9's headline lever was WRONG. `wall_scale_setup_m` is 10%, not 50%

Priced by DOUBLING it into dead registers (ablate `scaletwice`), the repo's own rule — never by
stubbing:

| viewpoint | shipped | doubled | **the kernel costs** | share of frame |
|---|---:|---:|---:|---:|
| spawn | 27,772,549 | 29,760,446 | **1.99M** | 7% |
| courtyard | 33,672,272 | 36,472,088 | **2.80M** | 8% |
| tree | 36,649,307 | 39,755,245 | **3.11M** | 8% |
| worst | 39,158,568 | 43,219,006 | **4.06M** | **10%** |

**~28k per seg, not ~190k.** EXP-9 said "the only lever of the required size is halving the per-seg
`wall_setup` + `wall_scale_setup`, ~190k ops paid ~150 times" and put its upside at ~14M. **That is
false.** Halving this kernel is worth ~2M at the worst viewpoint.

**Where the 190k came from, and why it was wrong to use:** `scratchpad/bboxcull_probe2.py`, a host
probe written for the PRE-optimisation framebuffer raster tier. It was never re-measured after
M13-scalerecip replaced the signed `fixed_div` (38.5k) with the block-FP reciprocal (~19k), after
the M13-mulorder operand swap, or after the move to the lines tier. A stale model number was quoted
as a measurement — the exact failure this file's own method rules exist to prevent:
**divide measured totals by MEASURED counts, never modelled ones.**

### Corrected accounting of the 39.16M worst frame

| component | cost | how known |
|---|---:|---|
| V4 things | 7.02M | subtraction vs the V3 tier |
| V3 step faces | ~5.7M | earlier ablation |
| `wall_scale_setup_m` | 4.06M | **EXP-10, doubling** |
| BSP walk skeleton + per-seg xorby | ~3.9M | earlier ablation |
| wedge cull | ~2.1M | earlier ablation |
| all `point_to_angle` | ~2.0M | earlier ablation |
| **UNACCOUNTED** | **~14.4M** | — |

**The ~14.4M residue is now the only place a large win can live**, and it is NOT the scale setup and
NOT resolution-dependent (EXP-9: ~27.4M of this frame is fixed against pixel count). The candidates,
untested: `wall_setup` proper, the occlusion pre-scan, the per-seg column-store loop, and the
`plane_near` marking-seg attribution — the last is worth ~5M by inference from the PNEAR 128→64 knob
(−2.57M for half the budget).

**Next session starts by bisecting that 14.4M**, with the `scaletwice`/`noprescan`/`projtwice`
ablates that already exist and `scratchpad/bench.py`. Do NOT start by optimising the scale setup.

### The seg-shape fact worth carrying

~150 segs pay setup per frame and their mean screen width is **3.9–4.7 columns** (0% are a single
column, 39% are ≤2 at the worst viewpoint). So the per-seg fixed cost is amortised over almost
nothing — roughly one net claimed column each, on a 160-column frame. Any real win has to reduce the
NUMBER of setup-paying segs, not the price of one. (A checked-and-rejected micro-lever: skipping the
second `scale_from_global_angle` when x1 == x2 is worth exactly zero — no seg is one column wide.)


## EXP-11 — the 15M target is ARITHMETICALLY out of reach under the stated constraints

Constraints (owner, 2026-08-01): keep 160x100, keep all four visual features, no thing count limit.
Under those, add up only the components that have been MEASURED, and stop:

| component | cost | how measured |
|---|---:|---|
| V4 things (every monster drawn) | **7.02M** | subtraction vs the V3 tier |
| `wall_scale_setup_m` | **4.06M** | EXP-10, doubling |
| BSP walk skeleton + per-seg xorby | ~3.9M | ablation |
| **subtotal** | **~15.0M** | **= the target, with NOTHING drawn** |
| + wedge cull | ~2.1M | ablation |
| + all `point_to_angle` | ~2.0M | ablation |
| + V3 step faces | ~5.7M | ablation |
| **floor before a single pixel is emitted** | **~24.8M** | |

The ~14.4M residue EXP-10 identified is on TOP of that. So even a residue of exactly zero — a
perfect emit, a free occlusion pre-scan, free plane attribution — lands at ~24.8M, **65% over
target**. No lever inside the residue can close it, which is why the search stopped here rather than
bisecting further: the bisection can only reallocate the 14.4M, never the 24.8M underneath it.

### What would have to give, in the owner's own terms

* **The monsters.** V4 is 7.02M and it is the single largest measured component. Every monster drawn
  is the explicit requirement, so this is the constraint most expensive to hold — and the one the
  owner most clearly wants held.
* **The step faces.** ~5.7M, and without them stairs are invisible — a playability loss, not a
  cosmetic one.
* **The algorithm.** ~150 segs pay a fixed setup to fill ~1 net column each (EXP-10). A renderer
  whose per-frame cost scales with COLUMNS rather than SEGS would not have this floor at all. That
  is a different renderer, not an optimisation of this one.

**Nothing here says the frame cannot be made faster** — the 14.4M residue is real and unbisected,
and 39.2M -> ~30M looks reachable. It says 15M specifically is the wrong number to aim at while all
three constraints hold. Pick which constraint moves, and the target becomes a design question again.
