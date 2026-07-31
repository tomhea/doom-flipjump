# Handoff — M13-2S rung 3c: two-sided step faces, with the frame at ~20M

**The job:** render two-sided geometry (steps, ledges, door frames) while the frame stays in the
owner's **20–30M band, near the 20M end**, trading visual ACCURACY where needed but never visual
CLEARNESS — you must be able to tell where a wall leads, and walls, floors, ceilings and other walls
must stay distinguishable.

Rung 3b (`two_sided=True`) is byte-exact vs `render_frame_2s` and costs **131M**. Rung 3a
(`plane_near`) shipped at **21.74M spawn / 26.56M worst-of-65** with no step faces; §2a of this
document has since taken it to **20.59M / 25.32M**, byte-exact, which is the baseline everything
below is measured against.

**The picture already exists: `scratchpad/rung3c_proto.png`** (host prototype, `rung3c_proto.py`).
It renders the design below at three viewpoints against the shipped frame. The thresholds and ledges
appear; K=1 and K=2 are visually indistinguishable, so **K=1**.

> **Document history.** v1: one upper + one lower per column — its core rule dropped 44% of runs.
> v2: K=2 slots + incremental projection, ~28–32M — honest but could not reach 20M. v3: decomposed
> the base by ablation — right instinct, but **two of its numbers were wrong**; see §0.
> **v4 (this one) is built on exact population counts and byte-exact doubling measurements.**

---

## 0. ⚠ Retraction of v3 — read this before trusting any older number

**v3's headline lever (incremental `topfrac += topstep` projection) is DEAD.** Counted exactly in the
oracle (`scratchpad/visits_vs_proj.py`): the frame runs `column_params_m` on **exactly 160 columns,
at every viewpoint** — `drawn[]` guarantees each column is projected once, ever. There is nothing to
amortise. Worse, accumulators must be stepped on every column VISIT (840 at spawn, 660 at the worst),
so DOOM's method would *add* two 8-nibble adds to 5× more work than it removes. It is the right
method for DOOM, which re-projects per seg per column; it is the wrong method here.

**v3's `noproj` row was contaminated.** Stubbing `column_params_m` to a fixed span shrinks every wall,
which changes the WPX emit volume too — the delta was projection + emit, not projection. Any ablate
that changes the frame prices *itself plus everything downstream*. The fix, and the rule: **price a
kernel by ADDING it** (run it twice with the same operands into dead registers) and assert the frame
stays byte-exact. `projtwice` and `scaletwice` do that.

---

## 1. Exact populations (oracle counts, no fj build, no confounds)

| | spawn | worst (-309,-44) |
|---|---:|---:|
| `wall_x_range` calls | 634 | 703 |
| … in-frustum (⇒ `wall_scale_setup` runs) | 169 | 202 |
| **`column_params_m` calls (= projections)** | **160** | **160** |
| pass-2 column VISITS | 840 | 660 |
| … of which already drawn, i.e. wasted | 680 (81%) | 500 (76%) |
| marking two-sided segs walked | 59 | 128 (budget-bound) |
| (marking seg, column) pairs the claim scan visits | 245 | 247 |
| columns holding ≥1 upper / ≥1 lower run | 0 / 54 | 53 / 55 |
| **marking segs that actually carry a face** | **2** | **24** |

That last row is the one that makes this rung cheap: a marking seg only needs the expensive per-seg
scale setup if it *has* an upper or lower. At spawn only 2 of 59 do.

## 1a. Unit prices, measured by DOUBLING (frame byte-exact — `scratchpad/xtadisp.py`)

| kernel | calls/frame | spawn | worst | share of the frame |
|---|---:|---:|---:|---:|
| `proj.column_params_m` | 160 | **11,853** | **11,426** | 9.2% / 7.2% |
| `proj.wall_scale_setup_m` (post-2a) | 169 / 202 | **15,372** | **23,642** | 12.6% / **18.9%** |

**`wall_scale_setup_m` is now the single largest item in the frame** (18.9% at the worst viewpoint,
and it is where its cost is data-dependent — 15.4k vs 23.6k for the same code). It is two
`scale_from_global_angle` (each with a `fixed_div`) plus a `scalestep` divide. It is out of scope for
this rung, but it is **the next lever after 3c** and worth more than anything left in §5.

