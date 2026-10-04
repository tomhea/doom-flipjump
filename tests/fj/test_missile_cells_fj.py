"""M7 P5 (doomfj.projcode): the MISSILE cells -- the third collision cell set (tag "mc6", radius FIREBALL_R) that
`pj_try` runs through `sim.check_cells` -- on the real flipjump engine against the model's `missile_lines_block`.

The points: for EVERY (cell, listed line) pair of the set, a point in that cell near that line (the line's point
nearest the cell's centre, jittered by up to 8 units with a random fraction, clamped into the cell) -- so every cell
runs, and every line from every cell that lists it, on both sides of the straddle. They run once at the level-start
states; the points of every cell that lists a DYNAMIC line (a door's, a lift's, the floor switch's) run again at every
state: config k puts every door and lift at min(k, its last state) and the switch at k & 1, k = 0 .. 9. The model's
heights are its own (`World._door_phase_scene`). ONE image, every record in turn (R5's call-twice rule): a stub that
leaves a constant xored in corrupts the next record.

R9: the lists built WITHOUT the margin (radius 0: a box straddling a line from the next cell is never tested) and the
player's door pass states (gap 56 instead of the fireball's 8: a door half open still stops the fireball) must part.
The coverage proof of the lists is host-side (tests/host/test_projcode.py).
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import projcode as PC
from doomfj.collision import CELL_SHIFT, COLLISION_STATE_DECLS, cell_lists
from doomfj.combat import FIREBALL_R
from doomfj.config import Config
from doomfj.doors import pass_state
from doomfj.harness import W
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
S = 1 << CELL_SHIFT
M32 = 0xFFFFFFFF
CONFIGS = 10


def _world():
    return World(monsters="full", player="full")


def _points(w):
    """[(config k, x16, y16)] -- the module docstring's records"""
    rnd = random.Random(0x5C6)
    rows, _doors = PC.missile_rows(w)
    lists = PC.missile_cell_lists(rows)
    dyn_secs = set(w.door_order) | set(w.lift_order) | set(w.switch)
    dyn_lines = {li for li, ld in enumerate(w.lds) if ld.back != -1
                 and {w.sds[ld.front].sector, w.sds[ld.back].sector} & dyn_secs}
    V = w.cmap.vertexes

    def near(cell, li):
        (cx, cy), ld = cell, w.lds[li]
        (ax, ay), (bx, by) = V[ld.v1], V[ld.v2]
        ax, ay, bx, by = ax << 16, ay << 16, bx << 16, by << 16
        mx, my = cx * S + S // 2, cy * S + S // 2
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((mx - ax) * dx + (my - ay) * dy) / (dx * dx + dy * dy)))
        qx, qy = int(ax + t * dx), int(ay + t * dy)
        qx += rnd.randint(-8 << 16, 8 << 16)
        qy += rnd.randint(-8 << 16, 8 << 16)
        return min(max(qx, cx * S), cx * S + S - 1), min(max(qy, cy * S), cy * S + S - 1)

    out = []
    dyn_cells = []
    for cell, lis in sorted(lists.items()):
        for li in lis:
            out.append((0, *near(cell, li)))
        if set(lis) & dyn_lines:
            dyn_cells.append(cell)
    for k in range(1, CONFIGS):
        for cell in dyn_cells:
            for li in lists[cell]:
                out.append((k, *near(cell, li)))
    return out


def _config(w, k):
    ws = w.ws
    for d, si in enumerate(w.door_order):
        ws.d_state[d] = min(k, w.door_nstates[si] - 1)
    for j, si in enumerate(w.lift_order):
        ws.l_state[j] = min(k, len(w.lift_stops[si]) - 1)
    ws.f_switch = k & 1
    w._door_phase_scene()


def _expected(w, pts) -> bytes:
    out, cur = [], None
    for k, x16, y16 in pts:
        if k != cur:
            _config(w, k)
            cur = k
        out.append("0" if w.missile_lines_block(x16, y16) else "1")
    return "".join(out).encode()


