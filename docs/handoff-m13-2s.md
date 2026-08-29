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
# (scratchpad/tsprobe.py retired 2026-08-29 -- it priced the WPX/two-sided walk, and both tiers are gone)
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

## 11. Rung 3b is PRICED, and as designed it does NOT fit under 33M

Rung 3a used the headroom §4 had budgeted for 3b's emit (worst-of-65 24.84M -> 31.0M, ceiling 33M), so
3b was priced before building it (R23/R32). Two independent measurements:

**(a) `scratchpad/rung3b_volume.py` — the emit volume, straight from the two oracles** (no fj build,
no confounds). The lines tier's cost is dominated by emitted `[y2][colour]` pairs at ~3.7k ops each;
counting each frame's per-column colour runs gives what each tier must emit:

| viewpoint | rung 3a runs | rung 3b runs | extra EMIT alone |
|---|---|---|---|
| spawn | 3,655 | 4,705 | **+3.88M** |
| spawn +90° | 4,947 | 5,224 | +1.02M |
| (−309,636,0) | 2,541 | 2,605 | +0.24M |
| (−309,−44,0) — the sweep's worst, 31.0M today | 2,662 | 3,652 | **+3.66M** |

So the two heaviest frames break 33M on the extra PIXELS alone, before counting any of rung 3b's new
machinery: the full pass-2 projection for the wall-drawable two-sided segs (scale setup + per-column
params, which rung 3a never pays — it only attributes), the per-column buffered pair lists, and the
sub-range plane walks.

**(b) ablate `"tsfull"`** routes the 709 wall-drawable two-sided segs through the one-sided emission
path — full projection, scale, per-column params, WPX emit: spawn **40,262,818**. ⚠ It is NOT a bound
in either direction: it draws FULL-HEIGHT walls, so it over-emits pixels AND over-occludes (columns
that real 3b leaves open close early, which makes its walk cheaper — hence the misleadingly LOW
19.7M / 12.1M at the other two viewpoints). Read (a), not (b); (b) only agrees that the gap is several
M, not marginal.

### RE-PRICED after M13-ATANDISP (§14): rung 3b now fits — barely

The `tsfull` proxy, re-run on the faster baseline:

| viewpoint | shipped (rung 3a + ATANDISP) | `tsfull` | delta |
|---|---|---|---|
| spawn | 21,730,429 | **31,168,051** | +9.44M |
| (−309,−44,0) | 26,551,706 | **32,614,637** | +6.06M |
| (−309,636,0) | 24,734,560 | 16,957,981 | −7.78M ⚠ the over-occlusion artefact |

40.26M → 31.17M at spawn: cutting the atan moved rung 3b from *clearly over* the ceiling to *inside*
it. The same caveat as before applies — `tsfull` draws FULL-HEIGHT walls, so it over-emits pixels
(real upper/lower slices are smaller) and over-occludes (columns real 3b leaves open close early,
which is why (−309,636) comes out BELOW the shipped frame). It models neither the per-column buffered
pair lists nor the sub-range band walks. Treat 31–33M as "plausible, not proven", and note the
`PNEAR_SEG_BUDGET` dial below is worth ~2.9M at the heavy viewpoints if 3b needs the room.

### The choice this puts in front of the owner

