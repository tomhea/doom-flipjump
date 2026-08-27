# M13-WPX — 1×1 pixel wall textures under 25M

Owner ask (2026-07-29): *"can the walls get 1x1 pixel textures? and still be about <25M. it
shouldn't be an exact replica of some model you have in mind, but rather just look good and use
some creative tricks to make it look alright and still be very fast."*

## What "1×1" costs, and why the obvious version is unaffordable

The dumb-device protocol (0x0B packed column-runs) takes `[x]` then `[y2][colour]` pairs, so a wall
column's price is its number of colour RUNS, not its pixel count. Two measurements set the budget:

- **Marginal cost of one strip entry ≈ 294k ops/frame** (measured: forced-length strips at N =
  1/4/16 gave 21.38M / 22.27M / 25.78M, a clean linear fit). The W2S tier walked ~7 entries/column.
- **The ditto columns are worth 4.83M** (measured: 23.17M with the ditto path on, 28.01M with it
  disabled — 58% of columns, ~52k ops each).

That second number kills the natural design. Sampling the texture column from the screen x (the
obvious way to get horizontal detail) makes a column's output depend on x, which breaks the
`[x][0xFE]` ditto records — at 4-pixel phase blocks that is ~23 broken dittos ≈ 1.2M ops, most of
the budget, for a *repeating* pattern that isn't perspective-correct anyway.

## The design that shipped

**Bake the run-list per (texture, light) × EXACT wall height.** A block is indexed by the column's
own height `wlen`, at a uniform stride, so the fj emit is one `mul_const` — no offset table, no
search. Each list is `[(rel, colour) × n][0][last_colour]`:

- `rel` is the run's end row *relative to the wall top*, so the emit is `y2 = ctake + rel` — **one
  add per run. No multiply, no v-DDA, no divide** (W2S needed a `mul_lo` + `shr_hex` per band).
- The last run always ends exactly at the wall bottom, which fj already holds in `fstart` — so its
  `rel` is never stored, which frees `rel == 0` to be the list **terminator**. No counter register,
  no per-run compare (worth ~160k ops/frame).
- Baking at the *exact* height is what makes it true 1×1: every boundary is pixel-exact, and short
  far walls self-limit (a 5px wall can hold at most 5 runs), so distant geometry stays nearly free.
- 575 E1M1 segs collapse to ~120 blocks — a texture at a given light always renders the same.

**Horizontal detail for free.** For a flat wall the screen height goes as `h ∝ 1/z`, and the DOOM
texture coordinate is affine in the depth `z` — so `u ∝ 1/h` is the *perspective-shaped* advance.
Since the bank is already indexed by height, deriving `u` from `h` (`wpx_texcol`) costs **zero
runtime ops and zero extra bank**, and — being a function of the clip rows alone — does not break a
single ditto column. The texture compresses exactly where the wall recedes. Measured cost: +61k
ops (0.26%). Head-on walls (constant `h`) keep one column, which is the honest limit of the trick.

**`WPX_RUN_CAP` (= 24) is the quality/ops knob.** Over budget, the *shortest* run is absorbed into
its neighbour, which drops single-pixel noise first and keeps the structural bands.

## Measured (E1M1, fj byte-exact vs the same-tier oracle at every point)

| viewpoint | W2S+FT1 (the tier this replaces) | **WPX+FT1** |
|---|---|---|
| spawn | 23,161,421 | **23,063,650** |
| (-480, 256, 0°) | 24,937,195 | **24,565,502** |
| (-309, -724, 90°) | 25,234,266 | **24,698,679** |
| (-309, 636, 0°) — worst found | 26,029,054 | **24,896,617** |

**True 1×1 texturing is cheaper than the 16-band stretch it replaces, at every viewpoint measured.**

⚠ **The old "<24M" claim was spawn-only.** A 63-viewpoint sweep (13 gate points + a 5×5×2 grid over
the whole map) shows W2S+FT1 actually reaches 26.03M away from spawn — it was over its stated
ceiling and nobody had measured it. WPX+FT1's worst over the same 63 viewpoints is 24,896,617,
under the 25M ask but by only 0.4%; a viewpoint outside the sample could exceed it. Lowering
`WPX_RUN_CAP` is the direct lever (cap 40 measured 25.00M worst on the narrow sweep, cap 24 saves
~0.3M and ~1.1M more is available at a 2px minimum run, at a visibly flatter look).

