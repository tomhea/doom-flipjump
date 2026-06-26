"""M13d2b (F5) — the runtime per-ROW TEXTURED span pass `frame.render_planes_spans` (DOOM R_MakeSpans),
byte-exact vs the oracle `reference_model._render_planes_textured`. This is the HARD new control structure
the textured-floor wire-in needs: for each screen row it walks the columns at runtime, GROUPS consecutive
columns that share a visplane (region + plane-height + flat-slice + light) into a horizontal span, and
rasterizes each span through the shared `plane.draw_span` leaf (the u,v DDA re-seeds per span off x1, so the
span BOUNDARIES must match the oracle EXACTLY — the linear DDA is not per-column-exact).

Tested in ISOLATION (no BSP walk / full renderer): a hand-built per-column config over the real 160x100 view
exercises every break condition — region change, ceiling/floor height change, flat change, light change, a
merge across identical columns, single-column spans, and screen-edge spans. The oracle computes the truth
frame from the raw (ceil_hi/floor_lo/col_ch/col_fh/col_lt/col_cf/col_ff); the fj bakes the derived per-column
arrays (cexcl/fstart/ceil_ph/floor_ph/plight/ceilbase/floorbase) + a small combined flat table and runs the
span pass. M13d2c/d wire this into emit_wall_renderer (the slice offsets come from the BSP walk).
"""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.fixedpoint import fixed_div
from doomfj.harness import W
from doomfj.lut_generator import (generate_yslope_lut_fj, generate_zlight_lut_fj,
                                  generate_distscale_lut_fj, generate_xtoviewangle_lut_fj,
                                  generate_trig_idioms_fj)
from doomfj.reference_model import ReferenceModel, ANG90, ANGLE_MASK
from doomfj.texturecompiler import compile_colormap, compile_palette, _texel_table
from doomfj.wad import WadFile

from tests.fj.test_wall_render import _ScreenWithInput

