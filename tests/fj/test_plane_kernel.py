"""M13c2 (F5) — the FLAT-COLORED floor/ceiling plane pixel in FlipJump (src/fj/plane_render.fj
`plane.draw_pixel`), byte-exact vs the H5 oracle (reference_model._plane_pixel). The distance-light
spine of the visplane raster: distance = FixedMul(planeheight, yslope[y]); zidx = min(127,
distance>>20); lvl = light>>4; zrow = zlight[lvl*128+zidx]; lit = colormap[zrow][pbase]. Driven over a
spread of (planeheight, light, pbase, y) — near/far/clamp distances, several light levels, the horizon
row and the screen edges — twice each (R5 #8), compared to the oracle. M13c3 wires this kernel into
emit_wall_renderer (replacing render_background_reg).
"""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_yslope_lut_fj, generate_zlight_lut_fj
from doomfj.reference_model import ReferenceModel
from doomfj.texturecompiler import compile_colormap
from doomfj.wad import WadFile

PLANE_FJ = Path("src/fj/plane_render.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")     # hex.read_table / hex.fixed_mul
ASSET = Path("tests/fixtures/freedoom_assets.wad")
COLORMAP_LIGHTS = 32
U = 1 << 16

# (planeheight 16.16, light 0..255, pbase palette index, y screen row): near/far/clamp + light spread +
# horizon (y=50) and the top/bottom edges.
CASES = [
    (41 * U, 191, 96, 99),    # close floor, bright sector, near row
    (41 * U, 191, 96, 50),    # same column at the horizon (far -> dark/clamped)
    (128 * U, 96, 200, 80),   # mid height, mid light
    (600 * U, 255, 4, 50),    # far + tall -> deep distance bucket (clamps to 127)
    (10 * U, 0, 0, 99),       # very close, darkest sector
    (256 * U, 128, 150, 25),  # upper screen (ceiling-ish), mid
    (41 * U, 255, 96, 0),     # top row, brightest
    (88 * U, 160, 110, 60),   # arbitrary interior
]


def test_plane_draw_pixel_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    colormap = WadFile.from_path(str(ASSET)).colormap()
    yslope = generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H)
    zlight = generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS)
    cm = compile_colormap("cm", WadFile.from_path(str(ASSET)), lights=COLORMAP_LIGHTS)

    body, data, expected = [], [], b""
    for k, (ph, light, base, y) in enumerate(CASES):
        for _ in range(2):   # call twice per case (R5 #8): catches scratch/result-reg cleanup bugs
            body += [
                f"hex.mov 8, planeheight, ph{k}", f"hex.mov 2, light, lt{k}",
                f"hex.mov 2, pbase, pb{k}", f"hex.mov 2, y, yy{k}",
                "stl.fcall plane_leaf, plane_ret",
                "hex.print_as_digit 2, lit, 0", "stl.output 10",
            ]
            expected += f"{rm._plane_pixel(colormap, ph, light, base, y):02x}\n".encode()
        data += [f"ph{k}: hex.vec 8, {ph}", f"lt{k}: hex.vec 2, {light}",
                 f"pb{k}: hex.vec 2, {base}", f"yy{k}: hex.vec 2, {y}"]
    data += [
        "planeheight: hex.vec 8", "light: hex.vec 2", "pbase: hex.vec 2", "y: hex.vec 2",
        "lit: hex.vec 2", "plane_ret: ;0",
        yslope, zlight, cm,
    ]
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
            + "plane_leaf: plane.draw_pixel\n" + "\n".join(data) + "\n")
    p = tmp_path / "plane_kernel.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [PLANE_FJ.resolve(), FIXED_POINT_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "plane.draw_pixel: fj output != oracle _plane_pixel"


# ── M13d1: the TEXTURED span kernel plane.draw_span, byte-exact vs the oracle _draw_span ──────────
from doomfj.fixedpoint import fixed_div                                   # noqa: E402
from doomfj.lut_generator import (                                        # noqa: E402
    generate_distscale_lut_fj, generate_xtoviewangle_lut_fj, generate_trig_idioms_fj)
from doomfj.reference_model import ANG90, ANGLE_MASK                      # noqa: E402
from doomfj.texturecompiler import _texel_table                          # noqa: E402

