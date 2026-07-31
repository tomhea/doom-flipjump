# Session handoff — the four visual features (V1-V3 shipped in fj, V4 half-landed)

**Branch:** `m13opt3-early-out`.

---

## 1. Where the frame is

| build | spawn | courtyard (1400,1200) | worst (-309,-44) |
|---|---:|---:|---:|
| session start (pre-V1) | 21,736,934 | — | 26,557,125 |
| M13-XTADISP | 20,594,618 | — | 25,319,870 |
| V1 grain + V2 sky | 23,536,484 | 20,134,978 | 26,405,793 |
| **+ V3 step faces** | **26,545,502** | **27,604,046** | **32,137,393** |

All three **BYTE-EXACT** vs `render_wall_frame(..., wall_noise=True, sky=True, near_steps=True)`
(`scratchpad/v3_check.py`), and the full suite is green: **`tests/fj/test_lines_render.py` 11/11
passed in 13:51** on this tree. The worst viewpoint sits inside the owner's accepted 30–35M band but
with ~3M of headroom, and V4 is priced at +2.8M — see §4 before starting it.

---

## 2. What shipped this session

### V3 — step faces (fj), byte-exact, +3.01M / +7.47M / +5.73M

Three parts, and each one moved for a measured reason:

**RECORD** — `frame.ts_step_faces` (`src/fj/frame_render.fj`). `seg_pass1_leaf_body_ts` had **no
projection machinery at all**, so V3 is a projection path *added* to a claim walk. Per face-carrying
boundary: `proj.wall_setup_sgn` + `proj.wall_scale_setup_m` (~93k — exactly what
`STEP_SEG_BUDGET = 12` gates), then per column two `proj.step_rows`.

`proj.step_rows` is `column_params_m` **without its two clips**, and the clips genuinely had to go:
a face is bounded by a different pair of world heights than the wall's, and its emptiness test
compares the two RAW rows — `column_params_m` clamps `bottom` to `VIEW_H-1`, which silently loses
the one row a face reaching the bottom of the ceiling region needs (`min(H-2, B)` for `min(H-1, B)`).

**STORE** — a slot is bytes, so emptiness is decided at record time:

```
valid  <=>  A <= B  and  B >= 0  and  A <= VIEW_H-1
store  =    (max(A, 0), min(B, VIEW_H-1))
```

`scratchpad/v3_slotmodel.py` proves that identical to the oracle's store-raw-then-clip at five
viewpoints — **before** a build was spent on it, and it also asserts each clipped face lands strictly
inside its own region, which is what keeps the emitted column monotone.

**EMIT** — `stream.emit_col_lines`. `pwalk` and `swalk` collapsed into ONE `qwalk` over a window
`[qlo, qbound)` plus `half_walk` (which half-lists to walk). The ceiling prefix and floor suffix are
special cases of it, and the face splice needs it anyway: the list is **re-walked from its head**,
not resumed, because the 0x0B cursor only moves forward — re-emitting an already-covered pair would
rewind it and repaint over the face.

### V4 — the THINGS oracle (`render_wall_frame(..., things=True, sprite_wad=...)`)

Renders E1M1's 292 things as billboards: 849 px / 53 columns at the courtyard, 2,013 px / 119
columns at the tree viewpoint (`scratchpad/v4_oracle.py` → `scratchpad/v4_things.png`).
**Every decision in it was made so the fj can follow it** — see §4.

⚠ The test fixture wad has NO sprite lumps (223 lumps, no `S_START`). Sprite art comes from
`assets/freedoom1.wad` via a separate `sprite_wad` argument; geometry, flats and colormap stay on
the fixture so nothing else moves.

---

## 3. The two numbers that were wrong, and why

1. **V3 was priced at +1.3M / +2.7M; it is +3.0M / +5.7M.** The estimate counted the projections and
   the setups but not the columns they run over, and not the ditto. Populations are now measured —
   `scratchpad/v3_pop.py`: 2 face segs / 54 face columns at spawn, 12 / 262 at the courtyard,
   12 / 79 at the worst.

