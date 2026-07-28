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

## Rung 2 — FT1 minor textured floors (est +0.6M → ~22.5M)

Keep the distance-light band structure exactly as today (236+422 pairs, no new pairs); change only
where each band's COLOUR comes from.

- The baked band bank switches its entry from `[y2][final_colour]` to `[y2][zrow]`.
- Bake per flat a **64-entry texel strip** sampled from the real flat.
- Emit: `texel = strip[(x + off + band_index*13) & 63]`, `colour = cm.emit(zrow<<8 | texel)`.
  `off` is a **per-frame constant** derived from viewangle/viewx/viewy, so the pattern slides as
  the camera moves/turns instead of being welded to the screen.
- Cost per band pair: +1 read (~600) + index build (~200) + cm.emit vs byte.emit (~+50) ≈ **+850**.
- **Honest limitation, to state plainly to the owner:** this is a *moving pattern sampled from the
  real flat*, NOT perspective-correct floor texturing. True per-pixel u,v costs 3–9M (measured
  reasoning in the campaign notes) and cannot fit under 24M. FT1 buys "the floor has texture and
  it moves with you"; it does not buy "the texture is nailed to the world".

## Execution order (each rung: implement → square smoke → E1M1 measure → gate → commit)

1. Bank + oracle for W2S; fj emit; measure; `test_lines_render` extended with a W2S gate.
2. Band-bank format change to `[y2][zrow]` + flat strips + FT1 emit; measure; gate.
3. PNG set (W1/flat today vs W2S+FT1) sent to the owner; full-suite certification; push.

## Rollback

Both rungs are additive tiers behind emitter flags (`wall_mode="W2S"`, `floor_mode="FT1"`), so the
shipping 20.64M W1/flat configuration remains selectable and byte-exact throughout.
