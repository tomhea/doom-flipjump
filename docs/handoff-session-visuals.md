# Session handoff — the four visual features (2 of 4 shipped)

**Branch:** `m13opt3-early-out`. Both build configurations green, full lines gate **11/11**.

---

## 1. Where the frame is

| build | spawn | courtyard (1400,1200) | state |
|---|---:|---:|---|
| session start | 21,736,934 | — | |
| M13-XTADISP | 20,594,618 | — | ✅ byte-exact |
| default (features off) | 20,597,739 | — | ✅ byte-exact |
| **V1 grain + V2 sky** | **23,536,484** | **20,134,978** | ✅ **11/11 gate** |

The renderer gained textured walls and sky **and is faster than at session start**. Inside the
owner's 25–30M hope; ~6.5M of headroom remains to the 30–35M ceiling for V3 (+1.3M) and V4 (+2.8M).

---

## 2. What shipped

### M13-XTADISP — `xtoviewangle` by dispatch (−1.14M / −1.24M, byte-exact)
`wall_scale_setup` opened with two `read_table_packed 4` reads of a 161-entry table, once per
in-frustum seg. Converted to a D4 dispatch table behind a lines-only `proj.wall_scale_setup_m`.

### V1 — pseudo-random wall texture (the owner's idea; +1.6M vs +19.6M for real sampling)
Don't FETCH a texel, DERIVE one. The baked per-(texture, height) run-list still supplies colours and
vertical structure; each run is pushed down `wall_noise(x)` colormap rows. No lookup table at all.

Three things measurement overturned, all counter to the obvious choice:
- **XOR on a PALETTE INDEX is wrong** — DOOM's palette runs dark→bright with the index, so `0^3`
  turns black into light grey and the walls erupt in white confetti. The **colormap** is the right
  operator: "same colour, N steps darker", in-hue by construction.
- **Key the hash on `x>>2`, not `x`.** Per-column noise breaks DITTO (100 → 44 columns; ditto is
  worth 4.83M). Grouping four columns: ditto holds at 76 and the emit delta is +375 pairs instead of
  +1,198 — a third of the cost for *more* visible grain.
- **Step 0/4/8/12, not 0..3.** Colormap row 0 is the identity, so a small jitter barely moves an
  already-dark colour: 375 px changed vs **2,896**.

In the lines tier `cm.emit` colormaps AND emits in one dispatch, so the grain REPLACES a `byte.emit`
rather than adding beside it.

### V2 — sky (byte-exact both viewpoints)
Sky is the only surface with no perspective and no distance lighting, so a sky column depends on the
texture column `u` alone → **it IS just a band list**, and the feature reduces to a per-column choice
of ceiling band-list address with **no new emit path**.

- `skybase = viewangle >> 24` once per frame (SKY_TURN=2 chosen so the shift is exactly 6 nibbles —
  fj shifts cheaply only by whole nibbles).
- `u = skybase + skyoff[x]`, `skyoff` a compile-time dispatch table. **No mask**: the bank holds
  `3*tw` lists with entry `u` carrying column `u & (tw-1)`, so the sum can never leave it.
- `cbufa`/`cbufd` point at the sky pair; the existing prefix walk emits it.

---

## 3. What did NOT ship

**V3 step faces** — oracle DONE and rendering (463 / 654 / 154 face px at spawn / (-480,256) /
(-309,-44); `scratchpad/v3_steps.png`). `render_wall_frame(..., near_steps=True)`. **fj unwired.**

**V4 things** — designed against counted populations and measured unit prices. **Not started.**

### V3 fj — scope, measured from the code

`seg_pass1_leaf_body_ts` (`frame_render.fj:1188`) is where a marking seg claims columns, and it has
**no projection machinery at all** — its `<` list is geometry and claim state only. So V3 is not a
splice into existing code; it adds a projection path to a leaf that has never projected:

1. `proj.wall_setup_sgn` + `proj.wall_scale_setup_m` per face-carrying seg (**~93k each** — which is
   why `STEP_SEG_BUDGET = 12` must gate the SETUP, not the fill)
2. a back-sector `column_params_m` per candidate column (11.9k; use the ROW-RULE sparse-delta form
   `back_row = front_row + (wt_front − wt_back)*scale` with the baked delta SECOND ⇒ ~3.8k)
3. write-once slots `ustep[x]`/`lstep[x]` + the fill
4. a face-seg budget counter, separate from `n_tsv`
5. the two-piece splice in `stream.emit_col_lines`
6. the `dgchk` ditto-chain entry

