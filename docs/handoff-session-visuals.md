# Session handoff — all four visual features shipped, and an optimisation campaign on top

**Branch:** `m13opt3-early-out`, pushed.

---

## 1. Where the frame is

| build | spawn | courtyard | tree (2432,1344) | worst (-309,-44) |
|---|---:|---:|---:|---:|
| session start (pre-V1) | 21,736,934 | — | — | 26,557,125 |
| V1 grain + V2 sky | 23,536,484 | 20,134,978 | — | 26,405,793 |
| + V3 step faces | 26,545,502 | 27,604,046 | — | 32,137,393 |
| + V4 things | 28,104,383 | 36,010,624 | 45,252,666 | 39,448,264 |
| + optimisation campaign (EXP-1..5) | 27,823,804 | 33,859,325 | 37,933,652 | 37,003,252 |
| + EXP-7 far-thing reject | 27,631,269 | 33,820,592 | 37,224,868 | 36,433,309 |
| + EXP-8 `THING_BUDGET`=16 | 27,631,269 | 33,820,592 | 31,826,978 | 35,216,185 |
| + V4 selection policy: monsters never dropped (budgets 16/64) | 27,772,447 | 33,671,882 | 34,541,408 | 39,156,918 |
| **+ NO COUNT LIMIT — distance decides (SHIPPED)** | **27,772,549** | **33,672,272** | **36,649,307** | **39,158,568** |

Every row is **BYTE-EXACT** against the oracle at every viewpoint listed
(`scratchpad/v4_check.py --emit`). Gates green on this tree: `tests/fj/test_lines_render.py` and
`tests/fj/test_projection_kernels.py` (16/16).

**All four features are in**: V1 pseudo-random wall grain, V2 sky, V3 step faces, V4 things.

The last row is the SHIPPED tier, **BYTE-EXACT at all four viewpoints**, and it is deliberately
ABOVE the old 30–35M band: it draws 28 of 28 monsters at the worst viewpoint where the budget tier
drew 17.

⚠ **Retiring the count limit costs +2.1M at the tree and ~nothing elsewhere, for an IDENTICAL
picture.** That is not a regression, it is the price of the guarantee: with a count, things past the
cap were skipped by a counter test; without one, every thing pays its (early, ~20k) distance reject
instead. At the tree that is ~100 extra things. The trade buys correctness on any map denser than
E1M1 — arrival order can never drop a monster again — and the min-size reject keeps the picture
identical. Lower `THING_BUDGET` alone if a future map needs the ops back; it thins scenery and never
touches monsters. See §5 for the end-of-phase state and why the 15M target is not met.

---

## 1a. ⚠ HOW TO SEE IT — the features are OPT-IN, and only the walker is wired

Every one of V1–V4 is a keyword flag on `emit_wall_renderer`, defaulting to **False**. That is why
`python scripts/walk_e1m1.py` showed the pre-V1 tier: it did not pass them.

**`scripts/walk_e1m1.py` now turns all four ON by default** (`--no-grain`, `--no-sky`, `--no-steps`,
`--no-things` to drop any of them). Sprite art comes from `--sprites assets/freedoom1.wad`; the
cut-down fixture wad has no sprite lumps at all, so if that file is missing V4 turns itself off with
a warning instead of failing to build. ⚠ **Expect ~10 minutes to assemble** — the sprite bank makes
it a ~42M-character program.

### Wiring status (all three items below are now DONE)

| entry point | state |
|---|---|
| `doomfj.build.build_wall_renderer` (the SHIPPED binary) | **WIRED.** Its defaults are now the shipping tier — `raster_mode="lines"`, `wall_mode="WPX"`, `floor_mode="FT1"`, `plane_near=True` — with all four features ON, and every one is a keyword pass-through so the older tiers stay reachable. V4's art comes from a new `sprite_wad` argument (default `assets/freedoom1.wad`), and `_resolve_sprite_wad` **raises** rather than silently shipping `things=True` with an empty bank. R0 gate re-measured below. |
| `tests/fj/test_lines_render.py` (the 11-test gate) | tests the flag-OFF tier, deliberately: it is the ungated-build regression net, and an unused label in a gated feature is still a hard assembler error there |
| a committed regression test for V1–V4 | **`tests/fj/test_visual_features.py`** — one binary, four viewpoints, byte-exact against the oracle. ⚠ ~10 min to assemble, so run it explicitly |

