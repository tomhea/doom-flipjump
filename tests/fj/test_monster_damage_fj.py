"""M7 P4.2a (docs/gp-combat.md): the monsters' DAMAGE on the real flipjump engine -- `damagecode`'s dm_go / dm_leaf,
the very text the emitter splices, against the model's own `_line_attack` -> `damage_monster` / `_kill_monster` in
the player mode "shoot" (World(player="shoot"): no drop, no effect, no barrel).

Each record pokes ONE slot's cells identically on both sides -- health (around 0 and the hit's damage, so a hit
leaves exactly 0), shootable, state (the spawn state, its second frame, the see state, the pain state, others),
tics, the P_Random state, threshold (0 or not), reaction, target, justhit, its position -- and the player's
position at, just inside and just outside the reach (melee 64 / 65, bullets 2048), then shoots it. After every
record the slot's cells and its neighbour's are printed (the neighbour catches a stub that writes the wrong slot).
A few records name no slot (dm_id 0).

R9: no pain draw, `< 0` instead of `<= 0` for the death, the threshold reset when it is not 0, the see switch from a
state other than the spawn state, `>=` for the reach, the death without its tics roll, bullets without their 2048
reach (the aim window's tz alone), and bullets reading the caller's stale `dm_reach` must each part.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import rng as R
from doomfj.combat import MISSILERANGE_U, PUNCH_REACH, SAW_REACH
from doomfj.config import Config
from doomfj.harness import W
from doomfj.weaponcode import DM_CELLS
from doomfj.world import TicEvents, World, aprox_distance

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 320
M32 = 0xFFFFFFFF
PLAYER = "shoot"
CELLS = (("mon_health", 3), ("mon_shootable", 1), ("mon_state", 2), ("mon_tics", 1), ("mon_rng", 2),
         ("mon_threshold", 2), ("mon_reaction", 1), ("mon_target", 1), ("mon_justhit", 1), ("mon_solid", 1))


def _world():
    return World(monsters="decide", sight_rule="seen", player=PLAYER)


def _records(w):
    """[(slot or None, pokes {field: value}, (x, y), (px16, py16), dmg, melee, reach)]"""
    rnd = random.Random(0x42A)
    n = w.layout.nmon
    act = [m for m in range(n) if w.ws.mon_active[m]]
    out = []
    for r in range(N):
        if r % 40 == 39:
            out.append((None, {}, (0, 0), (rnd.randrange(1 << 31), rnd.randrange(1 << 31)), 5, 0, 0))
            continue
        m = rnd.choice(act) if rnd.random() < 0.95 else rnd.randrange(n)
        info = w.mon_info[m]
        dmg = rnd.randint(1, DC.DM_MAX)
        hp = rnd.choice((dmg, dmg, dmg - 1, dmg + 1, 1, 0, -2, rnd.randint(1, info.spawnhealth),
                         rnd.randint(1, info.spawnhealth), info.spawnhealth, info.spawnhealth, dmg + 7))
        st = rnd.choice((info.spawnstate, info.spawnstate, info.spawnstate, info.spawnstate,
                         gd.STATES[info.spawnstate].next, info.seestate,
                         info.painstate, gd.STATES[info.seestate].next, info.missilestate if info.missilestate !=
                         gd.S_NULL else info.meleestate))
        pokes = {"mon_health": hp, "mon_shootable": int(rnd.random() < 0.9), "mon_state": gd.STATE_INDEX[st],
                 "mon_tics": rnd.randint(1, 14), "mon_rng": rnd.randrange(256),
                 "mon_threshold": rnd.choice((0, 0, 0, 1, rnd.randint(1, gd.BASETHRESHOLD))),
                 "mon_reaction": rnd.randrange(16), "mon_target": rnd.randrange(2), "mon_justhit": rnd.randrange(2)}
        melee = int(rnd.random() < 0.5)
        reach = rnd.choice((PUNCH_REACH, SAW_REACH)) if melee else rnd.randrange(256)   # stale for bullets: unread
        lim = reach if melee else MISSILERANGE_U
        x, y = rnd.randint(-1500, 3000), rnd.randint(-3000, 1500)
        d = rnd.choice((lim, lim, lim - 1, lim + 1, rnd.randint(0, lim)))
        # a point at P_AproxDistance d: on an axis, or a diagonal walked until the distance is reached
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
        px16 = (((x + dx) << 16) | rnd.randrange(1 << 16)) & M32
        py16 = (((y + dy) << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        out.append((m, pokes, (x, y), (px16, py16), dmg, melee, reach))
    return out


def _apply(w, rec, ev):
    """the model's shot: the cells poked, then `_line_attack` with the aim naming the slot (the reach test is the
    model's own)"""
    m, pokes, (x, y), (px16, py16), dmg, melee, reach = rec
    ws = w.ws
    ws.px = px16 - (1 << 32) if px16 >> 31 else px16
    ws.py = py16 - (1 << 32) if py16 >> 31 else py16
    if m is None:
        return
    for f, v in pokes.items():
        getattr(ws, f)[m] = v
    ws.mon_x[m], ws.mon_y[m] = x, y
    w.aim = lambda world, col, _m=m: ("mon", _m)
    w._line_attack("fist" if melee else "pistol", w.aim_centre, dmg, reach if melee else MISSILERANGE_U, ev)


