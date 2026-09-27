"""M7 P1.2 — the player's collision CELLS in fj, byte-exact against `ReferenceModel.check_position`.

`doomfj.collision.collision_cells_fj` emits the routine the game runs: a jump tree on the 16.16
centre to its 32-unit cell, a stub per distinct line list, a stub per line that xors its constants
into argument cells around ONE shared `sim.line_test`, and a door line's stub reading its door's
`dstate`. These tests assemble THAT text for E1M1 -- all 1,175 linedefs, all 13 doors -- in a program
of a few seconds, and require the fj answer (verdict AND both opening heights) to equal the
oracle's, which is the contract the whole project runs on.

⚠ ONE IMAGE, MANY CALLS (R5's call-twice rule). Every sample in a test runs in the same image, one
record after another. A line stub that xored a constant in and not out, or a return register left
dirty, corrupts the NEXT call -- a fresh image per position could never see it.

⚠ THE CONTROLS. Every assertion here passes against a routine that always answered "legal" unless
the sample holds refusals, so each test requires them; the door test requires verdicts that move
with the door; and `test_a_routine_missing_one_line_is_caught` assembles a mutated routine that has
lost one line from one cell and requires the harness to catch it.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.collision import (CELL_SHIFT, COLLISION_STATE_DECLS, cell_lists, cell_of,
                              collision_cells_fj, line_rows)
from doomfj.config import Config
from doomfj.doorcode import door_line_ids
from doomfj.doors import door_states, pass_state
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp, seg_sector
from doomfj.reference_model import (MAX_STEP, ML_BLOCKING, PLAYER_HEIGHT, PLAYER_RADIUS,
                                    ReferenceModel, SimState, apply_sector_heights, build_scene,
                                    scene_sectors, spawn_state)
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
FIXP = Path("src/fj/fixed_point.fj")
SIM = Path("src/fj/sim.fj")
U = 1 << 16
M32 = 0xFFFFFFFF


class Level:
    """E1M1 as the game tier builds its collision: door lines take the OPEN opening, and a door's
    blocking is its state against its pass state."""

    def __init__(self):
        self.wad = WadFile.from_path(E1M1)
        self.cmap = bake_bsp(self.wad, "E1M1")
        self.lds, self.sds = self.wad.linedefs("E1M1"), self.wad.sidedefs("E1M1")
        self.secs = self.wad.sectors("E1M1")
        self.rm = ReferenceModel(Config())
        tbl = door_states(self.secs, self.lds, self.sds)
        self.order = sorted(tbl)
        self.nstates = [len(tbl[si]) for si in self.order]
        self.lines_of = door_line_ids(self.secs, self.lds, self.sds, tbl)
        self.passes = [pass_state(self.secs, self.lds, self.sds, si) for si in self.order]
        self.open_h = {si: (self.secs[si].floor_h, tbl[si][-1]) for si in self.order}
        self.rows = line_rows(self.lds, self.cmap.vertexes, self.secs, self.sds, ML_BLOCKING,
                              secs_open=apply_sector_heights(self.secs, self.open_h),
                              door_line_ids={li for v in self.lines_of.values() for li in v})
        self.lists = cell_lists(self.rows, PLAYER_RADIUS)
        self.doors = {}
        for d, si in enumerate(self.order):
            for li in self.lines_of.get(si, ()):
                self.doors.setdefault(li, []).append((d, self.passes[d]))
        self._scenes = {}

    def scene(self, states):
        shut = frozenset(li for d, si in enumerate(self.order) if states[d] < self.passes[d]
                         for li in self.lines_of.get(si, ()))
        if shut not in self._scenes:
            self._scenes[shut] = build_scene(self.wad, self.wad, "E1M1", self.open_h, shut)
        return self._scenes[shut]

    def seed(self, scene, x16, y16):
        ss = self.cmap.subsectors[self.rm.point_in_subsector(self.cmap, x16 >> 16, y16 >> 16)]
        sec = seg_sector(self.lds, self.sds, scene_sectors(scene), self.cmap.segs[ss.firstseg])
        return sec.floor_h, sec.ceil_h

    def extent(self):
        xs = [v[0] for v in self.cmap.vertexes]
        ys = [v[1] for v in self.cmap.vertexes]
        return min(xs), max(xs), min(ys), max(ys)


@pytest.fixture(scope="module")
def level():
    return Level()


def _door_bytes(states, n):
    nib = list(states) + [0] * (2 * ((n + 1) // 2) - len(states))
    return bytes(nib[2 * i] | (nib[2 * i + 1] << 4) for i in range(len(nib) // 2))


def _assemble(tmp, lvl, body, extra_inputs, lists=None, name="cells"):
    """A loop over records (`0xD0`, the inputs, the 13 door states) until a 0 magic byte, running
    `body` on each against ONE cell routine; `lists` overrides the routine's lists (the control)."""
    cells, root = collision_cells_fj("e1m1", lvl.rows, lists or lvl.lists, doors=lvl.doors)
    nd = len(lvl.order)
    prog = "\n".join([
        "stl.startup_and_init_all",
        f"hex.set 8, cprad, {PLAYER_RADIUS}",
        "loop:",
        "hex.input 1, wmagic",
        "hex.if0 2, wmagic, done",
        *[f"hex.input 4, {r}" for r in extra_inputs],
        f"hex.input {(nd + 1) // 2}, dstate",
        *[ln.replace("ROOT", root) for ln in body],
        ";loop",
        "done:",
        "stl.loop",
        cells,
        "wmagic: hex.vec 2", f"dstate: hex.vec {2 * ((nd + 1) // 2)}",
        *[f"{r}: hex.vec 8" for r in extra_inputs if r not in {d.split(":")[0] for d in COLLISION_STATE_DECLS}],
        *COLLISION_STATE_DECLS,
    ]) + "\n"
    src = tmp / f"{name}.fj"
    src.write_text(prog, encoding="utf-8")
    out = tmp / f"{name}.fjm"
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")        # sim.fj's pad constants
    fj.assemble([consts.resolve(), FIXP.resolve(), SIM.resolve(), src.resolve()], out,
                memory_width=W, print_time=False)
    return out


