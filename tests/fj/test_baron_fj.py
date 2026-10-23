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
  * the thrust on a mass-1000 target (knockcode.thrust_lines(mass1k=True): kbm1k and hex.fixed_mul_low) against
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


# ---- 4. the green fireball's pool ------------------------------------------------------------------------------------
POOL_FRAMES = 420
POOL_ANGLE = "    proj.point_to_angle pw_ang, pw_x, pw_y, viewx, viewy, 1\n"


def _pool_world():
    return _world(player="full")


def _pool_script(w):
    """[(px16, py16, p_hp, p_dead, door states, floor-group states, [(mm_x, mm_y)])]: scenes from the Barons' spots --
    a player in the open at a random angle and distance, point blank, dead; the door and the three floor groups
    (the boss sector's lines shut a missile below their pass state) at random states"""
    rnd = random.Random(0xBA7)
    spots = [(w.ws.mon_x[m], w.ws.mon_y[m]) for m in range(w.layout.nmon)]
    out, f = [], 0
    import math
    while f < POOL_FRAMES:
        kind = rnd.choice(("open", "open", "blank", "dead", "far"))
        shooter = rnd.choice(spots)
        ang = rnd.random() * 2 * math.pi
        dist = {"open": rnd.randint(30, 200), "blank": rnd.uniform(4, 27), "dead": rnd.randint(20, 120),
                "far": rnd.randint(200, 700)}[kind]
        px, py = int((shooter[0] + dist * math.cos(ang)) * 65536), int((shooter[1] + dist * math.sin(ang)) * 65536)
        hp, dead = (rnd.choice(((100, 1), (0, 0), (-5, 0))) if kind == "dead" else (rnd.choice((100, 37, 1)), 0))
        for i in range(rnd.randint(10, 40)):
            if f >= POOL_FRAMES:
                break
            dst = [rnd.randrange(w.door_nstates[si]) for si in w.door_order]
            fst = [rnd.randrange(g.n) if rnd.random() < 0.3 else 0 for g in w.floor_groups]
            r = rnd.random()
            nsp = 0 if r < 0.6 else 1 if r < 0.92 else 2
            out.append((px & M32, py & M32, hp, dead, dst, fst, [shooter] * nsp))
            f += 1
    return out


def _pool_row(w):
    ws = w.ws
    s = ""
    for k in range(FIREBALL_POOL):
        s += "%x%08x%08x%08x%08x%02x%x" % (ws.proj_active[k], ws.proj_x[k] & M32, ws.proj_y[k] & M32,
                                          ws.proj_momx[k] & M32, ws.proj_momy[k] & M32, ws.proj_state[k],
                                          ws.proj_tics[k])
        s += "%02x" % (ws.proj_src[k] + 1 if ws.proj_active[k] else 0)
        s += "%08x%08x%03x" % (ws.proj_y[k] & M32 & ~0xFFFF, ws.proj_x[k] & M32 & ~0xFFFF, ws.proj_leaf[k])
    return s + "%02x" % ws.rng_fx


