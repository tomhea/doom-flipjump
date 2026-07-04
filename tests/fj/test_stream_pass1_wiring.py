"""M13pS2c-wiring -- the pass-1 wiring of plane.build_bands into the REAL renderer
(seg_pass1_leaf_body_stream, raster_mode="stream"). Not a full capstone yet (no emit-loop, no deletion
of the old raster) -- this proves the WIRING alone: after a real square-room render, read back
col_ceil_n/col_ceil_bands/col_floor_n/col_floor_bands/col_lit for representative columns and compare
against a Python-computed expected band list (the SAME `_zidx_band_walk` + zrow-grouping the standalone
kernel test already validated, R15/R16), fed with the REAL per-column ph/light/base this scene produces.
"""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import BAND_STRIDE, emit_wall_renderer

from tests.fj.test_wall_render import _ScreenWithInput

PRESENT_FJ = Path("src/fj/present.fj")
FRAME_FJ = Path("src/fj/frame_render.fj")
PROJECTION_FJ = Path("src/fj/projection.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
PLANE_BANDS_FJ = Path("src/fj/plane_bands.fj")
PLANE_FJ = Path("src/fj/plane_render.fj")
ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"

CHECK_COLUMNS = [10, 120]


def _expected_bands(rm, ph, light, base, y0, count):
    rows = list(range(y0, y0 + count))
    zidxs = rm._zidx_band_walk(ph, rows)
    lvl = min(15, light >> 4)
    bands = []
    for z in zidxs:
        zrow = rm.zlight[lvl][z]
        if bands and bands[-1][1] == zrow:
            bands[-1] = (bands[-1][0] + 1, zrow)
        else:
            bands.append((1, zrow))
    return [(c, base, zrow) for c, zrow in bands]


PER_COL_SIZE = 6 + BAND_STRIDE + BAND_STRIDE   # n_ceil, n_floor, lit, cexcl_lo, ceilbase_lo, top_lo, bands


def _dump_code(ci, x):
    """Copy column x's band-list report into framebuffer PIXELS starting at ci*PER_COL_SIZE (a spare
    region of the frame we'll read back via screen.pixel_indices after the run -- InMemoryScreen only
    understands the device command stream, so `stl.output`-based text printing can't coexist with
    `present.update_screen_reg`; encoding the dump as extra framebuffer pixels reuses the ALREADY-
    correct pixel decode path instead of inventing a second one). Must run BEFORE update_screen_reg."""
    base = ci * PER_COL_SIZE
    lines = [
        # direct compile-time-address reads (same idiom as render_planes_spans' `hex.mov 2, cexcl,
        # col_cexcl + 8*x*dw` elsewhere in this file) -- no pointer indirection needed since x is
        # known at emit time.
        f"hex.mov 2, framebuffer + {2 * (base + 0)}*dw, col_ceil_n + 8*{x}*dw",
        f"hex.mov 2, framebuffer + {2 * (base + 1)}*dw, col_floor_n + 8*{x}*dw",
        f"hex.mov 2, framebuffer + {2 * (base + 2)}*dw, col_lit + 8*{x}*dw",
        f"hex.mov 2, framebuffer + {2 * (base + 3)}*dw, col_cexcl + 8*{x}*dw",       # sanity: already-proven field
        f"hex.mov 2, framebuffer + {2 * (base + 4)}*dw, col_ceilbase + 8*{x}*dw",    # sanity: already-proven field
        f"hex.mov 2, framebuffer + {2 * (base + 5)}*dw, col_top + 8*{x}*dw",         # sanity: already-proven field
        f"hex.set w/4, dumpptr, col_ceil_bands + {BAND_STRIDE}*{x}*dw",
    ]
    for k in range(BAND_STRIDE):
        lines += ["hex.read_byte_and_inc dumpbyte, dumpptr",
                  f"hex.mov 2, framebuffer + {2 * (base + 6 + k)}*dw, dumpbyte"]
    lines.append(f"hex.set w/4, dumpptr, col_floor_bands + {BAND_STRIDE}*{x}*dw")
    for k in range(BAND_STRIDE):
        lines += ["hex.read_byte_and_inc dumpbyte, dumpptr",
                  f"hex.mov 2, framebuffer + {2 * (base + 6 + BAND_STRIDE + k)}*dw, dumpbyte"]
    return "\n".join(lines)


def test_stream_pass1_wiring_matches_expected_bands(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(ROOM)
    aw = WadFile.from_path(ASSET)
    scene = build_scene(mw, aw, "MAP01")
    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16

    main = emit_wall_renderer(mw, "MAP01", cfg, asset_wad=aw, over_align=False,
                             floor_mode="flat", wall_mode="W1", raster_mode="stream")
    dump = "\n".join(_dump_code(ci, x) for ci, x in enumerate(CHECK_COLUMNS))
    marker = "present.set_palette palette\npresent.update_screen_reg framebuffer\nstl.loop"
    assert main.count(marker) == 1, "expected marker not found verbatim -- emitter text changed"
    main = main.replace(marker, dump + "\n" + marker, 1)
    main += "\ndumpptr: hex.vec w/4\ndumpbyte: hex.vec 2\n"

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "streamwire.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "streamwire.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), PLANE_BANDS_FJ.resolve(), PLANE_FJ.resolve(),
                 p.resolve()],
                out, memory_width=W, print_time=False)

    # ONE assemble, re-run over several stdin viewpoints (the suite's established pattern). The spawn
    # viewpoint has cexcl=0 at BOTH check columns (walls reach the screen top) -- it exercises ONLY the
    # floor call; the ceiling call takes build_bands' empty early-exit there (a VACUOUS pass for the
    # ceiling wiring, the exact trap that hid the pS2c bidx bug: an isolation experiment that never
    # reaches the write path proves nothing about it, fj-lessons R17). The (24,24)@0x20000000 corner
    # viewpoint (probed host-side) has cexcl>0 AND fstart<VIEW_H at both columns, so BOTH calls write.
    viewpoints = [(spx, spy, sp.angle), (24, 24, 0x20000000)]

    lds, sds, secs = mw.linedefs("MAP01"), mw.sidedefs("MAP01"), mw.sectors("MAP01")
    flatcache = {}
    orig = ReferenceModel._render_planes_flat
    failures = []
    for vx, vy, va in viewpoints:
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        px = bytes(screen.pixel_indices)

        # the REAL per-column (cexcl, fstart, ph_c, ph_f, light, base_c, base_f) this scene's frame
        # produces -- captured DIRECTLY from a real render_wall_frame call (monkeypatching
        # _render_planes_flat to intercept its arguments, R13: don't re-derive the claim/clip formulas,
        # reuse the oracle's own numbers) instead of re-deriving cexcl/fstart from scratch (an earlier
        # version of this test WRONGLY assumed the ceiling/floor windows are always [0,centery)/
        # [centery,100) -- they're not; cexcl/fstart depend on the wall's actual projected top/bottom,
        # which for the square-room spawn (a floor-to-ceiling wall filling the whole column) can be 0).
        captured = {}

        def _capture(self, fb, colormap, asset_wad, flatcache_, viewz_, ceil_hi, floor_lo, col_ch,
                     col_fh, col_lt, col_cf, col_ff):
            captured["args"] = (ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff)
            return orig(self, fb, colormap, asset_wad, flatcache_, viewz_, ceil_hi, floor_lo, col_ch,
                        col_fh, col_lt, col_cf, col_ff)

        ReferenceModel._render_planes_flat = _capture
        try:
            rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                 floor_texturing=False, wall_mode="W1")
        finally:
            ReferenceModel._render_planes_flat = orig
        ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff = captured["args"]

        pss = scene.cmap.subsectors[rm.point_in_subsector(scene.cmap, vx, vy)]
        viewz = rm.view_z(rm._seg_sector(lds, sds, secs, scene.cmap.segs[pss.firstseg]).floor_h)

        for ci, x in enumerate(CHECK_COLUMNS):
            base = ci * PER_COL_SIZE
            n_ceil, n_floor, lit, cexcl_lo, ceilbase_lo, top_lo = (px[base], px[base + 1], px[base + 2],
                                                                  px[base + 3], px[base + 4], px[base + 5])
            ceil_bytes = px[base + 6: base + 6 + n_ceil * 3]
            floor_bytes = px[base + 6 + BAND_STRIDE: base + 6 + BAND_STRIDE + n_floor * 3]
            got_ceil = [tuple(ceil_bytes[i:i + 3]) for i in range(0, len(ceil_bytes), 3)]
            got_floor = [tuple(floor_bytes[i:i + 3]) for i in range(0, len(floor_bytes), 3)]

            cexcl = min(ceil_hi[x] + 1, cfg.VIEW_H) if ceil_hi[x] >= 0 else 0
            fstart = floor_lo[x] if floor_lo[x] < cfg.VIEW_H else cfg.VIEW_H
            ph_c = abs((col_ch[x] << 16) - viewz) if ceil_hi[x] >= 0 else None
            ph_f = abs((col_fh[x] << 16) - viewz) if floor_lo[x] < cfg.VIEW_H else None
            base_c = rm._flat_base(scene.asset_wad, col_cf[x], flatcache) if col_cf[x] else None
            base_f = rm._flat_base(scene.asset_wad, col_ff[x], flatcache) if col_ff[x] else None
            lt = col_lt[x]

            exp_ceil = _expected_bands(rm, ph_c, lt, base_c, 0, cexcl) if ph_c is not None and cexcl > 0 else []
            exp_floor = (_expected_bands(rm, ph_f, lt, base_f, fstart, cfg.VIEW_H - fstart)
                        if ph_f is not None and fstart < cfg.VIEW_H else [])
            vp = f"vp=({vx},{vy},{va:#x})"
            print(f"{vp} col {x}: cexcl={cexcl} fstart={fstart} n_ceil={n_ceil}(want {len(exp_ceil)}) "
                  f"n_floor={n_floor}(want {len(exp_floor)}) lit={lit} cexcl_lo(sanity)={cexcl_lo} "
                  f"ceilbase_lo(sanity)={ceilbase_lo}(want {base_c}) top_lo(sanity)={top_lo}")
            if n_ceil != len(exp_ceil):
                failures.append(f"{vp} col {x}: n_ceil {n_ceil} != expected {len(exp_ceil)} ({exp_ceil})")
            if n_floor != len(exp_floor):
                failures.append(f"{vp} col {x}: n_floor {n_floor} != expected {len(exp_floor)} ({exp_floor})")
            if got_ceil != exp_ceil:
                failures.append(f"{vp} col {x}: ceil bands {got_ceil} != expected {exp_ceil}")
            if got_floor != exp_floor:
                failures.append(f"{vp} col {x}: floor bands {got_floor} != expected {exp_floor}")
    assert not failures, "\n".join(failures)
