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

⚠ **The call count matters as much as the total.** `wall_scale_setup_m` lives in pass 2, which runs
only when pass 1 set `proceed` — i.e. only for segs with at least one unclaimed column: **28 at
spawn, 51 at the worst**, NOT the 169/202 in-frustum segs. (The in-frustum count gives 15.4k vs
23.6k — a 1.5× spread for identical code, which is the tell that the count is wrong.)

| kernel | calls/frame | spawn | worst | frame share |
|---|---:|---:|---:|---:|
| `proj.column_params_m` | 160 / 160 | **11,853** | **11,426** | 9.2% / 7.2% |
| `proj.wall_scale_setup_m` | 28 / 51 | **92,781** | **93,640** | 12.6% / **18.9%** |

The two viewpoints agree to 0.9%, and the price reconciles exactly with the measured primitives in
`fj-cost-model`:

```
2 x hex.fixed_div 8,4   = 2 x 38,500 = 77,000      <- 83% of it
+ scalestep hex.div 8,2 =              9,361
+ finesine / muls / folds             ~7,000
                                 total ~93,400     (measured: 92,781 / 93,640)
```

**So the single biggest item in the frame is two 32-bit divides per seg.** `hex.fixed_div 8,4` is the
most expensive primitive in the whole cost table. That is rung 3d (§8), not this rung.

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

### 2b. ~~Clip pass 2's column loop to the unclaimed window~~ — ❌ **MEASURED AND DROPPED**

Worth **≤0.08M**, and negative once the mandatory fix is paid. Two reasons, both measured
(`scratchpad/prefix_len.py`):

1. **Pass 2 barely walks anything.** Only 28/51 segs reach it, visiting ~207/200 columns of which
   160 are useful. The "840 visits, 680 wasted (81%)" figure in §1 counts columns walked by pass 1's
   **prescan**, which then rejects those segs outright — that work is not pass 2's and it already
   pays for itself many times over (removing the prescan costs +9.5M). Prefix is 6/26 columns and
   suffix 37/14 across the whole frame.
2. **Skipping the prefix is not free.** `scale` accumulates `scale += scalestep` on EVERY column
   including drawn ones, so starting at the prescan's column needs `scale += scalestep * (x - x1)`
   once per seg (~3.5k) — more than the ~0.2 prefix columns per seg are worth. I built this, and it
   came back NOT byte-exact for exactly this reason.

Recorded so nobody rebuilds it. The END clip needs no scale fix, but at 37/14 columns it is worth
~0.07M — also not worth the `[dmin, dmax]` machinery.

### 2b-OLD (superseded, kept for the reasoning)

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
| extra `wall_scale_setup_m` (face-carrying segs) | 2 / 12 | **93k** | 0.19M | 1.12M |
| back-sector projection, **sparse-delta** (below) | 54 / 108 | ~3.8k | 0.21M | 0.41M |
| slot checks over the claim scan's pairs | 245 / 247 | ~0.5k | 0.12M | 0.12M |
| the per-column splice test | 160 / 160 | ~1k | 0.16M | 0.16M |
| | | | **+0.68M** | **+1.81M** |

⚠ **`STEP_SEG_BUDGET` is 12, not 24** — at 93k per face-carrying seg it is the dominant term at the
worst viewpoint (24 segs would be +2.94M). At spawn only **2** segs want a face, so the budget costs
nothing there and only trims the heavy viewpoint. Tune it against the prototype's picture, not
against the arithmetic.

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
| = the baseline in the tree now | **20,594,618** | **25,319,870** | ✅ |
| ~~− 2b column-loop clip~~ | ~~−1.0M~~ | ~~−0.75M~~ | ❌ measured ≤0.08M — dropped |
| + 2c step faces, K=1, flat, budget 12 | +0.68M | +1.81M | measured units, counted populations |
| **= rung 3c** | **≈21.3M** | **≈27.1M** | |
| (textured faces instead of flat) | ≈22.3M | ≈28.3M | |
| **then rung 3d (§8), the two divides** | **≈19.4M** | **≈23.7M** | the route to ≤20M |
| (or −W1 flat-coloured walls instead, §5) | ≈18.4M | ≈25.4M | owner's look call |

**Confidence, stated on measured ground:**
- **~90%** that rung 3c lands **inside the owner's 20–30M band at every viewpoint** — every term is
  now either measured or a counted population times a measured unit price.
- **~75%** that spawn lands **at about 21M**, i.e. *close to* 20M but **not under it**. I am no
  longer claiming ≤20M for rung 3c alone: 2a's −1.14M was real but 2b's −1.0M was not, and the step
  faces cost more than I first priced because `wall_scale_setup_m` is 93k, not 15k.
- **≤20M needs one more lever** — either rung 3d (§8, the two `fixed_div`s, worth ~1.9M/~3.4M) or
  W1 flat-coloured walls (−2.86M/−1.69M, measured, but it changes the look). **Rung 3d is the
  honest route and it is a proven pattern; W1 is the owner's call.**
- **~0%** that the worst viewpoint reaches 20M without a culling redesign. **Do not promise it.**

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
- **`scale` accumulates on EVERY column, drawn or not.** Any change to pass 2's column loop bounds
  must carry `scale` forward or the frame silently shifts. This killed 2b.
- **The assembler rejects an unused label**, so removing the last user of a `<`-list global is a
  hard error, not a warning to ignore.
- **The Windows console is cp1255** — a `⚠` in a probe's `print` raises `UnicodeEncodeError` and can
  destroy the diagnostic you actually needed. Keep probe output ASCII.

---

## 8. Rung 3d — the two divides. This is the route to ≤20M.

§1a's reconciliation says **two `hex.fixed_div 8,4` are 77k of `wall_scale_setup_m`'s 93k**, i.e.
**2.16M at spawn and 3.93M at the worst viewpoint** — the largest single item in the frame by a wide
margin, and `fixed_div 8,4` at 38,500 ops is the most expensive primitive in the cost table.

`scale_from_global_angle` computes `FixedDiv(projection·sin, den)` twice per seg (at x1 and at x2).
The lever is the same reciprocal-dispatch pattern that already worked for `slopediv_recip8` and
`tantoangle` and `xtoviewangle`: a table of reciprocals indexed by the denominator's high bits, then
a multiply.

⚠ **Unlike 2a, this is NOT byte-exact.** DOOM's `SlopeDiv` genuinely *is* a coarse table, which is
why `slopediv_recip8` was exact; `FixedDiv` here is a true 32-bit division, so a reciprocal changes
low bits and occasionally shifts a row by 1. **The oracle must adopt it too**, and the gates re-bless
against the new oracle — the same deal rung 3c already makes for the step faces. Estimated
**−1.5M to −1.9M spawn / −2.8M to −3.4M worst**, which is what takes the frame under 20M.

Cheaper byte-exact fallback worth measuring first: `hex.div n` is **n²(10@+20)**, so narrowing the
divide's width where the operand ranges genuinely allow it is quadratic in payoff and changes
nothing. Check the actual ranges of `num`/`den` before assuming 8 nibbles are needed.
