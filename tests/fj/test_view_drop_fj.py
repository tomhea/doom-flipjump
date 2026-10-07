"""M7 P8a A -- THE DYING VIEW SINKS, in fj (docs/gp-final-plan.md 1.1 / 3.1 row A / 4.3 steps 5 and 9): the REAL emitted
text on the flipjump engine against the MODEL.

  * the death think's drop -- `hurtcode.turn_lines(sink=True)` (`dt_turn`, called once a dead tic after the psprites):
    p_vd += 1 while p_vd < 35 (`hurtcode.sink_decls`' cap), then the P7 turn and fade -- against
    `combat.CombatMixin._death_think` in the "final" player mode, TICS tics from start depths 0, 1, 17, 33, 34, 35
    (and above the cap: a poked 40 is left alone, as the model's `<` does), with and without an attacker (the turn
    must still run after the drop: P_DeathThink's order psprites -> drop -> turn);
  * the landing -- `wall_renderer.landing_drop_lines()` (after `dsc_done`): viewz = (floor + 41) << 16 as the landing
    sets it, then viewz -= p_vd << 16 -- against the oracle's sunk eye `view_z(floor) - (d << 16)` (mod 2^32) for floors
    across E1M1's range and beyond, including the eyes that cross zero (floor -40 .. -6: the borrow must run through
    nibble 7) and every d 0..35;
  * the restart -- `restartcode.view_restart_lines()` puts any p_vd back to the standing eye (0).

R9: each mutant must be caught -- `no_sink` (no increment), `sink_floor` (the cap at 34 or 36: viewheight stops at 7 or
5), `sink_restart` (the restart forgets p_vd), `no_land` (the landing subtracts nothing), `land_shift` (p_vd << 12),
`land_noborrow` (the subtract stops at nibble 5: an eye that crosses zero keeps its high half).
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import hurtcode as HC
from doomfj import monstercode as MC
from doomfj import restartcode as RC
from doomfj import wall_renderer as WR
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj
from doomfj.reference_model import SLOPERANGE, VIEW_DROP_MAX, ReferenceModel
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.wall_renderer import hoisted_scratch_fj

FJ = Path(__file__).resolve().parents[2] / "src" / "fj"
M32 = 0xFFFFFFFF
TICS = 40
ROW_OFFSET = 2
FLOORS = (-300, -48, -41, -40, -36, -35, -34, -20, -7, -6, -5, 0, 8, 24, 40, 255, 256, 1000, 4000)


@pytest.fixture(scope="module")
def world():
    from doomfj.world import World
    w = World(player="final", monsters="final")
    assert w.layout.nmon == 53
    return w


def _think_cases(w):
    rnd = random.Random(0x8A)
    nmon = w.layout.nmon
    vx, vy = 1056 << 16 | 0x8000, (-3616 << 16) + 0x4321
    out = []
    for k, vd in enumerate((0, 1, 17, 33, 34, 35, 40)):
        out.append((vx, vy, rnd.getrandbits(32), rnd.randrange(101), 0, 0, 0, vd))           # no attacker
        m = (k * 11) % nmon
        ax, ay = ((vx >> 16) + 300 - 90 * k) << 16, ((vy >> 16) - 200 + 70 * k) << 16
        out.append((vx, vy, rnd.getrandbits(32), rnd.randrange(101), m + 1, ax, ay, vd))     # the turn after it
    return out


def _model_think(w, case):
    """the model's death think, TICS tics -> [(p_vdrop, viewangle, damagecount)] after each"""
    from doomfj.world import KEYS, TicEvents
    vx, vy, ang, dc, atk, ax, ay, vd = case
    ws = w.reset(w.ws.skill) or w.ws
    ws.p_dead, ws.px, ws.py, ws.pangle, ws.p_damagecount, ws.p_attacker = 1, vx, vy, ang, dc, atk
    ws.p_vdrop = vd
    if atk:
        ws.mon_x[atk - 1], ws.mon_y[atk - 1] = ax >> 16, ay >> 16
    out = []
    for _ in range(TICS):
        w._death_think(dict.fromkeys(KEYS, False), TicEvents(0))
        out.append((ws.p_vdrop, ws.pangle, ws.p_damagecount))
    return out