---

## 2. The three changes

### 2a. `xtoviewangle` → a D4 dispatch table — ✅ **DONE, MEASURED −1.14M / −1.24M, BYTE-EXACT**

`proj.wall_scale_setup` runs **once per in-frustum seg** (169 / 202) and opened with **two
`hex.read_table_packed 4` reads of `xtoviewangle`** (at x1 and x2) — ~2.6M/3.2M per frame spent
reading a 161-entry table. Same lever as **M13-ATANDISP** (`tantoangle`, `slopediv_recip8`):
`generate_dispatch_table_fj` → `<label>.lookup dst, idx`.

Shipped as `proj.wall_scale_setup_m` (lines mode only, so the stream/raster/proj tiers keep the
`read_table_packed` form) plus a 161-entry `xtadisp` table — 84k chars of program, ~1/25 of the
tantoangle conversion. The generated text ends with a self-invoking `xtadisp.init`, so there is no
wiring to add.

| | spawn | worst (-309,-44) |
|---|---:|---:|
| before | 21,736,934 | 26,557,125 |
| **after** | **20,594,618** | **25,319,870** |
| | **−1,142,316** | **−1,237,255** |

Byte-exact against the oracle at both viewpoints. ⚠ The saving is **~45% of what the stl's documented
`~289@` for `read_table_packed 4` predicts** (6.8k/seg for both reads, i.e. ~3.4k per read ≈ 125@, not
289@) — with `idx_n=2` the `mov` is trivial and the `mul_const` is strength-reduced. **Trust the
complexity docs for the ORDER, not the constant.**

`plane_render.fj:132` reads the same table per span and is still unconverted — a leftover lever.

### 2b. Clip pass 2's column loop to the unclaimed window (−1.0M / −0.75M)

76–81% of pass-2 column visits are already-drawn columns whose body is a no-op — but each still pays
`read_byte drawn[x]`, the ditto invalidation, the pointer step and the loop test (~1.5k).

**Half of this is already computed and then thrown away.** Pass 1's occlusion prescan
(`frame_render.fj:1385-1401`) walks from `x1` to the first unclaimed column and leaves it in `x`,
with `dptr` aimed at it — and `x`/`dptr` are SHARED globals in both leaves' `<` lists, with nothing
running between pass 1 and pass 2 for a given seg. Then pass 2 opens with

```
hex.mov 8, x, x1                        // frame_render.fj:1444 — re-aim drawn[] at x1
hex.ptr_index dptr, dbase, x1           // ... discarding the prescan's result
rep(pnear, k) .lines_plane_ptr x1
```

**Deleting those two instructions and aiming `lines_plane_ptr` at `x` is the whole first half of 2b**,
and it is byte-exact by construction (the skipped columns are drawn; a drawn column's body is a
no-op). Do this half first — it is three lines and cannot change the frame.

The second half clips the END. ⚠ It needs a NEW `[dmin, dmax]` pair tracking the **`drawn[]`**
window: rung 3a's existing `pmin`/`pmax` (`frame_render.fj:1212-1236`) track the `pclaim[]`
attribution window, which is a *different array* — do not reuse them. Maintain `dmin`/`dmax` by the
same trick that pair uses (two compares, no memory reads, conservative update) and end pass 2's loop
at `min(x2, dmax+1)`.

### 2c. The step faces (+1.2M spawn / +1.9M worst)

Per column keep the **nearest K=1 upper and K=1 lower run** in a write-once slot, filled by the
front-to-back claim walk, capped at **`STEP_SEG_BUDGET = 24` face-carrying marking segs** (the near
ones — the walk is front-to-back). A seg whose slots are full costs one read and a branch, with no
projection at all.

**Flat-shaded**: a face emits ONE pair — the block's mid texel at that run's scalelight row — not a
WPX 1×1 run list. Because every piece is known when the one-sided wall closes the column, it emits
inline exactly as rung 3a does: **no region buffer, no flush pass** — those are what made rung 3b
cost 131M.

