"""M12m+ (F5) — the runtime projection kernels in FlipJump (src/fj/projection.fj), each byte-exact vs the
H5 oracle (reference_model). proj.slope_div is R_PointToAngle's SlopeDiv: the tantoangle index for a
slope num/den. Driven over a spread of 16.16 magnitudes (small den / normal / clamp / boundary) twice
each (R5 #8), compared to ReferenceModel._slope_div — so the fj angle math and the oracle agree (D12)."""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.fixedpoint import fixed_mul, fixed_div, _signed
from doomfj.harness import W
from doomfj.lut_generator import (
    generate_tantoangle_lut_fj, generate_trig_idioms_fj, generate_viewangletox_lut_fj,
    generate_finetangent_lut_fj, generate_xtoviewangle_lut_fj,
)
from doomfj.reference_model import ReferenceModel, SLOPERANGE, ANGLE_MASK
from doomfj.mapcompiler import bake_bsp, _point_side
from doomfj.wad import WadFile

PROJECTION_FJ = Path("src/fj/projection.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")   # provides hex.read_table + hex.fixed_div
E1M1_WAD = Path("tests/fixtures/freedoom_e1m1.wad")
MASK40 = (1 << 40) - 1   # 10-nibble two's-complement mask (point_on_side's working width)


def _run(tmp_path, name, body, data, expected: bytes):
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj output != oracle"


# (num, den) 16.16 magnitudes: den<512 sentinel; den==0; slope<1; slope==1 (ANG45 clamp); slope>1 clamp;
# den exactly 512; num==0; a mid value.
SLOPE_CASES = [
    (0x10000, 0x100),     # den 256 < 512 -> SLOPERANGE
    (0x50000, 0x0),       # den 0 < 512 -> SLOPERANGE (no divide-by-zero)
    (0x10000, 0x20000),   # slope 0.5 -> 1024
    (0x20000, 0x20000),   # slope 1.0 -> 2048 (ANG45, exactly at clamp)
    (0x30000, 0x10000),   # slope 3.0 -> clamp to 2048
    (0x10000, 0x200),     # den exactly 512 -> compute
    (0x8000,  0x40000),   # slope 0.125 -> 256
    (0x0,     0x10000),   # num 0 -> 0
]


def test_slope_div_byte_exact_vs_oracle(tmp_path):
    body, data = [], []
    for k, (num, den) in enumerate(SLOPE_CASES):
        for _ in range(2):   # call twice per case (R5 #8): catches scratch/result-reg cleanup bugs
            body += [f"proj.slope_div d, n{k}, m{k}", "hex.print_as_digit 3, d, 0", "stl.output 10"]
        data += [f"n{k}: hex.vec 8, {num}", f"m{k}: hex.vec 8, {den}"]
    data.append("d: hex.vec 3")
    expected = b"".join(f"{ReferenceModel._slope_div(num, den):03x}\n".encode() * 2
                        for num, den in SLOPE_CASES)
    _run(tmp_path, "slope_div", body, data, expected)


# ── proj.point_to_angle (R_PointToAngle2): octant-fold wrapper around slope_div + tantoangle ──
F = 0x10000   # 1.0 in 16.16 world units

# (x1, y1, x2, y2) 16.16 coords. Hits all 8 octants (idx = sx*4+sy*2+gt) + (0,0) + the axis/diagonal
# boundary quirks (due-E=0, due-N=ANG90-1, due-W=ANG180-1, due-S=ANG270, NE-diag=ANG45-1) + a
# non-origin base point so the dx/dy subtraction is exercised.
P2A_CASES = [
    (0, 0, 0, 0),               # both deltas zero -> 0
    # the 8 octants from the origin
    (0, 0,  F,  3*F),           # sx0 sy0 gt0 : |dx|<=|dy|, dy>0
    (0, 0,  3*F,  F),           # sx0 sy0 gt1 : |dx|>|dy|
    (0, 0,  F, -3*F),           # sx0 sy1 gt0
    (0, 0,  3*F, -F),           # sx0 sy1 gt1
    (0, 0, -F,  3*F),           # sx1 sy0 gt0
    (0, 0, -3*F,  F),           # sx1 sy0 gt1
    (0, 0, -F, -3*F),           # sx1 sy1 gt0
    (0, 0, -3*F, -F),           # sx1 sy1 gt1
    # axis boundaries (the DOOM ±1 quirks)
    (0, 0,  F, 0),              # due east  -> 0
    (0, 0, 0,  F),              # due north -> ANG90-1
    (0, 0, -F, 0),              # due west  -> ANG180-1
    (0, 0, 0, -F),              # due south -> ANG270
    # exact diagonals (dx==dy boundary -> not-gt branch)
    (0, 0,  2*F,  2*F),         # NE diagonal -> ANG45-1
    (0, 0, -2*F,  2*F),         # NW diagonal
    # non-origin base point + a larger spread
    (2*F, 5*F, 9*F, 8*F),       # general NE-ish from (2,5)
    (10*F, 10*F, 3*F, 2*F),     # general SW from (10,10)
    (0, 0, 7*F, 7*F),           # another exact diagonal, bigger magnitude
]


