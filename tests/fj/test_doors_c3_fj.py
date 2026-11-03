"""M8 C3 -- the door kinds E1M3..E1M9 need RUN in fj against doomfj.doors (the model every gate steps):

  * the door tic on every one of those maps' doors (`doorcode.door_tic_lines` with the map's keyed boxes, switch
    cards / latches / stay presses and close strides): the D1 key doors that stay open (32 / 33), E1M3 150's two
    sides (D1 31 keyless west, D1 32 blue east: front boxes), the SR 61 / 114 and S1 112 / 133 (blue) switches, E1M6's
    latched S1 103 on door 56 and E1M9's on DR door 135 (a STAY press: it opens for good, a DR press then closes it),
    the blazing raise 114 / 105, a close line's door closing at its stride and HOLDING on the player;
  * the WR lines (`doorcode.repeat_walk_lines`): 105 presses a door at rest, 75 / 107 start it closing;
  * E1M4 102's contact (a closing door a box fits inside: `door_contact_lines`' convex centre-inside test).
Nothing here is modelled: each program is the emitter's own text, fed records and read back; the expectation is
doomfj.doors.DoorPhase / touches_door. R9: MUTANTS -- one real edit of the emitted text each -- must each disagree.
The 46 GR shot doors are tests/fj/test_shot_doors_fj.py's."""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import doors as D
from doomfj.combat import PLAYER_R
from doomfj.config import Config
from doomfj.doorcode import WAIT_NIBBLES, door_contact_lines, door_decls, door_tic_lines, repeat_walk_lines
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FULL = ROOT / "assets" / "freedoom1.wad"
M32 = 0xFFFFFFFF
CARDS = ("pcard", "pcard_y", "pcard_r")
MAPS = ("E1M3", "E1M4", "E1M5", "E1M6", "E1M7", "E1M9")

pytestmark = pytest.mark.skipif(not FULL.exists(), reason="the full episode wad is not present")

_CACHE = {}


def _phase(m):
    if m not in _CACHE:
        mw = WadFile.from_path(str(FULL))
        secs, lds, sds = mw.sectors(m), mw.linedefs(m), mw.sidedefs(m)
        boxes = D.use_boxes_xy(secs, lds, sds, bake_bsp(mw, m).vertexes)
        dp = D.DoorPhase(secs, lds, sds, mw.vertexes(m), boxes)
        dp.secs, dp.lds, dp.sds, dp.verts = secs, lds, sds, mw.vertexes(m)
        _CACHE[m] = dp
    return _CACHE[m]


def _run(tmp, name, program, feed):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


def _mutated(lines, old, new):
    text = "\n".join(lines)
    assert text.count(old) >= 1, old
    return text.replace(old, new, 1).split("\n")


def _d(dp, si):
    return dp.order.index(si)


def _requested(dp):
    """the doors a request presses: W1, WR 105, GR 46 (doors.requested_doors)"""
    return D.requested_doors(dp.secs, dp.lds, dp.sds, dp.verts)


# ---- 1. the door tic ----------------------------------------------------------------------------------------------

def tic_lines(dp):
    return door_tic_lines(dp.order, dp.nstates, dp.boxes, dp.kinds, contact=dp.contact, passes=dp.passes,
                          switches=dp.switches, walked=_requested(dp), keyed=dp.keyed,
                          switch_info={si: [e[1:] for e in v] for si, v in dp.switch_info.items()},
                          nwalk=len(dp.triggers), close=dp.close)


