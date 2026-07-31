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

## 5. Where to start

1. `docs/opt-experiments.md`, section "What is left, ranked by measured upside".
2. The two gates above.
3. If touching per-column storage, prove the model in Python first (`v3_slotmodel.py` is the
   pattern) — EXP-6 lost a build cycle by not doing that.
