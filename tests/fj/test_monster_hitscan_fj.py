"""M7 P8a I (docs/gp-final-plan.md 1.2.2 / 1.2.3, O-B5): a monster's attacks AT ITS TARGET on the real engine --
monsterdecide's `mt_load` then `md_attack` in its fight emission (`attack_leaf_lines(full=True, fight=True)`: the
target's distance, facing, reach and attack sight; the bullets' scan of the things in the way, `hs_scan` / `hs_cand` /
`hs_wid` on the `mbsd` and `hwtr` tables and the shared angle leaf `ia_leaf`; the claw and the bite on a monster
target through dm_go; the fireball aimed at the target) -- driven with poked registers against the model's own
`_monster_attack` (World(monsters="final", player="final")): `_mon_hitscan` with `_bullet_victim`, `_mon_melee`.

Each record names an attacker (a zombieman, a shotgun guy, an imp, a demon) at a random spot, its TARGET (the player,
alive or dead, or another monster slot, alive or dead) at every range, and a CROWD in the line of fire -- monster slots
near the shooter -> target line (some beyond the target, some dead), the player in the line (when he is not the
target), and the BARRELS of the map in every state when the shot passes one (barrels never move: the record places
the shooter beside one). The traces are pokes: `sl_los` and `sl_far` are stubs returning the record's sl_hit (the
model's `los_to_player` / `los_to_target` return its negation). The damage leaves are stubs that print each call --
dp_go its damage and source, dm_go its id, damage, mode and source -- as the model's damage_player / damage_monster /
damage_barrel are replaced by recorders printing the same; `pj_spawn` prints the shooter and the target it aims at.
After every record: the monster's stream and facing.

R9 (each must part from the model): a bullet that passes through everything (the scan returns at once); the shooter
in its own way; every thing as wide as the player (the radius class ignored); the first thing met instead of the
nearest; the offset's sign reversed; a monster target's attack sight ignored (the far LOS never consulted); a monster
target's melee reach the player's; the scan box's low x bound left unbiased."""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import hurtcode as H
from doomfj import monstercode as MC
from doomfj import monsterdecide as MD
from doomfj.combat import PLAYER_R
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj
from doomfj.reference_model import SLOPERANGE
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.world import MELEE_BASE, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 320
M32 = 0xFFFFFFFF
ACTION = {3004: "A_PosAttack", 9: "A_SPosAttack", 3001: "A_TroopAttack", 3002: "A_SargAttack"}


def _world():
    return World(skill=gd.SK_HARD, monsters="final", player="final", sight_rule="seen")


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _shooters(w):
    out = {}
    for m, t in enumerate(w.mon_things):
        if t.type in ACTION and t.type not in out and w.ws.mon_active[m]:
            out[t.type] = m
    return out