def door_program(dp, text=None):
    nd, nf = len(dp.order), len(dp.triggers) + dp.nlatch
    tic = text if text is not None else tic_lines(dp)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, rbyte", "hex.mov 1, duse, rbyte"]
    for c in CARDS:
        body += ["hex.input 1, rbyte", f"hex.mov 1, {c}, rbyte"]
    for d in range(nd):
        body += ["hex.input 1, rbyte", f"hex.mov 1, dreq + {d}*dw, rbyte"]
    for d, si in enumerate(dp.order):
        # the harness's close injection (a WR close line crossed last move: doors.repeat_act / close_state) -- test
        # scaffolding, the emitter's own copy is repeat_walk_lines (section 2)
        body += ["hex.input 1, rbyte"]
        if si in dp.close:
            e = f"cj{d}"
            body += [f"hex.if0 1, rbyte, {e}_e", f"hex.if0 1, ddir + {d}*dw, {e}_a", f";{e}_e", f"{e}_a:",
                     f"hex.if0 {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw, {e}_b", f";{e}_e", f"{e}_b:",
                     f"hex.if0 1, dstate + {d}*dw, {e}_e", f"hex.set 1, ddir + {d}*dw, {D.CLOSING}",
                     f"hex.set 1, dsub + {d}*dw, {D.SPEED}", f"{e}_e:"]
    body += list(tic)
    for d in range(nd):
        body += _pr(f"dstate + {d}*dw", 1) + _pr(f"ddir + {d}*dw", 1) + _pr(f"dsub + {d}*dw", 1)
        body += _pr(f"dwait + {WAIT_NIBBLES * d}*dw", WAIT_NIBBLES) + _pr(f"dreq + {d}*dw", 1)
    for k in range(len(dp.triggers), nf):
        body += _pr(f"wfired + {k}*dw", 1)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
             "viewx: hex.vec 8", "viewy: hex.vec 8", "pcard_y: hex.vec 1, 0", "pcard_r: hex.vec 1, 0",
             *door_decls(nd, nf)]
    return "\n".join(body) + "\n"


def _area_box(dp, si):
    area = dp.contact[si][0]
    if area[0] == "poly":
        e = area[1]
        xs, ys = [p for q in e for p in (q[0], q[2])], [p for q in e for p in (q[1], q[3])]
        return min(xs), min(ys), max(xs), max(ys)
    return area


