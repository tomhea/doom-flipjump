# M13p — Procedural-Floor/Wall Perf Ladder Implementation Plan (462.7M → ≤12M ops/frame, HARD)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking. Read the memory `fj-lessons` file BEFORE writing any fj code.

**Goal (owner-set, HARD):** Ladder the renderer from the measured **462,742,550 ops/frame (0.605 fps
@280M)** down to **≤ 12,000,000 ops/frame** — the static E1M1 spawn frame as reported by
`scripts/measure_frame.py`, under the same measurement convention as the 462.7M baseline (fresh run,
known-zero framebuffer). Procedural screen-space color (floors first, then walls) buys the first ~10×;
the last ~3× is a **hard per-stage budget ledger** (below) that forces three structural redesigns: the
unified composite raster (pC), the until-full walk/geometry (pG), and — if any ledger line overshoots —
the named fidelity valves (pV). Still a ladder: **each rung measured, non-empty, shippable.**

**Architecture:** The pipeline stays (BSP walk → pass-1 geometry → raster). Each rung swaps ONE kernel
or bakes ONE table cheaper, behind an emitter *mode flag* mirrored in the oracle, so the textured path
stays in-tree and testable the whole time. De-risk order per rung: oracle change → PNG → owner look-OK
→ fj mirror → byte-exact gate → **measure ops/frame** → commit. At pC the two raster passes (wall
pass-2 + plane pass) merge into ONE unrolled composite pass — the only structural rewrite, and it is
itself laddered (prototype → floors-only → unified).

**Tech stack:** Python emitter (`src/doomfj/wall_renderer.py`) + fj macros (`src/fj/plane_render.fj`,
`src/fj/frame_render.fj`), flipjump 1.5.1 assembler/runner, pytest gates, `term.op_counter` measurement.

## Global constraints (binding, from the owner / prior sessions)

- **Branch:** all work stacks on `m13opt3-early-out` (@ `8d175d2`). **Do NOT merge to main** until the
  endgame rung (M13p8) — owner policy 2026-07-03.
- **Owner direction (verbatim intent):** can sacrifice looks; wants easy-to-implement patches that each
  give a non-empty improvement. NOT one big-bang rewrite.
- **Every pixel-changing rung ([re-bless]) is PNG-gated by the owner before fj work starts.** Byte-exact
  rungs ([exact]) gate on the existing goldens.
- **Table Design Law:** tables are 16ˣ sized, indexed by top nibbles via `.lookup` (no shift, no clamp,
  no `read_table` arithmetic); **≤ 16³ (4096) entries without owner permission**.
- **Goldens now:** square textured `00de1aaa…` (never moved), E1M1 textured `3f0133d9…`,
  square flat `aeeb82a8…`, E1M1 flat `6d5baf9e…` (all asserted in `tests/host/test_floor_planes.py`).
- **Build gates:** E1M1 assemble ≈ 605s > the Bash tool's 600s cap → run heavy builds via
  `run_in_background` with NO shell `timeout` (they notify on completion).
- `--werror` rejects an UNUSED macro param — do not fold params away without weighing the caller cascade.
- Baseline span = 23,570,200 words at the raised 2²⁶ flat limit; program ≈ 2.23M lines, **95% of the
  lines = the combined wall texture table** (deleted at M13p4a).
- Measured op costs to estimate with: `fixed_mul 8,4` = 11,493 · `fixed_div 8,4` = 41,324 ·
  `write_hex_and_inc` ×2 (one fb pixel) = 1,564 · compile-time-address `xor_zero` write = 284 ·
  `cm.apply` ≈ 399 · `flat.sample` ≈ 391 · `shr_hex 8,5` = 331 · `read_table` ≈ thousands, `.lookup` ≈ 35.

## ★ THE 12M LEDGER (the hard budget; every endgame rung is accepted against its line)

`12M ÷ 16,000 px ≈ 750 ops/pixel, EVERYTHING included.` Four structural facts set the floor:

- **F1 — the write floor.** Copying one runtime 8-bit pixel to a compile-time fb address costs
  **284 ops (`xor_zero`)**; 16,000 px × 284 = **4.55M just for writes — 38% of the whole budget**.
  Runtime-pointer writes (1,564/px) are banned from every hot path. Nothing reduces the write COUNT
  except lower resolution (pV3) or fewer bits per pixel (pV2 — 16-color halves it to 142/px).
- **F2 — present is FREE.** `present.update_screen_reg` (present.fj:42, the 0x06 command) hands the
  device the `hex.vec 2` framebuffer ADDRESS and the device DMA-reads it — there is NO per-pixel
  present copy. The rasters write the final frame in place; the residue line covers only init/input.
- **F3 — the known-zero convention.** `xor_zero` assumes a zero destination — true today (fresh run,
  zero-init fb; the 462.7M baseline banks the same assumption in pass-2), and the 12M target is
  measured under that convention. ⚠ **M14 liability, on record:** a LOOPING game re-renders into a
  dirty fb — writes become clear+set (~×2 ⇒ +~4.5M at full res) or need a per-frame clear (same
  cost). The valves (pV2/pV3) cover it; decide at M14, not now.
- **F4 — exact per-row distance-light is unaffordable.** zrow needs `zidx = (ph·yslope[y])>>20`; the
  exact `fixed_mul 8,4` is 11.5k — even at ~1,400 computes/frame that is 16M, alone over budget. The
  ledger FORCES block-FP zrow (~2.5-3.5k, band boundaries may shift ≤1 row) — a [re-bless] with a
  PNG gate. (Unlike the rejected Phase-2 bucketing, every row keeps its own distance — only the
  BOUNDARY ROUNDING between light bands moves; vertical replication cannot occur.)

### The ledger (static E1M1 spawn frame; measured convention = the 462.7M baseline's)

| Line | Stage | Budget | Basis |
| --- | --- | --- | --- |
| L1 | floor+ceiling pixel writes (10,381 × 284) | 2.95M | F1 |
| L2 | wall pixel writes (5,619 × 284) | 1.60M | F1 |
| L3 | composite-pass overhead (classify/dispatch/glue over 16k cells) | ≤ 1.80M | pC variant choice |
| L4 | lit colors (block-FP zrow + cm, span/band-coherent, ~0.4-1.4k computes) | ≤ 1.50M | F4 |
| L5 | pass-1 geometry, until-full (x_range + projection + claim) | ≤ 2.00M | pG |
| L6 | BSP walk, until-full + abort (narrowed muls) | ≤ 1.20M | pG |
| L7 | init + input parse + clear_planes + present residue | ≤ 0.50M | F2 |
| L8 | slack (estimate error, @ ripple, misc) | 0.45M | — |
| — | **TOTAL** | **12.00M** | — |

**Valve triggers (pV):** if after pG the measured frame is >12M, apply valves in look-cost order until
under: **pV1 row-dup floors** (−~½ of L3+L4's floor share ≈ −1.0-1.5M), **pV2 16-color mode** (halves
L1+L2: −2.3M — owner permission, big look change), **pV3 80×50** (quarters L1-L4: −~5M — the only
write-COUNT cutter; most invasive, every golden re-blesses). The ledger with pV1 alone covers a
~1.5M overshoot; pV2 covers ~3.8M; the target is reachable without pV3 if L3-L6 land on their lines.

**[M14] upside (not counted):** the dispatch-incremental walk + affine maintenance replaces L5+L6's
until-full work with ~1-2M steady-state — headroom, not a dependency. The plan no longer NEEDS the
M14 number to claim 12M; it is the buffer that keeps 12M true while walking.

