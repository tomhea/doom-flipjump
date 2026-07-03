# M13p — Procedural-Floor/Wall Perf Ladder Implementation Plan (462.7M → ~12M ops/frame)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking. Read the memory `fj-lessons` file BEFORE writing any fj code.

**Goal:** Ladder the renderer from the measured **462,742,550 ops/frame (0.605 fps @280M)** toward the
DESIGN §1 ~12M budget by replacing 1:1-Doom perspective texturing with **cheap screen-space procedural
color** (floors first, then walls), then re-crushing the geometry/walk residue at the new scale — as a
sequence of small rungs, **each one measured, each one a non-empty win, each one shippable**.

**Architecture:** The pipeline stays (BSP walk → pass-1 geometry → pass-2 wall raster → plane pass).
Each rung swaps ONE kernel or bakes ONE table cheaper, behind an emitter *mode flag* mirrored in the
oracle, so the textured path stays in-tree and testable the whole time. De-risk order per rung:
oracle change → PNG → owner look-OK → fj mirror → byte-exact gate → **measure ops/frame** → commit.

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
  lines = the combined wall texture table** (deleted at M13p4).
- Measured op costs to estimate with: `fixed_mul 8,4` = 11,493 · `fixed_div 8,4` = 41,324 ·
  `write_hex_and_inc` ×2 (one fb pixel) = 1,564 · compile-time-address `xor_zero` write = 284 ·
  `cm.apply` ≈ 399 · `flat.sample` ≈ 391 · `shr_hex 8,5` = 331 · `read_table` ≈ thousands, `.lookup` ≈ 35.

## The budget model (why the rungs are what they are)

Current 462.7M ≈ **floor pass ~300M** (per-span perspective setup ~200M + per-pixel u,v DDA/sample ~43M +
classify walk ~23M + slop) + **walls/geometry/walk ~162M** (internally UNSPLIT — measured only as a lump;
M13p0 splits it). Two hard facts frame the ladder:

1. **Procedural color deletes both floor giants at once.** A flat/pattern span needs NO u,v seed (the 6
   `fixed_mul`s per span vanish) and NO per-pixel DDA/sample — only zlight + the write survive. That is
   the single biggest step available anywhere: ~300M → ~65M in one easy rung (M13p1), then ~65M → ~45M
   with the cheap squeezes (M13p3a-c). **Below ~45M the floor is pinned by the runtime-pointer write
   (1,564/px) + the span/walk machinery — only the unrolled compile-address cell pass (p3d) or fewer
   pixels (p7) go lower.** p3d is therefore load-bearing for any frame below ~200M, not optional.
