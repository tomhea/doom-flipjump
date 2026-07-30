# Handoff — M13-2S: two-sided walls + plane attribution

**This is CURRENT M13 renderer work, to be done BEFORE M14 input+sim.** (Two-sided walls were
originally slated for M16; the owner moved them forward. The two already-pushed commits `9d8229b`
and `f5dfb81` say "M16-2S" in their messages — pushed history left alone, everything else renamed.)

Branch: `m13opt3-early-out`. Everything below is committed and pushed through `f5dfb81`.

---

## 1. What the owner is seeing, and what is / is not fixed

The owner played the game (`python scripts/walk_e1m1.py`) and reported two things:

1. *"hard to distinguish close and far walls, the outlines aren't strong"* — **FIXED and live.**
2. *"the close floor in the middle is gray, yet the sides are yellow… it should all be the same
   yellowish colour for the nearby floors all along"* — **NOT FIXED in the game.** The fix exists
   only in the host oracle (`ReferenceModel.render_frame_2s`), which the walker does not use.
   ⚠ Do not tell the owner this is fixed until the fj renderer does it. I made that mistake once.

| | state |
|---|---|
| wall distance lighting (`scalelight`) + fake contrast, and the two bugs below | **live in the walker** |
| floor/ceiling plane attribution | oracle only |
| two-sided walls (steps, ledges, door frames) | oracle only |

Two genuine bugs were found and fixed while porting DOOM's wall lighting (both live):
- **wall light was inverted** — colormap row 0 is BRIGHTEST, but the code used `light >> 3` directly
  as the row, so a fully-lit sector picked row 31 = darkest. Floors were always right (`zlight`
  handles the inversion internally); only walls were wrong.
- **`scalelight` lacked DOOM's view-width compensation** — DOOM divides by `SCREENWIDTH/viewwidth`;
  our projection is `view_w/2`, so at 160 wide every wall landed ~6 colormap rows too dark.
  `zlight_table` already took `view_w`; `scalelight_table` now does too.

---

## 2. Root cause of the floor bug (fully characterised — don't re-derive)

**The renderer keeps ONE floor record per column and takes it from whichever wall CLAIMS that
column.** That encodes the assumption *"a column's whole floor strip belongs to one sector"*, which
holds only if every sector boundary is a solid wall. In DOOM most boundaries are two-sided — 1482 of
E1M1's 2057 segs — and those were skipped entirely, so a column's floor normally crosses several
sectors and we paint all of it with the **farthest** one's flat, height and light.

Measured at E1M1 spawn. The player stands on flat `AQF054`; only **27 of 160 columns** paint the
floor with it:

| columns | floor flat used | floor_h | light |
|---|---|---|---|
| 0–15 | AQF054 ✓ | 0 | 150 |
| 16–33 | **AQF018** | 0 | 192 |
| 34–64 | **AQF024** | 0 | 192 |
| 65 | **FLOOR5_2** | **−128** (a pit ⇒ shaded ~4× further ⇒ very dark) | 160 |
| 66–143 | **AQF024 / AQF018** | 0 / 16 | 160 / 192 |
| 144–159 | AQF054 ✓ | 0 | 150 |

So **three** attributes are wrong at once — flat, height, light — from one cause. It is not a
lighting bug and cannot be fixed by adjusting shading: the renderer has no idea where the near
floor ends, because that boundary *is* a two-sided linedef it skips.

Earlier evidence for the same thing, at row 80: every column had identical `planeheight` 41 (the
floor underfoot) yet came out in zlight rows 19/7/15/12, because the claiming sectors were lit
150/192/160.

### ⚠ Owner's explicit constraint on the fix

> *"i don't want the change to be all floors are painted as a close-floor — far floor should still
> look a bit different. BUT not so different — it should still be easily distinguishable from the
> walls, it should still be looking as a floor color."*

