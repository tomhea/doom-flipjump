"""M7 P7 -- the dead view TURNS TO THE KILLER (owner, 2026-10-05; docs/gp-p67-interface.md section 10, O1): the fj
leaf `hurtcode.turn_lines` (`dt_turn`) on the real flipjump engine against the MODEL's own death think,
`combat.CombatMixin._death_think` in the "full" player mode (`_turn_to_attacker`): P_DeathThink's
R_PointToAngle2 to the attacker, the ANG5 turn the short way, the snap and the damage-flash fade once within ANG5,
and the plain fade with no attacker.

Each case puts a viewer (fractional 16.16), a view angle, a damage count and an attacker id (0 none, 1 + one of
E1M1's 53 monster slots, through BOTH levels of the id's dispatch) into the cells, the attacker's thpos_rt row at a
whole-unit position (its row is NOT its slot: `slot_rows` is offset), and runs TICS death-think tics, printing the
view angle and the damage count after each -- the model steps the same state through `_death_think` with no keys.
Cases cover every octant, the attacker on the viewer (angle 0), the deltas at +-ANG5 and +-ANG5 +- 1, exactly
ANG180 (DOOM turns the minus way), long turns (most of a half circle) and the no-attacker fade.

R9 (the coordinator's three, each must be caught): no turn; the turn's direction flipped; the turn never stops.
Plus: the fade while turning (DOOM fades only once facing).
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import hurtcode as HC
from doomfj import monstercode as MC
from doomfj.combat import ANG5
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj
from doomfj.reference_model import SLOPERANGE
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.wall_renderer import hoisted_scratch_fj

FJ = Path(__file__).resolve().parents[2] / "src" / "fj"
M32 = 0xFFFFFFFF
TICS = 40
ROW_OFFSET = 2                     # monster slot m's runtime thing is m + ROW_OFFSET


@pytest.fixture(scope="module")
def world():
    from doomfj.world import World
    w = World(player="full", monsters="full")
    assert w.layout.nmon == 53
    return w


def _cases(w):
    rm, rnd = w.rm, random.Random(0x77)
    nmon = w.layout.nmon
    out = []
    views = [(1056 << 16 | 0x8000, (-3616 << 16) + 0x4321), (-512 << 16, 700 << 16 | 0x1), (0, 0)]
    offs = [(300, 0), (0, 300), (-300, 0), (0, -300), (200, 200), (-200, 200), (200, -200), (-200, -200),
            (500, 7), (7, 500), (-500, -7), (1, 0), (0, 0), (-3, 900)]
    for k, ((vx, vy), (dx, dy)) in enumerate([(v, o) for v in views for o in offs]):
        m = (k * 7) % nmon                                # every hi nibble of the id: 1..53
        ax, ay = ((vx >> 16) + dx) << 16, ((vy >> 16) + dy) << 16
        out.append((vx, vy, rnd.getrandbits(32), rnd.randrange(101), m + 1, ax, ay))
    # the boundaries: delta exactly +-ANG5, +-ANG5 +- 1, exactly ANG180, just past it
    vx, vy = views[0]
    ax, ay = ((vx >> 16) + 123) << 16, ((vy >> 16) - 45) << 16
    a = rm.point_to_angle(vx, vy, ax, ay)
    for d in (ANG5, ANG5 - 1, ANG5 + 1, -ANG5, -ANG5 + 1, -ANG5 - 1, 0x80000000, 0x7FFFFFFF, 0x80000001, 0, 1):
        out.append((vx, vy, (a - d) & M32, 50, nmon, ax, ay))
    # no attacker: the flash fades and nothing turns
    out.append((vx, vy, 0x12345678, 30, 0, 0, 0))
    out.append((vx, vy, 0x12345678, 0, 0, 0, 0))
    return out


def _model(w, case):
    """the model's death think, TICS tics -> [(viewangle, damagecount)] after each"""
    from doomfj.world import KEYS, TicEvents
    vx, vy, ang, dc, atk, ax, ay = case
    ws = w.reset(w.ws.skill) or w.ws
    ws.p_dead, ws.px, ws.py, ws.pangle, ws.p_damagecount, ws.p_attacker = 1, vx, vy, ang, dc, atk
    if atk:
        ws.mon_x[atk - 1], ws.mon_y[atk - 1] = ax >> 16, ay >> 16
    out = []
    for _ in range(TICS):
        w._death_think(dict.fromkeys(KEYS, False), TicEvents(0))
        out.append((ws.pangle, ws.p_damagecount))
    return out


