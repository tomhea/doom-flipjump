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
   the single biggest step available anywhere: ~300M → ~65M in one easy rung (M13p1), then ~65M → ~15-20M
   with follow-up squeezes (M13p3).
2. **12M is won or lost outside the floor after that.** The wall/geometry lump (~162M) must fall to
   ~10M. Its composition is unmeasured — M13p0's split sizes M13p4-p6. Two honest scenarios:
   - If the lump is mostly pass-2 trampoline + per-seg column iteration + `wall_x_range` (all
     restructurable), the static frame lands **~25-45M ≈ 6-11 fps** after M13p6.
   - The last stretch to ~12M then comes from M13p7 (2×2 blocks / fewer pixels) **and/or** the
     [M14] dispatch-incremental walk+`rw_distance` (~15M of walk/cull cost → ~1-2M — already designed,
     needs the sim's dvx/dvy). Owner has already ruled only M14+ *walking* fps matters, so quoting the
     projected M14 steady-state per rung is legitimate: **report BOTH numbers from M13p4 on** (static
     frame ops, and static minus the M14-incremental-eligible walk/cull share).

Every rung below ships a measured win regardless of where the ladder stops; the owner calls "playable"
whenever satisfied.

### Expected ladder (estimates; re-anchor each rung on the measured number)

| Rung | What | Tag | Frame after (est) | fps @280M |
| --- | --- | --- | --- | --- |
| — | baseline | — | 462.7M | 0.605 |
| M13p0 | measure split + PNG bake-off + owner picks | none | 462.7M | — |
| M13p1 | fj flat-colored floors | [exact vs flat goldens] | **~220-240M** | ~1.2 |
| M13p2 | pattern floors (if owner picks a pattern) | [re-bless, PNG-gated] | +~5-10M over p1 | ~1.15 |
| M13p3 | floor residue crush (walk key, row ptr, zrow) | [exact] + one [re-bless] | **~170-195M** | ~1.5 |
| M13p4 | procedural walls + DELETE the texture table | [re-bless, PNG-gated] | ~155-180M, **build ~10min → ~1-2min** | ~1.7 |
| M13p5 | pass-2 per-column loop (kill the 16K trampoline) | [exact] | ~135-160M | ~1.9 |
| M13p6 | geometry endgame at the new scale (p0-split-ordered) | mixed | **~25-60M** (split-dependent) | 5-11 |
| M13p7 | 2×2 blocks / fewer pixels (only if still short) | [re-bless, PNG-gated] | ~12-25M | 11-23 |
| M13p8 | flip defaults, re-bless, merge to main | — | — | — |

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

- [ ] **Step 3: run the split** (4 background runs; each ≈ 11 min for E1M1). Record in the appendix:
  - full (`--ablate ""`) — must reproduce ~462.7M (sanity)
  - `--ablate planes` → wall-side lump
  - `--ablate planes,pass2` → pass-1 geometry + walk + present residue
  - `--ablate planes,pass2,pass1` → walk + init/present floor cost
  Derive: floor pass, pass-2 (trampoline + wall raster), pass-1 (x_range/projection/claim loops),
  walk+present. **These four numbers order M13p3-p6.**

- [ ] **Step 4: write `scripts/bakeoff_planes.py`** — oracle-only PNG contact set (lift `_save_png` from
  `scripts/m12j_evidence.py:19`, scale=5). Render square-spawn + E1M1-spawn + E1M1-rotated-45° for:
  - **T** current textured (reference), **F** flat tier (`floor_texturing=False` — already in-tree);
  - **P1 per-flat 16-strip:** `pal = pat[(x ^ y) & 15]` where `pat[i] = flat_texels[4*i]` (16 samples of
    the flat's row 0 — keeps per-flat hue identity);
  - **P2 checker:** `pal = base if ((x >> 2) ^ (y >> 2)) & 1 == 0 else base2`, `base = texels[0]`,
    `base2 = texels[32*64 + 32]`;
  - **P3 xor-noise:** `pal = pat[(x ^ (y << 1) ^ (y >> 2)) & 15]` (same `pat` as P1, busier break-up);
  - **W1 walls:** per-seg solid color = the mean palette index of the seg's downscaled texture
    (baked), existing column light kept; **W2:** W1 + `pat[(texrow) & 15]` vertical 16-banding.
  Implement each as a tiny local override of `_plane_pixel`/the wall texel in a subclassed
  `ReferenceModel` inside the script — NO oracle edits at this rung (the chosen one gets a real oracle
  mode in M13p2/p4).
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

## Task M13p3: crush the floor residue to ≤ ~20M

After p1/p2 the floor pass ≈ 65M: classify walk ~23M + span setup ~23M + pixels ~20M. Three
independent sub-rungs, each measured; do them in this order and STOP when the floor pass ≤ ~20M
(diminishing returns vs M13p4-p6 which are bigger).

- [ ] **p3a [exact] per-ROW fb base pointer.** In `render_planes_spans` (frame_render.fj:768): seed a
  row pointer ONCE per row (`rowp += VIEW_W*2*dw` per row via a preset add), and in
  `draw_span_flat/_pat` replace the `pixp = y*VIEW_W` `mul_const 8` + 8-nib add + `shl_bit` + `ptr_index`
  seed with `ptr_index` from the ROW base and the 2-nibble `2*x1` offset (`hex.mov 2` + `shl_bit 3`).
  Saves ~2.5-3k × 1,357 spans ≈ **~4M**. Gate: square flat test + E1M1 capstone (byte-exact — address
  math only). ⚠ the advance unit (digit vs bit) trap — the golden catches it (gap #3 note).
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

**Deliberately NOT here:** the full 16k-cell unrolled plane pass (compile-time-address `xor_zero`
writes, ~284/px). It's another ~10M below the span design but costs a ~+2-4M-word program, a per-cell
zrow strategy, and a new pass structure — disproportionate while M13p4-p6 hold bigger wins. Revisit
ONLY as part of M13p7 if the final gap demands it.

---

## Task M13p4: procedural walls — `wall_mode="pattern"` + DELETE the combined texture table

Per the owner's W1/W2 pick at M13p0 (if the owner keeps textured walls, this rung still lands the
mode flag + measurement, default off, and the ladder re-evaluates after M13p6). Twin wins: the wall
texel becomes column-constant (per-pixel = write only), and the combined wall texture table — 95% of
the program's source lines, the reason the build is ~10.1 min — is not emitted at all.

**Files:**
- Modify: `src/doomfj/reference_model.py` (`wall_mode` kwarg: the wall texel → the seg's baked color
  [W1] or `color ^ band[texrow & 15]`-style [W2] — the p0-picked formula VERBATIM),
  `src/doomfj/wall_renderer.py` (`wall_mode`; bake `seg_color` = mean palette index of the downscaled
  texture instead of `seg_texinfo`; skip `tex`/`_texel_table`), `src/fj/frame_render.fj` (a
  `leaf_body_w` flat variant: `proj.column_render_params` keeps top/bottom/scale but drops
  `texcol`/`frac0`/`step`; per-pixel = the lit column color write + row advance),
  `src/doomfj/build.py` (pass-through).
- Test: `tests/host/test_wall_frame.py` (+2 wall-pattern goldens, blessed after the p0 PNG),
  `tests/fj/test_wall_render.py` or `test_floor_planes_fj.py` (square 4-viewpoint + E1M1 capstone).

**Interfaces:**
- Consumes: the p0 wall pick; the pass-2 column machinery unchanged (`col_top/col_bottom` etc. stay;
  `col_base/col_step/col_frac0/col_heightmask` become the baked color / vanish for W1).
- Produces: `wall_mode="textured"|"pattern"`; a build whose assemble is **~1-2 min** (measure it) and
  whose span drops ~3.5M words — EVERY LATER RUNG ITERATES ~5× FASTER. Report ops/frame AND the new
  assemble time + span.

- [ ] **Steps:** oracle mode + host goldens (bless) → fj variant + emitter flag → square 4-viewpoint
  byte-exact → E1M1 capstone → measure (expect **−10-20M** ops; the real prize is the build) → commit.
- [ ] **From this rung on, report the TWO numbers** (static frame; static minus the M14-incremental-
  eligible walk/cull share from the p0 split) in every measurement.

---

## Task M13p5: wall pass-2 restructure — per-column [top,bottom] runtime loop [exact]

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
