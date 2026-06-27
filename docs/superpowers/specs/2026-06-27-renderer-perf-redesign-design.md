# Renderer performance redesign — toward ~40-50M ops/frame

**Status:** design (approved architecture, pre-implementation)
**Date:** 2026-06-27
**Owner goal:** **~40-50M fj ops/frame** (geometry ~20-30M), down from the current 645M. Stretch: 12M.
**Branch base:** `m13opt1-drawspan-perpixel` (off `m13d2c-textured-wirein`).

## 1. Goal & the currency

The textured E1M1 renderer is byte-exact but slow. After this session's two [exact] wins it is **645,575,343
ops/frame (~0.43 fps at 280M fj/s)**. The owner target is **~40-50M (~5-7 fps)**, geometry alone ~20-30M.

The design currency is the **`fixed_mul`** (8.4): ~10,000 fj ops each at @≈25. 40M ÷ 10k ≈ **~4,000
`fixed_mul`-equivalents per frame**; 12M ≈ ~1,200. Everything else — table lookups, adds, compile-time-address
writes (`hex.xor_by`/`mov 2` into a `hex.vec 2` cell), the `drawn[]` checks — is "cheap" by comparison. The
design problem is **spending the multiplies per-band and per-visible-seg, never per-pixel.**

## 2. Measured cost model (E1M1 spawn, the 645M frame)

```
645M  =  FLOOR 300M (46%)   +   GEOMETRY walk 295M (46%)   +   wall RASTER 50M (8%)
```
- **GEOMETRY (pass-1) = 295M** — the baked BSP-as-code walk (681 nodes) + `seg_pass1_leaf` over **all 575
  one-sided segs**: `wall_x_range` (cull) on every seg, the full projection (`wall_setup`/`wall_scale_setup`/
  `wall_offset`) on every *visible* seg, and the per-column loop (`column_render_params` = a `texture_u` divide
  + an `iscale` `fixed_div`, then 14 `store_col_field`s). ≈ 30,000 `fixed_mul`-equiv — **25× over the 12M
  budget by itself.**
- **wall RASTER (pass-2) = 50M** — the 16K-pixel unrolled trampoline + `leaf_body_w` on the ~5,619 wall pixels.
  Compile-time addresses already (cheap writes). Texture *sampling* was never the cost.
- **FLOOR = 300M** — per-span perspective SETUP (6 `fixed_mul`s × 1,357 spans ≈ 200M) + per-pixel (~43M) +
  walk (23M, solved by opt2).

**Key facts that shape the design** (all measured this session):
- A `fixed_mul` ≈ 10k ops; a table lookup is cheap and **independent of table size** (so pre-bake freely).
- Runtime pointer write (`write_hex`) ≈ 420 ops; **compile-time-address write (`xor_by`/`mov 2`) ≈ a few @** —
  so rasterizers should write to *unrolled compile-time addresses*.
- The geometry processes **all 575 segs**; DOOM processes only the ~30-40 *visible* ones (it stops when the
  screen fills). **This is the single biggest waste, and removing it is byte-exact.**

## 3. Architecture: three phases, with the trajectory

| Phase | Change | re-bless? | frame after |
|---|---|---|---|
| **1. Early-out walk** | stop processing segs once the screen is full (+ per-seg occlusion skip) | **NO — byte-exact, preserves golden `db5d3da8`** | 645M → **~370M** (geometry 295M → ~25M) |
| **2. Bucketed floor** | distance-bucketed pre-baked patterns; compile-time-address raster | yes (modified oracle, new golden) | ~370M → **~85M** (floor 300M → ~9M) |
| **3. Vertical-pattern walls** | vertical-only procedural wall texture (no `texcol`) + bucketed column scale (no per-column `fixed_div`) | yes (modified oracle, new golden) | ~85M → **~40-50M** (raster 50M → ~10M + per-column divides gone) |

The phases are independent and individually shippable; each is gated by byte-exactness (Phase 1 vs the existing
oracle; Phases 2-3 vs the modified oracle) + a measured ops/frame drop. Implement and verify **in order** —
Phase 1 first because it is the biggest single win, the cleanest (no oracle change), and a prerequisite for
reasoning about the others (it defines "the visible segs").

## 4. Phase 1 — byte-exact early-out (geometry 295M → ~25M)

**Principle:** a seg whose columns are all already claimed (or off-screen) contributes **zero pixels** (the
front-to-back `drawn[]` clip means the nearest wall already painted them, and sets the floor/ceiling plane
params too). Skipping its projection changes **no output** — same framebuffer, same golden.