def _pool_model(script):
    """-> (the expected output, the stdin feed) -- tests/fj/test_fireball_pool_fj.py's protocol: per frame the pokes,
    each spawn's position, the angle the stubbed point_to_angle line reads, every point location's leaf"""
    w = _pool_world()
    ws = w.ws
    log, feed = [], []
    orig_leaf, orig_try, orig_spawn = w._leaf16, w._missile_try, w._spawn_fireball
    st = {"spawn": False, "skip": False}

    def leaf16(x16, y16):
        leaf = orig_leaf(x16, y16)
        if not st["skip"]:
            log.append("p%010x%010x" % ((x16 >> 16) & 0xFFFFFFFFFF, (y16 >> 16) & 0xFFFFFFFFFF))
            feed.append(struct.pack("<H", leaf))
        return leaf

    def mtry(slot, nx, ny, ev):
        st["skip"] = st["spawn"]
        try:
            return orig_try(slot, nx, ny, ev)
        finally:
            st["skip"] = False

    def spawn(m, ev):
        st["spawn"] = True
        try:
            orig_spawn(m, ev)
        finally:
            st["spawn"] = False
    w._leaf16, w._missile_try, w._spawn_fireball = leaf16, mtry, spawn
    w.damage_player = lambda dmg, source, inflictor, ev: log.append("h%02x%02x" % (dmg, source[1] + 1))
    ng = len(w.floor_groups)
    lines = []
    for px16, py16, hp, dead, dst, fst, sp in script:
        feed.append(bytes([0xD0]) + struct.pack("<II", px16, py16) + struct.pack("<H", (hp & 0xFFF) | (dead << 12))
                    + bytes([dst[0]]) + bytes(fst) + bytes([len(sp)]))
        ws.px, ws.py = _s32(px16), _s32(py16)
        ws.p_health, ws.p_dead = hp, dead
        ws.d_state[0] = dst[0]
        for g, v in enumerate(fst):
            w._set_floor(g, v, 0)
        w._door_phase_scene()
        ev = TicEvents(0)
        for x, y in sp:
            feed.append(struct.pack("<HH", x & 0xFFFF, y & 0xFFFF))
            ws.mon_x[0], ws.mon_y[0] = x, y
            if not all(ws.proj_active):
                feed.append(struct.pack("<I", w.rm.point_to_angle(x << 16, y << 16, ws.px, ws.py)))
            w._spawn_fireball(0, ev)
        w._projectiles_phase(ev)
        lines.append("".join(log) + _pool_row(w))
        log.clear()
    return ("\n".join(lines) + "\n").encode(), b"".join(feed) + bytes([0])


POOL_MUTANTS = ("imp", "times10", "nodraw")