def _records(w):
    """[dict]: the attacker, its spot, its stream, the target, the crowd, the player, the barrels, the pokes"""
    rnd = random.Random(0x8AB)
    n = w.layout.nmon
    sh = _shooters(w)
    types = sorted(ACTION)
    out = []
    for r in range(N):
        tp = types[r % 4] if r % 3 else rnd.choice((3004, 9))        # bullets twice as often
        m = sh[tp]
        others = [j for j in range(n) if j != m]
        if rnd.random() < 0.3:                                        # beside a barrel, shooting past it
            bt = w.barrel_things[rnd.randrange(len(w.barrel_things))]
            ang = rnd.random() * 6.283
            back = rnd.randint(20, 120)
            import math
            ux, uy = math.cos(ang), math.sin(ang)
            mx, my = int(bt.x - ux * back), int(bt.y - uy * back)
        else:
            mx, my = rnd.randint(-600, 3000), rnd.randint(-1000, 2200)
            import math
            ang = rnd.random() * 6.283
            ux, uy = math.cos(ang), math.sin(ang)
        d = rnd.choice((rnd.randint(20, 80), rnd.randint(40, 300), rnd.randint(200, 900), rnd.randint(800, 2100),
                        MELEE_BASE + 20, MELEE_BASE + 30, MELEE_BASE + 29, MELEE_BASE + 19, 2047, 2048))
        if tp in (3001, 3002) and rnd.random() < 0.5:                 # the claw's and the bite's reach
            d = rnd.choice((rnd.randint(10, 56), rnd.randint(56, 78)))   # the player's reach .. a demon's
            if rnd.random() < 0.5:                                    # on an axis: P_AproxDistance is d exactly
                ux, uy = rnd.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        tx, ty = int(mx + ux * d), int(my + uy * d)
        player_target = rnd.random() < 0.45
        tj = None if player_target else rnd.choice(others)
        crowd = {}
        pool = [j for j in others if j != tj]
        rnd.shuffle(pool)
        for j in pool[:rnd.choice((0, 1, 2, 3, 5, 8))]:
            t = rnd.uniform(-0.1, 1.2)
            off = rnd.choice((0, rnd.randint(-12, 12), rnd.randint(-45, 45)))
            crowd[j] = (int(mx + ux * d * t - uy * off), int(my + uy * d * t + ux * off),
                        int(rnd.random() < 0.85))
        if player_target:
            px16 = ((tx << 16) | rnd.randrange(1 << 16)) & M32
            py16 = ((ty << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
            pdead = int(rnd.random() < 0.15)
        else:
            if rnd.random() < 0.3:                                    # the player in the line of fire
                t = rnd.uniform(0.05, 1.1)
                off = rnd.randint(-30, 30)
                px, py = mx + ux * d * t - uy * off, my + uy * d * t + ux * off
            else:
                px, py = rnd.randint(-600, 3000), rnd.randint(-1000, 2200)
            px16 = ((int(px) << 16) | rnd.randrange(1 << 16)) & M32
            py16 = ((int(py) << 16) | rnd.randrange(1 << 16)) & M32
            pdead = int(rnd.random() < 0.2)
        bars = []
        for b in range(len(w.barrel_things)):
            st = rnd.choice(("stand", "stand", "stand", "gone", "boom"))
            bars.append({"stand": (gd.STATE_INDEX["S_BAR1"], rnd.randint(1, 20)), "gone": (0, 0),
                         "boom": (gd.STATE_INDEX["S_BEXP"], rnd.choice((0, -5)))}[st])
        out.append(dict(tp=tp, m=m, mx=mx, my=my, rng=rnd.randrange(256), target=1 if player_target else 2 + tj,
                        tpos=(tx, ty), talive=int(rnd.random() < 0.85), crowd=crowd, px16=px16, py16=py16,
                        pdead=pdead, seen=int(rnd.random() < 0.5), hit=int(rnd.random() < 0.3), bars=bars))
    # the claw's and the bite's reach on a MONSTER target, on an axis between the player's 60 and a demon's 74
    for r in range(40):
        tp = (3001, 3002)[r % 2]
        m = sh[tp]
        tj = rnd.choice([j for j in range(n) if j != m])
        mx, my = rnd.randint(-600, 3000), rnd.randint(-1000, 2200)
        ux, uy = rnd.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        d = rnd.randint(58, 75)
        out.append(dict(tp=tp, m=m, mx=mx, my=my, rng=rnd.randrange(256), target=2 + tj, tpos=(mx + ux * d, my + uy * d),
                        talive=1, crowd={}, px16=0, py16=0, pdead=1, seen=0, hit=0, bars=[(0, 0)] * len(w.barrel_things)))
    return out


def _apply(w, rec, log):
    """the record on the model: the cells, then `_monster_attack` with the damage and the spawn recorded"""
    ws, n = w.ws, w.layout.nmon
    m = rec["m"]
    for j in range(n):
        ws.mon_active[j], ws.mon_shootable[j], ws.mon_health[j] = 1, 0, 0
        ws.mon_x[j], ws.mon_y[j] = -20000, -20000
    ws.mon_x[m], ws.mon_y[m] = rec["mx"], rec["my"]
    ws.mon_shootable[m], ws.mon_health[m] = 1, 50
    for j, (x, y, alive) in rec["crowd"].items():
        ws.mon_x[j], ws.mon_y[j] = x, y
        ws.mon_shootable[j], ws.mon_health[j] = alive, 50 if alive else 0
    ws.mon_target[m] = rec["target"]
    if rec["target"] >= 2:
        j = rec["target"] - 2
        ws.mon_x[j], ws.mon_y[j] = rec["tpos"]
        ws.mon_shootable[j], ws.mon_health[j] = rec["talive"], 50 if rec["talive"] else 0
    ws.px, ws.py = _s32(rec["px16"]), _s32(rec["py16"])
    ws.p_dead, ws.p_health = rec["pdead"], 0 if rec["pdead"] else 100
    for b, (st, hp) in enumerate(rec["bars"]):
        ws.bar_state[b], ws.bar_health[b] = st, hp
    ws.mon_rng[m], ws.mon_seen[m] = rec["rng"], rec["seen"]
    hit = rec["hit"]
    w.los_to_player = lambda world, mm, _h=hit: not _h
    w.los_to_target = lambda world, mm, _h=hit: not _h
    mode = {"v": 3}

    def dp(dmg, source, inflictor, ev):
        log.append("P%02x%02x" % (dmg, source[1] + 1))

    def dmon(j, dmg, source, inflictor, ev):
        log.append("M%02x%02x%x%02x" % (1 + j, dmg, mode["v"], 2 + source[1]))

    def dbar(b, dmg, source, ev):
        log.append("M%02x%02x%x%02x" % (1 + n + b, dmg, 4, 2 + source[1]))

    def spawn(mm, ev):
        tx16, ty16 = w._target_pos16(mm)
        log.append("F%04x%04x%08x%08x" % (ws.mon_x[mm] & 0xFFFF, ws.mon_y[mm] & 0xFFFF, tx16 & M32, ty16 & M32))
    w.damage_player, w.damage_monster, w.damage_barrel, w._spawn_fireball = dp, dmon, dbar, spawn
    w._spawn_fx_at_target = lambda *a: None
    base = type(w)._mon_hitscan

    def hitscan(mm, bullets, ev):
        mode["v"] = 4
        try:
            base(w, mm, bullets, ev)
        finally:
            mode["v"] = 3
    w._mon_hitscan = hitscan
    ev = TicEvents(0)
    w._monster_attack(m, ACTION[rec["tp"]], ev)
    return ev


def _expected(w, records) -> bytes:
    lines = []
    for rec in records:
        log = []
        _apply(w, rec, log)
        ws = w.ws
        lines += log + ["%02x%x" % (ws.mon_rng[rec["m"]], ws.mon_facing[rec["m"]])]
    return ("\n".join(lines) + "\n").encode()


MUTANTS = {
    "pass_through": ("hs_scan:\n    hex.zero 2, hs_vic\n", "hs_scan:\n    hex.zero 2, hs_vic\n    stl.fret hs_ret\n"),
    "hits_shooter": ("    hex.cmp 2, hs_id, md_me, hsc_d, hsc_out, hsc_d\n", ""),
    "nearest": ("    hex.mov 4, hs_bd, mt_d", "    hex.mov 4, hs_d, mt_d"),
    "delta_sign": ("    hex.mov 8, hs_t8, ia_ang\n    hex.sub 8, hs_t8, md_at\n",
                   "    hex.mov 8, hs_t8, md_at\n    hex.sub 8, hs_t8, ia_ang\n"),
    "los_ignored": ("    stl.fcall sl_far, sf_ret\n    hex.if0 1, sl_hit, mm_as_out\n", "    ;mm_as_out\n"),
    "reach_player": ("    hex.cmp 4, mt_d, mt_reach, md_claw_r, md_claw_f, md_claw_f\n",
                     "    hex.cmp 4, mt_d, mt_c60, md_claw_r, md_claw_f, md_claw_f\n"),
    "radius": None,                                          # the table: every class the player's
    # the scan's box's low x bound left unbiased: a signed position compared unsigned
    "box_sign": ("    hex.xor_by hs_xlo + 3*dw, 8", "    hex.zero 1, hs_in"),
}


def _program(w, mut=None):
    n = w.layout.nmon
    tables = H.tables_fj(w.hwt) + MD.fight_tables_fj(w.rm.sine)
    if mut == "radius":
        vals = MD.hwtr_values(w.rm.sine)
        vals = [vals[(MD.RC[PLAYER_R] << 8) | (i & 0xFF)] for i in range(len(vals))]
        tables = [t for t in tables if "ns hwtr {" not in t] + [
            generate_dispatch_table_fj("hwtr", vals, index_nibbles=3, result_nibbles=2)]
    tables += [generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
               generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
               generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    fp = MD.fight_parts(w, list(range(n)))
    text = "\n".join(MD.todist_leaf_lines(True) + MD.octant_leaf_lines() + MD.as_leaf_lines(True)
                     + MD.attack_leaf_lines(full=True, fight=True) + fp["lines"] + MC.dist_leaf_lines()) + "\n"
    if mut and MUTANTS[mut]:
        old, new = MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    stubs = ["sl_los:", "    stl.fret sl_ret", "sl_far:", "    stl.fret sf_ret",
             "dp_go:", "    stl.output 80", "    hex.print_as_digit 2, dp_dmg, 0", "    hex.print_as_digit 2, dp_src, 0",
             "    stl.output 10", "    hex.zero 2, dp_src", "    stl.fret dp_ret",
             "dm_go:", "    stl.output 77", "    hex.print_as_digit 2, dm_id, 0", "    hex.print_as_digit 2, dm_dmg, 0",
             "    hex.print_as_digit 1, dm_melee, 0", "    hex.print_as_digit 2, dm_src, 0", "    stl.output 10",
             "    hex.zero 2, dm_src", "    stl.fret dm_ret",
             "pj_spawn:", "    stl.output 70", "    hex.print_as_digit 4, mm_x, 0", "    hex.print_as_digit 4, mm_y, 0",
             "    hex.print_as_digit 8, mt_tqx, 0", "    hex.print_as_digit 8, mt_tqy, 0", "    stl.output 10",
             "    stl.fret pj_sret"]
    nbar = len(w.barrel_things)
    decls = (H.hurt_decls(H.level_start(w)) + MD.context_decls() + MC.P32A_SCRATCH + fp["decls"]
             + ["mm_x: hex.vec 4", "mm_y: hex.vec 4", "mm_rng: hex.vec 2",
                "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
                "mt_t: hex.vec 4", "viewx: hex.vec 8", "viewy: hex.vec 8",
                "sl_hit: hex.vec 1", "sl_ret: hex.vec w/4", "sf_ret: hex.vec w/4", "pj_sret: hex.vec w/4",
                "dm_id: hex.vec 2", "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2",
                "dm_ret: hex.vec w/4",
                "mon_shootable: hex.vec %d" % n, "mon_solid: hex.vec %d" % n, "thpos_rt: hex.vec %d" % (16 * n),
                "bar_solid: hex.vec %d" % nbar,
                "bar_st: hex.vec %d" % (2 * nbar), "bar_hp: hex.vec %d" % (2 * nbar)])
    return decls, text + "\n".join(stubs) + "\n", tables


def _build(tmp_path, name, mut=None):
    w = _world()
    records = _records(w)
    want = _expected(w, records)
    n = w.layout.nmon
    kinds = MD.ATTACK_KINDS
    body = ["stl.startup_and_init_all"]
    for rec in records:
        m = rec["m"]
        body += ["hex.zero %d, mon_shootable" % n, "hex.zero %d, thpos_rt" % (16 * n)]
        rows = {m: (rec["mx"], rec["my"], 1)}
        rows.update(rec["crowd"])
        if rec["target"] >= 2:
            rows[rec["target"] - 2] = rec["tpos"] + (rec["talive"],)
        for j, (x, y, alive) in sorted(rows.items()):           # the others: row 0, not shootable (none reads them)
            body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 4, x & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 12, y & 0xFFFF)]
            if alive:
                body += ["hex.set 1, mon_shootable + %d*dw, 1" % j]
        nb = len(rec["bars"])
        body += ["hex.set %d, bar_st, %d" % (2 * nb, sum(st << (8 * b) for b, (st, _hp) in enumerate(rec["bars"]))),
                 "hex.set %d, bar_hp, %d" % (2 * nb, sum((hp & 0xFF) << (8 * b) for b, (_st, hp) in
                                                         enumerate(rec["bars"])))]
        body += ["hex.set 8, viewx, %d" % rec["px16"], "hex.set 8, viewy, %d" % rec["py16"],
                 "hex.set 1, p_dead, %d" % rec["pdead"], "hex.set 3, p_hp, %d" % (0 if rec["pdead"] else 100),
                 "hex.set 4, mm_x, %d" % (rec["mx"] & 0xFFFF), "hex.set 4, mm_y, %d" % (rec["my"] & 0xFFFF),
                 "hex.set 2, mm_rng, %d" % rec["rng"], "hex.set 1, mm_seen, %d" % rec["seen"],
                 "hex.set 1, sl_hit, %d" % rec["hit"], "hex.set 1, mm_kind, %d" % kinds[ACTION[rec["tp"]]],
                 "hex.set 2, md_src, %d" % (m + 1), "hex.set 2, mm_tg, %d" % rec["target"],
                 "stl.fcall mt_load, mt_lret", "stl.fcall md_attack, md_ret",
                 "hex.print_as_digit 2, mm_rng, 0", "hex.print_as_digit 1, mm_fa, 0", "stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = _program(w, mut)
    from doomfj.wall_renderer import hoisted_scratch_fj
    prog = "\n".join(body + decls + [text] + tables) + "\n" + hoisted_scratch_fj()
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, want


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path():
    """the model's own outcomes over the records: bullets on the target (the player, a monster), on a monster in
    the way, on a barrel in the way, on the player in the way, missed; claws and bites on a monster target; fireballs
    at a monster target; a dead target's bullets missed"""
    w = _world()
    seen = dict(t_player=0, t_mon=0, way_mon=0, way_bar=0, way_player=0, miss=0, claw_mon=0, bite_mon=0,
                fire_mon=0, dead_target=0, near_not_nearest=0)
    for rec in _records(w):
        log = []
        ev = _apply(w, rec, log)
        n = w.layout.nmon
        tg = rec["target"]
        for ln in log:
            if ln[0] == "P":
                seen["t_player" if tg == 1 else "way_player"] += 1
            elif ln[0] == "M":
                i, mode = int(ln[1:3], 16), int(ln[5], 16)
                if mode == 3:
                    seen["claw_mon" if rec["tp"] == 3001 else "bite_mon"] += 1
                elif i > n:
                    seen["way_bar"] += 1
                elif i == tg - 1:
                    seen["t_mon"] += 1
                else:
                    seen["way_mon"] += 1
            elif ln[0] == "F" and tg >= 2:
                seen["fire_mon"] += 1
        seen["miss"] += sum(1 for s in ev.mon_shots if not s[3])
        seen["dead_target"] += bool(ev.mon_shots) and tg >= 2 and not rec["talive"]
        seen["near_not_nearest"] += len([1 for j in rec["crowd"] if rec["crowd"][j][2]]) >= 2
    want = dict(t_player=20, t_mon=20, way_mon=20, way_bar=5, way_player=3, miss=60, claw_mon=3, bite_mon=3,
                fire_mon=10, dead_target=5, near_not_nearest=40)
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_attacks_at_the_target_follow_the_model(tmp_path):
    assert _run(tmp_path, "mhitscan"), "the fj attacks at the target parted from the model's _monster_attack"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_attack_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mhitscan_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
