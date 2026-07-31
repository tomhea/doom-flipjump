# Handoff — the four visual features, at ~27M/frame

**The job (owner, 2026-07-31):** add step faces, sky, things and wall texturing to the shipped
renderer. 30–35M on the average frame is acceptable, "not so far off" on the worst. Wall texture may
be **pseudo-random** rather than sampled, and 2×2 texel granularity is allowed.

Baseline today: **20,594,618 spawn / 25,319,870 at the worst sweep viewpoint** (E1M1, lines
WPX+FT1+plane_near, after M13-XTADISP).

---

## 0. Prices, re-audited by COUNTING (not modelled)

Emit is charged per `[y2][colour]` pair at a **measured ~330 ops**. Today's frame is **1,434 pairs /
100 ditto columns ≈ 0.47M**, so every feature's emit cost is its counted pair delta
(`scratchpad/feature_cost_audit.py`):

| feature | pairs added | ditto lost | emit | compute | **total** |
|---|---:|---:|---:|---:|---:|
| Sky | +1,209 | −53 | +0.40M | +0.3M | **+0.7M** (outdoors only) |
| Pseudo-random texture | +780 | 0 | +0.26M | +1.2M | **+1.5M** |
| Step faces | +404 | −16 | +0.13M | +1.2M | **+1.3M** / +2.7M worst |
| Things | +2,765 | −74 | +0.91M | +1.9M | **+2.8M** |
| | | | | | **+6.3M / +7.7M** |

**Projected: ~26.9M spawn / ~33.0M worst.** Inside the owner's accepted band, near the hoped 25–30
on the typical frame.

### What the audit overturned

- **True texture mapping is +19.6M, not +0.6M.** 5,612 wall rows are on screen; each needs a texel
  fetch (~1.4k) + colormap + run-merge ≈ 3.2k. And it kills **all 100** ditto columns. Baking it
  away is not an option either: the wall bank is already **8.9M characters / 897k lines**, and the
  assembler is ~cubic — indexing it by texture column too would be 35–70M chars. **Retracted from
  the artifact, which called this cheap.**
- **A column can only be written ONCE, top-down.** The 0x0B record resets `_cl_y = 0` and pairs only
  ever fill forward, so a sprite cannot be overlaid onto a finished column. Things therefore need a
  per-column fragment pre-pass, merged before the column is emitted — not a second pass.

---

## 1. Pseudo-random texture — the owner's idea, and the picture that fixed it

Don't FETCH a texel, DERIVE one. Keep the baked per-(texture, height) run-list — so colours and
vertical structure still come from the real texture — and perturb each run by a hash of the column.

⚠ **XORing the palette index is WRONG and the prototype caught it.** DOOM's palette runs
dark→bright with the index, so `0 ^ 3` turns black into light grey: a dark wall erupts in white
confetti (`scratchpad/noise_tex_proto.py`, variant history).

**The right operator is the COLORMAP** — literally "this same colour, N steps darker", 34 rows of it
already in the program and already reachable through the `cm.apply` dispatch. So the noise darkens a
texel by 0..3 steps: in-hue by construction, reads as surface grain.

```
h = x ^ (x >> 2) ^ (cell * 5) ^ (seg << 1)      # xors and shifts only -- ~27 ops each in fj
h ^= h >> 3                                     # no multiply, NO LOOKUP TABLE
noise = h & 3                                   # colormap row to darken by
```

Cost: one `cm.apply` (~540) per emitted pair — the bank must store the BASE texel rather than the
pre-colormapped colour, which keeps it exactly the same size — plus the extra pairs the grain
creates. **+1.5M.** `cell` = run index (free) or `(y - y0) >> 1` for the owner's 2×2 granularity;
measured pair counts are within 2% of each other, so **use 2×2**.

---

## 2. Sky — ✅ ORACLE DONE, fj design settled

Ceilings whose flat is `F_SKY1` (19 sectors in E1M1) take a texture column chosen by the VIEW ANGLE
and no distance lighting. **Sky has no perspective**, so its run-list bakes once per sky texture
column. Measured: SKY1 downscales to **128 wide × 64 tall**; 139 sky columns at the courtyard
viewpoint, +8.7 pairs each; **0 pixels change indoors** (byte-exact) and 2,111 in the courtyard.

### The fj shape — sky is a per-column CHOICE OF CEILING BAND LIST, nothing more

The ceiling is already emitted by walking a baked `[y2_cumulative][colour]` band list whose address
sits in `cbufa`. A sky column is **exactly the same walk against a different list**, because a sky
column has no perspective and no lighting — so it IS just a band list. Therefore:

1. Bake `skybands`: **256 lists** over rows [0, H), same format as the plane band lists.
2. Per frame: `skybase = (viewangle >> 23) & 127` — one shift and mask, once.
3. Per column: `u = skybase + skyoff[x]` where `skyoff[x]` is a **compile-time** constant (a
   dispatch table over x, exactly like `wnoise`), then `cbufa = skybands + u*stride`.
4. The existing prefix walk emits it. **No new emit path at all.**

⚠ **Why 256 lists and not 128:** both addends are already in [0, 127], so `skybase + skyoff[x]`
never exceeds 254 — and with entry `u` holding sky column `u & 127`, **the wrap needs no mask**.
That matters because fj has no cheap AND: masking would cost a dispatch, or a compare-and-subtract,
*per column*. The duplicate half is pure static text (~477k chars against the 8.9M-char wall bank).
Trading baked data for an omitted runtime op is the same bargain the wall bank already makes.

`ReferenceModel.sky_texel` already takes this same base+offset decomposition, so the oracle stays
authoritative bit for bit.

⚠ **Sky columns must join the DITTO chain** (the V1 lesson): two adjacent sky columns have different
`u`, so they render differently even with identical clip rows and plane id. Compare `u` — or simply
refuse the ditto when the column is sky — or the frame diverges exactly as V1's did at columns 12
and 144.

---

## 3. Step faces

Per `docs/handoff-m13-2s-fast.md` §2c: nearest K=1 upper and lower run per column, flat-shaded,
write-once slots, `STEP_SEG_BUDGET = 12`. Costed on measured units (93k per face-carrying seg setup,
11.9k per column projection, and the ROW-RULE sparse-delta trick for the back projection). Add the
slot writes (~5.4k each) and a per-column ditto signature byte, both of which the earlier estimate
missed. **+1.3M / +2.7M.**

---

## 4. Things

292 in E1M1. Because a column is write-once, this is a **pre-pass**, not an overlay:

1. Walk the BSP as today; for each visited subsector, iterate its things (DOOM's own arrangement —
   avoids a 292-thing cull at ~2k each).
2. Project each visible thing once (~27k: transform + one reciprocal divide) into per-column
   write-once fragment slots `[sprite][bucket][depth]`, nearest-first.
3. When a column closes, merge its fragments (those nearer than the wall) into the run list it was
   about to emit.

Sprite columns bake per (sprite frame, size bucket) exactly as wall columns bake per (texture,
height). Needs a per-column **depth byte**, which the renderer does not keep today (it keeps a 1-bit
`drawn`). **+2.8M** at a thing-heavy viewpoint.

---

## 4a. ⚠ THE DITTO CHAIN — the trap every remaining feature will hit

The `0xFE` record means "copy column x−1", and its guard (`frame_render.fj`, label `dgchk`) compares
only the clip rows and the plane id. **Anything that changes a column's CONTENT without changing its
CLIP ROWS must be added to that chain**, or the renderer emits a ditto for two columns that now
differ and the frame diverges from the oracle.

V1 hit this and it cost a build cycle: the first differing pixels were at column 12 and column 144,
both exactly ≡ 0 (mod 4) — the `x>>2` grain-group boundaries. The fix pattern is now in the tree:
lift the per-column value's lookup into pass 2 (it must be known BEFORE the emit/ditto decision),
add a compare to the chain, and save it alongside `dct`/`dfs` on the emit path.

Still to do, each for the same reason: **sky `u`** (V2), the **step-face slots** (V3), the
**sprite fragments** (V4).

## 5. Order, and the paydown if the worst case runs hot

Build in this order — cheapest and most self-contained first, so the emit path is understood before
the architectural change:

| rung | feature | state |
|---|---|---|
| **V1** | pseudo-random texture | ✅ **SHIPPED, BYTE-EXACT — 22,192,782 spawn / 26,405,793 worst** |
| **V2** | sky | oracle ✅ done + verified; fj design settled (§2), not yet wired |
| V3 | step faces | oracle + fj to do, per `handoff-m13-2s-fast.md` §2c |
| V4 | things | oracle + fj to do, per §4 — pre-pass, never an overlay |

**Measured after V1:** 22.19M spawn / 26.41M worst. Remaining budget to the owner's 30–35M: ~8M
typical. V2 +0.7M, V3 +1.3M, V4 +2.8M ⇒ **~27M typical / ~31M worst**.