**R0 re-measured, and the number went the other way.** The worry was that the sprite bank (~5.5M
characters) would push the span past 2²⁶. It did not — the shipped span **FELL, 24.7M → 12.89M
words**, headroom 5.21× under the raised limit and comfortably under 2²⁴ as well:

```
{"tier": "lines/WPX/FT1+plane_near", "span_words": 12887798, "storage_mode": "flat",
 "headroom": 5.207, "fjm_bytes": 3747340, "assemble_seconds": 190.8,
 "features": {"wall_noise": true, "sky": true, "steps": true, "things": true}}
```

The reason is the tier, not the features: the lines raster emits a 0x0B column stream instead of a
framebuffer, which deletes **both** 16K-pixel pass-2 unrolls (the wall trampoline and the M13c3
plane pass), and those were the bulk of the old span. The sprite bank is small against what went
away. So the shipped binary got a newer picture *and* half the memory. `flat_max_words=2**26` is
now far more headroom than this tier needs — worth revisiting only if something re-adds an unroll.

---

## 2. What V4 looks like

`render_wall_frame(..., things=True, sprite_wad=...)` and
`emit_wall_renderer(..., things=True, sprite_wad=...)`.

⚠ The test fixture wad has **no sprite lumps**. Art comes from `assets/freedoom1.wad` through a
separate `sprite_wad` argument; geometry, flats and colormap stay on the fixture so nothing else moves.

The design, and why each piece is shaped that way:

* **Fragments are recorded during the walk**, when it reaches the thing's own subsector, and only
  into columns no wall has claimed. Front-to-back order does two jobs: it makes "the first writer is
  the nearest" true, and it *is* the occlusion test. That is what lets a write-once, forward-only
  column protocol show sprites at all — DOOM draws them last, back-to-front, and this cannot.
* **Sprite columns bake per (sprite, downscaled column, height BUCKET)**, 32 buckets. Exact heights
  would be ~17M characters against a program already at 42M and a ~cubic assembler.
