"""M8 -- the switch textures' fj RUN against doomfj.switches (the model's rule, World.switch_doors / switch_uses):

  1. the TIC: `switchcode.door_phase_lines` (the SR countdown, then the door switches a held use presses) and
     `switchcode.use_press_lines` (the floor and lift switches a use press changes), on E1M2's own switch lines --
     every one, their real boxes, doors and floor groups -- plus SYNTHETIC SR lines E1M2 does not have (a 63 door
     switch on two doors, a 62 lift switch on two lifts), so the countdown, the lift test and a multi-target door are
     run too. Fed per frame: the position, use held, the tic-start death, the use PRESS edge, each door's `ddir` /
     `dwait`, each lift's `lstate`, each floor group's timer; read back `swpr` and `swtm` after every frame, from a
     schedule that walks every box (inside, on each edge, one unit out) with random machine states, re-zeroing the
     cells now and then so a latched S1 line is pressed again from scratch;
  2. the PICTURE's dispatch: `wall_renderer.switch_seg_blocks` -- a switch seg's two constant blocks behind the
     one-nibble switch on its cell -- dispatched twice per cell value (the first call SETs the state's fields, the
     second CLEARs them), the cell surviving.

R9: MUTANTS -- one real edit of the emitted text each (the door's wait test dropped, the countdown's swap-back dropped,
the moving group's timer test dropped, a lift switch reading one lift only, an SR line pressed again while its button
is out, the dead player's guard dropped, the blocks swapped) -- must each make their program disagree.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import movers as MV
from doomfj import switches as SW
from doomfj.config import Config
from doomfj.doorcode import WAIT_NIBBLES
from doomfj.harness import W
from doomfj.switchcode import decls, door_phase_lines, use_press_lines
from doomfj.wad import WadFile
from doomfj.wall_renderer import switch_seg_blocks

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
BN = SW.BUTTON_NIBBLES


class Lvl:
    """E1M2's switches and machines, plus the synthetic SR lines"""

    def __init__(self):
        mw = WadFile.from_path(FIX)
        m = "E1M2"
        secs, lds, sds, verts = mw.sectors(m), mw.linedefs(m), mw.sidedefs(m), mw.vertexes(m)
        real = SW.map_switches(secs, lds, sds, verts)
        self.groups = MV.floor_groups(secs, lds, sds)
        self.wide = MV.floor_wide(self.groups)
        self.nlift = len(MV.lift_states(secs, lds, sds))
        doors = sorted({si for s in real if s.kind == "door" for si in s.targets})
        # the synthetic SR lines: a door switch on BOTH of E1M2's switch doors, a lift switch on two lifts; their boxes
        # overlap the real ones' so one press can change several lines
        b0 = next(s.box for s in real if s.kind == "door")
        b1 = next(s.box for s in real if s.kind == "floor")
        syn = [SW.Switch(90001, 63, "door", True, False, (b0[0] + 40, b0[1], b0[2] + 40, b0[3]), tuple(doors)),
               SW.Switch(90002, 62, "lift", True, True, (b1[0] - 30, b1[1] + 20, b1[2] - 30, b1[3] + 20), (0, 3))]
        self.switches = real + syn
        self.lat = SW.latched(self.switches)
        self.sr = SW.repeating(self.switches)
        self.door_slot = {si: d for d, si in enumerate(doors)}
        assert len(self.sr) == 2 and len(self.lat) == 8
        assert {s.kind for s in real} == {"door", "floor", "exit"}, "E1M2: no lift switch line"


@pytest.fixture(scope="module")
def lvl():
    return Lvl()


