# Handoff — M13-2S rung 3c: two-sided walls at 20–30M

**The job: keep the two-sided geometry, lose 100M ops.** Rung 3b (`two_sided=True`, commits
`c086a20`/`08e86b6`) is byte-exact vs `ReferenceModel.render_frame_2s` but costs **131,060,211
ops/frame** at E1M1 spawn against a shipped tier at **21,730,429**. The owner's ruling:

> *"the speed is crazy!! it should be in the 20M~30M, and it jumped to 130M, not acceptable. get to
> this level, in the expense of visual-accuracy (but still leave visual-clearness — i.e. where is the
> wall leading, clear difference between wall and floor and ceiling and other walls)."*

So this rung may render something DIFFERENT from `render_frame_2s`. It may not be unreadable, and no
claim in it may be unmeasured.

> ⚠ **This document is v2.** v1 proposed "keep exactly one upper and one lower run per column" and
> budgeted ~36M. Measuring it against E1M1 (`scratchpad/rung3c_check.py`) broke three of its
> assumptions — see §3. The design below is what survived.

---

## 1. ⚠ Correct the cost model first — `@` is 25–30 ops, not 150

An earlier session inferred `@ ≈ 150` by dividing a measured total by a MODELLED visit count, and
then blamed rung 3b's cost on its region buffer. **The owner corrected it: `@` is 25–30 ops.** With
`@ = 27` the same measurement (per-column body 88.8M over ~1,120 column visits = 79,286 ops =
2,937@ each) blames something else:

| per-column item | @ | ops |
|---|---|---|
| **`column_params_m` once** (two 6-row muls + the folds) | ~720 | **19,440** |
| **`column_params_m` twice** (a two-sided seg with an upper or lower) | ~1,440 | **38,880** |
| one buffered region (5 `write_byte_and_inc` + count r/w + offset lookup) | ~330 | 8,910 |
| `col_state_load` / `col_state_store` | 92 / 108 | 2,484 / 2,916 |
| the two row clamps | 120 | 3,240 |

**The per-column PROJECTION is ~43.5M of the 88.8M; the region buffer is ~23M.** Plus the flush's
expansion at ~40M and a BSP walk that is only **4.83M** (ablate `colstub`).

---

## 2. ★ The lever v1 missed: DOOM does not multiply per column

`column_params_m` computes `top = centery - (worldtop * scale >> 16)` with a 6-row multiply, once per
column per seg. DOOM instead keeps `topfrac` in 16.16 and adds a per-seg `topstep`:

```
topstep  = -FixedMul(worldtop, scalestep)          once per seg
topfrac  =  centeryfix - FixedMul(worldtop, scale_at_x1)
per column:  top = topfrac >> 16 ;  topfrac += topstep
```

Same shape as the existing `wall_scale_setup`/`scale += scalestep` the renderer already trusts. Cost
per column: **~120@ ≈ 3.2k ops instead of ~720@ ≈ 19.4k — 6× cheaper**, and it needs four accumulators
(front ceil/floor, back ceil/floor) instead of two `column_params_m` calls.

It is NOT bit-identical to the per-column multiply (different rounding, occasionally ±1 row), so the
ORACLE adopts it too and the gates stay byte-exact against the new oracle. This is the single biggest
item in the whole rung and it also would have halved rung 3b — do it FIRST, and measure it on the
shipped rung-3a tier before touching anything else (rung 3a runs ~160 of these a frame; expect ~−2M
there alone, byte-exact only against a re-blessed oracle).

---

## 3. What the measurements did to v1 of this plan

`scratchpad/rung3c_check.py`, five E1M1 viewpoints:

| finding | number | consequence |
|---|---|---|
| "nearest upper/lower only" drops runs | **707 of 1,615 = 44%** (56% at (−309,−44)) | v1's core rule is too lossy — staircases lose most risers |
| the naive splice goes NON-MONOTONE | **296 columns** (mostly lowers: 23–69 per viewpoint) | a near step's face overlaps the closing wall's band; needs an occlusion-correct clamp, and it is not an edge case |
| closed doors that would self-close a column | 0–5 columns | v1's "free win" is not one; drop it from the design |
| columns never closed by a one-sided wall | 0 | rung 3a's black-column case doesn't bite at these viewpoints |