* **Texels are RAW**, colormapped at emit through `cm.emit` (V1's grain mechanism), so one bank
  serves all 16 light levels instead of being multiplied by them.
* **Interior transparent gaps take the nearest opaque texel above.** Forced, not chosen: the 0x0B
  cursor never moves back, so a transparent run mid-fragment would need background already passed.
* **One overlay per column, sprite wins** — a column with a fragment draws no step face.
* The emit composes a fragmented column as `region(0, sy1)` + the sprite runs + `region(sy2+1, H)`,
  where `region(lo, hi)` is the ceiling `half_walk`, a **windowed** `wpx_wall`, and the floor
  `half_walk`. A step face lives inside ONE region; a billboard straddles all three.

---

## 3. The bugs that cost the most, and their general form

Seven real bugs between the emit splice and a byte-exact frame. **Five were the same class: a value
used at the wrong WIDTH or the wrong SCALE.**

| bug | general form |
|---|---|
| `projection*0x10000` | a constant that already carried its shift |
| `hex.add 8, dst, <hex.vec 2>` (x3) | **an n-nibble op reads n nibbles of its source** — a narrow register drags its neighbours in as high nibbles |
| block index shifted twice, and once by the wrong amount | a stride applied on both sides of a store |
| `hex.add w/4, ptr, base` on a SLOT offset | a slot offset must be scaled by `dw` to become an address — `ptr_index` does it, a raw add does not |
| missing `byte.emit y2r` | a pair is TWO bytes; emitting one desynchronises the whole frame |
| a thing-carrying BSP leaf pruned | **any pruning a feature does not know about is a feature that silently does not run** — and there were TWO prunes, one compile-time and one runtime, so fixing only the first changed nothing |

**The tool that found them was not another build.** `scratchpad/v4_check.py` caches the assembled
`.fjm` keyed on a hash of the sources, and `--trace` decodes the 0x0B stream and names the first
structural anomaly (a row past VIEW_H, a non-monotone pair). Diagnosis went from ten minutes per
hypothesis to seconds. `scratchpad/v4_col.py` dumps one column's emitted pairs beside the oracle's
runs, against the cached binary.

---

## 4. Probes

| script | what it does |
|---|---|
| `scratchpad/v4_check.py --emit` | the four-viewpoint V4 gate; caches the binary |
| `... --trace` | + the 0x0B stream anomaly report |
| `... --nothings` | build without things: the V3 baseline at every viewpoint |
| `... --reconly` | keep the record half, disable the emit: prices record alone, byte-exact |
| `... --thingtwice` | double `project_thing` into dead registers: prices all projections |
| `scratchpad/v4_col.py <vp> <col>...` | one column's fj pairs vs the oracle's runs |
| `scratchpad/v3_check.py` | the V3 gate |
| `scratchpad/v3_slotmodel.py` | proves the V3 storage model with no build at all |
| `scratchpad/v4_oracle.py` | renders the things oracle + its pair/ditto deltas |

**Run the parse-only check before every real build** — assemble the fj sources against a two-line
`main`. It costs ~40 seconds and catches every unused-label and arity error; a real build is ~10 min.

---

## 5. STATE AT THE END OF THIS SESSION (2026-08-01) — read this first

### ⭐ THE PLAYABLE DEFAULT IS NOW E2M8, NOT E1M1

`scripts/walk_e1m1.py` defaults to the **arena** (`assets/freedoom1.wad`, E2M8, 542 segs).
Measured on the real walker: **24.5M ops, 178 ms, 5.6 fps** — against E1M1's ~2.9 fps. Same
renderer, same 160x100, all four visual features, every monster drawn, byte-exact at five
viewpoints. Nothing is given up but the specific level.

**E1M1 remains the ladder's canonical map** and every golden, gate and test still targets it:

    python scripts/walk_e1m1.py --wad tests/fixtures/freedoom_e1m1.wad --map E1M1

Why: the frame's cost is MAP cost. A 4-seg room costs 4.69M (EXP-12's floor measurement), so
everything above that is the level. E1M1 is one of the largest, most open maps in the game — the
worst possible case for a renderer whose cost is per-seg.

**Sprite selection is now DISTANCE-ONLY, by owner decision.** There is no count limit: both
`THING_BUDGET` and `MONSTER_BUDGET` sit at 255 (the widest the 2-nibble counters hold) and cannot
bind — E1M1's heaviest viewpoint projects 52 things. What a frame draws is decided entirely by the
per-thing **min-size reject**: scenery below `MIN_SPRITE_H` = 3 screen px is not drawn, a monster
keeps the 1 px bound and is never dropped. Retiring the counts changed **zero pixels at all four
gate viewpoints** — the size rule already filtered everything a count could have.

The counters and their compares are deliberately KEPT (≈one test per thing): they are the backstop
against a pathological map, and if a limit is ever wanted again, lowering `THING_BUDGET` alone thins
scenery without ever touching monsters.

**Frame cost, shipped:** 27.8M spawn / 33.7M courtyard / 34.5M tree / **39.2M worst** (~2.9 fps at
the native engine's throughput). That is ABOVE the old 30–35M band, and knowingly so: the frame now
draws 28 of 28 monsters at the worst viewpoint where it used to draw 17.

### ⚠ The 15M target is NOT met — and EXP-11 shows it is ARITHMETIC, not a missing lever

Measured components only: V4 things 7.02M + `wall_scale_setup_m` 4.06M + walk skeleton ~3.9M
**= ~15.0M with nothing drawn**. Add the wedge cull, `point_to_angle` and V3 step faces and the
floor is **~24.8M before a pixel is emitted**, with EXP-10's ~14.4M residue still on top. So no
lever inside the residue can reach 15M while all three owner constraints hold (160x100, all
features, no thing limit). 39.2M -> ~30M looks reachable; 15M needs a constraint to move.

### And the reason resolution cannot do it either

The owner asked for <15M/frame. **Cost is nearly resolution-INDEPENDENT**: building at 96×60 (36% of
the pixels) bought only 21% of the ops, and the fit puts ~27.4M of the worst frame outside pixel
count altogether. A 1×1 frame would still cost ~27M. Every cheap lever is now measured and dead
(`docs/opt-experiments.md` EXP-9): ditto columns, the WPX run cap, V1 grain, the `fixed_div` swap,
a per-linedef setup memo (only ~10% of setup-paying segs share a linedef), and the budget knobs
(−2.57M worst but +855k courtyard and ~750 px of floor damage — not shipped).

⚠ **EXP-10 RETRACTS the lever EXP-9 named.** "Halve the per-seg setup, ~190k x ~150 segs, upside
~14M" was built on a STALE probe (`bboxcull_probe2.py`, written for the pre-optimisation raster
tier). Measured properly by doubling the kernel: `wall_scale_setup_m` costs **4.06M at the worst
viewpoint — 10% of the frame, ~28k per seg.** Halving it is worth ~2M. **Do not start there.**

