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
