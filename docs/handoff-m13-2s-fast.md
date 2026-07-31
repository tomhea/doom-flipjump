# Handoff — M13-2S rung 3c: two-sided walls **with the frame at ~20M**

**The job:** the game must render two-sided geometry (steps, ledges, door frames) at **~20M
ops/frame**, trading visual ACCURACY where needed but never visual CLEARNESS — you must always be
able to tell where a wall leads, and walls, floors, ceilings and other walls must stay distinguishable.

Rung 3b (`two_sided=True`) is byte-exact vs `render_frame_2s` and costs **131M**. Rung 3a
(`plane_near`, shipped) costs **21.74M spawn / 26.56M worst-of-65** and has no step faces. Neither is
the answer, and — this is the point of v3 — **adding steps to rung 3a is not the answer either,
because rung 3a is itself too expensive to carry them.** This rung cuts the base first.

> **Document history.** v1: "one upper + one lower per column", budget ~36M — measured, and its core
> rule dropped 44% of runs. v2: K=2 slots + DOOM's incremental projection, budget ~28–32M — honest
> but it could not reach 20M. **v3 (this one) decomposes the SHIPPED base by measurement and spends
> the two big items it found.** Everything below is a measured number or a stated estimate with its
> basis.

---

## 1. The shipped base, decomposed by measurement

Every row is an ablation on the current tier (`plane_near`, WPX+FT1), E1M1 spawn and the worst of the
65-viewpoint sweep:

| component | spawn | worst | how it was measured |
|---|---:|---:|---|
| BSP walk skeleton + per-seg xorby + startup/present | 3,878,019 | 3,913,873 | ablate `segstub` |
| the wedge cull | 2,015,397 | 2,108,794 | `wedgestub − segstub` |
| `point_to_angle` (after M13-ATANDISP) | ~1,700,000 | ~2,000,000 | `atantwice`, scaled for §14's cut |
| **per-column projection (`column_params_m`)** | **4,230,490** | 1,332,496 | ablate `noproj` |
| WPX wall texture detail (vs a flat wall) | 2,860,155 | 1,689,951 | `WPX − W1` |
| ceiling/floor band emit | 1,578,883 | 1,668,409 | ablate `emitnowalk` |
| **residue: the per-column loop, the occlusion prescan, emit framing** | **5,473,990** | **13,843,602** | total − the above |
| **total** | **21,736,934** | **26,557,125** | |

Two facts to keep: the occlusion prescan is worth **9.5M at spawn** (removing it costs 31.26M) so it
stays, and **W2S is not cheaper than WPX** (21.00M spawn but 27.05M worst) so the wall tier is not a
lever. The levers are the projection and the residue.

---

## 2. The three changes

### 2a. Incremental per-column projection — DOOM's own method (−3.5M spawn)

`column_params_m` runs a 6-row multiply per column per seg (~720@ ≈ 19.4k ops). DOOM never does
that: it keeps `topfrac` in 16.16 and adds a per-seg step.

```
topstep = -FixedMul(worldtop,  scalestep)         once per seg
topfrac =  centeryfix - FixedMul(worldtop, scale_at_x1)
per column:  top = topfrac >> 16 ;  topfrac += topstep      (~120@ ≈ 3.2k ops)
```

Four accumulators (front ceil/floor, back ceil/floor) replace one or two `column_params_m` calls.
Measured target: **4.23M spawn / 1.33M worst**, of which ~5/6 goes. It is not bit-identical
(rounding, occasionally ±1 row), so **the oracle adopts it too** and the gates stay byte-exact
against the new oracle. Apply it to the SHIPPED tier first, on its own, and re-bless.

### 2b. Clip pass 2's column loop to the unclaimed window (−2M spawn, −4M worst)

The residue is per-column loop overhead — `read_byte drawn`, clamps, ditto test, `drawn` write, the
pointer steps — paid for **every** column of every seg that passes the prescan, including the long
already-drawn prefixes and suffixes of that range. The prescan already walks to the first unclaimed
column; have it **record that index**, and keep the global `[pmin, pmax]` unclaimed window that rung
3a's two-sided leaf already maintains (`scratchpad`-proven there: 769 column reads → 201). Then pass 2
starts at `max(x1, first_unclaimed, pmin)` and ends at `min(x2, pmax+1)`.

Byte-exact by construction: the skipped columns are already drawn, and a drawn column's body is a
no-op. This is the one that attacks the **13.8M worst-case residue**, which is why the worst case
improves more than spawn.

### 2c. The step faces, flat-shaded (+2.3M spawn)

Per column keep the **nearest K upper and K lower runs** (K=2; measured distribution at spawn:
uppers `{0:76,1:34,2:34,3:16}`, lowers `{0:80,1:55,2:12,3:9,4:4}`, so K=2 keeps ~80% of runs where
K=1 keeps 56%), in write-once 4-byte slots `[blk:2][y1][y2]` filled nearest-first by the front-to-back
walk. A seg whose slots are full costs one `read_byte` and a branch.

**Flat-shaded**: a step face emits ONE pair — the block's mid-texel at that run's scalelight row —
instead of its WPX 1×1 run list. ~272 runs/frame × ~1,050 ops per emitted pair (the measured rate
from the band emit: 1.58M for ~1,500 pairs) ⇒ **+0.3M** for the faces, plus ~2.0M for the fills.
Textured faces instead cost ~+2.3M more; make it a flag and let the owner pick after seeing both.

Because every piece is known when the one-sided wall closes the column, the record is emitted inline
exactly as rung 3a does it: **no region buffer, no flush pass** — those are what made rung 3b cost
131M.

---

## 3. The projection

