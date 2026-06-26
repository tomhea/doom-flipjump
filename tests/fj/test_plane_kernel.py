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