**Do not touch the per-row distance falloff.** `zlight[light][distance]` is applied per screen row,
distance coming from the plane height and `yslope[y]`. That mechanism is correct and stays. The only
thing changing is *which sector's* (flat, height, light) each part of the strip is attributed to.
Far floors therefore stay darker than near ones automatically.

---

## 3. The model to implement (DOOM `R_RenderSegLoop`)

Per column keep DOOM's two clip values, replacing the 1-bit `drawn[]`:
- `ceilingclip[x]` — highest row still unpainted from the top (init `-1`)
- `floorclip[x]` — lowest row still unpainted from the bottom (init `VIEW_H`)

Then per seg, front-to-back, per column, in this order:

```
front-sector CEILING region | upper wall | (opening) | lower wall | front-sector FLOOR region
```

narrowing the window from both ends. A one-sided seg fills what remains and closes the column.
Each plane region carries the **bounding seg's own front sector**, which is what fixes §2.

A two-sided seg whose two sectors share **both** ceiling and floor can never draw anything — 773 of
E1M1's 1482 — and is excluded up front. In fj that is a baked compile-time exclusion, already proven
by `tsprobe`.

Reference implementation: `ReferenceModel.render_frame_2s` (`src/doomfj/reference_model.py`). It is
the **byte-exact target** for the fj work and is already gated. `scratchpad/twosided_proto.py`
renders the same thing standalone if you want a picture fast.

---

## 4. Budget — measured, not estimated

Owner's ceiling: **33M ops/frame**. Today's shipped tier (WPX+FT1): spawn **23,204,595**, worst of 63
viewpoints **24,843,494**.

`tsprobe` (ablate mode, commit `f5dfb81`) walks the 1284 drawable segs through the GEOM xorby block
+ pass 1 only — no emit — to price the decisive unknown:

| viewpoint | baseline | + two-sided walked/culled | delta |
|---|---|---|---|
| spawn | 23,204,595 | 27,295,669 | +4.09M |
| (-309,636,0) | 24,867,650 | 29,598,436 | +4.73M |
| (-480,256,0) | 24,756,945 | 29,012,178 | +4.26M |

**So visiting + culling the two-sided segs costs +4.1–4.7M, leaving ~3.4M of the 33M for the emit.**
I had estimated +12M and would have redesigned around it — wrong, because the host study counted 699
front-facing segs as atan-payers but the wedge and affine culls reject most before `wall_x_range`
runs (only ~87 two-sided segs reach projection at spawn). **Measure in context before believing a
cost model** — this repo already paid +24.7M for that lesson once (fj-lessons R23/R32).

**The per-vertex angle memo is NOT needed.** It would avoid 42% of the 1398 vertex angles, but the
budget no longer requires it. Keep it in reserve; note fj-lessons records it as a +0.73M loss from a
low-repeat-rate era, so re-measure rather than inherit either verdict.

### Populations at E1M1 spawn (`scratchpad/twosided_study.py`)

| stage | count |
|---|---|
| segs at leaf | 2057 |
| draw nothing (same ceil AND floor) — free compile-time cull | 773 of 1482 two-sided |
| drawable | 1284 |
| front-facing (cheap cross product) | 699 |
| in-frustum (`wall_x_range`) | 436 |
| runs (solid / upper / lower) | 411 (159 / 147 / 105) |
| plane regions (ceiling / floor) | 328 / 292 |

### Unit costs to price rungs against

| thing | measured |
|---|---|
| one emitted `[y2][colour]` pair | ~3.7k ops |
| one average WPX strip entry, whole frame | ~294k ops/frame |
| the ditto path (`[x][0xFE]`) is worth | **4.83M** — do not break it casually |
| one `point_to_angle` in context | ~19–23k |

---

## 5. Rung 3a — fix the floor cheaply (DO THIS FIRST)

**Let the nearest DRAWABLE seg (one-sided *or* two-sided) set the column's plane record, while
`ctake`/`fstart` keep coming from the nearest ONE-SIDED wall as today.**