Distribution of runs per column at spawn: uppers `{0:76, 1:34, 2:34, 3:16}`, lowers
`{0:80, 1:55, 2:12, 3:9, 4:4}`. So **two slots per side captures the large majority**; three captures
nearly all.

Because §2 makes per-column projection 6× cheaper, more slots are now affordable — which is exactly
the trade v1 could not make.

---

## 4. The design

Keep rung 3a's frame whole — it ships at 21.7M and the owner approved its look — and splice in the
**nearest K upper and K lower runs per column**, held in write-once slots. Start with **K = 2** and
measure; K is a compile-time constant, so K = 1 and K = 3 are one rebuild away.

### Per-column state (replaces rung 3b's entry lists, its flush pass, and its buffer entirely)

Per column, per side, K slots of `[blk:2][y1][y2]` = 4 bytes; K=2 ⇒ 16 bytes/column, 2,560 total.
Slots fill nearest-first (the walk is front-to-back), and a seg whose slots are all full costs one
`read_byte` and a branch.

### The emitted record, in one pass at claim time

Every piece is known when the one-sided wall closes the column, so **there is no buffer and no flush
pass**, the emit stays inline exactly like rung 3a, and rung 3a's ditto path keeps working:

```
ceiling bands [0, u1_y1)            near sector's baked list        (rung 3a)
upper run     [u1_y1, u1_y2)        nearest upper, WPX for its exact height
ceiling bands [u1_y2, u2_y1)        same list, SUB-RANGE walk       (rung 3b machinery, reuse it)
upper run     [u2_y1, u2_y2)        second-nearest upper
ceiling bands [u2_y2, wall_top)
wall          [wall_top, wall_bot)  the one-sided wall
lower runs + floor bands            mirrored, bottom-up
```

### ⚠ The splice must be OCCLUSION-CORRECT, not naive (296 columns depend on it)

The step faces are NEARER than the wall that closes the column, so where they overlap, the step wins
and the wall shrinks:

```
wall_top = max(ctake, last_upper_y2)      wall_bot = min(fstart, first_lower_y1)
```

and every piece is emitted only if its range is non-empty, with each piece's start clamped to the
previous piece's end so the y2 sequence is strictly monotone (the 0x0B device only moves its cursor
forward — a non-monotone pair paints nothing and the error is silent).

### ⚠ The ditto test must include the slots

Rung 3a's ditto compares `(cexcl, fstart)` and the plane pid. Two adjacent columns can share those
and differ in their steps, so the comparison grows by the K×2 slots (or by a per-column signature
byte maintained at fill time — cheaper, and it is the same trick as `pclm`).

### What is kept and what is traded

