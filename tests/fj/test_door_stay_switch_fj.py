"""M8 C11 -- E1M9's MIXED door RUNS in fj against doomfj.doors: door 135 is a DR door (line 650, special 1: raise,
wait, close) that an S1 103 switch (line 887, EV_DoDoor(open)) opens to STAY. Its kind stays "plain"; the switch's
box (`doors.stay_switch_boxes`) presses it at rest with `door_tic`'s `stay_used` -- OPENING with wait = STAY_MARK,
so the top sets no wait and it stays open; a DR press at the top then waits and closes it (EV_VerticalDoor: a new
raise on an idle open sector). KNOWN SIMPLIFICATION: the S1 latch is not kept (`switch_door_triggers`), so the switch
opens it again after a DR use closed it -- DOOM's line would be spent.

The program is the emitter's own text (doorcode.door_tic_lines with `stay_switches`, every E1M9 door), fed a scripted
walk through door 135's DR box and switch box plus random frames, and read back each frame; the expectation is
doors.DoorPhase.tic. Every map before E1M9 has no mixed door: its door text is unchanged (tests/host/
test_mixed_door.py compares it to the pre-C11 emitter).

R9: MUTANTS -- one real edit of the emitted text each -- must each make the program disagree: the switch's hit sent to
the plain press (it would close after the wait), and the top's STAY_MARK test dropped (the same, by the other half).
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import doors as D
from doomfj.config import Config
from doomfj.doorcode import WAIT_NIBBLES, door_decls, door_tic_lines
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FULL = ROOT / "assets" / "freedoom1.wad"
M32 = 0xFFFFFFFF
CARDS = ("pcard", "pcard_y", "pcard_r")
MIXED = 135


@pytest.fixture(scope="module")
def dp():
    if not FULL.exists():
        pytest.skip("the full episode wad is not present")
    mw = WadFile.from_path(str(FULL))
    m = "E1M9"
    secs, lds, sds = mw.sectors(m), mw.linedefs(m), mw.sidedefs(m)
    boxes = D.use_boxes_xy(secs, lds, sds, bake_bsp(mw, m).vertexes)
    return D.DoorPhase(secs, lds, sds, mw.vertexes(m), boxes)


def tic_lines(dp):
    return door_tic_lines(dp.order, dp.nstates, dp.boxes, dp.kinds, contact=dp.contact, passes=dp.passes,
                          switches=dp.switches, walked={t[0] for t in dp.triggers}, stay_switches=dp.stay_switches)


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


def door_program(dp, lines):
    nd = len(dp.order)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, rbyte", "hex.mov 1, duse, rbyte"]
    for c in CARDS:
        body += ["hex.input 1, rbyte", f"hex.mov 1, {c}, rbyte"]
    body += list(lines)
    for d in range(nd):
        body += _pr(f"dstate + {d}*dw", 1) + _pr(f"ddir + {d}*dw", 1) + _pr(f"dsub + {d}*dw", 1)
        body += _pr(f"dwait + {WAIT_NIBBLES * d}*dw", WAIT_NIBBLES)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
             "viewx: hex.vec 8", "viewy: hex.vec 8", "pcard_y: hex.vec 1, 0", "pcard_r: hex.vec 1, 0",
             *door_decls(nd, len(dp.triggers))]
    return "\n".join(body) + "\n"


def _run(tmp, name, program, feed):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def schedule(dp, seed=5):
    """(x, y, use) frames: door 135's switch pressed (opens to stay), held open far past WAIT, a DR press at the top
    (waits, closes), the switch pressed while it closes (refused: not at rest) and again at rest (opens again: the
    simplification), a DR press from shut (a plain cycle), the switch while that waits (refused) -- then every boxed
    door and switch with random use"""
    def ctr(b):
        return ((b[0] + b[2]) // 2) << 16, ((b[1] + b[3]) // 2) << 16
    sw, dr = ctr(dp.stay_switches[MIXED][0]), ctr(dp.boxes[MIXED])
    away = (dr[0] + (400 << 16), dr[1] + (400 << 16))
    out = [(*sw, 1)] + [(*away, 0)] * (D.WAIT + 30)
    out += [(*dr, 1)] + [(*away, 0)] * 10
    out += [(*sw, 1)] * 3 + [(*away, 0)] * (D.WAIT + 30)
    out += [(*sw, 1)] + [(*away, 0)] * 30
    out += [(*dr, 1)] + [(*away, 0)] * 25 + [(*dr, 0)] * 2 + [(*dr, 1)] + [(*away, 0)] * 2
    out += [(*sw, 1)] + [(*away, 0)] * (D.WAIT + 20)
    rng = random.Random(seed)
    visits = [dp.boxes[si] for si in dp.order if si in dp.boxes]
    visits += [b for si in dp.order for b in list(dp.switches.get(si, ())) + list(dp.stay_switches.get(si, ()))]
    for (x0, y0, x1, y1) in visits:
        for f in range(10):
            x, y = (rng.randint(x0 - 4, x1 + 4), rng.randint(y0 - 4, y1 + 4))
            out.append((x << 16, y << 16, int(f < 2 or rng.random() < 0.2)))
    return out


def expect(dp, sched):
    st, want = dp.initial(), []
    for x16, y16, use in sched:
        st = dp.tic(st, bool(use), x16, y16, has_blue=True, has_yellow=True, has_red=True)
        for si in dp.order:
            want += list(st[0][si])
    return want


def feed(sched):
    return b"".join(bytes([1]) + struct.pack("<II", x & M32, y & M32) + bytes([use, 1, 1, 1]) for x, y, use in sched)


def test_the_mixed_door_runs_as_DoorPhase(tmp_path, dp):
    assert set(dp.stay_switches) == {MIXED} and dp.kinds[MIXED] == "plain"
    sched = schedule(dp)
    got = _run(tmp_path, "mixed", door_program(dp, tic_lines(dp)), feed(sched))
    want = expect(dp, sched)
    assert len(got) == len(want)
    bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert not bad, (len(bad), bad[:5])
    # not vacuous: 135 rests OPEN with no wait for longer than WAIT (the stay), and later closes again (the DR)
    d, nd, last = dp.order.index(MIXED), len(dp.order), dp.nstates[MIXED] - 1
    rows = [want[4 * (f * nd + d):4 * (f * nd + d) + 4] for f in range(len(sched))]
    run, best = 0, 0
    for r in rows:
        run = run + 1 if (r[0] == last and r[1] == D.IDLE and r[3] == 0) else 0
        best = max(best, run)
    assert best > D.WAIT + 20, best
    top = next(f for f, r in enumerate(rows) if r[0] == last)
    assert any(r[0] == 0 for r in rows[top:]), "it never closed again"


@pytest.mark.parametrize("mutant", ["plain_press", "no_mark_test"])
def test_control_mutants_disagree(tmp_path, dp, mutant):
    d = dp.order.index(MIXED)
    text = "\n".join(tic_lines(dp))
    if mutant == "plain_press":
        old, new = f"    ;dr{d}_spress", f"    ;dr{d}_press"
    else:
        old = f"    hex.if0 {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw, dr{d}_opw"
        new = f"    ;dr{d}_opw"
    assert text.count(old) == 1, old
    sched = schedule(dp)
    got = _run(tmp_path, mutant, door_program(dp, text.replace(old, new).split("\n")), feed(sched))
    assert got != expect(dp, sched)