def test_point_to_angle_byte_exact_vs_oracle(tmp_path):
    rm = ReferenceModel()
    body, data = [], []
    for k, (x1, y1, x2, y2) in enumerate(P2A_CASES):
        for _ in range(2):   # call twice per case (R5 #8): catches scratch/result-reg cleanup bugs
            body += [f"proj.point_to_angle d, x1_{k}, y1_{k}, x2_{k}, y2_{k}",
                     "hex.print_as_digit 8, d, 0", "stl.output 10"]
        data += [f"x1_{k}: hex.vec 8, {x1 & 0xFFFFFFFF}", f"y1_{k}: hex.vec 8, {y1 & 0xFFFFFFFF}",
                 f"x2_{k}: hex.vec 8, {x2 & 0xFFFFFFFF}", f"y2_{k}: hex.vec 8, {y2 & 0xFFFFFFFF}"]
    data += ["d: hex.vec 8", generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    expected = b"".join(f"{rm.point_to_angle(x1, y1, x2, y2):08x}\n".encode() * 2
                        for (x1, y1, x2, y2) in P2A_CASES)

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "point_to_angle.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "point_to_angle: fj output != oracle"


# ── proj.point_to_dist (R_PointToDist): perpendicular-free distance via tantoangle + finesine + 2 divides ─
# (viewx, viewy, x, y) 16.16. Covers: axis-aligned (dy=0 -> dist=dx exact), dy>dx (the swap branch),
# dy<dx, dy==dx (slope 1.0 -> SLOPERANGE), the degenerate point (dx==0 -> 0), abs of negative deltas,
# the 3-4-5 triangle (dist≈5), and a non-origin view point + a larger spread.
P2D_CASES = [
    (0, 0, 0, 0),               # degenerate -> 0
    (0, 0,  F, 0),              # due east, axis-aligned -> dist == F
    (0, 0, 0,  F),              # due north -> swap (dy>dx) -> dist == F
    (0, 0,  F,  F),             # exact diagonal: slope 1.0 -> SLOPERANGE; dist == F*sqrt(2)
    (0, 0,  3*F,  4*F),         # 3-4-5: dy>dx swap -> dist ≈ 5F
    (0, 0, -3*F, -4*F),         # abs of negatives -> same 5F
    (0, 0,  4*F,  3*F),         # dy<dx, no swap -> dist ≈ 5F
    (2*F, 2*F, 5*F, 6*F),       # non-origin view: dx=3F,dy=4F -> ≈ 5F
    (0, 0, 100*F, 30*F),        # larger spread
    (0, 0,  F,  2*F),           # dy>dx swap, off-axis
]


def test_point_to_dist_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    body, data = [], []
    for k, (vx, vy, x, y) in enumerate(P2D_CASES):
        for _ in range(2):   # call twice per case (R5 #8): catches scratch/result-reg cleanup bugs
            body += [f"proj.point_to_dist d, vx{k}, vy{k}, x{k}, y{k}",
                     "hex.print_as_digit 8, d, 0", "stl.output 10"]
        data += [f"vx{k}: hex.vec 8, {vx & 0xFFFFFFFF}", f"vy{k}: hex.vec 8, {vy & 0xFFFFFFFF}",
                 f"x{k}: hex.vec 8, {x & 0xFFFFFFFF}", f"y{k}: hex.vec 8, {y & 0xFFFFFFFF}"]
    data += ["d: hex.vec 8",
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
             generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)]
    expected = b"".join(f"{rm.point_to_dist(vx, vy, x, y):08x}\n".encode() * 2
                        for (vx, vy, x, y) in P2D_CASES)

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "point_to_dist.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "point_to_dist: fj output != oracle"


# ── proj.wall_setup (R_StoreWallRange): rw_normalangle + rw_distance for a seg ──
# Driven on the committed DOOM-wound square room (256x256, verts (0,0)..(256,256)) from a few view
# positions: straight-on (offsetangle≈0), near/far, and oblique (exercises the BAM-abs fold + the
# ANG90 clamp). wall_setup INLINES point_to_angle + point_to_dist (heavy read_table bodies) per call,
# so we keep the case count small to stay well under the 300s assemble ceiling — the renderer-scale
# call sites route through a shared leaf later (the integration rung). Byte-exact vs ReferenceModel.
def _square_room():
    from doomfj.mapcompiler import bake_bsp
    from doomfj.wad import WadFile
    return bake_bsp(WadFile.from_path(Path("tests/fixtures/square_room.wad")), "MAP01")


# (viewx_units, viewy_units, seg_index) — seg 0..3 = west,north,east,south (CW DOOM winding)
WALL_SETUP_CASES = [
    (128, 128, 2),   # east wall straight ahead from centre: offsetangle≈0, dist 128
    (128, 128, 0),   # west wall (behind/normal flipped) from centre
    (128, 128, 1),   # north wall from centre
    (200, 128, 2),   # east wall, closer (dist 56), straight-on
    (200, 128, 1),   # north wall seen obliquely (large offsetangle / clamp)
    (64, 180, 3),    # south wall from an off-centre point (oblique)
]


def test_wall_setup_byte_exact_vs_oracle(tmp_path):
    cmap = _square_room()
    rm = ReferenceModel()
    U = 1 << 16
    body, data, expected = [], [], b""
    for k, (vxu, vyu, si) in enumerate(WALL_SETUP_CASES):
        seg = cmap.segs[si]
        v1x, v1y = cmap.vertexes[seg.v1]
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.wall_setup nrm, rwd, vx{k}, vy{k}, sa{k}, v1x{k}, v1y{k}",
                     "hex.print_as_digit 8, nrm, 0", "stl.output 10",
                     "hex.print_as_digit 8, rwd, 0", "stl.output 10"]
        data += [f"vx{k}: hex.vec 8, {vxu * U}", f"vy{k}: hex.vec 8, {vyu * U}",
                 f"sa{k}: hex.vec 4, {seg.angle & 0xFFFF}",
                 f"v1x{k}: hex.vec 8, {(v1x << 16) & 0xFFFFFFFF}",
                 f"v1y{k}: hex.vec 8, {(v1y << 16) & 0xFFFFFFFF}"]
        nrm, rwd = rm.wall_setup(vxu * U, vyu * U, seg, cmap.vertexes)
        expected += (f"{nrm:08x}\n{rwd:08x}\n".encode()) * 2
    data += ["nrm: hex.vec 8", "rwd: hex.vec 8",
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
             generate_trig_idioms_fj("finesine", Config().TRIG_N, 16)]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "wall_setup.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "wall_setup: fj output != oracle"


