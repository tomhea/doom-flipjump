"""M7 P2b L3 -- door reversal RUN in fj (docs/gp-lift-spike.md section 4): the shipped door machine
(`doorcode.door_tic_lines` with `contact=`/`passes=`) on E1M1's real doors, each fed CLOSING about to
step at and around its pass state with the player on the edges of `doors.touches_door` -- inside the
rectangle, straddling each two-sided line, one 16.16 step off each. The expectation is
`doors.door_tic(..., blocked=touches_door(...), pass_at=)`, the model's rule
(tests/host/test_movers_model.py holds touches_door to check_position's own test).

R9: MUTANTS -- one real edit of the emitted text each -- must each make the program disagree.
"""
import struct

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import doors as D
from doomfj.doorcode import WAIT_NIBBLES, door_decls, door_tic_lines
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile

FIX = "tests/fixtures/freedoom_e1m1.wad"
M32 = 0xFFFFFFFF
R = 16


@pytest.fixture(scope="module")
def lvl():
    mw = WadFile.from_path(FIX)
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    verts = bake_bsp(mw, "E1M1").vertexes
    tbl = D.door_states(secs, lds, sds)
    order = sorted(tbl)
    return {"order": order, "n": {si: len(v) for si, v in tbl.items()},
            "boxes": D.use_boxes_xy(secs, lds, sds, verts), "kinds": D.door_kinds(secs, lds, sds),
            "geo": D.door_contact_geo(secs, lds, sds, verts),
            "passes": {si: D.pass_state(secs, lds, sds, si) for si in order}}


def program(lvl, text=None):
    order, n = lvl["order"], lvl["n"]
    tic = text if text is not None else door_tic_lines(order, n, lvl["boxes"], lvl["kinds"],
                                                        contact=lvl["geo"], passes=lvl["passes"])
    nd = len(order)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy"]
    for d in range(nd):
        body += ["hex.input 1, rbyte", f"hex.mov 1, dstate + {d}*dw, rbyte",
                 "hex.input 1, rbyte", f"hex.mov 1, ddir + {d}*dw, rbyte",
                 f"hex.set 1, dsub + {d}*dw, 1", f"hex.zero {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw"]
    body += ["hex.zero 1, duse", "hex.zero 1, pcard", f"hex.zero {nd}, dreq", *tic]
    for d in range(nd):
        body += [f"    hex.print_as_digit 1, dstate + {d}*dw, 0", "    stl.output 32",
                 f"    hex.print_as_digit 1, ddir + {d}*dw, 0", "    stl.output 32"]
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
             "viewx: hex.vec 8", "viewy: hex.vec 8", *door_decls(nd, 2)]
    return "\n".join(body) + "\n"