def _row(w, m) -> str:
    ws, n = w.ws, w.layout.nmon
    return "".join("".join("%0*x" % (nib, getattr(ws, f)[s] & (16 ** nib - 1)) for f, nib in CELLS)
                   for s in (m, (m + 1) % n))


def _expected(records) -> bytes:
    w = _world()
    lines = []
    for rec in records:
        _apply(w, rec, TicEvents(0))
        lines.append(_row(w, rec[0] if rec[0] is not None else 0))
    return ("\n".join(lines) + "\n").encode()


MUTANTS = {
    "nodraw": ("    hex.inc 2, dm_rng\n", ""),                                       # no pain (or tics) draw
    "lt0": ("    hex.if0 3, dm_hp, dm_kill\n", ""),                                  # `< 0` for the death
    "thrnz": ("    hex.if1 2, dm_th, dm_out\n", ""),                                 # threshold reset when not 0
    "seeany": ("    hex.cmp 2, dm_st, dm_sp, dm_out, dm_see, dm_out\n", "    ;dm_see\n"),   # see from any state
    "reachge": ("    hex.cmp 4, mt_d, dm_r4, dm_in, dm_in, dm_out\n",
                "    hex.cmp 4, mt_d, dm_r4, dm_in, dm_out, dm_out\n"),             # `>=` for the reach
    "notics": ("    hex.sub 1, dm_ti, dm_rr\n", ""),                                 # the death's tics roll unapplied
    "nobulletreach": ("    hex.set 4, dm_r4, %d\n" % MISSILERANGE_U, "    hex.set 4, dm_r4, 65535\n"),   # tz only
    "stalereach": ("    hex.if0 1, dm_melee, dm_far\n", ""),                         # bullets read the stale dm_reach
}


def _program(w, mut=None):
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    dp = DC.damage_parts(w, slot_rt=list(range(n)), boot_skill=ws.skill)
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS}
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": 0}, n)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, [0] * n)
             + MC.P32A_SCRATCH + dp["decls"]
             + ["%s: hex.vec %d" % cn for cn in DM_CELLS]                 # the caller's (weaponcode.shot_decls)
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "thpos_rt: hex.vec %d" % (16 * n)])
    text = "\n".join(MC.dist_leaf_lines() + dp["lines"] + dp["tables"]) + "\n"
    if mut:
        old, new = MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    return decls, text