2. **12M is won or lost outside the floor after that.** The wall/geometry lump (~162M) must fall to
   ~10M. Its composition is unmeasured — M13p0's split sizes M13p4-p6. Two honest scenarios:
   - If the lump is mostly pass-2 trampoline + per-seg column iteration + `wall_x_range` (all
     restructurable), the static frame lands **~45-90M ≈ 3-6 fps** after M13p6 (see the ladder table).
   - The last stretch toward ~12M then comes from M13p7 (2×2 blocks / row-dup, on floors AND walls)
     **and/or** the [M14] dispatch-incremental walk+`rw_distance` (the p0-stub-measured walk/cull
     share → ~1-2M — already designed, needs the sim's dvx/dvy). Owner has already ruled only M14+
     *walking* fps matters, so quoting the projected M14 steady-state per rung is legitimate:
     **report BOTH numbers from M13p4a on** (static frame ops, and static minus the M14-incremental-
     eligible walk/cull share).

Every rung below ships a measured win regardless of where the ladder stops; the owner calls "playable"
whenever satisfied.

### Expected ladder (estimates; re-anchor each rung on the measured number)

| Rung | What | Tag | Frame after (est) | fps @280M |
| --- | --- | --- | --- | --- |
| — | baseline | — | 462.7M | 0.605 |
| M13p0 | measure split + PNG bake-off + owner picks | none | 462.7M | — |
| M13p1 | fj flat-colored floors | [exact vs flat goldens] | **~225-240M** | ~1.2 |
| M13p2 | pattern floors (if owner picks a pattern) | [re-bless, PNG-gated] | +~5-10M over p1 | ~1.15 |
| M13p3a-c | floor residue squeezes (row base, walk key, zrow) | [exact] + one [re-bless] | ~205-220M (floor ~45M) | ~1.3 |
| M13p3d | unrolled compile-addr plane cell pass (floor → ~10-18M) | [exact vs flat goldens] | **~175-190M** | ~1.5 |
| M13p4a | tiny per-seg wall textures — DELETE the 793k-texel table | [re-bless, PNG-gated] | ~170-185M, **build ~10min → ~1-2min** | ~1.6 |
| M13p4b+p5 | write-only wall raster + pass-2 per-column loop (one restructure) | [exact after p4a] | ~140-160M | ~1.9 |
| M13p6 | geometry endgame at the new scale (p0-split-ordered) | mixed | **~45-90M** (split decides; the lump is ~130M unsplit) | 3-6 |
| M13p7 | 2×2 blocks / row-dup (floors AND walls) | [re-bless, PNG-gated] | ~25-60M | 5-11 |
| — | + the [M14] dispatch-incremental walk/cull share (designed, needs the sim) | [M14] | **~12-30M steady-state** | 9-23 |
| M13p8 | flip defaults, re-bless, merge to main | — | — | — |

**Convergence honesty:** the static single-frame 12M pre-M14 is NOT promised by this table — it requires
p6 to cut the (unmeasured) ~130M pass-1/walk/present lump by ~90%, which only the p0 split can confirm.
What IS promised: every rung is a measured win, the frame passes ~1 fps at p1, ~2 fps by p5, and the
M14 steady-state number (the one the owner ruled matters) lands in the ~12-30M band if p6+p7 go as
estimated. Re-anchor this table on real numbers at every rung.

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
  interleave, so block ablation cannot separate them — and p6's ordering plus the "M14-eligible
  share" reporting need exactly this split). Add two stub modes to the same `ablate` set:
  - `"segstub"` — the seg subsector-action leaf `fret`s immediately → the bare walk skeleton (node
    side tests + dispatch) + call overhead;
  - `"xrstub"` — `wall_x_range` replaced by an immediate cull-fail → walk + per-seg entry overhead
    without the atan/cull math.
  Derive: walk skeleton, wall_x_range+cull bulk, projection+claim residue (= pass-1 − the stubs).
  **These numbers order M13p4b-p6 and define the M14-incremental-eligible share.**

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

## Task M13p3: crush the floor residue (a-c: cheap squeezes to ~45M; d: the cell-pass endgame to ~10-18M)

After p1/p2 the floor pass ≈ 65M: classify walk ~23M + span setup ~25M + pixels ~20M. **The a-c
squeezes bottom out around ~45M** (the runtime-pointer write pins the pixels at ~1.9k each); the real
floor endgame is **p3d**, the unrolled compile-address cell pass. Do a-c first only if p3d's program-
word cost needs deferring past M13p4a's table deletion (which frees ~3.5M words of span headroom);
otherwise a reasonable path is p1 → p4a → p3d, skipping a-c entirely. Decide on p0's numbers.

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
- [ ] **p3d [exact-vs-flat-goldens] the unrolled compile-address plane CELL pass — the floor endgame.**
  Replaces spans + classify walk + span leaf entirely for flat/pattern modes: unroll
  `rep(view_h, y) rep(view_w, x) plane_cell x, y` (16,000 cells, like wall pass-2). Per cell, ALL of
  (x, y, fb address, pattern index) are COMPILE-TIME: classify = 2× `cmp 2` vs `col_cexcl/col_fstart +
  8*x*dw` (compile-time addresses), then write `lit_col_strip` via `xor_zero` at the compile-time fb
  address (~284). The one runtime input is the lit color: keep a per-COLUMN 2-nibble `col_litc/col_litf`
  pair (ceil/floor lit color at the column's zrow... which varies per ROW) — so the cell body reads a
  per-(column,row-band) value. Two candidate designs, prototype ONE row-block first and measure:
  - (d-i) keep zrow per-row-per-column via a pass-1.5: for each column, a tiny runtime loop fills a
    100-entry per-column lit strip? — REJECTED on sight: that's 16k fills again. Only viable if strips
    are per-VISPLANE (few): pass-1.5 builds `lit_strip[sector][y]` (n_sectors×100 fills, ~dozens of
    visible sectors ⇒ ~2-6k fills × ~1.5k ≈ 3-9M) into a runtime-written table; the cell reads
    `lit_strip + (key*100 + y)*dw`-style at a compile-time y offset with a runtime key — needs
    `ptr_index`-free keyed read (dispatch by key, 16ˣ table law) — design carefully against R4/R5x
    runtime-write idioms.
  - (d-ii) cheaper: accept per-cell `cm.apply` (399) with a per-column preset zrow?? zrow varies by
    row — same problem. So (d-i)'s per-visplane strip is the shape; the fallback if it fights fj is
    2×2/row-dup (p7) which halves the strip AND the cells.
  Cost: cells 16,000 × ~(2 cmp + strip read + write) ≈ ~600-1,100 ⇒ **floor ≈ 10-18M all-in** (strips
  included), program +~1.5-3M words (do AFTER p4a's −3.5M table deletion; re-check the 2²⁶ span gate).
  Byte-exact vs the flat goldens (same values, new addressing). This rung is LOAD-BEARING for any
  frame < ~200M — it is a real design task; prototype the strip read standalone (fast square gate)
  before committing the 16k unroll.
- [ ] **Measure after each sub-rung** (`scripts/measure_frame.py --floor-mode flat`), record, commit
  each separately (`"M13p3a: ..."` etc.).

---

## Task M13p4: procedural walls — TWO sub-rungs (p4a table deletion; p4b write-only raster)

Per the owner's W1/W2 pick at M13p0 (if the owner keeps textured walls, p4a still lands as a mode
flag + measurement, default off, and the ladder re-evaluates after M13p6). The two wins are
SEPARABLE and deserve separate rungs:

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
  ~5× FASTER.** Do this rung EARLY (right after p1 is also defensible) — it buys iteration speed for
  p3d/p5/p6.
- [ ] **p4b [exact after p4a] write-only wall raster.** With a 1×1 texel the per-pixel wall body's
  sample + `cm.apply` + v-DDA are computing a COLUMN-CONSTANT value 5,619 times: hoist the lit color
  into `column_render_params` (once per ~160 claimed columns), drop `col_step/col_frac0/
  col_heightmask` stores, and reduce `leaf_body_w` to the fb write + row advance. For W2 (1×16), keep
  a narrowed 8.8 v-DDA + a 16¹ band `.lookup`. ⚠ do p4b TOGETHER WITH M13p5 (they rewrite the same
  pass-2 code region — separate rungs = rework; one restructure, one gate). Expect **−10-20M** with
  p5's share included.
- [ ] **From p4a on, report the TWO numbers** (static frame; static minus the M14-incremental-
  eligible walk/cull share from the p0 stub split) in every measurement.

**Files (both):** `src/doomfj/reference_model.py` (`wall_mode` kwarg — the tiny-canvas rule VERBATIM
from the p0 pick), `src/doomfj/wall_renderer.py` (`wall_mode`; tiny-canvas combined table; p4b: the
column hoist + dropped col stores), `src/fj/frame_render.fj` (p4b only: `leaf_body_w` variant +
pass-2 loop with M13p5), `src/doomfj/build.py` (pass-through). Tests: `tests/host/test_wall_frame.py`
(+wall-mode goldens, blessed after the p0 PNG), fj square 4-viewpoint + E1M1 capstone per rung.

---

## Task M13p5: wall pass-2 restructure — per-column [top,bottom] runtime loop [exact; ONE rung with p4b]

The 16K-pixel unrolled `pixel_tramp`+`compare_y` trampoline runs for every screen pixel though only
~5,619 are wall pixels. Replace with a per-column runtime loop over `[top, bottom]` with a running fb
pointer (`+= VIEW_W*2*dw` per row). Under procedural walls the per-pixel body is a write, so the
pointer math is the only added cost. Also shrinks the program by ~16M words (the M12 bisect's pass-2
share) → smaller span, faster assemble, global @ ripple.

- [ ] **Step 1 (gate the idea, gap #11):** measure the current pass-2 share from the p0 split; estimate
  net = (10,381 skipped trampolines × their cost) − (5,619 × pointer-advance cost). **Land only if the
  estimate ≥ ~5M**; else record SKIPPED-with-numbers in the appendix and move on.
- [ ] **Step 2:** implement in `frame_render.fj` (a `wall_col x` unrolled per column — compile-time
  column base address + a runtime row loop), byte-exact gates (goldens unchanged — same pixels), measure
  ops + span + assemble, commit.

---

## Task M13p6: geometry endgame at the new scale (p0-split-ordered)

The "geometry well is DRY" verdict was relative to 462M — at a ~150M frame every 2M is 1.3%. Re-open
the assessed-and-skipped list with the p0 split as the order. Rule: **prototype → measure standalone →
land iff ≥ ~2% of the then-current frame.** Candidates, largest-expected first:

- [ ] **p6a [exact] per-seg column-iteration narrowing** (`seg_pass1_leaf_body_mtlwp`,
  frame_render.fj:~640-750): the per-column loop pays `hex.inc 8, x` + `hex.add 8, scale, scalestep` +
  `skip_if_drawn` per column per seg. Narrow `x` to 2 nibbles (column < 160), audit `skip_if_drawn`'s
  cost, hoist the `hex.set 8, cVH` constants out of the loop.
- [ ] **p6b [exact] `_bsp_as_code` single-emission** (the M12 finding: each leaf's subsector action is
  emitted TWICE, once per node branch — share via one label + jump). Mostly a span/program win (@
  ripple + assemble), possibly small ops.
- [ ] **p6c [exact] walk `point_on_side` width audit** — E1M1 map coords fit well under 10 nibbles;
  narrow the baked muls.
- [ ] **p6d [re-bless] Montgomery batch inversion** for the ~26-seg projection divides (the designed
  gather-then-use restructure; docs "DECIDED — BATCH INVERSION" section) — only if the p0 split shows
  projection ≥ ~8M.
- [ ] **p6e [re-bless] `viewangletox`/`zlight` 16ˣ conversions** (table-law; viewangletox shifts
  columns → PNG-gate).
- [ ] **p6f: present/init residue** — whatever the p0 split shows for the non-render frame cost;
  attack by the same narrow/unroll rules.
- [ ] Measure + commit each landed item; record each SKIP with its measured number.

**Explicitly deferred to M14:** the dispatch-incremental walk + affine `rw_distance`/side maintenance
(designed, needs the sim's dvx/dvy). The plan's 12M claim counts these at their M14 steady-state
(~15M → ~1-2M); do NOT build stateless approximations of them now (owner decision on record).

---

## Task M13p7: fewer pixels — 2×2 blocks / half-res floors (ONLY if the frame is still > ~16-25M)

The last fidelity lever (owner: looks are sacrificable, PNG decides). Preferred form: **floor row
duplication** — render only even rows' spans and write each pixel to row y AND y+1 (the classify walk
halves too: ~50 rows), floors ≈ ×0.55; then **2×2** (also step x by 2, write 4 cells) if needed,
floors ≈ ×0.3. Walls analogous (row-pair writes in the p5 column loop). Oracle mirror per mode +
PNG-gate + re-bless + measure, same cycle as every rung. Alternatives to offer the owner alongside:
render-1-of-N tics, or 80×50 (a cfg change rippling through every golden — most invasive, last).

---

## Task M13p8: endgame — flip defaults, re-bless the shipped goldens, merge to main

- [ ] Flip `build_doom` defaults to the owner-chosen `floor_mode`/`wall_mode` (+ blocks if p7 landed).
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
| `--ablate planes` (wall-side lump) | | p0 |
| `--ablate planes,pass2` (pass-1 + walk + present) | | p0 |
| `--ablate planes,pass2,pass1` (walk + present) | | p0 |
| owner picks (floor / wall / #9a+#11 bless) | | p0 |
| p1 flat floors | | p1 |
| … | | |

## Self-review notes (plan-time)

- The M13p1 fj code is written against the CURRENT `draw_span`/`render_planes_spans` register contract
  (verified in-tree at `8d175d2`); `flatbase` reuse at 2 nibbles inside a 5-nibble field keeps
  `plane_col`'s `cmp 5` exact.
- p3b's key-walk is byte-exact ONLY for flat/pattern modes — the emitter must keep the 4-field compare
  for `floor_mode="textured"` (encoded in the task).
- Rungs p2/p4/p7 cannot carry final code before the owner's p0 pick — each instead carries the exact
  candidate formulas (P1-P3/W1-W2, specified to the texel) and the fixed implementation shape, so the
  pick drops in verbatim. That is the plan's only deliberate late-binding.
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
