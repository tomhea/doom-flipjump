# M13p — Procedural-Floor/Wall Perf Ladder Implementation Plan (462.7M → ≤12M ops/frame, HARD)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking. Read the memory `fj-lessons` file BEFORE writing any fj code.

**Goal (owner-set, HARD):** Ladder the renderer from the measured **462,742,550 ops/frame (0.605 fps
@280M)** down to **≤ 12,000,000 ops/frame** — the static E1M1 spawn frame as reported by
`scripts/measure_frame.py` (ops convention unchanged from the 462.7M baseline). Procedural
screen-space color (floors first, then walls) buys the first ~10×; the last ~3× is a **hard per-stage
budget ledger** (below) built on the owner's v4 directive — **we control flipjump 1.5.1's ScreenIO
device** — which turns pixel delivery into a device RUN stream: the column-stream raster (pS,
~1,300-2,000 RLE runs instead of 16,000 register writes), the until-full walk/geometry (pG), and —
now only as insurance — the fidelity valves (pV). Still a ladder: **each rung measured, non-empty,
shippable.**

**Architecture:** The pipeline stays (BSP walk → pass-1 geometry → raster). Each rung swaps ONE kernel
or bakes ONE table cheaper, behind an emitter *mode flag* mirrored in the oracle, so the textured path
stays in-tree and testable the whole time. De-risk order per rung: oracle change → PNG → owner look-OK
→ fj mirror → byte-exact gate → **measure ops/frame** → commit. At pS the two raster passes (wall
pass-2 + plane pass) are replaced by ONE per-column run-stream emitter feeding the device — the only
structural rewrite, itself laddered (protocol → prototype → ship). The v3 composite-fb design (pC) is
retained verbatim as the fallback if the device protocol is rejected.

**Tech stack:** Python emitter (`src/doomfj/wall_renderer.py`) + fj macros (`src/fj/plane_render.fj`,
`src/fj/frame_render.fj`), flipjump 1.5.1 assembler/runner, pytest gates, `term.op_counter` measurement.

## Global constraints (binding, from the owner / prior sessions)

- **Branch:** all work stacks on `m13opt3-early-out` (@ `8d175d2`). **Do NOT merge to main** until the
  endgame rung (M13p8) — owner policy 2026-07-03.
- **Owner direction (verbatim intent):** can sacrifice looks; wants easy-to-implement patches that each
  give a non-empty improvement. NOT one big-bang rewrite.
- **Owner directives (2026-07-04):** (a) the **ScreenIO device in flipjump 1.5.1 is OURS to extend**
  — new commands, IO-flip output paths ("write_pixel", "write_column", stream modes), and hot tables
  regenerated to flip IO+0/1 instead of xoring a result register — "if it saves time, definitely do
  that, with most fj ops saved"; (b) **16-color mode is pre-approved** (turns out unneeded under RLE
  — kept as a valve); (c) **row-dup floors only if the result does not look vertically stretched**
  (the PNG gate decides).
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

## ★ THE 12M LEDGER v4 (the hard budget; every endgame rung is accepted against its line)

`12M ÷ 16,000 px ≈ 750 ops/pixel, EVERYTHING included.` Five structural facts set the economics —
F1/F3 changed completely on the owner's 2026-07-04 device directive:

- **F5 — THE DEVICE IS PROGRAMMABLE (the v4 game-changer).** We control flipjump 1.5.1's ScreenIO:
  new commands may be added, and pixels may leave the program as IO output bits (flipping IO/IO+1)
  instead of framebuffer register writes. The device decodes host-side in Python — **zero fj ops**.
- **F1′ — the write economics under F5.** Copying a RUNTIME byte to a register/fb costs ~284 (two
  nibble dispatches) — that was v3's 4.55M floor. But OUTPUTTING a compile-time-KNOWN value costs
  ~1 op/bit, and every dispatch-table cell knows its value at bake time. So the hot tables are
  regenerated as **EMIT tables** (the handler flips its baked byte into IO instead of xoring a
  result register — the owner's instruction verbatim; `generate_dispatch_table_fj`'s per-entry
  handler with a different body, lut_generator.py:321). A runtime color OUTPUT ≈ one dispatch
  (~100-150); with a device-side RUN command (`[count][color]`), pixel cost becomes **per RUN, not
  per PIXEL** — and this frame is naturally run-structured (light bands = row-runs per column, W1
  walls = one run per column): 16,000 pixels ≈ **~1,300-2,000 runs**. The v3 write floor DISSOLVES.
- **F2 — present is FREE** (unchanged mechanism, extended): the device already DMA-reads
  (present.fj:42); under F5 it additionally decodes the run stream into its own buffer and presents.
