"""M14-d — line collision IN FJ, byte-exact against `ReferenceModel.check_position`.

`doomfj.collision` bakes each linedef's PIT_CheckLine as straight-line fj, with the slope switch,
the parity flips, the blocking rules and the two sector openings all resolved at compile time. This
drives that generated code over real E1M1 geometry and requires the fj answer -- blocked flag AND
both opening heights -- to equal the oracle's, which is the contract the whole project runs on.

It assembles in seconds because it bakes only the lines the blockmap selects, exactly as the
emitted renderer will. That is deliberate: the sim's collision must be debuggable without a
25-minute renderer build, the same way `test_state_wire.py` made the player tic debuggable.

⚠ `test_positions_that_are_actually_blocked` is the CONTROL. Every other assertion here passes if
the generated code says "legal" unconditionally -- most of the map is open space. That test demands
the sample contain genuinely refused positions and that fj refuses exactly those.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.collision import (COLLISION_DECLS, LineBake, check_position_ops, line_scratch_decls)
from doomfj.config import Config
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp, blockmap_candidates, build_blockmap, seg_sector
from doomfj.reference_model import ML_BLOCKING, PLAYER_RADIUS, ReferenceModel, build_scene
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
FIXP = Path("src/fj/fixed_point.fj")
U = 1 << 16


@pytest.fixture(scope="module")
def level():
    wad = WadFile.from_path(E1M1)
    cmap = bake_bsp(wad, "E1M1")
    lds, sds, secs = wad.linedefs("E1M1"), wad.sidedefs("E1M1"), wad.sectors("E1M1")
    return (ReferenceModel(Config()), build_scene(wad, wad, "E1M1"), cmap, lds, sds, secs,
            build_blockmap(cmap, lds))


def _seed(rm, cmap, lds, sds, secs, x, y):
    """P_CheckPosition's subsector seed for the opening, in map units."""
    ss = cmap.subsectors[rm.point_in_subsector(cmap, x >> 16, y >> 16)]
    sec = seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
    return sec.floor_h, sec.ceil_h


def _run_one(tmp_path, level, x16, y16, name):
    """Bake the blockmap's candidate lines for (x16, y16) and run the generated check."""
    rm, _scene, cmap, lds, sds, secs, grid = level
    cand = blockmap_candidates(grid, x16 >> 16, y16 >> 16, PLAYER_RADIUS >> 16)
    bakes = [LineBake(lds[i], cmap.vertexes, secs, sds, ML_BLOCKING) for i in cand]
    sf, sc = _seed(rm, cmap, lds, sds, secs, x16, y16)
    body = ([f"    hex.set 8, cpx, {x16 & 0xFFFFFFFF}", f"    hex.set 8, cpy, {y16 & 0xFFFFFFFF}"]
            + check_position_ops(bakes, radius=PLAYER_RADIUS, seed_floor=sf, seed_ceil=sc)
            + ["    hex.print_as_digit 1, cp_ok, 0", "    stl.output 10",
               "    hex.print_as_digit 8, cp_floor, 0", "    stl.output 10",
               "    hex.print_as_digit 8, cp_ceil, 0", "    stl.output 10"])
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
            + "\n".join(COLLISION_DECLS + line_scratch_decls(len(bakes))) + "\n")
    src = tmp_path / f"{name}.fj"
    src.write_text(prog, encoding="utf-8")
    out = tmp_path / f"{name}.fjm"
    fj.assemble([FIXP.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    ok, floorz, ceilz = io.get_output(allow_incomplete_output=True).decode().split("\n")[:3]

    def signed(h):
        v = int(h, 16)
        return v - (1 << 32) if v >> 31 else v

    return int(ok, 16) == 1, signed(floorz), signed(ceilz), len(bakes)


# a spread over E1M1: the spawn, open floor, positions hugging walls, and points in solid space
POSITIONS = [
    (-416, 256), (-416, 300), (-300, 256), (664, 291), (1272, -724), (1869, 479),
    (1024, 1024), (0, 0), (2173, 2029), (343, 128), (-267, 1458), (909, 2120),
]


@pytest.mark.parametrize("vx,vy", POSITIONS)
def test_check_position_matches_the_oracle(tmp_path, level, vx, vy):
    rm, scene, _cmap, _lds, _sds, _secs, _grid = level
    got_ok, got_f, got_c, nlines = _run_one(tmp_path, level, vx << 16, vy << 16, f"cp{vx}_{vy}")
    want_ok, want_f, want_c = rm.check_position(scene, vx << 16, vy << 16)
    assert (got_ok, got_f, got_c) == (want_ok, want_f, want_c), (
        f"({vx},{vy}) over {nlines} baked lines: fj {(got_ok, got_f, got_c)} != "
        f"oracle {(want_ok, want_f, want_c)}")


@pytest.mark.parametrize("frac", [0x4000, 0x8000, 0xC000])
def test_fractional_positions_match_too(tmp_path, level, frac):
    """The sim produces fractional positions from its second step, so the collision has to be
    exact there as well -- the same regime that hid the `wall_x_range_m` bug (section 4b)."""
    rm, scene, _cmap, _lds, _sds, _secs, _grid = level
    x16, y16 = (-416 << 16) + frac, (256 << 16) + frac
    got_ok, got_f, got_c, _n = _run_one(tmp_path, level, x16, y16, f"cpf{frac:x}")
    assert (got_ok, got_f, got_c) == rm.check_position(scene, x16, y16)


def test_positions_that_are_actually_blocked(tmp_path, level):
    """⚠ THE CONTROL. Most of the map is open, so every test above would pass against a generator
    that always answered "legal". Find positions the oracle REFUSES and require fj to refuse them
    too -- and require the sample to contain some, so the control cannot pass vacuously."""
    rm, scene, cmap, _lds, _sds, _secs, _grid = level
    xs = [v[0] for v in cmap.vertexes]
    ys = [v[1] for v in cmap.vertexes]
    blocked = []
    for x in range(min(xs), max(xs), 211):
        for y in range(min(ys), max(ys), 197):
            if not rm.check_position(scene, x << 16, y << 16)[0]:
                blocked.append((x, y))
    assert len(blocked) >= 8, f"only {len(blocked)} blocked positions found -- the control is weak"
    for i, (x, y) in enumerate(blocked[:8]):
        got_ok, got_f, got_c, _n = _run_one(tmp_path, level, x << 16, y << 16, f"cpb{i}")
        assert (got_ok, got_f, got_c) == rm.check_position(scene, x << 16, y << 16), \
            f"({x},{y}) is refused by the oracle; fj said {(got_ok, got_f, got_c)}"