def _input(w, pts) -> bytes:
    nd, nl = len(w.door_order), len(w.lift_order)
    feed = b""
    for k, x16, y16 in pts:
        ds = [min(k, w.door_nstates[si] - 1) for si in w.door_order] + [0] * (nd & 1)
        ls = [min(k, len(w.lift_stops[si]) - 1) for si in w.lift_order] + [0] * (nl & 1)
        feed += bytes([0xD0]) + struct.pack("<II", x16 & M32, y16 & M32)
        feed += bytes(ds[2 * i] | ds[2 * i + 1] << 4 for i in range(len(ds) // 2))
        feed += bytes(ls[2 * i] | ls[2 * i + 1] << 4 for i in range(len(ls) // 2))
        feed += bytes([k & 1])
    return feed + bytes([0])


def _run(tmp_path, name, mut=None) -> bool:
    w = _world()
    pts = _points(w)
    want = _expected(w, pts)
    lists = doors = None
    if mut == "margin0":
        rows, _d = PC.missile_rows(w)
        lists = cell_lists(rows, 0, corner=False)
    elif mut == "playerpass":
        _rows, doors = PC.missile_rows(w)
        doors = {li: tuple((slot, p if isinstance(slot, str) else
                            pass_state(w.secs, w.lds, w.sds, w.door_order[slot])) for slot, p in v)
                 for li, v in doors.items()}
        assert any(p2 != p1 for li in doors for (_s, p2), (_s1, p1) in zip(doors[li], PC.missile_rows(w)[1][li]))
    cells, root = PC.missile_cells_fj(w, lists=lists, doors=doors)
    nd, nl = len(w.door_order), len(w.lift_order)
    prog = "\n".join([
        "stl.startup_and_init_all",
        "loop:",
        "hex.input 1, wmagic",
        "hex.if0 2, wmagic, done",
        "hex.input 4, cpx", "hex.input 4, cpy",
        "hex.input %d, dstate" % ((nd + 1) // 2), "hex.input %d, lstate" % ((nl + 1) // 2),
        "hex.input 1, fswitch",
        "hex.set 8, cprad, %d" % (FIREBALL_R << 16),
        "sim.check_cells %s" % root,
        "hex.print_as_digit 1, cp_ok, 0",
        ";loop",
        "done:",
        "stl.loop",
        cells,
        "wmagic: hex.vec 2", "dstate: hex.vec %d" % (2 * ((nd + 1) // 2)),
        "lstate: hex.vec %d" % (2 * ((nl + 1) // 2)), "fswitch: hex.vec 2",
        *COLLISION_STATE_DECLS]) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, _input(w, pts), want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_points_exercise_every_verdict():
    """the records hold refusals and passes, both at the level start and at the moving states, and door lines whose
    verdict moves with the door between the fireball's pass state and the player's (the `playerpass` control's
    bite) -- and margin points: a refusal by a line whose bbox misses the point's cell (the `margin0` control's)"""
    w = _world()
    pts = _points(w)
    want = _expected(w, pts).decode()
    assert want.count("0") > 500 and want.count("1") > 2000, (want.count("0"), want.count("1"))
    rows, _d = PC.missile_rows(w)
    m0 = cell_lists(rows, 0, corner=False)
    from doomfj.collision import cell_of
    margin, every = 0, w._lines
    _config(w, 0)
    for (k, x16, y16), v in zip(pts, want):
        if v == "0" and k == 0:                  # refused: would the margin-less cell's lines alone refuse?
            keep = set(m0.get((cell_of(x16), cell_of(y16)), ()))
            w._lines = [t for t in every if t[0] in keep]
            margin += not w.missile_lines_block(x16, y16)
            w._lines = every
    assert margin >= 5, margin
    assert len(set(k for k, _x, _y in pts)) == CONFIGS


def test_the_missile_cells_follow_the_model(tmp_path):
    assert _run(tmp_path, "mc6"), "the fj missile cells parted from the model's missile_lines_block"


@pytest.mark.parametrize("mut", ["margin0", "playerpass"])
def test_control_broken_missile_cells_are_caught(tmp_path, mut):
    assert not _run(tmp_path, "mc6_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