CHECK_BODY = ["sim.check_cells ROOT",
              "hex.print_as_digit 1, cp_ok, 0", "stl.output 10",
              "hex.print_as_digit 8, cp_floor, 0", "stl.output 10",
              "hex.print_as_digit 8, cp_ceil, 0", "stl.output 10"]


@pytest.fixture(scope="module")
def cells_fjm(tmp_path_factory, level):
    return _assemble(tmp_path_factory.mktemp("cells"), level, CHECK_BODY,
                     ["cpx", "cpy", "cp_seedf", "cp_seedc"])


def _sg(h):
    v = int(h, 16)
    return v - (1 << 32) if v >> 31 else v


def _check_all(fjm, lvl, samples):
    """samples: [(x16, y16, door states)] -> (fj answers, oracle answers), ONE run for all of them"""
    feed, want = b"", []
    for x16, y16, states in samples:
        scene = lvl.scene(states)
        sf, sc = lvl.seed(scene, x16, y16)
        feed += bytes([0xD0]) + struct.pack("<IIII", x16 & M32, y16 & M32, sf & M32, sc & M32)
        feed += _door_bytes(states, len(lvl.order))
        want.append(lvl.rm.check_position(scene, x16, y16))
    io = FixedIO(feed + bytes([0]))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    out = io.get_output(allow_incomplete_output=True).decode().split("\n")
    got = [(int(out[3 * k], 16) == 1, _sg(out[3 * k + 1]), _sg(out[3 * k + 2]))
           for k in range(len(samples))]
    return got, want


POSITIONS = [
    (-416, 256), (-416, 300), (-300, 256), (664, 291), (1272, -724), (1869, 479),
    (1024, 1024), (0, 0), (2173, 2029), (343, 128), (-267, 1458), (909, 2120),
]