# ── proj.scale_from_global_angle (R_ScaleFromGlobalAngle): the per-column wall scale ──
# (visangle, viewangle, rw_normalangle, rw_distance) BAM/16.16. Covers: den==0 -> SCALE_MAX, clamp-up,
# clamp-down (far), the exact perpendicular-centre scale (0.625=40960), a closer wall, off-angle
# visangle/viewangle/normalangle, and a NEGATIVE-den case (sine of an angle past ANG180 is negative ->
# the oracle's fixed_div returns it UNSIGNED-wrapped to a huge value -> clamps to SCALE_MAX; this is why
# the clamp compares are UNSIGNED hex.cmp, NOT scmp — scmp would wrongly give SCALE_MIN). PROJECTION
# (=CENTERX, resolution-dependent) is passed as a compile-time arg from Config (R6 SSOT), not hardcoded.
_AU = 1 << 16
SCALE_CASES = [
    (0, 0, 0, 0),                          # den 0 -> SCALE_MAX
    (0, 0, 0, 1 * _AU),                    # very close -> clamp up to SCALE_MAX
    (0, 0, 0, 30000 * _AU),                # very far -> clamp down to SCALE_MIN
    (0, 0, 0, 128 * _AU),                  # perpendicular centre: PROJECTION/128 = 0.625 = 40960 exact
    (0, 0, 0, 56 * _AU),                   # closer wall -> larger scale
    (0x10000000, 0, 0, 100 * _AU),         # off-angle visangle
    (0, 0x10000000, 0, 100 * _AU),         # viewangle offset (anglea != ANG90)
    (0, 0, 0x20000000, 100 * _AU),         # oblique wall (angleb != ANG90)
    (0, 0xA0000000, 0, 100 * _AU),         # anglea past ANG180 -> sin<0 -> den<0 -> wraps -> SCALE_MAX (unsigned)
    (0x08000000, 0x04000000, 0x10000000, 200 * _AU),   # general mix
]