2. **The ditto chain must COMPARE the face state, never refuse the ditto.** The first working build
   refused it (`stv != 0 → no ditto`), stayed byte-exact, and cost **+4.06M / +9.16M**. At an outdoor
   viewpoint nearly every column carries a face, so "no ditto on a face column" is "no ditto", and
   ditto is worth ~4.8M. Comparing the six emit inputs (`uy1, uy2p1, ucol, ly1, ly2p1, lcol`,
   **zeroed** when absent so a stale value cannot make two identical columns compare different)
   recovered 1.05M / 1.69M / 0.46M. **This is the fourth feature to hit the ditto chain
   (`dgchk`); V4's fragments will be the fifth.**

Also settled: the ORACLE now **interpolates** the face scale across the seg (one setup, then
`+= scalestep` per column) rather than calling `scale_from_global_angle` per column. That is what
DOOM does and the only affordable option — ~40k fj ops per COLUMN against ~93k once per SEG.
Measured effect: 1 of 108 projected rows moves at spawn, 10 of 210 at the worst viewpoint.

---

## 4. V4 — what is done, what is left

### Done and committed

* **Increment A — the RECORD half, in fj, BYTE-EXACT at four viewpoints** (`scratchpad/v4_check.py`).
  Nothing reads `spslot`/`sprflag` yet, so the frame must equal the V3 frame — which makes the ops
  delta the record half's price on its own, with none of the "a stub prices itself plus everything
  downstream" contamination:

  | viewpoint | ops | vs V3 |
  |---|---:|---:|
  | spawn | 25,689,298 | −856,204 |
  | courtyard | 28,722,844 | +1,118,798 |
  | tree (2432,1344) | 25,058,919 | — |
  | worst (-309,-44) | **36,992,405** | **+4,855,012** |

  ⚠ **Two things to read off this before writing increment B.**
  (a) The worst viewpoint is now **37.0M, over the owner's 35M ceiling, with the emit half still to
  come.** `THING_BUDGET = 24` projections at ~60k each is only ~1.4M of that +4.86M; the rest is the
  per-column record loop (two byte reads per scanned column, over up to 24 things' full column
  ranges) at a viewpoint where the view never closes so `n_claimed == VIEW_W` never fires. Trim
  before adding emit: lower the budget, or stop the loop once every column is drawn or fragmented.
  (b) spawn came out **cheaper**, which no added work can be — the program grew 36.2M → 41.7M
  characters and that is layout drift at the few-percent level. Do not read a −856k as a saving;
  the honest statement is "unchanged at spawn within layout noise".

* **The oracle**, with every fj-forced decision already taken:
  * fragments are recorded **during the walk**, at the moment it reaches the thing's own subsector,
    and only into columns no wall has claimed yet. Front-to-back order is what makes "the first
    writer is the nearest" true **and** is the entire occlusion test — the same trick V3 uses, and
    the reason a write-once forward-only column protocol can show sprites at all (DOOM draws them
    last, back-to-front, and this cannot).
  * sprite columns bake per **(sprite, downscaled column, height BUCKET)** —
    `SPRITE_HEIGHT_BUCKETS = 32`. Exact heights (the WPX wall bank's shape) would be ~17M characters
    against a program already at 36M and an assembler that is ~cubic.
  * texels are stored **RAW** and colormapped at emit through `cm.emit` (V1's grain mechanism), so
    one bank serves all 16 light levels instead of being multiplied by them.
  * **interior transparent gaps take the nearest opaque texel above.** Not aesthetics — a
    transparent run in the middle of a fragment would need background the emit has already passed.
  * **one overlay per column, and the sprite wins**: a column with a fragment draws no step face.
  * `THING_BUDGET = 24` bounds the per-frame projection cost the way `STEP_SEG_BUDGET` bounds V3.
* **`wall_renderer._lines_sprite_bank`** — the bank generator. Measured: 31 sprite kinds,
  17,216 blocks, **5.08M characters** (program 36M → ~41M).
* **`proj.project_thing`** — R_ProjectSprite in this repo's fixed point (one `hex.fixed_div` ≈ 38.5k
  plus a block-FP reciprocal and five multiplies ⇒ ~60k per thing), wired and running.

### Left to do — increment B, the EMIT half

1. **Trim the record half first.** Worst is 37.0M against a 35M ceiling and the emit is still to
   come. The 24 projections are only ~1.4M of the +4.86M; the rest is the per-column loop's two byte
   reads over up to 24 things' full column ranges, at a viewpoint whose view never closes so
   `n_claimed == VIEW_W` never fires. Either lower `THING_BUDGET`, or add the missing early-out:
   stop when every column is drawn OR fragmented (count fragments, and stop the walk the way
   `tsstop` stops the two-sided claim).
2. **The emit splice** — the part V3 did NOT have to do. A sprite straddles the ceiling region, the
   wall and the floor region, so a fragmented column becomes `region(0, sy1)` + the sprite runs +
   `region(sy2+1, VIEW_H)`, where `region(lo, hi)` is the ceiling `half_walk`, a **windowed**
   `wpx_wall`, and the floor `half_walk`. Keep the existing no-sprite path untouched beside it —
   the wall run-list walk is where most of the frame's pairs are and it must not get slower.
   The sprite runs go out through `cm.emit` with the fragment's shade row in the high byte (V1's
   grain mechanism), but from a **separate index register** — reusing the grain's `cmidx` would give
   the wall emitted after the sprite the sprite's light row.