def _pool_run(tmp_path, name, mut=None) -> bool:
    w = _pool_world()
    assert len(w.door_order) == 1 and not w.lift_order
    n, nleaf, ng = w.layout.nmon, len(w.cmap.subsectors), len(w.floor_groups)
    nt = n
    nthings = nt + FIREBALL_POOL + FX_POOL
    script = _pool_script(w)
    want, feed = _pool_model(script)
    missile = None if mut == "imp" else PC.missile_of_world(w)
    assert PC.missile_of_world(w) == "MT_BRUISERSHOT"
    cells, root = PC.missile_cells_fj(w)
    code = "\n".join(PC.pj_lines(nt=nt, root=root, **({"missile": missile} if missile else {}))
                     + PC.pool_tic_lines()) + "\n"
    if mut == "times10":
        old = "".join(ln + "\n" for ln in PC._times15("pw_mx"))
        assert code.count(old) == 1
        code = code.replace(old, "".join(ln + "\n" for ln in PC._times10("pw_mx")))
    if mut == "nodraw":
        old = ("    hex.inc 2, rng_fx\n    fxrnd.lookup pw_rr, rng_fx\n    hex.sub 1, pw_ti, pw_rr + 2*dw\n"
               "    stl.fret pj_eret\n")
        assert code.count(old) == 1
        code = code.replace(old, "    stl.fret pj_eret\n")
    assert code.count(POOL_ANGLE) == 1
    code = code.replace(POOL_ANGLE, "    hex.input 4, pw_ang\n")
    head, nxt = [0] * nleaf, [0] * nthings
    for leaf, ks in w.leaf_lists().items():
        head[leaf] = ks[0] + 1
        for a, b in zip(ks, ks[1:] + [-1]):
            nxt[a] = b + 1
    ws = w.ws
    dump = ["pj_dump:"]
    for s in range(FIREBALL_POOL):
        t = nt + s
        dump += ["    hex.print_as_digit 1, pj_act + %d*dw, 0" % s,
                 "    hex.print_as_digit 8, pj_x + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, pj_y + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, pj_mx + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, pj_my + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 2, pj_st + %d*dw, 0" % (2 * s),
                 "    hex.print_as_digit 1, pj_ti + %d*dw, 0" % s,
                 "    hex.print_as_digit 2, pj_src + %d*dw, 0" % (2 * s),
                 "    hex.print_as_digit 16, thpos_rt + %d*dw, 0" % (16 * t),
                 "    hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * t)]
    dump += ["    hex.print_as_digit 2, rng_fx, 0", "    stl.output 10", "    stl.fret dump_ret"]
    body = ["stl.startup_and_init_all",
            "loop:",
            "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.input 2, hpin", "hex.mov 3, p_hp, hpin", "hex.mov 1, p_dead, hpin + 3*dw",
            "hex.input 1, dstate",
            # the floor-group states: one byte each from the feed into fswitch's state nibbles
            "hex.input %d, fsin" % ng] + ["hex.mov 1, fswitch + %d*dw, fsin + %d*dw" % (g, 2 * g) for g in range(ng)]
    body += ["hex.input 1, nsp",
             "sp_loop:", "hex.if0 2, nsp, sp_done",
             "hex.input 2, mm_x", "hex.input 2, mm_y",
             "hex.set 2, md_src, 1",
             "stl.fcall pj_spawn, pj_sret",
             "hex.dec 2, nsp", ";sp_loop",
             "sp_done:",
             "stl.fcall pj_phase, pj_pret",
             "stl.fcall pj_dump, dump_ret",
             ";loop",
             "done:", "stl.loop",
             "dp_go:", "    stl.output 104", "    hex.print_as_digit 2, dp_dmg, 0",
             "    hex.print_as_digit 2, dp_src, 0", "    hex.zero 2, dp_src", "    stl.fret dp_ret",
             "ptloc_walk:", "    stl.output 112", "    hex.print_as_digit 10, ptx, 0", "    hex.print_as_digit 10, pty, 0",
             "    hex.zero w/4, ptss", "    hex.input 2, ptss", "    stl.fret ptloc_ret"]
    decls = (PC.pool_decls() + COLLISION_STATE_DECLS + point_location_decls() + LEAF_LINK_DECLS
             + ["wmagic: hex.vec 2", "nsp: hex.vec 2", "hpin: hex.vec 4", "fsin: hex.vec %d" % (2 * ng),
                "viewx: hex.vec 8", "viewy: hex.vec 8", "mm_x: hex.vec 4", "mm_y: hex.vec 4",
                "p_hp: hex.vec 3", "p_dead: hex.vec 1", "lvdone: hex.vec 1", "dp_dmg: hex.vec 2",
                "dp_src: hex.vec 2", "md_src: hex.vec 2",
                "dp_ret: hex.vec w/4", "dump_ret: hex.vec w/4",
                "dstate: hex.vec 2", "fswitch: hex.vec %d" % (2 * ng),
                "thpos_rt: hex.vec %d, %d" % (16 * nthings, sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32)
                                                                 << 32) << (64 * m) for m in range(n))),
                "thss_rt: hex.vec %d, %d" % (16 * nthings, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * nthings)])
    tables = (PC.tables_fj(**({"missile": missile} if missile else {}))
              + [generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry")])
    prog = "\n".join(body + decls + dump + [code, cells] + tables) + "\n"
    return _run_prog(tmp_path, name, prog, want, feed=feed)


def test_the_pool_script_exercises_every_path():
    w = _pool_world()
    script = _pool_script(w)
    want, _feed = _pool_model(script)
    text = want.decode()
    assert text.count("h") >= 15, "impacts on the player"
    ws = w.ws
    st = set()
    w2 = _pool_world()
    for rec in script:
        px16, py16, hp, dead, dst, fst, sp = rec
        w2.ws.px, w2.ws.py, w2.ws.p_health, w2.ws.p_dead = _s32(px16), _s32(py16), hp, dead
        w2.ws.d_state[0] = dst[0]
        for g, v in enumerate(fst):
            w2._set_floor(g, v, 0)
        w2._door_phase_scene()
        ev = TicEvents(0)
        for x, y in sp:
            w2.ws.mon_x[0], w2.ws.mon_y[0] = x, y
            w2._spawn_fireball(0, ev)
        w2._projectiles_phase(ev)
        st |= {gd.THING_STATE_NAMES[w2.ws.proj_state[k]] for k in range(FIREBALL_POOL) if w2.ws.proj_active[k]}
    assert st == {"S_BRBALL1", "S_BRBALL2", "S_BRBALLX1", "S_BRBALLX2", "S_BRBALLX3"}, st


def test_the_green_fireball_pool_follows_the_model(tmp_path):
    assert _pool_run(tmp_path, "bpool"), "the fj pool (the Baron's missile) parted from the model"


@pytest.mark.parametrize("mut", POOL_MUTANTS)
def test_control_a_broken_green_fireball_is_caught(tmp_path, mut):
    assert not _pool_run(tmp_path, "bpool_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ---- 5. the thrust on a mass-1000 target -----------------------------------------------------------------------------
def _thrust_records():
    rnd = random.Random(0x1000)
    out = []
    for k in range(160):
        tx, ty = rnd.randint(-1500, 2000), rnd.randint(-2000, 800)
        fx, fy = rnd.randrange(1 << 16), rnd.choice((0, rnd.randrange(1 << 16)))
        ang = rnd.random() * 6.2831853
        d = rnd.choice((rnd.randint(1, 300), 0, rnd.randint(1, 8)))
        import math
        ix, iy = tx + int(d * math.cos(ang)), ty + int(d * math.sin(ang))
        rev = rnd.random() < 0.35                         # the reversal's conditions all hold (then the coin)
        dmg = rnd.randint(1, 39) if rev else rnd.choice((rnd.randint(1, 255), rnd.randint(1, 80), 255, 1))
        hp = rnd.randint(1, dmg - 1) if rev and dmg > 1 else rnd.choice((1000, rnd.randint(1, 1000), 3))
        tz, iz = (rnd.randint(70, 200), 0) if rev else (rnd.randint(-40, 40), rnd.randint(-40, 40))
        out.append((tx, ty, fx, fy, ix, iy, dmg, hp, tz, iz, rnd.randrange(256)))
    return out


def _thrust_expected(records) -> bytes:
    w = _world(monsters="final", player="final")
    ws = w.ws
    lines = []
    for tx, ty, fx, fy, ix, iy, dmg, hp, tz, iz, rng in records:
        ws.mon_x[0], ws.mon_y[0], ws.mon_fx[0], ws.mon_fy[0] = tx, ty, fx, fy
        ws.mon_x[1], ws.mon_y[1] = ix, iy
        ws.mon_health[0], ws.mon_rng[0], ws.mon_floorz[0], ws.mon_floorz[1] = hp, rng, tz, iz
        ws.mon_momx[0] = ws.mon_momy[0] = 0
        w._thrust(("mon", 0), ("mon", 1), ("mon", 1), dmg)
        lines.append("%08x%08x%02x" % (ws.mon_momx[0] & M32, ws.mon_momy[0] & M32, ws.mon_rng[0]))
    return ("\n".join(lines) + "\n").encode()


def _thrust_run(tmp_path, name, mut=None) -> bool:
    from doomfj import knockcode as KC
    from doomfj.lut_generator import generate_tantoangle_lut_fj
    from doomfj.reference_model import SLOPERANGE
    from doomfj.tables import slopediv_recip8_table, tantoangle_table
    from doomfj.wall_renderer import hoisted_scratch_fj
    w = _world(monsters="final", player="final")
    assert w.mon_info[0].mass == KC.MASS_TABLE
    records = _thrust_records()
    th = "\n".join(KC.thrust_lines(mass1k=True)) + "\n"
    if mut == "shift":                                   # the mass-400 path (the shift) for a Baron
        th = th.replace("    hex.if1 1, kb_hk, kq_k1k\n", "    hex.set 1, kb_hv, 1\n")
    if mut == "norev":
        old = "    hex.shl_bit 8, kb_t1k\n    hex.shl_bit 8, kb_t1k\n"
        assert th.count(old) == 1
        th = th.replace(old, "")
    body = ["stl.startup_and_init_all"]
    for tx, ty, fx, fy, ix, iy, dmg, hp, tz, iz, rng in records:
        body += ["hex.set 8, kb_tx, %d" % (((tx << 16) | fx) & M32), "hex.set 8, kb_ty, %d" % (((ty << 16) | fy) & M32),
                 "hex.set 8, kb_i8x, %d" % ((ix << 16) & M32), "hex.set 8, kb_i8y, %d" % ((iy << 16) & M32),
                 "hex.set 2, kb_dm, %d" % dmg, "hex.set 3, kb_hp, %d" % (hp & 0xFFF), "hex.set 2, kb_rng, %d" % rng,
                 "hex.set 4, kb_tz, %d" % (tz & 0xFFFF), "hex.set 4, kb_iz, %d" % (iz & 0xFFFF),
                 "hex.zero 1, kb_tzp", "hex.zero 1, kb_izp", "hex.zero 1, kb_hv", "hex.set 1, kb_hk, 1",
                 "stl.fcall kb_th, kb_tret",
                 "hex.print_as_digit 8, kb_mx, 0", "hex.print_as_digit 8, kb_my, 0", "hex.print_as_digit 2, kb_rng, 0",
                 "stl.output 10"]
    data = (list(KC.KB_INTERFACE) + list(KC.KB_SCRATCH) + ["kb_cell: stl.fret kb_cret"]
            + [th, generate_dispatch_table_fj("mrnd", MC.rnd_values(), index_nibbles=2, result_nibbles=4),
               generate_dispatch_table_fj("kbm1k", KC.thrust_table_values(), index_nibbles=2, result_nibbles=5),
               generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry"),
               generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
               generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
               generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
               "cpx: hex.vec 8", "cpy: hex.vec 8", "cp_floor: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8"])
    prog = "\n".join(body + ["stl.loop"] + data) + "\n" + hoisted_scratch_fj()
    return _run_prog(tmp_path, name, prog, _thrust_expected(records),
                     extra=("fixed_point.fj", "projection.fj", "frame_render.fj"))


def test_the_thrust_records_reverse_and_not():
    w = _world(monsters="final", player="final")
    ws = w.ws
    revs = 0
    for tx, ty, fx, fy, ix, iy, dmg, hp, tz, iz, rng in _thrust_records():
        ws.mon_rng[0] = rng
        revs += dmg < 40 and dmg > hp and tz - iz > 64 and bool(R_coin(rng))
    assert revs >= 10, revs


def R_coin(rng):
    from doomfj import rng as R
    return R.p_random(rng)[0] & 1


def test_the_mass_1000_thrust_follows_the_model(tmp_path):
    assert _thrust_run(tmp_path, "bthrust"), "the fj thrust on a Baron parted from combat._thrust"


@pytest.mark.parametrize("mut", ["shift", "norev"])
def test_control_a_broken_mass_1000_thrust_is_caught(tmp_path, mut):
    assert not _thrust_run(tmp_path, "bthrust_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ---- 6. the whole decide tic on E1M8 (the Barons' slots) -------------------------------------------------------------
TIC_FRAMES = 140


def _tic_world():
    """E1M8 in the decide mode: the four Barons awake (their reaction spent), Baron 3 killed at the start -- its tic
    walks S_BOSS_DIE1 .. DIE7: A_Fall at DIE4, A_BossDeath at DIE7 (three live Barons hold the floor)"""
    w = World(_MW, "E1M8", gd.SK_HARD, monsters="decide", sight_rule="seen")
    for m in range(3):
        w.ws.mon_target[m] = 1
        w._set_state(m, w.mon_info[m].seestate, False, TicEvents(0))
        w.ws.mon_reaction[m] = 0
    w.ws.mon_shootable[3], w.ws.mon_health[3] = 0, 0
    w._set_state(3, w.mon_info[3].deathstate, True, TicEvents(0))
    return w


def _tic_set(w, x16, y16, seen):
    ws = w.ws
    ws.px, ws.py = _s32(x16), _s32(y16)
    for m in range(w.layout.nmon):
        ws.mon_seen[m] = int(m in seen)


def _tic_script():
    w = _tic_world()
    rnd = random.Random(0xBA2)
    out = []
    for f in range(TIC_FRAMES):
        m = (f // 12) % 3
        r = rnd.choice((30, 40, 50, 90, 140, 300))
        a = rnd.randrange(8)
        dx, dy = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)][a]
        k = r if dx * dy == 0 else r * 7 // 10
        x16 = ((w.ws.mon_x[m] + dx * k) << 16 | rnd.randrange(1 << 16)) & M32
        y16 = ((w.ws.mon_y[m] + dy * k) << 16 | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        seen = {q for q in range(3) if rnd.random() < 0.6}
        out.append((x16, y16, seen))
        _tic_set(w, *out[-1])
        w._monsters_phase(TicEvents(0))
    return out


def _tic_row(w):
    ws, n = w.ws, w.layout.nmon
    s = "".join("%02x%x%x%x%x%02x%x%02x%02x%x%x%x%04x%04x%04x%03x" % (
        ws.mon_state[m], ws.mon_tics[m], ws.mon_facing[m], ws.mon_target[m], ws.mon_reaction[m],
        ws.mon_threshold[m], ws.mon_movedir[m], ws.mon_movecount[m] & 0xFF, ws.mon_rng[m], ws.mon_justattacked[m],
        ws.mon_justhit[m], ws.mon_solid[m],
        ws.mon_x[m] & 0xFFFF, ws.mon_y[m] & 0xFFFF, ws.mon_floorz[m] & 0xFFFF, ws.mon_leaf[m]) for m in range(n))
    return s + "%02x" % ws.sched_cursor


def _tic_expected(script) -> bytes:
    w = _tic_world()
    lines = []
    for fr in script:
        _tic_set(w, *fr)
        w._monsters_phase(TicEvents(0))
        lines.append(_tic_row(w))
        for d in range(len(w.door_order)):
            w.ws.d_monreq[d] = 0
    return ("\n".join(lines) + "\n").encode()


TIC_MUTANTS = {
    # A_BruisAttack facing its target (the imp's k_go for the Baron's action)
    "face": ("    ;mw0_k_gon\n", "    ;mw0_k_go\n"),
    # the Baron moved at radius 20 (the core class) -- its box and its cells' radius
    "r20": ("    hex.set 2, mm_r, 24\n", "    hex.set 2, mm_r, 20\n"),
    # no A_Fall for the dying Baron
    "nofall": ("  mw3_fall:\n    hex.zero 1, mon_solid + 3*dw\n", "  mw3_fall:\n"),
}


def _tic_build(tmp_path, name, mut=None):
    from doomfj import damagecode as DC
    from doomfj import monstermove as MM
    from doomfj import monstersight as MS
    from doomfj.collision import MON_CELL_DECLS, generate_point_location_fj, monster_cells_fj
    from doomfj.things import spawn_leaf_lists
    from doomfj.wall_renderer import DOOR_QUANT
    from doomfj.world import CHASE_DEADZONE, DROPOFF_MAX, NEWCHASEDIR_MAX_TRIES, STEP_UP, radius_classes
    w = _tic_world()
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    r0 = radius_classes(w.mon_radius)[0]
    assert r0 == 24 and set(w.mon_height) == {64}
    script = _tic_script()
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    things, _var = MM.static_blockers(w)
    cells, root = monster_cells_fj("e1m8", w.lds, w.cmap.vertexes, w.secs, w.sds, things=things, **kw)
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    door_boxes = [(d, w.mon_door_boxes[si]) for d, si in enumerate(w.door_order) if si in w.mon_door_boxes]
    bo = MC.boss_slots(w)
    slots = []
    for m in range(n):
        info = w.mon_info[m]
        slots.append(dict(t=m, x=ws.mon_x[m], y=ws.mon_y[m], rj="", see_idx=gd.THING_STATE_INDEX[info.seestate],
                          see_tics=gd.STATES[info.seestate].tics,
                          mv=dict(rt=m, radius=w.mon_radius[m], speed=w.mon_speed[m], r0=r0), dc=MD.type_decide(info),
                          dmg=True, boss=bo[m]))
    secs = sorted({w.leaf_sector[s] for s in range(len(w.cmap.subsectors))})
    tables = MC.p30_tables_fj(TYPES)
    tables += [generate_dispatch_table_fj("rj%d" % s, [int(w.reject.visible(s, q)) for q in range(w.reject.nsec)],
                                          index_nibbles=w.sec_nibbles, result_nibbles=1) for s in secs]
    nleaf = len(w.cmap.subsectors)
    tables.append(generate_dispatch_table_fj("lfsec", list(w.leaf_sector), index_nibbles=3, result_nibbles=w.sec_nibbles))
    tables.append(generate_point_location_fj(w.cmap))
    fields = MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS + MD.P32C_FIELDS
    vals = {f: list(getattr(ws, f)[:n]) for f in fields}
    msec = [w._mon_sector(m) for m in range(n)]
    head, nxt = spawn_leaf_lists([ws.mon_leaf[m] for m in range(n)], nleaf,
                                 present=[bool(ws.mon_active[m]) for m in range(n)])
    ng = len(w.floor_groups)
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": ws.sched_cursor},
                             n, w.sec_nibbles)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, msec, w.sec_nibbles, r0)
             + MC.p32c_decls(schema, n, {f: vals[f] for f in MD.P32C_FIELDS})
             + DC.field_decls(schema, n, {f: list(getattr(ws, f)[:n]) for f in DC.P42_FIELDS}) + ["mm_jh: hex.vec 1"]
             + MD.context_decls() + MS.SL_DECLS
             + MC.MT_DECLS + MC.P32A_SCRATCH + point_location_decls() + COLLISION_STATE_DECLS + MON_CELL_DECLS
             + LEAF_LINK_DECLS + MM.monster_seed_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "mt_tret: hex.vec w/4", "p_dead: hex.vec 1",
                "thpos_rt: hex.vec %d, %d" % (16 * n, sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32) << 32)
                                                          << (64 * m) for m in range(n))),
                "thss_rt: hex.vec %d, %d" % (16 * n, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * n),
                "dstate: hex.vec %d" % (2 * len(w.door_order)), "ddir: hex.vec %d" % (2 * len(w.door_order)),
                "dreq: hex.vec %d" % (2 * len(w.door_order)),
                "lstate: hex.vec 2", "lreq: hex.vec 2",
                "fswitch: hex.vec %d" % (2 * ng), "dbox: hex.vec 8",
                "bar_solid: hex.vec 2", "mc_don: hex.vec 2"])
    move = (MM.things_leaf_lines([(m, w.mon_radius[m]) for m in range(n)], solid="mon_solid")
            + MM.move_leaf_lines(root=root, lift_trigs=[], door_boxes=door_boxes, dropmax=DROPOFF_MAX,
                                 stepup=STEP_UP, height=64, r0=r0)
            + MM.ncd_leaf_lines(deadzone=CHASE_DEADZONE, max_tries=NEWCHASEDIR_MAX_TRIES)
            + MM.walk_leaf_lines(max_tries=NEWCHASEDIR_MAX_TRIES)
            + MM.chase_leaf_lines() + MD.decide_leaves(justhit=True, bruiser=True) + MS.near_los_lines(w))
    code = (["mt_tic_leaf:"] + MC.p32a_tic_lines(schema, n, slots, exit_guard=False, nib=w.sec_nibbles)
            + ["    stl.fret mt_tret"]
            + MC.p32a_leaves() + MC.p32b_rj_leaf(secs, len(w.secs), w.sec_nibbles) + move + seed)
    text = "\n".join(code + [cells] + tables) + "\n"
    if mut:
        old, new = TIC_MUTANTS[mut]
        assert text.count(old) >= 1, (mut, text.count(old))
        text = text.replace(old, new)
    body = ["stl.startup_and_init_all"]
    for x16, y16, seen in script:
        body += ["hex.set 8, viewx, %d" % x16, "hex.set 8, viewy, %d" % y16,
                 "hex.set %d, thseen, %d" % (n, sum(1 << (4 * m) for m in seen)),
                 "stl.fcall mt_tic_leaf, mt_tret"]
        for m in range(n):
            body += ["hex.print_as_digit 2, mon_state + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_tics + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_facing + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_target + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_reaction + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_threshold + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_movedir + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_movecount + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 2, mon_rng + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_justattacked + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_justhit + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_solid + %d*dw, 0" % m,
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 4),
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 12),
                     "hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m),
                     "hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * m)]
        body += ["hex.print_as_digit 2, sched_cursor, 0", "hex.zero %d, dreq" % (2 * len(w.door_order)),
                 "stl.output 10"]
    body += ["stl.loop"]
    prog = "\n".join(body + decls + [text]) + "\n"
    return prog, _tic_expected(script)