- **F3 — RESOLVED by F5.** With no fj framebuffer at all, the known-zero write convention and the
  M14 dirty-frame liability (v3's +~4.5M/frame) disappear — every frame streams complete and the
  device rebuilds its buffer. Nothing to decide at M14.
- **F4 — block-FP light bands still forced** (unchanged): exact per-row zrow muls (11.5k each) are
  unaffordable at any count the frame needs; the band machinery = one reciprocal per visplane +
  threshold walks over the baked `yslope` — ONE [re-bless], PNG-gated (band boundaries may shift
  ≤1 row; rows keep distinct distances — not the rejected Phase-2 vertical replication).

### The ledger v4 (static E1M1 spawn frame; ops convention unchanged)

| Line | Stage | Budget | Basis |
| --- | --- | --- | --- |
| LS1 | column-stream raster: per-run `byte.emit`+`cm.emit` + clip/advance logic (~1.3-2k runs × ~600-900) | ≤ 2.20M | F1′/F5 |
| LS2 | lit-band machinery (1 block-FP recip + yslope threshold walk + band lists, ~20-30 visplanes) | ≤ 0.80M | F4 |
| L5 | pass-1 geometry, until-full (x_range + projection + claim) | ≤ 2.00M | pG |
| L6 | BSP walk, until-full + abort (narrowed muls) | ≤ 1.20M | pG |
| L7 | init + input parse + stream/protocol residue | ≤ 0.50M | F2 |
| L8 | slack / headroom | 5.30M | — |
| — | **TOTAL** | **12.00M** | — |

**The headroom is the point:** v3 closed at 12.00M with 0.45M slack and leaned on the valves; v4
budgets ~6.7M of work against the 12M line — a ~1.8× estimate-error cushion. The valves become
INSURANCE, not plan: **16-color is owner-approved but likely unnecessary** (under RLE the color cost
is per-run, so the full 256-palette look survives); **row-dup only if it looks unstretched** (owner
constraint, PNG gate); 80×50 is almost certainly moot.

**[M14] upside (not counted):** the dispatch-incremental walk + affine maintenance replaces L5+L6
(~3.2M) with ~1-2M while walking — on top of the 5.3M slack.

### Expected ladder v4 (estimates; re-anchor on the measured number at every rung)

| Rung | What | Tag | Frame after (est/MEASURED) | fps @280M |
| --- | --- | --- | --- | --- |
| — | baseline (⚠ CORRECTED 2026-07-04, was recorded 462.7M — stale) | — | **453,235,929** | 0.617 |
| M13p0 | measure split + stub split + until-full counts + PNG bake-off → owner picks | none | 453.2M (unchanged) | — |
| M13p1 | fj flat-colored floors (`draw_span_flat`) — **DONE, MEASURED 2026-07-04, byte-exact vs `6d5baf9e`, two independent measurements agree (capstone test + `measure_frame.py`)** | [exact vs flat goldens] | **264,777,325** (est. was ~225-240M — came in ~10-17% higher; span 23.6M→20.0M words) | **1.06** |
| M13p4a | tiny 1×1/1×16 per-seg wall textures — table shrunk — **DONE, MEASURED 2026-07-04, byte-exact vs new W1/W2 goldens, both modes built alongside floor_mode=flat (owner pick still pending, ships neither as default yet)** | [re-bless vs new W1/W2 goldens] | wall_mode ALONE (textured floors): W1 453,906,555 / W2 453,886,700 (barely moved, as predicted — ops win is @ ripple only). **Combined with p1's flat floors: W1 265,676,539 / W2 265,654,364** (both ≈ +0.34% over p1 alone — negligible). **Assemble: 605s → 78.7-78.8s, a 7.7× speedup** (beat the ~1-2min estimate) | ~1.05 (combined) |
| M13p2 | pattern floors (only if the owner picks a pattern) | [re-bless, PNG-gated] | +~5-10M | ~1.2 |
| (M13p3a-c) | OPTIONAL interim floor squeezes — only if pS stretches over sessions | [exact] | ~205-220M | ~1.3 |
| M13pS0 | ScreenIO column-stream protocol: owner sign-off, device impl + tests, EMIT tables | host+device, no frame change | — | — |
| M13pS1 | stream prototype: one column end-to-end, per-run cost MEASURED | none (scratch) | — | — |
| M13pS2 | THE COLUMN-STREAM COMPOSITE — fb, pass-2 unroll (~16M words) and ALL plane machinery DELETED | [re-bless once: block-FP bands, PNG-gated] | **~110-140M** | ~2.2 |
| M13pG1 | walk+pass-1 FULL-ABORT (stop the walk when all columns claimed) | [exact] | −(p0-measured post-full share) | — |
| M13pG2-5 | until-full geometry crush to L5-L7 (narrow muls, cheap x_range, residue) | mixed | **~8-14M** | ~23 |
| M13pV | INSURANCE only, if >12M: row-dup (unstretched-looking) / 16-color (approved) / 80×50 | [re-bless, owner-gated] | **≤ 12.0M** | **≥ 23** |
| M13p8 | flip defaults, ship the flipjump device change, re-bless, merge to main | — | — | — |

**Where the convergence claim lives (v4):** LS1's per-run cost is MEASURED at pS1 before pS2 is
built; LS2's band machinery is measured standalone at pS0/pS1; L5+L6 are sized by p0's host-side
until-full counts before any fj geometry work (pG1 collapses walk/geometry to "work done before the
screen fills"); L7 is F2 plus small change. With **5.3M of slack**, any single line missing by 2-3×
is absorbed without touching a valve — **the ladder cannot silently stall, and the valves are
insurance, not plan.**

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

## Task M13p3 (OPTIONAL interim): cheap floor squeezes — shippable wins while pS is prototyped

After p1/p2 the floor pass ≈ 65M: classify walk ~23M + span setup ~25M + pixels ~20M. The a-c
squeezes bottom out around ~45M (the runtime-pointer write pins the pixels at ~1.9k each) and are
ALL deleted by M13pS2 — do them only as interim shippable wins if pS0/pS1 stretch over multiple
sessions; skipping straight from p1/p4a to pS is the faster path to 12M. **Exception: p3b's
sector-key machinery is NOT throwaway — the same baked per-column key is how the pS2 emitter selects
a column's visplane band lists; building it here de-risks pS.**

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

*(The former p3d "cell pass" is superseded by **Task M13pS** below — under the v4 device directive
the raster is a per-column RUN STREAM, no cell unroll at all; the v3 cell-pass design survives only
as the M13pC fallback.)*

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
  for pS/pG.
- [ ] **The write-only wall raster is NOT a separate rung anymore** — with a 1×1 texel the wall lit
  color is COLUMN-CONSTANT (one `cm.apply` per ~160 claimed columns, computed in
  `column_render_params`, stored as a 2-nibble `col_lit`); the per-pixel raster that consumes it is
  **M13pS2** (the column-stream composite; pC3 in the fallback). p4a only needs to additionally store `col_lit` (and, for W2, the
  16 band texels' lit variants) so pS2 can consume it.
- [ ] **From p4a on, report the TWO numbers** (static frame; static minus the M14-incremental-
  eligible walk/cull share from the p0 stub split) in every measurement.

**Files:** `src/doomfj/reference_model.py` (`wall_mode` kwarg — the tiny-canvas rule VERBATIM from
the p0 pick), `src/doomfj/wall_renderer.py` (`wall_mode`; tiny-canvas combined table; the `col_lit`
store), `src/doomfj/build.py` (pass-through). Tests: `tests/host/test_wall_frame.py` (+wall-mode
goldens, blessed after the p0 PNG), fj square 4-viewpoint + E1M1 capstone.

---

## Task M13pS: THE COLUMN-STREAM COMPOSITE — pixels leave as a device RUN stream (LS1+LS2)

The v4 pixel engine (supersedes the v3 composite fb raster, kept below as fallback). Everything the
frame shows is emitted as a **column-major RLE run stream** to a new ScreenIO command; the device
(host-side Python — zero fj ops) decodes runs into its buffer and presents. DELETED outright at pS2:
the `hex.vec 2` framebuffer, the 16K pass-2 unroll (~16M words per the M12 bisect),
`render_planes_spans`/`plane_col`/`draw_span_flat`(/`_pat`) — the program shrinks by ~16M+ words on
top of p4a's table deletion (span↓, @↓, assemble↓), and NO 16k-cell unroll replaces it: the emitter
is a 160-column loop.

### The protocol (SIGNED OFF by the owner, 2026-07-04 — ours to keep evolving)

⚠ **This protocol is not frozen.** The owner's explicit standing permission: "you determine this
protocol — if you need to modify it in the future to meet your needs, it's something that you can
and are allowed to do." Treat `init_stream_mode` below as versioned, not sacred — if pS0/pS1
prototyping finds a cheaper shape, change it and update this section + the device + the tests
together (same rung, one gate).

- `0x07` **BEGIN_FRAME_STREAM** — the device resets its cursor to (column 0, row 0).
- Then, for each of the 160 columns in order: runs of `[count:1 byte][color:1 byte]`; the counts sum
  to exactly H=100 per column.
- **Flush granularity is a CONFIG VALUE, sent once at init** (owner, 2026-07-04): `0x01`
  `init_screen` (present.fj:14) gains one more byte, `flush_mode` — `0` = **flush the physical
  display once per FULL FRAME** (after column 159 fills; **the default**), `1` = flush once per
  COLUMN (after each column fills — useful for debugging/streaming a partial frame, not needed for
  the ops target). fj always emits the same 160-column stream regardless of `flush_mode` — the byte
  only tells the DEVICE when to blit its internal buffer to the actual screen; **ops/frame is
  identical either way** (no per-column emit cost changes), so the ladder's numbers don't depend on
  this choice. Default per-frame per the owner's instruction.
- Colors stay 8-bit/256-palette: under RLE the color cost is per-run, so 16-color (approved) is not
  needed for ops — it remains a pV valve only.
- Future, NOT built now (M16 sprites/HUD): the owner's `write_pixel` suggestion
  (`0x08 [x:1][y:1][color:1]`) as a sparse overlay on the streamed frame.

### fj-side machinery (pS0) — the owner's "IO+0/1 flips instead of xoring to a result variable"

**DONE, MEASURED 2026-07-04** (commit follows this rung):
1. **EMIT tables**: a new `generate_emit_dispatch_table_fj` (`src/doomfj/lut_generator.py`, alongside
   `generate_dispatch_table_fj` rather than an extra mode on it — the emit case has no `dst`/`.res` at
   all, a genuinely different shape) — the SAME per-entry dispatch-CODE structure, but each entry's
   handler is 8 `stl.output_bit` calls (the compile-time-constant primitive `stl.output_char` already
   uses internally) + 1 jump-to-clean, instead of wflipping the value into a kept-zero result register.
   No `dst`, nothing to read out — the byte already left as IO.
   - `cm.emit idx` — built from the SAME `colormap_values(...)` list `compile_colormap`'s `.apply`
     table uses (no drift), just fed through the emit generator. **MEASURED: 329.5 ops/call** (real
     8,192-entry E1M1 colormap) — est. was ~150-400, landed mid-range. **2.07× cheaper than the OLD
     cm.apply(399)+xor_zero(284)=683 combo**, since there's no register write to pay for afterward.
   - `byte.emit v` — a 256-entry IDENTITY table (`values=range(256)`) for run counts/raw bytes.
     **MEASURED: 283.6 ops/call** — est. was ~100-150, landed higher (dispatch overhead dominates the
     handler-body difference more than expected). Not concerning: LS1's per-run budget (~600-900,
     TWO emits + narrow clip/advance) still holds — 283.6+329.5≈613 is within range before the
     clip/advance ops are even added.
   - Verified end-to-end (not just eyeballed): a smoke assemble+run confirmed a 4-entry identity table
     dispatches idx→byte correctly (`b"ABCD"`), before committing to the cost measurement.
2. **The device side**: `tests/fj/stream_screen.py::StreamScreen(InMemoryScreen)` — an in-repo
   subclass (per the plan: "tests already pass `io_device=` explicitly, so byte-exact gates need NO
   package edit"). Decodes the EXTENDED 9-byte `0x01` (the stock 8 bytes + `flush_mode`) and the new
   `0x07` `BEGIN_FRAME_STREAM`, which puts the device into a stateful column-major run-stream mode —
   raw `[count][color]` byte pairs with NO per-run command-byte framing (the device knows the total
   pixel count `width*height` from init, so the LAST run naturally completes the frame; no end
   marker needed). `flush_mode=0` presents once after the whole stream (the shipped default);
   `flush_mode=1` presents once per completed column (100-pixel boundary) — a debug aid, same fj op
   cost either way (flush_mode only changes when the DEVICE blits, never what fj emits). 6 pure-Python
   unit tests (`tests/fj/test_stream_screen.py`, no fj assembly, feeding synthetic byte streams via
   `write_bit`) plus 2 fj-level integration tests (the SAME 3-run 2×3 grid emitted by a real
   `present.init_screen_stream`/`present.begin_frame_stream`/`byte.emit` program, decoded by
   `StreamScreen` — both `flush_mode` values) — 8/8 pass, closing the loop end-to-end (fj emission →
   device decode). Upstream the command into the owner's flipjump 1.5.1 before M13p8; package diff
   stays in-repo (`tests/fj/stream_screen.py`) until then.
3. **`present.fj` additions (ADDITIVE ONLY):** `present.init_screen_stream flush_mode` (9-byte 0x01)
   and `present.begin_frame_stream` (bare 0x07) — the EXISTING `present.init_screen`/
   `update_screen*` macros are byte-identical, untouched; every other test + `build_doom` keeps using
   the stock 8-byte init + the stock `InMemoryScreen`. Verified the exact wire bytes match
   (`01<W><H><BPP><NCOLORS><flush_mode>` then `07`) before writing any device code.

### The emitter (pS2) — per column x, unrolled ×160 (compile-time col-array addresses, small bodies)

Read `col_cexcl / col_fstart / col_lit / col_key` (pass-1 outputs). Emit three windows:
1. **CEILING `[0, cexcl)`**: walk the column's ceiling-visplane BAND LIST (from LS2 — zidx is
   monotone in y, so ~≤14 runs): per band overlapping the window,
   `byte.emit (min(band_end, cexcl) − cur)` then `cm.emit (band_zrow, base)`.
2. **WALL `[cexcl, fstart)`**: ONE run — `byte.emit (fstart − cexcl)` + `cm.emit` of `col_lit`'s
   index (W1). W2's ≤16 vertical bands reuse the SAME band-walk shape (costed: ~+1.5-2M — the
   bake-off pick decides whether it fits LS1).
3. **FLOOR `[fstart, 100)`**: the floor-visplane band list, as (1).
Per column ≈ ~5-12 runs × ~600-900 (two emits + narrow clip/advance ops) ≈ ~5-8k ⇒ **LS1 ≈
1.0-1.6M**. The band lists come from the SAME lit-band machinery as v3 (one block-FP reciprocal per
visplane — `slopediv_recip_table` machinery — + a threshold walk over the baked monotone `yslope`,
~25k per visplane × ~20-30 ⇒ **LS2 ≈ 0.5-0.8M**; the F4 [re-bless], PNG-gated).

### Sub-rungs (each gated)

- [x] **pS0 — protocol + device + tables (ships nothing visible). DONE, MEASURED 2026-07-04.**
  `generate_emit_dispatch_table_fj` (own function, not a mode flag — see above) + `StreamScreen`
  device subclass (`tests/fj/stream_screen.py`) + `present.init_screen_stream`/
  `present.begin_frame_stream` (additive, `present.fj`) + 6 pure-Python decode tests + 2 fj-level
  integration tests (known 3-run column, both flush_mode values) — all 8 pass. MEASURED:
  `byte.emit` 283.6 ops/call, `cm.emit` 329.5 ops/call (2.07× cheaper than the old cm.apply+xor_zero
  combo). Nothing visible ships yet (no renderer wiring) — this rung only proves the mechanism.
- [ ] **pS1 — one-column prototype (scratch).** A synthetic column (fixed cexcl/fstart/band list)
  through the REAL emitter body; byte-exact vs a hand-computed column; MEASURE per-run and
  per-column cost → appendix. **Gate: LS1's line must hold here, before pS2 is built.**
- [ ] **pS2 — the composite stream ships.** Wire the 160-column emitter after pass-1; DELETE fb +
  pass-2 + all plane machinery; oracle re-expressed via the same recip+threshold band arithmetic;
  **re-bless the flat goldens once** (F4, PNG-gated). Gates: square 4-viewpoint + E1M1 capstone,
  byte-exact = the DEVICE's decoded grid equals the oracle frame. Measure (expect **~110-140M**;
  LS1+LS2 now real); record the new span/assemble (expect big drops); commit.

