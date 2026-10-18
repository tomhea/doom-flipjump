"""M8 -- THE SECTOR LIGHTS in fj, RUN against doomfj.lights (the model every gate steps: world.World._lights_phase).

Nothing here is modelled: each program is the emitter's own text, fed records and read back.

  1. THE PHASE (`lightcode.phase_lines` + `decls` + `tables`): E1M2's nine animated thinkers -- three flashes, a fast
     strobe, a fire flicker, four glows -- plus a synthetic set covering what E1M2 lacks (the slow and the synced
     strobes, a fire whose flicker is a real roll, a one-step glow), ticked hundreds of times with `lvdone` set at
     random, every cell (`ltst`, `ltct`, `rng_lt`) printed after every tic against `lights.tic_all`; and NEW GAME's
     `level_start_lines` mid-run, which must put every cell back.
  2. THE PER-STATE BLOCKS the walk switches on: a light leaf's sprite light base (`wall_renderer.state_dispatch_lines`,
     the leaf's `ss_ltb`, cleared after) and a baked thing's light class (`light_thing_blocks` over
     `light_class_fields`, SET then CLEAR, the two class bytes `sp_lt` / `sp_lt_hi`), at every state of E1M2's real
     thinkers, each dispatched twice (a dispatch whose clean is wrong looks perfect once).

R9: MUTANTS -- one real edit of the emitted text each (a glow's last state off by one, a strobe's times swapped, a
flash's count tables swapped, a roll not drawn, the lvdone guard dropped, a fire's count not reloaded, a thinker reading
the next thinker's cell, the leaf block not cleared, the thing switched on the wrong cell) -- must each make their
program disagree.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import lightcode as LC
from doomfj import lights as L
from doomfj.config import Config
from doomfj.harness import W
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"


@pytest.fixture(scope="module")
def e1m2():
    return L.map_thinkers(WadFile.from_path(FIX), "E1M2")


def _synthetic():
    """the kinds E1M2 lacks: a slow strobe, the two synced strobes, a fire with real rolls, a one-step glow"""
    fire_lv = L._fire_levels(192, 144)
    return [L.LightThinker(400, 3, "strobe", 200, 120, (200, 120), L.SLOWDARK, False),
            L.LightThinker(401, 12, "strobe", 176, 0, (176, 0), L.SLOWDARK, True),
            L.LightThinker(402, 13, "strobe", 160, 96, (160, 96), L.FASTDARK, True),
            L.LightThinker(403, 17, "fire", 192, 144, fire_lv),
            L.LightThinker(404, 8, "glow", 128, 112, L._glow_levels(128, 112)),
            L.LightThinker(405, 1, "flash", 255, 0, (255, 0))]


def test_the_sets_cover_every_kind(e1m2):
    assert [th.sector for th in e1m2] == [1, 70, 97, 194, 256, 261, 283, 323, 350]
    syn = _synthetic()
    assert len(syn[3].levels) >= 3 and any(LC._fire_constant(syn[3], s) is None for s in range(len(syn[3].levels))), (
        "the synthetic fire must roll for real (a non-constant outcome table)")
    assert syn[4].levels == (128, 120)
    kinds = {(th.kind, th.special) for th in e1m2 + syn}
    assert {("flash", 1), ("strobe", 2), ("strobe", 3), ("strobe", 12), ("strobe", 13), ("glow", 8),
            ("fire", 17)} <= kinds


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


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


# ---- 1. the phase ---------------------------------------------------------------------------------------------------

def phase_program(ths, phase=None):
    """per record [cmd, lvdone]: cmd 1 runs the phase (lt_phase, fcall'd as the world tic calls it), cmd 2 NEW GAME's
    level_start_lines; then every cell is printed"""
    n = len(ths)
    body = ["stl.startup_and_init_all", "loop:", "    hex.input 1, rmagic", "    hex.if0 2, rmagic, done",
            "    hex.input 1, rbyte", "    hex.mov 1, lvdone, rbyte",
            "    hex.xor_by 2, rmagic, 2", "    hex.if0 2, rmagic, restart",
            f"    {LC.TIC_CALL}", "    ;show", "restart:", *LC.level_start_lines(ths), "show:"]
    for k in range(n):
        body += _pr(f"ltst + {k}*dw", 1)
    for k in range(n):
        body += _pr(f"ltct + {2 * k}*dw", 2)
    body += _pr("rng_lt", 2)
    body += ["    ;loop", "done:", "    stl.loop",
             *(LC.phase_lines(ths) if phase is None else phase),
             "rmagic: hex.vec 2", "rbyte: hex.vec 2", "lvdone: hex.vec 1, 0",
             *LC.decls(ths), *LC.tables(ths)]
    return "\n".join(body) + "\n"


def phase_schedule(seed, tics=420, restart_at=(300,)):
    rng = random.Random(seed)
    return [(2 if t in restart_at else 1, int(rng.random() < 0.1)) for t in range(tics)]


def phase_expect(ths, sched):
    states, counts, r = L.level_start(ths)
    want = []
    for cmd, done in sched:
        if cmd == 2:
            states, counts, r = L.level_start(ths)
        elif not done:
            r = L.tic_all(ths, states, counts, r)
        want += list(states) + list(counts) + [r]
    return want


def _feed(sched):
    return b"".join(bytes([cmd, done]) for cmd, done in sched)


@pytest.fixture(scope="module")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("lights")


def test_e1m2s_thinkers_run_as_the_model(tmp, e1m2):
    sched = phase_schedule(3)
    want = phase_expect(e1m2, sched)
    assert _run(tmp, "e1m2", phase_program(e1m2), _feed(sched)) == want
    # not vacuous: every state of every thinker was shown, and the stream moved
    n = len(e1m2)
    seen = [set(want[i * (2 * n + 1) + k] for i in range(len(sched))) for k in range(n)]
    assert all(len(s) == len(th.levels) for s, th in zip(seen, e1m2)), seen   # state 0 again after the restart


def test_the_kinds_e1m2_lacks_run_as_the_model(tmp):
    syn = _synthetic()
    sched = phase_schedule(7, tics=600, restart_at=(250, 251))
    assert _run(tmp, "syn", phase_program(syn), _feed(sched)) == phase_expect(syn, sched)


def _mut(lines, old, new, count=1):
    text = "\n".join(lines)
    assert text.count(old) >= count, old
    return text.replace(old, new, count).split("\n")


MUTANTS = [
    # (name, the set, the edit)
    ("a glow's last state off by one", "e1m2", "    hex.xor_by 1, ltst + 7*dw, 5", "    hex.xor_by 1, ltst + 7*dw, 4"),
    ("a strobe's dark time is its bright", "e1m2", "    hex.xor_by 2, ltct + 8*dw, 15", "    hex.xor_by 2, ltct + 8*dw, 5"),
    ("the flash's count tables swapped", "e1m2", "    ltfmin.lookup ltct + 0*dw, rng_lt",
     "    ltfmax.lookup ltct + 0*dw, rng_lt"),
    ("a flash draws no roll", "e1m2", "  lt0_go:\n    hex.inc 2, rng_lt", "  lt0_go:"),
    ("the lvdone guard dropped", "e1m2", "    hex.if1 1, lvdone, lt_out", ""),
    ("a fire's count not reloaded", "syn", "    hex.xor_by 2, ltct + 6*dw, 4", ""),
    ("a thinker reads the next one's state", "e1m2", "    hex.if0 1, ltct + 12*dw, lt6_dn",
     "    hex.if0 1, ltct + 14*dw, lt6_dn"),
]


@pytest.mark.parametrize("name,which,old,new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutants_are_caught(tmp, e1m2, name, which, old, new):
    ths = e1m2 if which == "e1m2" else _synthetic()
    phase = _mut(LC.phase_lines(ths), old, new)
    sched = phase_schedule(11, tics=300, restart_at=())
    assert _run(tmp, "mut", phase_program(ths, phase), _feed(sched)) != phase_expect(ths, sched), name


# ---- 2. the per-state blocks ----------------------------------------------------------------------------------------

def test_the_leaf_base_switches_on_the_state_and_clears(tmp, e1m2):
    """a light leaf's `ss_ltb` (subsector_action): the state's base xored in by state_dispatch_lines, the thing pass
    reads it, `hex.zero` after -- at every state of every thinker, twice each"""
    from doomfj.wall_renderer import state_dispatch_lines

    def program(zero=True, cell_shift=0):
        body, blocks, want = ["stl.startup_and_init_all"], [], []
        for k, th in enumerate(e1m2):
            vals = [0x101 * (k + 1) + 0x37 * s for s in range(len(th.levels))]
            blocks += [f"leaf{k}:", *state_dispatch_lines(f"slt{k}", f"ltst + {k + cell_shift}*dw",
                                                           [[f"    hex.xor_by 4, ss_ltb, {v}"] for v in vals]),
                       "    stl.fret lret"]
            for s in list(range(len(th.levels))) * 2:
                body += [f"    hex.set 1, ltst + {k}*dw, {s}", f"    stl.fcall leaf{k}, lret", *_pr("ss_ltb", 4)]
                body += ["    hex.zero 4, ss_ltb"] if zero else []
                body += _pr("ss_ltb", 4) + _pr(f"ltst + {k}*dw", 1)
                want += [vals[s], 0, s]
        text = "\n".join(body + ["    stl.loop", "ss_ltb: hex.vec 4", f"ltst: hex.vec {len(e1m2) + 1}",
                                 "lret: hex.vec w/4"] + blocks)
        return text + "\n", want

    text, want = program()
    assert _run(tmp, "leaf", text, b"") == want
    for kw in ({"zero": False}, {"cell_shift": 1}):           # R9: not cleared / the wrong thinker's cell
        text, _w = program(**kw)
        assert _run(tmp, "leaf_mut", text, b"") != want, kw


THING_DECLS = ["xb_ret: ;0", "sp_x: hex.vec 8", "sp_y: hex.vec 8", "sp_z: hex.vec 8", "sp_left: hex.vec 8",
               "sp_w: hex.vec 8", "sp_hh: hex.vec 8", "sp_base: hex.vec 4", "sp_dw: hex.vec 2", "sp_lt: hex.vec 2",
               "sp_lt_hi: hex.vec 2", "sp_tzmax: hex.vec 8", "sp_mon: hex.vec 2", "sp_tzmax2: hex.vec 8",
               "sp_base2: hex.vec 4", "cls_rd: hex.vec 4"]


def test_a_baked_things_light_class_follows_the_state(tmp, e1m2):
    """a baked thing in an animated light sector (subsector_action): `light_thing_blocks` over `light_class_fields`,
    called twice (SET, CLEAR) as the call site does; the record body reads the class as 4 nibbles from `sp_lt` -- a
    class past 255 must reach `sp_lt_hi`, and both bytes must be 0 after the CLEAR"""
    from doomfj.wall_renderer import THING_XORBY_FIELDS, light_class_fields, light_thing_blocks
    base = [(n, w_, (k * 0x1111 + 0x23) % (16 ** w_)) for k, (n, w_) in enumerate(THING_XORBY_FIELDS)]

    def program(wrong_cell=False):
        body, data, want = ["stl.startup_and_init_all"], [], []
        for k, th in enumerate(e1m2):
            classes = [(0x2B + 0x91 * s + 0x40 * k) % 0x400 for s in range(len(th.levels))]
            blk, call = light_thing_blocks(f"tlt{k}", f"ltst + {(k + 1) % len(e1m2) if wrong_cell else k}*dw",
                                           [light_class_fields(base, c) for c in classes])
            data += blk
            for s in list(range(len(th.levels))) * 2:
                body += [f"    hex.set 1, ltst + {k}*dw, {s}", call, "    hex.mov 4, cls_rd, sp_lt",
                         *_pr("cls_rd", 4), call, "    hex.mov 4, cls_rd, sp_lt", *_pr("cls_rd", 4)]
                want += [classes[s], 0]
        assert any(c > 0xFF for c in want), "no class past one byte: the sp_lt_hi case is vacuous"
        text = "\n".join(body + ["    stl.loop", f"ltst: hex.vec {len(e1m2)}"] + THING_DECLS + data)
        return text + "\n", want

    text, want = program()
    assert _run(tmp, "thing", text, b"") == want
    text, _w = program(wrong_cell=True)                     # R9: switched on another thinker's state
    assert _run(tmp, "thing_mut", text, b"") != want