| | spawn | worst-of-65 |
|---|---:|---:|
| shipped rung 3a today | 21.74M | 26.56M |
| − 2a incremental projection | −3.5M | −1.1M |
| − 2b unclaimed-window clip | −2.0M | −4.0M |
| + 2c step faces, flat-shaded | +2.3M | +2.5M |
| **= rung 3c** | **≈18.5M** | **≈23.9M** |
| (with textured step faces instead) | ≈20.5M | ≈25.9M |

**Confidence, stated honestly:**
- **~85%** that spawn lands at **20M or below** with flat-shaded faces. 2a is arithmetic on a measured
  4.23M with a formula that is 6× cheaper and is what DOOM itself does; 2c's +2.3M rests on a
  measured ops-per-pair rate; only 2b's −2M is an estimate (of a measured 5.47M residue).
- **~65%** that the worst-of-65 lands at **24M or below** — 2b's −4M is the least certain number here
  and the worst case is where it matters most. If it under-delivers, §5's reserve levers are real.
- **Near 0%** that the worst-of-65 reaches 20M without a culling redesign: at that viewpoint the walk
  skeleton + wedge alone are 6.0M and the residue is 13.8M spread over per-seg/per-column loop
  overhead, not any one kernel. **Do not promise it.**

---

## 4. What the frame looks like

**Kept:** step faces, ledge fronts and door frames — you can see where a wall leads; walls keep the
WPX 1×1 texture, their scalelight row and fake contrast; floors and ceilings keep zlight distance
banding and the FT1 flat variety, so wall/floor/ceiling stay distinct; rung 3a's near-floor
attribution (the owner's original complaint) untouched.

**Traded:** step FACES are flat-shaded (a solid band at the right distance-shade, not a textured
strip) unless the textured flag wins; only the nearest 2 steps per column, so a long staircase seen
along its axis shows two risers and then smooth floor; plane regions stay per-column rather than
per-seg, so a distant room's floor takes the near sector's surface; nothing behind the first
two-sided boundary is drawn; ±1-row differences from the incremental projection.

⚠ **Put the staircase in front of the owner as a PNG at 3c-1, before any fj work.** That single image
decides whether this design ships; if it reads badly the answer is a different trade (per-seg plane
regions, no step textures), not a knob.

---

## 5. Reserve levers, in the order to spend them

1. flat-shaded faces (already counted; textured costs +2.0M)
2. **K=1 for uppers only** — lowers are the common case in E1M1 and read as steps: ~−0.6M
3. drop runs shorter than 2 rows (distant hairlines): ~−0.3M and fewer fills
4. **W1 walls** (flat-coloured, no 1×1 texture): −2.86M spawn / −1.69M worst. ⚠ This is the owner's
   approved look; ask, don't take it.
5. `PNEAR_SEG_BUDGET` 128 → 64: the owner disliked forcing this knob. Last.

---

## 6. Ladder — each rung is measurable and abortable

| rung | what | gate | abort if |
|---|---|---|---|
| 3c-0 | **2a** on the shipped tier, oracle first | re-blessed rung-3a goldens, full suite, spawn ≤ 18.5M | saving < 2M ⇒ the multiply wasn't the cost, re-measure |
| 3c-1 | **2b** — prescan records the first unclaimed column + global window | byte-exact vs 3c-0 (pure optimisation), spawn ≤ 16.5M, worst ≤ 21.5M | saving < 1M ⇒ the residue is elsewhere; profile the loop body before continuing |
| 3c-2 | oracle: `render_wall_frame(..., near_steps=K, flat_faces=)`; **PNG of the staircase to the owner** | host gates: near floor still 1 surface; step counts vs `render_frame_2s` | the picture reads badly ⇒ redesign the trade, not the code |
| 3c-3 | fj: the write-once slots + fill (nothing read) | byte-exact vs 3c-1 | — |
| 3c-4 | fj: the emit splice, **occlusion-correct** | byte-exact vs the 3c oracle, square + E1M1 | — |
| 3c-5 | sweep 65 viewpoints, full suite, report | spawn ≈ 20M, worst reported honestly | — |

### ⚠ The splice must be occlusion-correct (296 columns depend on it)

Measured over 5 viewpoints: a nearest lower run starts ABOVE the closing wall's `fstart` in 23–69
columns each. The step is nearer, so it wins and the wall shrinks:

```
wall_top = max(ctake,  last_upper_y2)      wall_bot = min(fstart, first_lower_y1)
```

and every piece is emitted only if non-empty, each start clamped to the previous end, so the y2
sequence is strictly monotone — **the 0x0B device only moves its cursor forward and silently drops a
non-monotone pair.** Also: rung 3a's ditto test must compare the slots (or a per-column signature
byte maintained at fill time, the `pclm` trick), or two columns with identical clip rows and
different steps will ditto wrongly.

---

## 7. Pitfalls that each cost a build cycle

- **`mul_const` / `ptr_index` read `w/4` nibbles of their source** — zero-extend a 2-nibble register
  first (R11). Symptom: `term=ip<2w`, frame all zeros.
- **A macro body inlined in a loop must `;end` over its own scratch `hex.vec` data** (lesson #2).
- **`hex.set n` is @+4, `hex.mov n` is n(2@)** — set from a constant, don't mov.
- **Multiplying a COUNT by `5*dw` instead of 5** ran a compare loop 320× too long; `dw` is for
  addresses only.
- **DOOM's upper-wall end is `ub`, no +1** (`min(ub-1, win_lo)` is inclusive) — 644 pixels.
- **The square room has no two-sided linedefs** — only E1M1 exercises the two-sided path, but the
  square room is still the right first gate for everything else.
- **@ is 25–30 ops.** Divide measured totals by MEASURED counts, never modelled ones.