**Kept (the owner's "visual clearness"):** step faces, ledge fronts and door frames — you can see
where a wall leads; walls keep their WPX texture, scalelight row and fake contrast; planes keep their
zlight distance banding, so wall/floor/ceiling stay distinct; rung 3a's near-floor fix untouched.

**Traded:** only the nearest K steps per column (at K=2, ~20% of runs are dropped rather than v1's
44%); plane regions are not per-seg, so a distant room's floor is shaded with the near sector's
surface (rung 3a's approved behaviour, not a new regression); nothing behind the first two-sided
boundary is drawn; ±1-row differences from the incremental projection.

---

## 5. Budget — and an honest answer about "20M"

| item | ops |
|---|---|
| rung 3a as it ships | 21.7M |
| + slot fills, ~1,000 contributing column visits × ~200@ (incremental projection + clamps + writes) | 5.4M |
| + step faces, WPX textured (~180 runs × ~10 pairs) | 4.4M |
| + the extra band sub-ranges around them | 1.0M |
| **= textured** | **~32M** |
| **= with flat-shaded step faces** (one pair per run instead of the WPX list) | **~28.5M** |

Minus whatever §2's incremental stepping gives back on rung 3a's own ~160 projections (~−2M).

**So: ~26–30M at spawn is realistic; 20M is not, without also making rung 3a itself cheaper.** The
honest framing for the owner is "the low end of your band needs a second rung on the 3a path", and
§2 is the obvious candidate there too. Do not promise 20M on the back of this design; measure at
3c-4 and report the number.

Worst-of-65 will be higher than spawn (rung 3a's worst is 26.55M vs 21.73M spawn — a 1.22× factor),
so expect **~32–37M worst** and be ready to spend one of these, in order: flat-shaded faces (already
counted), K=1 for the uppers only (lowers are the common case in E1M1 and read as steps), then drop
runs shorter than 2 rows.

---

## 6. Ladder

| rung | what | gate |
|---|---|---|
| 3c-0 | **incremental per-column projection** (§2) on the SHIPPED rung-3a path, oracle first | re-blessed rung-3a goldens; measure the delta; full suite |
| 3c-1 | oracle: `render_wall_frame(..., near_steps=K)` — the slots, the occlusion-correct splice, and the flat-shade flag | host gates: near floor still 1 surface at spawn; step count vs `render_frame_2s`; a PNG for the owner |
| 3c-2 | fj: the per-column slots + write-once fill in the two-sided leaf, nothing read yet | byte-exact vs rung 3a — proves the fill has no side effects |
| 3c-3 | fj: the emit splice | byte-exact vs the 3c oracle, square room + E1M1 |
| 3c-4 | flat-shade, the 2-row floor, K sweep, 65-viewpoint sweep | worst < 30M if it can be had; full suite; report the real number |

Reusable from rung 3b (written and gated already): `stream.band_range` (the general sub-range band
walk), `stream.wall_run`, the WPX bank's upper/lower blocks (`_lines_wall_pix_bank(..., two_sided=)`,
622 blocks on E1M1), the per-seg `seg_flags`/`bceilfix`/`bfloorfix`/`seg_wsupper`/`seg_wslower` bakes,
and the `entoff` dispatch. Rung 3b stays in the tree as the ACCURACY reference (`--two-sided`), with
`render_frame_2s` as its oracle.

---

## 7. Will it ship?

That is the owner's call and it turns on one thing: **at K=2 a staircase seen along its axis shows
its two nearest risers and then a smooth distance-shaded floor.** That is the visual risk of the
whole design, and it is worth putting a PNG of exactly that case (E1M1's stairs) in front of the
owner at rung 3c-1 — *before* the fj work — because if it reads badly, the answer is a different
trade (e.g. per-seg plane regions but no upper/lower textures), not a tuning knob.

The rest of the picture is unaffected: near floor correct, walls/floors/ceilings distinct, steps and
door frames present.

---

## 8. Pitfalls that already cost build cycles (5–10 min each)

- **`mul_const` / `ptr_index` read `w/4` nibbles of their source** — zero-extend a 2-nibble register
  first (fj-lessons R11). Symptom: `term=ip<2w`, frame all zeros.
- **A macro body inlined in a loop must `;end` over its own scratch `hex.vec` data** (lesson #2).
- **`hex.set n` is @+4 but `hex.mov n` is n(2@)** — set from a constant, don't mov.
- **Multiplying a COUNT by `5*dw` instead of 5** ran a compare loop 320× too long. `dw` belongs in
  address arithmetic only.
- **DOOM's upper-wall end is `ub`, with NO +1** (`min(ub - 1, win_lo)` is inclusive) — 644 pixels.
- **The square room has no two-sided linedefs**, so it cannot catch a bug in the two-sided path; only
  E1M1 exercises it. It is still the right first gate for everything else.
- **Price before building** (R23/R32/§13): both of this rung's course corrections came from a
  10-minute host measurement, not from a build.