def test_scale_from_global_angle_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    proj = cfg.PROJECTION << 16            # the R6 SSOT value, passed as a compile-time macro arg
    body, data, expected = [], [], b""
    for k, (vis, view, nrm, rwd) in enumerate(SCALE_CASES):
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.scale_from_global_angle s, vis{k}, vw{k}, nrm{k}, rwd{k}, {proj}",
                     "hex.print_as_digit 8, s, 0", "stl.output 10"]
        data += [f"vis{k}: hex.vec 8, {vis & 0xFFFFFFFF}", f"vw{k}: hex.vec 8, {view & 0xFFFFFFFF}",
                 f"nrm{k}: hex.vec 8, {nrm & 0xFFFFFFFF}", f"rwd{k}: hex.vec 8, {rwd & 0xFFFFFFFF}"]
        expected += f"{rm.scale_from_global_angle(vis, view, nrm, rwd):08x}\n".encode() * 2
    data += ["s: hex.vec 8", generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "scale.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "scale_from_global_angle: fj output != oracle"


# ── proj.angle_to_x (R_PointToX / viewangletox lookup): view-relative BAM angle -> screen column ──
# idx = (angle + ANG90) >> angle_shift(20), clamped to [0, len(viewangletox)-1]; result = the signed
# column (2's-complement 8-nibble; the off-screen ends carry -1 / VIEW_W+1 sentinels). Covers straight
# ahead, the ±ANG45 FOV edges, beyond-FOV angles that clamp to the table ends, and a spread.
A2X_CASES = [
    0x00000000,   # straight ahead -> centre column
    0x20000000,   # +ANG45 (left FOV edge)
    0xE0000000,   # -ANG45 (right FOV edge)
    0x40000000,   # +ANG90 (beyond left) -> idx clamps to len-1
    0xC0000000,   # -ANG90 (beyond right) -> idx 0
    0x10000000, 0x30000000, 0x08000000, 0xF0000000, 0x80000000,
]


def test_angle_to_x_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    body, data, expected = [], [], b""
    for k, a in enumerate(A2X_CASES):
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.angle_to_x d, a{k}", "hex.print_as_digit 8, d, 0", "stl.output 10"]
        data.append(f"a{k}: hex.vec 8, {a & 0xFFFFFFFF}")
        expected += f"{rm.angle_to_x(a) & 0xFFFFFFFF:08x}\n".encode() * 2
    data += ["d: hex.vec 8",
             generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "angle_to_x.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "angle_to_x: fj output != oracle"


# ── proj.wall_x_range (R_AddLine): seg -> (visible, x1, x2, rw_angle1) ──
# Drives the square room from views that produce a back-face cull, an outside-FOV cull, a clipped-but-
# visible wall, and straight-on visible walls. The fj writes a `visible` flag (0 = the oracle's None) and
# zeroes x1/x2/rw_angle1 on any cull, so culled cases compare as (0,0,0,0). Inlines point_to_angle x2 +
# angle_to_x x2 per call, so the case count is kept small (300s ceiling). Byte-exact vs the oracle.
_ANG90 = 0x40000000
_ANG45 = 0x20000000
# (viewx_u, viewy_u, viewangle, seg_index)
WXR_CASES = [
    (128, 128, 0, 2),         # facing east, EAST wall straight ahead -> visible
    (128, 128, 0, 0),         # facing east, WEST wall behind -> back-face cull (span>=ANG180)
    (128, 128, 0, 1),         # facing east, NORTH wall to the side -> outside FOV cull
    (128, 128, _ANG90, 1),    # facing north, NORTH wall straight ahead -> visible
    (200, 128, 0, 2),         # facing east, EAST wall closer -> visible (wider span)
    (128, 128, _ANG45, 2),    # facing NE, EAST wall at the FOV edge -> clipped but visible
]


def test_wall_x_range_byte_exact_vs_oracle(tmp_path):
    cmap = _square_room()
    rm = ReferenceModel()
    U = 1 << 16
    body, data, expected = [], [], b""
    for k, (vxu, vyu, va, si) in enumerate(WXR_CASES):
        seg = cmap.segs[si]
        v1x, v1y = cmap.vertexes[seg.v1]
        v2x, v2y = cmap.vertexes[seg.v2]
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.wall_x_range vis, x1, x2, rwa, vx{k}, vy{k}, va{k}, "
                     f"a{k}, b{k}, c{k}, e{k}",
                     "hex.print_as_digit 1, vis, 0", "stl.output 10",
                     "hex.print_as_digit 8, x1, 0", "stl.output 10",
                     "hex.print_as_digit 8, x2, 0", "stl.output 10",
                     "hex.print_as_digit 8, rwa, 0", "stl.output 10"]
        data += [f"vx{k}: hex.vec 8, {vxu * U}", f"vy{k}: hex.vec 8, {vyu * U}",
                 f"va{k}: hex.vec 8, {va & 0xFFFFFFFF}",
                 f"a{k}: hex.vec 8, {(v1x << 16) & 0xFFFFFFFF}", f"b{k}: hex.vec 8, {(v1y << 16) & 0xFFFFFFFF}",
                 f"c{k}: hex.vec 8, {(v2x << 16) & 0xFFFFFFFF}", f"e{k}: hex.vec 8, {(v2y << 16) & 0xFFFFFFFF}"]
        res = rm.wall_x_range(vxu * U, vyu * U, va, seg, cmap.vertexes)
        if res is None:
            expected += b"0\n00000000\n00000000\n00000000\n" * 2
        else:
            x1, x2, rwa = res
            expected += f"1\n{x1 & 0xFFFFFFFF:08x}\n{x2 & 0xFFFFFFFF:08x}\n{rwa:08x}\n".encode() * 2
    data += ["vis: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
             generate_viewangletox_lut_fj("viewangletox", Config().VIEW_W, Config().TRIG_N)]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "wall_x_range.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "wall_x_range: fj output != oracle"


# ── proj.wall_screen_span (R_RenderSegLoop top/bottom projection): the screen rows a wall column fills ──
# top/bottom = (CENTERY<<16 - fixed_mul(ceil/floor<<16 - viewz, scale)) >> 16 (ARITHMETIC). Outputs are
# SIGNED row ints (8-nibble 2's-complement; off-screen rows < 0 or >= VIEW_H are clipped by the loop).
# centeryfix (resolution-dependent) is a compile-time arg from Config (R6). No LUTs needed.
# (ceil_h, floor_h map units; viewz, scale 16.16) — incl. negative tops (sign-extension) + negative heights.
WSS_CASES = [
    (128, 0, 41 << 16, 0xA000),     # square-room perpendicular centre: (-5, 75)
    (128, 0, 41 << 16, 0x10000),    # scale 1.0: (-37, 91)
    (128, 0, 41 << 16, 0x100),      # SCALE_MIN (far): (49, 50)
    (200, 64, 41 << 16, 0x20000),   # taller/closer: (-268, 4)
    (128, 0, 41 << 16, 0x300000),   # huge scale: (-4126, 2018)
    (-32, -128, 9 << 16, 0x18000),  # negative ceil/floor heights: (111, 255)
]


def test_wall_screen_span_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    centeryfix = cfg.CENTERY << 16        # resolution-dependent -> compile-time arg from Config (R6)
    body, data, expected = [], [], b""
    for k, (ch, fh, vz, sc) in enumerate(WSS_CASES):
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.wall_screen_span top, bot, cf{k}, ff{k}, vz{k}, sc{k}, {centeryfix}",
                     "hex.print_as_digit 8, top, 0", "stl.output 10",
                     "hex.print_as_digit 8, bot, 0", "stl.output 10"]
        data += [f"cf{k}: hex.vec 8, {(ch << 16) & 0xFFFFFFFF}", f"ff{k}: hex.vec 8, {(fh << 16) & 0xFFFFFFFF}",
                 f"vz{k}: hex.vec 8, {vz & 0xFFFFFFFF}", f"sc{k}: hex.vec 8, {sc & 0xFFFFFFFF}"]
        top, bot = rm.wall_screen_span(ch, fh, vz, sc)
        expected += f"{top & 0xFFFFFFFF:08x}\n{bot & 0xFFFFFFFF:08x}\n".encode() * 2
    data += ["top: hex.vec 8", "bot: hex.vec 8"]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "wall_screen_span.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "wall_screen_span: fj output != oracle"


