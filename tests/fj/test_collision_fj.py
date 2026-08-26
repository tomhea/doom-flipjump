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

from doomfj.collision import (LINE_BOX_BYTES, LINE_BOX_LEN, LINE_REST_BYTES,
                              LINE_REST_LEN, line_box, line_rest,
                              COLLISION_DECLS, CHECK_SCRATCH_DECLS, LineBake,
                              check_position_ops, line_scratch_decls)
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


# The RUNTIME path -- one block chosen by the program, with every (block, line) pair baked
# AS CODE -- was REMOVED 2026-08-26. It did not assemble (E1M1: 1,651 pairs x ~35 macro
# invocations ~ 57k lines, >50 min) and was superseded by the packed-table + runtime-loop
# shape the shipped binary runs -- which the `table_` tests below cover. The measurement and
# the reasoning it produced are in docs/opt-experiments.md. The two tests were
# @pytest.mark.skip, so they could never have announced a regression.


@pytest.fixture(scope="module")
def table_fjm(tmp_path_factory, level):
    """`sim.check_position` over the packed tables: the blockmap is indexed at RUNTIME, the block's
    line list and each line's row are READ, and `sim.check_line` executes DOOM's PIT_CheckLine with
    no compile-time specialisation. This is what bake-as-code was replaced by after it failed to
    assemble in 50 minutes -- note that this one assembles in seconds."""
    from doomfj.collision import (LINE_ROW_BYTES, LINE_ROW_LEN, block_tables, blockmap_grid,
                                  line_rows)
    from doomfj.lut_generator import generate_packed_lut_fj
    rm, scene, cmap, lds, sds, secs, grid = level
    rows = line_rows(lds, cmap.vertexes, secs, sds, ML_BLOCKING)
    bx0, by0, nbx, nby = blockmap_grid(grid)
    blocks, flat = block_tables(grid)

    def pack(vals, widths):
        v = sh = 0
        for x, nb in zip(vals, widths):
            v |= (x & ((1 << (8 * nb)) - 1)) << sh
            sh += 8 * nb
        return v

    prog = "\n".join([
        "stl.startup_and_init_all",
        "hex.input 1, wmagic", "hex.input 4, cpx", "hex.input 4, cpy",
        "hex.input 4, cp_seedf", "hex.input 4, cp_seedc",
        f"hex.set 8, cprad, {PLAYER_RADIUS}",
        f"sim.check_position bkoff, 4, bklin, 4, lnbox, lnrow, 3, {nbx}, {nby}, {bx0}, {by0}",
        "hex.print_as_digit 1, cp_ok, 0", "stl.output 10",
        "hex.print_as_digit 8, cp_floor, 0", "stl.output 10",
        "hex.print_as_digit 8, cp_ceil, 0", "stl.output 10",
        "stl.loop",
        "wmagic: hex.vec 2", "cpx: hex.vec 8", "cpy: hex.vec 8", "cprad: hex.vec 8",
        "cbx_lo: hex.vec 8", "cbx_hi: hex.vec 8", "cby_lo: hex.vec 8", "cby_hi: hex.vec 8",
        "cp_ok: hex.vec 1", "cp_floor: hex.vec 8", "cp_ceil: hex.vec 8",
        "cp_seedf: hex.vec 8", "cp_seedc: hex.vec 8",
        # the check_block/check_line scratch, from its single definition
        *CHECK_SCRATCH_DECLS,
        generate_packed_lut_fj("lnbox", [pack(line_box(r), LINE_BOX_BYTES) for r in rows],
                               LINE_BOX_LEN),
        generate_packed_lut_fj("lnrow", [pack(line_rest(r), LINE_REST_BYTES) for r in rows],
                               LINE_REST_LEN),
        generate_packed_lut_fj("bkoff", [pack(b, (2, 1)) for b in blocks], 3),
        generate_packed_lut_fj("bklin", list(flat), 2),
    ]) + "\n"
    d = tmp_path_factory.mktemp("simpos")
    src = d / "p.fj"
    src.write_text(prog, encoding="utf-8")
    out = d / "p.fjm"
    fj.assemble([FIXP.resolve(), Path("src/fj/sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    return out


def _run_table(table_fjm, level, x16, y16):
    import struct
    rm, _scene, cmap, lds, sds, secs, _grid = level
    sf, sc = _seed(rm, cmap, lds, sds, secs, x16, y16)
    io = FixedIO(bytes([0xD0]) + struct.pack("<IIII", x16 & 0xFFFFFFFF, y16 & 0xFFFFFFFF,
                                             sf & 0xFFFFFFFF, sc & 0xFFFFFFFF))
    fj.run(table_fjm, io_device=io, print_time=False, print_termination=False)
    b, f, c = io.get_output(allow_incomplete_output=True).decode().split("\n")[:3]

    def sg(h):
        v = int(h, 16)
        return v - (1 << 32) if v >> 31 else v

    return int(b, 16) == 1, sg(f), sg(c)


def test_table_check_position_matches_the_oracle(table_fjm, level):
    """⚠ The sample must contain REFUSED positions, or this proves only that open space is open."""
    import random
    rm, scene, cmap, *_ = level
    rng = random.Random(14)
    xs = [v[0] for v in cmap.vertexes]
    ys = [v[1] for v in cmap.vertexes]
    pts = list(POSITIONS) + [(rng.randint(min(xs), max(xs)), rng.randint(min(ys), max(ys)))
                             for _ in range(40)]
    refused = 0
    for x, y in pts:
        for fx, fy in ((0, 0), (0x8000, 0x4000)):        # integer AND fractional
            x16, y16 = (x << 16) + fx, (y << 16) + fy
            want = rm.check_position(scene, x16, y16)
            refused += not want[0]
            assert _run_table(table_fjm, level, x16, y16) == want,                 f"({x16 / U:.3f},{y16 / U:.3f})"
    assert refused >= 8, f"only {refused} refused positions in the sample -- too weak"


def test_table_check_position_on_a_walked_trajectory(table_fjm, level):
    from doomfj.reference_model import SimState, spawn_state
    rm, scene, *_ = level
    sp = spawn_state(scene.map_wad, "E1M1")
    st = SimState(sp.x, sp.y, sp.angle, "E1M1")
    for tic in range(30):
        st = rm.step_sim(st, {"turn_left": True} if tic % 7 == 6 else {"forward": True},
                         scene=scene)
        assert _run_table(table_fjm, level, st.x, st.y) == rm.check_position(scene, st.x, st.y),             f"tic {tic}"


@pytest.fixture(scope="module")
def trymove_fjm(tmp_path_factory, level):
    """`sim.try_move`: check_position plus P_TryMove's two extra refusals — the opening must fit
    the thing, and the floor must not be more than MAX_STEP above the one being left."""
    from doomfj.collision import (LINE_ROW_BYTES, LINE_ROW_LEN, block_tables, blockmap_grid,
                                  line_rows)
    from doomfj.lut_generator import generate_packed_lut_fj
    from doomfj.reference_model import MAX_STEP, PLAYER_HEIGHT
    _rm, _scene, cmap, lds, sds, secs, grid = level
    rows = line_rows(lds, cmap.vertexes, secs, sds, ML_BLOCKING)
    bx0, by0, nbx, nby = blockmap_grid(grid)
    blocks, flat = block_tables(grid)

    def pack(vals, widths):
        v = sh = 0
        for x, nb in zip(vals, widths):
            v |= (x & ((1 << (8 * nb)) - 1)) << sh
            sh += 8 * nb
        return v

    prog = "\n".join([
        "stl.startup_and_init_all",
        "hex.input 1, wmagic", "hex.input 4, cpx", "hex.input 4, cpy",
        "hex.input 4, cp_seedf", "hex.input 4, cp_seedc", "hex.input 4, herf",
        f"hex.set 8, cprad, {PLAYER_RADIUS}",
        f"sim.try_move bkoff, 4, bklin, 4, lnbox, lnrow, 3, {nbx}, {nby}, {bx0}, {by0}, "
        f"{PLAYER_HEIGHT >> 16}, {MAX_STEP >> 16}, herf",
        "hex.print_as_digit 1, mv_ok, 0", "stl.output 10", "stl.loop",
        "wmagic: hex.vec 2", "cpx: hex.vec 8", "cpy: hex.vec 8", "cprad: hex.vec 8",
        "cbx_lo: hex.vec 8", "cbx_hi: hex.vec 8", "cby_lo: hex.vec 8", "cby_hi: hex.vec 8",
        "cp_ok: hex.vec 1", "cp_floor: hex.vec 8", "cp_ceil: hex.vec 8",
        "cp_seedf: hex.vec 8", "cp_seedc: hex.vec 8", "herf: hex.vec 8", "mv_ok: hex.vec 1",
        # the check_block/check_line scratch, from its single definition
        *CHECK_SCRATCH_DECLS,
        generate_packed_lut_fj("lnbox", [pack(line_box(r), LINE_BOX_BYTES) for r in rows],
                               LINE_BOX_LEN),
        generate_packed_lut_fj("lnrow", [pack(line_rest(r), LINE_REST_BYTES) for r in rows],
                               LINE_REST_LEN),
        generate_packed_lut_fj("bkoff", [pack(b, (2, 1)) for b in blocks], 3),
        generate_packed_lut_fj("bklin", list(flat), 2),
    ]) + "\n"
    d = tmp_path_factory.mktemp("simtry")
    src = d / "t.fj"
    src.write_text(prog, encoding="utf-8")
    out = d / "t.fjm"
    fj.assemble([FIXP.resolve(), Path("src/fj/sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    return out


def test_try_move_matches_the_oracle(trymove_fjm, level):
    """⚠ The sample must contain REFUSED moves — a `try_move` that always said yes would otherwise
    pass, and "always yes" is exactly what a walker with no collision does."""
    import random
    import struct
    rm, scene, cmap, lds, sds, secs, _grid = level
    rng = random.Random(14)
    xs = [v[0] for v in cmap.vertexes]
    ys = [v[1] for v in cmap.vertexes]
    pts = [(-416, 256), (664, 291), (1272, -724), (1869, 479), (343, 128)]
    pts += [(rng.randint(min(xs), max(xs)), rng.randint(min(ys), max(ys))) for _ in range(35)]
    refused = tot = 0
    for x, y in pts:
        x16, y16 = x << 16, y << 16
        here = rm.check_position(scene, x16, y16)
        if not here[0]:
            continue                                   # the sim only ever steps off legal ground
        for dx, dy in ((50 << 16, 0), (0, 50 << 16), (-50 << 16, -50 << 16), (13 << 16, 7 << 16)):
            nx, ny = x16 + dx, y16 + dy
            sf, sc = _seed(rm, cmap, lds, sds, secs, nx, ny)
            io = FixedIO(bytes([0xD0]) + struct.pack(
                "<IIIII", nx & 0xFFFFFFFF, ny & 0xFFFFFFFF, sf & 0xFFFFFFFF, sc & 0xFFFFFFFF,
                here[1] & 0xFFFFFFFF))
            fj.run(trymove_fjm, io_device=io, print_time=False, print_termination=False)
            got = io.get_output(allow_incomplete_output=True).decode().split("\n")[0].strip() == "1"
            want = rm.try_move(scene, x16, y16, nx, ny)
            assert got == want, f"({x},{y}) -> ({nx / U:.2f},{ny / U:.2f}): fj {got} oracle {want}"
            tot += 1
            refused += not want
    assert refused >= 8, f"only {refused} of {tot} moves were refused -- the sample is too weak"


# ── M14-e's critical path: exact point location, baked as code ─────────────────────────────────

@pytest.fixture(scope="module")
def ptloc_fjm(tmp_path_factory, level):
    from doomfj.collision import generate_point_location_fj, point_location_decls
    _rm, _scene, cmap, *_ = level
    prog = "\n".join([
        "stl.startup_and_init_all",
        "hex.input 1, wmagic", "hex.input 2, inx", "hex.input 2, iny",   # 2 BYTES = 4 nibbles
        # sign-extend the int16 inputs into the 10-nibble signed working width
        "hex.zero 10, ptx", "hex.mov 4, ptx, inx", "hex.sign 4, inx, xn, xp",
        "xn:", "hex.set 6, ptx + 4*dw, 0xFFFFFF", "xp:",
        "hex.zero 10, pty", "hex.mov 4, pty, iny", "hex.sign 4, iny, yn, yp",
        "yn:", "hex.set 6, pty + 4*dw, 0xFFFFFF", "yp:",
        "stl.fcall ptloc_walk, ptloc_ret",
        "hex.print_as_digit 4, ptss, 0", "stl.output 10", "stl.loop",
        "wmagic: hex.vec 2", "inx: hex.vec 4", "iny: hex.vec 4",
        *point_location_decls(),
        generate_point_location_fj(cmap),
    ]) + "\n"
    d = tmp_path_factory.mktemp("ptloc")
    src = d / "p.fj"
    src.write_text(prog, encoding="utf-8")
    out = d / "p.fjm"
    fj.assemble([FIXP.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    return out


def test_baked_point_location_matches_point_in_subsector(ptloc_fjm, level):
    """M14-e needs "which subsector is this point in?" once per moved thing. Reusing
    `_bsp_descend_code` was PRICED and rejected (~2.9M ops a descent, ~730M for 251 things against a
    ~40M frame). Baking the descent makes 61% of E1M1's partitions multiply-free, and it stays
    EXACT -- no grid approximation, so no question about which leaf owns a thing near a boundary.

    The sample deliberately includes VERTICES, which sit exactly on partition lines: that is where
    `_point_side`'s "on the line counts as front" convention has to be reproduced, and where an
    approximate scheme would differ."""
    import random
    import struct
    rm, _scene, cmap, *_ = level
    rng = random.Random(14)
    xs = [v[0] for v in cmap.vertexes]
    ys = [v[1] for v in cmap.vertexes]
    pts = [(v[0], v[1]) for v in cmap.vertexes[:8]]
    pts += [(rng.randint(min(xs), max(xs)), rng.randint(min(ys), max(ys))) for _ in range(12)]
    for x, y in pts:
        io = FixedIO(bytes([0xD0]) + struct.pack("<hh", x, y))
        fj.run(ptloc_fjm, io_device=io, print_time=False, print_termination=False)
        got = int(io.get_output(allow_incomplete_output=True).decode().split("\n")[0], 16)
        assert got == rm.point_in_subsector(cmap, x, y), f"({x},{y}): fj ss{got}"