PRESENT_FJ = Path("src/fj/present.fj")
FRAME_FJ = Path("src/fj/frame_render.fj")
PROJECTION_FJ = Path("src/fj/projection.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
PLANE_FJ = Path("src/fj/plane_render.fj")
E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"
COLORMAP_LIGHTS = 32
U = 1 << 16


def _base_scales(rm, viewangle):
    cxfrac = rm.cfg.CENTERX << 16
    ang_b = ((viewangle - ANG90) & ANGLE_MASK) >> rm.angle_shift
    bxs = fixed_div(rm._finecos_idx(ang_b), cxfrac, 8, 4)
    bys = (-fixed_div(rm._finesin_idx(ang_b), cxfrac, 8, 4)) & ANGLE_MASK
    return bxs, bys


def _synthetic_columns(cfg):
    """A per-column visplane config over the real 160x100 view that exercises every span break condition.
    Returns the seven oracle arrays. All ceilings are ABOVE the eye and all floors BELOW it (the DOOM viewing
    invariant -> within a region the planeheight is bijective with the raw height, so grouping on planeheight
    reproduces the oracle's grouping on raw height)."""
    W_ = cfg.VIEW_W
    H_ = cfg.VIEW_H
    ceil_hi = [0] * W_; floor_lo = [0] * W_
    col_ch = [0] * W_; col_fh = [0] * W_; col_lt = [0] * W_
    col_cf = [None] * W_; col_ff = [None] * W_
    # (x_start, ceil_hi, floor_lo, ceil_h, floor_h, light, ceil_flat, floor_flat) — each block flips ONE key
    # vs the previous so spans break on exactly that axis; some blocks repeat to test merging.
    blocks = [
        (0,   18, 70, 128,   0, 192, "FLAT1",   "FLOOR5_2"),   # base
        (28,  18, 70, 128,   0, 192, "FLAT1",   "FLOOR5_2"),   # identical -> ceiling+floor MERGE across 0..39
        (40,  18, 70, 128,   0, 192, "FLAT1",   "CEIL5_1"),    # floor flat change -> floor span breaks at 40
        (62,  18, 70, 120,   0, 192, "FLAT1",   "CEIL5_1"),    # ceiling height change -> ceiling breaks at 62
        (84,  18, 70, 120,   0,  96, "FLAT1",   "CEIL5_1"),    # light change -> both break at 84
        (108, 30, 60, 120,   8,  96, "RROCK18", "CEIL5_1"),    # region bounds + ceil flat + floor height change
        (140, 30, 60, 120,   8,  96, "RROCK18", "CEIL5_1"),    # identical to prev -> merge 108..158
        (159, -1, 70, 120,   8,  96, "RROCK18", "FLOOR5_2"),   # last col: no ceiling, lone floor (1-col span)
    ]
    for i, (xs, chi, flo, ch, fh, lt, cf, ff) in enumerate(blocks):
        xe = blocks[i + 1][0] if i + 1 < len(blocks) else W_
        for x in range(xs, xe):
            ceil_hi[x], floor_lo[x] = chi, flo
            col_ch[x], col_fh[x], col_lt[x] = ch, fh, lt
            col_cf[x], col_ff[x] = cf, ff
    return ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff


def _col_array(label, vals):
    """An 8-nibble-stride per-column array (matches the renderer's col arrays): the first cell carries the
    label, then one `hex.vec 8, <value>` cell per column."""
    cells = [f"{label}: hex.vec 8, {vals[0] & 0xFFFFFFFF}"]
    cells += [f"hex.vec 8, {v & 0xFFFFFFFF}" for v in vals[1:]]
    return "\n".join(cells)


def test_render_planes_spans_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    W_, H_ = cfg.VIEW_W, cfg.VIEW_H
    mw = WadFile.from_path(E1M1_WAD)
    colormap = mw.colormap()

    # a chosen viewpoint (the per-column config is independent of the map geometry)
    viewx, viewy = (800 * U) & 0xFFFFFFFF, (600 * U) & 0xFFFFFFFF
    viewangle = 0x20000000
    viewz = 41 * U
    bxs, bys = _base_scales(rm, viewangle)

    ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff = _synthetic_columns(cfg)

    # the oracle truth frame from the raw per-column config
    want = bytearray(cfg.FB_SIZE)
    rm._render_planes_textured(want, colormap, mw, {}, viewx, viewy, viewangle, viewz,
                               ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff)

    # the combined flat table over the distinct flats this config uses (exact oracle texels -> identical sample)
    names = sorted({n for n in col_cf + col_ff if n})
    combined, offset = [], {}
    for nm in names:
        offset[nm] = len(combined)
        combined += list(rm._flat_texels(mw, nm, {}))
    flat_table = _texel_table("flat", combined, "per_entry", over_align=False)

    # derive the fj per-column arrays (what the BSP walk bakes at the wire-in)
    cexcl = [ch + 1 for ch in ceil_hi]                       # cexcl = ceil_hi + 1 (= min(top, VIEW_H))
    fstart = list(floor_lo)
    ceil_ph = [abs((col_ch[x] << 16) - viewz) for x in range(W_)]
    floor_ph = [abs((col_fh[x] << 16) - viewz) for x in range(W_)]
    ceilbase = [offset[col_cf[x]] for x in range(W_)]
    floorbase = [offset[col_ff[x]] for x in range(W_)]

    yslope = generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H)
    distscale = generate_distscale_lut_fj("distscale", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)
    zlight = generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    cm = compile_colormap("cm", mw, lights=COLORMAP_LIGHTS)
    palette = compile_palette("palette", mw)

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen",
        f"hex.set 8, viewx, {viewx}", f"hex.set 8, viewy, {viewy}",
        f"hex.set 8, viewangle, {viewangle}",
        f"hex.set 8, basexscale, {bxs}", f"hex.set 8, baseyscale, {bys}",
        f"frame.render_planes_spans {cfg.VIEW_W}, {cfg.VIEW_H}",
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        f"span_leaf: plane.draw_span framebuffer, {cfg.VIEW_W}",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "basexscale: hex.vec 8", "baseyscale: hex.vec 8",
        "planeheight: hex.vec 8", "light: hex.vec 2", "flatbase: hex.vec 5",
        "y: hex.vec 2", "x1: hex.vec 8", "x2: hex.vec 8", "span_ret: ;0",
        _col_array("col_cexcl", cexcl), _col_array("col_fstart", fstart),
        _col_array("col_ceil_ph", ceil_ph), _col_array("col_floor_ph", floor_ph),
        _col_array("col_plight", col_lt), _col_array("col_ceilbase", ceilbase),
        _col_array("col_floorbase", floorbase),
        yslope, distscale, xtoviewangle, zlight, finesine, cm, palette, flat_table,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "span_pass.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "span_pass.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(), PROJECTION_FJ.resolve(),
                 FRAME_FJ.resolve(), PLANE_FJ.resolve(), p.resolve()],
                out, memory_width=W, warning_as_errors=True, print_time=False)
    screen = _ScreenWithInput(b"")
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    got = bytes(screen.pixel_indices)
    assert got == bytes(want), "frame.render_planes_spans != oracle _render_planes_textured"