def door_schedule(dp, seed=7):
    """every use box, keyed box and switch box visited with no card, every card and each single card -- pressed from
    the box centre, then 12 frames in and around it with use now and then; then every door that closes (its own
    wait, or a close line: injected) stood in while it closes, the player on its lines; walk-over doors requested and
    close lines injected now and then throughout"""
    rng = random.Random(seed)
    # the keyed boxes first and the cards one at a time before all of them: a stay door opens ONCE a run, so the
    # first visit that can open it must be the one whose card is being tested
    visits = [(si, b) for si in dp.order for b, _c in dp.keyed.get(si, ())]
    visits += [(si, dp.boxes[si]) for si in dp.order if si in dp.boxes]
    visits += [(si, b) for si in dp.order for b in dp.switches.get(si, ())]
    walked = sorted(_requested(dp))
    out = []

    def frame(x, y, use, cards, rq=0.03, cl=0.05):
        req = {s for s in walked if rng.random() < rq}
        inj = {s for s in dp.close if rng.random() < cl}
        out.append(((x << 16) | rng.choice((0, 0x8000)), y << 16, use, cards, req, inj))
    for cards in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)):
        for si, (x0, y0, x1, y1) in visits:
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            for f in range(12):
                x, y = (cx, cy) if f < 3 else (rng.randint(x0 - 4, x1 + 4), rng.randint(y0 - 4, y1 + 4))
                frame(x, y, f < 2 or rng.random() < 0.15, cards)
    # a close line's door: opened from its repeatable switch, then closed (injected) with the player in it -- it holds
    for si in sorted(dp.close):
        b = next(b for b, _c, lt, _s in dp.switch_info[si] if lt is None)
        sx, sy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        x0, y0, x1, y1 = _area_box(dp, si)
        for f in range(3 + dp.nstates[si] + 2):
            frame(sx, sy, f < 3, (1, 1, 1), rq=0.0, cl=0.0)
        for f in range(30):
            out.append((((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16, False, (1, 1, 1), set(), {si}))
        for f in range(12):
            out.append((sx << 16, sy << 16, False, (1, 1, 1), set(), {si}))
    # closing doors with the player in them: open it (requests / injections / its box), then stand on it
    for si in dp.order:
        if D.door_stay(dp.kinds[si]) and si not in dp.close:
            continue
        x0, y0, x1, y1 = _area_box(dp, si)
        for f in range(70):
            x, y = rng.randint(x0 - 20, x1 + 20), rng.randint(y0 - 20, y1 + 20)
            frame(x, y, rng.random() < 0.1, (1, 1, 1), rq=0.05 if f < 30 else 0.0, cl=0.2 if f > 20 else 0.0)
    return out


def door_expect(dp, sched):
    st, want = dp.initial(), []
    nw = len(dp.triggers)
    for x16, y16, use, (b, yl, r), req, inj in sched:
        ds = dict(st[0])
        for si in inj:
            if D.repeat_act((si, "close"), ds[si]) == "close":
                ds[si] = D.close_state(ds[si])
        st = (ds, st[1], frozenset(req), st[3])
        st = dp.tic(st, use, x16, y16, has_blue=bool(b), has_yellow=bool(yl), has_red=bool(r))
        for si in dp.order:
            want += [*(v for v in st[0][si]), 0]
        want += list(st[1][nw:])
    return want


def door_feed(dp, sched):
    out = b""
    for x16, y16, use, cards, req, inj in sched:
        out += bytes([1]) + struct.pack("<II", x16 & M32, y16 & M32) + bytes([int(use), *cards])
        out += bytes(int(si in req) for si in dp.order) + bytes(int(si in inj) for si in dp.order)
    return out


def _rows(dp, want, nframes):
    per = 5 * len(dp.order) + dp.nlatch
    return [want[i * per:(i + 1) * per] for i in range(nframes)]


@pytest.mark.parametrize("m", MAPS)
def test_the_door_tic_runs_every_kind_as_DoorPhase(tmp_path, m):
    dp = _phase(m)
    sched = door_schedule(dp)
    got = _run(tmp_path, "doors", door_program(dp), door_feed(dp, sched))
    want = door_expect(dp, sched)
    assert len(got) == len(want)
    bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert not bad, (len(bad), bad[:5])
    rows = _rows(dp, want, len(sched))
    moved = {si for r in rows for d, si in enumerate(dp.order) if r[5 * d]}
    assert moved == set(dp.order), sorted(set(dp.order) - moved)     # not vacuous: every door moved


def test_the_cluster_kinds_are_where_the_survey_says():
    """the doors this file exercises are the ones C3 is for (a map edit would show here first)"""
    k3, k5, k6, k7, k9 = (_phase(m).kinds for m in ("E1M3", "E1M5", "E1M6", "E1M7", "E1M9"))
    assert k5[30] == "redstay" and k6[78] == "bluestay" and k9[149] == "redstay"
    assert k3[150] == "stay" and _phase("E1M3").keyed == {150: [((-1136, -24, -1072, 232), "blue")]}
    assert _phase("E1M3").boxes[150] == (-1216, -24, -1152, 232)            # the keyless D1 31's front box (west)
    assert k6[4] == "blaze" and k6[56] == "stay" and _phase("E1M6").close == {56: D.BLAZE_STRIDE}
    assert k7[528] == "blazestay" and k7[605] == "stay" and _phase("E1M7").close == {605: 1}
    assert k9[251] == "blazestay" and k9[135] == "plain" and k9[267] == "stay" and k9[184] == "stay"
    assert [e[1:] for e in _phase("E1M7").switch_info[528]] == [("blue", None, False)]
    assert [e[1:] for e in _phase("E1M6").switch_info[56]] == [(None, 0, False), (None, None, False)]
    assert [e[1:] for e in _phase("E1M9").switch_info[135]] == [(None, 0, True)]


def _drive(dp, frames):
    """DoorPhase over (x, y, use, cards) frames -> the states per frame"""
    st, out = dp.initial(), []
    for x, y, use, (b, yl, r) in frames:
        st = dp.tic(st, use, x << 16, y << 16, has_blue=bool(b), has_yellow=bool(yl), has_red=bool(r))
        out.append(st)
    return out


def _centre(b):
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def test_e1m3_150_opens_from_its_keyless_side_and_from_its_blue_side_only_with_the_card():
    dp = _phase("E1M3")
    west, east = _centre(dp.boxes[150]), _centre(dp.keyed[150][0][0])
    assert _drive(dp, [(*east, True, (0, 0, 0))] * 3)[-1][0][150][0] == 0      # blue side, no card: shut
    assert _drive(dp, [(*east, True, (1, 0, 0))] * 3)[-1][0][150][0] > 0      # with it: opens
    assert _drive(dp, [(*west, True, (0, 0, 0))] * 3)[-1][0][150][0] > 0      # the D1 31 side: no card needed
    # 40 units east of the door (inside the old two-sided box around the keyless line, not its front box): nothing
    assert _drive(dp, [(-1136 + 40, 100, True, (0, 0, 0))] * 3)[-1][0][150][0] == 0


def test_e1m9_135_stays_open_after_its_switch_and_closes_after_a_dr_press():
    dp = _phase("E1M9")
    n = dp.nstates[135]
    sw = _centre(dp.switches[135][0])
    frames = [(*sw, True, (0, 0, 0))] + [(*sw, False, (0, 0, 0))] * (n + 60)
    st = _drive(dp, frames)
    assert st[-1][0][135] == (n - 1, D.IDLE, D.SPEED, 0) and st[-1][1][-1] == 1     # open for good, latched
    # the switch again: latched, nothing; the DR line: a raise at the top -- waits, then closes
    box = _centre(dp.boxes[135])
    st2 = _drive(dp, frames + [(*sw, True, (0, 0, 0))] * 3)
    assert st2[-1][0][135][0] == n - 1 and st2[-1][0][135][3] == 0
    st3 = _drive(dp, frames + [(*box, True, (0, 0, 0))] + [(0, 0, False, (0, 0, 0))] * (D.WAIT + n + 2))
    assert st3[-1][0][135][0] == 0


# ---- 2. the WR lines -------------------------------------------------------------------------------------------------

def walk_program(dp, text=None):
    nd = len(dp.order)
    lines = text if text is not None else repeat_walk_lines(dp.repeats, dp.order, PLAYER_R)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy"]
    for d in range(nd):
        body += ["hex.input 1, rbyte", f"hex.mov 1, dstate + {d}*dw, rbyte", "hex.input 1, rbyte",
                 f"hex.mov 1, ddir + {d}*dw, rbyte", "hex.input 1, rbyte", f"hex.mov 1, dsub + {d}*dw, rbyte",
                 "hex.input 1, rbyte", f"hex.mov 2, dwait + {WAIT_NIBBLES * d}*dw, rbyte"]
    body += [f"hex.zero {nd}, dreq", *lines]
    for d in range(nd):
        body += _pr(f"dreq + {d}*dw", 1) + _pr(f"ddir + {d}*dw", 1) + _pr(f"dsub + {d}*dw", 1)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
             "cm_ox: hex.vec 8", "cm_oy: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8", *door_decls(nd, 1)]
    return "\n".join(body) + "\n"


def walk_cases(dp, seed=11, per=120):
    """moves of at most 16 units around every WR line, with each door at rest shut, at rest open, moving or waiting"""
    rng = random.Random(seed)
    out = []
    for trig in dp.repeats:
        geo = trig[2:]
        if geo[0] == "y":
            x1, y1, x2, y2 = geo[2], geo[1], geo[3], geo[1]
        elif geo[0] == "x":
            x1, y1, x2, y2 = geo[1], geo[2], geo[1], geo[3]
        else:
            x1, y1, x2, y2 = geo[1:]
        for _ in range(per):
            t = rng.uniform(-0.3, 1.3)
            px = (x1 + (x2 - x1) * t + rng.uniform(-20, 20)) * 65536
            py = (y1 + (y2 - y1) * t + rng.uniform(-20, 20)) * 65536
            old = (int(px), int(py))
            new = (old[0] + rng.randint(-16 << 16, 16 << 16), old[1] + rng.randint(-16 << 16, 16 << 16))
            ds = {}
            for si in dp.order:
                n = dp.nstates[si]
                ds[si] = rng.choice([(0, 0, 0, 0), (n - 1, 0, 1, 0), (rng.randrange(n), 1, 1, 0),
                                     (rng.randrange(n), 2, 1, 0), (n - 1, 0, 1, rng.randint(1, 30))])
            out.append((old, new, ds))
    return out


def walk_expect(dp, cases):
    want = []
    for old, new, ds in cases:
        st = dp.after_move((ds, (0,) * (len(dp.triggers) + dp.nlatch), frozenset(), 0), old, new, PLAYER_R)
        for si in dp.order:
            want += [int(si in st[2]), st[0][si][1], st[0][si][2]]
    return want


def walk_feed(dp, cases):
    out = b""
    for o, n, ds in cases:
        out += bytes([1]) + struct.pack("<IIII", o[0] & M32, o[1] & M32, n[0] & M32, n[1] & M32)
        for si in dp.order:
            out += bytes(ds[si])
    return out


@pytest.mark.parametrize("m", ("E1M6", "E1M7"))
def test_the_wr_lines_act_as_DoorPhase(tmp_path, m):
    dp = _phase(m)
    cases = walk_cases(dp)
    got = _run(tmp_path, "walk", walk_program(dp), walk_feed(dp, cases))
    want = walk_expect(dp, cases)
    assert got == want, [i for i, (g, w) in enumerate(zip(got, want)) if g != w][:5]
    per = 3 * len(dp.order)
    acts = [(want[i * per + 3 * d], want[i * per + 3 * d + 1], cases[i][2][si][1])
            for i in range(len(cases)) for d, si in enumerate(dp.order)]
    if any(t[1] == "open" for t in dp.repeats):
        assert sum(a[0] for a in acts) >= 10                                  # presses
    if any(t[1] == "close" for t in dp.repeats):
        assert sum(a[1] == D.CLOSING and a[2] != D.CLOSING for a in acts) >= 5   # closes started


# ---- 3. a closing door a box fits inside: the convex centre-inside test -------------------------------------------

def contact_program(geo, radius, lines=None):
    lines = lines if lines is not None else door_contact_lines("ct", geo, radius, "ct_y", "ct_n")
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", *lines, "  ct_y:", "    stl.output '1'", "    ;ct_e",
            "  ct_n:", "    stl.output '0'", "  ct_e:", ";loop", "done:", "stl.loop", "rmagic: hex.vec 2",
            "viewx: hex.vec 8", "viewy: hex.vec 8", *door_decls(1, 1)]
    return "\n".join(body) + "\n"


