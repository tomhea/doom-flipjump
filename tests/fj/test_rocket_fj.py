"""P9 (the owner, 2026-10-10: THE ROCKET LAUNCHER) -- the player's rocket on the real flipjump engine, the very text the
emitter splices (projcode `rockets`, barrelcode `rockets`, monstersight `dyn`), against the model's combat P9 rules
(World(monsters="final", player="final"): `_spawn_rocket`, `_projectiles_phase`, `_missile_try` -> `_rocket_things`,
`_explode` -> `_rocket_blast`).

A. THE FLIGHT (rk_spawn, rk_spawn_leaf, pj_try's lines through the REAL missile cells, pj_explode's rocket branch,
   pool_tic through S_ROCKET and S_EXPLODE1..3, the leaf lists): one record a frame -- the player somewhere (a monster
   spawn point, or point blank against a wall), a view angle, the doors' / lifts' / switch's states, maybe a FIRE (one
   rocket: its spawn), then the pool's phase. Nothing shootable stands anywhere (every monster neither solid nor
   shootable, every barrel removed: the things are B's), so a rocket flies until a WALL stops it; the blast is a stub
   that prints the spot (C is the blast). Per frame: every slot's cells (active, x, y, momentum, state, tics, src, z),
   its runtime row, rng_fx; every 8th frame every leaf's list. The point location is a stub (the model's leaf, as the
   fireball harness's); `kb_pz` a stub reading the model's player z.
   R9: momentum x10 (the fireball's), no half step, the rocket named a monster's fireball (pw_src 1), the explosion's
   tics one short, its tics roll not drawn, its z without the +32, the explosion the fireball's, the HIGHEST free slot.
B. THE THINGS (pj_try's rocket branch -> pt_lines(rockets) -> pt_thing): poked records as the fireball harness's fight
   section -- a rocket at a 16.16 spot, monsters at the box's edge (alive, dying, fallen; imps among them), barrels
   standing / exploding / removed, the PLAYER right there (alive: the rocket passes him), the lines a poke. The damage
   leaf is a stub printing each call and the thrust's source flag (kb_sp: the player, for the chainsaw's exception).
   R9: the species rule applied to the rocket, the fireball's damage, the player tested (hit), kb_sp not set.
C. THE BLAST (rk_blast -> bl_leaf(rockets) -> bl_dist / bl_mon<r> -> bl_los' DYNAMIC path; the barrels' loop): a
   rocket at a spot with the player, monsters and barrels around it at the blast's edges; the damage leaves (dp_go,
   dmg<m>, bdm<c>) are stubs that print each call with the thrust's interface (kb_on, kb_sp, kb_ix, kb_iy, kb_iz), and
   the far LOS (`sl_far`, exact by tests/fj/test_far_los_fj.py) a stub that prints its two ends -- P the spot, Q the
   target FLOORED -- and reads a verdict the model's los_points drew (a call the fj makes that the model did not, or the
   other way, misaligns every verdict after it). Then the pool window's thing and leaf (kept across the blast).
   R9: the static LOS path (bl_dyn not set), Q unfloored, the barrels at radius 20, an exploding barrel blasted, the
   source not the player, the z the barrel's table, the window lost.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import barrelcode as BC
from doomfj import gamedata as gd
from doomfj import knockcode as KC
from doomfj import monsterdecide as MD
from doomfj import monstersight as MS
from doomfj import projcode as PC
from doomfj.collision import COLLISION_STATE_DECLS, point_location_decls
from doomfj.combat import BARREL_R, FIREBALL_R, ROCKET_INFO
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_trig_idioms_fj
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl
from doomfj.world import FIREBALL_POOL, FX_POOL, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
LIST_EVERY = 8


def _world():
    return World(monsters="final", player="final", sight_rule="seen")


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _sidx(s):
    return gd.STATE_INDEX[s]


def _quiet(w):
    """nothing shootable or solid: every monster neither (still in the leaf lists), every barrel removed"""
    ws = w.ws
    for j in range(w.layout.nmon):
        ws.mon_solid[j] = ws.mon_shootable[j] = 0
        ws.mon_health[j] = 0
    for b in range(len(w.barrel_things)):
        ws.bar_state[b] = ws.bar_tics[b] = ws.bar_health[b] = ws.bar_solid[b] = 0


# ================================================================================================ A. THE FLIGHT
FRAMES = 600


def _wall_spot(w, rnd):
    """a point blank spawn: from a monster spawn point along an axis to the first wall a missile meets, then back
    3..14 units -- the spawn's half step (10) and the box (6) reach the wall, or nearly -- facing it"""
    for _ in range(400):
        m = rnd.randrange(w.layout.nmon)
        x, y = w.ws.mon_x[m], w.ws.mon_y[m]
        ang, (dx, dy) = rnd.choice(((0, (1, 0)), (0x40000000, (0, 1)), (0x80000000, (-1, 0)), (0xC0000000, (0, -1))))
        for d in range(0, 400):
            if w.missile_lines_block((x + d * dx) << 16, (y + d * dy) << 16):
                k = d - rnd.randint(3, 14)
                if k > 0:
                    return ((x + k * dx) << 16, (y + k * dy) << 16, ang)
                break
    raise AssertionError("no point blank spot")


def _ascript(w):
    """[(px16, py16, angle, door states, lift states, fswitch, fire, z, dump lists)]"""
    rnd = random.Random(0x50CE7)
    n = w.layout.nmon
    spots = [(w.ws.mon_x[m], w.ws.mon_y[m]) for m in range(n)]
    out = []
    burst = 0
    for f in range(FRAMES):
        if f % 90 == 0:
            burst = 12                                     # a volley: the pool fills, a rocket fizzles
        kind = rnd.random()
        if kind < 0.15:
            px, py, ang = _wall_spot(w, rnd)
            px |= rnd.randrange(1 << 16)
        else:
            sx, sy = rnd.choice(spots)
            px = ((sx << 16) + rnd.randint(-(4 << 16), 4 << 16)) & M32
            py = ((sy << 16) + rnd.randint(-(4 << 16), 4 << 16)) & M32
            ang = rnd.choice((0, 0x40000000, 0x80000000, 0xC0000000, rnd.randrange(1 << 32), rnd.randrange(1 << 32)))
        fire = burst > 0 or kind < 0.15 or rnd.random() < 0.06
        burst = max(0, burst - 1)
        dstates = [rnd.randrange(w.door_nstates[si]) for si in w.door_order]
        lstates = [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]
        out.append((px & M32, py & M32, ang, dstates, lstates, rnd.randrange(2), int(fire),
                    rnd.randint(-200, 200), f % LIST_EVERY == LIST_EVERY - 1 or f == FRAMES - 1))
    return out