**Steps:**
1. **Drawn-columns counter + `full` flag.** Add globals `n_drawn` (init 0) and `full` (init 0). In
   `mark_drawn` (frame_render.fj), after claiming a previously-unclaimed column, `inc n_drawn`; when
   `n_drawn == VIEW_W`, set `full = 1`. (Counter increments only on a *new* claim — `mark_drawn` is already
   guarded by `skip_if_drawn` at the call site, so each column counts once.)
2. **Per-seg early-out.** At the top of `seg_pass1_leaf_body_mtlwp`: `hex.if0 1, full, work; stl.fret seg_ret`
   — if `full`, return immediately (skip `wall_x_range` + projection + loop). Post-fill segs cost one
   flag-check + an fcall/fret. (The xorby SET/CLEAR around the fcall still run — cheap; a later refinement can
   guard those in the baked subsector_action too.)
3. **Per-seg occlusion skip (catches occluders before the screen is full).** After `wall_x_range` yields
   `[x1,x2]`, scan `drawn[x1..x2]`; if **all** set, fret (skip the projection + per-column loop). The scan is
   ~(x2-x1) cheap `drawn[]` reads vs a ~50k projection. (Today the per-column loop already `skip_if_drawn`s
   each column, but the per-seg projection ran first — this moves the test ahead of it.)
4. **Reset** `n_drawn`/`full` to 0 at frame start (the renderer re-runs per frame from stdin; the
   `rep(VIEW_W) ... ,0` array inits already zero `drawn[]`, so add the two scalar resets in `pass1`).

**Verification:** byte-exact vs the **current** oracle `render_wall_frame()` — the E1M1 golden `db5d3da8` and
all 4 viewpoints must pass **unchanged** (this is the proof the skip is invisible). Measure ops/frame; expect
~370M. Fast gate: the square + the E1M1 capstone (existing tests, no changes to expected output).

**Stretch (later):** node-level early-out — skip a BSP subtree when `full`. The baked `_bsp_as_code` walk would
check `full` at each node and jump past its subtree. Cuts the ~14M node-traversal floor too (geometry → ~10M).

**Risk:** the savings depend on the screen filling early (front-to-back order guarantees it for closed rooms;
E1M1 spawn is a room). Open viewpoints (long sightlines) fill slower → smaller savings, but never *negative*
(the flag-check is cheap and the output is identical). Measure across the 4 test viewpoints.

## 5. Phase 2 — distance-bucketed floor (300M → ~9M; modified oracle)

**Principle:** a floor screen-row is at constant distance, and distance is a function of the row. Quantize
distance into ~16-32 **bands** (the band index is the **top nibble** of the distance — a shift+mask, ~free).
The expensive perspective runs **once per band per frame (~32×), not once per span (~1357×).**

**Steps:**
1. **Modify the oracle** (`reference_model`): add a bucketed floor mode. Per frame, for each band b: seed the
   perspective once and walk a continuous DDA across the 160 columns, sampling the floor texture into
   `pattern[b][x]` (a 160-wide row of palette indices). Per floor pixel `(y,x)`: `b = band(distance(y))`,
   texel = `pattern[b][x]`, distance-lit. Render a PNG; confirm it reads as a receding repetitive floor (it
   "snaps" between bands — acceptable). **Bless a new floor golden.**
   - Band count is a config knob (start ~32; tune fidelity vs the ~32 × 6 `fixed_mul`s pre-compute cost).
2. **fj per-frame pre-compute** (a new leaf, R_ClearPlanes-style): for each band, the 6-`fixed_mul` seed + the
   160-step DDA writing `pattern[b][x]` into a memory buffer (`hex.vec 2` per entry). ≈ 32 bands → ~200
   `fixed_mul`s + ~5k cheap steps ≈ ~3-4M.