---

## Task M13pC (FALLBACK — build ONLY if the pS protocol is rejected): the v3 composite fb raster

*(Retained verbatim from plan v3; its L1-L4 ledger references are the v3 ledger — see `18330ca`.
If the owner declines device-side RLE decoding, this is the no-device-change path to ~12-14M with
the v3 valves. Do NOT build both.)*

The v3 pixel engine. Replaces BOTH the wall pass-2 (16K `pixel_tramp`+`compare_y` trampoline) and
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

After pS2 the frame ≈ the stream raster (LS1+LS2, ~2-3M) + the ENTIRE old wall/geometry lump minus
pass-2. **p0's split is now MEASURED (E1M1 spawn, not an estimate): pass-1 total = 127.5M (28.1% of
the 453.2M frame), split into walk skeleton 14.9M, wall_x_range+cull-only bulk ~0.1M (tiny — the
affine back-face cull already did its job), and — the big surprise — projection+claim residue =
112.5M (24.8% of the WHOLE frame, 88% of pass-1).** This campaign crushes the lump to L5+L6+L7 ≈
3.7M, landing the frame at **~8-14M — the 12M gate is expected to CLOSE here** (pV is insurance).
Two structural insights, ONE confirmed by the numbers above and one not yet:
1. **CONFIRMED (measured):** the dominant pass-1 cost is NOT the walk — it's the per-seg projection
   math (`wall_setup`/`wall_scale_setup`/`wall_offset`) and the per-column claim loop
   (`column_render_params` + `store_col_field` writes) for the ~26-ish segs/many columns that survive
   the cull. **pG3 (below) is therefore the priority rung, not pG1/pG2** — re-order execution
   accordingly (measure pG3's win FIRST after landing it; do pG1/pG2 regardless since they still gate
   the [M14] steady-state, but they are secondary at the raw-ops level this session).
