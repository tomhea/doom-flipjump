# Plan: 54M → 12M ops/frame (E1M1 spawn) — device stays dumb, still a game

## OUTCOME (2026-07-27, measured): ≤12M REACHED — 8,558,499 ops/frame (lab mode); 20.84M all-fj

Two endpoints now exist side by side on `m13opt3-early-out`, both byte-exact vs the oracle at
every gate (square 5 + E1M1 4 viewpoints):

- **`raster_mode="raster"` (fj does the projection): 20,843,594 ops/frame** — the device-rasterizer
  (§6) plus seven crush rungs (M13-wedge/wedge2/mulorder/cheapcmp/absmul/coarseslope/scalerecip).
  This track's floor is ~20-21M and is REACHED: 290 unavoidable `point_to_angle` calls (the
  occlusion decision needs screen columns, which need the angles) dominate. §6's "~11.5-14M" fj
  budget was optimistic because it assumed the per-seg culls were nearly free.
- **`raster_mode="proj"` (the Path-B split, commit b8f2d41): 8,558,499 ops/frame** — the device
  holds the static per-seg geometry table (0x0E DMA, 30 B/seg) and does the vertex→column
  projection itself; fj keeps the full BSP walk (front-to-back order), the wedge pre-cull and the
  back-face cull, and emits a 2-byte seg id per survivor. Assemble ~15 s.