def _build(tmp_path, name, mut=None):
    w = _world()
    n = w.layout.nmon
    records = _records(w)
    body = ["stl.startup_and_init_all"]
    nib = {f: MC.cell_nibbles(w.schema, f) for f, _ in CELLS}
    assert all(nib[f] == k for f, k in CELLS), nib
    for m, pokes, (x, y), (px16, py16), dmg, melee, reach in records:
        body += ["hex.set 8, viewx, %d" % (px16 & M32), "hex.set 8, viewy, %d" % (py16 & M32)]
        if m is None:
            body += ["hex.zero 2, dm_id"]
        else:
            body += ["hex.set %d, %s + %d*dw, %d" % (nib[f], f, nib[f] * m, v & (16 ** nib[f] - 1))
                     for f, v in pokes.items()]
            body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 4, x & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 12, y & 0xFFFF),
                     "hex.set 2, dm_id, %d" % (m + 1)]
        body += ["hex.set 2, dm_dmg, %d" % dmg, "hex.set 1, dm_melee, %d" % melee, "hex.set 2, dm_reach, %d" % reach,
                 "stl.fcall dm_go, dm_ret"]
        mm = m if m is not None else 0
        for s in (mm, (mm + 1) % n):
            body += ["hex.print_as_digit %d, %s + %d*dw, 0" % (k, f, k * s) for f, k in CELLS]
        body += ["stl.output 10"]
    body += ["stl.loop"]
    decls, text = _program(w, mut)
    prog = "\n".join(body + decls + [text]) + "\n"
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
    """the model's own outcomes over the records: kills (one leaving exactly 0 health), pains and hurts without
    pain, a wake from the spawn state and a threshold-0 hit from another state, a nonzero threshold kept, misses by
    the reach (one a hair past it) and hits AT it, non-shootable and dead targets -- each control needs its path"""
    w = _world()
    ws = w.ws
    seen = dict(kill=0, kill0=0, pain=0, nopain=0, wake=0, thr0_other=0, thr_kept=0, miss=0, miss1=0, at=0,
                unshootable=0, dead=0, none=0, bmiss=0, bhit=0)
    for rec in _records(w):
        m, pokes, (x, y), (px16, py16), dmg, melee, reach = rec
        if m is None:
            seen["none"] += 1
            _apply(w, rec, TicEvents(0))
            continue
        lim = reach if melee else MISSILERANGE_U
        d = aprox_distance(x - ((px16 - (1 << 32) if px16 >> 31 else px16) >> 16),
                           y - ((py16 - (1 << 32) if py16 >> 31 else py16) >> 16))
        hp, live = pokes["mon_health"], pokes["mon_shootable"] and pokes["mon_health"] > 0
        before_rng = pokes["mon_rng"]
        ev = TicEvents(0)
        _apply(w, rec, ev)
        if not pokes["mon_shootable"]:
            seen["unshootable"] += 1
        elif hp <= 0:
            seen["dead"] += 1
        elif d > lim:
            seen["miss"] += 1
            seen["miss1"] += d == lim + 1
            seen["bmiss"] += not melee
        else:
            seen["at"] += d == lim
            seen["bhit"] += not melee
            if ev.kills:
                seen["kill"] += 1
                seen["kill0"] += hp == dmg
            else:
                pain = R.p_random(before_rng)[0] < w.mon_info[m].painchance
                seen["pain" if pain else "nopain"] += 1
                spawn = pokes["mon_state"] == gd.STATE_INDEX[w.mon_info[m].spawnstate]
                if pokes["mon_threshold"]:
                    seen["thr_kept"] += 1
                elif spawn and not pain:
                    seen["wake"] += 1
                    assert ws.mon_state[m] == gd.STATE_INDEX[w.mon_info[m].seestate]
                elif not spawn:
                    seen["thr0_other"] += 1
            assert live and ws.mon_rng[m] == (before_rng + 1) & 0xFF, "a hit draws once"
    want = dict(kill=10, kill0=2, pain=10, nopain=5, wake=3, thr0_other=3, thr_kept=10, miss=10, miss1=3, at=10,
                unshootable=5, dead=5, none=3, bmiss=3, bhit=10)
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_damage_follows_the_model(tmp_path):
    assert _run(tmp_path, "mdamage"), "the fj damage parted from the model's damage_monster"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_damage_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mdamage_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut


