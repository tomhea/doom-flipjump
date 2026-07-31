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

## 2. Sky

Ceilings whose flat is `F_SKY1` (19 sectors in E1M1) take a texture column chosen by the VIEW ANGLE
and no distance lighting. **Sky has no perspective**, so its run-list bakes once per sky texture
column — 128 lists, ~9 runs each — and the per-column runtime cost is an add + shift + mask for `u`
plus one dispatch. Measured: 139 sky columns at the courtyard viewpoint, +8.7 pairs each. **+0.7M
where sky is visible, 0 indoors.**

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

## 5. Order, and the paydown if the worst case runs hot

Build in this order — cheapest and most self-contained first, so the emit path is understood before
the architectural change:

| rung | feature | gate |
|---|---|---|
| V1 | pseudo-random texture | oracle re-bless (it changes the frame by design), spawn ≤ 22.5M |
| V2 | sky | byte-exact indoors; courtyard viewpoint ≤ +1M |
| V3 | step faces | per `handoff-m13-2s-fast.md` ladder |
| V4 | things | byte-exact where no thing is visible |

**Paydown, if the worst viewpoint runs past ~33M.** The last big unaudited block is the **BSP walk
skeleton (3.88M) and wedge cull (2.02M)** — both stub-measured, and stub measurements have been
wrong three times this session. Then two known-pattern levers: `slopediv_recip`'s
`read_table_packed 3` → dispatch (4th application of the conversion that just paid −1.14M), and a
ROW-RULE operand-order check on `column_params_m`'s two multiplies (11.9k × 160 calls).