def _poly_box(edges):
    xs, ys = [p for q in edges for p in (q[0], q[2])], [p for q in edges for p in (q[1], q[3])]
    return min(xs), min(ys), max(xs), max(ys)


def contact_points(geo, seed=2, step=3):
    rng = random.Random(seed)
    x0, y0, x1, y1 = _poly_box(geo[0][1])
    pts = []
    for gx in range(x0 - 34, x1 + 35, step):
        for gy in range(y0 - 34, y1 + 35, step):
            pts.append(((gx << 16) + rng.choice((0, 1, -1, 0x8000)), (gy << 16) + rng.choice((0, 1, -1))))
    for ax, ay, bx, by in geo[0][1]:                     # on and beside every edge, at fractions
        for k in range(60):
            t = k / 59
            for off in (0, 1, -1, 0x4000, -0x4000):
                pts.append((int((ax + (bx - ax) * t) * 65536) + off, int((ay + (by - ay) * t) * 65536) - off))
    return pts


def _contact_run(tmp_path, geo, radius, pts, lines=None):
    feed = b"".join(bytes([1]) + struct.pack("<II", x & M32, y & M32) for x, y in pts)
    src = tmp_path / "ct.fj"
    src.write_text(contact_program(geo, radius, lines), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    out = tmp_path / "ct.fjm"
    fj.assemble([consts.resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode()


def _contact_expect(geo, radius, pts):
    return "".join(str(int(D.touches_door(geo, x, y, radius << 16))) for x, y in pts)


# two convex doors a box fits WELL inside (the inside test decides there): a 45-degree square 160 across (four slanted
# edges, sim.point_side) and a pentagon with three axis-aligned edges (DOOM's shortcuts) -- edges in scrambled
# directions, as a map gives them
SQUARE = (("poly", ((80, 0, 0, 80), (-80, 0, 0, 80), (-80, 0, 0, -80), (80, 0, 0, -80)), True), ())
PENTAGON = (("poly", ((0, 0, 128, 0), (128, 96, 128, 0), (128, 96, 64, 144), (0, 96, 64, 144), (0, 96, 0, 0)), True),
            ())


@pytest.mark.parametrize("radius", [PLAYER_R, 30])
@pytest.mark.parametrize("name, geo", [("square", SQUARE), ("pentagon", PENTAGON)])
def test_a_convex_door_box_fits_inside_is_touches_door(tmp_path, name, geo, radius):
    pts = contact_points(geo, step=5)
    want = _contact_expect(geo, radius, pts)
    got = _contact_run(tmp_path, geo, radius, pts)
    assert got == want, [i for i, (g, w) in enumerate(zip(got, want)) if g != w][:5]
    # not vacuous: centres inside that straddle no edge (only the inside test touches them)
    edges = geo[0][1]
    inner = [p for p in pts if D._inside_poly(edges, *p)
             and not D.touches_door((("poly", edges, False), ()), p[0], p[1], radius << 16)]
    assert len(inner) >= 20, len(inner)


@pytest.mark.parametrize("radius", [PLAYER_R, 20, 30])
def test_e1m4_102_contact_is_touches_door(tmp_path, radius):
    """E1M4 102: a 45-degree strip 8 thick that CLOSES and that `door_contact_geo` flags `fits` (its box is under
    2 * 31): refused before C3; its contact runs now (the inside test is never the deciding one here -- the strip is
    thinner than any box -- which the square and pentagon above cover)"""
    dp = _phase("E1M4")
    geo = dp.contact[102]
    assert geo[0][0] == "poly" and geo[0][2] and not D.door_stay(dp.kinds[102])
    pts = contact_points(geo)
    want = _contact_expect(geo, radius, pts)
    got = _contact_run(tmp_path, geo, radius, pts)
    assert got == want, [i for i, (g, w) in enumerate(zip(got, want)) if g != w][:5]
    assert want.count("1") > 100 and want.count("0") > 100


def test_a_door_a_box_fits_inside_that_is_not_convex_is_refused():
    from doomfj.doorcode import convex_edges
    with pytest.raises(AssertionError):
        convex_edges(((0, 0, 64, 0), (64, 0, 64, 64), (64, 64, 32, 16), (32, 16, 0, 64), (0, 64, 0, 0)))


# ---- R9 --------------------------------------------------------------------------------------------------------------

TIC_MUTANTS = [
    ("E1M3", "the blue side's card dropped", lambda dp: (
        f"  dr{_d(dp, 150)}_k0:\n    hex.if0 1, pcard, ", f"  dr{_d(dp, 150)}_k0:\n    hex.if0 1, duse, ")),
    ("E1M5", "the red stay door reads the blue card", lambda dp: ("    hex.if0 1, pcard_r, ", "    hex.if0 1, pcard, ")),
    ("E1M7", "the locked switch's card dropped", lambda dp: (
        "    hex.if0 1, pcard, dr%d_moved" % _d(dp, 528), "    hex.if0 1, duse, dr%d_moved" % _d(dp, 528))),
    ("E1M6", "the S1 latch never set", lambda dp: ("    hex.set 1, wfired + %d*dw, 1" % len(dp.triggers), "")),
    ("E1M9", "the S1 latch never tested", lambda dp: (
        "    hex.if1 1, wfired + %d*dw, " % len(dp.triggers), "    hex.if1 1, duse, ")),
    ("E1M9", "the stay press without its mark", lambda dp: (
        f"    hex.set {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * _d(dp, 135)}*dw, {D.STAY_MARK}", "")),
    ("E1M6", "the close line's door reverses", lambda dp: (
        f"  dr{_d(dp, 56)}_rev:\n    ;dr{_d(dp, 56)}_done",
        f"  dr{_d(dp, 56)}_rev:\n    hex.set 1, ddir + {_d(dp, 56)}*dw, {D.OPENING}\n    ;dr{_d(dp, 56)}_done")),
    ("E1M6", "the blazing close one stride short", lambda dp: (
        f"  dr{_d(dp, 56)}_dn:\n    hex.dec 1, dstate + {_d(dp, 56)}*dw\n", f"  dr{_d(dp, 56)}_dn:\n")),
]


@pytest.mark.parametrize("m, label, mk", TIC_MUTANTS, ids=[t[1] for t in TIC_MUTANTS])
def test_a_mutated_door_tic_fails(tmp_path, m, label, mk):
    dp = _phase(m)
    old, new = mk(dp)
    sched = door_schedule(dp)
    got = _run(tmp_path, "m", door_program(dp, _mutated(tic_lines(dp), old, new)), door_feed(dp, sched))
    assert got != door_expect(dp, sched), label


def test_control_a_wr_line_ignoring_the_door_at_work(tmp_path):
    dp = _phase("E1M6")
    lines = repeat_walk_lines(dp.repeats, dp.order, PLAYER_R)
    cases = walk_cases(dp)
    got = _run(tmp_path, "m", walk_program(dp, _mutated(lines, "    ;wor0_no\n  wor0_rd:", "  wor0_rd:")),
               walk_feed(dp, cases))
    assert got != walk_expect(dp, cases)


def test_control_a_close_of_a_shut_door(tmp_path):
    dp = _phase("E1M7")
    k = next(k for k, t in enumerate(dp.repeats) if t[1] == "close")
    lines = repeat_walk_lines(dp.repeats, dp.order, PLAYER_R)
    old = f"    hex.if0 1, dstate + {_d(dp, dp.repeats[k][0])}*dw, wor{k}_no\n"
    cases = walk_cases(dp)
    got = _run(tmp_path, "m", walk_program(dp, _mutated(lines, old, "")), walk_feed(dp, cases))
    assert got != walk_expect(dp, cases)


@pytest.mark.parametrize("edge", [0, 2])
@pytest.mark.parametrize("name, geo", [("square", SQUARE), ("pentagon", PENTAGON)])
def test_control_an_edge_of_the_inside_test_dropped(tmp_path, name, geo, edge):
    lines = door_contact_lines("ct", geo, PLAYER_R, "ct_y", "ct_n")
    text = "\n".join(lines)
    a, b = text.index(f"ct_in{edge}"), text.index(f"  ct_in{edge}_ok:")
    cut = text[:text.rfind("\n", 0, a) + 1] + text[b:]          # the edge's whole test gone: it always passes
    pts = contact_points(geo, step=5)
    got = _contact_run(tmp_path, geo, PLAYER_R, pts, cut.split("\n"))
    assert got != _contact_expect(geo, PLAYER_R, pts)


@pytest.mark.parametrize("name, geo", [("square", SQUARE), ("pentagon", PENTAGON)])
def test_control_without_the_inside_test(tmp_path, name, geo):
    lines = door_contact_lines("ct", geo, PLAYER_R, "ct_y", "ct_n")
    pts = contact_points(geo, step=5)
    got = _contact_run(tmp_path, geo, PLAYER_R, pts, _mutated(lines, "    ;ct_y\n  ct_out:", "    ;ct_out\n  ct_out:"))
    assert got != _contact_expect(geo, PLAYER_R, pts)


# ---- 4. the switch textures' door phase with a LOCKED switch (switchcode.door_phase_lines, S1 133) ------------------

def _locked_switches():
    """E1M7's S1 133 (blue) on door 528 and SR 61 on door 605, as doomfj.switches.Switch records (E1M7's own
    map_switches refuses its two exit lines, a separate matter)"""
    from doomfj import switches as SW
    dp = _phase("E1M7")
    b133 = next(b for b, c, _l, _s in dp.switch_info[528] if c == "blue")
    b61 = dp.switches[605][0]
    return dp, [SW.Switch(3150, 133, "door", False, False, b133, (528,)),
                SW.Switch(3724, 61, "door", True, False, b61, (605,))]


def _swd_program(sw, slot, text=None):
    from doomfj import switchcode as SC
    from doomfj import switches as SW
    lines = text if text is not None else SC.door_phase_lines(sw, slot)
    nd = max(slot.values()) + 1
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, rbyte", "hex.mov 1, duse, rbyte",
            "hex.input 1, rbyte", "hex.mov 1, pcard, rbyte"]
    for d in sorted(slot.values()):
        body += ["hex.input 1, rbyte", f"hex.mov 1, ddir + {d}*dw, rbyte",
                 "hex.input 1, rbyte", f"hex.mov 2, dwait + {WAIT_NIBBLES * d}*dw, rbyte"]
    body += [*lines]
    for k in range(len(SW.latched(sw))):
        body += _pr(f"swpr + {k}*dw", 1)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2", "viewx: hex.vec 8",
             "viewy: hex.vec 8", *SC.decls(len(SW.latched(sw)), len(SW.repeating(sw))), *door_decls(nd, 1)]
    return "\n".join(body) + "\n"


def _swd_cases(sw, slot, seed=3, n=300):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        s = rng.choice(sw)
        x = rng.randint(s.box[0] - 3, s.box[2] + 3)
        y = rng.randint(s.box[1] - 3, s.box[3] + 3)
        doors = {d: (rng.choice([0, 0, 1, 2]), rng.choice([0, 0, 0, 9])) for d in slot.values()}
        out.append((x, y, int(rng.random() < 0.7), int(rng.random() < 0.5), doors))
    return out


def _swd_expect(sw, slot, cases):
    from doomfj import switches as SW
    lat, sr = SW.latched(sw), SW.repeating(sw)
    on, tm = [0] * len(lat), [0] * len(sr)
    want = []
    for x, y, use, card, doors in cases:
        SW.countdown(on, tm, sr)
        for k in SW.door_presses(lat, bool(use), x << 16, y << 16,
                                 lambda si: doors[slot[si]] == (0, 0), lambda c: bool(card)):
            SW.press(on, tm, sr, k)
        want += list(on)
    return want


def _swd_feed(slot, cases):
    out = b""
    for x, y, use, card, doors in cases:
        out += bytes([1]) + struct.pack("<II", (x << 16) & M32, (y << 16) & M32) + bytes([use, card])
        for d in sorted(slot.values()):
            out += bytes(doors[d])
    return out


def test_the_switch_textures_take_the_locked_switchs_card(tmp_path):
    dp, sw = _locked_switches()
    slot = {si: d for d, si in enumerate(dp.order)}
    cases = _swd_cases(sw, slot)
    got = _run(tmp_path, "swd", _swd_program(sw, slot), _swd_feed(slot, cases))
    want = _swd_expect(sw, slot, cases)
    assert got == want
    assert any(want[2 * i] for i in range(len(cases)))        # the locked switch swapped (with the card)


def test_control_the_locked_switch_without_its_card_check(tmp_path):
    from doomfj import switchcode as SC
    dp, sw = _locked_switches()
    slot = {si: d for d, si in enumerate(dp.order)}
    lines = _mutated(SC.door_phase_lines(sw, slot), "    hex.if0 1, pcard, swd0_no", "")
    cases = _swd_cases(sw, slot)
    got = _run(tmp_path, "swdm", _swd_program(sw, slot, lines), _swd_feed(slot, cases))
    assert got != _swd_expect(sw, slot, cases)