The floor strip stays a *single* region, so this needs **no** buffered pair lists, no bottom-up
reversal, no upper/lower textures — but it is attributed to the **near** sector, so the floor at the
player's feet is correct in every column. The residual error moves to the far end of the strip,
which is a small and distant fraction of those pixels.

Cost ≈ the `tsprobe` delta already measured (+4.1M) plus a cheap per-column store ⇒ **~29–30M worst,
inside 33M, with no emit-architecture change.**

Track per column: `plane_claimed[x]` (set by the first drawable seg) separately from `drawn[x]` (set
by the first one-sided wall).

⚠ **This changes rendered output, so it needs an oracle mirror behind a FLAG.**
`render_wall_frame` also feeds tiers with **stored goldens** (the textured/flat framebuffer ones), so
make the new attribution opt-in — e.g. `plane_near=True` — and use it only from the lines WPX+FT1
tier. Otherwise those goldens re-bless and you have a much bigger diff to justify.

---

## 6. Rung 3b — the upper/lower wall runs (makes steps and door frames appear)

1. `drawn[]` (1 packed byte/column) → `ccl[x]` / `fcl[x]`, 2 bytes each.
2. Per-seg REST xorby block gains the two-sided data: back-sector ceil/floor, and upper/lower WPX
   bank offsets (the WPX bank is keyed `(texture, light level incl. fake contrast, wall span in map
   units)` × exact height — an upper wall's span is `front.ceil − back.ceil`, a lower's is
   `back.floor − front.floor`, and they sample `sd.upper` / `sd.lower`).
3. **Per-column buffered pair lists.** This is forced by the protocol, not a choice: 0x0B needs one
   contiguous top-to-bottom record per column (`[x][pairs…][0xFF]`), but walking front-to-back the
   uppers arrive top-down while the **lowers arrive bottom-UP**. So buffer and flush `[x] + pairs +
   0xFF` when the column closes (a solid wall) or at frame end. ~24 pairs/side/column ≈ 15k words —
   cheap. 0x0A span records would be order-independent but cost the 4.83M ditto saving — rejected.
4. Plane regions = **sub-range** walks of the same baked band lists. `stream.pwalk`/`swalk` already
   clip to an end bound; they need a start bound too.
5. Gate byte-exact vs `render_frame_2s`, then sweep 63 viewpoints for the worst case.

---

## 7. How to run things

```bash
python scripts/walk_e1m1.py                       # play it (native C engine, ~5 fps on E1M1)
python scripts/walk_e1m1.py --frames 3            # headless, no pygame, prints per-frame ops
python -m pytest tests/host/test_twosided.py -q    # the 2S oracle gates (fast)
python -m pytest tests/fj/test_lines_render.py -q  # the fj byte-exact tier gates (~6 min)
python scratchpad/wpx_sweep.py                     # 63-viewpoint worst-case sweep (~15 min)
python scratchpad/tsprobe.py                       # the two-sided walk-cost probe
python scratchpad/twosided_proto.py                # standalone picture of the target look
python scratchpad/twosided_study.py                # population counts
python -m pytest -q                                # full suite, ~1h15m, 299 passed / 4 skipped
```

⚠ Never run two heavy E1M1 fj builds concurrently — it disk-thrashes and nothing finishes
(fj-lessons / mperf-handoff). Serialize them.

---

## 8. Key symbols

| where | what |
|---|---|
| `reference_model.py` | `render_frame_2s` (the target), `_render_plane_regions_flat`, `wpx_strip`, `wpx_texcol`, `wall_lightnum`, `wall_light_row`, `wall_fake_contrast` |
| `tables.py` | `scalelight_table(view_w, num_colormaps)`, `MAXLIGHTSCALE`, `DOOM_SCREENWIDTH` |
| `wall_renderer.py` | `_lines_wall_pix_bank` (the WPX bank), the `subsector_action` seg loop, `tsprobe` ablate mode |
| `stream_render.fj` | `wpx_wall`, `emit_col_lines`, `pwalk`/`swalk` (band walkers) |
| `frame_render.fj` | `seg_pass1_leaf_body_lines` (cull), `seg_pass2_leaf_body_lines` (emit), the ditto test |
| `fastrun.py` | `FjmRunner` — load the .fjm once, run per frame (13.6× vs `flipjump.run`) |

