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
| **+ optimisation campaign** | **27,823,804** | **33,859,325** | **37,933,652** | **37,003,252** |

Every row is **BYTE-EXACT** against the oracle at every viewpoint listed
(`scratchpad/v4_check.py --emit`). Gates green on this tree: `tests/fj/test_lines_render.py` and
`tests/fj/test_projection_kernels.py` (16/16).

**All four features are in**: V1 pseudo-random wall grain, V2 sky, V3 step faces, V4 things.

The frame is still over the owner's 30–35M band at the two sprite-heavy viewpoints. The ranked list
of what remains is in `docs/opt-experiments.md`; the short version is that `proj.project_thing` is
still ~9M at the tree, because every one of E1M1's 250 things gets projected.

---

## 1a. ⚠ HOW TO SEE IT — the features are OPT-IN, and only the walker is wired

Every one of V1–V4 is a keyword flag on `emit_wall_renderer`, defaulting to **False**. That is why
`python scripts/walk_e1m1.py` showed the pre-V1 tier: it did not pass them.

**`scripts/walk_e1m1.py` now turns all four ON by default** (`--no-grain`, `--no-sky`, `--no-steps`,
`--no-things` to drop any of them). Sprite art comes from `--sprites assets/freedoom1.wad`; the
cut-down fixture wad has no sprite lumps at all, so if that file is missing V4 turns itself off with
a warning instead of failing to build. ⚠ **Expect ~10 minutes to assemble** — the sprite bank makes
it a ~42M-character program.

### Still NOT wired (deliberately, and each needs a decision)

| entry point | state | what it needs |
|---|---|---|
| `doomfj.build.build_wall_renderer` (the SHIPPED binary) | passes no feature flags | flags + a re-check of its R0 gate: it asserts `span < flat_max_words` (2²⁶) and the sprite bank grows the program ~5.5M characters |
| `tests/fj/test_lines_render.py` (the 11-test gate) | tests the flag-OFF tier | it is the ungated-build regression net, which is worth keeping; V1–V4 are gated by `scratchpad/v4_check.py` instead |
| a committed regression test for V1–V4 | **none exists** | the four-viewpoint gate lives in `scratchpad/v4_check.py`. Promoting it to `tests/` is the single most valuable piece of unfinished work here |

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

1. **Promote `scratchpad/v4_check.py` to a committed test.** V1–V4 have no regression net in
   `tests/`. Everything else on this list can break them silently. It is four viewpoints against the
   oracle and it already caches its binary.
2. **Wire the flags into `build_wall_renderer`** and re-check its R0 gate (`span < 2**26`). The
   sprite bank adds ~5.5M characters; if the span goes over, either raise the limit (DESIGN §1.2
   allows it, RAM-only) or ship with `things=False` until the bank shrinks.
3. **Decide `THING_BUDGET`** — EXP-8 in `docs/opt-experiments.md` has the curve. 24 → 16 is worth
   −5.4M at the tree and −1.2M at the worst point and **exactly zero** at spawn and the courtyard,
   at the price of the eight furthest things at a crowded viewpoint. One constant; the oracle
   follows it.
4. **The emit half, ~8.1M at the tree** (`docs/opt-experiments.md`, "What is left"). A fragmented
   column walks the ceiling list, the wall run-list and the floor list twice — once per region. The
   fix is a RESUMABLE walker: `qwalk` already stops mid-list holding `ptr`/`iP`/`y2r`, so a second
   entry point that skips the count header and re-emits the held pair against a new bound would let
   region 2 continue where region 1 stopped. Intricate; measure with `--reconly` either side of it.
5. **`project_thing`, still ~7M at the tree.** After EXP-7 the remaining rejects are DOOM's
   `|tx| > tz<<2`, which is a 4× FOV bound. The real screen test is `x2 < 0 or x1 >= VIEW_W`, i.e.
   roughly `|tx| <= tz + sprite half-width` — a much tighter reject, and it would skip the
   reciprocal for far more things. Derive the bound exactly and **verify it exhaustively in Python
   before building**, the way EXP-7's was.
6. **V3's step faces have had no optimisation pass at all** (+5.7M at the worst viewpoint).

### Two rules this session paid for

* **Prove a storage model in Python before spending a build on it.** `scratchpad/v3_slotmodel.py`
  is the pattern; EXP-6 skipped it and lost a cycle.
* **Run the parse-only check before every real build** — the fj sources against a two-line `main`,
  ~40 seconds, catches every unused-label and arity error. A real build is ~10 minutes.