def records(lvl):
    """per closing door, per state round its pass step, the player on every edge of the rule"""
    out = []
    for si in lvl["order"]:
        if D.door_stay(lvl["kinds"][si]):
            continue
        (x0, y0, x1, y1), lines = lvl["geo"][si]
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        pts = [(cx << 16, cy << 16), ((x0 << 16) + 1, cy << 16), ((x1 << 16) - 1, cy << 16),
               (x0 << 16, cy << 16), (cx << 16, (y0 << 16) - (40 << 16))]
        for axis, coord, lo, hi in lines:
            for dc in (-(R << 16), -(R << 16) + 1, 0, (R << 16) - 1, R << 16):
                for o in ((lo - R) << 16, ((lo - R) << 16) + 1, ((lo + hi) // 2) << 16,
                          ((hi + R) << 16) - 1, (hi + R) << 16):
                    c = (coord << 16) + dc
                    pts.append((o, c) if axis == "y" else (c, o))
        p, n = lvl["passes"][si], lvl["n"][si]
        for state in sorted({max(0, p - 1), p, min(n - 1, p + 1), min(n - 1, p + 3)}):
            for x, y in pts:
                out.append((si, state, x, y))
    return out


def expect(lvl, recs):
    want = []
    for si, state, x, y in recs:
        for sj in lvl["order"]:
            if sj != si:
                want += [0, 0]
                continue
            kind = lvl["kinds"][si]
            st = D.door_tic((state, D.CLOSING, 1, 0), lvl["n"][si], False, stride=D.door_stride(kind),
                            stay=D.door_stay(kind), blocked=D.touches_door(lvl["geo"][si], x, y, R << 16),
                            pass_at=lvl["passes"][si])
            want += [st[0], st[1]]
    return want


def feed(lvl, recs):
    out = b""
    for si, state, x, y in recs:
        out += bytes([1]) + struct.pack("<II", x & M32, y & M32)
        for sj in lvl["order"]:
            out += bytes([state, D.CLOSING]) if sj == si else bytes([0, 0])
    return out


def _run(tmp, name, text, data):
    src = tmp / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(data + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def test_a_closing_door_reverses_on_the_player_as_door_tic(tmp_path, lvl):
    recs = records(lvl)
    want = expect(lvl, recs)
    assert _run(tmp_path, "rev", program(lvl), feed(lvl, recs)) == want
    reversed_ = sum(1 for k in range(0, len(want), 2) if want[k + 1] == D.OPENING)
    assert 100 < reversed_ < len(recs), "reversals and closings both"


def _mut(lines, pred, repl):
    out, done = [], False
    for ln in lines:
        if not done and pred(ln):
            ln, done = repl(ln), True
        out.append(ln)
    assert done
    return out


MUTANTS = {
    "the reversal never turns the door": lambda ls: (
        ls[:ls.index("  dr0_rev:") + 1] + ls[ls.index("  dr0_rev:") + 2:]),
    "the pass-step mask off by one": lambda ls: _mut(
        ls, lambda l: "hex.if_flags dstate + 0*dw" in l,
        lambda l: l.replace(l.split(",")[1], " %#06x" % (int(l.split(",")[1], 16) << 1))),
    "the inside test not strict": lambda ls: _mut(
        ls, lambda l: "hex.scmp 8, viewx, dbox, dr0_ct_n0, dr0_ct_n0, dr0_ct_00a" in l,
        lambda l: l.replace("dr0_ct_n0, dr0_ct_n0, dr0_ct_00a", "dr0_ct_n0, dr0_ct_00a, dr0_ct_00a")),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_mutated_reversal_fails(tmp_path, lvl, name):
    good = door_tic_lines(lvl["order"], lvl["n"], lvl["boxes"], lvl["kinds"],
                          contact=lvl["geo"], passes=lvl["passes"])
    bad = MUTANTS[name](good)
    assert bad != good, "the mutant changed nothing"
    recs = records(lvl)
    assert _run(tmp_path, "mut", program(lvl, bad), feed(lvl, recs)) != expect(lvl, recs), name


# ---- M7 P3.2b: the reversal on MONSTERS (`mon_contact`: the shared contact leaf per door and radius) -----------
MONS = ((20, 1), (30, 1), (30, 0))   # (radius, active): the third is inactive -- a closing door ignores it
FAR = -30000 << 16


def mon_program(lvl, text=None):
    order, n = lvl["order"], lvl["n"]
    mc = [("mx + %d*dw" % (8 * j), "my + %d*dw" % (8 * j), r, "mact + %d*dw" % j) for j, (r, _a) in enumerate(MONS)]
    tic = text if text is not None else door_tic_lines(order, n, lvl["boxes"], lvl["kinds"], contact=lvl["geo"],
                                                        passes=lvl["passes"], mon_contact=mc)
    prog = program(lvl, text=tic)
    pre = "hex.input 4, viewy"
    ins = [pre] + ["hex.input 4, mx + %d*dw" % (8 * j) for j in range(len(MONS))] + \
          ["hex.input 4, my + %d*dw" % (8 * j) for j in range(len(MONS))] + \
          ["hex.input 2, mact"]                                     # one nibble per monster
    prog = prog.replace(pre, "\n".join(ins), 1)
    return prog + "\n".join(["mx: hex.vec %d" % (8 * len(MONS)), "my: hex.vec %d" % (8 * len(MONS)),
                             "mact: hex.vec 4"]) + "\n"


def mon_records(lvl):
    """per closing door and state round its pass step: ONE monster on each edge of the rule at its radius (the
    others and the player far away)"""
    out = []
    for si in lvl["order"]:
        if D.door_stay(lvl["kinds"][si]):
            continue
        (x0, y0, x1, y1), lines = lvl["geo"][si]
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        p, n = lvl["passes"][si], lvl["n"][si]
        for j, (r, _a) in enumerate(MONS):
            pts = [(cx << 16, cy << 16), ((x0 << 16) + 1, cy << 16)]
            for axis, coord, lo, hi in lines:
                for dc in (-(r << 16), -(r << 16) + 1, (r << 16) - 1, r << 16):
                    c = (coord << 16) + dc
                    o = ((lo + hi) // 2) << 16
                    pts.append((o, c) if axis == "y" else (c, o))
            for state in sorted({p, min(n - 1, p + 1)}):
                for x, y in pts:
                    out.append((si, state, j, x, y))
    return out


def mon_expect(lvl, recs):
    want = []
    for si, state, j, x, y in recs:
        r, act = MONS[j]
        for sj in lvl["order"]:
            if sj != si:
                want += [0, 0]
                continue
            kind = lvl["kinds"][si]
            blocked = bool(act) and D.touches_door(lvl["geo"][si], x, y, r << 16)
            st = D.door_tic((state, D.CLOSING, 1, 0), lvl["n"][si], False, stride=D.door_stride(kind),
                            stay=D.door_stay(kind), blocked=blocked, pass_at=lvl["passes"][si])
            want += [st[0], st[1]]
    return want


def mon_feed(lvl, recs):
    out = b""
    for si, state, j, x, y in recs:
        xs = [x if k == j else FAR for k in range(len(MONS))]
        ys = [y if k == j else FAR for k in range(len(MONS))]
        out += bytes([1]) + struct.pack("<II", FAR & M32, FAR & M32)
        out += b"".join(struct.pack("<I", v & M32) for v in xs) + b"".join(struct.pack("<I", v & M32) for v in ys)
        out += struct.pack("<H", sum(a << (4 * k) for k, (_r, a) in enumerate(MONS)))
        for sj in lvl["order"]:
            out += bytes([state, D.CLOSING]) if sj == si else bytes([0, 0])
    return out


def test_a_closing_door_reverses_on_a_live_monster(tmp_path, lvl):
    recs = mon_records(lvl)
    want = mon_expect(lvl, recs)
    assert _run(tmp_path, "mrev", mon_program(lvl), mon_feed(lvl, recs)) == want
    rev = sum(1 for k in range(0, len(want), 2) if want[k + 1] == D.OPENING)
    assert 30 < rev < len(recs), "reversals on monsters and closings both"


@pytest.mark.parametrize("mut", ["inactive counts", "one radius for all"])
def test_a_mutated_monster_reversal_fails(tmp_path, lvl, mut):
    mc = [("mx + %d*dw" % (8 * j), "my + %d*dw" % (8 * j), r, "mact + %d*dw" % j) for j, (r, _a) in enumerate(MONS)]
    if mut == "one radius for all":
        mc = [(x, y, 20, a) for x, y, _r, a in mc]
    bad = door_tic_lines(lvl["order"], lvl["n"], lvl["boxes"], lvl["kinds"], contact=lvl["geo"],
                         passes=lvl["passes"], mon_contact=mc)
    if mut == "inactive counts":
        bad = [ln.replace("hex.if0 1, mact + 2*dw,", "hex.if0 1, mact + 0*dw,") for ln in bad]
    recs = mon_records(lvl)
    assert _run(tmp_path, "mmut", mon_program(lvl, bad), mon_feed(lvl, recs)) != mon_expect(lvl, recs), mut