1. **Raise the ceiling.** 33M ≈ 6.7 fps on the native engine (~220M ops/s); 40M ≈ 5.5 fps.
2. **Buy headroom first.** The per-vertex angle memo is still in reserve (§4: avoids 42% of 1398
   vertex angles; its old +0.73M verdict was measured in a 471-atan era and never re-tested — the
   rung-3a budget now pays up to 128 segs' worth of atans, so re-measure it HERE). Cheaper still:
   `PNEAR_SEG_BUDGET` 128 → 64 trades far attribution for ops.
3. **Halve rung 3b: LOWER walls only** (steps and ledge fronts — the most legible missing geometry;
   105 of spawn's 252 runs). It still needs the buffered per-column pair lists, because a lower run
   arrives before the far wall that must precede it in the record.
4. **Attack the ~3.7k/pair unit cost of the emit protocol**, which would buy headroom for everything,
   not just 3b.

Recommended: (2) then (3), i.e. re-measure the memo, then land lowers before uppers.

## 12. ⚠ CORRECTION — "one emitted pair = ~3.7k ops" (§4) is WRONG, and it changes the plan

The owner picked "attack the ~3.7k/pair emit cost first". Measuring it first (ablate `emitnopair` =
walk the baked lists but emit no pairs; `emitnowalk` = skip the band walks entirely) says that lever
does not exist:

| E1M1, WPX+FT1+plane_near | spawn | (−309,−44,0) |
|---|---|---|
| full emit (shipped) | 25,494,558 | 30,998,786 |
| walk the lists, emit NO pairs | 25,396,585 | 30,896,145 |
| no band walk at all | 24,302,004 | 29,736,835 |

- the two `byte.emit` dispatches per pair cost **~27 ops** (97,973 over spawn's 3,655 pairs);
- the WHOLE ceiling+floor band emit — pointer reads, loop, compares and dispatches — is
  **1.19M of a 25.49M frame (4.7%)**, i.e. **~330 ops/pair, not 3,700**.

Making pairs *free* would buy 1.19M. §4's 3.7k figure must have been measured over something larger
(a whole per-column path), and two conclusions rested on it — both now retracted:

1. **§11's rung-3b emit estimate is wrong.** +1050 runs at spawn is ~+0.35M, not +3.88M. Rung 3b's
   emit is CHEAP; what makes `tsfull` cost +14.8M is the wall-drawable two-sided segs' PROJECTION and
   per-column work (pass-2 setup + `column_params_m` per column), not the pixels.
2. **The emit protocol is not the place to buy headroom.**

### Where the frame's ops actually are (the ablation ladder, same build/tier)

| stage | spawn | (−309,−44,0) | share of spawn |
|---|---|---|---|
| BSP walk skeleton + per-seg xorby SET/CLEAR (`segstub`) | 4,953,547 | 4,981,851 | 19% |
| + per-seg leaf entry (`xrstub`) | 4,950,443 | 4,979,621 | — (free) |
| + the wedge pre-cull (`wedgestub`) | 6,533,988 | 6,664,193 | +6% |
| + projection, per-column params, occlusion, WPX wall emit, plane attribution (`emitnowalk`) | 24,302,004 | 29,736,835 | **+70%** |
| + the ceiling/floor band emit (full) | 25,494,558 | 30,998,786 | +5% |

**70% of the frame is per-seg projection + per-column work.** That is the only place headroom of the
size rung 3b needs can come from. The obvious first candidate is still the per-vertex angle MEMO
(§4: avoids 42% of 1398 vertex angles at ~19–23k per `point_to_angle`, and its old +0.73M loss verdict
predates both this atan load and rung 3a's up-to-128-seg budget) — but per this section's own lesson,
MEASURE the atan share of that 70% before building it (an ablate that stubs `point_to_angle` inside
`wall_x_range_m` would isolate it).

## 13. The atan is 21–25% of the frame — and the memo is CONFIRMED DEAD

Measured by ADDING work, not removing it: `atantwice` runs each seg's two vertex atans a second time
into a dead register, `slopetwice` re-runs only `slope_div_m`, `tabletwice` only the packed
`tantoangle` read. Everything downstream stays bit-identical, and the probes assert the frames are
**byte-exact** — so each delta is that component's cost and nothing else.

| E1M1, WPX+FT1+plane_near | spawn | (−309,−44,0) |
|---|---|---|
| shipped | 25,516,636 | 31,007,093 |
| + the whole atan pair again | 30,990,444 | 38,909,987 |
| + only the slope divide again | 26,908,029 | 34,053,027 |
| + only the tantoangle read again | 26,413,990 | 33,107,512 |

| component | spawn | share of the atan | (−309,−44,0) |
|---|---|---|---|
| **all `point_to_angle`** | **5,473,808 (21% of frame)** | 100% | **7,902,894 (25%)** |
| the slope divide | 1,391,393 | 25% | 3,045,934 |
| the packed tantoangle LUT read (4 byte-reads) | 897,354 | 16% | 2,100,419 |
| the rest: dx/dy, sign/negate, octant select, the 8-nibble folds | 3,185,061 | **58%** | 2,756,541 |

`scratchpad/atan_count.py` counts the calls: 548 at spawn (274 segs × 2), 630 at (−309,−44) —
so **~10.0k / ~12.5k ops per `point_to_angle`**, against §4's estimate of 19–23k.

### The per-vertex angle memo (§4's reserve item) is dead — do not build it

A memo hit must READ a stored 32-bit angle: `ptr_index` (72@) + `read_hex 8` (320@) ≈ 400@, which at
this program's @ is the same order as the ~10k atan it replaces (fj-lessons R37: a wide pointer read
costs what the computation costs). At the measured 42% hit rate the expected saving is
`0.42 × 10k − ~4-5k ≈ 0` per angle, and the misses still pay the probe plus a store. That is exactly
the +0.73M LOSS the earlier session measured, and the arithmetic does NOT flip at 1398 angles — the
old verdict was right for the right reason, which §4 doubted. **Retire the idea.**

### What is actually left to cut

- **58% of the atan is not the divide or the lookup** — it is the surrounding 4-/8-nibble
  arithmetic and the octant dispatch. A micro-optimisation rung on `point_to_angle_m` itself is worth
  ~1–3M, and unlike the memo it does not need a hit rate to pay off.
- **Fewer atan payers.** The ts (plane-attribution) path spends up to `PNEAR_SEG_BUDGET` = 128 segs ×
  2 atans; at spawn that is ~47% of all atan calls (128 of 274 segs). Attribution does not actually
  need `wall_x_range`'s exact columns — only that the ORACLE and the fj agree — so a cheaper
  conservative column range for the ts path alone could remove up to ~2.6M at spawn. It changes which
  columns get attributed, so it needs the oracle mirrored and a fresh look at the near floor.
- The band emit (§12) is 4.7% and `byte.emit` is ~27 ops/pair: not a target.

## 14. M13-ATANDISP — read the stl's COMPLEXITY DOCS, not the tea leaves: −3.8M/frame

Owner's correction mid-session: *"before trying new improvements, trust the complexity
documentation"*. The stl annotates every macro with its time complexity, and reading them off
immediately explained §13's numbers and pointed at the fix. At w=32:

| macro | documented time | note |
|---|---|---|
| `hex.set n, dst, val` | **@+4** | CHEAP — not per-nibble |
| `hex.mov n, dst, src` | **n(2@)** → 16@ at n=8 | dearer than `set` |
| `hex.xor n` | **@** | ~free |
| `hex.add/sub n` | n(4@+12) → 32@+96 at n=8 | |
| `hex.cmp n` | m(3@+8), m from the first differing nibble | cheap on early differences |
| `hex.zero n`, `hex.sign n` | @, @−1 | ~free |
| `read_byte_and_inc` | **42@+187** | |
| `ptr_index` | **72@+168** | |
| `hex.read_table_packed nb=4` | 4 × read_byte_and_inc + `mul_const` ≈ **289@** | **the atan's biggest item** |

That last line is the whole story: `point_to_angle_m` spent ~289@ reading `tantoangle[sidx]`, and
`slope_div_m` another ~247@ reading `slopediv_recip8[sden]`. The repo already had the cheaper idiom —
the **D4 per-entry dispatch table** (`generate_dispatch_table_fj`, the same machinery behind `cm.apply`
and `byte.emit`), whose `.lookup dst, idx` is 3 `hex.xor` + a jump + `zero` + `xor_zero` ≈ 20@. Same
values, so byte-exact by construction:

| E1M1 spawn, WPX+FT1+plane_near | ops | delta |
|---|---|---|
| before | 25,516,636 | |
| `tantoangle` → `ttang.lookup` | 24,012,214 | **−1.50M** |
| `slopediv_recip8` → `sdrecip.lookup` | **21,730,429** | **−2.28M** |

| | worst of the 65-viewpoint sweep |
|---|---|
| rung 3a as shipped | 30,998,786 |
| **+ M13-ATANDISP** | **26,551,706 (−4.45M)** |

**The two-sided plane attribution is now CHEAPER than the renderer was before it existed** (spawn
21.73M vs the pre-rung-3a 23.21M), and the headroom under the owner's ceiling goes 2.0M → 6.4M —
which is what rung 3b needs. Cost: the two dispatch tables add ~2.5M chars of generated program
(4096 entries each); lines mode only, the other tiers keep the packed reads and are untouched.

⚠ Counter-example from the same session, for calibration: an "obvious" rewrite of the octant tails
(`hex.set 8` + `hex.add/sub 8` → `hex.mov 8` + `hex.xor_by 8`, justified by an exact carry-free
XOR identity) measured +69k — a WASH — because `set` is @+4 while `mov` is 16@. It was reverted. The
docs say which ops are dear; guessing does not.

### Every remaining `read_table*` in the LINES path is gone

The others live in `plane_bands.fj` (the runtime band builder — lines mode uses BAKED bands),
`plane_render.fj` (the framebuffer/textured-plane tier) and the coarse-cull bounds (off). The same
conversion is available for those tiers if they are ever revived.

## 15. Rung 3b — DONE and byte-exact (correct, not yet fast)

`emit_wall_renderer(..., two_sided=True)` renders DOOM's `R_RenderSegLoop` window model and is
**byte-exact vs `ReferenceModel.render_frame_2s`** on the square room (5 viewpoints incl. the
(24,24) negative-viewz straddle, no unpainted pixel) and on E1M1 (spawn + rotation). Step faces,
ledge fronts and door frames are drawn, and every plane region carries its own bounding seg's sector.

### Two oracle corrections the rung forced

1. **The 2S oracle culled two-sided segs by "can it draw a WALL"**, which throws away rung 3a's
   attribution fix — two sectors of equal heights but different flats/lights still bound the near
   floor. The cull is now DOOM's `R_AddLine` reject (the MARKING test, which subsumes the wall test):
   at E1M1 spawn that is the difference between 1 near-floor surface and 4.
2. **It didn't apply the per-seg fake contrast** the shipped WPX tier applies, so targeting it would
   have silently dropped the look the owner signed off on. It does now.

### How the emit works (and why it is shaped this way)

The 0x0B protocol needs ONE contiguous top-to-bottom record per column, but front-to-back a column is
built from BOTH ENDS: ceiling regions and upper walls arrive top-down, floor regions and lower walls
bottom-UP. So the walk BUFFERS each column's REGIONS -- 5 bytes, `[kind][arg:2][y1][yend]` -- in a top
list and a bottom list, and a flush pass afterwards expands them (top forward, bottom in reverse,
which fixed-size entries make a plain backward index walk) and assembles the records.

⚠ Buffering the finished [y2][colour] PAIRS instead measured **+19M on the square room alone**: a WPX
1x1 wall column is ~76 pairs and each costs a pointer write plus a read. Regions are ~14 per column at
worst (measured over 30 viewpoints), and the expansion emits straight to the device.

Everything in the per-column body is 2-nibble UNSIGNED arithmetic on EXCLUSIVE-end row bounds --
`ctake = clamp(top,0,VIEW_H)` and `fstart = clamp(bot+1,0,VIEW_H)` fold DOOM's signed clipping away
once per column, and then every piece is a `min`/`max` pair. ⚠ The upper wall is the one asymmetric
case: DOOM's `min(ub - 1, win_lo)` is an INCLUSIVE end, so its exclusive end is `ub` with NO +1,
unlike the one-sided wall whose end comes from `bot` (getting this wrong paints one row of step face
too many -- it was 644 pixels at spawn).

### Cost — measured, and honest

| E1M1 | spawn | rotated |
|---|---|---|
| rung 3a + ATANDISP (the SHIPPED tier) | 21,730,429 | 19,529,379 |
| **rung 3b** | **131,060,211** | **46,222,635** |

Optimisations already applied, in order of what they bought at spawn: restoring the `drawn[]` write so
pass 1's occlusion prescan fires again (187M → 148M), skipping the back-sector projection for segs
with neither an upper nor a lower (148M → 142M), and the flush's DITTO path — if a column's region
list is byte-identical to its neighbour's, emit `[x][0xFE]` and skip the whole expansion (142M →
137M; on the square room 16.3M → 10.9M).

A fourth landed after that: the entry-offset multiply in the append path (`mul_const` by `5*dw` =
9 shifts of w/4, ~72@) became a **dispatch lookup**, the same trick as §14 (137M → 131M, and the
square room 10.9M → 9.8M).

| E1M1 spawn | ops |
|---|---|
| first working rung 3b | 187,750,215 |
| + `drawn[]` write restored (pass-1 prescan fires) | 148,067,199 |
| + back projection only when there IS an upper/lower | 141,658,924 |
| + the flush's ditto path | 137,320,223 |
| + entry offsets by dispatch | **131,060,211** |

Measured split at spawn: **walk + pass 2 = 93.6M, the flush = 44M**, and within the first number the
BSP walk with all its early-outs is only **4.83M** (ablate `colstub`) — so **88.8M is the per-column
body**, ~79k ops per column visit over ~1,120 visits. The flush's cost is dominated by
re-walking a surface's whole baked band list for every region (a 3-row region still walks up to 32
entries, two pointer byte-reads each), which a per-list row→offset index would cut ~10x. ### What is left, and why it needs a design step rather than another tweak

79k ops per column visit, with ~1,600 region appends a frame, says the cost IS the buffering: a
`write_byte_and_inc` is 50@, an entry is 5 of them plus the count read/write, and **at this program's
size @ is worth roughly 150 ops** — so one buffered region costs ~40k. That also explains why the
pair-buffered first attempt was hopeless.

Ranked, with what each is worth:
1. **Shrink the entry.** 5 bytes → 4 (pack `kind` into the arg's spare nibble) or → 3 (a top entry's
   `y1` is the previous entry's `yend`, since top regions tile contiguously; the bottom needs a
   one-entry lookahead to do the same). ~20–40% of 88.8M.
2. **Index the baked band lists by row.** The flush re-walks a surface's whole 32-entry list for a
   3-row region; a per-list row→offset byte table makes it one indexed read. Most of the 44M flush.
3. **Don't buffer at all** — the real fix, and a design step: a column's record could be emitted at
   close time if the pieces arrived in order, which they do NOT in a seg-major walk. A column-major
   pass over the drawable segs would, at the cost of re-projecting per column.

None of these is a tweak away from 33M: rung 3b is ~4x over, and closing that gap is its own rung.

**So rung 3b is correct and gated, but it is 4x the owner's ceiling and is NOT the shipped tier.**
`plane_near` (rung 3a) still ships; `two_sided=True` is opt-in.

### ★ NEXT: rung 3c — docs/handoff-m13-2s-fast.md

The owner's ruling on §15's 131M: it must be 20–30M, and visual ACCURACY may be spent to get there so
long as visual CLEARNESS survives. That handoff also corrects this file's cost arithmetic: **@ is
25–30 ops, not 150**, which moves the blame from the region buffer (~23M) to the **per-column
projection (~43.5M)** and makes the fix structural — keep rung 3a's frame, splice in only the NEAREST
upper/lower per column, and the buffer and flush pass disappear entirely.

### Still open

- Rung 3b (§6) — the upper/lower wall runs. Unchanged by this rung except that the per-column plane
  attribution it needs now exists (and `pclm` already carries a per-column surface id).
- The residual attribution error is now at the FAR end of a column's floor strip (a column's strip is
  still ONE region), which is what rung 3b's sub-range plane regions fix.