# ── proj.scalestep (the per-column rw_scalestep, render_wall_frame lines 523-529): the linear scale
# increment from column x1 to x2 = trunc((scale2-scale1)/(x2-x1)) TOWARD ZERO (a plain truncated divide,
# NOT FixedDiv), or 0 if x2<=x1. scale1/scale2 are 16.16; x1/x2 are signed columns. Result is signed.
def _oracle_scalestep(s1, s2, x1, x2):
    if x2 > x1:
        diff, span = s2 - s1, x2 - x1
        return -(abs(diff) // span) if diff < 0 else diff // span   # trunc toward zero
    return 0


SCALESTEP_CASES = [
    (0xA000, 0x12000, 10, 50),    # diff>0, span 40
    (0x12000, 0xA000, 10, 50),    # diff<0 -> negative step (trunc toward zero)
    (0xA000, 0xA000, 10, 50),     # diff==0 -> 0
    (0xA000, 0x12000, 50, 50),    # x2==x1 -> 0 (the guard)
    (0x100, 0x400000, -1, 159),   # full span, x1=-1 (signed), big positive diff
    (0x400000, 0x100, 0, 80),     # big negative diff
    (0xA005, 0xA000, 5, 12),      # small negative diff, span 7 -> truncation
]


def test_scalestep_byte_exact_vs_oracle(tmp_path):
    body, data, expected = [], [], b""
    for k, (s1, s2, x1, x2) in enumerate(SCALESTEP_CASES):
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.scalestep d, s1_{k}, s2_{k}, x1_{k}, x2_{k}",
                     "hex.print_as_digit 8, d, 0", "stl.output 10"]
        data += [f"s1_{k}: hex.vec 8, {s1 & 0xFFFFFFFF}", f"s2_{k}: hex.vec 8, {s2 & 0xFFFFFFFF}",
                 f"x1_{k}: hex.vec 8, {x1 & 0xFFFFFFFF}", f"x2_{k}: hex.vec 8, {x2 & 0xFFFFFFFF}"]
        expected += f"{_oracle_scalestep(s1, s2, x1, x2) & 0xFFFFFFFF:08x}\n".encode() * 2
    data.append("d: hex.vec 8")

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "scalestep.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "scalestep: fj output != oracle"


# ── proj.wall_offset (R_StoreWallRange texture-horizontal setup, _wall_offset): rw_offset + rw_centerangle.
# rw_offset = ±fixed_mul(hyp, read_sin(BAM-abs+clamp(rw_normalangle - rw_angle1))) + texoff, sign by the
# UNFOLDED offsetangle < ANG180; rw_centerangle = ANG90 + viewangle - rw_normalangle. Inlines point_to_dist
# + finesine. Driven on the square room (real seg.offset + sidedef x_off), byte-exact vs rm._wall_offset.
def _square_room_wad():
    from doomfj.wad import WadFile
    return WadFile.from_path(Path("tests/fixtures/square_room.wad"))


# (viewx_u, viewy_u, viewangle, seg_index)
WOFF_CASES = [
    (128, 128, 0, 2),
    (128, 128, 0x40000000, 1),
    (200, 128, 0, 2),
    (64, 180, 0x20000000, 3),
    (128, 128, 0, 0),
]


def test_wall_offset_byte_exact_vs_oracle(tmp_path):
    cmap = _square_room()
    wad = _square_room_wad()
    rm = ReferenceModel()
    U = 1 << 16
    lds = wad.linedefs("MAP01")
    sds = wad.sidedefs("MAP01")
    verts = cmap.vertexes
    body, data, expected = [], [], b""
    for k, (vxu, vyu, va, si) in enumerate(WOFF_CASES):
        seg = cmap.segs[si]
        v1x, v1y = verts[seg.v1]
        rw_angle1 = rm.point_to_angle(vxu * U, vyu * U, v1x << 16, v1y << 16)
        rw_normalangle, _ = rm.wall_setup(vxu * U, vyu * U, seg, verts)
        ld = lds[seg.linedef]
        sd = sds[ld.front if seg.side == 0 else ld.back]
        rw_offset, rw_centerangle = rm._wall_offset(vxu * U, vyu * U, va, seg, verts,
                                                    rw_normalangle, rw_angle1, sd)
        texoff = (seg.offset + sd.x_off) << 16
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.wall_offset roff, rca, vx{k}, vy{k}, va{k}, nrm{k}, ra{k}, "
                     f"a{k}, b{k}, toff{k}",
                     "hex.print_as_digit 8, roff, 0", "stl.output 10",
                     "hex.print_as_digit 8, rca, 0", "stl.output 10"]
        data += [f"vx{k}: hex.vec 8, {vxu * U}", f"vy{k}: hex.vec 8, {vyu * U}",
                 f"va{k}: hex.vec 8, {va & 0xFFFFFFFF}",
                 f"nrm{k}: hex.vec 8, {rw_normalangle & 0xFFFFFFFF}",
                 f"ra{k}: hex.vec 8, {rw_angle1 & 0xFFFFFFFF}",
                 f"a{k}: hex.vec 8, {(v1x << 16) & 0xFFFFFFFF}", f"b{k}: hex.vec 8, {(v1y << 16) & 0xFFFFFFFF}",
                 f"toff{k}: hex.vec 8, {texoff & 0xFFFFFFFF}"]
        expected += f"{rw_offset & 0xFFFFFFFF:08x}\n{rw_centerangle & 0xFFFFFFFF:08x}\n".encode() * 2
    data += ["roff: hex.vec 8", "rca: hex.vec 8",
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
             generate_trig_idioms_fj("finesine", Config().TRIG_N, 16)]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "wall_offset.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "wall_offset: fj output != oracle"


# ── proj.texture_u (per-column texture u-coord, render_wall_frame lines 549-552): ang = rw_centerangle +
# xtoviewangle[x]; ft = finetangent[ang>>angle_shift]; texcol = ((rw_offset - fixed_mul(ft, rw_distance))
# signed >> 16) % tw — a FLOORED modulo (texcol in [0, tw)). Reads the xtoviewangle + finetangent LUTs.
def _oracle_texcol(rm, rw_centerangle, rw_offset, rw_distance, x, tw):
    cfg = rm.cfg
    ang = (rw_centerangle + rm.xtoviewangle[x]) & ANGLE_MASK
    ft = rm.finetangent[(ang >> rm.angle_shift) & (cfg.TRIG_N - 1)]
    return (_signed((rw_offset - fixed_mul(ft, rw_distance, 8, 4)) & ANGLE_MASK, 32) >> 16) % tw