⚠ V1's real price was **+1.6M / +1.1M**, not the +58k an intermediate build reported — that build
was cheap *because* its ditto was broken and skipping columns it should have emitted. **A
performance number taken from a build that is not byte-exact is not a performance number.**

**Paydown, if the worst viewpoint runs past ~33M.** The last big unaudited block is the **BSP walk
skeleton (3.88M) and wedge cull (2.02M)** — both stub-measured, and stub measurements have been
wrong three times this session. Then two known-pattern levers: `slopediv_recip`'s
`read_table_packed 3` → dispatch (4th application of the conversion that just paid −1.14M), and a
ROW-RULE operand-order check on `column_params_m`'s two multiplies (11.9k × 160 calls).

---

## V2 STATUS (end of session) — wired, spawn byte-exact, sky branch not firing

`emit_wall_renderer(..., wall_noise=True, sky=True)` assembles and runs. Gate result:

| viewpoint | ops | result |
|---|---:|---|
| spawn (no sky in view) | 23,492,508 | ✅ **BYTE-EXACT** |
| courtyard (139 sky columns) | 19,383,757 | ❌ 2,111 px differ, first at (0,0) |

**Read the failure precisely: 2,111 is EXACTLY the pixel count the oracle's sky changes at that
viewpoint.** So the sky path is not firing at all — this is not a wrong-sky-column bug, not an
off-by-one, and not a ditto bug. Everything else is right: spawn byte-exact proves the machinery is
harmless where sky is absent, and proves the ditto/plane-address paths survived the change.

Ruled out already:
- `pval8` IS the effective pid — `lines_col_plane`'s `own` path does `hex.mov 2, pval8, seg_pid`
  before `lines_pid_addrs pval8, ...`, so the register my macro indexes is the right one.
- F_SKY1 really is reachable: 19 sectors carry it and it appears among the walked segs' ceiling
  flats (32 distinct names).
- `hex.if0 2, issky, notsky` has the right polarity (jump when zero = not sky).

**Hypothesis (a) is DISPROVEN — do not re-test it.** The generated table is correct: 152 pids, 153
entries, **19 sky entries** at pids 41, 42, 64, 65, 69, 70, 73, 74, 75, 76, 77, 81, … and 152 < 255
so `index_nibbles=2` does not truncate. The data is right; the *lookup or the branch* is wrong.

Also disproven: `sky` reaches the macro (spawn cost rose +1.30M, which only happens if the sky
macros are emitted and running), and the `if0` polarity is right (jump-when-zero = not sky).

**Remaining candidates, in order:**
1. **`cbufa` is recomputed or overwritten after `lines_sky_ceil` runs.** `lines_col_plane` caches on
   `cpid` and only calls `lines_pid_addrs` when the pid CHANGES — so for a run of same-pid columns
   the plane address is stale-but-valid, while the sky override is applied every column. Check
   nothing downstream re-derives `cbufa` between the override and `emit_col_lines`.
2. **The ceiling prefix is skipped entirely.** `emit_col_lines` does `hex.if0 2, ctake, wall` — if
   `ctake` is 0 for these columns the sky list is never walked no matter how right the address is.
   Print `ctake` for a known sky column at the courtyard.
3. ~~The `hex.add_constant` label arithmetic~~ — **DISPROVEN.** Switched to the proven
   `hex.set w/4, tskb, skybands` + `hex.add` idiom; the ops moved (23,492,508 → 23,369,785, so the
   code really did change) and the diff is still **exactly 2,111**. Not the base address.

### ⚠ A SECOND, INDEPENDENT BUG found by re-reading (fix it regardless)

`lines_sky_ceil` overrides only **`cbufa`**, the ASCENDING ceiling list. But `emit_col_lines` walks
`cbufd` — the DESCENDING list — for the straddle case when `ctake > CENTERY`
(`hex.cmp 2, ctake, ccy, wall, wall, cdesc2`). So any sky column tall enough to cross the horizon
would emit plane bands for its lower part even once the main bug is fixed. Override `cbufd` too, or
point both at the sky list (sky has no horizon split — that's the whole reason it is a single
unperspectived list).

**That this did not change the pixel count (still exactly 2,111 = every sky pixel) is itself
evidence**: it means the sky path contributes NOTHING at all, so the failure is upstream of the
address — at the `skypid.lookup`/`if0` branch, or at whether the ceiling prefix runs for these
columns at all. Test next, cheapest first: make `lines_sky_ceil` unconditionally take the sky branch
(delete the `if0`) and rebuild — if the courtyard still shows no sky, the fault is in the prefix
walk (candidate 2), not the branch.

