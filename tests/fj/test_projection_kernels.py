"""M12m+ (F5) — the runtime projection kernels in FlipJump (src/fj/projection.fj), each byte-exact vs the
H5 oracle (reference_model). proj.slope_div is R_PointToAngle's SlopeDiv: the tantoangle index for a
slope num/den. Driven over a spread of 16.16 magnitudes (small den / normal / clamp / boundary) twice
each (R5 #8), compared to ReferenceModel._slope_div — so the fj angle math and the oracle agree (D12)."""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_tantoangle_lut_fj, generate_trig_idioms_fj
from doomfj.reference_model import ReferenceModel, SLOPERANGE

PROJECTION_FJ = Path("src/fj/projection.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")   # provides hex.read_table + hex.fixed_div


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