# (rw_centerangle, rw_offset, rw_distance, x, tw) — incl. negative tcol (floored mod) + non-pow2 tw.
TEXU_CASES = [
    (0x40000000, 0x00000000, 128 << 16, 80, 64),
    (0x40000000, 0x00400000, 128 << 16, 0, 64),
    (0x40000000, 0x00400000, 128 << 16, 159, 64),
    (0x40000000, 0xFFC00000, 100 << 16, 40, 128),   # rw_offset = -64.0 -> negative tcol -> floored mod
    (0x40000000, 0x00100000, 200 << 16, 120, 96),   # non-pow2 tw=96
    (0x50000000, 0x00800000, 64 << 16, 20, 256),
    (0x40000000, 0x00000000, 50 << 16, 159, 64),
]


def test_texture_u_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    body, data, expected = [], [], b""
    for k, (rca, roff, rdist, x, tw) in enumerate(TEXU_CASES):
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.texture_u d, rca{k}, roff{k}, rd{k}, xx{k}, tw{k}",
                     "hex.print_as_digit 8, d, 0", "stl.output 10"]
        data += [f"rca{k}: hex.vec 8, {rca & 0xFFFFFFFF}", f"roff{k}: hex.vec 8, {roff & 0xFFFFFFFF}",
                 f"rd{k}: hex.vec 8, {rdist & 0xFFFFFFFF}", f"xx{k}: hex.vec 2, {x}",
                 f"tw{k}: hex.vec 8, {tw}"]
        expected += f"{_oracle_texcol(rm, rca, roff, rdist, x, tw) & 0xFFFFFFFF:08x}\n".encode() * 2
    data += ["d: hex.vec 8",
             generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N),
             generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "texture_u.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "texture_u: fj output != oracle"


# ── proj.column_setup (the per-column texture-v DDA setup, render_wall_frame lines 553-559): from a
# column's scale + the wall's worldtop + the clipped top row, compute the 8.8 DDA params (frac0, step) the
# textured-column leaf consumes. iscale = fixed_div(1<<16, scale)//ds (texels/pixel); texturemid =
# (worldtop<<16)//ds; frac = texturemid + (top-CENTERY)*iscale; frac0 = (frac>>8)&0xFFFF, step =
# (iscale>>8)&0xFFFF. ds = TEXTURE_DOWNSCALE = 2 (engine invariant). CENTERY a compile-time arg (R6).
def _oracle_column_setup(cy, scale, worldtop, top, ds):
    iscale = fixed_div(1 << 16, scale & ANGLE_MASK, 8, 4) // ds
    texturemid = (worldtop << 16) // ds      # FLOORED (Python //) — negative worldtop floors toward -inf
    frac = texturemid + (top - cy) * iscale
    return (frac >> 8) & 0xFFFF, (iscale >> 8) & 0xFFFF


# (scale, worldtop, top, ds). ds=2 is the real config (TEXTURE_DOWNSCALE @ W=160); the ds=3 (non-pow2)
# cases exercise the GENERAL floored divide — incl. the negative-worldtop floor-correction branch that a
# pow2 ds (worldtop<<16 always even) never triggers. Also covers negative top (row above centre).
COLSETUP_CASES = [
    (0xA000, 87, 0, 2),      # square-room perpendicular centre (real ds=2)
    (0x10000, 87, 10, 2),    # scale 1.0
    (0x100, 87, 49, 2),      # SCALE_MIN (far)
    (0x20000, 50, -5, 2),    # negative top
    (0xA000, -20, 30, 2),    # negative worldtop (ceiling below the eye)
    (0x40000, 87, 75, 2),    # scale 4.0
    (0x10000, 50, 10, 3),    # ds=3: positive worldtop, non-pow2 floored divide
    (0x10000, -17, 60, 3),   # ds=3 + negative worldtop -> the floor-correction (radj) branch
]


def test_column_setup_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    cy = cfg.CENTERY
    assert cfg.TEXTURE_DOWNSCALE == 2     # the real config; the ds is threaded as an arg, not hardcoded
    body, data, expected = [], [], b""
    for k, (sc, wt, top, ds) in enumerate(COLSETUP_CASES):
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.column_setup f0, st, sc{k}, wt{k}, tp{k}, {cy}, {ds}",
                     "hex.print_as_digit 4, f0, 0", "stl.output 10",
                     "hex.print_as_digit 4, st, 0", "stl.output 10"]
        data += [f"sc{k}: hex.vec 8, {sc & 0xFFFFFFFF}", f"wt{k}: hex.vec 8, {wt & 0xFFFFFFFF}",
                 f"tp{k}: hex.vec 8, {top & 0xFFFFFFFF}"]
        frac0, step = _oracle_column_setup(cy, sc, wt, top, ds)
        expected += f"{frac0:04x}\n{step:04x}\n".encode() * 2
    data += ["f0: hex.vec 4", "st: hex.vec 4"]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "column_setup.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "column_setup: fj output != oracle"