⚠ Also worth pricing before shipping V2: the sky machinery costs **+1.30M at spawn where NO sky is
visible** (22,192,782 → 23,492,508). `lines_sky_base` runs per column and does a `hex.mov 8` +
`hex.shr_hex 8,6` + `hex.mov 2`; hoisting it to once per FRAME is the obvious fix and should recover
most of that.


---

## V2 STATUS UPDATE — three bugs fixed, one left, and it is understood

| build | courtyard diff | what changed |
|---|---:|---|
| wired | 2,111 px | — |
| + `hex.set` label base | 2,111 px | base was fine |
| + 3x bank (unmasked range) | 2,111 px | real bug, but not this one |
| **+ count header (plane format)** | **2,039 px** | ✅ real: 72 px now correct |

Spawn is **BYTE-EXACT at every one of these** (22,608,094 now), so nothing has ever escaped the
feature.

### The remaining 2,039: the ceiling is TWO half-lists, and sky only fills one

`emit_col_lines` walks `cbufa` for the ascending half and, when `ctake > CENTERY`, falls through to
`cdesc2` which walks **`cbufd`** — the plane bank keeps four half-lists per pid (ceiling asc,
ceiling desc, floor asc, floor desc), each `half_slots` long, because the zlight ordinals restart at
CENTERY. `lines_sky_ceil` currently overrides only `cbufa`, so any sky column reaching past row
CENTERY emits SKY above the horizon and PLANE BANDS below it.

**Fix:** bake the sky bank as two halves per texture column — rows [0, CENTERY) and [CENTERY, H) —
laid out exactly like a pid's ceiling pair, and point both `cbufa` and `cbufd` at them. Sky has no
perspective so the split is purely mechanical (it exists only to match the walker's layout), but the
walker's layout is not optional.

This is the same lesson as the other three V2 bugs, for the fourth time: **the consumer's format is
the specification.** Bank size, label idiom, list format and now half-list layout were each assumed
from a neighbouring subsystem rather than read off `emit_col_lines`.

---

## V3 fj — the design, ready to wire (oracle is DONE and rendering)

Oracle: `render_wall_frame(..., near_steps=True)` draws 463 / 654 / 154 face pixels at spawn /
(-480,256) / (-309,-44). Default hash unchanged, so V1+V2 stay byte-exact.

### Data (compile time)
Nothing new. A step face reuses the WPX wall bank: it is a wall run of the seg's lower/upper
texture, flat-shaded, so it needs only the block index the bank already assigns.

### Per-column state (runtime)
Two write-once slots per column, filled by the claim walk in `lines_col_plane`'s neighbourhood:
`ustep[x] = [y1][y2]`, `lstep[x] = [y1][y2]` — 4 bytes each, 0 = empty. Write-once is what makes
"nearest" free: the walk is front-to-back, so the FIRST writer is the nearest.

Bound it with `STEP_SEG_BUDGET = 12` face-carrying segs (a counter register, not a per-seg flag).
That bound is load-bearing: a face-carrying seg pays a full ~93k `wall_scale_setup`, and at a heavy
viewpoint all 128 marking segs would otherwise qualify. Measured: only **2** boundaries at spawn
have a face at all, so the budget costs nothing there and only trims the worst case.

### Emit (the splice)
`emit_col_lines` composes top-down; insert the faces as two extra pieces, each clipped to the
previous piece's end so the column stays MONOTONE:

```
ceiling prefix [0, min(ctake, up_y1))     upper face [up_y1, up_y2]     ceiling rest to ctake
wall [ctake, fstart)
floor prefix [fstart, lo_y1)              lower face [lo_y1, lo_y2]     floor suffix to VIEW_H
```

Each face is one `[y2][colour]` pair (flat-shaded), so ~+404 pairs/frame ≈ +0.13M emit.

### ⚠ The two traps this rung inherits
1. **The ditto chain.** `ustep[x]`/`lstep[x]` change a column's CONTENT without changing its CLIP
   ROWS, so they MUST join the `dgchk` compare or the frame diverges — exactly as V1's grain did at
   columns 12 and 144. Third feature, same trap.
2. **The consumer's format is the specification.** V2 cost four builds to bank size, label idiom,
   list format and half-list layout, each assumed from a neighbouring subsystem. Read the emit path
   before baking anything.

### And one from V3's own oracle
`STEP_FACE_BASE = 96`, NOT `WALL_BG` (=4, near-WHITE in DOOM's ramp — the faces blew out). A
palette INDEX carries no brightness ordering you can guess at; that is the same bug as V1's
confetti, twice.