def _arow(w):
    ws = w.ws
    s = ""
    for k in range(FIREBALL_POOL):
        s += "%x%08x%08x%08x%08x%02x%x%02x%04x" % (ws.proj_active[k], ws.proj_x[k] & M32, ws.proj_y[k] & M32,
                                                   ws.proj_momx[k] & M32, ws.proj_momy[k] & M32, ws.proj_state[k],
                                                   ws.proj_tics[k], 0, ws.proj_z[k] & 0xFFFF)
        s += "%08x%08x%03x" % (ws.proj_y[k] & M32 & ~0xFFFF, ws.proj_x[k] & M32 & ~0xFFFF, ws.proj_leaf[k])
    return s + "%02x" % ws.rng_fx


def _lists(w):
    return "".join("%03x:%s" % (leaf, ",".join("%02x" % k for k in ks)) for leaf, ks in sorted(w.leaf_lists().items()))


def _ahooks(w, log, feed):
    """the point location the fj makes logs its query and feeds the model's leaf (the spawn's own try at the spawn
    position locates nothing in the fj: skipped); the blast logs its spot; kb_pz's z comes from the record"""
    orig_leaf, orig_try, orig_spawn = w._leaf16, w._missile_try, w._spawn_rocket
    st = {"spawn": False, "skip": False, "z": 0}

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

    def spawn(ev):
        st["spawn"] = True
        try:
            orig_spawn(ev)
        finally:
            st["spawn"] = False
    w._leaf16, w._missile_try, w._spawn_rocket = leaf16, mtry, spawn
    w._rocket_blast = lambda s, ev: log.append("B%04x%04x" % ((w.ws.proj_x[s] >> 16) & 0xFFFF,
                                                             (w.ws.proj_y[s] >> 16) & 0xFFFF))
    w._knock_z = lambda thing: st["z"]
    return st