def test_the_tic_script_exercises_the_baron():
    """the model's events over the script: the Barons decide melee and missile, run A_FaceTarget and A_BruisAttack,
    move (at radius 24), and the dying one reaches A_Fall and S_BOSS_DIE7"""
    script = _tic_script()
    w = _tic_world()
    dec, acts, moves = set(), set(), 0
    face_kept = 0
    for fr in script:
        _tic_set(w, *fr)
        before = list(w.ws.mon_facing[:3])
        ev = TicEvents(0)
        w._monsters_phase(ev)
        dec |= {k for _, k in ev.decisions}
        acts |= {a for _, a in ev.attacks}
        moves += ev.tries
        face_kept += sum(1 for m_, a in ev.attacks if a == "A_BruisAttack"
                         and w.ws.mon_facing[m_] == before[m_])
    assert dec == {"melee", "missile"}, dec
    assert acts == {"A_BruisAttack"}, acts                  # (A_FaceTarget is no _monster_attack)
    assert moves >= 50 and face_kept >= 1
    assert gd.THING_STATE_NAMES[w.ws.mon_state[3]] == "S_BOSS_DIE7" and not w.ws.mon_solid[3]


def _tic_run(tmp_path, name, mut=None) -> bool:
    prog, want = _tic_build(tmp_path, name, mut)
    return _run_prog(tmp_path, name, prog, want)


@pytest.mark.slow                    # ~4.5 min an assembly (E1M8's monster cells): docs/episode-plan.md G9
def test_the_baron_decide_tic_follows_the_model(tmp_path):
    assert _tic_run(tmp_path, "btic"), "the fj tic of E1M8's Barons parted from the model's decide mode"


@pytest.mark.slow
@pytest.mark.parametrize("mut", sorted(TIC_MUTANTS))
def test_control_a_broken_baron_tic_is_caught(tmp_path, mut):
    assert not _tic_run(tmp_path, "btic_" + mut, mut), "%s passed: the comparison is vacuous" % mut