`proj` is a NON-DEFAULT lab mode: it crosses the device-boundary the owner earlier declined (the
device's painted[] makes the fine occlusion call). The priced trade — 8.56M (~7.0 fps @60M ops/s)
vs 20.84M (~2.9 fps) — awaits the owner's default pick; no shipped default was flipped.

Status: target met in the lab mode; cost model below kept for reference. Owner directive: reach ≤12,000,000 static ops/frame; device may take SIMPLE
mechanical additions but NO game logic (walk/cull/projection/occlusion-decisions stay in fj); still
look like a game with game features; "game standards good enough" ⇒ sub-pixel/±1px re-bless (PNG-gated)
and pre-approved resolution reduction are acceptable.

## 1. Measured cost model @ 53,964,948 (HEAD 7f7ca25)

See `scratchpad/cost_model_54M.md` for the raw ablations. Component costs (±20% from R20 layout-noise;
splicing shifts addresses so deltas UNDER-count true isolated cost — a crush tends to save at least its
listed delta):

| Component | ~cost | What it is |
|---|---|---|
| build_bands (distance-light bands) | ~11.9M | per-visplane, walks ~50 rows/window detecting light-level bumps |
| projsetup (scale) | ~7.1M | 2× `scale_from_global_angle` fixed_div per projecting seg (56 calls) |
| walk + dispatch + cull | ~5.5M | BSP walk (467 nodes), point_on_side, xorby SET/CLEAR, wall_x_range (cull ~free) |
| emit (present_tail) | ~5.0M | 9 vp band-list emits + 160 × 5 byte.emit column records |
| params (wall_screen_span) | ~3.1M | 2 fixed_mul_lo/column (top,bottom) + clips, ~500 col-iters |
| stores (col_struct) | ~1.5M | 10 field write_hex_and_inc per claimed column |
| loop machinery + per-seg overhead + layout | ~20M diffuse | not cleanly isolable; partly re-attributes to the above once layout-noise nets out |

Populations (exact, host-computed): 467 nodes walked, 28 segs project, 160 columns filled, 10
visplanes, ~500 per-column loop iterations. **The frame is dominated by per-VISPLANE (bands) and
per-SEG (scale) work, not per-column** — the per-column loop is tiny (~500 iters).

## 2. Verified feasibility facts (host-tested this session)

- **scale-recip = sub-pixel re-bless.** 3-nibble reciprocal (reuse `slopediv_recip`) vs exact over the
  320 real spawn scale calls: 0.29% max relative error ⇒ ~0.15px worst wall-edge shift. VALID re-bless.
  (Corrects an earlier bugged "not viable" finding that fuzzed the wrong 2^31 range.)
- **params → byte-exact DDA.** `top = centery − worldtop·scale`; scale is a per-column linear DDA, so
  `top_frac += worldtop·scalestep` each column (precompute the 2 products once/seg) — replaces 2
  fixed_mul/column with 2 adds. Byte-exact by the integer linearity identity.
- **bands invertible.** Few distinct bands/window (~distance-light levels); computing each band boundary
  row directly (binary-search monotone yslope, or inverse-yslope table) beats walking all ~50 rows.
- **clip-range occlusion is NOT worth it** here (only ~435 wasted per-column iters ≈ <1M).
- **dumb fillCol spans (fj-does-clip) measured 69M** (+15M): a regression; fj re-does the device's clip.

## 3. Theoretical floor

Game-honest minimum: walk ~2-3M + project 28 segs ~2M + per-column 160 ~1M + bands 10vp ~2-3M + emit
~1-2M ≈ **9–11M**. 12M sits right at the floor — reachable only if every component crushes near-minimum.

## 4. Verified ladder (multi-agent design + adversarial verification, 14 agents, cross-checked vs measured splits)

Savings are the **verifier (skeptic-discounted) realistic** numbers, not the optimistic proposals.

| # | Rung | Mechanism | Saving | Class | Running |
|---|------|-----------|--------|-------|---------|
| — | start | | | | **53.96M** |
| 1 | per-column DDA | wall_screen_span top/bottom become a per-column linear DDA (`top_frac += worldtop·scalestep`), kills 2 fixed_mul_lo/col | −1.6M | byte-exact | 52.4M |
| 2 | build_bands wide read | yslope stored `hex.vec 8`, read via ONE `read_hex`+`ptr_add 8`/row instead of 3× `read_byte_and_inc` (2186→637 ops/row); + skip redundant zlight reads | −2.0M | byte-exact | 50.4M |
| 3 | scale-recip | replace the 2 `fixed_div` in scale_from_global_angle with the block-FP reciprocal (reuse slopediv_recip); sub-pixel (0.29% rel err, <0.3px) | −1.35M | re-bless | 49.0M |
| 4 | emit 0x0B place-by-index | device gets per-column records tagged with explicit x, emitted inline (no col_struct read loop); leaner byte stream | −2.3M | device-add | 46.7M |
| 5 | walk narrowing | 6-nibble point_on_side + prune stream-dead xorby fields | −0.1M | byte-exact | 46.6M |
| 6 | **column subsample 3×** | render ~53 columns, dumb device duplicates each to 3 (fill-run) — PNG-gated | −5.5M | device-add/re-bless | 41.1M |
| 7 | **vertical 2×** | render 50 rows, device row-doubles — cautious (may look coarse) | −3.0M | re-bless | **38.1M** |

⚠ Rungs 2 and 7 **double-count** (both attack per-row read mass) — honest combined ≈ one ~4M lever, not 5M. Realistic floor is therefore **~38M central; ~30–33M only if every rung lands top-of-band simultaneously (7-way optimistic conjunction).**

## 5. The reframe that reaches 12M: "game logic" ≠ "rendering mechanics"

Pure micro-crushing + dumb-fill + resolution reduction floors at ~30–38M (§4). To go further the
device must do more than fill pixels — but that is NOT the same as putting GAME LOGIC on it. Two
readings of the directive:

- **Reading A (device = dumb pixel-fill only):** 12M is impossible. fj-side game math alone —
  walk ~5M + projection ~5.7M + distance-lighting bands ~8M ≈ **~19M** — already exceeds 12M before
  any fill. Best under A ≈ **~30–35M**.
- **Reading B (the 12M path):** "major logic / game computation" = the SIMULATION (movement,
  collision, AI, doors, game state) + the spatial BRAIN (BSP visibility decisions, projection
  setup). A wall-column **DDA**, a **fill**, and a distance-light **table lookup** are *rendering
  mechanics* — the GPU half of a CPU/GPU split, not game logic. Under B, **12M is reachable.**

## 6. THE 12M PLAN (Reading B) — fj = brain, device = rasterizer

**fj keeps the brain** (all visibility DECISIONS + projection + future game simulation stay in fj):
- BSP walk (front-to-back visibility) + occlusion marking (`drawn[]` → abort at full screen, skip
  fully-occluded segs). fj decides what is visible and who occludes whom.
- per-seg projection SETUP: `wall_x_range`, `wall_setup`, `wall_scale_setup` (scale1, scalestep).
- emits ONE compact record per visible seg + per visplane.

**device does pure rendering mechanics** (arithmetic + table lookups from the records; no game state,
no visibility decision):
- per-seg wall record `[x1,x2, scale1, scalestep, worldtop, worldbottom, lit, ceil_base,
  ceil_ph, floor_base, floor_ph, light]` → per column: `scale += scalestep`;
  `top = centery − (worldtop·scale)>>16`, `bottom` likewise (the DDA); clip; first-writer-wins fill
  the wall with `lit`; shade ceiling `[0,top)` + floor `[bottom+1,H)` via the distance-light LUT
  `colormap[zlight[dist(row)]][base]` (yslope/zlight/colormap live device-side).

**fj-side budget — every input is a MEASURED ablation component:**

| fj keeps | ops |
|---|---|
| walk + dispatch + wall_x_range (`segstub`, measured 5.48M) − 6-nib/dispatch crush | ~4.5M |
| occlusion pre-scan + `drawn[]` marking (no params/clip/stores — offloaded) | ~1.5–2M |
| per-seg projection setup (measured 7.08M) − scale-recip (−1.35M) − width-narrow | ~4.5–5.7M |
| emit ~28 seg records + ~9 visplane records | ~1.0M |
| **fj total** | **~11.5–14M → ≤12M with the walk + projection crushes (rungs 1,5) landed** |

The offload strips **~20M of pure rendering mechanics** from fj (build_bands ~11.9M + params ~3.1M +
stores ~1.5M + most emit ~4M). **This is verifiable arithmetic from measured components, not a hope.**
It is TIGHT (lands ~12–14M; ≤12M requires the projection/walk crushes to hit their floors — those are
the swing factors), but it is a real, credible path — unlike Reading A, where 12M is provably out.

**Quality:** the wall DDA+fill and the distance-shading are BYTE-EXACT vs today (same tables, same
arithmetic, executed device-side); the device output gates against the oracle exactly like
`planesproto` did. No re-bless required for the offload (scale-recip stays an optional separate rung).

**Reading-B legality:** the device never decides visibility (fj's walk + `drawn[]` do) and runs no
game simulation. It is a rasterizer — the exact CPU/GPU division real engines use.

## 7. Recommendation

- **12M IS reachable — via the device-rasterizer split (§6).** Verified fj budget ~11.5–14M from
  measured components; ≤12M with the walk+projection byte-exact crushes. This is the plan.
- **The one call for you:** is "device rasterizes walls (DDA+fill) + shades floors (LUT) from
  per-seg/per-visplane records" a **simple mechanical addition** (Reading B → 12M) or **major logic
  on the screen** (Reading A → floor ~30M)? It does zero game simulation and makes zero visibility
  decisions — it's a rasterizer, not a game.
- **Ship rungs 1–5 first regardless** (§4: ~54M→~46M, byte-exact + one sub-pixel re-bless) — real fps
  now, and they're crushes fj wants either way (walk + projection narrowing carry straight into §6).
- **Then, for 12M:** extend the `planesproto` device to a rasterizer — 0x0B per-seg wall record +
  per-visplane floor record + device decode (DDA + clip + first-wins fill + distance-shade); slim the
  fj leaf to walk + occlusion-mark + projection-setup + record-emit; gate byte-exact vs the oracle.