# ---- M7 P8a I (docs/gp-final-plan.md 1.2.2; damagecode `fight`): A MONSTER'S HITS -------------------------------------
# THE FIGHT'S RECORDS (World(monsters="final", player="final"); dm_leaf's full + fight emission): each record hits one
# slot in one of dm_melee's five modes -- the player's bullet or melee (0 / 1: the reach from the player, the blood, the
# switch to the player), a BLAST (2), a monster's claw / bite / fireball (MONSTER, 3: no reach, no blood) or a monster's
# bullet (BULLET, 4: no reach, the blood first) -- with `dm_src` none, the player, another slot or the hit slot ITSELF,
# on both sides: the model's damage_monster with the source the mode names (the blood recorded by
# `_spawn_fx_at_target`, the fj's fx_spawn a stub that prints it). The cells now include the TWO-nibble mon_target, and
# a source left in dm_src after the call prints "!" (dm_out zeroes it).
# R9: the switch to the source skipped; the threshold not consulted; the slot switching to itself; a monster's bullet
# without its blood; a monster's hit tested for the player's reach.
FIGHT_CELLS = (("mon_health", 3), ("mon_shootable", 1), ("mon_state", 2), ("mon_tics", 1), ("mon_rng", 2),
               ("mon_threshold", 2), ("mon_reaction", 1), ("mon_target", 2), ("mon_justhit", 1), ("mon_solid", 1))
NF = 300


def _fworld():
    w = World(monsters="final", player="final", sight_rule="seen")
    # M7 P8a K x I (the integration): this program is dm_leaf's FIGHT emission without the knock (damage_parts(
    # knock=False)), so the model's thrust is off too -- with K merged, "final" / "final" knocks, and the reversal's
    # coin draws on mon_rng (a FIGHT_CELL) whenever its conditions hold. The knock on dm_leaf's window is
    # test_knock_fj's; the knock with infighting's sources is test_barrel_fj's K x I section and test_knock_fight_model
    w._p_knock = False
    return w