def _land_cases():
    return [(f, d) for f in FLOORS for d in range(VIEW_DROP_MAX + 1)]


def _model_land(case):
    f, d = case
    return (ReferenceModel.view_z(f) - (d << 16)) & M32


def _program(w, think, land, leaf, decls, landing, restart):
    rows = w.layout.nmon + ROW_OFFSET
    body, data = ["stl.startup_and_init_all"], []
    for k, (vx, vy, ang, dc, atk, ax, ay, vd) in enumerate(think):
        body += ["hex.mov 8, viewx, vx%d" % k, "hex.mov 8, viewy, vy%d" % k, "hex.mov 8, viewangle, va%d" % k,
                 "hex.set 2, p_dc, %d" % dc, "hex.set 2, p_atk, %d" % atk, "hex.set 2, p_vd, %d" % vd]
        if atk:
            t = atk - 1 + ROW_OFFSET
            body += ["hex.mov 8, thpos_rt + %d*dw, ax%d" % (16 * t, k), "hex.mov 8, thpos_rt + %d*dw, ay%d" % (16 * t + 8, k)]
        body += ["rep(%d, i) tm_tic" % TICS, "stl.output 10"]
        data += ["vx%d: hex.vec 8, %d" % (k, vx & M32), "vy%d: hex.vec 8, %d" % (k, vy & M32),
                 "va%d: hex.vec 8, %d" % (k, ang), "ax%d: hex.vec 8, %d" % (k, ax & M32),
                 "ay%d: hex.vec 8, %d" % (k, ay & M32)]
    # the landing: the descend pre-walk's `hex.set 8, viewz, <view_z(floor)>`, then the drop lines (one copy, called)
    for k, (f, d) in enumerate(land):
        body += ["hex.set 8, viewz, %d" % (ReferenceModel.view_z(f) & M32), "hex.set 2, p_vd, %d" % d,
                 "stl.fcall tl_land, tl_lret", "hex.print_as_digit 8, viewz, 0", "stl.output_char 32"]
    body += ["stl.output 10"]
    # the restart: from every depth back to the standing eye
    for d in (35, 17, 1, 0):
        body += ["hex.set 2, p_vd, %d" % d, "stl.fcall tl_rs, tl_rret", "hex.print_as_digit 2, p_vd, 0",
                 "stl.output_char 32"]
    body += ["stl.output 10", "stl.loop",
             "tl_land:", *landing, "stl.fret tl_lret",
             "tl_rs:", *restart, "stl.fret tl_rret"]
    macro = ["def tm_tic < dt_tret, dt_turn, viewangle, p_dc, p_vd {", "    stl.fcall dt_turn, dt_tret",
             "    hex.print_as_digit 2, p_vd, 0", "    hex.print_as_digit 8, viewangle, 0",
             "    hex.print_as_digit 2, p_dc, 0", "    stl.output_char 32", "}"]
    data += ["viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8", "viewz: hex.vec 8", "p_dc: hex.vec 2",
             "p_atk: hex.vec 2", "tl_lret: hex.vec w/4", "tl_rret: hex.vec w/4",
             *RC.view_decls(), *decls,
             "thpos_rt: hex.vec %d" % (16 * rows), *HC.TURN_DECLS, *leaf,
             *MC.ROT_DECLS, *MC.rotation_leaf_lines(1), MC.rot_table_fj(),
             generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
             generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    return "\n".join(macro + body + data) + "\n" + hoisted_scratch_fj()


def _parts():
    return dict(leaf=HC.turn_lines([m + ROW_OFFSET for m in range(53)], sink=True), decls=HC.sink_decls(),
                landing=WR.landing_drop_lines(), restart=RC.view_restart_lines())


def _run(tmp_path, name, w, think, land, parts):
    p = tmp_path / ("%s.fj" % name)
    p.write_text(_program(w, think, land, **parts), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    out = tmp_path / ("%s.fjm" % name)
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
                 (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], out,
                memory_width=W, print_time=False)
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    lines = io.get_output(allow_incomplete_output=True).decode("ascii").split("\n")
    nt = len(think)
    got_think = [[(int(t[:2], 16), int(t[2:10], 16), int(t[10:], 16)) for t in ln.split()] for ln in lines[:nt]]
    got_land = [int(t, 16) for t in lines[nt].split()]
    got_rs = [int(t, 16) for t in lines[nt + 1].split()]
    return got_think, got_land, got_rs


def _verdict(w, got, think, land):
    got_think, got_land, got_rs = got
    want_think = [_model_think(w, c) for c in think]
    want_land = [_model_land(c) for c in land]
    for k, (g, wnt) in enumerate(zip(got_think, want_think)):
        if g != wnt:
            t = next((i for i, (a, b) in enumerate(zip(g, wnt)) if a != b), len(g))
            return "think case %d %s, tic %d: fj %s, model %s" % (k, think[k], t, g[t:t + 1], wnt[t:t + 1])
    if len(got_think) != len(want_think):
        return "%d think cases printed of %d" % (len(got_think), len(want_think))
    bad = [(c, hex(g), hex(wn)) for c, g, wn in zip(land, got_land, want_land) if g != wn]
    if bad or len(got_land) != len(want_land):
        return "landing: %d of %d differ, first %s" % (len(bad), len(want_land), bad[:1])
    if got_rs != [0, 0, 0, 0]:
        return "restart: p_vd %s, not 0" % got_rs
    return None


def test_the_view_drops_as_the_model(tmp_path, world):
    think, land = _think_cases(world), _land_cases()
    got = _run(tmp_path, "vdrop", world, think, land, _parts())
    bad = _verdict(world, got, think, land)
    assert bad is None, bad
    # vacuity: the drop climbed to the cap and rested there; the turn ran after it; an eye crossed zero
    want = [_model_think(world, c) for c in think]
    assert any(r[0][0] == 1 and r[34][0] == 35 and r[-1][0] == 35 for r in want)
    assert any(c[4] and r[0][1] != c[2] for c, r in zip(think, want))
    assert any((ReferenceModel.view_z(f) >= 0) != (ReferenceModel.view_z(f) - (d << 16) >= 0) for f, d in land)


def _sub(lines, old, new):
    assert sum(ln == old for ln in lines) == 1, (old, lines)
    return [new if ln == old else ln for ln in lines]


MUTANTS = {
    "no_sink": lambda p: dict(p, leaf=_sub(p["leaf"], "    hex.inc 2, p_vd", "    ;dtt_vend")),
    "sink_floor_7": lambda p: dict(p, decls=[d.replace(", %d" % VIEW_DROP_MAX, ", %d" % (VIEW_DROP_MAX - 1))
                                             for d in p["decls"]]),
    "sink_floor_5": lambda p: dict(p, decls=[d.replace(", %d" % VIEW_DROP_MAX, ", %d" % (VIEW_DROP_MAX + 1))
                                             for d in p["decls"]]),
    "sink_restart": lambda p: dict(p, restart=[]),
    "no_land": lambda p: dict(p, landing=_sub(p["landing"], "hex.sub_shifted 8, 2, viewz, p_vd, 4", ";lnd_vd_end")),
    "land_shift": lambda p: dict(p, landing=_sub(p["landing"], "hex.sub_shifted 8, 2, viewz, p_vd, 4",
                                                 "hex.sub_shifted 8, 2, viewz, p_vd, 3")),
    "land_noborrow": lambda p: dict(p, landing=_sub(p["landing"], "hex.sub_shifted 8, 2, viewz, p_vd, 4",
                                                    "hex.sub 2, viewz + 4*dw, p_vd")),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_broken_drop_is_caught(tmp_path, world, name):
    think, land = _think_cases(world), _land_cases()
    parts = MUTANTS[name](_parts())
    assert parts != _parts(), name
    got = _run(tmp_path, "mut", world, think, land, parts)
    assert _verdict(world, got, think, land) is not None, "a drop with %r passed every case" % name