### Expected ladder v3 (estimates; re-anchor on the measured number at every rung)

| Rung | What | Tag | Frame after (est) | fps @280M |
| --- | --- | --- | --- | --- |
| — | baseline | — | 462.7M | 0.605 |
| M13p0 | measure split + stub split + until-full counts + PNG bake-off → owner picks | none | 462.7M | — |
| M13p1 | fj flat-colored floors (`draw_span_flat`) | [exact vs flat goldens] | **~225-240M** | ~1.2 |
| M13p4a | tiny 1×1/1×16 per-seg wall textures — DELETE the 793k-texel table | [re-bless, PNG-gated] | ~220-235M, **build ~10min → ~1-2min** | ~1.25 |
| M13p2 | pattern floors (only if the owner picks a pattern) | [re-bless, PNG-gated] | +~5-10M | ~1.2 |
| (M13p3a-c) | OPTIONAL interim floor squeezes — shippable wins while pC is prototyped | [exact] | ~205-220M | ~1.3 |
| M13pC1 | composite-pass PROTOTYPE: variants measured on the square room, idioms de-risked | none (scratch) | — | — |
| M13pC2 | composite pass, FLOORS+CEILINGS (plane pass + classify walk deleted) | [re-bless: block-FP zrow, PNG-gated] | **~160-175M** (floor ≈ L1+L3f+L4) | ~1.7 |
| M13pC3 | walls folded in — old pass-2 unroll DELETED (program −~16M words, span↓, @↓) | [exact vs pC2 goldens] | **~130-150M** | ~2 |
| M13pG1 | walk+pass-1 FULL-ABORT (stop the walk when all columns claimed) | [exact] | −(p0-measured post-full share) | — |
| M13pG2-5 | until-full geometry crush to L5+L6 (narrow muls, cheap x_range, residue) | mixed | **~14-20M** | ~15 |
| M13pV | valves, only if >12M: pV1 row-dup → pV2 16-color → pV3 80×50 | [re-bless, owner-gated] | **≤ 12.0M** | **≥ 23** |
| M13p8 | flip defaults, re-bless, merge to main | — | — | — |