3. **fj floor raster:** the column scan is **unrolled** (compile-time `x`, like opt2's `plane_col`); per floor
   pixel: `b` (from the row, hoisted), `pattern[b][x]` (a `read_table` by `b` at compile-time column x), the
   colormap, and a **compile-time-address `xor_by` write** into the `hex.vec 2` framebuffer cell. No runtime
   pointer, no per-span perspective, no per-pixel `fixed_mul`.
4. **Verification:** byte-exact vs the modified oracle (square + E1M1, new goldens). Measure.

**Open question:** within a band all rows share `pattern[b]` (identical texels) → horizontal banding. ~32
bands over ~50 floor rows ≈ 1-2 rows/band → mild. If too visible, raise the band count (cost is linear in
bands but still tiny). The oracle PNG decides.

## 6. Phase 3 — vertical-pattern walls (raster 50M → ~10M + kills per-column divides; modified oracle)

**Principle:** make wall textures a function of `texrow` **only** (vertical bands / brick courses / gradient +
a cheap noise XOR for "semi-random"). A vertical-only pattern needs no `texcol` → **delete `texture_u`** (a
per-column divide + the horizontal angle math). Bucket the wall's `rw_distance` (top nibble) → the column
`scale`/`[top,bottom]` from a small per-band table → **delete the per-column `iscale` `fixed_div`.** These two
deletions also shrink the *Phase-1 visible-seg* cost (the per-column divides were part of it).

**Steps:**
1. **Modify the oracle:** wall texel = `pattern(texrow, seg_seed)` (a tiny lookup / `xor`/`add`, seg_seed gives
   per-wall variety); bucket the column scale. PNG check (walls still read as walls — DOOM walls are mostly
   vertical structure). **Bless a new golden.**
2. **fj:** `column_render_params` loses `texture_u` (no `texcol`) and the `iscale` `fixed_div` (scale from a
   band table); `leaf_body_w` samples the vertical pattern from the (8.8) `frac` + the seg_seed. Per-pixel:
   `frac += step` → pattern → colormap → compile-time `xor_by`.
3. **Verification:** byte-exact vs the modified oracle; measure → ~40-50M.

## 7. The "modified oracle" methodology (Phases 2-3)

The project invariant is **fj byte-exact to the host oracle** (the goldens are the recorded hash of the
oracle's output). For Phases 2-3 we *change the oracle* (cheaper algorithm) and re-bless: change the oracle →
verify it looks acceptable (PNG) → bless the new golden → mirror in fj → assert fj == modified oracle. The
safety net (fj == oracle, bit-for-bit) is preserved at every step; only the recorded golden hash and the exact
pixels move (sub-perceptibly). Phase 1 changes **neither** (it's a pure speed win — same pixels).

## 8. Verification & gates (all phases)

- **Fast macro gates:** `scratchpad/repro.py` (real (-416,256) per-column config → the macros → byte-exact,
  ~1min — the gate that caught opt1's bug), the kernel tests (~18s), `test_plane_span_pass.py` (~30s).
- **Renderer gates:** square (~2min) then E1M1 capstone (~6-7min, all 4 viewpoints + golden + span < 2²⁶).
- **Measurement:** `term.op_counter` on the spawn frame ⇒ ops/frame ⇒ fps (280M / ops). Per-component splits
  via `scratchpad/split_floor.py` / `geom_only.py` (stub a pass, diff op_counter).
- ⚠ background `| tail`/`| grep` LOSES output — redirect to a file. E1M1 assemble is ~6-9min (the unroll grew
  it); run renderer variants **one at a time** (parallel assembles contend → timeouts).
- Each phase = a cr-tdd-ladder rung: branch → byte-exact (FAIL→PASS or golden) + ops-drop evidence → CR-ist →
  merge → tag.

## 9. Risks & open questions

- **R1 (Phase 1 leverage):** the 295M sub-split (x_range-on-all-575 vs visible-seg projection vs per-column) is
  *unmeasured*; the early-out's exact payoff is a hypothesis (~25M). If the ~40 *visible* segs' projection is
  itself heavy, Phase 1 lands higher than ~370M and Phase 3's per-column-divide removal becomes load-bearing.
  **Mitigation:** Phase 1 is byte-exact and cheap to try — implement it and measure; it can only help.
- **R2 (band fidelity):** floor/wall banding visible? Tune band count (cheap). PNG-gated.
- **R3 (program size / @):** Phase 2's unrolled floor raster + the pattern buffers grow the program (→ @, →
  assemble time, → span). Watch the R4 span gate (< 2²⁶) and assemble time; the pattern buffers are small.
- **R4 (12M stretch):** 40-50M is the committed goal; 12M additionally needs node-level early-out + the
  geometry per-column fully gone + possibly more bands — revisit after Phase 3's measured numbers.

## 10. Out of scope

Merging/simplifying *level* geometry (fewer walls in the world) — that WOULD change visuals and is explicitly
not proposed. "Fewer segments" here always means "fewer *invisible* segments computed." Also out: M14 input/sim
(this is the perf prerequisite before it).
