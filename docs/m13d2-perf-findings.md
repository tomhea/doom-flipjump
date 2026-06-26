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

## How to reproduce

- `scratchpad/prof_drawspan.py` — per-pixel ops vs span width vs flat-table size (native engine, fast).
- `scratchpad/prof_hist2.py` — per-pixel op breakdown (featured-loop IP histogram, span12−span2 diff,
  monkeypatches `RunStatistics.register_op_address`; maps IPs→labels via `load_debugging_labels`).
- `scratchpad/split_e1m1.py` — real-renderer walls-vs-floors split (emit_wall_renderer with the plane pass on
  vs off).
