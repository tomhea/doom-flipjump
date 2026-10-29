"""M8 w2fix -- a door whose PASS STATE IS ITS TOP, RUN in fj (the auto-gameplay gate on E1M5: door 1, sector 12, five
states, pass state 4; E1M3's 167 / 213 / 228 are the same kind). It starts closing at the top, reverses on the player
there (OPENING at its top state), and its next step is the top again with the full wait -- doors.door_tic's
`state >= nstates - 1` clamp, T_VerticalDoor's "up: at once at its top, topcountdown = topwait". The binary used to
step it PAST the top (state 5, still opening, wait 0) on frame 888 of the playthrough.

The shipped door machine (`doorcode.door_tic_lines` with `contact=` / `passes=`) on E1M5's real doors: each closing door
put CLOSING, about to step, at and around its pass state, the player inside its contact rectangle or far away; TWO
tics; after each, every door's state, direction and wait against `doors.door_tic` run twice.

R9: `top_clamp=False` (the old text, E1M1's emission) -- must part, on the top-pass door's records alone.
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

FIX = "tests/fixtures/freedoom_e1m5.wad"
MAP = "E1M5"
M32 = 0xFFFFFFFF
R = 16
FAR = -30000 << 16


@pytest.fixture(scope="module")
def lvl():
    mw = WadFile.from_path(FIX)
    secs, lds, sds = mw.sectors(MAP), mw.linedefs(MAP), mw.sidedefs(MAP)
    verts = bake_bsp(mw, MAP).vertexes
    tbl = D.door_states(secs, lds, sds)
    order = sorted(tbl)
    return {"order": order, "n": {si: len(v) for si, v in tbl.items()},
            "boxes": D.use_boxes_xy(secs, lds, sds, verts), "kinds": D.door_kinds(secs, lds, sds),
            "geo": D.door_contact_geo(secs, lds, sds, verts),
            "passes": {si: D.pass_state(secs, lds, sds, si) for si in order}}


def _tic(lvl):
    return door_tic_lines(lvl["order"], lvl["n"], lvl["boxes"], lvl["kinds"], contact=lvl["geo"], passes=lvl["passes"])


def program(lvl, tic):
    nd = len(lvl["order"])
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy"]
    for d in range(nd):
        body += ["hex.input 1, rbyte", f"hex.mov 1, dstate + {d}*dw, rbyte",
                 "hex.input 1, rbyte", f"hex.mov 1, ddir + {d}*dw, rbyte",
                 f"hex.set 1, dsub + {d}*dw, 1", f"hex.zero {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw"]
    body += ["hex.zero 1, duse", "hex.zero 1, pcard", f"hex.zero {nd}, dreq", "stl.fcall tic, tic_ret",
             "stl.fcall tic, tic_ret", ";loop",
             "tic:", f"hex.zero {nd}, dreq", *tic]
    for d in range(nd):
        body += [f"    hex.print_as_digit 1, dstate + {d}*dw, 0", "    stl.output 32",
                 f"    hex.print_as_digit 1, ddir + {d}*dw, 0", "    stl.output 32",
                 f"    hex.print_as_digit {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw, 0", "    stl.output 32"]
    body += ["stl.fret tic_ret", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2", "tic_ret: hex.vec w/4",
             "viewx: hex.vec 8", "viewy: hex.vec 8", *door_decls(nd, 2)]
    return "\n".join(body) + "\n"


def top_pass_doors(lvl):
    return [si for si in lvl["order"] if not D.door_stay(lvl["kinds"][si])
            and lvl["passes"][si] == lvl["n"][si] - 1]


def records(lvl):
    """per closing door, per state at and round its pass step: the player at its contact rectangle's centre, and far"""
    out = []
    for si in lvl["order"]:
        if D.door_stay(lvl["kinds"][si]):
            continue
        (x0, y0, x1, y1), _lines = lvl["geo"][si]
        pts = [(((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16), (FAR, FAR)]
        p, n = lvl["passes"][si], lvl["n"][si]
        for state in sorted({max(0, p - 1), p, n - 1}):
            for x, y in pts:
                out.append((si, state, x, y))
    return out


def expect(lvl, recs):
    want = []
    for si, state, x, y in recs:
        sts = {sj: (state, D.CLOSING, 1, 0) if sj == si else (0, D.IDLE, 1, 0) for sj in lvl["order"]}
        for _ in range(2):
            for sj in lvl["order"]:
                kind = lvl["kinds"][sj]
                sts[sj] = D.door_tic(sts[sj], lvl["n"][sj], False, stride=D.door_stride(kind),
                                     stay=D.door_stay(kind), blocked=D.touches_door(lvl["geo"][sj], x, y, R << 16),
                                     pass_at=lvl["passes"][sj])
                want += [sts[sj][0], sts[sj][1], sts[sj][3]]
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


def test_the_map_has_a_top_pass_door_that_reverses_at_its_top(lvl):
    """E1M5's sector 12 is one (the gate's door); the model reverses it at the top and clamps it there next tic"""
    tops = top_pass_doors(lvl)
    assert 12 in tops, tops
    si = 12
    n, p = lvl["n"][si], lvl["passes"][si]
    (x0, y0, x1, y1), _l = lvl["geo"][si]
    x, y = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
    kind = lvl["kinds"][si]
    kw = dict(stride=D.door_stride(kind), stay=D.door_stay(kind), blocked=D.touches_door(lvl["geo"][si], x, y, R << 16),
              pass_at=p)
    st = D.door_tic((n - 1, D.CLOSING, 1, 0), n, False, **kw)
    assert st[:2] == (n - 1, D.OPENING), st
    st = D.door_tic(st, n, False, **kw)
    assert (st[0], st[1], st[3]) == (n - 1, D.IDLE, D.WAIT), st


def test_two_tics_of_every_closing_door_follow_door_tic(tmp_path, lvl):
    recs = records(lvl)
    assert _run(tmp_path, "top", program(lvl, _tic(lvl)), feed(lvl, recs)) == expect(lvl, recs)


def test_control_without_the_top_clamp_the_door_steps_past_its_top(tmp_path, lvl):
    """`top_clamp=False` -- the old text, E1M1's (config.DOOR_TOP_STEP_LEGACY): exactly the clamp's three lines fewer,
    and it parts on the top-pass door's records"""
    good, bad = _tic(lvl), door_tic_lines(lvl["order"], lvl["n"], lvl["boxes"], lvl["kinds"], contact=lvl["geo"],
                                          passes=lvl["passes"], top_clamp=False)
    assert len(good) - len(bad) == 3 * len(top_pass_doors(lvl)), (len(good), len(bad))
    recs = [r for r in records(lvl) if r[0] in top_pass_doors(lvl)]
    assert _run(tmp_path, "top_mut", program(lvl, bad), feed(lvl, recs)) != expect(lvl, recs)