PROJECTION_DUMMY = None
FLAT = "FLOOR4_8"
VIEWZ = (0 + 41) * U                                                      # eye z = floor 0 + VIEWHEIGHT

# (viewx16, viewy16, viewangle BAM, plane height, light, screen row y, x1, x2): a spread of angles / rows /
# heights (floor & ceiling) / span widths incl. a 1-pixel span and a screen-edge span.
SPANS = [
    (512, 384, 0x20000000,   0, 160, 70,  40,  55),   # the grounded 45deg floor span
    (300, 700, 0x00000000, 128, 200, 20,  10,  30),   # ceiling-ish, facing east
    (100, 100, 0x80000000,   0,  96, 90, 120, 159),   # near floor, facing west, span to the screen edge
    (700, 250, 0x60000000,  72, 255, 55,  64,  64),   # 1-pixel span (x1==x2), another angle
    (450, 450, 0xA0000000, 200,  64, 35,   0,  18),   # tall ceiling, dark, left-edge span
]


def _base_scales(rm, viewangle):
    """R_ClearPlanes basexscale/baseyscale (per-frame seeds) for the oracle + the baked fj inputs."""
    cxfrac = rm.cfg.CENTERX << 16
    ang_b = ((viewangle - ANG90) & ANGLE_MASK) >> rm.angle_shift
    bxs = fixed_div(rm._finecos_idx(ang_b), cxfrac, 8, 4)
    bys = (-fixed_div(rm._finesin_idx(ang_b), cxfrac, 8, 4)) & ANGLE_MASK
    return bxs, bys


def test_plane_draw_span_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    Wd = cfg.VIEW_W
    asset = WadFile.from_path(str(ASSET))
    colormap = asset.colormap()
    flat_texels = rm._flat_texels(asset, FLAT, {})                        # raw 64x64 (4096 bytes)

    yslope = generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H)
    distscale = generate_distscale_lut_fj("distscale", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)
    zlight = generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    cm = compile_colormap("cm", asset, lights=COLORMAP_LIGHTS)
    flat = _texel_table("flat", list(flat_texels), "per_entry", over_align=False)

    body, data, expected = [], [], b""
    for k, (vx, vy, va, height, light, y, x1, x2) in enumerate(SPANS):
        viewx, viewy = (vx * U) & 0xFFFFFFFF, (vy * U) & 0xFFFFFFFF
        bxs, bys = _base_scales(rm, va)
        ph = abs((height << 16) - VIEWZ)
        # oracle: render the span into a fresh frame, then read its pixels back
        fb = bytearray(cfg.FB_SIZE)
        rm._draw_span(fb, colormap, flat_texels, height, light, viewx, viewy, va, VIEWZ,
                      bxs, bys, y, x1, x2)
        body += [
            f"hex.set 8, planeheight, {ph}", f"hex.set 2, light, {light}",
            f"hex.set 8, basexscale, {bxs}", f"hex.set 8, baseyscale, {bys}",
            f"hex.set 8, viewx, {viewx}", f"hex.set 8, viewy, {viewy}",
            f"hex.set 8, viewangle, {va}", f"hex.set 2, y, {y}",
            f"hex.set 8, x1, {x1}", f"hex.set 8, x2, {x2}", "hex.set 4, flatbase, 0",
            "stl.fcall draw_span_leaf, span_ret",
        ]
        for x in range(x1, x2 + 1):
            body += [f"hex.print_as_digit 2, framebuffer + {2 * (y * Wd + x)}*dw, 0", "stl.output 10"]
            expected += f"{fb[y * Wd + x]:02x}\n".encode()

    data += [
        "planeheight: hex.vec 8", "light: hex.vec 2", "basexscale: hex.vec 8", "baseyscale: hex.vec 8",
        "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8", "y: hex.vec 2",
        "x1: hex.vec 8", "x2: hex.vec 8", "flatbase: hex.vec 4", "span_ret: ;0",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        yslope, distscale, xtoviewangle, zlight, finesine, cm, flat,
    ]
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
            + f"draw_span_leaf: plane.draw_span framebuffer, {cfg.VIEW_W}\n" + "\n".join(data) + "\n")
    p = tmp_path / "draw_span.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [PLANE_FJ.resolve(), FIXED_POINT_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "plane.draw_span: fj output != oracle _draw_span"