def _amodel(script):
    w = _world()
    _quiet(w)
    log, feed = [], []
    st = _ahooks(w, log, feed)
    ws = w.ws
    lines, stats = [], {"spawns": 0, "fizzles": 0, "blasts": 0, "booms_at_spawn": 0, "removals": 0}
    for rec in script:
        px16, py16, ang, dstates, lstates, fsw, fire, z, lists = rec
        ds = list(dstates) + [0] * (len(dstates) & 1)
        ls = list(lstates) + [0] * (len(lstates) & 1)
        feed.append(bytes([0xD0]) + struct.pack("<III", px16, py16, ang)
                    + bytes(ds[2 * i] | ds[2 * i + 1] << 4 for i in range(len(ds) // 2))
                    + bytes(ls[2 * i] | ls[2 * i + 1] << 4 for i in range(len(ls) // 2)) + bytes([fsw, fire]))
        ws.px, ws.py, ws.pangle = _s32(px16), _s32(py16), ang
        for d, v in enumerate(dstates):
            ws.d_state[d] = v
        for k, v in enumerate(lstates):
            ws.l_state[k] = v
        ws.f_switch = fsw
        w._door_phase_scene()
        ev = TicEvents(0)
        act = list(ws.proj_active)
        if fire:
            st["z"] = z
            if not all(ws.proj_active):
                feed.append(struct.pack("<H", z & 0xFFFF))
            w._spawn_rocket(ev)
            stats["booms_at_spawn"] += sum(1 for s in ev.rocket_spawns if s >= 0 and not ws.proj_momx[s]
                                           and not ws.proj_momy[s])
        w._projectiles_phase(ev)
        stats["spawns"] += sum(1 for s in ev.rocket_spawns if s >= 0)
        stats["fizzles"] += ev.rocket_spawns.count(-1)
        stats["removals"] += sum(1 for s in range(FIREBALL_POOL) if act[s] and not ws.proj_active[s])
        feed.append(bytes([int(lists)]))
        stats["blasts"] += sum(1 for ln in log if ln[0] == "B")
        lines.append("".join(log) + _arow(w))
        log.clear()
        if lists:
            lines.append(_lists(w))
    return ("\n".join(lines) + "\n").encode(), b"".join(feed) + bytes([0]), stats


def leaf_dump_lines(nleaf: int) -> list:
    """`ll_dump` (the fireball harness's): every leaf with a list, "lll:" then its runtime things"""
    return ["ll_dump:",
            "    hex.zero w/4, dl_i",
            "  dl_next:",
            "    hex.set w/4, ll_base, sshead",
            "    hex.ptr_index ll_p, ll_base, dl_i", "    hex.read_byte ll_v, ll_p",
            "    hex.if0 2, ll_v, dl_end",
            "    hex.print_as_digit 3, dl_i, 0", "    stl.output 58",
            "  dl_loop:",
            "    hex.dec 2, ll_v", "    hex.print_as_digit 2, ll_v, 0",
            "    hex.set w/4, ll_base, thnext", "    hex.zero w/4, ll_idx", "    hex.mov 2, ll_idx, ll_v",
            "    hex.ptr_index ll_p, ll_base, ll_idx", "    hex.read_byte ll_v, ll_p",
            "    hex.if0 2, ll_v, dl_end", "    stl.output 44", "    ;dl_loop",
            "  dl_end:",
            "    hex.inc w/4, dl_i",
            "    hex.set w/4, dl_n, %d" % nleaf,
            "    hex.cmp w/4, dl_i, dl_n, dl_next, dl_done, dl_done",
            "  dl_done:",
            "    stl.output 10", "    stl.fret dump_ret"]


def _sub(text, old, new, mut):
    assert text.count(old) == 1, (mut, old, text.count(old))
    return text.replace(old, new)


def _mul_lines(cell, fn):
    return "".join("%s\n" % ln for ln in fn(cell))


A_MUTANTS = {
    "speed10": lambda t: _sub(_sub(t, "    finesine.read_cos pw_mx, pw_idx\n" + _mul_lines("pw_mx", PC._times20),
                                   "    finesine.read_cos pw_mx, pw_idx\n" + _mul_lines("pw_mx", PC._times10),
                                   "speed10"),
                              "    finesine.read_sin pw_my, pw_idx\n" + _mul_lines("pw_my", PC._times20),
                              "    finesine.read_sin pw_my, pw_idx\n" + _mul_lines("pw_my", PC._times10), "speed10"),
    "nohalf": lambda t: _sub(_sub(t, "  rk_hx_p:\n    hex.add 8, pw_x, pw_c\n", "  rk_hx_p:\n", "nohalf"),
                             "  rk_hy_p:\n    hex.add 8, pw_y, pw_c\n", "  rk_hy_p:\n", "nohalf"),
    # the rocket named a fireball of monster 0 (pw_src 1): its death, its things, its source all the fireball's
    "src_fireball": lambda t: _sub(t, "    hex.zero 2, pw_src\n    stl.fcall kb_pz",
                                   "    hex.set 2, pw_src, 1\n    stl.fcall kb_pz", "src_fireball"),
    # the explosion's S_EXPLODE1 one tic short (its tics roll then runs on 7 - v)
    "boom_tics": lambda t: _sub(t, "    hex.set 1, pw_ti, %d\n    stl.fcall rk_blast" % gd.STATES["S_EXPLODE1"].tics,
                                "    hex.set 1, pw_ti, %d\n    stl.fcall rk_blast" % (gd.STATES["S_EXPLODE1"].tics - 1),
                                "boom_tics"),
    "noroll": lambda t: _sub(t, "    hex.set 1, pw_ti, 1\n    hex.inc 2, rng_fx\n", "    hex.set 1, pw_ti, 1\n",
                             "noroll"),
    "z_nobias": lambda t: _sub(t, "    hex.mov 4, pw_z, kb_pzv\n    hex.add_constant 4, pw_z, 32\n",
                               "    hex.mov 4, pw_z, kb_pzv\n", "z_nobias"),
    "fireball_death": lambda t: _sub(t, "    hex.if0 2, pw_src, rk_explode\n", "", "fireball_death"),
    "highest": lambda t: _sub(t, "".join("    hex.if0 1, pj_act + %d*dw, rk_sp%d\n" % (s, s)
                                         for s in range(FIREBALL_POOL)),
                              "".join("    hex.if0 1, pj_act + %d*dw, rk_sp%d\n" % (s, s)
                                      for s in reversed(range(FIREBALL_POOL))), "highest"),
}


def _pj_text(w, nt, ft=None):
    """projcode's pool text in the final modes (fight, knock, rockets), the missile cells' root R"""
    ft = ft or PC.fight_things(w, list(range(w.layout.nmon)))
    return ft, "\n".join(PC.pj_lines(nt=nt, root="R", knock=True, fight=ft, rockets=True)
                         + PC.pool_tic_lines(knock=True)) + "\n"


def _abuild(tmp_path, name, mut=None):
    w = _world()
    n, nleaf = w.layout.nmon, len(w.cmap.subsectors)
    nt = n
    nthings = nt + FIREBALL_POOL + FX_POOL
    script = _ascript(w)
    want, feed, _stats = _amodel(script)
    cells, root = PC.missile_cells_fj(w)
    ft, code = _pj_text(w, nt)
    code = code.replace("sim.check_cells R\n", "sim.check_cells %s\n" % root)
    if mut:
        code = A_MUTANTS[mut](code)
    head, nxt = [0] * nleaf, [0] * nthings
    for leaf, ks in w.leaf_lists().items():
        head[leaf] = ks[0] + 1
        for a, b in zip(ks, ks[1:] + [-1]):
            nxt[a] = b + 1
    ws = w.ws
    nd, nl, nb = len(w.door_order), len(w.lift_order), len(w.barrel_things)
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
                 "    hex.print_as_digit 4, pj_z + %d*dw, 0" % (4 * s),
                 "    hex.print_as_digit 16, thpos_rt + %d*dw, 0" % (16 * t),
                 "    hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * t)]
    dump += ["    hex.print_as_digit 2, rng_fx, 0", "    stl.output 10", "    stl.fret dump_ret"]
    body = ["stl.startup_and_init_all",
            "loop:",
            "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 4, viewangle",
            "hex.input %d, dstate" % ((nd + 1) // 2), "hex.input %d, lstate" % ((nl + 1) // 2),
            "hex.input 1, fswitch", "hex.input 1, wfire",
            "hex.if0 2, wfire, no_fire", "stl.fcall rk_spawn, rk_sret", "no_fire:",
            "stl.fcall pj_phase, pj_pret",
            "stl.fcall pj_dump, dump_ret",
            "hex.input 1, wlist", "hex.if0 2, wlist, loop",
            "stl.fcall ll_dump, dump_ret",
            ";loop",
            "done:", "stl.loop",
            "ptloc_walk:", "    stl.output 112", "    hex.print_as_digit 10, ptx, 0", "    hex.print_as_digit 10, pty, 0",
            "    hex.zero w/4, ptss", "    hex.input 2, ptss", "    stl.fret ptloc_ret",
            "kb_pz:", "    hex.input 2, kb_pzv", "    stl.fret kb_pzret",
            "rk_blast:", "    stl.output 66", "    hex.print_as_digit 4, pw_x + 4*dw, 0",
            "    hex.print_as_digit 4, pw_y + 4*dw, 0", "    stl.fret rk_bret",
            # never reached here (nothing shootable; no fireball spawned): the labels the pool text names
            "dp_go:", "    stl.fret dp_ret", "dm_go:", "    stl.fret dm_ret", "ia_leaf:", "    stl.fret ia_ret"]
    decls = (PC.pool_decls(values={"rng_fx": ws.rng_fx}) + PC.pt_decls(ft) + PC.ROCKET_DECLS + COLLISION_STATE_DECLS
             + point_location_decls() + LEAF_LINK_DECLS + KC.KB_INTERFACE + KC.persisted_decls(n)
             + ["pw_z: hex.vec 4", "kb_pzv: hex.vec 4", "kb_pzret: hex.vec w/4"]
             + [d for d in MD.FIGHT_DECLS if d.split(":")[0].startswith(("ia_", "mt_tq"))]
             + ["wmagic: hex.vec 2", "wlist: hex.vec 2", "wfire: hex.vec 2",
                "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8", "mm_x: hex.vec 4", "mm_y: hex.vec 4",
                "p_hp: hex.vec 3, 100", "p_dead: hex.vec 1", "lvdone: hex.vec 1", "dp_dmg: hex.vec 2",
                "dp_src: hex.vec 2", "md_src: hex.vec 2", "dp_ret: hex.vec w/4",
                "dm_id: hex.vec 2", "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2", "dm_ret: hex.vec w/4",
                "dump_ret: hex.vec w/4", "dl_i: hex.vec w/4", "dl_n: hex.vec w/4",
                "dstate: hex.vec %d" % (2 * ((nd + 1) // 2)), "lstate: hex.vec %d" % (2 * ((nl + 1) // 2)),
                "fswitch: hex.vec 2",
                "mon_solid: hex.vec %d" % n, "mon_shootable: hex.vec %d" % n,
                "bar_st: hex.vec %d" % (2 * nb), "bar_hp: hex.vec %d" % (2 * nb), "bar_solid: hex.vec %d" % nb,
                "thpos_rt: hex.vec %d, %d" % (16 * nthings, sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32)
                                                                 << 32) << (64 * m) for m in range(n))),
                "thss_rt: hex.vec %d, %d" % (16 * nthings, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * nthings)])
    tables = PC.tables_fj(rockets=True) + [generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry")]
    prog = "\n".join(body + decls + dump + leaf_dump_lines(nleaf) + [code, cells] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()], feed, want


def _arun(tmp_path, name, mut=None) -> bool:
    srcs, feed, want = _abuild(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, feed, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_flight_script_exercises_every_path():
    """the model's own run: rockets spawned and flying, a full pool fizzling a rocket, rockets exploding at their
    spawn (P_CheckMissileSpawn) and against walls, the explosion's states run out and the slot freed"""
    _want, _feed, stats = _amodel(_ascript(_world()))
    assert stats["spawns"] >= 60 and stats["fizzles"] >= 3 and stats["booms_at_spawn"] >= 5 \
        and stats["blasts"] >= 50 and stats["removals"] >= 50, stats


def test_the_rocket_flies_as_the_model(tmp_path):
    assert _arun(tmp_path, "rkfly"), "the fj rocket's flight parted from the model's"


@pytest.mark.parametrize("mut", sorted(A_MUTANTS))
def test_control_a_broken_flight_is_caught(tmp_path, mut):
    assert not _arun(tmp_path, "rkfly_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut


# ================================================================================================ B. THE THINGS
B_N = 500
BAR_ST = {"stand": (lambda: _sidx("S_BAR1"), 20, 1), "boom": (lambda: _sidx("S_BEXP"), 0, 1),
          "gone": (lambda: 0, 0, 0)}


def _brecords(w):
    rnd = random.Random(0x3B07)
    n = w.layout.nmon
    out = []
    for r in range(B_N):
        if rnd.random() < 0.25:
            bt = w.barrel_things[rnd.randrange(len(w.barrel_things))]
            cx, cy, B = bt.x, bt.y, BARREL_R + FIREBALL_R
        else:
            cx, cy = rnd.randint(-600, 3000), rnd.randint(-1000, 2200)
            B = rnd.choice((20, 30)) + FIREBALL_R
        k = rnd.choice((B - 1, B, B + 1, rnd.randint(0, B + 2)))
        fx, fy = rnd.choice((0, 0, rnd.randrange(1 << 16))), rnd.choice((0, rnd.randrange(1 << 16)))
        nx16 = (((cx + rnd.choice((k, -k, rnd.randint(-k, k)))) << 16) | fx) & M32
        ny16 = (((cy + rnd.choice((k, -k, rnd.randint(-k, k)))) << 16) | fy) & M32
        mons = {}
        pool = [j for j in range(n) if w.ws.mon_active[j]]
        for j in rnd.sample(pool, rnd.choice((0, 1, 2, 3, 5))):
            r_ = w.mon_radius[j] + FIREBALL_R
            kk = rnd.choice((r_ - 1, r_, r_ + 1, rnd.randint(0, r_ + 2)))
            x = (nx16 >> 16) + rnd.choice((kk, -kk, rnd.randint(-kk, kk)))
            y = (ny16 >> 16) + rnd.choice((kk, -kk, rnd.randint(-kk, kk)))
            stt = rnd.choice(("alive", "alive", "alive", "dying", "fallen"))
            mons[j] = (x, y, int(stt != "fallen"), int(stt == "alive"))
        bars = [rnd.choice(("stand", "stand", "boom", "gone")) for _ in w.barrel_things]
        # the player: alive, ON the rocket's path (within the fireball's box of it) most of the time -- a rocket passes
        p16 = ((nx16 + rnd.randint(-12 << 16, 12 << 16)) & M32, (ny16 + rnd.randint(-12 << 16, 12 << 16)) & M32)
        out.append(dict(nx16=nx16, ny16=ny16, mons=mons, bars=bars, p16=p16, lines=int(rnd.random() < 0.8),
                        rng=rnd.randrange(256)))
    return out


def _bapply(w, rec, log):
    ws, n = w.ws, w.layout.nmon
    for j in range(n):
        ws.mon_solid[j] = ws.mon_shootable[j] = ws.mon_health[j] = 0
        ws.mon_x[j], ws.mon_y[j] = -20000, -20000
    for j, (x, y, solid, alive) in rec["mons"].items():
        ws.mon_x[j], ws.mon_y[j], ws.mon_solid[j], ws.mon_shootable[j] = x, y, solid, alive
        ws.mon_health[j] = 30 if alive else -3
    for b, kind in enumerate(rec["bars"]):
        st, hp, solid = BAR_ST[kind]
        ws.bar_state[b], ws.bar_health[b], ws.bar_solid[b] = st(), hp, solid
    ws.p_dead, ws.p_health = 0, 100
    ws.px, ws.py = _s32(rec["p16"][0]), _s32(rec["p16"][1])
    ws.rng_fx = rec["rng"]
    s = 0
    ws.proj_src[s], ws.proj_active[s], ws.proj_state[s] = 0, 1, _sidx("S_ROCKET")
    w.missile_lines_block = lambda x16, y16, _ok=rec["lines"]: not _ok
    w.damage_player = lambda dmg, source, inflictor, ev: log.append("P%02x" % dmg)
    w.damage_monster = lambda j, dmg, source, inflictor, ev: log.append(
        "M%02x%02x3%02x%x" % (1 + j, dmg, w._source_code(source), int(w._source_is_player(source))))
    w.damage_barrel = lambda b, dmg, source, ev: log.append(
        "M%02x%02x3%02x%x" % (1 + n + b, dmg, w._source_code(source), int(w._source_is_player(source))))
    w._leaf16 = lambda x16, y16: 0
    w._list_remove = w._list_insert = lambda k, leaf: None
    ws.proj_leaf[s] = 0
    return w._missile_try(s, _s32(rec["nx16"]), _s32(rec["ny16"]), TicEvents(0))


def _window(r):
    return 0x44 + r % 10, (37 * r + 5) % 0x2C0


def _bexpected(w, records) -> bytes:
    lines = []
    for r, rec in enumerate(records):
        log = []
        ok = _bapply(w, rec, log)
        lines += log + ["%x%02x%02x%03x" % ((int(ok), w.ws.rng_fx) + _window(r))]
    return ("\n".join(lines) + "\n").encode()


B_MUTANTS = {
    "species": ("    hex.if1 1, pt_rk, pt_nsp\n", ""),
    "fireball_damage": ("    hex.if0 1, pt_rk, pt_dfb\n    rkdmg.lookup dm_dmg, rng_fx\n  pt_dfb:\n", ""),
    "hits_player": ("    hex.if0 2, pw_src, pj_tm\n", ""),
    "kb_sp": ("    hex.mov 1, kb_sp, pt_rk\n", ""),
}


def _bbuild(tmp_path, name, mut=None):
    w = _world()
    n, nb = w.layout.nmon, len(w.barrel_things)
    records = _brecords(w)
    want = _bexpected(w, records)
    ft, code = _pj_text(w, 0)
    a, b = code.index("pj_try:\n"), code.index("pj_explode:\n")
    unit = code[a:b]
    unit = _sub(unit, "    sim.check_cells R\n", "    hex.mov 1, cp_ok, cp_poke\n", "lines")
    if mut:
        unit = _sub(unit, *B_MUTANTS[mut], mut)
    body = ["stl.startup_and_init_all"]
    for r, rec in enumerate(records):
        body += ["hex.zero %d, mon_solid" % n, "hex.zero %d, mon_shootable" % n]
        for j, (x, y, solid, alive) in sorted(rec["mons"].items()):
            body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 4, x & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 12, y & 0xFFFF),
                     "hex.set 1, mon_solid + %d*dw, %d" % (j, solid), "hex.set 1, mon_shootable + %d*dw, %d" % (j, alive)]
        for bb, kind in enumerate(rec["bars"]):
            st, hp, solid = BAR_ST[kind]
            body += ["hex.set 2, bar_st + %d*dw, %d" % (2 * bb, st()), "hex.set 2, bar_hp + %d*dw, %d" % (2 * bb, hp),
                     "hex.set 1, bar_solid + %d*dw, %d" % (bb, solid)]
        body += ["hex.zero 1, p_dead", "hex.set 3, p_hp, 100",
                 "hex.set 8, viewx, %d" % rec["p16"][0], "hex.set 8, viewy, %d" % rec["p16"][1],
                 "hex.set 2, rng_fx, %d" % rec["rng"], "hex.zero 2, pw_src",
                 "hex.set 8, pw_nx, %d" % rec["nx16"], "hex.set 8, pw_ny, %d" % rec["ny16"],
                 "hex.set 1, cp_poke, %d" % rec["lines"],
                 "hex.set w/4, pw_t, %d" % _window(r)[0], "hex.set w/4, pw_leaf, %d" % _window(r)[1],
                 "stl.fcall pj_try, pj_tret",
                 "hex.print_as_digit 1, pw_ok, 0", "hex.print_as_digit 2, rng_fx, 0",
                 "hex.print_as_digit 2, pw_t, 0", "hex.print_as_digit 3, pw_leaf, 0", "stl.output 10"]
    body += ["stl.loop",
             "dp_go:", "    stl.output 80", "    hex.print_as_digit 2, dp_dmg, 0", "    stl.output 10",
             "    hex.zero 2, dp_src", "    stl.fret dp_ret",
             "dm_go:", "    stl.output 77", "    hex.print_as_digit 2, dm_id, 0", "    hex.print_as_digit 2, dm_dmg, 0",
             "    hex.print_as_digit 1, dm_melee, 0", "    hex.print_as_digit 2, dm_src, 0",
             "    hex.print_as_digit 1, kb_sp, 0", "    stl.output 10",
             "    hex.zero 2, dm_src", "    hex.zero 1, kb_on",
             "    hex.not w/4, pw_t", "    hex.not w/4, pw_leaf",          # the drop link writes the window (kept)
             "    stl.fret dm_ret"]
    decls = (PC.pool_decls() + PC.pt_decls(ft) + PC.ROCKET_DECLS + KC.KB_INTERFACE
             + ["pw_z: hex.vec 4",
                "viewx: hex.vec 8", "viewy: hex.vec 8", "p_hp: hex.vec 3", "p_dead: hex.vec 1",
                "dp_dmg: hex.vec 2", "dp_src: hex.vec 2", "dp_ret: hex.vec w/4",
                "dm_id: hex.vec 2", "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2", "dm_ret: hex.vec w/4",
                "cp_ok: hex.vec 1", "cp_poke: hex.vec 1", "cpx: hex.vec 8", "cpy: hex.vec 8", "cprad: hex.vec 8",
                "mon_solid: hex.vec %d" % n, "mon_shootable: hex.vec %d" % n, "thpos_rt: hex.vec %d" % (16 * n),
                "bar_st: hex.vec %d" % (2 * nb), "bar_hp: hex.vec %d" % (2 * nb), "bar_solid: hex.vec %d" % nb])
    prog = "\n".join(body + decls + [unit] + PC.tables_fj(rockets=True)) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()], want


def _brun(tmp_path, name, mut=None) -> bool:
    srcs, want = _bbuild(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_thing_records_exercise_every_thing():
    """the model's own outcomes: monsters (imps among them) and barrels hit by the rocket's 20s, solid corpses and
    exploding barrels stopping it, the player passed (inside the box), the lines refusing, clear passes"""
    w = _world()
    seen = {"mon": 0, "imp": 0, "bar": 0, "corpse": 0, "player_in_box": 0, "pass": 0, "lines": 0}
    for rec in _brecords(w):
        log = []
        hits = []
        orig = w._rocket_things
        w._rocket_things = lambda s, nx, ny, ev, _o=orig: (_o(s, nx, ny, ev), hits.extend(ev.rocket_hits))[0]
        ok = _bapply(w, rec, log)
        w._rocket_things = orig
        for kind, j, _d in hits:
            seen[kind] += 1
            seen["imp"] += kind == "mon" and w.mon_things[j].type == 3001
        bd = (FIREBALL_R + 16) << 16
        seen["player_in_box"] += (abs(_s32(rec["p16"][0]) - _s32(rec["nx16"])) < bd
                                  and abs(_s32(rec["p16"][1]) - _s32(rec["ny16"])) < bd)
        seen["pass"] += bool(ok)
        seen["lines"] += (not ok) and not hits
        assert not any(ln[0] == "P" for ln in log), "the rocket hit its shooter"
    want = {"mon": 40, "imp": 8, "bar": 8, "corpse": 15, "player_in_box": 300, "pass": 100, "lines": 20}
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_rocket_meets_things_as_the_model(tmp_path):
    assert _brun(tmp_path, "rkthings"), "the fj rocket's things parted from the model's _rocket_things"


@pytest.mark.parametrize("mut", sorted(B_MUTANTS))
def test_control_a_broken_rocket_thing_test_is_caught(tmp_path, mut):
    assert not _brun(tmp_path, "rkthings_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut


# ================================================================================================ C. THE BLAST
C_N = 300


def _crecords(w):
    rnd = random.Random(0xB1A57)
    n, nb = w.layout.nmon, len(w.barrel_things)
    out = []
    for r in range(C_N):
        if rnd.random() < 0.4:                               # beside a barrel or two
            bt = w.barrel_things[rnd.randrange(nb)]
            cx, cy = bt.x + rnd.randint(-150, 150), bt.y + rnd.randint(-150, 150)
        else:
            m = rnd.randrange(n)
            cx, cy = w.ws.mon_x[m] + rnd.randint(-100, 100), w.ws.mon_y[m] + rnd.randint(-100, 100)
        x16 = ((cx << 16) | rnd.randrange(1 << 16)) & M32
        y16 = ((cy << 16) | rnd.randrange(1 << 16)) & M32
        mons = {}
        for j in rnd.sample(range(n), rnd.choice((0, 1, 2, 4))):
            e = rnd.choice((127, 128, 129, 140, 150, 157, 158, 159, rnd.randint(0, 170)))
            x = cx + rnd.choice((e, -e, rnd.randint(-e, e)))
            y = cy + rnd.choice((e, -e, rnd.randint(-e, e)))
            mons[j] = (x, y, rnd.choice((1, 1, 1, 0)), rnd.choice((60, 60, 1, 0)), rnd.choice((1, 1, 0)))
        bars = [rnd.choice(("stand", "stand", "stand", "boom", "gone", "low")) for _ in range(nb)]
        e = rnd.choice((127, 143, 144, 145, rnd.randint(0, 160)))
        p16 = ((((cx + rnd.choice((e, -e, rnd.randint(-e, e)))) << 16) | rnd.randrange(1 << 16)) & M32,
               (((cy + rnd.choice((e, -e, rnd.randint(-e, e)))) << 16) | rnd.randrange(1 << 16)) & M32)
        out.append(dict(x16=x16, y16=y16, z=rnd.randint(-200, 300), mons=mons, bars=bars, p16=p16,
                        pdead=int(rnd.random() < 0.1), seed=rnd.randrange(1 << 30)))
    return out


C_BAR = {"stand": (lambda: _sidx("S_BAR1"), 20), "low": (lambda: _sidx("S_BAR2"), 1),
         "boom": (lambda: _sidx("S_BEXP"), 0), "gone": (lambda: 0, 0)}


def _capply(w, rec, log, feed):
    ws, n = w.ws, w.layout.nmon
    for j in range(n):
        ws.mon_active[j] = ws.mon_shootable[j] = ws.mon_health[j] = 0
    for j, (x, y, act, hp, shoot) in rec["mons"].items():
        ws.mon_x[j], ws.mon_y[j], ws.mon_active[j], ws.mon_health[j], ws.mon_shootable[j] = x, y, act, hp, shoot
    for b, kind in enumerate(rec["bars"]):
        st, hp = C_BAR[kind]
        ws.bar_state[b], ws.bar_health[b] = st(), hp
    ws.px, ws.py, ws.p_dead = _s32(rec["p16"][0]), _s32(rec["p16"][1]), rec["pdead"]
    ws.p_health = 0 if rec["pdead"] else 100
    s = 0
    ws.proj_x[s], ws.proj_y[s], ws.proj_z[s] = _s32(rec["x16"]), _s32(rec["y16"]), rec["z"]
    rnd = random.Random(rec["seed"])

    def los(p, q):
        v = int(rnd.random() < 0.75)
        log.append("L%08x%08x%08x%08x" % (q[0] & M32, q[1] & M32, p[0] & M32, p[1] & M32))   # the spot, the target
        feed.append(bytes([v]))
        return bool(v)
    w.los_points = los

    def kb(source, inflictor):
        ix, iy = w._inflictor_xy(inflictor)
        return "%x%x%04x%04x%04x" % (1, int(w._source_is_player(source)), (ix >> 16) & 0xFFFF, (iy >> 16) & 0xFFFF,
                                     w._knock_z(inflictor) & 0xFFFF)
    w.damage_player = lambda dmg, source, inflictor, ev: log.append(
        "P%02x%02x" % (dmg, source[1] + 1 if source[0] == "mon" else 0) + kb(source, inflictor))
    w.damage_monster = lambda m, dmg, source, inflictor, ev: log.append(
        "M%02x%02x2%02x" % (m, dmg, w._source_code(source)) + kb(source, inflictor))
    w.damage_barrel = lambda c, dmg, source, ev: log.append("D%02x%02x%02x" % (c, dmg, w._source_code(source)))
    w._rocket_blast(s, TicEvents(0))


def _cmodel(w, records):
    lines, feed = [], []
    for r, rec in enumerate(records):
        log = []
        _capply(w, rec, log, feed)
        lines += log + ["%02x%03x" % _window(r)]
    return ("\n".join(lines) + "\n").encode(), b"".join(feed)


C_MUTANTS = {
    "static_los": ("    hex.set 1, bl_dyn, 1\n", ""),
    "unfloored": ("    hex.zero 4, mt_tqx\n    hex.mov 4, mt_tqx + 4*dw, bl_qx + 4*dw\n",
                  "    hex.mov 8, mt_tqx, bl_qx\n"),
    "barrel_r20": None,
    "boom_blasted": None,
    "src_none": ("    hex.set 2, bl_src, 1\n", "    hex.zero 2, bl_src\n"),
    "z_table": ("    hex.mov 4, bl_z, pw_z\n", ""),
    "window_lost": ("    hex.mov w/4, pw_leaf, rk_svl\n", ""),
}


def _cbuild(tmp_path, name, mut=None):
    w = _world()
    n, nb = w.layout.nmon, len(w.barrel_things)
    records = _crecords(w)
    want, feed = _cmodel(w, records)
    slot_rt = list(range(n))
    spots = [(t.x, t.y) for t in w.barrel_things]
    maxr = max([16] + list(w.mon_radius[:n]))
    los = "\n".join(MS.blast_los_lines(w, spots, maxr, fight=True, dyn=True)) + "\n"
    a = los.index("  bl_lst:\n")
    # the dynamic path is the real text; the static path (the barrels' own lists) prints 'S' -- a rocket never takes it
    los = los[:a] + "  bl_lst:\n    stl.output 83\n    stl.output 10\n    ;bl_ldone\nbl_ldone:\n    stl.fret bl_lret\n"
    text = "\n".join(BC.blast_lines(w, slot_rt=slot_rt, knock=True, fight=True, rockets=True)
                     + PC.rocket_blast_lines(w)) + "\n" + los
    if mut == "barrel_r20":
        old = "    stl.fcall bl_mon%d, blm_ret\n" % BARREL_R
        assert text.count(old) == nb
        text = text.replace(old, "    stl.fcall bl_mon20, blm_ret\n")
    elif mut == "boom_blasted":                     # barrel 0 is blasted whatever its health
        old = "    hex.if_flags bar_hp + 1*dw, 0xFF00, rk_b0_p, rk_b0_n\n  rk_b0_p:\n    hex.if0 2, bar_hp + 0*dw, rk_b0_n\n"
        text = _sub(text, old, "  rk_b0_p:\n", mut)
    elif mut:
        text = _sub(text, *C_MUTANTS[mut], mut)
    stubs = ["sl_far:", "    stl.output 76",
             "    hex.zero 4, lt_p", "    hex.mov 4, lt_p + 4*dw, mm_x", "    hex.print_as_digit 8, lt_p, 0",
             "    hex.zero 4, lt_p", "    hex.mov 4, lt_p + 4*dw, mm_y", "    hex.print_as_digit 8, lt_p, 0",
             "    hex.print_as_digit 8, mt_tqx, 0", "    hex.print_as_digit 8, mt_tqy, 0",
             "    stl.output 10", "    hex.input 1, lt_v", "    hex.mov 1, sl_hit, lt_v", "    hex.xor_by sl_hit, 1",
             "    stl.fret sf_ret",
             "dp_go:", "    stl.output 80", "    hex.print_as_digit 2, dp_dmg, 0", "    hex.print_as_digit 2, dp_src, 0",
             *["    hex.print_as_digit %d, %s, 0" % (k, c) for c, k in
               (("kb_on", 1), ("kb_sp", 1), ("kb_ix", 4), ("kb_iy", 4), ("kb_iz", 4))],
             "    stl.output 10", "    hex.zero 2, dp_src", "    hex.zero 1, kb_on", "    stl.fret dp_ret"]
    for m in range(n):
        stubs += ["dmg%d:" % m, "    stl.output 77", "    hex.set 2, pr_m, %d" % m, "    hex.print_as_digit 2, pr_m, 0",
                  "    hex.print_as_digit 2, dm_dmg, 0", "    hex.print_as_digit 1, dm_melee, 0",
                  "    hex.print_as_digit 2, dm_src, 0",
                  *["    hex.print_as_digit %d, %s, 0" % (k, c) for c, k in
                    (("kb_on", 1), ("kb_sp", 1), ("kb_ix", 4), ("kb_iy", 4), ("kb_iz", 4))],
                  "    stl.output 10", "    hex.zero 2, dm_src", "    hex.zero 1, kb_on",
                  "    hex.not w/4, pw_t", "    hex.not w/4, pw_leaf",          # a kill's drop link (kept: rk_blast)
                  "    stl.fret dm_ret"]
    for c in range(nb):
        stubs += ["bdm%d:" % c, "    stl.output 68", "    hex.set 2, pr_m, %d" % c, "    hex.print_as_digit 2, pr_m, 0",
                  "    hex.print_as_digit 2, bw_dmg, 0", "    hex.print_as_digit 2, bd_src, 0", "    stl.output 10",
                  "    stl.fret bdm_ret"]
    body = ["stl.startup_and_init_all"]
    for r, rec in enumerate(records):
        body += ["hex.zero %d, mon_active" % n, "hex.zero %d, mon_shootable" % n, "hex.zero %d, mon_health" % (3 * n)]
        for j, (x, y, act, hp, shoot) in sorted(rec["mons"].items()):
            body += ["hex.set 1, mon_active + %d*dw, %d" % (j, act), "hex.set 1, mon_shootable + %d*dw, %d" % (j, shoot),
                     "hex.set 3, mon_health + %d*dw, %d" % (3 * j, hp),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 4, x & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 12, y & 0xFFFF)]
        for c, kind in enumerate(rec["bars"]):
            st, hp = C_BAR[kind]
            body += ["hex.set 2, bar_st + %d*dw, %d" % (2 * c, st()), "hex.set 2, bar_hp + %d*dw, %d" % (2 * c, hp)]
        body += ["hex.set 1, p_dead, %d" % rec["pdead"], "hex.set 3, p_hp, %d" % (0 if rec["pdead"] else 100),
                 "hex.set 8, viewx, %d" % rec["p16"][0], "hex.set 8, viewy, %d" % rec["p16"][1],
                 "hex.set 8, pw_x, %d" % rec["x16"], "hex.set 8, pw_y, %d" % rec["y16"],
                 "hex.set 4, pw_z, %d" % (rec["z"] & 0xFFFF),
                 "hex.set w/4, pw_t, %d" % _window(r)[0], "hex.set w/4, pw_leaf, %d" % _window(r)[1],
                 "stl.fcall rk_blast, rk_bret",
                 "hex.print_as_digit 2, pw_t, 0", "hex.print_as_digit 3, pw_leaf, 0", "stl.output 10"]
    body += ["stl.loop"]
    decls = (BC.decls(w, gd.SK_HARD) + BC.fight_decls(w) + ["bl_dyn: hex.vec 1", "bl_z: hex.vec 4"]
             + PC.WINDOW_DECLS + PC.ROCKET_DECLS + KC.KB_INTERFACE + ["pw_z: hex.vec 4"]
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "p_hp: hex.vec 3", "p_dead: hex.vec 1",
                "dp_dmg: hex.vec 2", "dp_src: hex.vec 2", "dp_ret: hex.vec w/4", "sl_hit: hex.vec 1",
                "sf_ret: hex.vec w/4", "lt_p: hex.vec 8", "lt_v: hex.vec 2", "pr_m: hex.vec 2",
                "mt_tqx: hex.vec 8", "mt_tqy: hex.vec 8",
                "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2", "dm_ret: hex.vec w/4",
                "mm_x: hex.vec 4", "mm_y: hex.vec 4", "bar_solid: hex.vec %d" % nb,
                "mon_active: hex.vec %d" % n, "mon_shootable: hex.vec %d" % n,
                "mon_health: hex.vec %d" % (3 * n), "thpos_rt: hex.vec %d" % (16 * n)])
    prog = "\n".join(body + decls + [text] + stubs + KC.tables_fj(w)) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()], feed, want


def _crun(tmp_path, name, mut=None) -> bool:
    srcs, feed, want = _cbuild(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, feed, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_blast_records_exercise_every_target():
    """the model's own blasts: the player hurt (self-damage) and missed (out of range, dead, no sight), monsters hurt
    at the radius' edge and spared, barrels hurt (standing) and skipped (exploding, removed), LOS asked and refused"""
    w = _world()
    seen = {"player": 0, "mon": 0, "bar": 0, "los": 0, "los_no": 0, "edge": 0}
    for rec in _crecords(w):
        log, feed = [], []
        _capply(w, rec, log, feed)
        seen["player"] += sum(1 for ln in log if ln[0] == "P")
        seen["mon"] += sum(1 for ln in log if ln[0] == "M")
        seen["bar"] += sum(1 for ln in log if ln[0] == "D")
        seen["los"] += len(feed)
        seen["los_no"] += sum(1 for v in feed if v == b"\x00")
        seen["edge"] += sum(1 for ln in log if ln[0] in "MD" and int(ln[3:5], 16) <= 2)
    want = {"player": 40, "mon": 60, "bar": 60, "los": 300, "los_no": 60, "edge": 5}
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_rocket_blast_is_the_model(tmp_path):
    assert _crun(tmp_path, "rkblast"), "the fj rocket blast parted from the model's _rocket_blast"


@pytest.mark.parametrize("mut", sorted(C_MUTANTS))
def test_control_a_broken_rocket_blast_is_caught(tmp_path, mut):
    assert not _crun(tmp_path, "rkblast_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut


def test_the_rocket_parts_are_the_finals_only():
    """the rocket needs the final modes' things and z: projcode refuses it without them; the text with rockets off is
    the pool's as before (no rk_ label), and the rocket's state chain is its own pool's tail"""
    w = _world()
    with pytest.raises(AssertionError):
        PC.pj_lines(nt=0, root="R", rockets=True)
    ft = PC.fight_things(w, list(range(w.layout.nmon)))
    off = "\n".join(PC.pj_lines(nt=0, root="R", knock=True, fight=ft))
    assert "rk_" not in off and "pt_rk" not in off
    assert PC.pool_states(True, True)[-4:] == ["S_ROCKET", "S_EXPLODE1", "S_EXPLODE2", "S_EXPLODE3"]
    assert ROCKET_INFO.spawnstate == "S_ROCKET" and ROCKET_INFO.deathstate == "S_EXPLODE1"