Costed on **measured unit prices** (doubling, byte-exact — see §1a), not estimates:

| item | count spawn / worst | unit | spawn | worst |
|---|---|---:|---:|---:|
| extra `wall_scale_setup_m` (face-carrying segs) | 2 / 24 | 15.4k / 23.6k | 0.03M | 0.57M |
| back-sector projection, **sparse-delta** (below) | 54 / 108 | ~3.8k | 0.21M | 0.41M |
| slot checks over the claim scan's pairs | 245 / 247 | ~0.5k | 0.12M | 0.12M |
| the per-column splice test | 160 / 160 | ~1k | 0.16M | 0.16M |
| | | | **+0.52M** | **+1.26M** |

⚠ **Use the ROW RULE for the back projection.** A full `column_params_m` measures **11.9k** (it runs
`rep(6,j) fixed_mul_lo.row` twice, over `scale`'s six nibbles). The back row is
`front_row + (worldtop_front − worldtop_back) * scale >> 16`, and that height DELTA is a per-seg
BAKED CONSTANT with typically 1–2 nonzero nibbles. Put the delta SECOND — the row rule prices a
multiply by the nonzero nibbles of the second operand — and it is one multiply of ~2 rows instead of
two of 6: ~3.8k, not 11.9k. This is measured-rule arithmetic, not a guess; verify it with a
`facetwice` doubling probe before trusting the number.

`STEP_SEG_BUDGET` bounds this **independently of the viewpoint**, which is the property rung 3a
lacked and had to retrofit (`PNEAR_SEG_BUDGET`). Set it once; no viewpoint can blow it up.

---

## 3. The projection

| | spawn | worst (-309,-44) | status |
|---|---:|---:|---|
| rung 3a, as it shipped | 21,736,934 | 26,557,125 | |
| **− 2a `xtoviewangle` dispatch** | **−1,142,316** | **−1,237,255** | ✅ **measured, byte-exact** |
| = the new baseline | **20,594,618** | **25,319,870** | ✅ **in the tree now** |
| − 2b clip pass 2 to the unclaimed window | −1.0M | −0.75M | estimated |
| + 2c step faces, K=1, flat-shaded | +0.52M | +1.26M | measured units, modelled counts |
| **= rung 3c** | **≈20.1M** | **≈25.8M** | |
| (textured faces instead of flat) | ≈21.1M | ≈27.0M | |
| (− W1 flat-coloured walls, §5) | ≈17.3M | ≈24.1M | |

**Confidence:**
- **~85%** that spawn lands **at or about 20M**. Only 2b is unmeasured now, and even at *zero* the
  frame is 21.1M — the step faces cost less than 2a already saved.
- **~95%** that *every* viewpoint stays inside the owner's **20–30M band**. Worst case with 2b
  delivering nothing and textured faces: 26.6M.
- **~0%** that the worst viewpoint reaches 20M without a culling redesign — there `wall_scale_setup_m`
  alone is 4.78M and the walk skeleton plus wedge cull are 6.0M. **Do not promise it.**

The margin comes from a real place: **2a alone paid for the whole rung.** Step faces cost less than
the one optimisation that preceded them.

---

## 4. What the frame looks like

**Kept:** step faces, ledge fronts and door frames — you can see where a wall leads; walls keep the
WPX 1×1 texture, scalelight and fake contrast; floors and ceilings keep zlight banding and the FT1
flat variety, so wall/floor/ceiling stay distinct; rung 3a's near-floor attribution untouched.

**Traded:** faces are flat-shaded (a solid band at the right distance shade); only the NEAREST step
per column, and only from the nearest 24 marking segs, so a long staircase along its axis shows one
riser and then smooth floor, and distant boundaries show none; plane regions stay per-column;
nothing behind the first two-sided boundary is drawn.

The prototype sheet shows all of this. If the owner rejects the look, the answer is a different
trade (per-seg plane regions; textured faces; a bigger `STEP_SEG_BUDGET`), not a knob on the budget.

---

## 5. Reserve levers, in the order to spend them

1. flat faces (already counted; textured costs ~+1.0M)
2. `STEP_SEG_BUDGET` 24 → 12: ~−0.4M at the worst, invisible at spawn (only 2 segs used there)
3. drop runs shorter than 2 rows (distant hairlines): ~−0.2M
4. **W1 flat-coloured walls**: −2.86M spawn / −1.69M worst, **measured** (18.88M / 24.87M today).
   ⚠ This changes the owner's approved look — ask, don't take it.
5. `PNEAR_SEG_BUDGET` 128 → 64. The owner explicitly dislikes this knob. Last.

⚠ **W2S is not a lever**: 21.00M spawn but 27.05M *worse* at the worst viewpoint than WPX's 26.56M.

---

## 6. Ladder — each rung measurable and abortable

| rung | what | gate | abort if |
|---|---|---|---|
| ~~3c-0~~ | ~~**2a** `xtoviewangle` dispatch~~ | ✅ **DONE — 20,594,618 / 25,319,870, byte-exact** | |
| 3c-1 | **2b** — start pass 2 at the prescan's `x`, then the `dmax` end clip | byte-exact, spawn ≤ 19.8M | saving < 0.3M ⇒ take it anyway (it is 3 lines) and move on |
| 3c-2 | oracle: `render_wall_frame(..., near_steps=K, flat_faces=)` matching `rung3c_proto.py`; **PNG to the owner** | near floor still 1 surface; face counts match the prototype | the picture reads badly ⇒ redesign the trade |
| 3c-3 | fj: write-once slots + fill, nothing read | byte-exact vs 3c-1 | — |
| 3c-4 | fj: the emit splice, **monotone** | byte-exact vs the 3c oracle, square + E1M1 | — |
| 3c-5 | sweep 65 viewpoints, full suite, report | spawn ≈ 20M, worst reported honestly | — |

### ⚠ The splice must be monotone (296 columns depend on it)

The 0x0B device's cursor only moves forward and **silently drops a non-monotone pair**. Measured over
5 viewpoints, a nearest lower run starts above the closing wall's `fstart` in 23–69 columns each.
Compose the column top-down with each piece clamped to the previous end — the prototype does exactly
this and writes no pixel twice:

```
ceiling plane [0, up_y1-1] | upper face | ceiling plane [.., top-1] |
wall [top, bot] | floor plane [bot+1, lo_y1-1] | lower face | floor plane [.., H-1]
```

Also: rung 3a's ditto test must compare the slots too (or a per-column signature byte maintained at
fill time), or two columns with identical clip rows and different steps will ditto wrongly.