What is actually left is a **~14.4M unaccounted residue** (see EXP-10's accounting table): not the
scale setup, not resolution-dependent, and not yet bisected. Candidates: `wall_setup` proper, the
occlusion pre-scan, the per-seg column-store loop, and `plane_near` attribution (~5M by inference
from the PNEAR knob). **Next session starts by bisecting that**, with the existing
`scaletwice`/`noprescan`/`projtwice` ablates and `scratchpad/bench.py`.

Shape fact that constrains every idea: ~150 segs pay setup and their mean screen width is 3.9-4.7
columns, i.e. roughly ONE net claimed column each on a 160-column frame. A win has to cut the NUMBER
of setup-paying segs, not the price of one.

### Also worth knowing before touching anything

* **A latent defect at TEXTURE_DOWNSCALE ≠ 2.** At 96×60 spawn is byte-exact but the other three
  viewpoints DIFFER, so something in the lines renderer does not follow `cfg` at odd downscales.
  Harmless today (the shipped tier is 160×100, downscale 2); a trap for any future resolution work.
* **Two binding traps cost two probes this session.** `wall_renderer` does
  `from doomfj.reference_model import THING_BUDGET, ...` (bound at IMPORT), and
  `wpx_strip(..., cap=WPX_RUN_CAP)` is a KEYWORD DEFAULT (bound at DEF time). Patching the module
  global moves neither. `scratchpad/bench.py` documents both and patches every binding site.
* `tests/fj/test_floor_planes_fj.py` still carries two permanently-skipped tests for the legacy
  framebuffer flat kernel — the tier is slated for deletion at M13p8; tier and tests should go
  together.

---

## 5b. ⚠ READ BEFORE M14 — what MOVING things break, and the trap that will bite first

M14 is input + simulation, which means enemies that move. The renderer is better placed for that
than it looks, but three things are compile-time and one of them fails SILENTLY.

**Already runtime, needs no work:** `proj.project_thing` and `frame.thing_record_body` read the
thing's position out of REGISTERS (`sp_x`/`sp_y`/`sp_z`). Nothing in the projection, the height
bucket, the column DDA or the run-list emit knows where the thing is. Move it and the same kernel
projects it correctly. That is the expensive, intricate half and it is already position-agnostic.

**Compile-time, must change:**

1. **Which BSP leaf owns the thing.** `things_by_ss` is built at emit by `point_in_subsector`, and
   the per-thing call sites are emitted INSIDE that leaf's code (`wall_renderer.py`, the
   `subsector_action` thing loop). A monster that walks into the next room is still recorded by the
   old room's leaf — wrong occlusion order, and invisible whenever that leaf is not visited.
2. **The per-thing constants** — x, y, z, sprite-bank base, light class, the min-size depth bound,
   the monster flag — baked as one xor-involution block per (subsector, thing).
3. **The art: ONE still frame.** `sprite_art` tries `A0/A1/A2A8/A1D1`, all spellings of frame A,
   rotation 0. No walk cycle, no 8-way facing. A moving monster would slide, facing one way.