# ── proj.wall_scale_setup (the per-seg scale interpolation seed, render_wall_frame lines 521-527): the
# column-x1 scale (= scale_from_global_angle at visangle = viewangle + xtoviewangle[x1]) + the linear
# rw_scalestep to x2. Composes the xtoviewangle lookup + scale_from_global_angle (x2) + scalestep. The
# per-column scale is then scale1 accumulated by scalestep (the loop's `scale += scalestep`).
def _oracle_wall_scale_setup(rm, viewangle, rw_normalangle, rw_distance, x1, x2):
    s1 = rm.scale_from_global_angle((viewangle + rm.xtoviewangle[x1]) & ANGLE_MASK,
                                    viewangle, rw_normalangle, rw_distance)
    s2 = rm.scale_from_global_angle((viewangle + rm.xtoviewangle[x2]) & ANGLE_MASK,
                                    viewangle, rw_normalangle, rw_distance)
    if x2 > x1:
        diff, span = s2 - s1, x2 - x1
        step = -(abs(diff) // span) if diff < 0 else diff // span
    else:
        step = 0
    return s1, step


# (viewx_u, viewy_u, viewangle, seg_index) on the square room — visible segs (x1<x2 in [0,VIEW_W]).
WSS_SETUP_CASES = [
    (128, 128, 0, 2),            # facing east, EAST wall
    (200, 128, 0, 2),            # closer to EAST wall (steeper scalestep)
    (128, 128, 0x40000000, 1),   # facing north, NORTH wall
    (128, 128, 0x80000000, 0),   # facing west, WEST wall
]


def test_wall_scale_setup_byte_exact_vs_oracle(tmp_path):
    cmap = _square_room()
    rm = ReferenceModel()
    cfg = Config()
    proj = cfg.PROJECTION << 16
    U = 1 << 16
    verts = cmap.vertexes
    body, data, expected = [], [], b""
    for k, (vxu, vyu, va, si) in enumerate(WSS_SETUP_CASES):
        seg = cmap.segs[si]
        rng = rm.wall_x_range(vxu * U, vyu * U, va, seg, verts)
        assert rng is not None, f"case {k}: seg not visible"
        x1, x2, _ = rng
        rw_normalangle, rw_distance = rm.wall_setup(vxu * U, vyu * U, seg, verts)
        s1, step = _oracle_wall_scale_setup(rm, va, rw_normalangle, rw_distance, x1, x2)
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.wall_scale_setup sc1, sst, va{k}, nrm{k}, rd{k}, x1_{k}, x2_{k}, {proj}",
                     "hex.print_as_digit 8, sc1, 0", "stl.output 10",
                     "hex.print_as_digit 8, sst, 0", "stl.output 10"]
        data += [f"va{k}: hex.vec 8, {va & 0xFFFFFFFF}",
                 f"nrm{k}: hex.vec 8, {rw_normalangle & 0xFFFFFFFF}",
                 f"rd{k}: hex.vec 8, {rw_distance & 0xFFFFFFFF}",
                 f"x1_{k}: hex.vec 8, {x1 & 0xFFFFFFFF}", f"x2_{k}: hex.vec 8, {x2 & 0xFFFFFFFF}"]
        expected += f"{s1 & 0xFFFFFFFF:08x}\n{step & 0xFFFFFFFF:08x}\n".encode() * 2
    data += ["sc1: hex.vec 8", "sst: hex.vec 8",
             generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N),
             generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "wall_scale_setup.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "wall_scale_setup: fj output != oracle"


# ── proj.column_render_params (the per-column render-parameter bundle, render_wall_frame lines 540-559):
# wall_screen_span -> CLIP top=max(0,top)/bottom=min(VIEW_H-1,bottom) -> texture_u -> column_setup, all for
# one column. Outputs (top, bottom [both clipped], texcol, frac0, step). The clip is the new logic (signed
# hex.sign/scmp). centery/ds/VIEW_H-1 are compile-time Config args (R6); centeryfix = centery<<16 (expr).
def _oracle_column_params(rm, scale, rw_centerangle, rw_offset, rw_distance, x, tw,
                          ceil_h, floor_h, viewz, worldtop):
    cfg = rm.cfg
    top, bottom = rm.wall_screen_span(ceil_h, floor_h, viewz, scale & ANGLE_MASK)
    top = max(0, top)
    bottom = min(cfg.VIEW_H - 1, bottom)                  # clip to the screen
    texcol = _oracle_texcol(rm, rw_centerangle, rw_offset, rw_distance, x, tw)
    frac0, step = _oracle_column_setup(cfg.CENTERY, scale, worldtop, top, cfg.TEXTURE_DOWNSCALE)
    return top, bottom, texcol, frac0, step


