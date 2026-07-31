# Handoff — M13-2S rung 3c: two-sided walls at 20–30M

**The job: keep the two-sided geometry, lose 100M ops.** Rung 3b (`two_sided=True`, commits
`c086a20`/`08e86b6`) is byte-exact vs `ReferenceModel.render_frame_2s` but costs **131,060,211
ops/frame** at E1M1 spawn against a shipped tier at **21,730,429**. The owner's ruling:

> *"the speed is crazy!! it should be in the 20M~30M, and it jumped to 130M, not acceptable. get to
> this level, in the expense of visual-accuracy (but still leave visual-clearness — i.e. where is the
> wall leading, clear difference between wall and floor and ceiling and other walls)."*

So this rung is allowed to render something DIFFERENT from `render_frame_2s`. It is not allowed to be
unreadable, and it is not allowed to be unmeasured.

---

## 1. ⚠ Correct the cost model first — `@` is 25–30 ops, not 150

An earlier session (this one) inferred `@ ≈ 150` from a division and then blamed rung 3b's cost on
the region buffer. **The owner corrected it: `@` is 25–30 ops.** Everything below uses `@ = 27`, and
it moves the blame:

| per-column item | cost | ops at @=27 |
|---|---|---|
| `col_state_load` (2 `read_byte` + ptr moves) | 92@ | 2,484 |
| **`column_params_m` ONCE** (two 6-row muls + the folds) | ~720@ | **19,440** |
| **`column_params_m` TWICE** (a two-sided seg with an upper or lower) | ~1,440@ | **38,880** |
| the two row clamps | 120@ | 3,240 |
| one region append (5 `write_byte_and_inc` + count r/w + offset lookup) | ~330@ | 8,910 |
| `col_state_store` | 108@ | 2,916 |
| pointer steps + loop | 90@ | 2,430 |

Measured: the per-column body is **88.8M over ~1,120 column visits = 79,286 ops (2,937@) per visit**,
and the model above lands at ~63k for a visit with two projections and ~1.5 appends. Close enough to
name the villain:

- **the per-column PROJECTION is ~43.5M of the 88.8M** — `column_params_m`, run once per column per
  seg and TWICE for two-sided segs that have an upper or a lower;
- the region buffer round-trip (append + flush read, ~1,600 entries) is **~23M**;
- everything else in the body is ~20M.

Plus the flush's band/run expansion at **~40M**, and a BSP walk that is only **4.83M** (ablate
`colstub`).

**The lever is therefore the NUMBER of per-column projections, not the buffer.** Rung 3b projects for
every marking seg × every column it covers. Rung 3a projected only for the ~160 columns it emitted.

---

## 2. The design: keep rung 3a's frame, splice in the NEAREST step per column

Rung 3a already ships at 21.7M and the owner approved its look. Rung 3c keeps it whole and adds the
one thing rung 3b is actually for — the wall faces of two-sided boundaries — under a hard rule:

> **Per column, at most ONE upper run and ONE lower run: the nearest one. Plane regions stay exactly
> as rung 3a computes them (one ceiling + one floor per column, attributed to the nearest marking
> seg).**

That rule is what buys the 100M, because it converts "project every seg at every column" into "the
first wall-drawable seg to reach a column projects it, everyone after reads one byte and leaves".

### What the frame is made of, per column

```
[ceiling bands 0 .. up_y1)         from the near sector's baked band list  (rung 3a)
[upper run    up_y1 .. up_y2)      the NEAREST upper, WPX list for its exact height
[ceiling bands up_y2 .. ctake)     same list, sub-range walk                (rung 3b machinery)
[wall         ctake .. fstart)     the one-sided wall that closes the column (rung 3a)
[floor bands  fstart .. lo_y1)     near sector's floor list, sub-range
[lower run    lo_y1 .. lo_y2)      the NEAREST lower
[floor bands  lo_y2 .. VIEW_H)     same list, sub-range
```

Every piece is known **at claim time** (when the one-sided wall closes the column), because the
upper/lower slots were filled earlier by nearer segs. **So there is no per-column region buffer and no
flush pass at all** — the record is emitted inline exactly like rung 3a, which also means rung 3a's
ditto path keeps working unchanged.

### Per-column state (replaces rung 3b's 5-byte entry lists)

Two fixed slots per column, write-once (first writer is the nearest):

| field | bytes | meaning |
|---|---|---|
| `up_blk` | 2 | WPX bank block index of the nearest upper (0 = none) |
| `up_y1`, `up_y2` | 2 | its row range, exclusive end |
| `lo_blk` | 2 | ... and the same for the nearest lower |
| `lo_y1`, `lo_y2` | 2 | |

8 bytes per column, 1,280 total. A seg that finds both slots already filled costs **one `read_byte`
plus a branch** and skips its projection entirely.

### What is kept and what is lost, stated plainly