def test_the_cell_routine_matches_the_oracle(cells_fjm, level):
    """Fixed positions, random ones (integer and fractional), and the 16.16 corners of a sample of
    lined cells -- the exact values where one cell hands over to the next -- with every door shut."""
    rng = random.Random(14)
    x0, x1, y0, y1 = level.extent()
    shut = [0] * len(level.order)
    pts = [(x << 16, y << 16) for x, y in POSITIONS]
    pts += [((rng.randint(x0, x1) << 16) + rng.choice((0, 0x8000, 0x4001)),
             (rng.randint(y0, y1) << 16) + rng.choice((0, 0x8000, 0xBFFF))) for _ in range(400)]
    S = 1 << CELL_SHIFT
    for cx, cy in rng.sample(sorted(level.lists), 60):
        pts += [(x, y) for x in (cx * S, cx * S + S - 1) for y in (cy * S, cy * S + S - 1)]
    got, want = _check_all(cells_fjm, level, [(x, y, shut) for x, y in pts])
    bad = [(k, pts[k][0] / U, pts[k][1] / U, g, w) for k, (g, w) in enumerate(zip(got, want)) if g != w]
    assert not bad, bad[:5]
    refused = sum(not w[0] for w in want)
    assert refused >= 40, f"only {refused} refused positions in the sample -- too weak"


