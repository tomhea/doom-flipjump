"""M7 P5 (doomfj.hurtcode, monsterdecide.attack_leaf_lines(full=True)): the monsters' attacks APPLIED, on the real
flipjump engine -- `md_attack`'s full emission, the very text the emitter splices, driven directly with poked
registers, against the model's own `_monster_attack` (World(monsters="full"): _mon_hitscan, _mon_melee, the
fireball) -- without the heavy decide harness (tests/fj/test_monster_decide_fj.py, which runs the whole tic).

Each record names one attacker (a zombieman's A_PosAttack, a shotgun guy's A_SPosAttack, an imp's A_TroopAttack, a
demon's A_SargAttack) and pokes, identically on both sides: the monster's position and stream, its seen flag, the
near trace's outcome (`sl_los` is a STUB returning the poked `sl_hit` -- 1: the trace HIT a wall, no line of
sight, as monstersight's -- and the model's `los_to_player` returns its negation), the player's position -- in melee reach, around NEAR, across the bullets' 16-unit reach buckets and past
2048 -- and the player's cells (health, armor, armortype, damagecount, dead, stream; the ready pistol). `pj_spawn` is
a STUB too (agent C implements it): it counts its calls and keeps mm_x / mm_y, as the model's `_spawn_fireball` is
replaced by a recorder. After every record: the monster's stream and facing, the player's cells, the fireballs.

R9: the bullets' reach L off by 16 (mbul built with L + 16), the attack sight ignored by the bullets, the claw
without its sight, the bite at `<=` its reach, the imp's fireball never spawned, and a bullet's damage not handed
on must each part.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import hurtcode as H
from doomfj import monstercode as MC
from doomfj import monsterdecide as MD
from doomfj import weaponcode as WC
from doomfj.combat import BULLETS, half_width_table
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.sight import NEAR
from doomfj.world import MELEE_REACH, TicEvents, World, aprox_distance

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 360
M32 = 0xFFFFFFFF
ACTION = {3004: "A_PosAttack", 9: "A_SPosAttack", 3001: "A_TroopAttack", 3002: "A_SargAttack"}
CELLS = (("mm_rng", 2), ("mm_fa", 1), ("p_hp", 3), ("p_ar", 2), ("p_at", 1), ("p_dc", 2), ("p_dead", 1),
         ("rng_pl", 2), ("pj_n", 1), ("pj_lx", 4), ("pj_ly", 4))


def _world():
    return World(skill=gd.SK_HARD, monsters="full", sight_rule="seen", player="fire")


def _slots(w):
    """one active slot per attacker type"""
    out = {}
    for m, t in enumerate(w.mon_things):
        if t.type in ACTION and t.type not in out and w.ws.mon_active[m]:
            out[t.type] = m
    assert set(out) == set(ACTION), out
    return out


def _records(w):
    """[(type, (mx, my), (px16, py16), mon_rng, seen, sl_hit, player pokes)]"""
    rnd = random.Random(0x5A7)
    out = []
    types = sorted(ACTION)
    for r in range(N):
        tp = types[r % 4]
        mx, my = rnd.randint(-1500, 3000), rnd.randint(-3000, 1500)
        d = rnd.choice((rnd.randint(0, MELEE_REACH + 4), MELEE_REACH - 1, MELEE_REACH, NEAR, NEAR + 1,
                        rnd.randint(0, NEAR + 20), 16 * rnd.randint(1, 128), 16 * rnd.randint(1, 128) - 1,
                        rnd.randint(0, 2100), 2047, 2048, rnd.randint(2048, 2300)))
        k = rnd.randrange(3)
        if k == 0:
            dx, dy = d, 0
        elif k == 1:
            dx, dy = 0, d
        else:
            a = rnd.randint(0, d)
            dx, dy = a, 0
            while aprox_distance(dx, dy) < d:
                dy += 1
        dx, dy = dx * rnd.choice((1, -1)), dy * rnd.choice((1, -1))
        px16 = (((mx + dx) << 16) | rnd.randrange(1 << 16)) & M32
        py16 = (((my + dy) << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        hp = rnd.choice((100, 100, 100, rnd.randint(1, 30), 5, 0))
        pokes = {"p_health": hp, "p_armor": rnd.choice((0, 0, 3, 50, 200)), "p_armortype": rnd.choice((0, 1, 2)),
                 "p_damagecount": rnd.randint(0, 100), "p_dead": int(hp <= 0 or rnd.random() < 0.04),
                 "rng_player": rnd.randrange(256)}
        out.append((tp, (mx, my), (px16, py16), rnd.randrange(256), int(rnd.random() < 0.6),
                    int(rnd.random() < 0.5), pokes))
    return out


def _signed32(v):
    return v - (1 << 32) if v >> 31 else v


class _Fire:
    def __init__(self):
        self.n, self.last = 0, (0, 0)


def _apply(w, slots, rec, fire, ev):
    tp, (mx, my), (px16, py16), mrng, seen, hit, pokes = rec
    m = slots[tp]
    ws = w.ws
    ws.px, ws.py = _signed32(px16), _signed32(py16)
    ws.mon_x[m], ws.mon_y[m], ws.mon_rng[m], ws.mon_seen[m], ws.mon_target[m] = mx, my, mrng, seen, 1
    for f, v in pokes.items():
        setattr(ws, f, v)
    ws.p_ready, ws.p_wpn_state, ws.p_wpn_tics, ws.p_wpn_sy = (
        gd.WP_PISTOL, gd.STATE_INDEX[gd.WEAPONINFO[gd.WP_PISTOL].readystate], 1, 32)
    w.los_to_player = lambda world, mm, _h=hit: not _h        # sl_hit: the trace was blocked

    def spawn(mm, e):
        fire.n += 1
        fire.last = (ws.mon_x[mm], ws.mon_y[mm])
    w._spawn_fireball = spawn
    w._monster_attack(m, ACTION[tp], ev)
    return m


def _row(w, m, fire) -> str:
    ws = w.ws
    vals = [ws.mon_rng[m], ws.mon_facing[m], ws.p_health & 0xFFF, ws.p_armor, ws.p_armortype, ws.p_damagecount,
            ws.p_dead, ws.rng_player, fire.n & 15, fire.last[0] & 0xFFFF, fire.last[1] & 0xFFFF]
    return "".join("%0*x" % (n, v) for (_c, n), v in zip(CELLS, vals))


def _expected(records) -> bytes:
    w = _world()
    slots = _slots(w)
    fire = _Fire()
    lines = []
    for rec in records:
        m = _apply(w, slots, rec, fire, TicEvents(0))
        lines.append(_row(w, m, fire))
    return ("\n".join(lines) + "\n").encode()


def _l16_mbul(hwt):
    vals = H.mbul_values(hwt, fold=lambda s, dmg: min(0x800, H.bullet_reach(hwt, s) + 16) | dmg)
    return generate_dispatch_table_fj("mbul", vals, index_nibbles=2, result_nibbles=3)


MUTANTS = {
    "l16": None,                                                                     # the table, below
    "nosight": ("    hex.if0 1, md_seen, md_bul_out\n", ""),
    "clawnosight": ("    hex.if0 1, mm_asr, md_claw_f\n", ""),
    "bitele": ("    hex.cmp 4, mt_d, mt_c60, md_bite_r, md_out, md_out\n",
               "    hex.cmp 4, mt_d, mt_c60, md_bite_r, md_bite_r, md_out\n"),
    "nofireball": ("    stl.fcall pj_spawn, pj_sret\n", ""),
    "bulnodmg": ("    hex.mov 1, dp_dmg, md_row\n", ""),
}


def _program(w, mut=None):
    hwt = half_width_table(w.rm.sine)
    tables = H.tables_fj(hwt)
    if mut == "l16":
        tables = [t if "ns mbul {" not in t else _l16_mbul(hwt) for t in tables]
    attack = "\n".join(MD.attack_leaf_lines(full=True)) + "\n"
    if mut and MUTANTS[mut]:
        old, new = MUTANTS[mut]
        assert attack.count(old) == 1, (mut, attack.count(old))
        attack = attack.replace(old, new)
    lines = (MD.todist_leaf_lines() + MD.octant_leaf_lines() + MD.as_leaf_lines() + MC.dist_leaf_lines()
             + H.dp_lines()
             + ["sl_los:", "    stl.fret sl_ret",                                  # the near trace: the poke
                "pj_spawn:", "    hex.inc 1, pj_n", "    hex.mov 4, pj_lx, mm_x", "    hex.mov 4, pj_ly, mm_y",
                "    stl.fret pj_sret"])
    states, frames = WC.weapon_states(), WC.overlay_frames()
    decls = (H.hurt_decls(H.level_start(w)) + WC.weapon_decls(WC.level_start(w.mw, "E1M1"), states, frames)
             + WC.weapon_const_decls() + MD.context_decls() + MC.P32A_SCRATCH
             + ["mm_x: hex.vec 4", "mm_y: hex.vec 4", "mm_rng: hex.vec 2",
                "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
                "mt_t: hex.vec 4", "viewx: hex.vec 8", "viewy: hex.vec 8",
                "sl_hit: hex.vec 1", "sl_ret: hex.vec w/4", "pj_sret: hex.vec w/4", "pj_n: hex.vec 1",
                "pj_lx: hex.vec 4", "pj_ly: hex.vec 4"])
    return decls, "\n".join(lines) + "\n" + attack, tables


def _build(tmp_path, name, mut=None):
    w = _world()
    records = _records(w)
    kinds = MD.ATTACK_KINDS
    nib = {"p_health": ("p_hp", 3), "p_armor": ("p_ar", 2), "p_armortype": ("p_at", 1),
           "p_damagecount": ("p_dc", 2), "p_dead": ("p_dead", 1), "rng_player": ("rng_pl", 2)}
    states, frames = WC.weapon_states(), WC.overlay_frames()
    ready = gd.WEAPONINFO[gd.WP_PISTOL].readystate
    body = ["stl.startup_and_init_all"]
    for tp, (mx, my), (px16, py16), mrng, seen, hit, pokes in records:
        body += ["hex.set 8, viewx, %d" % px16, "hex.set 8, viewy, %d" % py16,
                 "hex.set 4, mm_x, %d" % (mx & 0xFFFF), "hex.set 4, mm_y, %d" % (my & 0xFFFF),
                 "hex.set 2, mm_rng, %d" % mrng, "hex.set 1, mm_seen, %d" % seen, "hex.set 1, sl_hit, %d" % hit,
                 "hex.set 1, mm_kind, %d" % kinds[ACTION[tp]],
                 "hex.set 1, wp_rdy, %d" % gd.WP_PISTOL, "hex.set 2, wp_st, %d" % states.index(ready),
                 "hex.set 1, wp_tics, 1", "hex.set 2, wp_sy, 32",
                 "hex.set 1, wp_frm, %d" % frames.index(WC.psprite_lump(ready))]
        body += ["hex.set %d, %s, %d" % (nib[f][1], nib[f][0], v & (16 ** nib[f][1] - 1)) for f, v in pokes.items()]
        body += ["stl.fcall md_attack, md_ret"]
        body += ["hex.print_as_digit %d, %s, 0" % (n, c) for c, n in CELLS]
        body += ["stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = _program(w, mut)
    prog = "\n".join(body + decls + [text] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(records)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path():
    """the model's own outcomes: bullets hit and missed (a miss by the reach bucket, a miss by the sight), the
    sight from the seen flag and from the near trace, claws and bites in reach with and without sight, out of reach,
    imps' fireballs both ways (out of reach, out of sight), kills, and hits on a dead player"""
    w = _world()
    slots = _slots(w)
    fire = _Fire()
    seen = dict(bhit=0, bmiss_reach=0, bmiss_sight=0, trace=0, claw=0, bite=0, claw_nosight=0, out=0,
                fire_far=0, fire_blind=0, kill=0, deadhit=0)
    for rec in _records(w):
        tp, (mx, my), (px16, py16), mrng, sn, hit, pokes = rec
        d = aprox_distance((_signed32(px16) >> 16) - mx, (_signed32(py16) >> 16) - my)
        ev = TicEvents(0)
        n0 = fire.n
        _apply(w, slots, rec, fire, ev)
        alive = pokes["p_health"] > 0 and not pokes["p_dead"]
        sight = bool(sn) or (d <= NEAR and not hit)
        if tp in (3004, 9):
            assert len(ev.mon_shots) == BULLETS[ACTION[tp]]
            for _m, _s, _dmg, h in ev.mon_shots:
                seen["bhit"] += h
                seen["bmiss_reach"] += (not h) and alive and sight
                seen["bmiss_sight"] += (not h) and alive and not sight
            seen["trace"] += (not sn) and d <= NEAR
            seen["deadhit"] += (not alive) and sight and d < 2048
        else:
            near = d < MELEE_REACH
            if near and sight:
                seen["claw" if tp == 3001 else "bite"] += 1
                assert len(ev.mon_melee) == 1
            elif near:
                seen["claw_nosight"] += 1
            else:
                seen["out"] += 1
            if tp == 3001 and fire.n > n0:
                seen["fire_far" if not near else "fire_blind"] += 1
        seen["kill"] += ev.deaths
    want = dict(bhit=30, bmiss_reach=30, bmiss_sight=20, trace=10, claw=5, bite=5, claw_nosight=5, out=30,
                fire_far=10, fire_blind=2, kill=3, deadhit=3)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)


def test_the_attacks_follow_the_model(tmp_path):
    assert _run(tmp_path, "mattack"), "the fj attack parted from the model's _monster_attack"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_attack_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mattack_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