**Kept (the owner's "visual clearness"):**
- step faces, ledge fronts and door frames appear — you can see where a wall leads;
- walls, floors and ceilings stay distinct: the wall keeps its WPX texture and its scalelight row,
  the planes keep their zlight distance banding;
- rung 3a's near-floor attribution (the fix the owner asked for) is untouched;
- fake contrast on every wall run.

**Lost (the "visual accuracy" being traded):**
- only the nearest step per column — a staircase seen edge-on shows its first riser, not all four;
- plane regions are not per-seg: a column's floor/ceiling bands use the NEAR sector's height, light
  and flat for the whole strip, so a distant room's floor is shaded as if it were the near one's
  surface (this is precisely rung 3a's approved behaviour, not a new regression);
- windows/openings deeper than one boundary are not walked, so nothing behind the first two-sided
  boundary is drawn.

---

## 3. The budget, computed the same way §1 was

| item | count at spawn | unit | ops |
|---|---|---|---|
| rung 3a as it ships today | — | — | **21,730,429** |
| per-column projection for wall-drawable segs (first writer only) | ~320 column-first-touches | 720@ | ~6.2M |
| the write-once slot reads for everyone else | ~800 visits | ~40@ | ~0.9M |
| upper/lower run emission (WPX pairs) | ~252 runs × ~10 pairs | ~90@/pair | ~6.1M |
| the extra band sub-ranges around the runs | ~160 columns × 2 | ~110@ | ~0.9M |
| **projected total** | | | **~36M** |

That is over the target, so the rung ships with two more accuracy trades already designed. Apply them
in order and stop when the sweep is inside 30M:

1. **Flat-shade the step faces** (`up`/`lo` runs emit ONE pair — the block's mid-texel at the run's
   scalelight row — instead of the WPX 1×1 list). Removes ~5.5M of the 6.1M. A step face becomes a
   solid shaded band, which still reads as "there is a face here, this wall leads up/down"; the
   TEXTURE detail on it is what is lost. **Do this one first — it is the cheapest 5M in the design.**
2. **Skip runs shorter than 2 rows.** Distant hairline steps vanish; they were sub-pixel noise.
   Worth ~0.5M and it also cuts the number of columns that project.
3. If still over: **cap the projections per frame** (a `PNEAR_SEG_BUDGET`-style bound on the
   wall-drawable segs, nearest-first). ⚠ The owner disliked forcing that knob for rung 3a — reach for
   it last, and report what it costs visually rather than silently lowering it.

With (1) and (2): **~30M at spawn**, and the heavy viewpoints scale with the same rung-3a factor
(worst-of-65 was 26.55M for rung 3a, so expect ~34M worst — measure, don't assume).

---

## 4. The oracle comes first, and it is a NEW mode

Rung 3c does not match `render_frame_2s`, so **it needs its own oracle** — and the fj must be
byte-exact against it, exactly like every other tier here. Add to `ReferenceModel`:

```python
render_wall_frame(..., plane_near=True, near_steps=True)   # rung 3c
```

i.e. extend the SHIPPED rung-3a path (not `render_frame_2s`) with:
- the per-column `up_*`/`lo_*` write-once slots, filled while walking marking segs front-to-back
  using the same `wall_screen_span` calls rung 3b uses (front.ceil→back.ceil for the upper,
  back.floor→front.floor for the lower);
- the splice into the emitted column (the 7 pieces in §2), with the same clamps;
- the flat-shade option from §3.1 behind its own flag so the trade is measurable, not baked in.

⚠ **The upper wall's end is `ub` with NO +1** — DOOM's `min(ub - 1, win_lo)` is an inclusive end.
Getting this wrong is 644 pixels at spawn and it cost a build cycle in rung 3b. The lower's start is
`max(lt, win_hi)`, no adjustment.

Gate it the way rung 3b is gated: square room 5 viewpoints (it has no two-sided lines, so the gate
proves the splice didn't disturb rung 3a) + E1M1 spawn and rotated + the 65-viewpoint sweep for the
worst case.

---

## 5. Ladder

| rung | what | gate |
|---|---|---|
| 3c-1 | the oracle: `near_steps` on the rung-3a path, both flavours (WPX runs / flat-shaded) | host gates: the near floor is still 1 surface at spawn; steps present; PNG for the owner |
| 3c-2 | fj: the 8-byte per-column slots + the write-once fill in the two-sided leaf (no emit change yet) | byte-exact vs rung 3a still (slots written, nothing read) — proves the fill is free of side effects |
| 3c-3 | fj: the emit splice (7 pieces) | byte-exact vs the 3c oracle, square + E1M1 |
| 3c-4 | flat-shade + the 2-row floor, measure, sweep 65 viewpoints | worst < 30M, full suite |

Reuse from rung 3b, which is already written and gated: the sub-range band walk
(`stream.band_range`, the general form of pwalk/swalk), `stream.wall_run`, the WPX bank's upper/lower
blocks (`_lines_wall_pix_bank(..., two_sided=...)`, 622 blocks on E1M1), the per-seg baked
`seg_flags`/`bceilfix`/`bfloorfix`/`seg_wsupper`/`seg_wslower`, and the `entoff` dispatch. Rung 3b
itself stays in the tree as the accuracy reference — it is the thing 3c is measured against for
*look*, and `render_frame_2s` remains its oracle.

---

## 6. Pitfalls that already cost build cycles (each ~5–10 min)

- **`mul_const` / `ptr_index` read `w/4` nibbles of their source** — a 2-nibble register must be
  zero-extended first (fj-lessons R11). Symptom: `term=ip<2w`, frame all zeros.
- **A macro body inlined in a loop must `;end` over its own scratch `hex.vec` data** (lesson #2).
  Same symptom.
- **`hex.set n` is @+4 but `hex.mov n` is n(2@)** — set from a constant, don't mov.
- **Multiplying a COUNT by `5*dw` instead of 5** made a compare loop run 320× too long. `dw` belongs
  in address arithmetic only.
- **The square room has no two-sided linedefs** — it cannot catch a bug in the two-sided path. Only
  E1M1 exercises it.
- **Price before building** (R23/R32/§13): rung 3b's own 187M would have been caught by pricing the
  per-column projection count first.