def _frecords(w):
    """[(slot, pokes, (x, y), (px16, py16), dmg, mode, reach, src)]"""
    rnd = random.Random(0x8A1D)
    n = w.layout.nmon
    act = [m for m in range(n) if w.ws.mon_active[m]]
    out = []
    for r in range(NF):
        m = rnd.choice(act)
        info = w.mon_info[m]
        dmg = rnd.randint(1, 30)
        hp = rnd.choice((dmg, dmg + 1, 1, 0, rnd.randint(1, info.spawnhealth), info.spawnhealth, dmg + 9))
        st = rnd.choice((info.spawnstate, info.spawnstate, info.seestate, info.painstate))
        pokes = {"mon_health": hp, "mon_shootable": int(rnd.random() < 0.92), "mon_state": gd.STATE_INDEX[st],
                 "mon_tics": rnd.randint(1, 14), "mon_rng": rnd.randrange(256),
                 "mon_threshold": rnd.choice((0, 0, 0, 1, rnd.randint(1, gd.BASETHRESHOLD))),
                 "mon_reaction": rnd.randrange(16), "mon_target": rnd.choice((0, 1, 2 + rnd.randrange(n))),
                 "mon_justhit": rnd.randrange(2)}
        mode = rnd.choice((0, 1, 2, 3, 3, 4, 4))
        src = rnd.choice((0, 1, 2 + rnd.randrange(n), 2 + rnd.randrange(n), 2 + m))
        reach = rnd.choice((PUNCH_REACH, SAW_REACH)) if mode == 1 else rnd.randrange(256)
        x, y = rnd.randint(-1500, 3000), rnd.randint(-3000, 1500)
        lim = reach if mode == 1 else MISSILERANGE_U
        d = rnd.choice((lim, lim - 1, lim + 1, rnd.randint(0, lim), rnd.randint(0, 3000)))
        px16 = (((x + d) << 16) | rnd.randrange(1 << 16)) & M32
        py16 = ((y << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        out.append((m, pokes, (x, y), (px16, py16), dmg, mode, reach, src))
    return out


def _fsource(src):
    return None if not src else ("player", -1) if src == 1 else ("mon", src - 2)


def _fapply(w, rec, log):
    m, pokes, (x, y), (px16, py16), dmg, mode, reach, src = rec
    ws = w.ws
    ws.px = px16 - (1 << 32) if px16 >> 31 else px16
    ws.py = py16 - (1 << 32) if py16 >> 31 else py16
    for f, v in pokes.items():
        getattr(ws, f)[m] = v
    ws.mon_x[m], ws.mon_y[m] = x, y
    w._spawn_fx_at_target = lambda kind, fx, fy, fd, melee, ev: log.append(
        "B%04x%04x%02x" % (fx & 0xFFFF, fy & 0xFFFF, fd))
    ev = TicEvents(0)
    if mode in (0, 1):
        w.aim = lambda world, col, _m=m: ("mon", _m)
        w._line_attack("fist" if mode == 1 else "pistol", w.aim_centre, dmg, reach if mode == 1 else MISSILERANGE_U,
                       ev)
    elif mode == 4:
        w._spawn_fx_at_target("blood", x, y, dmg, False, ev)
        w.damage_monster(m, dmg, _fsource(src), ("mon", 0), ev)
    else:
        w.damage_monster(m, dmg, _fsource(src), ("bar", 0) if mode == 2 else ("mon", 0), ev)
    return ev


def _fexpected(records) -> bytes:
    w = _fworld()
    lines = []
    for rec in records:
        log = []
        _fapply(w, rec, log)
        lines += log + ["".join("%0*x" % (nib, getattr(w.ws, f)[rec[0]] & (16 ** nib - 1)) for f, nib in FIGHT_CELLS)]
    return ("\n".join(lines) + "\n").encode()


FIGHT_MUTANTS = {
    "no_switch": ("    hex.mov 2, dm_tg, dm_src\n", ""),
    "threshold_ignored": ("    hex.if1 2, dm_th, dm_out\n", ""),
    "self_switch": ("    hex.cmp 2, dm_src, dm_me, dm_swok, dm_out, dm_swok\n", ""),
    "bullet_noblood": ("    hex.if_flags dm_melee, %d, dm_nmb, dm_in\n" % (1 << DC.BULLET),
                       "    hex.if_flags dm_melee, %d, dm_nmb, dm_chk\n" % (1 << DC.BULLET)),
    "monster_reach": ("    hex.if_flags dm_melee, %d, dm_nbl, dm_chk\n" % ((1 << DC.BLAST) | (1 << DC.MONSTER)),
                      "    hex.if_flags dm_melee, %d, dm_nbl, dm_chk\n" % (1 << DC.BLAST)),
}


def _fbuild(tmp_path, name, mut=None):
    w = _fworld()
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    records = _frecords(w)
    want = _fexpected(records)
    dp = DC.damage_parts(w, slot_rt=list(range(n)), boot_skill=ws.skill, fx=True, full=True, fight=True)
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS}
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": 0}, n)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, [0] * n)
             + MC.P32A_SCRATCH + dp["decls"]
             + ["%s: hex.vec %d" % cn for cn in DM_CELLS]
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "thpos_rt: hex.vec %d" % (16 * n),
                "fxs_x: hex.vec 4", "fxs_y: hex.vec 4", "fxs_dmg: hex.vec 2", "fxs_kind: hex.vec 1",
                "fx_sret: hex.vec w/4"])
    text = "\n".join(MC.dist_leaf_lines() + dp["lines"] + dp["tables"]
                     + ["fx_spawn:", "    stl.output 66", "    hex.print_as_digit 4, fxs_x, 0",
                        "    hex.print_as_digit 4, fxs_y, 0", "    hex.print_as_digit 2, fxs_dmg, 0",
                        "    stl.output 10", "    stl.fret fx_sret"]) + "\n"
    if mut:
        old, new = FIGHT_MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    nib = {f: MC.cell_nibbles(schema, f) for f, _ in FIGHT_CELLS}
    assert all(nib[f] == k for f, k in FIGHT_CELLS), nib
    body = ["stl.startup_and_init_all"]
    for k, (m, pokes, (x, y), (px16, py16), dmg, mode, reach, src) in enumerate(records):
        body += ["hex.set 8, viewx, %d" % (px16 & M32), "hex.set 8, viewy, %d" % (py16 & M32)]
        body += ["hex.set %d, %s + %d*dw, %d" % (nib[f], f, nib[f] * m, v & (16 ** nib[f] - 1))
                 for f, v in pokes.items()]
        body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 4, x & 0xFFFF),
                 "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 12, y & 0xFFFF),
                 "hex.set 2, dm_id, %d" % (m + 1), "hex.set 2, dm_dmg, %d" % dmg, "hex.set 1, dm_melee, %d" % mode,
                 "hex.set 2, dm_reach, %d" % reach, "hex.set 2, dm_src, %d" % src, "stl.fcall dm_go, dm_ret",
                 "hex.if0 2, dm_src, rec_ok%d" % k, "stl.output 33", "rec_ok%d:" % k]
        body += ["hex.print_as_digit %d, %s + %d*dw, 0" % (kk, f, kk * m) for f, kk in FIGHT_CELLS]
        body += ["stl.output 10"]
    body += ["stl.loop"]
    prog = "\n".join(body + decls + [text]) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], want


