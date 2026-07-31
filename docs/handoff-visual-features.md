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

1. Bake `skybands`: 128 lists (one per sky texture column) over rows [0, H), same format as the
   plane band lists. ~9 runs each, so ~1,150 pairs of static data — trivial beside the 8.9M-char
   wall bank.
2. Per frame: `skybase = (viewangle >> 23) & 127` — one shift and mask.
3. Per column: `u = (skybase + skyoff[x]) & 127` where `skyoff[x]` is a **compile-time** constant
   (a dispatch table over x, exactly like `wnoise`), then `cbufa = skybands + u*stride`.
4. The existing prefix walk emits it. **No new emit path at all.**

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