def _run(tmp, name, program, feed, extra=()):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([*extra, src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


# ---- 1. the tic --------------------------------------------------------------------------------------------------

def tic_text(lvl):
    return door_phase_lines(lvl.switches, lvl.door_slot, dead="p_dd0"), use_press_lines(lvl.switches, lvl.groups,
                                                                                         lvl.wide)


def tic_program(lvl, text=None):
    door, use = tic_text(lvl) if text is None else text
    nd, ng = len(lvl.door_slot), len(lvl.groups)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, rbyte", "hex.if0 1, rbyte, noreset",
            f"hex.zero {len(lvl.lat)}, swpr", f"hex.zero {BN * len(lvl.sr)}, swtm", "noreset:",
            "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.input 1, rbyte", "hex.mov 1, duse, rbyte",
            "hex.input 1, rbyte", "hex.mov 1, p_dd0, rbyte",
            "hex.input 1, rbyte", "hex.mov 1, prs, rbyte"]
    for d in range(nd):
        body += ["hex.input 1, rbyte", f"hex.mov 1, ddir + {d}*dw, rbyte",
                 "hex.input 1, rbyte", f"hex.mov {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw, rbyte"]
    for k in range(lvl.nlift):
        body += ["hex.input 1, rbyte", f"hex.mov 1, lstate + {k}*dw, rbyte"]
    for g in range(ng):
        body += ["hex.input 1, rbyte", f"hex.mov 1, fswitch + {ng + g}*dw, rbyte"]
    body += [*door, "hex.if0 1, prs, nopress", *use, "nopress:"]
    for k in range(len(lvl.lat)):
        body += _pr(f"swpr + {k}*dw", 1)
    for j in range(len(lvl.sr)):
        body += _pr(f"swtm + {BN * j}*dw", BN)
    body += [";loop", "done:", "stl.loop",
             "rmagic: hex.vec 2", "rbyte: hex.vec 2", "viewx: hex.vec 8", "viewy: hex.vec 8", "dbox: hex.vec 8, 0",
             "duse: hex.vec 1, 0", "p_dd0: hex.vec 1, 0", "prs: hex.vec 1, 0",
             f"ddir: hex.vec {nd}, 0", f"dwait: hex.vec {WAIT_NIBBLES * nd}, 0",
             f"lstate: hex.vec {lvl.nlift}, 0", f"fswitch: hex.vec {2 * ng}, 0",
             *decls(len(lvl.lat), len(lvl.sr))]
    return "\n".join(body) + "\n"


def schedule(lvl, seed=7, frames=900):
    """the frames: (reset, x16, y16, use, dead, press, doors [(dir, wait)], lifts [state], subs [timer])"""
    rng = random.Random(seed)
    pts = []
    for s in lvl.switches:
        x0, y0, x1, y1 = s.box
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        for x, y in ((cx, cy), (x0, cy), (x1, cy), (cx, y0), (cx, y1)):
            for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
                pts.append(((x << 16) + dx, (y << 16) + dy))
    out = []
    for f in range(frames):
        if rng.random() < 0.15:          # stay a while: an SR button runs out
            x, y = (5000 << 16, 5000 << 16)
        else:
            x, y = rng.choice(pts)
        doors = [(rng.choice((0, 0, 0, 1, 2)), rng.choice((0, 0, 0, 1, 37))) for _ in lvl.door_slot]
        lifts = [rng.choice((0, 0, 3)) for _ in range(lvl.nlift)]
        subs = [rng.choice((0, 0, 0, 1)) if g.sub else 0 for g in lvl.groups]
        dead = int(rng.random() < 0.1)
        use = int(rng.random() < 0.7)
        press = int(use and not dead and rng.random() < 0.6)
        out.append((int(f % 97 == 96), x & M32, y & M32, use, dead, press, doors, lifts, subs))
    return out


def feed(sched):
    out = b""
    for reset, x, y, use, dead, press, doors, lifts, subs in sched:
        out += bytes([1, reset]) + struct.pack("<II", x, y) + bytes([use, dead, press])
        for dr, wt in doors:
            out += bytes([dr, wt])
        out += bytes(lifts) + bytes(subs)
    return out


def expect(lvl, sched):
    """the model's steps (World.switch_doors / switch_uses' order) on the same records"""
    on, tm = [0] * len(lvl.lat), [0] * len(lvl.sr)
    want = []
    s32 = lambda v: v - (1 << 32) if v & 0x80000000 else v            # noqa: E731
    for reset, x, y, use, dead, press, doors, lifts, subs in sched:
        if reset:
            on, tm = [0] * len(lvl.lat), [0] * len(lvl.sr)
        x16, y16 = s32(x), s32(y)
        ds = {si: doors[d] for si, d in lvl.door_slot.items()}
        SW.countdown(on, tm, lvl.sr)
        for k in SW.door_presses(lvl.lat, bool(use and not dead), x16, y16,
                                 lambda si: ds[si][0] == 0 and ds[si][1] == 0):
            SW.press(on, tm, lvl.sr, k)
        if press:
            for k in SW.use_presses(lvl.lat, x16, y16, lambda t: lifts[t] == 0,
                                    lambda g: (subs[g] if lvl.wide else 0) == 0):
                SW.press(on, tm, lvl.sr, k)
        want += list(on) + list(tm)
    return want


def test_e1m2_switch_lines(lvl):
    real = [s for s in lvl.switches if s.line < 90000]
    assert [(s.line, s.kind) for s in real] == [(34, "floor"), (93, "door"), (737, "exit"), (1284, "floor"),
                                               (1544, "floor"), (1854, "door"), (1904, "floor")]
    assert [s.line for s in real if s.sw2] == [1544]
    assert not any(s.repeat for s in real), "E1M2's switch lines are all S1 (and the exit)"
    # the boxes are the machines' own (movers.floor_use_boxes)
    mw = WadFile.from_path(FIX)
    fu = dict((b, g) for g, b in MV.floor_use_boxes(mw.linedefs("E1M2"), mw.vertexes("E1M2"), lvl.groups))
    for s in real:
        if s.kind == "floor":
            assert fu[s.box] == s.targets[0]


def test_the_tic_is_switches(tmp_path, lvl):
    sched = schedule(lvl)
    want = expect(lvl, sched)
    got = _run(tmp_path, "tic", tic_program(lvl), feed(sched))
    assert got == want
    # the schedule is not vacuous: every latched line goes on, an SR button runs out, a frame changes several lines
    n = len(lvl.lat) + len(lvl.sr)
    frames = [want[i * n:(i + 1) * n] for i in range(len(sched))]
    for k in range(len(lvl.lat)):
        assert any(fr[k] == 1 for fr in frames), k
    for j in range(len(lvl.sr)):
        assert any(a[len(lvl.lat) + j] == 1 and b[len(lvl.lat) + j] == 0 for a, b in zip(frames, frames[1:]))
    assert any(sum(b[k] == 1 and a[k] == 0 for k in range(len(lvl.lat))) >= 2 for a, b in zip(frames, frames[1:]))


# ---- 2. the picture's dispatch -----------------------------------------------------------------------------------

OWN = [("sra", 2, 0x5A), ("srb", 8, 0x12345678), ("src", 1, 0x0)]
USED = [("sra", 2, 0xC3), ("srb", 8, 0x0BADF00D), ("src", 1, 0x9)]


def blocks_program(own=OWN, used=USED, swap=False):
    blk, call = switch_seg_blocks("swl", used if swap else own, own if swap else used, "swcell")
    body = ["stl.startup_and_init_all"]
    for v in (0, 1, 1, 0):
        body += [f"    hex.set 1, swcell, {v}"]
        for _twice in range(2):
            body += [*call, *_pr("sra", 2), *_pr("srb", 8), *_pr("src", 1), *_pr("swcell", 1)]
    body += ["    stl.loop", "sra: hex.vec 2, 0", "srb: hex.vec 8, 0", "src: hex.vec 1, 0", "swcell: hex.vec 1, 0",
             *blk]
    return "\n".join(body) + "\n"


def blocks_want(own=OWN, used=USED):
    out = []
    for v in (0, 1, 1, 0):
        f = (own, used)[v]
        out += [f[0][2], f[1][2], f[2][2], v]
        out += [0, 0, 0, v]
    return out


def _consts(tmp):
    return [Config().emit_fj_consts(tmp / "fj_consts.fj").resolve(), (FJ / "sim.fj").resolve()]


def test_the_seg_blocks_dispatch_on_the_switch_cell(tmp_path):
    assert _run(tmp_path, "blk", blocks_program(), b"", extra=_consts(tmp_path)) == blocks_want()


# ---- R9: mutants -------------------------------------------------------------------------------------------------

def _drop(lines, pred, repl=""):
    out, done = [], False
    for ln in lines:
        if not done and pred(ln):
            ln, done = repl, True
        out.append(ln)
    assert done
    return out


def _door_mut(fn):
    return lambda lvl: (fn(lvl, tic_text(lvl)[0]), tic_text(lvl)[1])


def _use_mut(fn):
    return lambda lvl: (tic_text(lvl)[0], fn(lvl, tic_text(lvl)[1]))


MUTANTS = {
    # EV_DoDoor's no-thinker test without the wait: a door waiting open takes the press
    "the door's wait test dropped": _door_mut(lambda lvl, ls: [
        ln.replace(f"hex.if0 {WAIT_NIBBLES}, dwait", f"hex.if0 {WAIT_NIBBLES}, rbyte") for ln in ls]),
    # the button never comes back
    "the countdown's swap-back dropped": _door_mut(lambda lvl, ls: _drop(
        ls, lambda l: l.strip().startswith("hex.zero 1, swpr"))),
    # EV_DoFloor on a moving group
    "the moving group's timer test dropped": _use_mut(lambda lvl, ls: [
        ln for ln in ls if not ln.strip().startswith("hex.if1 1, fswitch")]),
    # EV_DoPlat on the first lift of the tag only
    "a lift switch reads one lift": _use_mut(lambda lvl, ls: _drop(
        ls, lambda l: l.strip().startswith("hex.if0 1, lstate + 3*dw"))),
    # switches.press: an SR line's second press while its button is out restarts the timer
    "an SR door switch pressed again while out": _door_mut(lambda lvl, ls: _drop(
        ls, lambda l: l.strip().startswith("hex.if1 1, swpr + %d*dw" % lvl.sr[0]))),
    # a dead player presses a door switch
    "the dead player's guard dropped": _door_mut(lambda lvl, ls: _drop(
        ls, lambda l: l.strip().startswith("hex.if1 1, p_dd0"))),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_mutant_is_caught(tmp_path, lvl, name):
    sched = schedule(lvl)
    got = _run(tmp_path, "mut", tic_program(lvl, MUTANTS[name](lvl)), feed(sched))
    assert got != expect(lvl, sched), name


def test_mutant_swapped_blocks_is_caught(tmp_path):
    got = _run(tmp_path, "bswap", blocks_program(swap=True), b"", extra=_consts(tmp_path))
    assert got != blocks_want()