2. **Still to confirm (Step 3c's host-side counts, not yet cross-checked against THIS fj measurement):**
   front-to-back walk + the `full` flag mean all NODE-VISIT cost after the screen fills is pure waste
   — Phase 1a already frets SEGS post-full, but the WALK (node side tests, subsector dispatch) runs to
   completion today. Step 3c's host-side counts (32-87% of subsectors post-full, viewpoint-dependent)
   size pG1's win; they have NOT yet been cross-checked against a `segstub`-with-`full`-abort fj
   measurement (that IS pG1's own gate, done when pG1 lands).

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
- [ ] Measure + commit each; record every SKIP with its number. **Exit criterion: frame ≤ 12.0M
  (expected ~8-14M) with L5/L6/L7 each at/below its line at ALL THREE p0 viewpoints; if >12M, enter
  pV with the overshoot named per line.**

**Explicitly deferred to M14 (unchanged owner decision):** the dispatch-incremental walk + affine
maintenance. Post-pG they become pure headroom (~L5+L6 → ~1-2M while walking) — the 12M static claim
does NOT depend on them.

---

## Task M13pV: the valves — INSURANCE ONLY (entered only if pG exits > 12.0M)

Under the v4 ledger (5.3M slack) these should not fire; they stay fully specified so an overshoot
has a named, sized answer. Each is an oracle mode + PNG gate + re-bless.

- [ ] **pV1 — row-dup floors [re-bless, PNG-gated].** Halve the band-walk rows and emit each floor
  run's count doubled over row PAIRS (in the run stream this is nearly free to express — counts just
  come from a half-resolution band walk). **⚠ Owner constraint (2026-07-04, verbatim intent): only
  if it does NOT look vertically stretched** — the PNG bake-off decides; if it reads stretched,
  skip to pV2. Saves ~half of LS2 + a slice of LS1 ≈ **−0.5-1.0M** (less than v3 promised — the
  stream already collapsed per-pixel cost, so there is less for row-dup to save).
- [ ] **pV2 — 16-color mode [re-bless; owner APPROVED 2026-07-04].** Under RLE this no longer
  halves a 4.55M write bill (colors are per-run) — it saves only ~a nibble per color emit,
  **≈ −0.1-0.3M**, at a big look cost. Approved but demoted: use only if pV1 fell short AND the
  overshoot is small. (Its v3 rationale — halving fb writes — died with the fb.)
- [ ] **pV3 — 80×50 half-resolution [re-bless + fresh owner permission].** Still the biggest
  hammer: halves the columns (LS1, L5's per-column work) and the band rows (LS2) ⇒ **≈ −1.5-2.5M**
  plus geometry ripple. Most invasive (cfg + every LUT + every golden). Only for a large overshoot.
- [ ] Orthogonal, no re-bless: render-1-of-N tics — an M14 fps multiplier, does NOT reduce
  ops/frame; listed for completeness only.

*(Note the inversion vs v3: the stream design flipped the valve order's value — pV1/pV3 now save
run-STRUCTURE work, not writes, and pV2 barely matters. If pG somehow exits far above 12M, the
first response is to re-measure LS1/L5/L6 against their lines, not to burn look.)*

---

## Task M13p8: endgame — flip defaults, re-bless the shipped goldens, merge to main

- [ ] Flip `build_doom` defaults to the owner-chosen `floor_mode`/`wall_mode` (+ any pV valves).
- [ ] **Ship the ScreenIO change:** upstream the column-stream command into flipjump 1.5.1 (owner's
  package) so the real viewer decodes it; pin the version; keep the in-repo subclass as the test
  device and the diff under `patches/`.
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
| baseline full frame (as recorded pre-p0) | 462,742,550 | pre-p0 (2026-07-03) |
| ⚠ **CORRECTED baseline** — re-measured via `scripts/measure_frame.py` AND independently confirmed by the pre-existing golden capstone test (`test_e1m1_textured_planes_full_frame_byte_exact_and_golden`, which also PASSED byte-exact vs `3f0133d9` and printed the identical number itself — two independent code paths agreeing rules out a harness bug) | **453,235,929** (span 23,599,940 words) | p0, 2026-07-04. The 462,742,550 figure was stale (~2.1% off), likely from the lost pre-M13p0 scratchpad script; **453.2M is the true current baseline** — every ratio/percentage elsewhere in this plan is computed relative to 462.7M and is only ~2% optimistic as a result; re-anchor the ledger/ladder tables' absolute numbers to 453.2M when next fully revised, but do not re-derive the qualitative conclusions (they're insensitive to a 2% shift). |
| **RAW measured (E1M1 spawn, viewpoint (-416,256,0), all sequential, no contention):** full 453,235,929 · `--ablate planes` 150,432,868 · `--ablate planes,pass2` 127,484,005 · `--ablate planes,pass2,pass1` 14,747 · `--ablate planes,pass2,segstub` 14,906,830 · `--ablate planes,pass2,xrstub` 15,012,072 | measured | p0, 2026-07-04 |
| ⚠ correction (mechanics validation, square room): `segstub`/`xrstub` ALONE (not combined with `planes,pass2`) inflate wildly (137.97M/137.98M vs 123.1M baseline) — the plane pass renders the WHOLE screen as floor when `col_fstart` stays 0 (garbage init). Always combine stubs with `planes,pass2`. | fixed in `scripts/measure_frame.py` usage | p0 |
| **DERIVED SPLIT (E1M1 spawn, % of the 453.2M frame):** floor pass (planes delta) **302,803,061 (66.8%)** · wall pass-2 raster (pass2 delta) **22,948,863 (5.1%)** · pass-1 total = geometry+walk (pass1 delta) **127,469,258 (28.1%)**, of which: walk skeleton (segstub) **14,906,830 (3.3%)**, wall_x_range+cull-only bulk (xrstub−segstub) **105,242 (0.02%, tiny)**, and **pass-1 projection+claim residue (pass1−xrstub) = 112,457,186 (24.8% of the WHOLE frame, 88% of pass-1)**. ★ **Finding not anticipated by the v3/v4 pG task write-up:** the walk itself is cheap; the dominant pass-1 cost is the per-seg PROJECTION math (wall_setup/wall_scale_setup/wall_offset) + per-column CLAIM loop (column_render_params + store_col_field writes) for the ~26-troops-of-160-claimed segs that survive the cull — **8× the walk's own cost**. This re-orders pG's priority: pG3 (projection+claim crush) matters far more than pG1/pG2 (walk abort/narrowing) at the OPS level, though pG1 still matters most for the [M14]-steady-state share (post-full node visits are pure waste regardless of their per-node cost). | measured + derived, p0, 2026-07-04 | |
| Sequential timing (no contention): 6 runs × ~7-11 min each, ~63 min wall-clock total, vs the EARLIER parallel attempt that ran 100+ min with ZERO completions (disk queue length 188, %Disk Time 12341% — confirmed I/O thrash from 6 concurrent large `.fjm` writes). **Lesson: never run more than one E1M1 heavy build at a time on this machine.** | measured, p0, 2026-07-04 | |
| **until-full counts (E1M1, host-side, step 3c, 3 viewpoints):** spawn 682 subsectors/463 until-full (32.1% post-full), 575 segs visited/432 until-full (24.9% post-full), 160 pass x_range/116 until-full · rot45: 205/682 until-full (69.9% post-full), 306/575 segs (46.8% post-full) · othersector: 212/682 (68.9% post-full), **only 74/575 segs visited until-full (87.1% post-full!)**. Confirms pG1 full-abort is a large, viewpoint-dependent win — worst case (othersector) wastes work on 501 of 575 segs. | measured | p0, 2026-07-04 |
| pS0: `byte.emit` / `cm.emit` standalone cost | **MEASURED (`scratchpad/measure_emit.py`): byte.emit 283.6 ops/call (256-entry identity table), cm.emit 329.5 ops/call (real 8,192-entry E1M1 colormap)** — both landed higher than the ~100-150/~150-400 estimates individually, but the SUM (613) is still within the ~600-900 per-run LS1 budget before clip/advance ops; cm.emit alone is 2.07× cheaper than the old cm.apply(399)+xor_zero(284)=683 combo | pS0, 2026-07-04 |
| pS0: protocol signed by owner (auto-present? counts encoding?) | **SIGNED 2026-07-04**: `flush_mode` config byte in `init_screen`, default per-frame; owner: protocol is ours to keep evolving | p0 |
| pS0: mechanism proven end-to-end | **8/8 tests pass** (6 pure-Python `StreamScreen` decode tests, no fj; 2 fj-level integration tests emitting a known 3-run column via real `present.init_screen_stream`/`begin_frame_stream`/`byte.emit`, both flush_mode values) — `tests/fj/test_stream_screen.py` | pS0, 2026-07-04 |
| pS1: per-run + per-column emitter cost; band machinery standalone | | pS1 |
| (fallback only) pC1: per-cell cost, variant A vs C; patched-chain idiom | | pC1 |
| owner picks (floor / wall / #9a+#11 bless) | *bake-off PNGs rendered, awaiting owner pick* | p0, 2026-07-04 |
| #9a+#11 bless diff (measured, not just re-quoting the commit messages): square 0/16000 px changed (0.0%, confirms axis-aligned segs ⇒ affine==exact divide, as `d383016` claimed); E1M1 spawn 1,049/16,000 px changed (6.56%), max raw palette-index delta 246, mean delta 23.16 (raw index deltas are NOT a perceptual distance — palette indices are categorical; the diff-highlight PNG is the real evidence) | measured | p0, 2026-07-04 |
| p1 flat floors: 453,235,929 → **264,777,325** (41.6% cut, span 23.6M→20.0M words); cross-validated by the E1M1 capstone test AND `measure_frame.py` independently, identical numbers | measured | p1, 2026-07-04 |
| p4a wall_mode alone (textured floors, isolating the wall change): W1 **453,906,555**, W2 **453,886,700** (both ~+0.15-0.17% over the 453.2M textured baseline — negligible, ops win is @ ripple only, as predicted) | measured | p4a, 2026-07-04 |
| p4a COMBINED with p1 (floor_mode=flat + wall_mode): W1 **265,676,539** (78.7s assemble), W2 **265,654,364** (78.8s assemble) — both ≈+0.34% over p1 alone. **Assemble 605s → 78.7-78.8s = 7.7× faster**, beating the ~1-2min estimate | measured | p4a, 2026-07-04 |
| p4a span: textured-floor+W1 20,145,938 words / +W2 20,172,470 words (vs textured-floor+textured-wall 23,599,940 — a ~3.45-3.5M word drop, matching the ~3.5M estimate almost exactly) | measured | p4a, 2026-07-04 |
| p4a byte-exactness: both W1 and W2 pass square (4 viewpoints) + E1M1 capstone (4 viewpoints) vs NEW goldens in `tests/host/test_wall_frame.py` + `tests/fj/test_floor_planes_fj.py` — hashes cross-validated against the M13p0 bake-off's independent preview (exact match, zero drift) | measured | p4a, 2026-07-04 |
| owner's W1-vs-W2 pick: still pending — both built as parallel infra, neither is the shipped default yet (stays "textured" until M13p8) | pending | p4a |
| … | | |

## Self-review notes (plan-time)

- The M13p1 fj code is written against the CURRENT `draw_span`/`render_planes_spans` register contract
  (verified in-tree at `8d175d2`); `flatbase` reuse at 2 nibbles inside a 5-nibble field keeps
  `plane_col`'s `cmp 5` exact.
- p3b's key-walk is byte-exact ONLY for flat/pattern modes — the emitter must keep the 4-field compare
  for `floor_mode="textured"` (encoded in the task).
- Rungs p2/p4a/pV cannot carry final code before the owner's p0 pick — each instead carries the exact
  candidate formulas (P1-P3/W1-W2, specified to the texel) and the fixed implementation shape, so the
  pick drops in verbatim. The other deliberate late-bindings: the pS0 protocol sign-off (the owner
  owns the device) and pS1's measured per-run cost — both bound by an explicit gate, not a
  placeholder.
- Estimates use isolated-kernel op costs, which the findings doc shows UNDERESTIMATE full-renderer
  cost (~2.5× @ gap) — hence every rung re-anchors on `measure_frame.py`, and no later rung's
  decision rule depends on an estimate alone.

## Adversarial gap review (v2 pass 2026-07-03 G1-G10; v3 pass 2026-07-03 G11-G13; v4 pass 2026-07-04 G14 — all corrections folded into the tasks above)

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
| G14 | **v3 optimized inside a wrong constraint** (v4 pass, on the owner's device directive): the 284/px write floor exists only because pixels were copied as runtime values into an fj framebuffer — but the ScreenIO device is OURS to extend, dispatch-table cells can OUTPUT their baked bytes for ~1 op/bit, and a device RUN command makes cost per-run (~1.3-2k runs) instead of per-pixel (16k). F1 dissolved, F3 (and its M14 dirty-frame liability) dissolved with the fb itself, the 16k-cell unroll became unnecessary, and the ledger gained 5.3M of slack. | constraint | v4: **F5/F1′** in the ledger; **pS** (protocol sign-off → EMIT tables → one-column prototype → composite stream) replaces pC, which is retained as the no-device-change fallback; pV demoted to insurance with pV2's rationale re-derived (it barely matters under RLE). |