**Where the convergence claim now lives:** L1+L2 (4.55M) are arithmetic, not estimates. L3+L4 are
bounded by the pC variant that pC1 MEASURES before the 16k unroll is committed. L5+L6 are bounded by
the until-full counts that p0 measures host-side (the walk/geometry cost collapses to "work done
before the screen fills" once pG1 lands). L7 is F2 plus small change. If any line's measured reality
exceeds its budget, the delta is named and a valve covers it — **the ladder cannot silently stall.**

---

## Task M13p0: Measurement harness + component split + PNG bake-off (host-only, no fj changes)

**Files:**
- Create: `scripts/measure_frame.py`
- Create: `scripts/bakeoff_planes.py`
- Modify: `src/doomfj/wall_renderer.py:54` (add `ablate` kwarg), `:213` (use it)
- Modify: `docs/m13p-procedural-plan.md` (record the measured split in the appendix below)

**Interfaces:**
- Consumes: `emit_wall_renderer(map_wad, mapname, cfg, *, asset_wad, over_align)` (existing),
  `tests.fj.test_wall_render._ScreenWithInput` (existing stdin-fed screen), `term.op_counter`
  (flipjump run result), `scripts/m12j_evidence.py::_save_png` (lift the helper).
- Produces: `emit_wall_renderer(..., ablate=frozenset())` accepting any of
  `{"planes", "pass2", "pass1"}`; `python scripts/measure_frame.py [--ablate planes,pass2]` printing
  `ops/frame`; a `scratchpad/bakeoff/*.png` contact set for the owner.

- [ ] **Step 1: add the `ablate` kwarg to the emitter** (measurement-only; default = emit everything).
  In `src/doomfj/wall_renderer.py`, change the signature and the mainline assembly:

```python
def emit_wall_renderer(map_wad, mapname, cfg, *, asset_wad=None, over_align=False,
                       ablate=frozenset()) -> str:
```

and where the mainline is joined (line ~213):

```python
    mainline = ["stl.startup_and_init_all", "present.init_screen",
                *([] if "pass1" in ablate else pass1),
                *([] if "pass2" in ablate else pass2),
                *([] if "planes" in ablate else plane_pass),
                ...]           # keep the existing tail (present/loop) exactly as-is
```

- [ ] **Step 2: write `scripts/measure_frame.py`** (the persistent successor of the session-scratchpad
  `measure_ops.py` / `split_e1m1.py` that were lost with the old scratchpad):

```python
"""Measure E1M1 spawn ops/frame through the SHARED emitter, with component ablation.
Usage: python scripts/measure_frame.py [--ablate planes,pass2,pass1] [--map E1M1]
Assemble is ~605s for E1M1 -- run via run_in_background, no shell timeout."""
import argparse, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import flipjump as fj
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.test_wall_render import _ScreenWithInput

SRC = [ROOT / "src/fj" / f for f in
       ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj")]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablate", default="", help="comma list: planes,pass2,pass1")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    args = ap.parse_args()
    ablate = frozenset(x for x in args.ablate.split(",") if x)
    cfg = Config()
    mw = WadFile.from_path(str(ROOT / args.wad))
    main_txt = emit_wall_renderer(mw, args.map, cfg, over_align=False, ablate=ablate)
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    (tmp / "m.fj").write_text(main_txt, encoding="utf-8")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
                tmp / "m.fjm", memory_width=W, print_time=False)
    sp = spawn_state(mw, args.map)
    vx, vy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    screen = _ScreenWithInput(f"{vx}\n{vy}\n{sp.angle}\n".encode())
    term = fj.run(tmp / "m.fjm", io_device=screen, print_time=False, print_termination=False)
    print(f"ablate={sorted(ablate) or 'none'}  ops/frame={term.op_counter:,}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: run the split** (background runs; ≈ 11 min each for E1M1). ⚠ Ablation is only valid
  **cumulatively from the END of the pipeline** (removing a later block never changes an earlier one;
  the reverse is false — ablating pass-1 leaves pass-2/planes running on zero-filled column arrays,
  which distorts their cost). So:
  - full (`--ablate ""`) — must reproduce ~462.7M (sanity)
  - `--ablate planes` → delta = the floor pass
  - `--ablate planes,pass2` → delta = pass-2 (trampoline + wall raster)
  - `--ablate planes,pass2,pass1` → the init + input-parse + present residue (NOT "the walk" — the
    BSP walk is inside pass-1 and leaves with it)
- [ ] **Step 3b: split pass-1 internally with STUB variants** (the walk and the per-seg work
  interleave, so block ablation cannot separate them — and pG's ordering plus the "M14-eligible
  share" reporting need exactly this split). Add two stub modes to the same `ablate` set:
  - `"segstub"` — the seg subsector-action leaf `fret`s immediately → the bare walk skeleton (node
    side tests + dispatch) + call overhead;
  - `"xrstub"` — `wall_x_range` replaced by an immediate cull-fail → walk + per-seg entry overhead
    without the atan/cull math.
  Derive: walk skeleton, wall_x_range+cull bulk, projection+claim residue (= pass-1 − the stubs).
  **These numbers size the ledger's L5/L6 and define the M14-incremental-eligible share.**
- [ ] **Step 3c: HOST-SIDE until-full counts** (sizes M13pG1, minutes not hours): instrument the
  oracle's `render_wall_frame` seg loop (a script-local counter, no oracle edit) to report, at E1M1
  spawn + 2 other viewpoints: (a) how many BSP nodes are visited and (b) how many segs reach
  `wall_x_range` BEFORE every column is claimed (`all(drawn)`), vs the totals (681 / 432+). The
  post-full share is what pG1's walk-abort deletes; L5+L6 must be paid only by the until-full share.
  Record all three viewpoints — the abort win is viewpoint-dependent and must hold at the WORST one.

- [ ] **Step 4: write `scripts/bakeoff_planes.py`** — oracle-only PNG contact set (lift `_save_png` from
  `scripts/m12j_evidence.py:19`, scale=5). Render square-spawn + E1M1-spawn + E1M1-rotated-45° for:
  - **T** current textured (reference), **F** flat tier (`floor_texturing=False` — already in-tree);
  - **P1 per-flat 16-strip:** `pal = pat[(x ^ y) & 15]` where `pat[i] = flat_texels[4*i]` (16 samples of
    the flat's row 0 — keeps per-flat hue identity);
  - **P2 checker:** `pal = base if ((x >> 2) ^ (y >> 2)) & 1 == 0 else base2`, `base = texels[0]`,
    `base2 = texels[32*64 + 32]`;
  - **P3 xor-noise:** `pal = pat[(x ^ (y << 1) ^ (y >> 2)) & 15]` (same `pat` as P1, busier break-up);
  - **W1 walls:** per-seg solid color = the **MODE texel** (most common palette index) of the seg's
    downscaled texture — NOT the mean (palette indices are not luminance-ordered; a mean index is a
    random hue), existing column light kept; **W2:** a 16-tall vertical band strip (see the hook below).
  Hooks (verified against the oracle at `8d175d2`):
  - Floor patterns P1-P3: override **`_render_planes_flat`** in a script-local `ReferenceModel`
    subclass — `_plane_pixel` does NOT receive `x`, so it cannot host an (x,y) pattern; keep its
    distance/zlight math and swap only the `flat_base` argument per (x,y).
  - Walls W1/W2: override **`_wall_texture`** to return a tiny synthetic canvas — **1×1** (the mode
    texel) for W1, **1×16** (16 band texels sampled from the real texture's column 0) for W2. The
    whole textured pipeline (`texcol % tw` → 0, heightmask wrap on th=16) renders it unchanged — this
    same trick is the fj rung M13p4a, so the bake-off previews exactly what ships.
  NO oracle edits at this rung (the chosen looks get real oracle modes in M13p2/p4).
- [ ] **Step 5: include the OWED #9a+#11 consolidated bless PNGs** in the same contact set (textured
  E1M1 current vs pre-campaign — the ~25px sub-pixel drift the owner still has to batch-look at).
- [ ] **Step 6: owner gate (the one real decision):** owner picks floor look (F / P1 / P2 / P3) and wall
  look (keep-textured / W1 / W2), and signs the #9a+#11 batch bless. **M13p2 and M13p4 scope depend on
  this answer.**
- [ ] **Step 7: commit** `git add scripts/measure_frame.py scripts/bakeoff_planes.py src/doomfj/wall_renderer.py docs/m13p-procedural-plan.md && git commit -m "M13p0: measurement split harness + procedural-look PNG bake-off"`

---

## Task M13p1: fj flat-colored floors — `floor_mode="flat"` (the big first rung)

The oracle tier, both goldens, and the host tests ALREADY EXIST (`floor_texturing=False`, square
`aeeb82a8…`, E1M1 `6d5baf9e…`). This rung only mirrors it in fj behind an emitter flag. It deletes,
per span: 5 of 6 `fixed_mul`s + 2 finesine reads + the distscale/xtoviewangle reads; per pixel: the
u/v extract + `flat.sample` + `cm.apply` + the 2 DDA adds. Also stops emitting the combined FLAT table.

**Files:**
- Modify: `src/fj/plane_render.fj` (add `plane.draw_span_flat` after `draw_span`, line ~230)
- Modify: `src/doomfj/wall_renderer.py` (`floor_mode` kwarg; seg flat-base bake; skip flat table;
  span_leaf swap)
- Modify: `src/doomfj/build.py` (pass-through kwarg on `build_wall_renderer`/`build_doom`, default
  `"textured"` until M13p8)
- Test: `tests/fj/test_floor_planes_fj.py` (add the two flat-mode tests)

**Interfaces:**
- Consumes: `render_planes_spans`/`plane_col` (UNCHANGED — grouping keys keep working: `col_ceilbase`/
  `col_floorbase` now hold the 2-nibble flat BASE palette index instead of a 5-nibble slice offset;
  `cmp 5` on values ≤ 0xFF is still exact), `rm._flat_base(asset_wad, name, cache)`
  (`reference_model.py:528` — texel (0,0), WALL_BG fallback), the `yslope`/`zlight` LUTs + `cm.apply`.
- Produces: `emit_wall_renderer(..., floor_mode="textured"|"flat")`; fj macro
  `plane.draw_span_flat fbase, view_w` reading globals `planeheight, light, y, x1, x2, flatbase` and
  returning via `span_ret` — the same register contract `render_planes_spans` already drives.

- [ ] **Step 1: write the failing square test** (append to `tests/fj/test_floor_planes_fj.py`; same
  shape as `test_square_textured_planes_byte_exact_vs_oracle`, lines 43-77):

```python
# the M13a flat-colored goldens (tests/host/test_floor_planes.py flat tier)
SQUARE_FLAT_GOLDEN = "aeeb82a8bea795acf51edf4ff9150dab8f4bd15030f8e6008c6b00a1702d1463"
E1M1_FLAT_GOLDEN = "6d5baf9eda47761d804d2127c85fad7a924aa6903f0217cbb2c988269dc8f88e"


def test_square_flat_planes_byte_exact_vs_oracle(tmp_path):
    """M13p1: floor_mode='flat' -- the M13a flat-colored tier through the SHARED emitter, byte-exact
    vs the oracle floor_texturing=False over 4 viewpoints, spawn matching the blessed flat golden."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw, aw = WadFile.from_path(ROOM), WadFile.from_path(ASSET)
    scene = build_scene(mw, aw, "MAP01")
    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45)]
    main = emit_wall_renderer(mw, "MAP01", cfg, asset_wad=aw, over_align=False, floor_mode="flat")
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    (tmp_path / "sqflat.fj").write_text(main, encoding="utf-8")
    out = tmp_path / "sqflat.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), PLANE_FJ.resolve(),
                 (tmp_path / "sqflat.fj").resolve()], out, memory_width=W, print_time=False)
    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                    floor_texturing=False)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"M13p1 @ ({vx},{vy},{va}) != oracle flat planes"
        if k == 0:
            assert frame_hash(got) == SQUARE_FLAT_GOLDEN
```

- [ ] **Step 2: run it to verify it fails** —
  `python -m pytest tests/fj/test_floor_planes_fj.py::test_square_flat_planes_byte_exact_vs_oracle -x`
  Expected: `TypeError: emit_wall_renderer() got an unexpected keyword argument 'floor_mode'`.

- [ ] **Step 3: add `plane.draw_span_flat`** to `src/fj/plane_render.fj` (after `draw_span`). The
  setup keeps ONLY the distance/zlight block + ONE `cm.apply` (lit is span-constant) + the running
  pointer seed; the loop is write-write-dec:

```
    // M13p1 — the FLAT-COLORED span (the M13a tier, spans instead of the retired M13c3 per-column
    // tramp). One span [x1,x2] at row y: lit = colormap[zlight-row][flat BASE index], written to every
    // pixel via the running fb pointer. `flatbase` holds the 2-nibble BASE palette index (not a slice
    // offset). Byte-exact vs the oracle _render_planes_flat/_plane_pixel: distance/zidx/lvl/zrow are
    // the exact draw_pixel formulas; lit is span-constant because (planeheight, light, base, y) are.
    // Returns via stl.fret BEFORE the @-local data (lesson #2). @requires hex.init & stl.ptr_init.
    def draw_span_flat fbase, view_w \
            @ ys, dist, zidx, lvl, zlidx, zrow, c127, tt, cmidx, lit, \
              count, pixp, fbptr, cell, sloop, sbody, sdone, zclamp, zok \
            < planeheight, light, y, x1, x2, flatbase, yslope, zlight, span_ret {
        hex.read_table 8, ys, yslope, 2, y               // ys = yslope[y]
        hex.fixed_mul 8, 4, dist, planeheight, ys        // distance = FixedMul(planeheight, yslope[y])
        hex.mov 8, tt, dist
        hex.shr_hex 8, 5, tt                             // distance >> 20 (LIGHTZSHIFT)
        hex.mov 3, zidx, tt
        hex.set 3, c127, 127
        hex.cmp 3, zidx, c127, zok, zok, zclamp          // zidx = min(127, distance>>20)
      zclamp:
        hex.mov 3, zidx, c127
      zok:
        hex.mov 2, lvl, light
        hex.shr_hex 2, 1, lvl                            // lvl = light >> 4 (LIGHTSEGSHIFT)
        hex.mul_const 3, zlidx, lvl, 128
        hex.add 3, zlidx, zidx
        hex.read_table 2, zrow, zlight, 3, zlidx         // zrow = zlight[lvl*128 + zidx]
        hex.zero 4, cmidx
        hex.mov 2, cmidx, flatbase                       // low byte = the flat BASE palette index
        hex.mov 2, cmidx + 2*dw, zrow
        cm.apply lit, cmidx                              // lit = colormap[zrow][base]  (SPAN-CONSTANT)
        hex.zero 8, pixp
        hex.mov 2, pixp, y
        hex.mul_const 8, pixp, pixp, view_w              // pixp = y*VIEW_W (once per span)
        hex.zero 8, tt                                   // CLEAR tt (still holds dist>>20 -- opt1 lesson)
        hex.mov 2, tt, x1
        hex.add 8, pixp, tt
        hex.shl_bit 8, pixp                              // *2 -> the hex.vec2 cell digit offset
        hex.set w/4, fbptr, fbase
        hex.ptr_index cell, fbptr, pixp                  // cell -> &fb[y*VIEW_W + x1]
        hex.mov 2, count, x2
        hex.sub 2, count, x1
        hex.inc 2, count                                 // count = x2 - x1 + 1
      sloop:
        hex.if0 2, count, sdone
      sbody:
        hex.write_hex_and_inc cell, lit                  // *cell = lit low nibble
        hex.write_hex_and_inc cell, lit + 1*dw           // *cell = lit high nibble -> next pixel
        hex.dec 2, count
        ;sloop
      sdone:
        stl.fret span_ret

      ys: hex.vec 8
      dist: hex.vec 8
      zidx: hex.vec 3
      lvl: hex.vec 3
      zlidx: hex.vec 3
      zrow: hex.vec 2
      c127: hex.vec 3
      tt: hex.vec 8
      cmidx: hex.vec 4
      lit: hex.vec 2
      count: hex.vec 2
      pixp: hex.vec 8
      fbptr: hex.vec w/4
      cell: hex.vec w/4
    }
```

- [ ] **Step 4: emitter `floor_mode`** in `src/doomfj/wall_renderer.py`:
  - signature: `def emit_wall_renderer(map_wad, mapname, cfg, *, asset_wad=None, over_align=False, ablate=frozenset(), floor_mode="textured") -> str:` (+ `assert floor_mode in ("textured", "flat")`)
  - per-seg bake (lines ~179-180): when flat, bake the BASE index instead of the slice offset —

```python
    flat_basecache: dict = {}
    def _flatval(name):
        return (flat_slice[name.upper()] if floor_mode == "textured"
                else rm._flat_base(asset_wad, name, flat_basecache))
    ...  ("seg_ceilbase", 5, _flatval(ssec.ceil_tex)),
         ("seg_floorbase", 5, _flatval(ssec.floor_tex))
```

  - the flat table (line ~123): `flat_table = _texel_table(...) if floor_mode == "textured" else ""`
    and drop it from the parts list (line ~267) when empty. (`plane.draw_span` referencing `flat.sample`
    is safe — an uninstantiated macro def assembles to nothing.)
  - span leaf (line ~218): `f"plane.draw_span framebuffer, {cfg.VIEW_W}"` →
    `f"plane.draw_span{'_flat' if floor_mode == 'flat' else ''} framebuffer, {cfg.VIEW_W}"`
  - KEEP `plane.clear_planes` + `basexscale/baseyscale` in flat mode (per-frame, ~0.1M — removing them
    risks the `--werror` unused-param cascade; delete at M13p3 only if free).
- [ ] **Step 5: square gate** —
  `python -m pytest tests/fj/test_floor_planes_fj.py -k "flat or textured" -x` (textured square test
  must STILL pass — the mode flag must not disturb the default path). Expected: both PASS, ~8-10 min.
- [ ] **Step 6: add + run the E1M1 flat capstone** (mirror the existing
  `test_e1m1_textured_planes_full_frame_byte_exact_and_golden`, `floor_mode="flat"`, oracle
  `floor_texturing=False`, hash `E1M1_FLAT_GOLDEN`; copy the existing capstone's skip/heavy marker
  verbatim). Run via `run_in_background` (~12 min). Expected: PASS.
- [ ] **Step 7: measure** — `python scripts/measure_frame.py --floor-mode flat` (add the pass-through
  arg to the script: one `ap.add_argument`, one kwarg). Expected: **~220-240M ops/frame** (floor pass
  ~300M → ~65M: setup 1,357 × ~17k ≈ 23M + pixels 10,381 × ~1.9k ≈ 20M + walk ~23M). Record the real
  number in the appendix + the ladder table.
- [ ] **Step 8: commit** — `git commit -m "M13p1: fj flat-colored floors (floor_mode=flat) -- byte-exact vs the M13a goldens, XXXM ops/frame (was 462.7M)"`

---

## Task M13p2: pattern floors — `floor_mode="pattern"` (ONLY if the owner picked P1/P2/P3 over plain flat)

Adds the procedural texture-ish break-up at near-flat cost. If the owner picked **F (plain flat)** in
M13p0, SKIP this task entirely — the ladder proceeds to M13p3 unchanged.

**Files:**
- Modify: `src/doomfj/reference_model.py` (add `_render_planes_pattern` + widen `floor_texturing` to a
  3-way `floor_mode` kwarg with back-compat: `floor_texturing=True/False` keeps working, `floor_mode`
  overrides), `src/doomfj/wall_renderer.py` (mode + the per-flat 16-entry pattern table bake),
  `src/fj/plane_render.fj` (`draw_span_pat`), `src/doomfj/lut_generator.py` (the combined 16-entry-per-
  flat pattern table, 16-aligned slices).
- Test: `tests/host/test_floor_planes.py` (2 new pattern goldens — bless AFTER the p0 PNG sign-off),
  `tests/fj/test_floor_planes_fj.py` (square 4-viewpoint + E1M1 capstone vs the new goldens).

**Interfaces:**
- Consumes: the owner's exact pattern formula from M13p0 step 6 (P1/P2/P3 — written into the oracle
  VERBATIM as the new mode).
- Produces: `floor_mode="pattern"`; fj `plane.draw_span_pat` = `draw_span_flat` + per-pixel
  `pal = pat[(x ^ f(y)) & 15]` via a 16¹ `.lookup` at a per-flat 16-aligned slice; per-pixel
  `cm.apply` returns (the pattern varies per pixel, so lit is no longer span-constant).

**Steps** (same cycle as M13p1 — the concrete diffs depend on the picked pattern; the P1 shape):
- [ ] **Step 1:** oracle `_render_planes_pattern` = `_render_planes_flat` with
  `fb[y*W+x] = colormap[row][pat[(x ^ y) & 15]]`, `pat` = 16 samples of the flat's row 0 (`texels[4*i]`).
  Host golden test first (fails), render, HASH-BLESS square+E1M1 (the PNG was owner-approved at p0).
- [ ] **Step 2:** bake the combined pattern table: per used flat, 16 entries at a 16-aligned slice
  (slice offset = `flat_ord * 16`, table total = 16×n_flats ≤ 4096 for E1M1's ~15 flats — within the
  table law). `seg_ceilbase/floorbase` bake the SLICE offset again (5-nib field, values ≤ ~240).
- [ ] **Step 3:** fj `draw_span_pat`: setup = flat-tier setup (dist/zrow/cmidx-high preset) + a 1-nibble
  `xctr` seeded `x1 & 15`-equivalent (`hex.mov 1, xctr, x1`) + `yx` preset = the y-derived nibble of the
  picked formula; loop = `hex.mov 1, pidx, xctr` · `hex.xor 1, pidx, yx` · pattern `.lookup` (16¹) at
  `patslice + pidx` · `hex.mov 2, cmidx, pal` · `cm.apply lit, cmidx` · 2 writes · `hex.inc 1, xctr` ·
  dec/loop. Per-pixel ≈ ~2.6k (vs flat ~1.9k) → floors +~7M.
- [ ] **Step 4:** gates (square 4-viewpoint byte-exact + E1M1 capstone vs the new goldens), measure,
  record, commit `"M13p2: procedural pattern floors (P?) -- XXXM"`.

---

## Task M13p3 (OPTIONAL interim): cheap floor squeezes — shippable wins while pC is prototyped

After p1/p2 the floor pass ≈ 65M: classify walk ~23M + span setup ~25M + pixels ~20M. The a-c
squeezes bottom out around ~45M (the runtime-pointer write pins the pixels at ~1.9k each) and are
ALL deleted by M13pC2 — do them only as interim shippable wins if pC1's prototyping stretches over
multiple sessions; skipping straight from p1/p4a to pC is the faster path to 12M. **Exception: p3b's
sector-key machinery is NOT throwaway — the same baked per-column key is pC's lit-cache key; building
it here de-risks pC.**

- [ ] **p3a [exact] per-ROW `rowbase` cache.** In `render_planes_spans` (frame_render.fj:768): compute
  `rowbase = y*VIEW_W` ONCE per row (100 `mul_const`/frame instead of 1,357), keep it in a global; in
  `draw_span_flat/_pat` the seed becomes `pixp = rowbase + x1` (8-nib mov + 2-nib add) + the existing
  `shl_bit` + `ptr_index` — the per-span `mul_const 8` (~900) + the zero/mov chain go. NO new pointer
  primitive needed (keeps `ptr_index` as-is). Saves ~1.5-2k × 1,357 ≈ **~2.5M**. Gate: square flat
  test + E1M1 capstone (byte-exact — address math only). ⚠ the advance unit (digit vs bit) trap — the
  golden catches it (gap #3 note).
- [ ] **p3b [exact, flat/pattern modes only] packed visplane KEY in the classify walk.** `plane_col`
  (frame_render.fj:801) compares 4 fields per open-span cell (`cmp 2 + cmp 8 + cmp 5 + cmp 2`). Both
  ph and flatbase and light are SECTOR-determined, so bake a per-seg 3-nibble
  `col_key = 2*sector_index + region` (region bit: ceil=0/floor=1), stored by pass-1 like the other
  col fields; the extend test becomes ONE `cmp 3`. Byte-exact FOR FLAT/PATTERN: splitting an
  oracle-merged span (two sectors, equal (ph,flat,light)) produces identical pixel values because the
  value is a pure function of (ph,light,base,y) — equal on both sides of the split. ⚠ NOT valid for
  the textured mode (span x1 seeds xfrac) — key the emitter: only emit the key-walk under
  flat/pattern. Walk ~23M → **~13-15M**. Gate: square + E1M1 flat capstone byte-exact.
- [ ] **p3c [re-bless, PNG-gated] zrow via block-FP (kill the last per-span `fixed_mul`).** The span
  setup's remaining giant is `dist = FixedMul(planeheight, yslope[y])` (11.5k) used ONLY for
  `zidx = min(127, dist>>20)`. Replace with the owner-law block-FP form: prebake per-row
  `(yslope_mant3, yslope_exp)`; normalize `planeheight` once per (row,visplane-key) change (or accept
  per-span); 3×3-nibble mant mul + exp add + windowed nibble read → zidx. ~3k vs ~13k per span ≈
  **~13M**. ⚠ zidx may shift ±1 at light-band boundaries → [re-bless]: PNG both maps, owner look,
  re-bless the two flat goldens (square likely unchanged — single planeheight). ONLY do this rung if
  p3a+p3b left the floor > ~25M.
- [ ] **Measure after each sub-rung** (`scripts/measure_frame.py --floor-mode flat`), record, commit
  each separately (`"M13p3a: ..."` etc.).

*(The former p3d "cell pass" is superseded by **Task M13pC** below — the 12M ledger forces the cell
pass to be the ONE composite raster for floors AND walls, with a per-cell budget the span design
can't meet; see pC for the full design and its measured variant choice.)*

---

## Task M13p4a: tiny per-seg wall textures — DO THIS RIGHT AFTER M13p1 (build-speed rung)

Per the owner's W1/W2 pick at M13p0. ⚠ At the 12M target, keeping full wall textures is NOT an option
(the sampling+DDA per-pixel cost has no room in L2+L3) — if the owner rejects both W1 and W2 at p0,
that is a stop-the-line conversation, not a silent re-plan. The two wall wins are SEPARABLE:

- [ ] **p4a [re-bless, PNG-gated at p0] tiny per-seg textures — DELETE the 793k-texel table.**
  The cheapest patch in the whole plan: replace each wall texture with a tiny synthetic canvas —
  **1×1** (the seg texture's MODE texel — most common palette index; NOT the mean, palette indices
  are not luminance-ordered) for W1, or **1×16** (16 band texels from the real texture's column 0)
  for W2. NOTHING else changes: the oracle override is `_wall_texture` returning the tiny canvas
  (exactly the p0 bake-off hook, so the PNG previewed exactly this); the emitter change is the
  `combined` build loop in `emit_wall_renderer` (wall_renderer.py:85-96) compositing the tiny canvas
  instead of the full one (`th ∈ {1,16}` are powers of 2 — the heightmask/`% tw` path is untouched).
  The fj kernels, `column_render_params`, pass-2 — ALL unchanged; the combined table just shrinks
  793,344 → ~70-1,120 texels. Bless new goldens (host + fj capstone). Ops win small (@ ripple only);
  the prize: **assemble ~605s → ~1-2min (measure it), span −~3.5M words — EVERY LATER RUNG ITERATES
  ~5× FASTER.** Do this rung EARLY (right after p1, per the ladder table) — it buys iteration speed
  for pC/pG.
- [ ] **The write-only wall raster is NOT a separate rung anymore** — with a 1×1 texel the wall lit
  color is COLUMN-CONSTANT (one `cm.apply` per ~160 claimed columns, computed in
  `column_render_params`, stored as a 2-nibble `col_lit`); the per-pixel raster that consumes it is
  **M13pC3** (the composite pass). p4a only needs to additionally store `col_lit` (and, for W2, the
  16 band texels' lit variants) so pC3 can consume it.
- [ ] **From p4a on, report the TWO numbers** (static frame; static minus the M14-incremental-
  eligible walk/cull share from the p0 stub split) in every measurement.

**Files:** `src/doomfj/reference_model.py` (`wall_mode` kwarg — the tiny-canvas rule VERBATIM from
the p0 pick), `src/doomfj/wall_renderer.py` (`wall_mode`; tiny-canvas combined table; the `col_lit`
store), `src/doomfj/build.py` (pass-through). Tests: `tests/host/test_wall_frame.py` (+wall-mode
goldens, blessed after the p0 PNG), fj square 4-viewpoint + E1M1 capstone.

---

## Task M13pC: THE COMPOSITE PASS — one unrolled raster for ceiling/wall/floor (ledger L1-L4)

The 12M pixel engine. Replaces BOTH the wall pass-2 (16K `pixel_tramp`+`compare_y` trampoline) and
the whole plane machinery (classify walk + span leaves) with ONE pass over the 16,000 cells, every
fb write at a **compile-time address** (`xor_zero`, 284 — F1). Program effect: the old pass-2 unroll
(~16M words per the M12 bisect) and the plane code are DELETED; the new cells are ~150-350 words each
(~2.5-5.6M words) → **net program shrinks ~10M+ words** → span ↓, @ ↓ (a global ripple every op
enjoys), assemble ↓ (on top of p4a's table deletion). Precedent: the M12 pass-2 16k unroll assembled
fine; the shared-leaf mantra does NOT apply to the cells (they must be inline for compile-time
addresses — they are FLAT sequences, not nested macros).

**Inputs (all already produced by pass-1 per column x, compile-time addresses):** `col_cexcl` (first
non-ceiling row), `col_fstart` (first floor row), `col_key` (2-nib sector key, from p3b or built
here), `col_lit` (wall lit color, from p4a), `col_ceil_ph/col_floor_ph` + `col_plight` (for the lit
strips). The lit COLORS per (visplane, row-band) come from the **band machinery** below.

### The lit-band machinery (L4 ≤ 1.5M) — shared by every variant

Floor/ceiling lit = `colormap[zrow(ph, y, light)][base]`. Per visplane (≈ visible sectors ×2 regions,
~10-30/frame), `zidx(y)` is MONOTONE in y (distance shrinks away from the horizon) ⇒ the 100-row lit
strip is ~≤14 constant RUNS. Build per visplane per frame:
1. ONE block-FP reciprocal of `ph` (`slopediv_recip_table` machinery, in-tree) → per band boundary k:
   threshold `t_k = (k<<20)·recip(ph)` (narrow mul);
2. walk the baked, monotone `yslope[]` ONCE comparing against `t_k` (a 2-3-nibble compare per row,
   ~100 rows) → the band-boundary rows;
3. per band: ONE `cm.apply` → the run's lit color.
Cost ≈ (recip ~5k + 100 cmp × ~150 + ~10 cm.apply) ≈ ~25k per visplane × ~20 ≈ **~0.5M**, plus the
strip/run STORAGE writes (runtime-array idiom, R4/R5x — same class as `store_col_field`). ⚠ the
reciprocal rounds ⇒ a boundary row can shift by 1 ⇒ **[re-bless] with PNG gate** (forced by F4 — the
exact mul is unaffordable; see the ledger). The oracle mirrors the SAME recip+threshold arithmetic so
fj stays byte-exact vs the NEW goldens.

### Cell variants — pC1 MEASURES, then commits ONE

- **Variant A (row-major classify cells).** `rep(view_h,y) rep(view_w,x) cell x,y`: per cell 2 narrow
  compares of compile-time `y` vs runtime `col_cexcl/col_fstart[x]` → region → write the region's lit.
  Simple, closest to today's structures; per-cell classify is the risk: pixel_clipped's 2 `hex.cmp 2`
  dominated its ~500 ops, so classify may cost ~200-400/cell ⇒ L3 = 3.2-6.4M — **potentially 2-3× over
  the L3 line**. Only survives pC1 if a cheap `cmp2_vs_const` micro-primitive (compile-time operand,
  dispatch-style) lands near ~70-100.
- **Variant B (column-major Duff entry).** Unroll per column a BACKWARD cell chain (cell 99 → cell 0);
  enter it via a dispatch on the runtime row count (the M5/M6 dispatch-CODE construction — in-tree
  precedent) so exactly the last N cells execute. Gives "first/last N rows" windows with ZERO per-cell
  classify; a [a,b] window needs the exit trick from C. Floor lit varies per band inside a column ⇒
  per-band re-entry (a few dispatches per column).
- **Variant C (patched-window chains) — the on-paper winner.** Column-major chains + **runtime code
  patching**: per column, pass-1.5 wflip-patches an EXIT jump after cell `b` and dispatch-enters at
  cell `a` — the chain runs [a,b] with zero per-cell tests; un-patch after (2 wflips, ~50-100). Per
  column: ceiling window + wall window + per-band floor windows (~4-8 patches ≈ ~0.5-1k) ×160 claimed
  columns ≈ ~0.15M. Cells: write `xor_zero` + ~35-70 glue; the region's lit sits in ONE shared source
  register set per window entry (walls: `col_lit`; planes: the band's lit) — so the cell body is
  IDENTICAL for all three regions. **L3 ≈ 16,000 × ~50-100 glue + windows ≈ 1.0-1.8M ✓.** New idiom
  risk: self-modifying chain enter/exit — de-risk FIRST (pC1).

### Sub-rungs (each shippable)

- [ ] **pC1 — prototype + measure (scratch, square room, fast gates).** (i) micro-test the patched
  enter/exit chain idiom on a 100-cell chain (variant C's only new mechanism); (ii) build a ~10-column
  strip of each surviving variant; (iii) measure per-cell cost of A vs C (B only if C's patching
  fails); (iv) measure the band machinery standalone. **Commit the numbers to the appendix; pick the
  variant that meets L3+L4 ≤ 3.3M.** No ship, no golden.
- [ ] **pC2 — floors+ceilings composite (ships).** The chosen variant renders planes; walls still go
  through the old pass-2 (order: pass-2 first, composite fills the plane regions — same occlusion
  semantics as today's plane pass). DELETE `render_planes_spans`/`plane_col`/`draw_span_flat`(/`_pat`)
  + the p1 span leaf. Oracle: `_render_planes_flat`/`_pattern` re-expressed via the SAME recip+
  threshold band arithmetic; **re-bless the flat goldens once** (PNG-gated ≤1-row band shifts — F4).
  Gates: square 4-viewpoint + E1M1 capstone vs the new goldens; measure (expect floor pass ≈ L1+L3f+L4
  ≈ **~5-6M**, frame ~160-175M); commit.
- [ ] **pC3 — walls folded in (ships).** Wall windows join the composite (consuming p4a's `col_lit`);
  DELETE the old pass-2 unroll entirely (−~16M words). W2 (1×16 bands): the wall window splits into
  ≤16 band sub-windows reusing the SAME patched-window machinery as floor bands (walls+floors share
  one pattern engine — the handoff's open question, answered). Gates: byte-exact vs pC2 goldens
  ([exact] — same pixel values, new addressing); measure (expect **~130-150M**, and L1-L4 now fully
  real); commit. Re-check the 2²⁶ span gate + record the new span/assemble.

---

## Task M13pG: geometry to the ledger — L5 (pass-1 ≤ 2.0M) + L6 (walk ≤ 1.2M) + L7 (residue ≤ 0.5M)

After pC3 the frame ≈ pixels (L1-L4, ~7.9M) + the ENTIRE old wall/geometry lump minus pass-2
(~100-130M — p0's stub split has the real number). This campaign crushes it to ~3.7M. The structural
insight: **front-to-back walk + the `full` flag mean all geometry cost after the screen fills is pure
waste** — Phase 1a already frets SEGS post-full, but the WALK (node side tests, subsector dispatch)
runs to completion. p0's Step 3c counts say how much is post-full (expected: most of it — the 681-node
walk visits everything; a spawn view fills within a fraction).

- [ ] **pG1 [exact] FULL-ABORT the walk.** At every emitted node entry (and subsector action), test the
  existing 1-nibble `full` flag → jump to the walk's exit (skip the subtree). Post-full cost collapses
  to ~one test per already-entered ancestor node (~≤ tree depth), post-full nodes never entered.
  Emitter: `_bsp_as_code` gains the guard (~2 ops/node of program, negligible). Gates: byte-exact on
  ALL goldens (the walk order until full is unchanged; everything after painted nothing — Phase 1a/1b
  proved the semantics). Measure: expect L6' = until-full walk share only. **The single biggest
  geometry rung; do it FIRST.**
- [ ] **pG2 [exact] narrow the walk's `point_on_side`** — E1M1 map coords and node line coeffs fit
  ~5-6 nibbles, not 10; the until-full nodes' 2 muls shrink ~2×. Combined with pG1, L6 ≈ until-full
  nodes × ~10-12k → **≤ 1.2M** if until-full nodes ≲ ~100-120 (p0 Step 3c verifies; if a viewpoint
  shows more, add the `_bsp_as_code` single-emission fix + revisit).
- [ ] **pG3 [mixed] until-full `wall_x_range` crush to L5.** The until-full segs (~50-120 per Step 3c)
  each pay ~2 cheap atans + range logic (~40-50k post-#13). Levers in measured order: (i) [exact]
  narrow the seg-loop per-column iteration (`inc 8, x` → 2-nib, `skip_if_drawn` audit, hoist loop
  consts); (ii) [re-bless] `viewangletox` 160→256 16ˣ (table-law, PNG-gated — kills the clamp+shift
  per angle_to_x); (iii) [re-bless] Montgomery batch inversion for the ~26-seg projection divides —
  only if the stub split shows projection > ~0.7M; (iv) if x_range is still > its share: the affine
  back-face cull already skips 44% — add the cheap frustum SIDE test (both endpoints behind the view
  plane → skip, an affine sign test, no atan) before any atan.
- [ ] **pG4 [exact] residue to L7:** startup/init_screen/set_palette/input-parse/clear_planes — audit
  whatever p0's residue run shows above ~0.5M (candidates: the stdin digit parser, table init loops).
- [ ] **pG5: `_bsp_as_code` single-emission** (each leaf emitted twice — M12 finding): mostly a
  program/span/@ win; do it here if pG1's guard doubled per-node code or the span gate tightens.
- [ ] Measure + commit each; record every SKIP with its number. **Exit criterion: frame ≤ ~14-20M
  and L5+L6+L7 each at/below its line at ALL THREE p0 viewpoints.**

**Explicitly deferred to M14 (unchanged owner decision):** the dispatch-incremental walk + affine
maintenance. Post-pG they become pure headroom (~L5+L6 → ~1-2M while walking) — the 12M static claim
does NOT depend on them.

---

## Task M13pV: the valves — apply IN ORDER until the measured frame ≤ 12.0M

Only entered if pG's exit measurement is > 12M. Each valve's arithmetic is exact (F1: only pV3 cuts
the write COUNT); each is an oracle mode + PNG gate + re-bless, same cycle as every rung. All are
owner-sanctioned in principle ("can sacrifice looks") but pV2/pV3 need an explicit fresh OK.

- [ ] **pV1 — row-dup floors [re-bless].** The composite renders even rows' plane cells and writes
  each value to rows y and y+1 (two `xor_zero`s, both compile-time — in variant C the odd-row cell
  simply joins the chain with the same source reg). Write count UNCHANGED (F1); saves the odd rows'
  share of L3 glue + halves the band-walk rows. **≈ −0.7-1.5M.** Look: floors slightly blockier
  vertically; walls untouched.
- [ ] **pV2 — 16-color mode [re-bless + owner permission].** Quantize the palette to 16 colors
  (colormap folds to 4-bit) → every pixel write is ONE nibble: `xor_zero` 284 → ~142. **L1+L2:
  4.55M → 2.3M (−2.3M).** The single biggest valve. Look: Doom's 256-palette shading drops to 16 —
  big; bake the 16 entries from the E1M1 histogram and PNG-gate. (Also halves the F3 dirty-frame
  liability for M14.)
- [ ] **pV3 — 80×50 half-resolution [re-bless + owner permission].** The only write-COUNT cutter:
  4,000 px × 284 = 1.14M writes; L1-L4 all quarter (**≈ −6M from the pixel side**). `cfg` change
  (VIEW_W/VIEW_H) rippling through every LUT + golden — the most invasive change in the plan; the
  present device init takes the new W/H (F2 — the device renders whatever geometry init_screen
  declares). Use only if pV1+pV2 fall short (they shouldn't: ledger math says pG-exit ~14-20M − pV1
  − pV2 ≈ 10.5-16.5M... if the top of that range holds, pV3 IS the closer — hence it stays in the
  plan, fully specified, not hand-waved).
- [ ] Also available to the owner (orthogonal, no re-bless): render-1-of-N tics — an fps
  multiplier at M14, not an ops/frame reduction; listed for completeness, does NOT satisfy the 12M
  ops/frame target.

---

## Task M13p8: endgame — flip defaults, re-bless the shipped goldens, merge to main

- [ ] Flip `build_doom` defaults to the owner-chosen `floor_mode`/`wall_mode` (+ any pV valves).
- [ ] The deferred merge checklist (owner policy): re-enable the 2 skipped E1M1 tests in
  `tests/fj/test_wall_render.py`; update `E1M1_GOLDEN` `0b817e4a…` → current; fix the R0-gate span
  bound in `tests/host/test_e1m1_integration.py`; full suite green (heavy gates in background).
- [ ] PR (TDD evidence per rung in the body: every "failing test first" + the measured ladder table),
  CR-ist review subagent, literal merge, tag `v0.M13p`, archive the binary under `versions/`
  (cr-tdd-ladder workflow).
- [ ] Update the memory handoff (`mperf-handoff`) + `docs/m13d2-perf-findings.md` with the final table.

---

## Measurement appendix (fill as the ladder executes)

| Measurement | Value | Rung / date |
| --- | --- | --- |
| baseline full frame | 462,742,550 | pre-p0 (2026-07-03) |
| `--ablate planes` → floor pass | | p0 |
| `--ablate planes,pass2` → pass-2 | | p0 |
| `--ablate planes,pass2,pass1` → init+input+present residue (L7 raw) | | p0 |
| `segstub` → walk skeleton (L6 raw) | | p0 |
| `xrstub` → x_range+cull bulk (L5 raw, part) | | p0 |
| until-full counts: nodes / segs before all-claimed (3 viewpoints) | | p0 step 3c |
| pC1: per-cell cost, variant A vs C; band machinery standalone | | pC1 |
| pC1: patched-chain enter/exit idiom cost | | pC1 |
| owner picks (floor / wall / #9a+#11 bless) | | p0 |
| p1 flat floors | | p1 |
| … | | |

## Self-review notes (plan-time)

- The M13p1 fj code is written against the CURRENT `draw_span`/`render_planes_spans` register contract
  (verified in-tree at `8d175d2`); `flatbase` reuse at 2 nibbles inside a 5-nibble field keeps
  `plane_col`'s `cmp 5` exact.
- p3b's key-walk is byte-exact ONLY for flat/pattern modes — the emitter must keep the 4-field compare
  for `floor_mode="textured"` (encoded in the task).
- Rungs p2/p4a/pV cannot carry final code before the owner's p0 pick — each instead carries the exact
  candidate formulas (P1-P3/W1-W2, specified to the texel) and the fixed implementation shape, so the
  pick drops in verbatim. pC1's variant choice is the other deliberate late-binding — bound by a
  measurement, not a placeholder.
- Estimates use isolated-kernel op costs, which the findings doc shows UNDERESTIMATE full-renderer
  cost (~2.5× @ gap) — hence every rung re-anchors on `measure_frame.py`, and no later rung's
  decision rule depends on an estimate alone.

## Adversarial gap review (second pass, 2026-07-03 — corrections already folded into the tasks above)

| # | Gap found | Type | Resolution (in-plan) |
| --- | --- | --- | --- |
| G1 | **The v1 ladder table didn't converge**: p3a-c bottom the floor at ~45M (pixels are pinned at ~1.9k/px by the runtime-pointer write), yet the table claimed 170-195M after p3 — the excluded cell-unroll was silently load-bearing. | arithmetic | Table recomputed; **p3d** (compile-addr cell pass) promoted to an explicit, load-bearing rung with its program-word cost and a prototype-first step; convergence-honesty paragraph added. |
| G2 | **Block ablation cannot split pass-1 internally** (the walk and seg actions interleave), and ablating pass-1 distorts downstream passes (zero-filled col arrays) — yet p6's ordering and the "M14-eligible share" depended on that split. | method | Step 3 rewritten (cumulative-from-the-END only); **Step 3b stub variants** (`segstub`, `xrstub`) added to split walk / wall_x_range / projection+claim. |
| G3 | **The bake-off hook was wrong**: `_plane_pixel` never receives `x` (reference_model.py:569) — it cannot host an (x,y) pattern. | correct | Hooks respecified: patterns override `_render_planes_flat`; walls override `_wall_texture`. |
| G4 | **Walls-as-tiny-textures insight**: `_wall_texture` → `% tw` + heightmask renders a 1×1/1×16 canvas through the UNCHANGED pipeline — the bake-off preview, the oracle mode, and the easiest fj rung are all the same mechanism. The v1 plan bundled the table deletion with the raster rewrite. | scope | **p4 split into p4a** (tiny textures — trivial, deletes the table, buys the ~5× build speedup early) **and p4b** (write-only raster, merged with p5 — same code region, one restructure). |
| G5 | **W1 "mean palette index" is not a color** — palette indices aren't luminance-ordered; a mean index is a random hue. | correct | W1 = the MODE texel (most common index; `_flat_base`'s texel(0,0) is the precedent for "cheap representative"). |
| G6 | **p3a assumed an unverified pointer primitive** (advancing a cell pointer by a runtime `2*x1` without `ptr_index`). | correct | p3a redesigned: cache `rowbase = y*VIEW_W` once per row (a global), span seed = `rowbase + x1` + the existing `shl_bit`/`ptr_index` — only verified ops; win re-estimated ~2.5M (was ~4M). |
| G7 | p3b's key needs `sector_index < 256` (2 nibbles) — E1M1 has ~85 sectors, but this must be ASSERTED at emit time; and the square room is a single sector, so the square gate is DEGENERATE for p3b — E1M1 is the only meaningful gate. | correct | Noted here; add the emit-time assert + rely on the E1M1 capstone when implementing p3b. |
| G8 | Flat mode still emits the now-unused `distscale`/`xtoviewangle` LUT data (span words, no ops). | cost | Free cleanup — fold into p3 or whenever the emitter is next touched. |
| G9 | Mode-combination golden matrix (floor_mode × wall_mode) could explode the heavy-test count. | cost | Gate only (a) the full-textured combo (regression net) and (b) the SHIPPED combo; do not bless off-diagonal combos. |
| G10 | The handoff's open question "distance-banded pattern *scale* as a perspective cue" got no bake-off candidate; and suite time grows with each new heavy fj test. | scope | Optional P4 candidate at the owner's request during p0; heavy tests carry the existing skip-marker convention (plan p1 step 6 already says copy it verbatim). |
| G11 | **The known-zero fb convention is load-bearing and frame-scoped** (found in the v3 hard-12M pass): `xor_zero` writes assume a zero destination — true per fresh run, but a LOOPING game (M14) re-renders into a dirty fb: writes become ~×2 or need a ~4.5M/frame clear. Any 12M/frame claim silently banked this. | correct | Named as ledger fact **F3** with the M14 liability on record; pV2/pV3 sized to cover it; decision explicitly deferred to M14. |
| G12 | **The write floor is arithmetic, not design**: 16,000 × 284 = 4.55M (38% of 12M) no matter how clever the kernels; and the exact per-row zlight mul (11.5k) is unaffordable at ANY compute count the frame needs — so full-res 12M FORCES both compile-addr writes everywhere AND block-FP zrow ([re-bless]). The v2 plan treated the cell pass and the zrow change as optional. | arithmetic | The LEDGER section (F1, F4) makes both forced moves explicit; pC2 carries the one-time flat-golden re-bless with the PNG gate and the no-vertical-replication argument. |
| G13 | The v2 endgame (p4b/p5/p6) still spent per-cell classify + per-column runtime-pointer loops that can't meet 750 ops/px; and the walk ran to completion after the screen filled (Phase 1a only frets SEGS post-full — the 681-node walk itself never stops). | design | v3 restructures: **pC** unified composite pass (variants A/B/C, measured at pC1; variant C's patched-window chains reuse the M5/M6 dispatch-code + R4/R5x runtime-write idioms); **pG1** full-abort guards every node on the existing `full` flag; p0 step 3c measures the until-full share host-side before any fj work. |