**The fill site** is the claim loop at `frame_render.fj:1247-1262` — labels `loop → body → claim →
next`, walking `pclm[]` with `pptr`. `claim:` is where a column is first attributed, i.e. exactly
where "the first writer is the nearest" holds. Land it in increments: **storage + fill first (it is
byte-exact, because nothing reads the slots yet)**, then the splice.

Calibration: **V2 reused an existing walk, added no new machinery, and still took six builds.**
V3 is strictly larger.

---

## 4. Prices (counted populations × measured unit prices)

Emit costs **~330 ops per `[y2][colour]` pair**; the frame is ~1,434 pairs / 100 ditto columns.

| kernel | calls/frame | ops each |
|---|---:|---:|
| `proj.column_params_m` | 160 (one per column, ever) | 11,853 |
| `proj.wall_scale_setup_m` | 28 spawn / 51 worst | **92,781** |

⚠ **Get the call COUNT right.** `wall_scale_setup_m` is in pass 2, which runs only for segs with an
unclaimed column — 28/51, NOT the 169/202 in-frustum segs. With the wrong count it reads 15.4k vs
23.6k; **a 1.5× spread for identical straight-line code is the tell that the count is wrong.**

Feature costs: V3 **+1.3M**, V4 **+2.8M** ⇒ ~27.6M projected.

⚠ **True texture mapping is +19.6M, not the +0.6M an earlier artifact claimed.** 5,612 wall rows are
on screen, each needing a texel fetch + colormap + run-merge (~3.2k), and it kills all 100 ditto
columns. Baking it away is also out: the wall bank is already 8.9M chars / 897k lines and the
assembler is ~cubic. That retraction is why the pseudo-random approach exists.

---

## 5. Lessons (in memory as R38–R43) — the ones that cost builds here

1. **The consumer's format is the specification.** V2 cost four builds to bank size, label idiom
   (`hex.set` not `add_constant` for a label base), list format (the walker reads a COUNT header,
   not the WPX sentinel) and half-list layout (asc/desc PAIR split at CENTERY). Each was assumed
   from a neighbouring subsystem instead of read off `emit_col_lines`.
2. **Narrow probes verify the path you're on; only the SUITE covers the ones you aren't.** V1's
   arity change to `wpx_wall` broke the opt-in 2S tier and survived **five "byte-exact" builds**.
   `tests/fj/test_lines_render.py` (11 tests, ~16 min) found it in one run. Run it BEFORE starting.
3. **A gated feature can break the ungated build** — an unused label is a hard assembler error, so a
   register referenced only inside `rep(flag,k)` breaks the flag-off build.
   `scratchpad/default_build_check.py` covers that in one build.
4. **A performance number from a build that is not byte-exact is not a performance number.** V1 was
   reported at +58k from a broken-ditto build; the true cost is +1.6M — 25× out.
5. **When elimination stalls, force the EFFECT.** Three builds went into "the sky branch never
   fires"; an ablate flag forcing the branch showed spawn (no sky) moving 4,011 px, proving the path
   ran and reframing it as "fires and produces garbage".
6. **Grep for the code you think you wrote.** A silent string-replacement failure meant V3's splice
   was never inserted; I committed a diagnosis blaming a clamp that was never executing.
7. **Verify a property on the side that will RUN it.** The sky bank's no-mask bound was proven with
   the ORACLE's masked base; fj's is unmasked, so the real index reached 382 against a 256-entry
   bank. Values agreed, ranges did not.
8. **A palette INDEX carries no brightness ordering you can guess at** — bit V1 (confetti) and V3
   (blown-out white faces, `WALL_BG`=4 is near-white; use `STEP_FACE_BASE`=96).

---

## 6. Where to start

1. `python -m pytest tests/fj/test_lines_render.py -q` — establish the baseline is green.
2. V3 increment A: slot storage + fill at `frame_render.fj:1254` (`claim:`), gated. **Must be
   byte-exact** — nothing reads the slots.
3. V3 increment B: the splice + the `dgchk` ditto entry. Gate against
   `render_wall_frame(..., near_steps=True)`.
4. V4 per §4 of `handoff-visual-features.md` — a per-column fragment PRE-PASS, never an overlay:
   the 0x0B column is write-once, top-down.

Probes: `scratchpad/v2_check.py` (two-viewpoint, fast), `scratchpad/default_build_check.py`
(flag-off), `scratchpad/feature_cost_audit.py` (pair counts).