So the change is to the **list**, not the renderer: a runtime thing table plus either a runtime
`point_in_subsector` per moved thing or DOOM's per-leaf thing list (`P_UnsetThingPosition` /
`P_SetThingPosition`). Sizing is friendly — mean ~1.9 things per occupied leaf, max 13 — so the
per-leaf loop is short. A BSP descent is cheap against a ~47k projection.

**⚠ THE TRAP: the prune.** A leaf with no one-sided seg is dropped TWICE — `_lines_prune` at compile
time and `_lines_plane_gate`'s `tsstop` node gate at runtime — and both had to be taught that a
thing-carrying leaf is live. That worked because with STATIC things the emitter knows which leaves
carry things. **With moving things it does not.** A monster can walk into a leaf pruned as empty and
vanish with no error. Widen the predicate to "any leaf a thing could ever enter", or move the prune
to runtime — and settle it BEFORE writing the runtime list, not after. This is the exact bug class
that already cost this repo two builds.

**One design note worth keeping:** a thing lives in exactly one leaf and that is not a limitation.
Leaf ownership is a *when*, not a *where* — it fixes the moment the thing is recorded (its slot in
the front-to-back order); the sprite's extent is in SCREEN COLUMNS, which have nothing to do with
leaves. Recording it in a second leaf would be actively wrong: another ~47k projection whose output
the write-once columns reject. The one real failure mode is a thing whose centre is in leaf A but
whose body reaches into a nearer leaf B: it takes A's depth slot, so a wall in B that already
claimed those columns wins and the sprite is UNDER-drawn — clipped away, never drawn over a wall it
belongs behind. Conservative, which is the right direction for a write-once protocol.

**Known gaps in sprite occlusion**, for whoever touches this next: occlusion is per column and
all-or-nothing, so a sprite cannot be cut off at a wall's top edge (forced by the forward-only 0x0B
cursor); and step faces do not occlude sprites at all — "one overlay per column, sprite wins" — so a
monster behind a ledge draws in front of it. The second is a policy choice in the emit, not a
protocol limit, and is fixable: both are per-column records with known row ranges.

---

## 5a. What is left, in the order I would do it

Items 1–3 of the previous list are **done**: the V1–V4 regression test is committed
(`tests/fj/test_visual_features.py`), the flags are wired into `build_wall_renderer` with its R0
gate re-measured, and `THING_BUDGET` is **16**.

1. **The emit half, ~8.1M at the tree** (`docs/opt-experiments.md`, "What is left"). A fragmented
   column walks the ceiling list, the wall run-list and the floor list twice — once per region. The
   fix is a RESUMABLE walker: `qwalk` already stops mid-list holding `ptr`/`iP`/`y2r`, so a second
   entry point that skips the count header and re-emits the held pair against a new bound would let
   region 2 continue where region 1 stopped. Intricate; measure with `--reconly` either side of it.
2. **V3's step faces have had no optimisation pass at all** (+5.7M at the worst viewpoint). This is
   now the biggest single item at the **only frame still at the band's edge** (35.22M), which is why
   it moves up the list: `THING_BUDGET` took 5.4M off the tree but only 1.2M off the worst point.
3. **`project_thing`.** After EXP-7 the remaining rejects are DOOM's `|tx| > tz<<2`, which is a 4×
   FOV bound. The real screen test is `x2 < 0 or x1 >= VIEW_W`, i.e. roughly
   `|tx| <= tz + sprite half-width` — a much tighter reject, and it would skip the reciprocal for
   far more things. Derive the bound exactly and **verify it exhaustively in Python before
   building**, the way EXP-7's was. ⚠ Re-price it before writing any fj: a failed projection does
   not increment `n_thing`, but the budget still ends the walk sooner at 16 than at 24, so some of
   the calls this lever would have skipped are already gone.

### Two rules this session paid for

* **Prove a storage model in Python before spending a build on it.** `scratchpad/v3_slotmodel.py`
  is the pattern; EXP-6 skipped it and lost a cycle.
* **Run the parse-only check before every real build** — the fj sources against a two-line `main`,
  ~40 seconds, catches every unused-label and arity error. A real build is ~10 minutes.
