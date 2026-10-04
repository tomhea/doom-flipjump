"""M7 P4.2a (docs/gp-combat.md): the monsters' DAMAGE on the real flipjump engine -- `damagecode`'s dm_go / dm_leaf,
the very text the emitter splices, against the model's own `_line_attack` -> `damage_monster` / `_kill_monster`
(World(player="shoot") when the model has that mode, else "full": the two differ inside damage only in the drop,
which fj does not hold).

Each record pokes ONE slot's cells identically on both sides -- health (around 0 and the hit's damage, so a hit
leaves exactly 0), shootable, state (the spawn state, its second frame, the see state, the pain state, others),
tics, the P_Random state, threshold (0 or not), reaction, target, justhit, its position -- and the player's
position at, just inside and just outside the reach (melee 64 / 65, bullets 2048), then shoots it. After every
record the slot's cells and its neighbour's are printed (the neighbour catches a stub that writes the wrong slot).
A few records name no slot (dm_id 0).

R9: no pain draw, `< 0` instead of `<= 0` for the death, the threshold reset when it is not 0, the see switch from a
state other than the spawn state, `>=` for the reach, and the death without its tics roll must each part.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj.combat import MISSILERANGE_U, PUNCH_REACH, SAW_REACH
from doomfj.config import Config
from doomfj.harness import W
from doomfj.world import PLAYER_MODES, TicEvents, World, aprox_distance

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 320
M32 = 0xFFFFFFFF
PLAYER = "shoot" if "shoot" in PLAYER_MODES else "full"
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
                         rnd.randint(1, info.spawnhealth), info.spawnhealth))
        st = rnd.choice((info.spawnstate, info.spawnstate, gd.STATES[info.spawnstate].next, info.seestate,
                         info.painstate, gd.STATES[info.seestate].next, info.missilestate if info.missilestate !=
                         gd.S_NULL else info.meleestate))
        pokes = {"mon_health": hp, "mon_shootable": int(rnd.random() < 0.9), "mon_state": gd.STATE_INDEX[st],
                 "mon_tics": rnd.randint(1, 14), "mon_rng": rnd.randrange(256),
                 "mon_threshold": rnd.choice((0, 0, 0, 1, rnd.randint(1, gd.BASETHRESHOLD))),
                 "mon_reaction": rnd.randrange(16), "mon_target": rnd.randrange(2), "mon_justhit": rnd.randrange(2)}
        melee = int(rnd.random() < 0.5)
        reach = rnd.choice((PUNCH_REACH, SAW_REACH)) if melee else 0
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
        px16 = ((x + dx) << 16) | rnd.randrange(1 << 16)
        py16 = ((y + dy) << 16) | rnd.choice((0, rnd.randrange(1 << 16)))
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
}


def _program(w, mut=None):
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    dp = DC.damage_parts(w, slot_rt=list(range(n)), boot_skill=ws.skill)
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS}
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": 0}, n)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, [0] * n)
             + MC.P32A_SCRATCH + dp["decls"]
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
                unshootable=0, dead=0, none=0)
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
        else:
            seen["at"] += d == lim
            if ev.kills:
                seen["kill"] += 1
                seen["kill0"] += hp == dmg
            else:
                seen["pain" if ws.mon_justhit[m] and not pokes["mon_justhit"] or ws.mon_state[m] ==
                     gd.STATE_INDEX[w.mon_info[m].painstate] and pokes["mon_state"] != ws.mon_state[m]
                     else "nopain"] += 1
                if pokes["mon_threshold"] == 0:
                    if pokes["mon_state"] == gd.STATE_INDEX[w.mon_info[m].spawnstate] and ws.mon_state[m] == \
                            gd.STATE_INDEX[w.mon_info[m].seestate]:
                        seen["wake"] += 1
                    elif pokes["mon_state"] != gd.STATE_INDEX[w.mon_info[m].spawnstate]:
                        seen["thr0_other"] += 1
                else:
                    seen["thr_kept"] += 1
            assert live and ws.mon_rng[m] == (before_rng + 1) & 0xFF, "a hit draws once"
    want = dict(kill=10, kill0=2, pain=10, nopain=5, wake=3, thr0_other=3, thr_kept=10, miss=10, miss1=3, at=10,
                unshootable=5, dead=5, none=3)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)


def test_the_damage_follows_the_model(tmp_path):
    assert _run(tmp_path, "mdamage"), "the fj damage parted from the model's damage_monster"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_damage_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mdamage_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
