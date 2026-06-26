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

## How to reproduce

- `scratchpad/prof_drawspan.py` — per-pixel ops vs span width vs flat-table size (native engine, fast).
- `scratchpad/prof_hist2.py` — per-pixel op breakdown (featured-loop IP histogram, span12−span2 diff,
  monkeypatches `RunStatistics.register_op_address`; maps IPs→labels via `load_debugging_labels`).
- `scratchpad/split_e1m1.py` — real-renderer walls-vs-floors split (emit_wall_renderer with the plane pass on
  vs off).
