# Plan: W2 walls + FT1 minor-textured floors in the lines mode, budget < 24M

Owner directive (2026-07-29): the 20.64M full-resolution look beats the 18.51M subsampled one, so
**revert the subsample** (done: `b4f44f0` reverts `f53e99a`; every non-visual optimization is kept
— baseline re-measured at **20,641,469**). Then add **W2 walls** and a **really minor version of
textured floors**, staying **under 24M ops/frame**. Device stays dumb (0x0B column-runs + 0xFE
ditto only) — no new device semantics.

## Measured facts this plan rests on (E1M1 spawn, `scratchpad/w2_budget.py`)

| quantity | value |
|---|---|
| claimed columns / emitting / ditto | 160 / **67** / 93 |
| emit cost per (y2, colour) PAIR | **~3.7k ops** (20.64M − 17.95M emit-ablation over ~725 pairs) |
| pairs today | 67 wall + 236 ceiling + 422 floor = **725** |
| wall rows over emitting columns | 2230 (mean 33/col) |
| W2 **tiled** (real DOOM v-DDA) wall pairs | **2230** — one per row; ~8M. **REJECTED** |
| W2 **stretched**, unmerged | 929 |
| W2 **stretched + run-merged** | **410** (strips average 8.4 distinct colours of 16) |

Budget: 24.0 − 20.64 = **3.36M**. Plan spends ~1.9M, leaving ~1.4M of headroom.

## Rung 1 — W2S walls (est +1.3M → ~21.9M)

The 1×16 strip texels spread **evenly over each wall's [top,bottom] span** rather than tiled by
world height. Two reasons this is the shipping choice over exact tiling: tiling needs a texel
decision per ROW (2230 pairs, per-pixel cost), and stretching depends only on `(seg, top, bottom)`
— the **exact ditto key** — so the 93 ditto columns stay free.

- Bake per seg a **run-merged colour strip**: entries `[cum_band:1][colour:1]`, cum_band ∈ 1..16
  cumulative, colour = `colormap[light_row][texel]` folded at emit time. Mean 8.4 entries/seg.
  Stored in a static bank; the seg's xorby carries a baked **dw-offset** (same pattern as the
  band bank). Single-colour walls (83 segs) collapse to one entry = today's cost exactly.
- Emit per wall: `y2_j = top + ((cum_j * h) >> 4)` where `h = bottom - top + 1` — an exact integer
  form, **no divide** (the 1/16 is the `>>4`). Skip entries whose `y2` doesn't advance.
- Oracle mirror: new `wall_mode="W2S"` in `render_wall_frame` using the identical integer
  boundary formula, so fj vs oracle stays byte-exact and the existing W1/W2/textured tiers are
  untouched.

## Rung 2 — FT1 minor textured floors — SHIPPED as a ZERO-COST bake (+0.67M → 23,161,421)

⚠ **The design below changed during execution; this section records what actually shipped and why.**

*Planned (built, then discarded):* keep the band structure, switch the bank entry to `[y2][zrow]`,
bake a 64-texel strip per flat, and at emit time take `texel = strip[(x + off + band*13) & 63]`
with `off` a per-frame constant so the pattern slides with the camera. This was fully implemented
and debugged to byte-exact, then **measured at 27.1M — over the owner's 24M ceiling** — and
reverted. Two costs the plan under-priced: `ft1_colour` runs ~3.4k/pair (ptr_index + read_byte +
cm.emit + index math, on 658 pairs), and switching the bank to `[y2][zrow]` *splits* bands that
colour-merging had merged, adding pairs on top.

*Shipped instead:* sample the flat by **band ORDINAL** rather than by column — band j of a
half-window list takes the flat's j-th diagonal texel. Because the index no longer depends on `x`,
the texel is a compile-time function of the band, so it folds straight into the colour byte the
bank already bakes. **Runtime cost: zero ops.** The +0.67M against the W2S tier is purely the
slightly different band merging.

**Honest scope (unchanged):** depth-varying real texel colour, NOT perspective-correct floor
texturing. The pattern varies with distance, not world position, so it does not slide under the
player. True per-pixel u,v measured 3–9M and cannot fit the <24M budget.

## Outcome (all three tiers byte-exact vs their own oracle mirrors, 296-test suite green)

| tier | ops/frame | commit |
|---|---|---|
| W1 + flat | 20,641,469 | unchanged, still selectable and bit-identical |
| W2S + flat | 22,491,671 | `3f89fc4` |
| **W2S + FT1** | **23,161,421** | `d64563a` — the shipping look, under the 24M ceiling |

Gates: `tests/fj/test_lines_render.py` 4/4 (square 5 viewpoints incl. the negative-viewz straddle
+ E1M1 2 viewpoints, per tier). `scripts/walk_e1m1.py` defaults to W2S+FT1 and takes
`--wall-mode`/`--floor-mode` to switch. `measure_frame.py` accepts both new tier flags.

## Rollback

Both rungs are additive tiers behind emitter flags (`wall_mode="W2S"`, `floor_mode="FT1"`), so the
shipping 20.64M W1/flat configuration remains selectable and byte-exact throughout.