---

## 7. Pitfalls that each cost a build cycle

- **`SimState.x/y` are SIGNED python ints.** `spawn_state` returns `-0x1a00000`, not `0xFE600000`;
  masking to unsigned puts the player 4e9 units off-map and the walk yields NO segs — a silently
  empty measurement, not a crash. (Cost one debugging cycle this session.)
- **Never price a kernel with an ablate that changes the frame.** Double it into dead registers and
  assert the frame hash is unchanged (`projtwice`, `scaletwice`, `atantwice`).
- **`mul_const` / `ptr_index` read `w/4` nibbles of their source** — zero-extend a 2-nibble register
  first (R11). Symptom: `term=ip<2w`, frame all zeros.
- **A macro body inlined in a loop must `;end` over its own scratch `hex.vec` data** (lesson #2).
- **`hex.set n` is @+4, `hex.mov n` is n(2@)** — set from a constant, don't mov.
- **DOOM's upper-wall end is `ub`, no +1** (`min(ub-1, win_lo)` is inclusive) — 644 pixels.
- **The square room has no two-sided linedefs** — only E1M1 exercises this path.
- **@ is 25–30 ops.** Divide measured totals by MEASURED counts, never modelled ones.
- **Trust the stl complexity docs for the ORDER, not the constant.** `read_table_packed 4` is
  documented at ~289@; converting it away measured ~125@ of real saving. The lever was still right —
  the size was 2.3× off.
- **A generated dispatch table self-invokes its `init`** (the text ends with `<label>.init`), so
  there is nothing to wire at startup — but the `.lookup` index register must be exactly
  `index_nibbles` wide, same as the `read_table_packed` it replaces.