def test_column_render_params_byte_exact_vs_oracle(tmp_path):
    cmap = _square_room()
    rm = ReferenceModel()
    cfg = Config()
    U = 1 << 16
    verts = cmap.vertexes
    ANG90 = 0x40000000
    CEIL_H, FLOOR_H = 128, 0
    viewz = 41 << 16                       # view_z for the square room (floor 0 + VIEWHEIGHT 41)
    worldtop = CEIL_H - (viewz >> 16)      # 87
    TW = 64
    RW_OFFSET = 0x80000                    # synthetic texture u-origin (texture_u path already M12w-tested)
    # (viewx_u, viewy_u, seg_index, column x)
    CASES = [
        (128, 128, 2, 0),      # east wall, x=0: top -5 -> 0 (top clip)
        (128, 128, 2, 80),     # mid column
        (200, 128, 2, 0),      # closer: top -75 -> 0, bottom 108 -> 99 (both clip)
        (200, 128, 2, 159),    # closer, right edge
        (200, 128, 2, 80),
    ]
    body, data, expected = [], [], b""
    for k, (vxu, vyu, si, x) in enumerate(CASES):
        seg = cmap.segs[si]
        x1, x2, _ = rm.wall_x_range(vxu * U, vyu * U, 0, seg, verts)
        nrm, rwd = rm.wall_setup(vxu * U, vyu * U, seg, verts)
        s1, sstep = _oracle_wall_scale_setup(rm, 0, nrm, rwd, x1, x2)
        scale = (s1 + (x - x1) * sstep) & ANGLE_MASK          # the loop's accumulated scale at column x
        rca = (ANG90 + 0 - nrm) & ANGLE_MASK                  # rw_centerangle (viewangle 0)
        top, bottom, texcol, frac0, step = _oracle_column_params(
            rm, scale, rca, RW_OFFSET, rwd, x, TW, CEIL_H, FLOOR_H, viewz, worldtop)
        for _ in range(2):   # call twice (R5 #8)
            body += [f"proj.column_render_params tp, bt, tc, f0, st, sc{k}, rca{k}, ro{k}, rd{k}, "
                     f"xx{k}, tw{k}, cf{k}, ff{k}, vz{k}, wt{k}, {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}",
                     "hex.print_as_digit 8, tp, 0", "stl.output 10",
                     "hex.print_as_digit 8, bt, 0", "stl.output 10",
                     "hex.print_as_digit 8, tc, 0", "stl.output 10",
                     "hex.print_as_digit 4, f0, 0", "stl.output 10",
                     "hex.print_as_digit 4, st, 0", "stl.output 10"]
        data += [f"sc{k}: hex.vec 8, {scale & 0xFFFFFFFF}", f"rca{k}: hex.vec 8, {rca & 0xFFFFFFFF}",
                 f"ro{k}: hex.vec 8, {RW_OFFSET & 0xFFFFFFFF}", f"rd{k}: hex.vec 8, {rwd & 0xFFFFFFFF}",
                 f"xx{k}: hex.vec 2, {x}", f"tw{k}: hex.vec 8, {TW}",
                 f"cf{k}: hex.vec 8, {(CEIL_H << 16) & 0xFFFFFFFF}", f"ff{k}: hex.vec 8, {(FLOOR_H << 16) & 0xFFFFFFFF}",
                 f"vz{k}: hex.vec 8, {viewz & 0xFFFFFFFF}", f"wt{k}: hex.vec 8, {worldtop & 0xFFFFFFFF}"]
        expected += (f"{top & 0xFFFFFFFF:08x}\n{bottom & 0xFFFFFFFF:08x}\n{texcol & 0xFFFFFFFF:08x}\n"
                     f"{frac0:04x}\n{step:04x}\n").encode() * 2
    data += ["tp: hex.vec 8", "bt: hex.vec 8", "tc: hex.vec 8", "f0: hex.vec 4", "st: hex.vec 4",
             generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N),
             generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")
    p = tmp_path / "column_render_params.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "column_render_params: fj output != oracle"


# ── proj.point_on_side (R_PointOnSide / mapcompiler._point_side): the BSP partition side test ──
# back = 1 iff dx*(vy-py) - dy*(vx-px) > 0 (the "back/left" side; on-the-line and front -> 0). This is
# the geometry primitive the BSP-as-code walk branches on (opt #7). Computed at 10 nibbles (40-bit
# signed): int16 map coords -> |cross product| <= 2^32, so it never overflows 40-bit signed and the fj
# sign matches the oracle's full-precision sign byte-exact. Hand cases hit both signs, the on-the-line
# (==0 -> front) case, negative dx/dy, and large magnitudes; then real baked E1M1 nodes.
HAND_SIDE_CASES = [
    # (px, py, dx, dy, vx, vy)
    (0, 0, 0, 1, 5, 0),            # vertical partition, viewer on the right (front) -> 0
    (0, 0, 0, 1, -5, 0),           # viewer on the left (back) -> 1
    (0, 0, 1, 0, 5, 0),            # horizontal partition, viewer ON the line (==0 -> front) -> 0
    (10, 20, -3, -4, 0, 0),        # negative dx,dy -> +20 -> 1
    (10, 20, -3, -4, 100, 100),    # -> +120 -> 1
    (10, 20, -3, -4, -100, -100),  # -> -80 -> 0
    (32000, -32000, 30000, 25000, -30000, 31000),     # large magnitude (40-bit width stress)
    (-32000, 32000, -30000, -25000, 30000, -31000),
]


def test_point_on_side_byte_exact_vs_oracle(tmp_path):
    """proj.point_on_side's sign matches mapcompiler._point_side (>0 -> back) byte-exact, over hand
    cases (both signs / on-the-line / negative dx,dy / large magnitude) and real baked E1M1 nodes
    (root + a spread of indices) from several viewpoints. Each case run twice (R5 #8)."""
    cmap = bake_bsp(WadFile.from_path(E1M1_WAD), "E1M1")
    node_idxs = [cmap.root, 0, 100, 300, len(cmap.nodes) - 1]
    viewpoints = [(-416, 256), (0, 256), (256, -256), (2048, -3680)]
    cases = list(HAND_SIDE_CASES)
    for ni in node_idxs:
        n = cmap.nodes[ni]
        cases += [(n.x, n.y, n.dx, n.dy, vx, vy) for vx, vy in viewpoints]

    body, data, expected = [], [], b""
    for k, (px, py, dx, dy, vx, vy) in enumerate(cases):
        for _ in range(2):   # call twice per case (R5 #8)
            body += [f"proj.point_on_side b, vx{k}, vy{k}, "
                     f"{px & MASK40}, {py & MASK40}, {dx & MASK40}, {dy & MASK40}",
                     "hex.print_as_digit 1, b, 0", "stl.output 10"]
        data += [f"vx{k}: hex.vec 10, {vx & MASK40}", f"vy{k}: hex.vec 10, {vy & MASK40}"]
        back = 1 if _point_side(px, py, dx, dy, vx, vy) > 0 else 0
        expected += f"{back}\n".encode() * 2
    data.append("b: hex.vec 2")
    _run(tmp_path, "point_on_side", body, data, expected)
