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
| **+ EXP-8 `THING_BUDGET`=16 (SHIPPED)** | **27,631,269** | **33,820,592** | **31,826,978** | **35,216,185** |

Every row is **BYTE-EXACT** against the oracle at every viewpoint listed
(`scratchpad/v4_check.py --emit`). Gates green on this tree: `tests/fj/test_lines_render.py` and
`tests/fj/test_projection_kernels.py` (16/16).

**All four features are in**: V1 pseudo-random wall grain, V2 sky, V3 step faces, V4 things.

**Every viewpoint is now inside the owner's 30–35M band** — the worst one only just (35.22M), so it
is the frame still worth spending on. The budget is the owner's call, taken 2026-08-01: 16 costs 41
pixels at the tree and 19 at the worst point, out of 16,000, and nothing at all at spawn or the
courtyard where it never binds (EXP-8 in `docs/opt-experiments.md` has the rendered comparison).
The ranked list of what remains is in the same file; the short version is that `proj.project_thing`
is still the largest kernel, because every one of E1M1's 250 things gets projected.

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

## 5. What is left, in the order I would do it

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