Memory: `m13-2s-handoff.md` (this work), `mperf-handoff.md` (renderer state), `fj-lessons.md`
(R34–R36 cover the bake-indexing lever, the interpreter finding, and "check what DOOM did before
inventing an effect"), `fj-cost-model.md` (per-primitive costs + the ROW RULE).

---

## 9. Definition of done

- Byte-exact fj vs `render_frame_2s` on the square room (5 viewpoints incl. the negative-viewz
  straddle at (24,24)) and E1M1 (spawn + rotation).
- The square room leaves **no** unpainted pixel — a hole means a mishandled clip range.
- Worst of the 63-viewpoint sweep **< 33M**.
- Full suite green.
- The near floor is one continuous colour family across the frame, still darkening with distance.
- Then: **M14 input + simulation.**

---

## 10. Rung 3a — DONE (this session): the near floor is one surface again

**Shipped in the lines tier behind `plane_near=True`** (`emit_wall_renderer(..., plane_near=True)`,
`ReferenceModel.render_wall_frame(..., plane_near=True)`); the walker turns it ON by default
(`--no-plane-near` goes back to the old look). Everything without the flag is untouched, so no
stored golden re-blesses.

### The cull in §3/§5 was WRONG for planes — and that is why the floor was still wrong

"A two-sided seg whose two sectors share both ceiling and floor can never draw anything" is right for
WALLS but too strong for PLANES: it drops the boundary between two sectors of EQUAL heights but
different flats or lights, which at E1M1 spawn is exactly where the near floor changes surface. Under
that cull the near floor still came out as 3 flats. The correct test is DOOM's
`R_StoreWallRange` markfloor/markceiling: the two sides differ in the band-bank key
`(height, light, flat)`. Then attributing a skipped seg's plane to either side is identical BY
CONSTRUCTION, and at spawn all 160 columns get the player's own surfaces:

| | floor claims at E1M1 spawn |
|---|---|
| shipped (wall claims the column) | 7 surfaces: AQF018/AQF024/AQF054/FLOOR5_2, heights 0/16/−128, lights 150/160/192 |
| wall-cull two-sided (§3's cull) | 6 surfaces |
| **marking cull (this rung)** | **1: (0, 192, AQF054) in all 160 columns** — and (128, 192, SLIME14) for the ceiling |

### Cost — measured, and the two things that make it fit

`tsmark` (a new ablate mode) prices the naive form: walk every marking seg through the cull front
end = **35.09M / 37.22M / 37.14M** at the three §4 viewpoints — 2–4M OVER the ceiling. Two levers
bring it back:

1. **`pfull`** — once all 160 columns are attributed, no later seg can change anything. At spawn 59
   marking two-sided segs are reached before that point and **1386 after it**, and the caller tests
   `pfull` BEFORE the seg's xorby block, so those cost one 1-nibble test each. Because including
   two-sided segs in the walk also kills the M13-prune compile-time prune (145 prunable subtrees → 2),
   subtrees with NO one-sided segs get the same gate at the NODE level (`plane_gate` in
   `_bsp_as_code`): the compile-time prune became a runtime one.
2. **the unattributed-column window `[pmin, pmax]`** — every column outside it is already attributed,
   so the claim scan clips to it: at (−309,636) 769 column reads → 201, and 37 of 60 projected segs
   exit outright. The bounds are updated with two compares and NO reads (after a scan of [xa,xb)
   that whole range is attributed, so if it started at `pmin` the bound jumps to `xb`).

3. **`config.PNEAR_SEG_BUDGET` = 128 marking segs/frame** — and this one is not an optimization, it
   is what makes the cost BOUNDED. "Every column attributed" never happens when part of the view is
   open sky or void: 13 of the sweep's 65 viewpoints never attribute all 160 columns, and the worst
   of them (−309,−724) walked all 1445 marking segs for **69,638,352 ops** — 2× the ceiling — because
   `full` never fires there either, so nothing bounded the walk at all. Two cheaper ideas were
   MEASURED AND REJECTED first: a distance cull on the attribution path (at maxdist 2048 it changes
   no frame but only takes 2020 projections down to 1911 — E1M1 fits inside 2048 units of any
   viewpoint), and capping on *projected* rather than *visited* segs (the atans are paid before a seg
   projects, so it saves almost nothing). Segs arrive nearest-first, so the budget only ever costs
   FAR attribution: those columns fall back to the claiming wall's sector, i.e. the pre-rung-3a
   behaviour, in the distant part of the frame. `scratchpad/rung3a_budget.py` has the numbers behind
   128; the oracle mirrors the budget and both stop conditions, so the gates test the mirror too.

Two design mistakes worth not repeating (both measured, not guessed):

- storing the two band-list ADDRESSES per column and reading them back with
  `hex.ptr_index` + `hex.read_hex 8` costs ~780 dispatches per column (+5M/frame). The claim state is
  now ONE byte per column: the claiming seg's **plane-pair id**, and the bank is laid out per pid
  (ceiling list at slot 2p, floor at 2p+1) so both addresses are one strength-reduced multiply.
  Cost: keys stop being shared between pids, bank 1.42M → 1.91M words.
- that multiply is ~15 shifts of w/4 and cost +1.1M/frame when paid per column; the addresses depend
  on the pid ALONE, so a one-entry cache (`cpid`) drops it to the handful of surface changes per frame.

### Where it landed

| | spawn | (−309,636,0) | (−480,256,0) | worst of the 65-viewpoint sweep |
|---|---|---|---|---|
| baseline (no plane_near) | 23,209,289 | 24,874,548 | 24,771,650 | 24,843,494 (the shipped tier's published number) |
| first working version | 33,153,404 | — | — | — |
| + pid bank, cache, window | 25,438,444 | 32,220,803 | 27,639,003 | 69,638,352 ⚠ (the open-view viewpoint) |
| **rung 3a as shipped** | **25,494,558** | **29,294,483** | **27,685,988** | **30,998,786 @ (−309,−44,0) — UNDER 33M** |

All 15 gate viewpoints of `scratchpad/pnear_sweep.py` are byte-exact vs the `plane_near=True` oracle
(the budget and both stop conditions are mirrored there, so the gates test the mirror too).

⚠ Two fj bugs cost time, both the SAME root cause and both already in fj-lessons: a macro's scratch
`hex.vec` data must be jumped over when the body is INLINE in a loop (lesson #2), and `mul_const` /
`ptr_index` read `w/4` nibbles of their source/index register, so a 2-nibble register must be
zero-extended first (R11). Symptom in both cases: `term=ip<2w` a few hundred k ops in, frame all
zeros.

### ⚠ What the owner will SEE, stated exactly

At spawn the near floor becomes ONE surface — the flat the player is actually standing on, `AQF054`,
whose base colour is neutral grey (palette 108 = rgb 55,55,55). **The yellow was the bug**: `AQF018`
(rgb 175,123,31) is another room's floor, and it was being painted over the near floor by the wall
that claimed those columns. So the owner's "it should all be the same yellowish colour" resolves to
"all the same GREY-ish colour" — same-ness achieved, yellow removed, because the yellow was never
this floor's. If they want the near floor warmer, that is a LOOK decision on the FT1 tier (which
texel each distance band samples), not this bug. `scratchpad/rung3a_before_after.png` is the
side-by-side.

### Still open

- Rung 3b (§6) — the upper/lower wall runs. Unchanged by this rung except that the per-column plane
  attribution it needs now exists (and `pclm` already carries a per-column surface id).
- The residual attribution error is now at the FAR end of a column's floor strip (a column's strip is
  still ONE region), which is what rung 3b's sub-range plane regions fix.
