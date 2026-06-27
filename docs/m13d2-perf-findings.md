# M13d2 performance findings — the first real ops/frame measurement (R-1)

The textured floor/ceiling renderer is **byte-exact** (E1M1 spawn golden `db5d3da8`, square golden
`00de1aaa`, all viewpoints byte-exact vs the oracle). But the first real **ops/frame** measurement reveals
the renderer is **~83× slower** than the DESIGN §1 estimate. This file records the profiling data that the
perf-reduction phase works from.

## Headline numbers

| Quantity | Measured | DESIGN §1 target | Ratio |
| --- | --- | --- | --- |
| E1M1 spawn **ops/frame** | **1,165,180,455** (~1.165 B) | ~14 M | **~83× over** |
| **fps** (at 280 M fj/s) | **~0.24 fps** | ~20 fps | ~83× under |
| ops / screen pixel (16 000 px) | **~72,800** | ~700–1450 | ~50–100× over |

## What it is NOT (ruled out)

- **NOT @-at-scale.** @ ≈ 25–30 at this program scale (owner), not the ~50× that would explain it.
- **NOT table size.** `plane.draw_span` per-pixel cost is **identical** for a 4096-entry flat table
  (13,433 ops/px) and a 151,552-entry table (13,454 ops/px) — the `.lookup` is a computed jump, O(log size)
  in the index width only. The 198k-wall + 151k-flat combined tables are **not** the cost.
- **NOT a correctness/algorithm bug** — the frame is byte-exact.

## What it IS: the per-pixel nibble-op dispatch count

Every `hex` operation on an N-nibble register is N nibble-level truth-table dispatches (~4@ each). The
per-pixel path simply executes **too many nibble-ops**. Profiled `plane.draw_span` (isolated kernel,
histogram of the pure per-pixel loop = span12−span2 ÷ 10):

```
PURE PER-PIXEL = 13,446 ops/pixel
  80.9%  10,881/px  (shared hex truth-table dispatch: hex.tables.ret/res + wflips)  <- the nibble-op COUNT
   6.5%     869/px  hex.mul_const   <- y*VIEW_W recomputed PER PIXEL (8-nibble; y is span-constant!)
   3.6%     490/px  hex.add         <- xfrac+=xstep, yfrac+=ystep, pixp+=x (all 8-nibble)
   3.1%     421/px  hex.write_hex   <- the framebuffer store
   2.4%     326/px  hex.ptr_index   <- FB address recomputed from scratch PER PIXEL
   2.2%     292/px  hex.mov
   1.6%     220/px  hex.scmp
   0.6%      83/px  hex.shr_hex
   ... and ~0.3% each: flat.sample (36/px), cm.apply (33/px)  <- the table lookups are CHEAP
```

The 80.9% "shared dispatch" is not one macro — it is the dispatch every nibble-op routes through, i.e. the
cost is proportional to the **number of nibble-operations** the per-pixel body issues. The table samples
(`flat.sample`, `cm.apply`) are a rounding error (~0.6%).

### `plane.draw_span` per-SPAN setup is also huge

- Per-span setup ≈ **123,000 ops** (the DDA re-seed: yslope/distscale/xtoviewangle reads + finecos/finesin +
  several 8-nibble `fixed_mul`s).
- E1M1 spawn frame = **1,357 spans** ⇒ **~167 M ops in span setup alone** (≈ the whole DESIGN frame budget,
  just for re-seeding). Adjacent same-row spans of one visplane share `dist/xstep/ystep/zlight-row` (depend
  only on planeheight,y,light) — only `xfrac/yfrac` (the x1 length+angle seed) differ.

## Frame composition (E1M1 spawn)

- 10,381 plane (floor/ceiling) pixels · 5,619 wall pixels · 1,357 spans · 16,000 total.
- **MEASURED** (real renderer, below): FLOOR pass = **820 M (70.4%)**, walls + BSP walk = **345 M (29.6%)**.
- The floor 820 M ÷ 10,381 px = ~79 k ops per plane pixel-equivalent (per-pixel body + the per-span DDA
  re-seed amortized over 1,357 spans). Isolated-kernel rates (13.4 k/px, 123 k/span) UNDERESTIMATE — the full
  renderer's @ is larger; treat the isolated numbers as a lower bound on the optimization opportunity.

### Measured walls-vs-floors split (real renderer, plane pass on vs off — `scratchpad/split_e1m1.py`)

```
FULL (walls+floors): 1,165,180,455 ops
WALLS+WALK only:       344,792,345 ops  (29.6%)   <- the M12 wall renderer alone = ~0.81 fps
FLOOR pass (delta):    820,388,110 ops  (70.4%)   <- the textured visplane pass DOMINATES
```

**The FLOOR pass is 70% of the frame — the #1 target by a wide margin.** (My isolated-kernel estimate of
~306 M was 2.7× low: the full-renderer @ is larger AND the per-span setup is heavier at full scale.) 820 M
over 10,381 plane px + 1,357 spans ⇒ ~the per-pixel body and the per-span DDA re-seed in `plane.draw_span` /
`frame.render_planes_spans` are where the optimization effort pays off most. Walls (`leaf_body_w` + the
all-16,000-px pass-2 trampoline + the 575-seg walk) are the secondary 30%.

## Optimization targets (the perf-reduction phase works from these)

Ordered roughly by leverage. None change correctness (the byte-exact goldens stay the gate).

1. **Hoist span-constant work out of `plane.draw_span`'s per-pixel loop** (biggest, easy):
   - `pixp = y*VIEW_W` (`hex.mul_const 8`) is recomputed every pixel though `y` is constant per span →
     compute once in setup.
   - The FB write recomputes the full address every pixel (`zero/mov/shl/set fbptr/ptr_index`) → keep a
     **running FB pointer**, `+= 2*dw` per pixel (strength reduction). Removes mul_const 8 + most of ptr_index.
2. **Narrow the per-pixel registers** (the DESIGN §1.1.4 "precision ledger"): use 8.8 (4-nibble) instead of
   16.16 (8-nibble) for the `xfrac/yfrac` DDA + minimal widths for u/v/spot/x — halves the dominant `hex.add`
   / `hex.shr_hex` nibble counts. (The DESIGN already budgets the DDA at 8.8.)
3. **Cut the per-span setup (167 M):** hoist the row-and-visplane-shared `dist/xstep/ystep/zlight-row` so they
   are computed once per (row, visplane) rather than per span; only re-seed `xfrac/yfrac` per span. Keep the
   span BOUNDARIES identical (byte-exactness depends on them).
4. **Wall pass-2 overlap:** `pixel_tramp`+`compare_y` runs for all 16,000 pixels though only 5,619 are walls
   (the plane pass repaints the other 10,381). Restrict the wall pass to each column's `[top,bottom]`.
5. **Apply (1)+(2) to the WALL per-pixel path** (`frame.leaf_body_w`) too — it is the same kind of nibble-op
   pile and (per the split) the larger half of the frame.