3. **The `dgchk` ditto entry** — the FIFTH feature to need it. Compare the fragment's stored values
   (zeroed when absent); do NOT refuse the ditto (§3.2).

The fragment layout already in the tree: `sprflag[x]` one byte, `spslot[x]` =
`[sy1][sy2p1][y0+128][blk_lo][blk_hi][shade row]` at a 16-byte stride. `y0` is biased by 128 because
a near sprite's top sits above row 0 (h ≤ VIEW_H bounds it to ±99). A block is
`[r0][last_rel][n][(rel_end, RAW texel) × n]` at a 32-dw stride — `r0`/`last_rel` are in the header
precisely so the record half can bound the fragment with two byte reads instead of pre-walking.

### Before starting: the headroom question

V4's record half alone put the worst viewpoint at 37.0M — **already past the ceiling**, and the
+2.8M V4 estimate was for the whole feature. This is now a blocker, not a caution. The
paydown levers, in order, are still: `slopediv_recip`'s `read_table_packed 3` → dispatch (the 4th
application of the conversion that paid −1.14M), a ROW-RULE operand-order check on
`column_params_m`'s two multiplies (160 calls × 11.9k), and the two `hex.fixed_div 8,4` in
`wall_scale_setup_m` (2.16M/3.93M — the single biggest item in the frame).

---

## 5. Lessons this session added

1. **An unused macro PARAMETER is a hard assembler error, exactly like an unused label.** Two builds
   were lost to `sh_idx`/`sh_p` missing from a `@` list and to a `vieww` parameter I stopped using.
   `scratchpad/`-style parse-only check (assemble the fj sources against a two-line `main`) costs
   ~40 seconds and catches all of it — **run it before every real build.**
2. **`fj.assemble` reads the `.fj` files when it is CALLED, not when the script starts.** Editing a
   shared `.fj` while a verification build is in flight killed a 10-minute run with a syntax error
   from a feature that build does not even use. Python modules are safe (imported once); `.fj` is not.
3. **A performance number from a byte-exact build can still be the wrong design.** The refuse-the-ditto
   build was byte-exact at all three viewpoints and 4M too expensive. Byte-exactness proves
   correctness, not that the mechanism is the right one.
4. Everything in `docs/handoff-visual-features.md` §5's lesson list still holds — in particular
   **the consumer's format is the specification**, which is why `qwalk` had to be a generalisation of
   the existing walkers and not a new path beside them.

---

## 6. Where to start

1. `python -m pytest tests/fj/test_lines_render.py -q` — the 11-test gate, ~17 min.
2. The parse-only check (§5.1) before every build.
3. V4 per §4, in increments: **the record path first with nothing reading the fragments** (that is
   byte-exact against today's oracle and prices the record half alone), then the emit.

Probes: `scratchpad/v3_check.py` (three viewpoints, the V3 gate), `scratchpad/v3_pop.py`
(populations), `scratchpad/v3_slotmodel.py` (the storage model, no build needed),
`scratchpad/v4_oracle.py` (the things oracle + its pair/ditto deltas),
`scratchpad/default_build_check.py` (the flag-off build).