def _frun(tmp_path, name, mut=None) -> bool:
    srcs, want = _fbuild(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_fight_records_exercise_every_path():
    """switches to a monster, refused by the threshold, by no source and by the source being the slot itself; a
    player's shot switching to the player; a monster's bullet bleeding; a monster's hit far beyond the player's reach"""
    w = _fworld()
    seen = dict(to_mon=0, thr_refused=0, nosrc=0, itself=0, to_player=0, bullet_blood=0, far_hit=0)
    for rec in _frecords(w):
        m, pokes, (x, y), (px16, py16), dmg, mode, reach, src = rec
        log = []
        before = pokes["mon_target"]
        _fapply(w, rec, log)
        if not (pokes["mon_shootable"] and pokes["mon_health"] > dmg):
            continue
        d = aprox_distance(x - ((px16 - (1 << 32) if px16 >> 31 else px16) >> 16),
                           y - ((py16 - (1 << 32) if py16 >> 31 else py16) >> 16))
        if mode >= 2:
            seen["far_hit"] += d > MISSILERANGE_U
            if pokes["mon_threshold"]:
                seen["thr_refused"] += src >= 2 and src != 2 + m
            elif not src:
                seen["nosrc"] += 1
            elif src == 2 + m:
                seen["itself"] += 1
            elif src >= 2:
                seen["to_mon"] += w.ws.mon_target[m] == src
            seen["bullet_blood"] += mode == 4 and bool(log)
        elif not pokes["mon_threshold"] and d <= (reach if mode == 1 else MISSILERANGE_U):
            seen["to_player"] += w.ws.mon_target[m] == 1 and before != 1
    want = dict(to_mon=10, thr_refused=5, nosrc=3, itself=3, to_player=5, bullet_blood=10, far_hit=5)
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_fight_damage_follows_the_model(tmp_path):
    assert _frun(tmp_path, "mdamage_fight"), "the fj damage parted from the model's damage_monster (fight)"


@pytest.mark.parametrize("mut", sorted(FIGHT_MUTANTS))
def test_control_a_broken_fight_damage_is_caught(tmp_path, mut):
    assert not _frun(tmp_path, "mdamage_fight_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