6. **Algorithmic fidelity levers (DESIGN §2, if 1–5 don't reach playable):** 2×2-block textured floors
   (¼ the textured pixels), flat-colored floors (no u,v DDA), render-1-of-N tics, lower res. These trade look
   for fps and are the documented fallbacks.

## Perf-reduction phase — progress (Phase 1 [exact]; Phase 2 [re-bless], owner-approved)

| Rung | ops/frame | fps @280M | vs baseline | what |
| --- | --- | --- | --- | --- |
| baseline (textured) | 1,165,180,455 | 0.24 | — | M13d2c byte-exact |
| opt1 per-pixel | 1,093,029,378 | 0.26 | 1.07× | draw_span per-pixel: running fb pointer, direct-offset u/v extract, span-constant presets, 6-nib DDA, count-down loop (per-pixel 13.4k→4.2k ops, but per-pixel was only ~9% of the frame). +fix: clear stale `tt` before the x1 seed (register-lifetime bug at far spans, caught at E1M1 (-416,256)). |
| **opt2 walk unroll** | **645,575,343** | **0.43** | **1.81×** | `render_planes_spans` column scan UNROLLED (`rep(view_w,x) plane_col x`) → compile-time addresses, no `ptr_index`. WALK 312M→23M (13.3×); whole floor pass 540M→267M (2.0×). |
| Phase 1a `full` early-out | 580,447,590 | 0.48 | 2.01× | DESIGN Phase 1 step 1-2: count newly-claimed columns in `seg_pass1_leaf_body_mtlwp`; once all VIEW_W claimed set `full`, then later (farther) segs `fret` immediately (skip `wall_x_range` + projection + loop). Saved ~65M — far below the spec's est. (R1 materialized: the per-seg projection is NOT the geometry bulk, and the screen fills late at spawn). |
| **Phase 1b occlusion pre-scan** | **515,248,614** | **0.54** | **2.26×** | DESIGN Phase 1 step 3: after `wall_x_range` gives [x1,x2), scan `drawn[x1..x2)`; if ALL claimed, `fret` (skip projection) — catches fully-occluded segs processed BEFORE the screen fills. Another ~65M. **Phase 1 total: 645.6M→515.2M (1.25×), byte-exact.** |
| **Phase 2 bucketed floor** [re-bless] ⚠**TO REVERT** | **444,515,210** | **0.63** | **2.62×** | DESIGN Phase 2: the per-span u,v DDA seed (5 of the 6 `fixed_mul`s) replaced by a per-band shared seed — distance log-bucketed (block-FP, MANT=4), the seed built once per band at its first-hit distance, a span deriving `xfrac0 + x1*xstep`. Floor setup ~200M→~130M; saved ~71M (1.16× more). Re-blessed goldens (square `661061c6`, E1M1 `5f470107`). ⚠ **VISUALLY BAD — owner rejected.** See the revert note below. |

### ⚠ Phase 2 is being REVERTED (visual artifact) — NEXT STEP

**The bug in the idea (not the code):** floor distance is a function of the screen ROW
(`distance = FixedMul(planeheight, yslope[y])`), so a "distance band" is a *range of rows*; every span in a band
shares one u,v seed ⇒ **all rows in the band render IDENTICALLY** (each floor pixel equals the one below it —
vertical replication, worst near the horizon where many rows fall in one band). This is inherent to
distance-bucketing: the speed win *is* seed-sharing across rows, which *is* the vertical stretch. The MANT=4 PNG
validation (3× upscaled) was too lenient; the owner rejected it on the real frame.

**NEXT STEP (decided, not yet started) — revert Phase 2, then a CLEAN [exact] recovery:**
1. **Revert the Phase 2 commits** (oracle `69df2ed`, fj `f7f4409`, the prototype `01060f8`, and the goldens):
   restore the byte-exact perspective floor + the original goldens (square `00de1aaa`, E1M1 `db5d3da8`) in
   `reference_model._render_planes_textured`/`_draw_span`, `plane.draw_span` (drop `floor_band`/`build`/the
   band tables/the emitter band globals), and `test_floor_planes.py` / `test_wall_frame.py` /
   `test_floor_planes_fj.py`. Keep ALL of Phase 1 (it is byte-exact — zero visual change). Back to **515.2M /
   0.54 fps / 2.26×**, correct floors.
2. **Then the [exact] per-(row, visplane) span cache** (TIER-1 #1 below): within ONE row, walls chop a floor
   plane into ≈2.9 spans that all share `dist/xstep/ystep/zlight-row` (these depend only on `(planeheight, y)`);
   only `xfrac/yfrac` (the x1 seed) differ. Cache them per (row, distinct planeheight) → dedupe the ~885 chopped
   spans' 3 shared `fixed_mul`s. **~70M, NO visual change** (each row keeps its EXACT distance — no vertical
   replication). Needs a `draw_span` split (a `setup_rv` leaf + ~a few cache globals keyed by planeheight,
   reset per row in `render_planes_spans`). Lands back near ~445M but correct-looking. This is the floor lever
   that should have been chosen over bucketing (bucketing's real win was only 71M AND ugly).

Phase 1 byte-exact (square `00de1aaa`, E1M1 `db5d3da8`). Phase 2 re-blessed (square `661061c6`, E1M1
`5f470107`). Span after Phase 2 = 24,228,804 words (< 2²⁶). **Combined 1.165B → 444.5M = 2.62× (0.24→0.63 fps).**

**Phase 1 verdict (vs the DESIGN ~370M target):** the byte-exact geometry early-out is worth ~130M (1.25×), not the
~270M the spec hoped — confirming DESIGN R1. The per-seg *projection* that the early-out removes is NOT where the
295M "geometry" lives; the unremovable residual is `wall_x_range`-on-many-segs + the per-claimed-column work + the
baked 681-node walk. **The single dominant remaining cost is the FLOOR per-span setup (~200M, 6 `fixed_mul`s ×
~1357 spans)** — only DESIGN Phase 2 (distance-bucketed floor, [re-bless]) reaches it. Geometry/walls beyond this
need DESIGN Phase 3 ([re-bless]) or node-level walk culling.

**Phase 3 (vertical-pattern walls) — ASSESSED, NOT IMPLEMENTED.** The DESIGN Phase 3 raster/divide win is
mostly illusory in this renderer: `proj.column_render_params` (which holds the per-column `texture_u` divide
and the `iscale` `fixed_div` that Phase 3 deletes) runs ONLY on newly-claimed columns — **~160/frame total**
(`skip_if_drawn` skips the rest), so deleting both divides saves only ~8M; and the per-pixel raster leaf
(`leaf_body_w`) is NOT sped by a vertical-only pattern (the texture *sample* was never the cost — it's the
nibble-op count of `cm.apply`/the add/the writes). So vertical-pattern walls would **degrade wall visuals for
~8M (~1.8%)** — a bad trade, declined. The real wall lever is the **[exact] pass-2 restructure** (the 16K-pixel
unrolled trampoline → a per-column `[top,bottom]` runtime loop, skipping the ~10,381 non-wall iterations,
≤~25M, NO visual change) — but it is "net uncertain" (trades compile-time FB addressing for runtime pointers,
reopens the M12oo assemble/span tradeoffs); left as a separate focused effort. The dominant remaining cost is
the GEOMETRY (~165M post-Phase-1: `wall_x_range`-on-many-segs + the baked 681-node walk), reachable only by
node-level walk culling (a bigger change).

**New floor breakdown (isolated spawn, post-opt2):** FULL 267M = per-span SETUP ~200M (75%) + per-pixel ~43M
(16%) + walk ~23M (9%). The per-span setup (6 `fixed_mul`s × 1,357 spans) is now the floor's giant; the walk
is solved. Frame ~645M ≈ floor (~300M full) + walls/BSP-walk (~345M, UNTOUCHED).

**Remaining [exact] levers (modest + complex; the big wins are done):**
- Per-span setup cache (2-slot ceil/floor, dedupe `dist/xstep/ystep/zrow` for the ~885 chopped spans, chop
  rate 2.875) → ~44M isolated / ~70M full. Needs a draw_span split (setup_rv leaf) + cache logic + ~14 globals.
- Per-row fb cell base (move `y*VIEW_W` out of draw_span's per-span seed to render_planes_spans per row) → ~12M.
- Wall pass-2 restructure (the 16K-pixel unrolled trampoline → per-column [top,bottom] runtime loop): skips
  ~10,381 non-wall iterations AND shrinks the program (→ lower @ globally, gap #15). Net uncertain — measure first.
- Width narrowing in plane_col/the seed. Small.
- **Estimated [exact] ceiling ≈ 450–550M (~0.5–0.6 fps).** 20M needs the re-bless/algorithmic levers (declined).

## MASTER LIST — all optimizations from the perf session (consolidated)

Tags: **[done]** shipped this session · **[next]** decided, do now · **[M14]** needs the sim · **[exact]** keeps
pixels · **[rebless]** changes pixels (re-bless goldens) · impact = rough ops/frame.

### A. Implemented this session
1. **[done][exact] Phase 1 geometry early-out** — `full` flag + occlusion pre-scan in
   `seg_pass1_leaf_body_mtlwp`. 645.6M→515.2M (1.25×). Goldens preserved. KEEP.
2. **[done→REVERT][rebless] Phase 2 log-bucketed floor** — 515.2M→444.5M but **vertical-replication artifact
   (owner rejected)**. Revert (commits `69df2ed`/`f7f4409`/`01060f8` + goldens).
3. **[declined] Phase 3 vertical-pattern walls** — ~8M for a visual downgrade; the per-column divides run
   ~160×/frame not per-pixel, and the raster leaf isn't sped by vertical patterns.

### B. Immediate next (decided)
4. **[next][exact] Revert Phase 2** → back to byte-exact perspective floors (515.2M / 0.54 fps).
5. **[DEFERRED][exact] per-(row,visplane) floor span cache** — MEASURED (spawn): the ~3.9 visplanes/row are
   **interleaved** across 13.6 spans/row, not consecutive, so a **1-slot cache hits only 10% (~0.3M, built +
   byte-exact + reverted as useless)**. A **direct-mapped** cache (idx=ph) plateaus at **41% (~20M)** due to
   collisions; a **full associative** (per-row, remember-all) cache hits **71% (~33M)** but needs a runtime-
   indexed fill (`ptr_index`) + per-row reset — complex, byte-exact-debugging at 6-min gates, for ~1.04-1.07×.
   Owner: **skip for now**, pick up later if wanted. Floors stay at Phase-1 (515M, correct).

### C. The BSP walk — [M14] dispatch-incremental
6. **[M14][exact-ish] dispatch-incremental side test** — maintain `side_i = a_i·vx+b_i·vy+c_i` (integer, exact,
   no drift); per tic `side_i += dispatch_a[dvx] + dispatch_b[dvy]` (precomputed products, `@`-routed, no mul,
   no `ptr_index`). Decision = `sign(side_i)`. ~204 shared tables (98 `dx` + 106 `dy`), ~12k cells. Walk
   ~7M→~1.1M.
7. **[decided] DROP sign-first entirely** — it's the stateless from-scratch method; superseded by #6. (Only
   had value pre-M14; owner cares only about M14+ walking fps.)
8. **[M14] seed = full-mul `point_on_side`, once** — needs the magnitude (can't be sign-first). Re-seed ONLY on
   teleport (E1M1 = 0; doors/lifts/exit move heights not vertices → never reseed). Negligible.

### D. Per-seg geometry — [rebless] (only ~26 segs contribute; `wall_x_range` culls 432)
9. **[rebless] affine `rw_distance`** — perpendicular distance = `a'·vx+b'·vy+c'` (baked coeffs). Kills
   `point_to_dist` (96k, 2 divides) in BOTH `wall_setup` + `wall_offset`. [M14: maintain incrementally.]
10. **[rebless] affine back-face cull (the `rw_distance` SIGN)** — skip both atans for back-facing segs BEFORE
    paying them → cuts the 432-seg / 864-atan bulk (~71M) hard.
11. **[rebless] Montgomery batch inversion** — all per-seg reciprocals (`scale`, `iscale`, atan slope) via
    **1 divide/frame + ~3n muls** (no `1/y` table; division O(1)/frame not O(seg)). Needs block-FP normalize
    (narrow mantissa muls) + a gather-then-use restructure.
12. **[M14] Newton-Raphson incremental reciprocal** — maintain `1/D` per seg, 1 step (2 muls)/frame, divide
    only on a newly-visible seed. No divide in steady walking.
13. **[rebless] atan** — batch-invert the slope `den` (#11), `.lookup` `tantoangle` (16ˣ) → divide-free,
    O(1)/frame. (CORDIC considered, ≈ same as the divide here — not a win.)
14. **[rebless] fold compile-time-const muls into 16ˣ tables** — `PROJECTION·sin(angleb)` → one `projsin[ ]`
    lookup (no mul).

### E. Cross-cutting LAWS (apply to every table / op)
15. **[LAW] Table Design Law** — index a **16ˣ table by the top x nibbles XOR'd into the dispatch address**
    (`.lookup dst, var+offset*dw`): no shift, no clamp, no `read_table` arithmetic. Tables are **16ˣ sized**
    (smaller x for less precision); **≤16³ (4096) without owner permission**.
16. **[next][exact] kill avoidable whole-nibble shifts** — `shr_hex`/`shl_hex` used to extract an index → read
    at the compile-time offset instead (`var+k*dw`). ~331 ops each; opt1 did u/v only. (Subsumed by #15 where
    a table is involved.)
17. **[rebless] convert non-16ˣ tables to 16ˣ** — `zlight` 128→256 (kills `>>20`+`min(127,·)`), `viewangletox`
    160→256. (`finesine`=4096=16³, `tantoangle`=2048 OK.)
18. **[exact] `.lookup` dispatch, not `read_table`** — ~35 ops vs ~thousands (it computes the address
    arithmetically). 
19. **[principle] narrow every op to its real width** + fold compile-time constants into tables. Muls don't
    batch (no "1 mul for n") — only narrow / fold / reduce-count.

### F. Per-pixel raster — MEASURED: full-res 12M is IMPOSSIBLE; needs fewer pixels
20. **Per-pixel feasibility (MEASURED).** Irreducible per textured pixel = `flat.sample` (391) + `cm.apply`
    (399) + framebuffer write. The write DOMINATES and depends on addressing: **runtime pointer
    `write_hex_and_inc` ×2 = 1564** (what the floor uses) vs **compile-time-address `xor_zero` = 284** (the
    wall pass-2 way) — a **5.5×** gap. So:
    - floor today (runtime ptr): sample+apply+write = **2352 ops/px** → 16k px ≈ **38M** just for pixels.
    - ⚠ CORRECTION: 1074 = sample+apply+write ONLY. A real FLOOR pixel ALSO pays the u,v DDA step (`add 6` ×2 =
      1075) + the coord extract (`mov2`+`and2` ×2 = 584) + spot — irreducible for perspective texturing (narrow,
      not remove). So an *optimized* floor pixel ≈ **~2700-3000**, a wall pixel ≈ ~2000.
    - Full-res FULLY optimized (compile-addr writes, narrowed, batch-inverted geometry): floor 10,381×~2700 ≈
      28M + wall 5,619×~2000 ≈ 11M + geometry ≈ 5M = **~44M ≈ ~6-7 fps**. NOT ~17M (that omitted the DDA/extract).
    - → **Full-resolution (16,000 px) 12M is physically impossible**, even with zero geometry/walk/DDA. The
      binding constraint is the PIXEL COUNT, not the per-pixel cost (already near its floor).
    - **12M requires ~4× fewer pixels** (a quality tradeoff): **2×2 blocks → 4,000 px** × ~1074 (compile-addr) ≈
      **4.3M** for pixels (reachable); or lower resolution; or **flat-colored floors** (drop `flat.sample`,
      span-constant color → ~284/px write-only → ~4.5M, but no floor texture).
21. **Biggest full-res per-pixel lever (doesn't reach 12M but ~halves the floor):** switch the floor raster from
    the runtime pointer to **compile-time-address writes** (unroll like wall pass-2) — write 1564→284. Costs a
    large unrolled program (assemble time), like the wall's 16k unroll.

**VERDICT for 12M (corrected):** full-res textured, FULLY optimized ≈ **~40-50M ≈ ~6-7 fps** (~10× over 515M,
no quality loss). **12M is NOT reachable at full res** — it needs ~4× fewer textured pixels: 2×2 blocks
(~12-15M, ~20 fps, chunkier) or flat-colored floors (~10-15M, no floor texture). So 12M = a deliberate quality
tradeoff. The geometry/walk re-bless campaign (items 6-19) only matters once the pixel budget is chosen; full-res
it can't beat ~40M (the textured per-pixel floor dominates).

### The 5 cross-cutting principles (the "why")
1. **Affine + dispatch** — replace muls/divs with adds + `@`-routed lookups (walk, `rw_distance`, back-face).
2. **Batch inversion** — n divides → 1/frame (no per-op reciprocal).
3. **16ˣ top-nibble `.lookup`** — deletes shift + clamp + `read_table` (one ~35-op dispatch).
4. **Narrow + fold** — minimum width per op; compile-time constants → tables.
5. **Per-pixel is the floor** — 16k px × ~750 ops is the 12M budget; everything above is amortized setup.

## Path to 12M ops/frame — the irreducible algorithm + per-component plan (design, not built)

The renderer's algorithm STAYS (BSP walk + perspective projection + textured raster); we optimize each stage,
we do not replace the pipeline. Two structural facts frame the whole effort:

**(A) The side test is AFFINE in the viewpoint, and so is the wall distance.** `side_i = a_i·vx + b_i·vy + c_i`
(`a_i=−dy_i`, `b_i=dx_i`, all baked). `rw_distance` to a seg is the same shape (signed distance to a baked
line). Affine ⇒ exact integer incremental maintenance as the viewpoint moves (`+= a_i·dvx + b_i·dvy`, no drift),
and `dvx,dvy ∈ [−30,30]` (a signed byte; `MAXMOVE` caps every tic incl. knockback).

**(B) At 12M, the 16,000 screen pixels dominate.** `12M ÷ 16,000 px ≈ 750 ops/pixel`. Everything else (walk
~681 nodes, projection ~visible segs, per-column ~160) is *amortized setup* that can be driven cheap; the
per-pixel raster is the irreducible floor. Current per-pixel ≈ 4.2k ⇒ must fall ~5.6× (width narrowing; or a
resolution/▢-block tradeoff: 2×2 blocks → 4,000 px → a 3k-ops/px budget).

### The BSP walk — DECIDED design (build at M14, with the sim)

- **Per tic = dispatch-step (incremental).** Maintain `side_i` (full signed value) for all 681 nodes; each tic
  `side_i += dispatch_a[dvx] + dispatch_b[dvy]` where the two dispatch tables hold the *precomputed* products
  `a_i·dvx`, `b_i·dvy` (no multiply, no `ptr_index` — `@`-routed). Tables are SHARED by equal `dx`/`dy`
  (E1M1: 98 distinct `dx`, 106 distinct `dy` ⇒ ~204 tables × ~61 cells for ±30 ≈ ~12k baked cells). Side
  decision = read `sign(side_i)` (`>0`→back, `≤0`→front). Per node ≈ 2 dispatch + 2 adds ≈ ~1.7k ⇒ walk ≈ ~1.1M.
- **NO sign-first, NO conditional multiply.** Those are the *stateless* method; maintaining `side_i` makes the
  3-valued sign reconstruction and the same-sign-only-multiply both unnecessary. **Sign-first is dropped entirely**
  (owner decision: only M14+ walking fps matters; pre-M14 single-frame speed is not a goal worth throwaway work).
- **Seed = the existing full-mul `point_on_side`, once.** It needs the magnitude, so it can't be sign-first.
  Re-seed only on a position jump that overshoots the table — i.e. **only teleports** (normal move ≤ MAXMOVE
  never overshoots). **E1M1 has 0 teleports** (and doors/lifts/exit move sector *heights*, never vertices, so
  the BSP is static and they trigger NOTHING). So for E1M1 the seed runs exactly once, at load; elsewhere a
  teleport sets a "re-seed next frame" flag → one ~4.8M full-mul pass, a few times per playthrough. Negligible.

### Irreducible must-stay stages + their optimization angle

| Stage | runs ×/frame | must stay because | optimization angle |
| --- | --- | --- | --- |
| BSP walk side test | 681 nodes | visibility order | dispatch-incremental (above) → ~1.1M |
| `wall_x_range` (cull + screen x-span) | per visible seg | which columns a wall covers | angle-based (nonlinear) — coherence harder; revisit |
| `wall_setup` `rw_distance` | per visible seg | perspective distance | **AFFINE → same dispatch-incremental as the walk** |
| `wall_scale_setup` scale/step | per visible seg | perspective foreshortening | scale ∝ 1/distance·cos; incremental candidate |
| `column_render_params` | ~160 cols | per-column texcol + scale | scale already incremental; `iscale=1/scale` → reciprocal LUT/Newton |
| **wall per-pixel** (`leaf_body_w`) | ~5,619 px | drawing wall texels | **the 12M floor** — width narrow + `[top,bottom]`-only pass |
| **floor per-pixel** (`draw_span`) | ~10,381 px | drawing flat texels | **the 12M floor** — width narrow; per-(row,visplane) setup cache |
| span grouping (`render_planes_spans`) | 100 rows | R_MakeSpans | already unrolled (opt2) |
| occlusion (`drawn[]`) | per col/seg | front-to-back clip | already cheap |

**Takeaway:** 12M is won or lost in the two **per-pixel** rows (≈16k px, the ~750-ops/px budget). The walk and
the affine projection pieces (`rw_distance`) are cheap via the dispatch-incremental trick; the genuinely hard,
dominant work is the per-pixel raster — that's where the next deep design effort belongs.

### DECIDED — eliminate ALL divides in the per-seg projection ([re-bless])

Divides are the per-seg cost. **Measured primitives:** `fixed_mul 8,4` = 11,493; `fixed_div 8,4` = **41,324**
(~3.6× a mul); `point_to_angle` (atan) = **73,455** (a `hex.div 12` + `tantoangle`); `point_to_dist` =
**95,583** (TWO `fixed_div`s); `angle_to_x` = 9,049. The three per-seg macros: `wall_x_range` ≈ 165k (2 atans),
`wall_setup` ≈ 180k (atan + dist), `wall_scale_setup` ≈ 170k (3 divides).

**Measured seg-complexity (E1M1 spawn, fj + Phase 1):**
- `wall_x_range` runs on **432 segs** (Phase-1 `full` cut it from 575) — **2 atans each = 864 atans ≈ ~71M, the
  dominant geometry cost**. 116 pass (visible).
- **The full projection (`wall_setup`/`wall_scale_setup`/`wall_offset`) runs on ONLY ~26 segs/frame** (the
  occlusion pre-scan + `drawn[]` mean only the ~26 front-most contributing segs project). ~27 at other vps.
- per-column `column_render_params` (the `iscale` divide): 160 columns.

So "kill the divides" is two problems of very different size:

1. **The 26-seg full projection — easy + cheap to make divide-free.** Replace every divide with a reciprocal
   LUT (`1/x` table + a `fixed_mul` ≈ 12k, vs the 41k divide) or the affine form:
   - **`rw_distance` → affine, NO divide.** Perpendicular distance to a seg line = `a'·vx + b'·vy + c'` with
     baked coefficients (`a'=segdy/seglen` etc., computed once at level load). Replaces `point_to_dist` (96k,
     2 divides) in BOTH `wall_setup` and `wall_offset`. ⚠ coefficients are fixed-point (not integer like the
     side test) → maintain incrementally with periodic re-seed OR recompute per-frame as `(cross product)·
     (baked 1/seglen)` (2 `mul_const` + a `mul_const` — no divide). [re-bless: sub-bit rounding vs the oracle's
     divide path — verify PNG-identical, re-bless.]
   - **`scale`'s `1/(rw_distance·sin)` → reciprocal LUT / one Newton step** (you already track `rw_distance`).
   - **`iscale = 1/scale` and `texcol % tw` → reciprocal LUT / mask** (`tw` is a power of 2 → mask, not mod).
   - Net: ~26 segs × (~250k divide-free vs ~457k) ≈ **~6.5M instead of ~12M**, and the per-column divide gone.
2. **The 432-seg `wall_x_range` cull — the real bulk (~71M), a different problem.** Two levers:
   - **Back-face cull BEFORE the 2 atans, using the affine `rw_distance` SIGN** (which side of the seg line the
     eye is on — the same cheap affine test, no atan, no divide). Skips both atans for back-facing segs
     (roughly half) → far fewer atans.
   - The surviving atans: replace `point_to_angle`'s slope divide (`dy/dx`) with a **reciprocal LUT for `1/dx`**
     → atan ~73k → ~44k. [re-bless.]
   - Better still: most of these 432 never contribute (only 26 do) — a cheaper cull (affine side/back-face +
     the existing `full`/occlusion) should cut the 432 toward the ~26+frustum set before paying any atan.

**Verdict:** divide-free projection is a [re-bless] (reciprocal LUTs + the affine `rw_distance`), low-risk
(sub-bit value shifts, no visual artifact like the floor banding). The 26-seg full projection becomes ~6.5M;
the 432-seg `wall_x_range` needs the affine back-face cull to really fall. Both reuse the affine machinery.

**`tantoangle` is the only ratio-keyed table** (so the only one needing a divide to index — others key off a
shift of angle/distance/row). The atan's 73k is 69% one `hex.div 12` (the slope `dy/dx`); reciprocal-LUT the
slope (`num·(1/den)`, block-FP recip table) → atan ~73k → ~15-20k [re-bless]. (CORDIC is the textbook
divide-free atan but ≈50k here — same as the divide — since fj divides AND CORDIC iterations are both
width-bound; the reciprocal-LUT is the actual win.)

### DECIDED — TABLE DESIGN LAW (owner rules, binding for all optimization tables)

1. **Index a 16ˣ table by the top x nibbles, XOR'd straight into the dispatch (wflip) address** — `.lookup
   dst, var + offset*dw` (the `.lookup` body does `rep(x,i) hex.xor .dsp+4*i, idx+i*dw`, reading each nibble
   at its offset). **No `shr_hex`, no `read_table` arithmetic, no mask/clamp** — the nibbles are already there.
2. **Tables are 16ˣ sized.** Fewer entries / less precision ⇒ a *smaller x* (fewer top nibbles), NEVER a
   non-16ˣ size (a non-16ˣ size is exactly what forces the shift+clamp).
3. **≤ 16³ (4096) without owner permission.** Bigger = a "big table," ask first.

Consequence: this supersedes the shift-audit below — the right pattern isn't "shift less," it's "size the table
16ˣ and `.lookup` by the top nibbles," which deletes the shift AND the clamp AND the ~thousand-op `read_table`
(→ ~35-op dispatch). Existing NON-16ˣ tables to convert ([re-bless], ≤1 nibble coarser): `zlight` 128→256
(kills `>>20` + `min(127,·)`), `tantoangle` 2048→? , `viewangletox` 160→256. (`finesine` = 4096 = 16³ already.)
Reciprocal `1/den`: normalize (top-nibble leading-digit find) → top-3-significant-nibble `.lookup` → exponent
via offset, all within 16³; if a clean reciprocal needs > 16³, ASK first.

### DECIDED — per-seg reciprocals via BATCH INVERSION (1 divide/frame, no 1/y table)

Owner: a `1/y` reciprocal table won't work; **division is OK at O(1)/frame, NOT O(seg).** Answer =
**Montgomery batch inversion**: invert all `n` per-seg denominators with ONE divide + ~3n muls —
prefix-products `Pᵢ=Pᵢ₋₁·Dᵢ`, one `R=1/Pₙ`, back-substitute `Dᵢ⁻¹=R·Pᵢ₋₁ ; R=R·Dᵢ`. Applies to ALL per-seg
reciprocals at once: `scale` (`1/(rw_distance·sin)`), `iscale=1/scale`, the **atan slope** (`min/max` →
batch-invert the `max`es, `slope=min·(1/max)`). So the whole per-seg projection = **one division per frame**.
- ⚠ **Overflow**: `Pₙ` = product of ~26-116 distances → must run **block-FP** (normalized mantissa = top
  nibbles per the table law + a running exponent sum; final `1/Pₙ` = mantissa-reciprocal + exponent offset).
  Bonus: mantissa muls are NARROW (~3 nib ≈ 2.5k vs 11.5k) → ~3n narrow muls ≈ ~0.9M/116 segs vs ~4.75M for
  116 divides (~5×) AND O(1) divides.
- ⚠ needs a **gather-then-use restructure** (pass A: affine `rw_distance` + denominators for all visible segs
  → batch-invert → pass B: use) — fits the two-pass renderer.
- **Alternative (M14, stateful): Newton-Raphson incremental reciprocal** — maintain `1/Dᵢ` per seg, 1 step
  `r←r·(2−D·r)` (2 muls, no divide)/frame on the affinely-tracked `D`; real divide only on the SEED when a seg
  becomes newly visible (amortized O(1)/frame walking, O(new-segs) turning). No divide in steady state.

This supersedes the reciprocal-LUT bullets above (no `1/y` table). The atan: batch-invert the slope `den`,
`.lookup` tantoangle (16ˣ) → atan divide-free + O(1)/frame.

### DECIDED — cross-cutting: kill avoidable SHIFTS (whole-nibble → offset addressing) [exact]

Shifts are NOT free: `hex.shr_hex 8,5` = **331 ops**, `hex.shl_bit 8` = 346 (~30× a nibble op). A **whole-nibble
shift used to extract an index** (`distance>>20`=5 nib for zlight, `angle>>20`, `den>>8`, even `vx<<16`=4 nib)
is pure waste — the bits are already there; **read them at the compile-time offset** (`hex.mov 3, idx,
src + 5*dw`, or feed `src + k*dw` straight to `read_table`). opt1 did this for `draw_span`'s u/v but NOWHERE
else. Audit + delete the avoidable `shr_hex`/`shl_hex` in `draw_span` (zlight index, per-span ×1357),
`clear_planes`, `scale_from_global_angle`, `slope_div`, `point_to_angle/dist`. Each ~331 saved; ~a few M/frame
aggregate — **[exact]** (same value, just addressed not shifted). Only BIT-granular shifts (`shl_bit`, `>>1`,
non-nibble `>>10`) genuinely need a shift.

## Optimization backlog (macro-by-macro; ordered by leverage)

Principles: take work OFF the per-pixel path → do it once per row/column/span; replace multiplies with
incremental adds or precomputed LUT entries; do NOT rebuild a screen address per pixel (running pointer or
compile-time address). Tag: **[exact]** keeps the goldens; **[re-bless]** changes pixels → re-bless square
`00de1aaa` + E1M1 `db5d3da8` deliberately. Re-assert goldens + re-measure ops/frame after each.

### TIER 1 — `plane.draw_span` per-SPAN setup (~half the 70% floor pass; 1,357 spans × ~123k)
1. **Hoist the row/visplane-invariant seeds out of per-span.** `dist=FixedMul(planeheight,yslope[y])`,
   `xstep=FixedMul(dist,basexscale)`, `ystep=FixedMul(dist,baseyscale)`, and the zlight colormap-row depend
   only on `(planeheight,y[,light])` — identical for every same-visplane span in a row. Compute once per
   (row, distinct visplane); removes ~3 of the 6 eight-nibble `fixed_mul`s + a lookup per span. **[exact]**
2. **Continuous per-row DDA — kill per-span re-seeding entirely.** Re-architect `render_planes_spans`+
   `draw_span`: per row, seed each visplane's DDA ONCE at its first column and step `xfrac/yfrac += xstep/
   ystep` continuously left→right, stepping PAST wall columns without writing. No per-span `length`/`finecos`/
   `finesin`/`xfrac`/`yfrac` recompute (the other ~2-3 fixed_muls + 2 trig lookups). Drops setup from ~1,357
   spans to ~one seed per (row,visplane) (~200-400/frame). Needs the oracle to step continuously too.
   **[re-bless]** — the biggest single floor win.

### TIER 2 — `plane.draw_span` per-PIXEL body (~half the floor pass; ~13.4k ops/px)
3. **Running framebuffer pointer, not a per-pixel address rebuild.** Today each pixel does `pixp=y*VIEW_W`
   (`mul_const 8` — the priciest per-pixel op) + `zero off`/`mov`/`shl_bit`/`set fbptr`/`ptr_index`. Replace
   with a pointer seeded once per span (or row) and `+= 2*dw`/pixel, then `write_hex`. Kills the multiply +
   the address math. **[exact]**
4. **`spot = v*64+u` with no multiply:** `((yfrac>>10)&0xFC0) | ((xfrac>>16)&63)` (the ×64 folds into the
   shift — matches the oracle `(yfrac>>10)&4032`). Drops the per-pixel `mul_const 3`. **[exact]**
5. **Hoist the span-constant lookups.** `zrow` (distance light) is constant per span → take the colormap-row
   base once per span, then per-pixel index by `pal` only (1-level, no per-pixel `cmidx` rebuild). `flatbase`
   is span-constant. **[exact]**
6. **Narrow per-pixel registers.** xfrac/yfrac at 8.8 (4-nib) not 16.16 (8-nib) halves the dominant per-pixel
   `add` **[re-bless]**; the loop guard `scmp 8 xx,x2` + `inc 8 xx` → 2-nibble or a count-down counter
   **[exact]**; extract u/v from only the needed nibbles.

### TIER 3 — `frame.render_planes_spans` classify walk (16,000 cells/frame via pointer reads)
7. **Stop re-reading column-constant arrays per row.** col_cexcl/col_fstart/col_ceil_ph/col_ceilbase/col_plight
   are set once in pass-1, identical across all 100 rows → the walk re-reads them ~100× via `ptr_index`+
   `read_hex`. Either switch to DOOM's column-incremental R_MakeSpans (touch each column once; open/close spans
   across rows), or precompute a single packed **per-column visplane-key** so the extend test is ONE compare
   (not three: ph,base,light) and the full params are read only at span starts. **[exact]**
8. **Compile-time column addressing in the walk** where the column index can be unrolled (no `ptr_index`).

### TIER 4 — Wall pass-2 (`pixel_tramp`+`compare_y`, runs all 16,000 px; part of the 30%)
9. **Don't iterate all H rows per column.** ~10,381 of 16,000 pixel_tramp iterations are non-wall skips that
   still pay the trampoline + 2 `cmp`. Re-architect pass-2 as a **per-column runtime loop over [top,bottom]
   only**, running fb pointer down the column (`+= VIEW_W*2*dw`/row). Removes the wasted iterations AND shrinks
   the program (16K unroll → a loop) ⇒ faster assemble + smaller span. **[exact]**
10. `leaf_body_w` is already lean (2-nibble ops + the 8.8 add); width-audit only.

### TIER 5 — `proj.column_render_params` (per claimed column × seg; right tier, but heavy)
11. Per-column `fixed_div` (iscale=1/scale) + `fixed_mul`/`hex.div` (texcol, scale). `scale` is already
    incremental. Consider a reciprocal LUT / Newton step for `1/scale`; lower priority (per-column, not pixel).

### TIER 6 — cross-cutting
12. **Precompute per-row LUTs** to kill per-pixel/per-span multiplies: `rowbase[y]=y*VIEW_W` (100 entries),
    the row fb base address. Read once per row. **[exact]**
13. **Width audit (DESIGN §1.1.4 precision ledger):** every op's nibble width = the minimum the quantity needs;
    cost is ~linear in width.
14. **Method:** first MEASURE the floor pass's setup-vs-pixel-vs-walk split (one targeted run) to order 1–8;
    then each change → re-assert goldens (or re-bless) → re-measure fps.

## Op + width audit of `plane.draw_span` (the 70% hot path)

Two questions: (1) is each mul/div/complex-macro really needed? (2) what is the minimum nibble width of each
register? Cost is ~linear in nibble width, and an N-nibble op = N truth-table dispatches.

### (1) mul / div / complex-macro necessity
PER-PIXEL (lines 155-186) — runs ~10,381×/frame:
- `mul_const 8, pixp, yp, view_w` (y·VIEW_W) — **NOT NEEDED.** y is span-constant; the address is monotone →
  **running fb pointer (`+= 2*dw`/px)**. Deletes the multiply + `zero yp/off`, `mov yp/off`, `shl`, `set fbptr`,
  `ptr_index` (≈9 ops, several 8-nibble). **[exact]**
- `mul_const 3, spot, vv, 64` — ×64 is a single-bit constant ⇒ `mul_const` already strength-reduces it to one
  shift (not a real multiply). Keep or fold into the `fidx` write. Cheap.
- `flat.sample`, `cm.apply` — needed, measured cheap (~36/33 ops). NOT the problem.
- `ptr_index`+`write_hex` — the write is unavoidable; the ADDRESS REBUILD is not → running pointer (above).
- **Net: the per-pixel body needs ZERO real multiplies and ZERO per-pixel address math.**

PER-SPAN setup (lines 118-152) — the 6 `fixed_mul`s:
- `dist=ph·yslope[y]`, `xstep=dist·basexscale`, `ystep=dist·baseyscale` — depend only on (planeheight,y) →
  **hoist to once per (row,visplane)** (identical for same-visplane spans in a row). **[exact]**
- `length=dist·distscale[x1]`, `finecos·length`, `finesin·length` — x1-dependent. Eliminated by the
  **continuous per-row DDA** (seed once/row/visplane, step across) — **[re-bless]**; else stay per-span.
- The zlight-row block (`zidx`/clamp/`lvl`/`zlidx`/`zrow` read) also depends only on (dist,light) → **hoist to
  per (row,visplane)**. The `yslope[y]` read → **once per row**. **[exact]**
- `clear_planes` 2 `fixed_div` are PER-FRAME — fine. `draw_span` has NO divide.

### (2) minimum register widths (current → min)
| reg(s) | now | min | basis | tag |
| --- | --- | --- | --- | --- |
| `x1`,`x2`,`xx` (loop) | 8 | **2** | column 0-159 < 256; loop guard `scmp 8`→`scmp 2`, `inc 8`→`inc 2` (or count-down a 2-nib width) | [exact] |
| `xfrac`,`yfrac` | 8 | **6** | only bits 0-21 feed `(>>16)&63`; add carries up only, so mod 2²⁴ ≡ mod 2³² for bits 16-21 | [exact] |
| `xstep`,`ystep` | 8 | **6** | added into the 6-nib accumulators (read low 6) | [exact] |
| `u`,`vv` | 3 | **2** | 0-63 (6-bit); the 3rd nib was only for the old `mul_const`/`add 3` read | [exact] |
| `spot` | 5 | **3** | v·64+u ≤ 4095 (12-bit); flat slices are 4096-aligned ⇒ `fidx`low3 = spot OR-disjoint (no carry) → write spot into `fidx`'s low 3 nibs, `flatbase>>12` preset once/span | [exact] |
| `tt` (shift scratch) | 8 | **— delete** | replace `mov 8 tt,xfrac; shr_hex 8,4 tt` with `mov 2 u, xfrac+4*dw` (read nibbles 4-5 directly) — no 8-nib mov/shift per coord | [exact] |
| `yp`,`pixp`,`off` | 8/8/w4 | **— delete** | subsumed by the running fb pointer | [exact] |
| `cmidx` rebuild | 4 | per-pixel **2** | `zrow` (light) is span-constant → set `cmidx` high byte once/span; per-pixel only `mov 2 cmidx,pal` | [exact] |
| `planeheight`,`dist`,`ys`,`length` | 8 | 8 | genuine 16.16, large near horizon — keep | — |
| `fc`,`fs` | 8 | ~5 | finesine entries are 16-bit (sign-extended) — narrowable with care | [exact, later] |
| `idx`,`zidx`,`lvl`,`zlidx` | 3 | 3 | ok | — |
| `zrow`,`pal`,`lit` | 2 | 2 | ok | — |

Net per-pixel after (1)+(2): drop ~6 eight-nibble ops (the two `mov8`+`shr8` extracts, the `mul_const 8`, the
address rebuild) + narrow the two DDA adds 8→6 + the loop guard 8→2. Per-pixel ≈ **13.4k → ~3-4k ops** (the
remaining: 2× narrow extract, spot, `flat.sample`, `cm.apply`, `write_hex`, 2× `add 6`, pointer `+=`, counter).

### `frame.render_planes_spans` widths
`xcur`,`cVW`,`xm1`,`spanx1` are 8-nibble but ≤160 → **2 nibbles**; `cmp 8 xcur,cVW`→`cmp 2`. `spanph`/`cph`
stay 8 (planeheight). **[exact]**

### Wall path
`leaf_body_w` is already narrow (2-nib ops + the 8.8 DDA `add 4`). `proj.column_render_params` has per-column
`fixed_div` (iscale=1/scale) + `hex.div` (texcol%tw) — needed, PER-COLUMN (right tier); a reciprocal LUT for
`1/scale` is the later lever.

## Gaps / risks in the optimization ideas (adversarial self-review)

Before coding, the traps in each idea. Type: **correct** = could break byte-exactness; **leverage** = the
gain is unmeasured / may be near-zero; **cost** = a hidden cost the idea ignores; **dep** = depends on / overlaps
another change; **scope** = something not yet audited.

| # | Optimization | Gap / hidden issue | Type | Mitigation |
| --- | --- | --- | --- | --- |
| 1 | Hoist `dist/xstep/ystep/zrow` to per-(row,visplane) | Only helps rows where a visplane is **chopped into ≥2 spans**. If avg spans-per-visplane-per-row ≈ 1, gain ≈ 0. Needs a per-row cache keyed by `planeheight` (8-nib compares) + crosses the draw_span/render_planes_spans boundary. | leverage | **Measure the chop rate first** (spans ÷ distinct visplanes per row). Skip if ~1. |
| 2 | Continuous per-row DDA (no per-span re-seed) | Deviates from DOOM/oracle (continuous ≠ per-span re-seed) → owner must accept the visual. Skipping a wall gap of width g costs **g adds or a multiply** (not free). First seed/row/visplane still full. | correct, cost | Owner sign-off on re-bless; only worth it if chop rate (gap 1) is high. |
| 3 | Running fb pointer (`+= 2*dw`/px) | Still needs a per-span seed = `y*VIEW_W` (a multiply) → push it to a **per-ROW base pointer** (`+= VIEW_W`/row) or it just moves the mul from per-pixel to per-span. The advance unit (digit vs bit) is easy to get wrong → **silent frame corruption**. | cost, correct | Per-row base pointer; verify the advance unit against the FB layout (the golden catches it). |
| 4 | Narrow `xfrac/yfrac` 8→6 nib | **[exact] ONLY if the SEED `fixed_mul` stays 8-nib.** Computing the seed at 6 nib changes fractional bits 0-15 → different carries into bit 16 → breaks bits 16-21. | correct | Narrow only the per-pixel **add** to 6; keep the seed multiply at 8. |
| 5 | "Narrow DDA to 8.8 (4 nib)" | This is a **different, [re-bless]** change (drops fractional precision), NOT the same as the 6-nib [exact] narrowing. Conflating them silently changes pixels. | correct | Treat as two separate ideas; 6-nib first (exact), 8.8 only if needed (re-bless). |
| 6 | `spot` 5→3 + OR-disjoint into `fidx` | The OR trick assumes **every flat slice is 4096-aligned** (low 3 nib = 0). A future non-4096 flat / odd sentinel breaks it silently (lost carry). | correct | `assert` 4096-alignment in the emitter, or keep `add` (carry-safe). |
| 7 | `spot = v*64+u` "remove the multiply" | `mul_const ×64` is a single set bit ⇒ already strength-reduced to **one shift**. The "win" is tiny; the real win is the width narrow. | leverage | Don't prioritize; it's ~free already. |
| 8 | Direct-offset extract `mov 2 u, xfrac+4*dw` | The `+4*dw` offset is in **digit units** (nibble 4 = bits 16-19); an off-by-unit reads the wrong nibbles. | correct | Verify the offset; golden catches it. |
| 9 | Hoist span-constant `cmidx` hi-byte / `fidx` hi | Register **lifetime**: the per-pixel body must touch ONLY the low bytes; any intervening clobber of the preset high bytes corrupts every pixel after. | correct | Audit no intervening writes to `cmidx+2dw` / `fidx` high. |
| 10 | Classify-walk: read each column once | The clean version needs the **column-incremental R_MakeSpans** (H open-span entries; a substantially different, trickier algorithm). The cheap "packed visplane-key" only cuts the extend compare 3→1 — it does **NOT** remove the per-cell `cexcl/fstart` reads (region needs y). **The walk's share of the 820M is unmeasured.** | leverage, cost, scope | Measure the walk's share first; try the packed-key (small) before the full rewrite. |
| 11 | Wall pass-2 → per-column `[top,bottom]` loop | Trades **compile-time FB addressing** (the M12 design win = zero pointer math) for runtime pointers. Net win = (10,381 skipped trampolines) − (pointer math on 5,619 real px); could be marginal. Reopens the tuned M12oo assemble-time/span tradeoffs. | cost, dep | Measure the per-skip trampoline cost vs the pointer cost before committing. |
| 12 | Reciprocal LUT for `1/scale` | `scale` is a wide-range 16.16 input → a LUT needs many entries or interpolation; may not beat `fixed_div`. | leverage | Prototype + compare; low priority (per-column, not per-pixel). |
| 13 | `rowbase[y]=y*VIEW_W` LUT | **Redundant** with the running per-row base pointer (#3). Pick one. | dep | Use the running pointer; drop the LUT. |
| 14 | All per-pixel/per-span savings estimates | Measured at **isolated-kernel scale** (~2.5× below the full renderer's @). The real frame delta differs. | leverage | Re-measure on the real renderer per rung; isolated = a lower bound on opportunity. |
| 15 | Program-size feedback | Un-unrolling (wall loop, #11) **shrinks @ globally** (a win not in the local estimates); new LUTs grow span/@ (a cost). | cost | Prioritize size-reducing changes for the @ ripple; budget LUT span (R4). |
| 16 | All the draw_span [exact] tweaks (#3-9) | They touch the **same** per-pixel loop and overlap → doing them as separate rungs causes rework + repeated 5-min E1M1 re-verification. | dep | Bundle the [exact] draw_span changes into ONE rung; iterate on the fast SQUARE golden, capstone on E1M1. |
| 17 | The [re-bless] changes (#2, #5) | Need oracle + both goldens + every byte-exact test updated **in lockstep**; can't be incremental without re-blessing each time. | dep | Do all [exact] first; batch [re-bless] into one rung with a single re-bless. |
| 18 | Wall side (`column_render_params`, BSP walk) | **Not yet op/width-audited** — it's the 30% (345M). The floor audit doesn't cover it. | scope | Audit after the floor wins land. |
| 19 | Narrow `fc/fs` to ~5 nib | finesine entries are **signed**; narrowing must sign-extend correctly into `fixed_mul` — subtle. | correct | Defer; verify sign handling. |

**Two gaps gate the whole plan and should be measured BEFORE coding:** the **chop rate** (gaps 1-2 — is per-span
setup even hoistable?) and the **floor pass's setup-vs-pixel-vs-walk split** (gaps 10, 14 — which half to attack).
Both are one host-side count + one targeted renderer run.

## How to reproduce

- `scratchpad/prof_drawspan.py` — per-pixel ops vs span width vs flat-table size (native engine, fast).
- `scratchpad/prof_hist2.py` — per-pixel op breakdown (featured-loop IP histogram, span12−span2 diff,
  monkeypatches `RunStatistics.register_op_address`; maps IPs→labels via `load_debugging_labels`).
- `scratchpad/split_e1m1.py` — real-renderer walls-vs-floors split (emit_wall_renderer with the plane pass on
  vs off).