def _program(cases, nmon, leaf):
    rows = nmon + ROW_OFFSET
    body, data = ["stl.startup_and_init_all"], []
    for k, (vx, vy, ang, dc, atk, ax, ay) in enumerate(cases):
        body += ["hex.mov 8, viewx, vx%d" % k, "hex.mov 8, viewy, vy%d" % k, "hex.mov 8, viewangle, va%d" % k,
                 "hex.set 2, p_dc, %d" % dc, "hex.set 2, p_atk, %d" % atk]
        if atk:
            t = atk - 1 + ROW_OFFSET
            body += ["hex.mov 8, thpos_rt + %d*dw, ax%d" % (16 * t, k), "hex.mov 8, thpos_rt + %d*dw, ay%d" % (16 * t + 8, k)]
        body += ["rep(%d, i) tm_tic" % TICS, "stl.output 10"]
        data += ["vx%d: hex.vec 8, %d" % (k, vx & M32), "vy%d: hex.vec 8, %d" % (k, vy & M32),
                 "va%d: hex.vec 8, %d" % (k, ang), "ax%d: hex.vec 8, %d" % (k, ax & M32),
                 "ay%d: hex.vec 8, %d" % (k, ay & M32)]
    body += ["stl.loop"]
    macro = ["def tm_tic < dt_tret, dt_turn, viewangle, p_dc {", "    stl.fcall dt_turn, dt_tret", "    hex.print_as_digit 8, viewangle, 0",
             "    hex.print_as_digit 2, p_dc, 0", "    stl.output_char 32", "}"]
    data += ["viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8", "p_dc: hex.vec 2", "p_atk: hex.vec 2",
             "thpos_rt: hex.vec %d" % (16 * rows), *HC.TURN_DECLS, *leaf,
             # the monsters' rotation leaf the turn shares its R_PointToAngle2 with (monstercode, P3.1)
             *MC.ROT_DECLS, *MC.rotation_leaf_lines(1), MC.rot_table_fj(),
             generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
             generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    return "\n".join(macro + body + data) + "\n" + hoisted_scratch_fj()


def _run(tmp_path, name, w, cases, leaf):
    p = tmp_path / ("%s.fj" % name)
    p.write_text(_program(cases, w.layout.nmon, leaf), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    out = tmp_path / ("%s.fjm" % name)
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
                 (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], out,
                memory_width=W, print_time=False)
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    lines = io.get_output(allow_incomplete_output=True).decode("ascii").split("\n")
    return [[(int(t[:8], 16), int(t[8:], 16)) for t in ln.split()] for ln in lines[:len(cases)]]


def _leaf(w):
    return HC.turn_lines([m + ROW_OFFSET for m in range(w.layout.nmon)])


def _first_diff(got, want, cases):
    for k, (g, wnt) in enumerate(zip(got, want)):
        if g != wnt:
            t = next((i for i, (a, b) in enumerate(zip(g, wnt)) if a != b), len(g))
            return "case %d %s, tic %d: fj %s, model %s" % (k, cases[k], t, g[t:t + 1], wnt[t:t + 1])
    return None if len(got) == len(want) else "%d cases printed of %d" % (len(got), len(want))


def test_the_dead_view_turns_to_the_killer_as_the_model(tmp_path, world):
    cases = _cases(world)
    want = [_model(world, c) for c in cases]
    got = _run(tmp_path, "turn", world, cases, _leaf(world))
    bad = _first_diff(got, want, cases)
    assert bad is None, bad
    # vacuity: turns both ways, snaps, long turns, no-attacker fades, the dispatch's every level
    turned = [sum(1 for (a0, _), (a1, _) in zip([(c[2], 0)] + r, r) if a0 != a1) for c, r in zip(cases, want)]
    assert max(turned) >= 20 and any(t == 1 for t in turned)
    plus = minus = 0
    for c, r in zip(cases, want):
        d = (r[0][0] - c[2]) & M32
        plus += d == ANG5
        minus += d == (-ANG5 & M32)
    assert plus and minus, (plus, minus)
    assert {c[4] >> 4 for c in cases if c[4]} == {0, 1, 2, 3}
    assert any(c[4] == 0 and r[-1][1] == 0 and r[0][0] == c[2] for c, r in zip(cases, want))


def _mutate(leaf, old, new):
    assert sum(ln == old for ln in leaf) == 1, old
    return [new if ln == old else ln for ln in leaf]


MUTANTS = {
    "no turn": lambda lf: _mutate(_mutate(lf, "    hex.add 8, viewangle, dt_c5", "    ;dtt_out"),
                                  "    hex.sub 8, viewangle, dt_c5", "    ;dtt_out"),
    "the turn's direction flipped": lambda lf: _mutate(
        lf, "    hex.if_flags dt_d + 7*dw, 0xFF00, dtt_plus, dtt_minus",
        "    hex.if_flags dt_d + 7*dw, 0xFF00, dtt_minus, dtt_plus"),
    "the turn never stops": lambda lf: _mutate(_mutate(
        lf, "    hex.cmp 8, dt_d, dt_c5, dtt_face, dtt_far, dtt_far", "    ;dtt_far"),
        "    hex.cmp 8, dt_d, dt_cm5, dtt_turn, dtt_turn, dtt_face", "    ;dtt_turn"),
    "the flash fades while turning": lambda lf: _mutate(lf, "  dtt_turn:", "  dtt_turn: hex.if0 2, p_dc, dtt_tz\n"
                                                            "    hex.dec 2, p_dc\n  dtt_tz:"),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_broken_turn_is_caught(tmp_path, world, name):
    cases = _cases(world)
    want = [_model(world, c) for c in cases]
    got = _run(tmp_path, "mut", world, cases, MUTANTS[name](_leaf(world)))
    assert _first_diff(got, want, cases) is not None, "a turn with %r passed every case" % name