def test_the_door_lines_follow_their_doors_states(cells_fjm, level):
    """A box centred ON each door line, with every door in a random state, several times over: the
    verdict must follow the door exactly as the oracle's `blocked_lines` does, and must MOVE -- a
    routine that ignored `dstate` would pass the test above untouched."""
    rng = random.Random(3)
    samples = []
    for li in sorted(level.doors):
        (x1, y1), (x2, y2) = level.cmap.vertexes[level.lds[li].v1], level.cmap.vertexes[level.lds[li].v2]
        for _ in range(4):
            states = [rng.randrange(n) for n in level.nstates]
            samples.append((((x1 + x2) // 2) << 16, ((y1 + y2) // 2) << 16, states))
    got, want = _check_all(cells_fjm, level, samples)
    assert got == want, [(k, g, w) for k, (g, w) in enumerate(zip(got, want)) if g != w][:5]
    verdicts = {}
    for (x, y, _st), w in zip(samples, want):
        verdicts.setdefault((x, y), set()).add(w[0])
    moved = sum(v == {True, False} for v in verdicts.values())
    assert moved >= 10, f"only {moved} door lines changed verdict with their door"


def test_a_walked_trajectory_matches_too(cells_fjm, level):
    """The sim's own fractional positions along a walk from the spawn."""
    sp = spawn_state(level.wad, "E1M1")
    st = SimState(sp.x, sp.y, sp.angle, "E1M1")
    shut = [0] * len(level.order)
    scene = level.scene(shut)
    samples = []
    for tic in range(60):
        st = level.rm.step_sim(st, {"turn_left": True} if tic % 7 == 6 else {"forward": True},
                               scene=scene)
        samples.append((st.x, st.y, shut))
    got, want = _check_all(cells_fjm, level, samples)
    assert got == want, [(k, g, w) for k, (g, w) in enumerate(zip(got, want)) if g != w][:5]


def test_a_routine_missing_one_line_is_caught(tmp_path, level):
    """R9: the harness must be able to say no. Find a refused position, drop the line that refuses
    it from its cell's list, assemble THAT routine, and require the fj answer to differ from the
    oracle there -- through the same `_check_all` every test above trusts."""
    from doomfj.collision import check_position_cells
    x0, x1, y0, y1 = level.extent()
    rng = random.Random(9)
    shut = [0] * len(level.order)
    scene = level.scene(shut)
    for _ in range(4000):
        x16, y16 = rng.randint(x0, x1) << 16, rng.randint(y0, y1) << 16
        cell = (cell_of(x16), cell_of(y16))
        if cell not in level.lists or level.rm.check_position(scene, x16, y16)[0]:
            continue
        sf, sc = level.seed(scene, x16, y16)
        for li in level.lists[cell]:
            lists = dict(level.lists)
            lists[cell] = tuple(x for x in lists[cell] if x != li)
            if check_position_cells(level.rows, lists, x16, y16, PLAYER_RADIUS, sf, sc)[0]:
                break                                  # without li the model says legal: li refuses it
        else:
            continue
        break
    else:
        pytest.fail("no refused position found whose refusal rests on one line")
    fjm = _assemble(tmp_path, level, CHECK_BODY, ["cpx", "cpy", "cp_seedf", "cp_seedc"],
                    lists=lists, name="mutant")
    got, want = _check_all(fjm, level, [(x16, y16, shut)])
    assert not want[0][0] and got[0][0], (
        f"dropping line {li} from cell {cell} was not caught at ({x16 / U}, {y16 / U}): fj {got}")


@pytest.fixture(scope="module")
def trymove_fjm(tmp_path_factory, level):
    """`sim.try_move`: the cell check plus P_TryMove's two extra refusals -- the opening must fit
    the thing, and the floor must not be more than MAX_STEP above the one being left."""
    return _assemble(tmp_path_factory.mktemp("simtry"), level,
                     [f"sim.try_move ROOT, {PLAYER_HEIGHT >> 16}, {MAX_STEP >> 16}, herf",
                      "hex.print_as_digit 1, mv_ok, 0", "stl.output 10"],
                     ["cpx", "cpy", "cp_seedf", "cp_seedc", "herf"], name="try")


def test_try_move_matches_the_oracle(trymove_fjm, level):
    """⚠ The sample must contain REFUSED moves -- a `try_move` that always said yes would otherwise
    pass, and "always yes" is exactly what a walker with no collision does."""
    rng = random.Random(14)
    x0, x1, y0, y1 = level.extent()
    shut = [0] * len(level.order)
    scene = level.scene(shut)
    pts = [(-416, 256), (664, 291), (1272, -724), (1869, 479), (343, 128)]
    pts += [(rng.randint(x0, x1), rng.randint(y0, y1)) for _ in range(60)]
    feed, want = b"", []
    for x, y in pts:
        x16, y16 = x << 16, y << 16
        here = level.rm.check_position(scene, x16, y16)
        if not here[0]:
            continue                                   # the sim only ever steps off legal ground
        for dx, dy in ((50 << 16, 0), (0, 50 << 16), (-50 << 16, -50 << 16), (13 << 16, 7 << 16)):
            nx, ny = x16 + dx, y16 + dy
            sf, sc = level.seed(scene, nx, ny)
            feed += bytes([0xD0]) + struct.pack("<IIIII", nx & M32, ny & M32, sf & M32, sc & M32,
                                                here[1] & M32)
            feed += _door_bytes(shut, len(level.order))
            want.append(level.rm.try_move(scene, x16, y16, nx, ny))
    io = FixedIO(feed + bytes([0]))
    fj.run(trymove_fjm, io_device=io, print_time=False, print_termination=False)
    out = io.get_output(allow_incomplete_output=True).decode().split("\n")
    got = [out[k].strip() == "1" for k in range(len(want))]
    assert got == want, [(k, g, w) for k, (g, w) in enumerate(zip(got, want)) if g != w][:5]
    refused = sum(not w for w in want)
    assert refused >= 8 and len(want) >= 60, f"only {refused} of {len(want)} moves were refused"


# ── M14-e's critical path: exact point location, baked as code ─────────────────────────────────

@pytest.fixture(scope="module")
def ptloc_fjm(tmp_path_factory, level):
    from doomfj.collision import generate_point_location_fj, point_location_decls
    cmap = level.cmap
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
    rm, cmap = level.rm, level.cmap
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
