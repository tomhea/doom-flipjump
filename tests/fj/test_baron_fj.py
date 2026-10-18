"""M8 C8 -- THE BARON OF HELL on the real flipjump engine, each piece the very text the emitter splices, against the
model on E1M8's own four Barons (the World leaves out the thing types other clusters build: 45, 46, 2046, 2004 --
nothing a Baron reads):

  * `mstate`'s Baron rows (monstercode.state_table_values over the map's types): every S_BOSS_* entry at its borrowed
    thing-domain index looked up in fj -- next, tics, action (A_BruisAttack 9, A_BossDeath 10), view group;
  * A_BossDeath (monstercode.boss_lines, a Baron slot's `<L>boss` block): random cells -- the player dead or alive,
    each other Baron absent, alive, dead at 0 or below 0, the tag-666 group untouched, moving or done -- against
    World._a_boss_death on the same cells;
  * A_BruisAttack (monsterdecide.attack_leaf_lines(full=True, bruiser=True), kind 5): the claw on `brclaw` within
    MELEE_REACH and the attack sight, else the missile (pj_spawn, a stub that counts) -- against the model's
    _monster_attack (the claw's stream draw, the player's health / armor / damagecount, the attacker);
  * the green fireball's pool (projcode.pj_lines(missile="MT_BRUISERSHOT")): the spawn at speed 15 (16v - v), S_BRBALL1
    with its tics roll, the flight, the impact (P_Random()%8+1)*8 and S_BRBALLX1 -- against _spawn_fireball /
    _projectiles_phase;
  * the thrust on a mass-1000 target (knockcode.thrust_lines(mass1k=True): kbm1k and hex.fixed_mul_lo) against
    combat._thrust's momentum.

R9: each comparison has controls that break the piece and must part from the model.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import hurtcode as H
from doomfj import monstercode as MC
from doomfj import monsterdecide as MD
from doomfj import projcode as PC
from doomfj import weaponcode as WC
from doomfj.collision import COLLISION_STATE_DECLS, point_location_decls
from doomfj.combat import half_width_table
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_trig_idioms_fj
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl
from doomfj.wad import WadFile
from doomfj.world import FIREBALL_POOL, FX_POOL, MELEE_REACH, TicEvents, World, aprox_distance

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
_MW = WadFile.from_path(ROOT / "assets" / "freedoom1.wad")
TYPES = MC.map_monster_types(["MT_BRUISER"])


@pytest.fixture(autouse=True)
def _e1m8_things(monkeypatch):
    unknown = {t.type for t in _MW.things("E1M8")} - set(gd.THING_TYPES) - set(gd.NOT_THINGS)
    monkeypatch.setattr(gd, "NOT_THINGS", frozenset(gd.NOT_THINGS | unknown))


def _world(**kw):
    kw.setdefault("monsters", "full")
    kw.setdefault("player", "fire")
    return World(_MW, "E1M8", gd.SK_HARD, sight_rule="seen", **kw)


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _run_prog(tmp_path, name, prog, want, feed=b"", extra=("fixed_point.fj", "sim.fj")) -> bool:
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve()] + [(FJ / f).resolve() for f in extra] + [p.resolve()]
    return fj.assemble_and_run_test_output(srcs, feed, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


# ---- 1. mstate's Baron rows --------------------------------------------------------------------------------------
def _baron_states():
    return [s for s in MC.monster_states(TYPES) if s in gd.EXT_STATE_NAMES]


def test_the_baron_rows_decode_to_info_c():
    """host: each Baron row's fields are its state's (next / tics / action / view group by the map's groups)"""
    groups = MC.view_groups(TYPES)
    vals = MC.state_table_values(TYPES)
    assert len(_baron_states()) == 22
    for s in _baron_states():
        v, st = vals[gd.THING_STATE_INDEX[s]], gd.STATES[s]
        assert v & 0xFF == gd.THING_STATE_INDEX[st.next]
        assert (v >> 8) & 15 == (MC.TICS_FOREVER if st.tics < 0 else st.tics)
        assert (v >> 12) & 15 == MC.action_id(st.action)
        assert groups[v >> 16] == (st.sprite, st.frame_index)
    assert MC.action_id("A_BruisAttack") == 9 and MC.action_id("A_BossDeath") == 10
    # E1M1's table holds none of them: the borrowed indices read 0 there
    core = MC.state_table_values()
    assert all(core[gd.THING_STATE_INDEX[s]] == 0 for s in _baron_states())


def _mstate_run(tmp_path, name, emitted):
    vals = MC.state_table_values(TYPES)
    idx = [gd.THING_STATE_INDEX[s] for s in _baron_states()]
    body = ["stl.startup_and_init_all"]
    for k in idx:
        body += ["hex.set 2, ix, %d" % k, "mstate.lookup rdst, ix", "hex.print_as_digit 6, rdst, 0", "stl.output 10"]
    prog = "\n".join(body + ["stl.loop", "ix: hex.vec 2", "rdst: hex.vec 6",
                             generate_dispatch_table_fj("mstate", emitted, index_nibbles=2, result_nibbles=6)]) + "\n"
    want = "".join("%06x\n" % vals[k] for k in idx).encode()
    return _run_prog(tmp_path, name, prog, want, extra=())


def test_the_baron_rows_run_in_fj(tmp_path):
    assert _mstate_run(tmp_path, "bmstate", MC.state_table_values(TYPES))


def test_control_the_core_table_is_caught(tmp_path):
    """R9: E1M1's table (no Baron rows) in a Baron map must fail"""
    assert not _mstate_run(tmp_path, "bmstate_core", MC.state_table_values())


# ---- 2. A_BossDeath --------------------------------------------------------------------------------------------------
def _boss_records(w):
    rnd = random.Random(0xB055)
    out = []
    for k in range(240):
        m = rnd.randrange(4)
        others = []
        for j in range(4):
            if j == m:
                others.append((1, rnd.choice((0, -7))))          # the dying one: health <= 0, active
                continue
            kind = rnd.choice(("dead", "dead", "dead", "alive", "absent", "zero", "neg", "big"))
            others.append({"dead": (1, -rnd.randint(1, 60)), "alive": (1, rnd.randint(1, 1000)), "absent": (0, 1000),
                           "zero": (1, 0), "neg": (1, -2048), "big": (1, 2047)}[kind])
        dead = int(rnd.random() < 0.2)
        g = rnd.choice(("still", "still", "still", "moving", "done"))
        out.append((m, others, dead, g))
    return out


def _boss_expected(w, records):
    g = w.boss_group
    grp = w.floor_groups[g]
    lines = []
    for m, others, dead, gs in records:
        ws = w.ws
        for j, (a, hp) in enumerate(others):
            ws.mon_active[j], ws.mon_health[j] = a, hp
        ws.p_dead, ws.p_health = dead, (0 if dead else 100)
        st, sub = {"still": (0, 0), "moving": (0, 3), "done": (grp.n - 1, 0)}[gs]
        w._set_floor(g, st, sub)
        w._a_boss_death(m, TicEvents(0))
        lines.append("%x%x" % (w.floor_state(g), w.floor_sub(g)))
    return ("\n".join(lines) + "\n").encode()


BOSS_MUTANTS = {
    "nodead": ("    hex.if1 1, p_dead, bnext\n", ""),
    "nofired": ("    hex.if1 1, fswitch + 2*dw, bnext\n", ""),
    "nonzero": ("    hex.if0 3, mon_health + 3*dw, mw0_bo1\n", ""),
}


def _boss_run(tmp_path, name, mut=None) -> bool:
    w = _world(monsters="final", player="final")
    bo = MC.boss_slots(w)
    assert sorted(bo) == [0, 1, 2, 3] and bo[0]["state"] == "fswitch + 2*dw" and bo[0]["sub"] == 4
    ng = len(w.floor_groups)
    records = _boss_records(w)
    code = []
    for m in range(4):
        code += ["bossb%d:" % m] + MC.boss_lines("mw%d_" % m, "bnext", bo[m])
    code += ["bnext:", "    stl.fret b_ret"]
    text = "\n".join(code) + "\n"
    if mut:
        old, new = BOSS_MUTANTS[mut]
        assert text.count(old) >= 1, (mut, text.count(old))
        text = text.replace(old, new)
    body = ["stl.startup_and_init_all"]
    g = w.boss_group
    grp = w.floor_groups[g]
    for m, others, dead, gs in records:
        st, sub = {"still": (0, 0), "moving": (0, 3), "done": (grp.n - 1, 0)}[gs]
        body += ["hex.set 4, mon_active, %d" % sum(a << (4 * j) for j, (a, _h) in enumerate(others)),
                 "hex.set 12, mon_health, %d" % sum((hp & 0xFFF) << (12 * j) for j, (_a, hp) in enumerate(others)),
                 "hex.set 1, p_dead, %d" % dead,
                 "hex.set 1, fswitch + %d*dw, %d" % (g, st), "hex.set 1, fswitch + %d*dw, %d" % (ng + g, sub),
                 "stl.fcall bossb%d, b_ret" % m,
                 "hex.print_as_digit 1, fswitch + %d*dw, 0" % g, "hex.print_as_digit 1, fswitch + %d*dw, 0" % (ng + g),
                 "stl.output 10"]
    prog = "\n".join(body + ["stl.loop", "mon_active: hex.vec 4", "mon_health: hex.vec 12", "p_dead: hex.vec 1",
                             "fswitch: hex.vec %d" % (2 * ng), "b_ret: hex.vec w/4", text]) + "\n"
    return _run_prog(tmp_path, name, prog, _boss_expected(_world(monsters="final", player="final"), records))


def test_the_boss_records_exercise_every_path():
    w = _world(monsters="final", player="final")
    recs = _boss_records(w)
    fired = blocked = 0
    g = w.boss_group
    for m, others, dead, gs in recs:
        before = len(w.boss_log)
        _boss_expected(w, [(m, others, dead, gs)])
        fired += len(w.boss_log) > before
        blocked += len(w.boss_log) == before and not dead and gs == "still"
    assert fired >= 20 and blocked >= 20, (fired, blocked)


def test_boss_death_follows_the_model(tmp_path):
    assert _boss_run(tmp_path, "bboss"), "the fj A_BossDeath parted from World._a_boss_death"


@pytest.mark.parametrize("mut", sorted(BOSS_MUTANTS))
def test_control_a_broken_boss_death_is_caught(tmp_path, mut):
    assert not _boss_run(tmp_path, "bboss_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ---- 3. A_BruisAttack ------------------------------------------------------------------------------------------------
ATTACK_CELLS = (("mm_rng", 2), ("p_hp", 3), ("p_ar", 2), ("p_at", 1), ("p_dc", 2), ("p_dead", 1), ("rng_pl", 2),
                ("pj_n", 1), ("pj_lx", 4), ("pj_ly", 4), ("p_atk", 2))


def _attack_records(w):
    rnd = random.Random(0xB4)
    from doomfj.sight import NEAR
    out = []
    for r in range(240):
        m = r % 4
        mx, my = rnd.randint(-1500, 2000), rnd.randint(-2000, 800)
        d = rnd.choice((rnd.randint(0, MELEE_REACH + 4), MELEE_REACH - 1, MELEE_REACH, NEAR, NEAR + 1,
                        rnd.randint(0, 300), rnd.randint(200, 2100)))
        a = rnd.randint(0, d)
        dx, dy = a, 0
        while aprox_distance(dx, dy) < d:
            dy += 1
        dx, dy = dx * rnd.choice((1, -1)), dy * rnd.choice((1, -1))
        px16 = (((mx + dx) << 16) | rnd.randrange(1 << 16)) & M32
        py16 = (((my + dy) << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        hp = rnd.choice((100, 100, 100, rnd.randint(1, 60), 5, 0))
        pokes = {"p_health": hp, "p_armor": rnd.choice((0, 0, 3, 50, 200)), "p_armortype": rnd.choice((0, 1, 2)),
                 "p_damagecount": rnd.randint(0, 100), "p_dead": int(hp <= 0 or rnd.random() < 0.04),
                 "rng_player": rnd.randrange(256)}
        out.append((m, (mx, my), (px16, py16), rnd.randrange(256), int(rnd.random() < 0.6),
                    int(rnd.random() < 0.5), pokes))
    return out


class _Fire:
    def __init__(self):
        self.n, self.last = 0, (0, 0)


def _attack_apply(w, rec, fire, ev):
    m, (mx, my), (px16, py16), mrng, seen, hit, pokes = rec
    ws = w.ws
    ws.px, ws.py = _s32(px16), _s32(py16)
    ws.mon_x[m], ws.mon_y[m], ws.mon_rng[m], ws.mon_seen[m], ws.mon_target[m] = mx, my, mrng, seen, 1
    for f, v in pokes.items():
        setattr(ws, f, v)
    ws.p_ready, ws.p_wpn_state, ws.p_wpn_tics, ws.p_wpn_sy = (
        gd.WP_PISTOL, gd.STATE_INDEX[gd.WEAPONINFO[gd.WP_PISTOL].readystate], 1, 32)
    w.los_to_player = lambda world, mm, _h=hit: not _h

    def spawn(mm, e):
        fire.n += 1
        fire.last = (ws.mon_x[mm], ws.mon_y[mm])
    w._spawn_fireball = spawn
    w._monster_attack(m, "A_BruisAttack", ev)


def _attack_expected(records) -> bytes:
    w = _world()
    fire = _Fire()
    lines = []
    for rec in records:
        _attack_apply(w, rec, fire, TicEvents(0))
        m, ws = rec[0], w.ws
        vals = [ws.mon_rng[m], ws.p_health & 0xFFF, ws.p_armor, ws.p_armortype, ws.p_damagecount, ws.p_dead,
                ws.rng_player, fire.n & 15, fire.last[0] & 0xFFFF, fire.last[1] & 0xFFFF, ws.p_attacker]
        lines.append("".join("%0*x" % (n, v) for (_c, n), v in zip(ATTACK_CELLS, vals)))
    return ("\n".join(lines) + "\n").encode()


ATTACK_MUTANTS = {
    "imptable": None,                                       # brclaw holds the imp's (v%8+1)*3
    "nosight": ("    hex.if0 1, mm_asr, md_claw_f\n", "", 2),
    "nofireball": ("    stl.fcall pj_spawn, pj_sret\n", "", 1),
    "reachle": ("    hex.cmp 4, mt_d, mt_c60, md_bclaw_r, md_claw_f, md_claw_f\n",
                "    hex.cmp 4, mt_d, mt_c60, md_bclaw_r, md_bclaw_r, md_claw_f\n", 1),
}


def _attack_run(tmp_path, name, mut=None) -> bool:
    w = _world()
    records = _attack_records(w)
    hwt = half_width_table(w.rm.sine)
    tables = H.tables_fj(hwt, bruiser=True)
    if mut == "imptable":
        tables = [t if "ns brclaw {" not in t else generate_dispatch_table_fj(
            "brclaw", H.one_draw_values("troop_claw"), index_nibbles=2, result_nibbles=2) for t in tables]
    attack = "\n".join(MD.attack_leaf_lines(full=True, bruiser=True)) + "\n"
    if mut and ATTACK_MUTANTS[mut]:
        old, new, cnt = ATTACK_MUTANTS[mut]
        assert attack.count(old) == cnt, (mut, attack.count(old))
        attack = attack.replace(old, new) if cnt == 1 else attack.replace(
            "  md_bclaw_r:\n    stl.fcall mm_as, mm_asret\n" + old, "  md_bclaw_r:\n    stl.fcall mm_as, mm_asret\n" + new)
    lines = (MD.todist_leaf_lines() + MD.octant_leaf_lines() + MD.as_leaf_lines() + MC.dist_leaf_lines()
             + H.dp_lines()
             + ["sl_los:", "    stl.fret sl_ret",
                "pj_spawn:", "    hex.inc 1, pj_n", "    hex.mov 4, pj_lx, mm_x", "    hex.mov 4, pj_ly, mm_y",
                "    stl.fret pj_sret"])
    states, frames = WC.weapon_states(), WC.overlay_frames()
    decls = (H.hurt_decls(H.level_start(w)) + WC.weapon_decls(WC.level_start(w.mw, "E1M8"), states, frames)
             + WC.weapon_const_decls() + MD.context_decls() + MC.P32A_SCRATCH
             + ["mm_x: hex.vec 4", "mm_y: hex.vec 4", "mm_rng: hex.vec 2",
                "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
                "mt_t: hex.vec 4", "viewx: hex.vec 8", "viewy: hex.vec 8",
                "sl_hit: hex.vec 1", "sl_ret: hex.vec w/4", "pj_sret: hex.vec w/4", "pj_n: hex.vec 1",
                "pj_lx: hex.vec 4", "pj_ly: hex.vec 4"])
    nib = {"p_health": ("p_hp", 3), "p_armor": ("p_ar", 2), "p_armortype": ("p_at", 1),
           "p_damagecount": ("p_dc", 2), "p_dead": ("p_dead", 1), "rng_player": ("rng_pl", 2)}
    ready = gd.WEAPONINFO[gd.WP_PISTOL].readystate
    body = ["stl.startup_and_init_all"]
    for m, (mx, my), (px16, py16), mrng, seen, hit, pokes in records:
        body += ["hex.set 8, viewx, %d" % px16, "hex.set 8, viewy, %d" % py16,
                 "hex.set 4, mm_x, %d" % (mx & 0xFFFF), "hex.set 4, mm_y, %d" % (my & 0xFFFF),
                 "hex.set 2, mm_rng, %d" % mrng, "hex.set 1, mm_seen, %d" % seen, "hex.set 1, sl_hit, %d" % hit,
                 "hex.set 1, mm_kind, %d" % MD.ATTACK_KINDS["A_BruisAttack"],
                 "hex.set 1, wp_rdy, %d" % gd.WP_PISTOL, "hex.set 2, wp_st, %d" % states.index(ready),
                 "hex.set 1, wp_tics, 1", "hex.set 2, wp_sy, 32",
                 "hex.set 2, wp_frm, %d" % frames.index(WC.psprite_lump(ready))]
        body += ["hex.set %d, %s, %d" % (nib[f][1], nib[f][0], v & (16 ** nib[f][1] - 1)) for f, v in pokes.items()]
        body += ["hex.set 2, md_src, %d" % (m + 1), "stl.fcall md_attack, md_ret"]
        body += ["hex.print_as_digit %d, %s, 0" % (n, c) for c, n in ATTACK_CELLS] + ["stl.output 10"]
    prog = "\n".join(body + ["stl.loop"] + decls + ["\n".join(lines) + "\n" + attack] + tables) + "\n"
    return _run_prog(tmp_path, name, prog, _attack_expected(records))


def test_the_attack_records_exercise_every_path():
    w = _world()
    fire = _Fire()
    seen = dict(claw=0, far=0, blind=0, kill=0)
    for rec in _attack_records(w):
        ev = TicEvents(0)
        n0 = fire.n
        _attack_apply(w, rec, fire, ev)
        seen["claw"] += len(ev.mon_melee)
        d = aprox_distance((_s32(rec[2][0]) >> 16) - rec[1][0], (_s32(rec[2][1]) >> 16) - rec[1][1])
        if fire.n > n0:
            seen["far" if d >= MELEE_REACH else "blind"] += 1
        seen["kill"] += ev.deaths
    assert seen["claw"] >= 15 and seen["far"] >= 30 and seen["blind"] >= 3 and seen["kill"] >= 2, seen


def test_the_baron_attack_follows_the_model(tmp_path):
    assert _attack_run(tmp_path, "battack"), "the fj A_BruisAttack parted from the model"


@pytest.mark.parametrize("mut", sorted(ATTACK_MUTANTS))
def test_control_a_broken_baron_attack_is_caught(tmp_path, mut):
    assert not _attack_run(tmp_path, "battack_" + mut, mut), "%s passed: the comparison is vacuous" % mut