## Rejected, with the measurement that rejected it

- **x-derived texture phase** — breaks the ditto records, ~1.2M ops at 4px blocks (see above).
- **Height CLASSES instead of exact heights** — the last run would stretch to fill the remainder,
  up to 15% of a tall wall's height. Exact heights cost nothing extra (the bank is ~582k words).
- **2px minimum run length** — halves the run count (17.3 → 9.3 average, ≈1.1M ops) but visibly
  flattens the walls; the 1px grain is what reads as texture at 160×100. Rejected as against the
  ask, not as unaffordable.

## M13-WPXLIGHT — making depth readable (owner: "hard to distinguish close and far walls")

Owner report after first playing it: *"there is not a clear difference between walls... sometimes
it's hard to distinguish close and far ones, the outlines aren't strong or don't exist... difference
between far wall and a close column, for example too."*

**This was a fidelity gap, not a style choice.** Real DOOM has TWO cues for exactly this, and this
renderer had neither — walls were shaded by their sector's light level alone, dead flat from the
player's nose to the horizon (`light_row = sec.light >> LIGHT_SHIFT`, at every wall tier):

1. **`scalelight` (R_RenderSegLoop)** — DOOM shades each wall column by its projection scale:
   `dc_colormap = walllights[rw_scale >> LIGHTSCALESHIFT]`. Nearer column, larger scale, brighter
   row. This is what separates a close column from a far wall. Our floors already had the sibling
   `zlight`; the walls had nothing.
2. **Fake contrast (R_StoreWallRange)** — `lightnum--` for an east-west wall, `lightnum++` for a
   north-south one. It is *called* fake contrast in the DOOM source, and it exists precisely so two
   walls meeting at a corner don't render as one flat expanse with no visible edge.

So the answer to "do DOOM players complain about this?" is no — DOOM solves it, and we had skipped
both halves of the solution. Nothing here is an invented effect; both are ported.

**Both are FREE, by the same lever as `wpx_texcol`.** Fake contrast is per-seg and orientation-only.
Distance light needs the column's scale — and `h ≈ wall_units * scale >> 16`, so scale is recoverable
from the height the bank is ALREADY indexed by, provided the sector's ceiling-to-floor span is part
of the block key. So the block key goes from (texture, light row) to (texture, **light level incl.
contrast**, **wall span in map units**), each baked height looks up its own `scalelight` row, and the
runtime op count does not change at all — only which colour byte was baked.

| | before | after |
|---|---|---|
| E1M1 spawn | 23,063,650 | 23,309,174 (+1.1%) |
| worst of 63 viewpoints | 24,896,617 | **24,843,494** (slightly cheaper) |
| bank blocks / words | 120 / 582k | 185 / 897k (1.5x) |

⚠ **The one approximation, stated plainly:** `h` is the CLIPPED on-screen height, so a wall running
off the top or bottom of the view reports less than its true extent and is shaded as if further
away. It affects only the very nearest walls, it is constant down each such column, and it stays
monotone in `h` — near still reads brighter than far, which is the cue that was missing. Exact
scale would need the UNCLIPPED height as the bank index, which costs a per-run clip compare in the
fj emit (the current emit relies on the list spanning exactly `[ctake, fstart)`).

Also faithful-by-accident: `startmap` is 0 for a fully-lit sector, so DOOM gives such sectors no
wall falloff whatsoever. That is DOOM's behaviour, reproduced, not a bug to fix here.

## Gates

`tests/fj/test_lines_render.py` — `test_square_lines_wpx_ft1_byte_exact_vs_oracle` (5 square
viewpoints incl. the negative-viewz straddle) and `test_e1m1_lines_wpx_ft1_byte_exact_vs_oracle`
(E1M1 spawn + rotation, asserts the 25M ceiling). The W1/flat and W2S/FT1 tiers are untouched and
still selectable via `--wall-mode` / `--floor-mode` in `scripts/walk_e1m1.py` and
`scripts/measure_frame.py`; WPX is the new walker default.
