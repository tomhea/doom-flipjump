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

## Perf-reduction phase — progress ([exact] only, owner chose no re-bless)

| Rung | ops/frame | fps @280M | vs baseline | what |
| --- | --- | --- | --- | --- |
| baseline (textured) | 1,165,180,455 | 0.24 | — | M13d2c byte-exact |
| opt1 per-pixel | 1,093,029,378 | 0.26 | 1.07× | draw_span per-pixel: running fb pointer, direct-offset u/v extract, span-constant presets, 6-nib DDA, count-down loop (per-pixel 13.4k→4.2k ops, but per-pixel was only ~9% of the frame). +fix: clear stale `tt` before the x1 seed (register-lifetime bug at far spans, caught at E1M1 (-416,256)). |
| **opt2 walk unroll** | **645,575,343** | **0.43** | **1.81×** | `render_planes_spans` column scan UNROLLED (`rep(view_w,x) plane_col x`) → compile-time addresses, no `ptr_index`. WALK 312M→23M (13.3×); whole floor pass 540M→267M (2.0×). |

Both byte-exact (square `00de1aaa`, E1M1 `db5d3da8`). Span after opt2 = 23.6M words (< 2²⁶).

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
