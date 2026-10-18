"""M8 C6 (the PLASMA RIFLE, E1M6 / E1M9) on the real flipjump engine -- the very text the emitter splices (projcode
`plasma`, weaponcode `plasma`, lootcode `plasma`, wall_renderer.standalone_key_lines `plasma`) against the model
(World on tests/fixtures/plasma_wad.py's E1M1 with a rifle; doomfj.combat's M8 C6 conventions):

A. THE FLIGHT (pl_spawn, pl_spawn_leaf, pj_try through the REAL missile cells, pj_explode's pm_explode -> pl_explode,
   pool_tic through S_PLASBALL / S_PLASBALL2 / S_PLASEXP..5, the leaf lists) -- the rocket harness's records
   (tests/fj/test_rocket_fj.py A) with each fire a ROCKET or a PLASMA BALL, so the two share the pool and every path
   that tells them apart (the flight state's high nibble) runs both ways. R9: momentum x20 (the rocket's), no half
   step, the tics roll not drawn, the ball exploding as a rocket (blast and all), the explosion one tic short, the
   rocket exploding as a ball, the HIGHEST free slot.
B. THE THINGS (pj_try -> pt_lines(rockets, plasma) -> pt_thing): poked records as the rocket harness's B, the slot
   holding a ball (either flight state) or a rocket; the damage leaf a stub printing each call. R9: the ball hitting
   with the rocket's table, the discriminator inverted, the species rule applied to the ball.
C. THE WEAPON (weaponcode.weapon_lines(plasma=True), the "fire" mode): key 6, the rifle's psprites, A_FirePlasma (one
   cell, the flash by `plfl` on the player's stream), refire every 3 tics, the 20-tic S_PLASMA2 / S_PLASMA2B, the
   cells running dry, P_CheckAmmo's preference with the rifle first, the bar's cells and ARMS 6 -- tic by tic against
   World(player="fire"). R9: key 6 dead, the flash not drawn, the cell not spent, the rifle out of the preference.
D. THE GIVES (lootcode.give_lines(2004 / 2047 / 17), give_ammo_lines(plasma=True)) against combat._touch. R9: the
   rifle not brought up, one clip of cells, the cells' switch to the rifle gone.
E. KEY 6 (wall_renderer.standalone_key_lines(plasma=True): kb.poll and `w6_key_lines` after each poll, kb_now's 14th
   nibble) against keyboard.frame_keys(binding=BINDING_PLASMA). R9: the up edge not clearing kb_w6, the latch not set,
   the latch's 14th nibble never zeroed.
F. THE COST of an active plasma ball: pj_phase with the REAL point location, missile cells and things, ops per tic of
   flight (measured, printed; asserted only finite and above the empty pool's).
"""
import random
import re
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj import keyboard as KB
from doomfj import knockcode as KC
from doomfj import lootcode as L
from doomfj import hurtcode as H
from doomfj import monsterdecide as MD
from doomfj import projcode as PC
from doomfj import weaponcode as WC
from doomfj.collision import COLLISION_STATE_DECLS, generate_point_location_fj, point_location_decls
from doomfj.combat import BARREL_R, FIREBALL_R
from doomfj.config import GAME_CFG, Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_trig_idioms_fj
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl
from doomfj.wall_renderer import STANDALONE_POLLS, standalone_key_lines
from doomfj.wireformat import keys_byte
from doomfj.world import FIREBALL_POOL, FX_POOL, KEYS, TicEvents, World
from tests.fixtures.plasma_wad import plasma_e1m1

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
LIST_EVERY = 8
_WAD = []


def _wad():
    if not _WAD:
        _WAD.append(plasma_e1m1())
    return _WAD[0]


def _world(**kw):
    kw = {"monsters": "final", "player": "final", "sight_rule": "seen", **kw}
    return World(_wad(), "E1M1", **kw)


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _sidx(s):
    return gd.STATE_INDEX[s]


def _sub(text, old, new, mut):
    assert text.count(old) == 1, (mut, old, text.count(old))
    return text.replace(old, new)


def _quiet(w):
    """nothing shootable or solid: every monster neither (still in the leaf lists), every barrel removed"""
    ws = w.ws
    for j in range(w.layout.nmon):
        ws.mon_solid[j] = ws.mon_shootable[j] = 0
        ws.mon_health[j] = 0
    for b in range(len(w.barrel_things)):
        ws.bar_state[b] = ws.bar_tics[b] = ws.bar_health[b] = ws.bar_solid[b] = 0


def test_the_fixture_is_a_plasma_map():
    w = _world()
    assert w.layout.plasma == 1 and any(t.type == 2004 for t in w.pickup_things)


# ================================================================================================ A. THE FLIGHT
FRAMES = 600


def _wall_spot(w, rnd, far: bool = False):
    """a spawn facing a near wall: from a monster spawn point along an axis to the first wall a missile meets, then
    back 3..18 units (point blank: the half step, 12.5 for the ball, and the box reach the wall, or nearly) or, `far`,
    20..160 (a flight of a few tics: both flight frames, the relinks) -- facing it. (A far shot may TUNNEL through a
    thin wall -- a 25-unit step past a 6-unit box, the rocket's and the ball's 2D convention, both mirrors alike -- and
    fly out of the map holding its slot: the far shots come last, so the pool turns over first.)"""
    for _ in range(400):
        m = rnd.randrange(w.layout.nmon)
        x, y = w.ws.mon_x[m], w.ws.mon_y[m]
        ang, (dx, dy) = rnd.choice(((0, (1, 0)), (0x40000000, (0, 1)), (0x80000000, (-1, 0)), (0xC0000000, (0, -1))))
        for d in range(0, 400):
            if w.missile_lines_block((x + d * dx) << 16, (y + d * dy) << 16):
                k = d - (rnd.randint(20, 160) if far else rnd.randint(1, 6))
                if k > 0:
                    return ((x + k * dx) << 16, (y + k * dy) << 16, ang)
                break
    raise AssertionError("no point blank spot")


def _ascript(w):
    """[(px16, py16, angle, door states, lift states, fswitch, fire (0 none, 1 rocket, 2 ball), z, dump lists)]"""
    rnd = random.Random(0x91A5)
    spots = [(w.ws.mon_x[m], w.ws.mon_y[m]) for m in range(w.layout.nmon)]
    out, burst = [], 0
    for f in range(FRAMES):
        if f % 60 == 0:                                    # the doors / lifts / switch hold a while (a ball that
            dstates = [rnd.randrange(w.door_nstates[si]) for si in w.door_order]   # flew through an open door
            lstates = [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]  # meets the room behind it);
            fsw = rnd.randrange(2)                         # the wall spots are found in the scene they fire in
            for d, v in enumerate(dstates):
                w.ws.d_state[d] = v
            for k, v in enumerate(lstates):
                w.ws.l_state[k] = v
            w.ws.f_switch = fsw
            w._door_phase_scene()
        if f % 200 == 0:
            burst = 12                                     # a volley: the pool fills, a ball fizzles
        kind = rnd.random()
        if kind < 0.5 or burst:                            # toward a near wall: short lives keep the pool turning
            px, py, ang = _wall_spot(w, rnd, far=f >= FRAMES - 150 and rnd.random() < 0.5)
            px |= rnd.randrange(1 << 16)
        else:
            sx, sy = rnd.choice(spots)
            px = ((sx << 16) + rnd.randint(-(4 << 16), 4 << 16)) & M32
            py = ((sy << 16) + rnd.randint(-(4 << 16), 4 << 16)) & M32
            ang = rnd.choice((0, 0x40000000, 0x80000000, 0xC0000000, rnd.randrange(1 << 32), rnd.randrange(1 << 32)))
        fire = burst > 0 or kind < 0.5
        burst = max(0, burst - 1)
        out.append((px & M32, py & M32, ang, dstates, lstates, fsw,
                    (2 if rnd.random() < 0.75 else 1) if fire else 0,
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
    """the point location the fj makes logs its query and feeds the model's leaf (a spawn's own try locates nothing
    in the fj: skipped); the rocket's blast logs its spot; kb_pz's z comes from the record"""
    orig_leaf, orig_try = w._leaf16, w._missile_try
    orig_rk, orig_pl = w._spawn_rocket, w._spawn_plasma
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

    def wrap(orig):
        def spawn(ev):
            st["spawn"] = True
            try:
                orig(ev)
            finally:
                st["spawn"] = False
        return spawn
    w._leaf16, w._missile_try = leaf16, mtry
    w._spawn_rocket, w._spawn_plasma = wrap(orig_rk), wrap(orig_pl)
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
    lines = []
    stats = {"balls": 0, "rockets": 0, "fizzles": 0, "blasts": 0, "booms_at_spawn": 0, "removals": 0,
             "ball_exps": 0, "ball2": 0}
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
            (w._spawn_plasma if fire == 2 else w._spawn_rocket)(ev)
            spawned = ev.plasma_spawns + ev.rocket_spawns
            stats["booms_at_spawn"] += sum(1 for s in spawned if s >= 0 and not ws.proj_momx[s]
                                           and not ws.proj_momy[s])
        w._projectiles_phase(ev)
        stats["balls"] += sum(1 for s in ev.plasma_spawns if s >= 0)
        stats["rockets"] += sum(1 for s in ev.rocket_spawns if s >= 0)
        stats["fizzles"] += ev.plasma_spawns.count(-1) + ev.rocket_spawns.count(-1)
        stats["removals"] += sum(1 for s in range(FIREBALL_POOL) if act[s] and not ws.proj_active[s])
        stats["ball_exps"] += sum(1 for s in range(FIREBALL_POOL)
                                  if ws.proj_active[s] and gd.STATE_NAMES[ws.proj_state[s]] == "S_PLASEXP")
        stats["ball2"] += sum(1 for s in range(FIREBALL_POOL)
                              if ws.proj_active[s] and gd.STATE_NAMES[ws.proj_state[s]] == "S_PLASBALL2")
        feed.append(bytes([int(lists)]))
        stats["blasts"] += sum(1 for ln in log if ln[0] == "B")
        lines.append("".join(log) + _arow(w))
        log.clear()
        if lists:
            lines.append(_lists(w))
    return ("\n".join(lines) + "\n").encode(), b"".join(feed) + bytes([0]), stats


def leaf_dump_lines(nleaf: int) -> list:
    """`ll_dump`: every leaf with a list, "lll:" then its runtime things (the rocket harness's)"""
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


def _mul_lines(cell, fn):
    return "".join("%s\n" % ln for ln in fn(cell))


def _plleaf(t):
    """the text of pl_spawn_leaf alone (a mutant edits only the ball's spawn, never the rocket's)"""
    a = t.index("pl_spawn_leaf:\n")
    return a, t.index("    stl.fret pj_slret\n", a)


def _in_plleaf(t, old, new, mut):
    a, b = _plleaf(t)
    return t[:a] + _sub(t[a:b], old, new, mut) + t[b:]


A_MUTANTS = {
    "speed20": lambda t: _in_plleaf(_in_plleaf(
        t, "    finesine.read_cos pw_mx, pw_idx\n" + _mul_lines("pw_mx", PC._times25),
        "    finesine.read_cos pw_mx, pw_idx\n" + _mul_lines("pw_mx", PC._times20), "speed20"),
        "    finesine.read_sin pw_my, pw_idx\n" + _mul_lines("pw_my", PC._times25),
        "    finesine.read_sin pw_my, pw_idx\n" + _mul_lines("pw_my", PC._times20), "speed20"),
    "nohalf": lambda t: _sub(_sub(t, "  pl_hx_p:\n    hex.add 8, pw_x, pw_c\n", "  pl_hx_p:\n", "nohalf"),
                             "  pl_hy_p:\n    hex.add 8, pw_y, pw_c\n", "  pl_hy_p:\n", "nohalf"),
    "noroll": lambda t: _in_plleaf(t, "    hex.inc 2, rng_fx\n    fxrnd.lookup pw_rr, rng_fx\n"
                                   "    hex.sub 1, pw_ti, pw_rr + 2*dw\n", "", "noroll"),
    "ball_as_rocket": lambda t: _sub(t, "    hex.if_flags pw_st + dw, %d, pl_explode, rk_explode\n"
                                     % (1 << PC.ROCKET_HI), "    ;rk_explode\n", "ball_as_rocket"),
    "rocket_as_ball": lambda t: _sub(t, "    hex.if_flags pw_st + dw, %d, pl_explode, rk_explode\n"
                                     % (1 << PC.ROCKET_HI), "    ;pl_explode\n", "rocket_as_ball"),
    "exp_tics": lambda t: _sub(t, "  pl_explode:\n    hex.set 2, pw_st, %d\n    hex.set 1, pw_ti, 4\n"
                               % _sidx("S_PLASEXP"),
                               "  pl_explode:\n    hex.set 2, pw_st, %d\n    hex.set 1, pw_ti, 3\n"
                               % _sidx("S_PLASEXP"), "exp_tics"),
    "highest": lambda t: _sub(t, "".join("    hex.if0 1, pj_act + %d*dw, pl_sp%d\n" % (s, s)
                                         for s in range(FIREBALL_POOL)),
                              "".join("    hex.if0 1, pj_act + %d*dw, pl_sp%d\n" % (s, s)
                                      for s in reversed(range(FIREBALL_POOL))), "highest"),
}


def _pj_text(w, nt, ft=None):
    """projcode's pool text in the final modes with the rifle (fight, knock, rockets, plasma), the cells' root R"""
    ft = ft or PC.fight_things(w, list(range(w.layout.nmon)))
    return ft, "\n".join(PC.pj_lines(nt=nt, root="R", knock=True, fight=ft, rockets=True, plasma=True)
                         + PC.pool_tic_lines(knock=True)) + "\n"


def _pool_decls_rt(w, nt, nthings, head, nxt):
    ws, n = w.ws, w.layout.nmon
    nd, nl, nb = len(w.door_order), len(w.lift_order), len(w.barrel_things)
    return ["wmagic: hex.vec 2", "wlist: hex.vec 2", "wfire: hex.vec 2",
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
            byte_array_decl("sshead", head, 2 * len(head)), byte_array_decl("thnext", nxt, 2 * nthings)]


def _lists_init(w, nthings):
    head, nxt = [0] * len(w.cmap.subsectors), [0] * nthings
    for leaf, ks in w.leaf_lists().items():
        head[leaf] = ks[0] + 1
        for a, b in zip(ks, ks[1:] + [-1]):
            nxt[a] = b + 1
    return head, nxt


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
    head, nxt = _lists_init(w, nthings)
    ws = w.ws
    nd, nl = len(w.door_order), len(w.lift_order)
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
            "hex.if0 2, wfire, no_fire",
            "hex.if_flags wfire, 1<<2, fire_rk, fire_pl",
            "fire_rk:", "stl.fcall rk_spawn, rk_sret", ";no_fire",
            "fire_pl:", "stl.fcall pl_spawn, pl_sret",
            "no_fire:",
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
            "dp_go:", "    stl.fret dp_ret", "dm_go:", "    stl.fret dm_ret", "ia_leaf:", "    stl.fret ia_ret"]
    decls = (PC.pool_decls(values={"rng_fx": ws.rng_fx}) + PC.pt_decls(ft) + PC.ROCKET_DECLS + PC.PLASMA_DECLS
             + COLLISION_STATE_DECLS + point_location_decls() + LEAF_LINK_DECLS + KC.KB_INTERFACE
             + KC.persisted_decls(n) + ["pw_z: hex.vec 4", "kb_pzv: hex.vec 4", "kb_pzret: hex.vec w/4"]
             + [d for d in MD.FIGHT_DECLS if d.split(":")[0].startswith(("ia_", "mt_tq"))]
             + _pool_decls_rt(w, nt, nthings, head, nxt))
    tables = (PC.tables_fj(rockets=True, plasma=True)
              + [generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry")])
    prog = "\n".join(body + decls + dump + leaf_dump_lines(nleaf) + [code, cells] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], feed, want


def _arun(tmp_path, name, mut=None) -> bool:
    srcs, feed, want = _abuild(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, feed, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_flight_script_exercises_every_path():
    """the model's own run: balls AND rockets spawned and flying, a full pool fizzling, balls exploding at their
    spawn and against walls, both flight frames, the ball's explosion, the slots freed, rockets blasting"""
    _want, _feed, stats = _amodel(_ascript(_world()))
    assert stats["balls"] >= 80 and stats["rockets"] >= 15 and stats["fizzles"] >= 3 \
        and stats["booms_at_spawn"] >= 50 and stats["blasts"] >= 15 and stats["removals"] >= 80 \
        and stats["ball_exps"] >= 80 and stats["ball2"] >= 20, stats


def test_the_ball_flies_as_the_model(tmp_path):
    assert _arun(tmp_path, "plfly"), "the fj plasma ball's flight parted from the model's"


@pytest.mark.parametrize("mut", sorted(A_MUTANTS))
def test_control_a_broken_flight_is_caught(tmp_path, mut):
    assert not _arun(tmp_path, "plfly_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut


# ================================================================================================ B. THE THINGS
B_N = 500
BAR_ST = {"stand": (lambda: _sidx("S_BAR1"), 20, 1), "boom": (lambda: _sidx("S_BEXP"), 0, 1),
          "gone": (lambda: 0, 0, 0)}
B_STATES = ("S_PLASBALL", "S_PLASBALL2", "S_PLASBALL", "S_ROCKET")


def _brecords(w):
    rnd = random.Random(0x91B7)
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
        p16 = ((nx16 + rnd.randint(-12 << 16, 12 << 16)) & M32, (ny16 + rnd.randint(-12 << 16, 12 << 16)) & M32)
        out.append(dict(nx16=nx16, ny16=ny16, mons=mons, bars=bars, p16=p16, lines=int(rnd.random() < 0.8),
                        rng=rnd.randrange(256), st=rnd.choice(B_STATES)))
    return out


def _window(r):
    return 0x44 + r % 10, (37 * r + 5) % 0x2C0


def _bapply(w, rec, log, hits=None):
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
    ws.proj_src[s], ws.proj_active[s], ws.proj_state[s] = 0, 1, _sidx(rec["st"])
    w.missile_lines_block = lambda x16, y16, _ok=rec["lines"]: not _ok
    w.damage_player = lambda dmg, source, inflictor, ev: log.append("P%02x" % dmg)
    w.damage_monster = lambda j, dmg, source, inflictor, ev: log.append(
        "M%02x%02x3%02x%x" % (1 + j, dmg, w._source_code(source), int(w._source_is_player(source))))
    w.damage_barrel = lambda b, dmg, source, ev: log.append(
        "M%02x%02x3%02x%x" % (1 + n + b, dmg, w._source_code(source), int(w._source_is_player(source))))
    w._leaf16 = lambda x16, y16: 0
    w._list_remove = w._list_insert = lambda k, leaf: None
    ws.proj_leaf[s] = 0
    ev = TicEvents(0)
    ok = w._missile_try(s, _s32(rec["nx16"]), _s32(rec["ny16"]), ev)
    if hits is not None:
        hits += [("pl" if rec["st"] != "S_ROCKET" else "rk",) + h for h in ev.plasma_hits + ev.rocket_hits]
    return ok


def _bexpected(w, records) -> bytes:
    lines = []
    for r, rec in enumerate(records):
        log = []
        ok = _bapply(w, rec, log)
        lines += log + ["%x%02x%02x%03x" % ((int(ok), w.ws.rng_fx) + _window(r))]
    return ("\n".join(lines) + "\n").encode()


B_MUTANTS = {
    "rocket_table": ("  pt_dpl:\n    pldmg.lookup dm_dmg, rng_fx\n", "  pt_dpl:\n    rkdmg.lookup dm_dmg, rng_fx\n"),
    "discriminator": ("    hex.if_flags pw_st + dw, %d, pt_dpl, pt_drk\n" % (1 << PC.ROCKET_HI),
                      "    hex.if_flags pw_st + dw, %d, pt_drk, pt_dpl\n" % (1 << PC.ROCKET_HI)),
    "species": ("    hex.if1 1, pt_rk, pt_nsp\n", ""),
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
                 "hex.set 2, pw_st, %d" % _sidx(rec["st"]),
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
    decls = (PC.pool_decls() + PC.pt_decls(ft) + PC.ROCKET_DECLS + PC.PLASMA_DECLS + KC.KB_INTERFACE
             + ["pw_z: hex.vec 4",
                "viewx: hex.vec 8", "viewy: hex.vec 8", "p_hp: hex.vec 3", "p_dead: hex.vec 1",
                "dp_dmg: hex.vec 2", "dp_src: hex.vec 2", "dp_ret: hex.vec w/4",
                "dm_id: hex.vec 2", "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2", "dm_ret: hex.vec w/4",
                "cp_ok: hex.vec 1", "cp_poke: hex.vec 1", "cpx: hex.vec 8", "cpy: hex.vec 8", "cprad: hex.vec 8",
                "mon_solid: hex.vec %d" % n, "mon_shootable: hex.vec %d" % n, "thpos_rt: hex.vec %d" % (16 * n),
                "bar_st: hex.vec %d" % (2 * nb), "bar_hp: hex.vec %d" % (2 * nb), "bar_solid: hex.vec %d" % nb])
    prog = "\n".join(body + decls + [unit] + PC.tables_fj(rockets=True, plasma=True)) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], want


def _brun(tmp_path, name, mut=None) -> bool:
    srcs, want = _bbuild(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_thing_records_exercise_every_thing():
    """the model's outcomes: balls hitting monsters (imps among them: no species rule) and barrels with fives, rockets
    with twenties, solid corpses and exploding barrels stopping them, the player passed, clear passes"""
    w = _world()
    seen = {"pl_mon": 0, "pl_imp": 0, "pl_bar": 0, "pl_corpse": 0, "rk_mon": 0, "pass": 0, "lines": 0}
    for rec in _brecords(w):
        log, hits = [], []
        ok = _bapply(w, rec, log, hits)
        for who, kind, j, dmg in hits:
            seen["%s_%s" % (who, kind)] = seen.get("%s_%s" % (who, kind), 0) + 1
            seen["pl_imp"] += who == "pl" and kind == "mon" and w.mon_things[j].type == 3001
            assert who != "pl" or kind == "corpse" or (dmg % 5 == 0 and 5 <= dmg <= 40), (who, kind, dmg)
        seen["pass"] += bool(ok)
        seen["lines"] += (not ok) and not hits
        assert not any(ln[0] == "P" for ln in log), "a player's missile hit its shooter"
    want = {"pl_mon": 30, "pl_imp": 6, "pl_bar": 6, "pl_corpse": 10, "rk_mon": 8, "pass": 100, "lines": 20}
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_ball_meets_things_as_the_model(tmp_path):
    assert _brun(tmp_path, "plthings"), "the fj ball's things parted from the model's _rocket_things"


@pytest.mark.parametrize("mut", sorted(B_MUTANTS))
def test_control_a_broken_ball_thing_test_is_caught(tmp_path, mut):
    assert not _brun(tmp_path, "plthings_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut


# ================================================================================================ C. THE WEAPON
C_N = 700
C_CELLS = (("wp_rdy", 1), ("wp_pend", 1), ("wp_st", 2), ("wp_tics", 1), ("wp_sy", 2), ("fl_st", 2), ("fl_tics", 1),
           ("wp_rf", 2), ("wp_ad", 1), ("am_clip", 3), ("am_shell", 3), ("rng_pl", 2), ("wp_frm", 2), ("fl_frm", 1),
           ("hud_v", 3), ("hud_v + 9*dw", 6), ("wp_pass", 1), ("am_misl", 3), ("am_cell", 3), ("wp_own", 7))
C_KEYS = ("w1", "w2", "w3", "w4", "w5", "w6")


def _cscript(seed=0x6C):
    rng = random.Random(seed)
    keys, fire = [], False
    for t in range(C_N):
        if rng.random() < 0.07:
            fire = not fire
        k = {name: False for name in KEYS}
        k["fire"] = fire or rng.random() < 0.05
        if rng.random() < 0.015:
            k[rng.choice(C_KEYS + ("w6", "w6"))] = True
        keys.append(k)
    return keys


def _cworld():
    w = World(_wad(), "E1M1", skill=gd.SK_HARD, monsters="idle", player="fire", monster_tics=1)
    ws = w.ws
    ws.p_owned[gd.WP_SHOTGUN] = ws.p_owned[gd.WP_CHAINSAW] = ws.p_owned[gd.WP_MISSILE] = 1
    ws.p_owned[gd.WP_CHAINGUN] = ws.p_owned[gd.WP_PLASMA] = 1
    ws.p_ammo[gd.AM_SHELL], ws.p_ammo[gd.AM_CLIP], ws.p_ammo[gd.AM_MISL] = 4, 30, 3
    ws.p_ammo[gd.AM_CELL] = 60                          # the rifle runs dry inside the script
    return w


def _cstart(w):
    ws = w.ws
    return {f: getattr(ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                        "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown", "rng_player")} \
        | {"ammo": list(ws.p_ammo), "owned": list(ws.p_owned)}


C_MUTANTS = {
    "key6_dead": ("wk_6:\nhex.if0 1, kb_now + 13*dw, wk_end\n", "wk_6:\n;wk_end\n"),
    "flash_fixed": ("hex.inc 2, rng_pl\nplfl.lookup pl_k, rng_pl\n", "hex.zero 1, pl_k\n"),
    "cell_kept": ("hex.sub_constant 3, am_cell, 1\nhex.inc 2, rng_pl\n", "hex.inc 2, rng_pl\n"),
    "pref_norifle": None,
}


def _cprogram(start, mut=None):
    states = WC.weapon_states(True)
    frames = WC.overlay_frames(plasma=True)
    text = "\n".join(WC.weapon_lines(states, frames, plasma=True))
    if mut == "pref_norifle":
        text, k = re.subn(r"hex\.if0 1, wp_own \+ 6\*dw, (\w+cxg)\n", r";\1\n", text)
        assert k >= 1, "the rifle's preference not found"
    elif mut:
        old, new = C_MUTANTS[mut]
        assert old in text, mut
        text = text.replace(old, new)
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, kin",
            "hex.zero 2, pkeys",
            "hex.if_flags kin, 0xAAAA, kf_no, kf_yes", "kf_yes:", "hex.xor_by pkeys + dw, 0x8", "kf_no:"]
    for i, k in enumerate(C_KEYS):                     # bits 1..6 -> kb_now's w1..w6 nibbles (8..13)
        bit = i + 1
        nib, b = bit >> 2, bit & 3
        mask = sum(1 << v for v in range(16) if v >> b & 1)
        body += ["hex.zero 1, %s" % KB.now_cell(k),
                 "hex.if_flags kin + %d*dw, %#06x, kn%d_no, kn%d_yes" % (nib, mask, i, i),
                 "kn%d_yes:" % i, "hex.set 1, %s, 1" % KB.now_cell(k), "kn%d_no:" % i]
    body += [text,
             *[x for c, n in C_CELLS for x in ("hex.print_as_digit %d, %s, 0" % (n, c), "stl.output 44")],
             "stl.output 10", ";loop",
             "bad:", "stl.loop", "done:", "stl.loop",
             "rmagic: hex.vec 2", "kin: hex.vec 2", "pkeys: hex.vec 2",
             KB.now_decl(True),
             *WC.weapon_decls(start, states, frames, misl=True, plasma=True), *WC.weapon_const_decls(),
             *hudcode.hud_decls(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))),
             generate_dispatch_table_fj("ammobcd", WC.ammo_digit_values(), index_nibbles=3, result_nibbles=3),
             WC.plfl_table_fj()]
    return "\n".join(body) + "\n", states, frames


def _cwant(row, states, frames):
    idx = {gd.STATE_INDEX[s]: i for i, s in enumerate(states)}
    wst, fst = gd.STATE_NAMES[row["p_wpn_state"]], gd.STATE_NAMES[row["p_flash_state"]]
    ammo = {gd.WP_PISTOL: row["ammo"][gd.AM_CLIP], gd.WP_SHOTGUN: row["ammo"][gd.AM_SHELL],
            gd.WP_MISSILE: row["ammo"][gd.AM_MISL], gd.WP_CHAINGUN: row["ammo"][gd.AM_CLIP],
            gd.WP_PLASMA: row["ammo"][gd.AM_CELL]}.get(row["p_ready"])
    bar = hudcode.slot_codes(hud.slot_values(ammo=ammo, health=100, armor=0,
                                             owned=hud.arms_owned(row["owned"]), blue=False))
    return [row["p_ready"], row["p_pending"], idx[row["p_wpn_state"]], row["p_wpn_tics"], row["p_wpn_sy"],
            idx[row["p_flash_state"]], row["p_flash_tics"], row["p_refire"], row["p_attackdown"],
            row["ammo"][gd.AM_CLIP], row["ammo"][gd.AM_SHELL], row["rng_player"],
            frames.index(WC.psprite_lump(wst)),
            0 if fst == gd.S_NULL or gd.STATES[fst].tics == 0 else 1 + WC.flash_frames(True).index(WC.psprite_lump(fst)),
            bar[0] | bar[1] << 4 | bar[2] << 8, sum(bar[9 + i] << (4 * i) for i in range(6)), 0,
            row["ammo"][gd.AM_MISL], row["ammo"][gd.AM_CELL],
            sum(int(bool(row["owned"][x])) << (4 * WC.OWN[x]) for x in WC.weapons(True))]


def _crun(tmp_path, name, mut=None):
    script = _cscript()
    w = _cworld()
    text, states, frames = _cprogram(_cstart(w), mut)
    src = tmp_path / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    feed = b"".join(bytes([1, int(k["fire"]) | sum(int(k[c]) << (i + 1) for i, c in enumerate(C_KEYS))])
                    for k in script) + bytes([0])
    io = FixedIO(feed)
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = []
    for line in io.get_output(allow_incomplete_output=True).decode("latin-1").split("\n")[:len(script)]:
        try:
            got.append([int(v, 16) for v in line.split(",")[:len(C_CELLS)]])
        except ValueError:
            got.append(None)
    rows = []
    for k in script:
        w.tic(k)
        rows.append({f: getattr(w.ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                                   "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown",
                                                   "rng_player")}
                    | {"ammo": tuple(w.ws.p_ammo), "owned": tuple(w.ws.p_owned)})
    want = [_cwant(r, states, frames) for r in rows]
    return got, want, rows


def _first_bad(got, want):
    assert len(got) == len(want), "the program printed %d tics of %d" % (len(got), len(want))
    return next((t for t, (g, w_) in enumerate(zip(got, want)) if g != w_), None)


def test_the_rifle_is_the_model_tic_by_tic(tmp_path):
    got, want, rows = _crun(tmp_path, "plwpn")
    bad = _first_bad(got, want)
    names = [c for c, _n in C_CELLS]
    assert bad is None, "tic %d: %s" % (bad, {names[i]: (got[bad][i], want[bad][i]) for i in range(len(names))
                                             if got[bad] is None or got[bad][i] != want[bad][i]})
    # the script covers what it claims: the rifle up and firing, both flashes, the long S_PLASMA2B, the cells run
    # dry and the next weapon picked, key 6 used
    ready = [r["p_ready"] for r in rows]
    wst = {gd.STATE_NAMES[r["p_wpn_state"]] for r in rows}
    fst = {gd.STATE_NAMES[r["p_flash_state"]] for r in rows}
    assert gd.WP_PLASMA in ready and {"S_PLASMA1", "S_PLASMA2", "S_PLASMA2B"} <= wst, wst
    assert {"S_PLASMAFLASH1", "S_PLASMAFLASH2"} <= fst, fst
    assert any(r["ammo"][gd.AM_CELL] == 0 for r in rows) and len(set(ready)) >= 4


@pytest.mark.parametrize("mut", sorted(C_MUTANTS))
def test_control_a_broken_rifle_is_caught(tmp_path, mut):
    got, want, _rows = _crun(tmp_path, "plwpn_" + mut, mut)
    assert _first_bad(got, want) is not None, "%s passed: the comparison is vacuous" % mut


def test_the_rifle_s_weapon_text_is_e1m1_s_when_off():
    """plasma off: weapon_lines is the text it was (no key 6, no plfl, no rifle in any dispatch) -- the E1M1 / E1M2
    emission does not move; on, the loot weapon's A_FirePlasma calls pl_spawn after the flash"""
    st, fr = WC.weapon_states(), WC.overlay_frames()
    off = "\n".join(WC.weapon_lines(st, fr, shoot=True, noise=True, hurt=True, loot=True))
    assert "wk_6" not in off and "plfl" not in off and "am_cell" not in off and "pl_spawn" not in off
    on = "\n".join(WC.weapon_lines(WC.weapon_states(True), WC.overlay_frames(plasma=True), shoot=True, noise=True,
                                   hurt=True, loot=True, plasma=True))
    a = on.index("plfl.lookup pl_k, rng_pl")
    assert on.index("stl.fcall pl_spawn, pl_sret", a) > on.index("fl_ret", a)


# ================================================================================================ D. THE GIVES
D_N = 700
D_CELLS = (("am_clip", 3), ("am_shell", 3), ("am_cell", 3), ("am_misl", 3), ("p_bp", 1), ("wp_own", 7),
           ("wp_pend", 1), ("gv_ok", 1))
D_KINDS = (2004, 2047, 17, 2048, 8)


def _drecords():
    rnd = random.Random(0xD6)
    out = []
    for r in range(D_N):
        kind = D_KINDS[r % len(D_KINDS)] if r < 3 * len(D_KINDS) else rnd.choice(D_KINDS + (2004, 2047))
        bp = rnd.choice((0, 0, 1))
        ammo = []
        for a in range(gd.NUMAMMO):
            cap = gd.MAXAMMO[a] * (2 if bp else 1)
            ammo.append(rnd.choice((0, 0, cap, cap - 1, cap - 30, rnd.randint(0, cap), 1)))
        owned = {w: (1 if w in (gd.WP_FIST,) else int(rnd.random() < 0.5)) for w in WC.weapons(True)}
        owned[gd.WP_PISTOL] = 1
        ready = rnd.choice([x for x in WC.weapons(True) if owned[x]])
        pend = rnd.choice((gd.WP_NOCHANGE, gd.WP_NOCHANGE, rnd.choice(WC.weapons(True))))
        out.append(dict(kind=kind, bp=bp, ammo=ammo, owned=owned, ready=ready, pend=pend))
    return out


def _dexpected(w, records):
    lines = []
    for rec in records:
        ws = w.ws
        ws.p_backpack, ws.p_ready, ws.p_pending = rec["bp"], rec["ready"], rec["pend"]
        for a in range(gd.NUMAMMO):
            ws.p_ammo[a] = rec["ammo"][a]
        for x in range(gd.NUMWEAPONS):
            ws.p_owned[x] = rec["owned"].get(x, 0)
        taken = w._touch(rec["kind"], False, 0, 0)
        own = sum(ws.p_owned[x] << (4 * WC.OWN[x]) for x in WC.weapons(True))
        vals = [ws.p_ammo[gd.AM_CLIP], ws.p_ammo[gd.AM_SHELL], ws.p_ammo[gd.AM_CELL], ws.p_ammo[gd.AM_MISL],
                ws.p_backpack, own, ws.p_pending, int(taken)]
        lines.append("".join("%0*x" % (n, v) for (_c, n), v in zip(D_CELLS, vals)))
    return ("\n".join(lines) + "\n").encode()


D_MUTANTS = {
    "plas_nopend": (r"(  give_2004_new:\n    hex\.set 1, wp_own \+ 6\*dw, 1\n)    hex\.set 1, wp_pend, %d\n"
                    % gd.WP_PLASMA, r"\1"),
    "plas_one": (r"(give_2004:\n    hex\.set 3, ga_n, )40", r"\g<1>20"),
    "cell_noswitch": (r"(  ga2_sw:\n    hex\.if0 1, wp_own \+ 6\*dw, ga2_out\n)    hex\.set 1, wp_pend, %d\n"
                      % gd.WP_PLASMA, r"\1"),
}


def _drun(tmp_path, name, mut=None) -> bool:
    w = _world(monsters="idle", player="fire")
    records = _drecords()
    want = _dexpected(w, records)
    gives = []
    for kind in sorted(set(D_KINDS)):
        gives += L.give_lines(kind)
    for a in range(gd.NUMAMMO):
        gives += L.give_ammo_lines(a, plasma=True)
    text = "\n".join(gives) + "\n"
    if mut:
        pat, new = D_MUTANTS[mut]
        text, k = re.subn(pat, new, text)
        assert k >= 1, mut
    body = ["stl.startup_and_init_all"]
    for rec in records:
        body += ["hex.set 1, p_bp, %d" % rec["bp"], "hex.set 1, wp_rdy, %d" % rec["ready"],
                 "hex.set 1, wp_pend, %d" % rec["pend"]]
        for a in range(gd.NUMAMMO):
            body.append("hex.set 3, %s, %d" % (L.AMMO_CELL[a], rec["ammo"][a]))
        body.append("hex.set 7, wp_own, %d" % sum(rec["owned"][x] << (4 * WC.OWN[x]) for x in WC.weapons(True)))
        body += ["hex.set 1, gv_ok, 7", "stl.fcall give_%d, gv_ret" % rec["kind"]]
        body += ["hex.print_as_digit %d, %s, 0" % (n, c) for c, n in D_CELLS] + ["stl.output 10"]
    body += ["stl.loop"]
    wstart = WC.level_start(w.mw, "E1M1")
    decls = (L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(wstart, WC.weapon_states(True), WC.overlay_frames(plasma=True), plasma=True)
             + ["pcard: hex.vec 1"])
    prog = "\n".join(body + decls) + "\n" + text + "\n".join(L.tables_fj(w)) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_give_records_exercise_every_case():
    w = _world(monsters="idle", player="fire")
    seen = {"new": 0, "owned_ammo": 0, "refused": 0, "switch": 0}
    for rec in _drecords():
        ws = w.ws
        ws.p_backpack, ws.p_ready, ws.p_pending = rec["bp"], rec["ready"], rec["pend"]
        for a in range(gd.NUMAMMO):
            ws.p_ammo[a] = rec["ammo"][a]
        for x in range(gd.NUMWEAPONS):
            ws.p_owned[x] = rec["owned"].get(x, 0)
        cells0 = ws.p_ammo[gd.AM_CELL]
        taken = w._touch(rec["kind"], False, 0, 0)
        if rec["kind"] == 2004:
            seen["new"] += not rec["owned"][gd.WP_PLASMA]
            seen["owned_ammo"] += bool(rec["owned"][gd.WP_PLASMA] and taken)
            seen["refused"] += not taken
        seen["switch"] += (rec["kind"] in (2047, 17) and cells0 == 0 and ws.p_pending == gd.WP_PLASMA
                           and rec["pend"] != gd.WP_PLASMA)
    assert all(v >= 5 for v in seen.values()), seen


def test_the_rifle_s_gives_follow_the_model(tmp_path):
    assert _drun(tmp_path, "plgive"), "the fj gives parted from the model's _touch"


@pytest.mark.parametrize("mut", sorted(D_MUTANTS))
def test_control_a_broken_rifle_give_is_caught(tmp_path, mut):
    assert not _drun(tmp_path, "plgive_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut


# ================================================================================================ E. KEY 6
POLLS, E_FRAMES = STANDALONE_POLLS, 6
SIX, FIRE, FIVE = KB.W6_CODE, 0x85, 0x35


def _eprogram(key_lines) -> str:
    keys = KB.held_keys(True)
    return "\n".join([
        "stl.startup_and_init_all",
        "tm_frame:",
        *key_lines,
        "    hex.print_as_digit 2, pkeys, 0", "    stl.output_char 32",
        *[f"    hex.print_as_digit 1, {KB.now_cell(k)}, 0" for k in keys], "    stl.output_char 32",
        *[f"    hex.print_as_digit 1, {KB.flag(k)}, 0" for k in keys],
        "    stl.output 10",
        "    hex.inc 2, tm_count",
        "    hex.cmp 2, tm_count, tm_frames, tm_frame, tm_done, tm_done",
        "tm_done:", "    stl.loop",
        "bad:", "    stl.output_char 0x21", "    stl.loop",
        "kbstat: hex.vec 1", "kbcode: hex.vec 2", "pkeys: hex.vec 2",
        *[f"{KB.flag(k)}: hex.vec 1" for k in keys],
        KB.now_decl(True),
        *[f"{e}: hex.vec 1" for e in ("ev_enter", "ev_esc", "ev_up", "ev_dn", "ev_help", "ev_any", "ev_map")],
        "tm_count: hex.vec 2", f"tm_frames: hex.vec 2, {E_FRAMES}",
    ]) + "\n"


def _eassemble(tmp, name, key_lines):
    src = tmp / f"{name}.fj"
    src.write_text(_eprogram(key_lines), encoding="utf-8")
    out = tmp / f"{name}.fjm"
    fj.assemble([(FJ / "input.fj").resolve(), src.resolve()], out, memory_width=W, print_time=False)
    return out


def _erun(fjm, events) -> list:
    io = KeyboardIO(ScriptedKeyEventSource([KeyEvent(*e) for e in events]))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode("ascii").split("\n")[:E_FRAMES]


def _eexpected(events) -> list:
    keys = KB.held_keys(True)
    out = []
    for fk in KB.frame_keys(events, E_FRAMES, polls=POLLS, binding=KB.BINDING_PLASMA):
        out.append("%02x %s %s" % (keys_byte(KB.named(fk.now)), "".join(str(int(fk.now[k])) for k in keys),
                                   "".join(str(int(fk.held[k])) for k in keys)))
    return out


def tap(frame, code, at=0):
    return [(frame * POLLS + at, True, code), (frame * POLLS + at + 1, False, code)]


E_SCRIPTS = {
    "nothing": [],
    "6 tapped inside one frame": tap(1, SIX, at=2),
    "6 held three frames": [(POLLS + 1, True, SIX), (4 * POLLS + 2, False, SIX)],
    "6 and fire tapped in one frame, 5 the next": tap(1, SIX) + tap(1, FIRE, at=3) + tap(2, FIVE, at=1),
    "6 held from before, released and pressed again in one frame": [(0, True, SIX), (POLLS, False, SIX),
                                                                     (POLLS + 1, True, SIX), (3 * POLLS, False, SIX)],
    "a burst pushes the 6 into the next frame": ([(0, True, c) for c in (0x61, 0x64, 0x2C, 0x2E, 0x65, 0x31, 0x33)]
                                                 + tap(0, SIX)),
    "every bound key tapped once": [(2 * k + (not d), d, c)
                                    for k, c in enumerate(sorted(KB.BINDING_PLASMA)) for d in (True, False)],
}


def _elines():
    return standalone_key_lines(POLLS, plasma=True)


@pytest.fixture(scope="module")
def e_shipped(tmp_path_factory):
    return _eassemble(tmp_path_factory.mktemp("plkeys"), "plkeys", _elines())


@pytest.mark.parametrize("name", sorted(E_SCRIPTS))
def test_key_6_is_held_or_pressed_as_the_oracle(e_shipped, name):
    got, want = _erun(e_shipped, E_SCRIPTS[name]), _eexpected(E_SCRIPTS[name])
    assert got == want, (name, got, want)


def test_the_six_scripts_use_key_6():
    w6 = KB.held_keys(True).index("w6")
    for name in ("6 tapped inside one frame", "6 held three frames"):
        assert any(ln.split()[1][w6] == "1" for ln in _eexpected(E_SCRIPTS[name])), name


def _emutants():
    lines = _elines()
    return {"up edge keeps kb_w6": [ln for ln in lines if ln != "hex.zero 1, kb_w6"],
            "no latch": [ln for ln in lines if ln != "hex.set 1, %s, 1" % KB.now_cell("w6")],
            "the latch's 14th nibble never zeroed": [("hex.zero 13, kb_now" if ln == "hex.zero 14, kb_now" else ln)
                                                     for ln in lines]}


@pytest.mark.parametrize("name", sorted(_emutants()))
def test_control_a_broken_key_6_is_caught(tmp_path, name):
    lines = _emutants()[name]
    assert lines != _elines(), "the mutant changed nothing"
    bad = _eassemble(tmp_path, "bad", lines)
    assert [n for n in E_SCRIPTS if _erun(bad, E_SCRIPTS[n]) != _eexpected(E_SCRIPTS[n])], name


def test_the_key_lines_are_e1m1_s_without_the_rifle():
    """plasma off: no w6 reader, the 13-nibble latch -- E1M1's prologue"""
    off = standalone_key_lines(POLLS)
    assert not any("kb_w6" in ln or "kb6" in ln for ln in off) and "hex.zero 13, kb_now" in off


# ================================================================================================ F. THE COST
F_TICS = 24


def _fbuild(tmp_path, name, fire: bool, tics: int):
    """pj_phase `tics` times (after one pl_spawn when `fire`) with the REAL point location, missile cells and the
    things (every monster and barrel as the level start stands them) -- nothing printed"""
    w = _world()
    n = w.layout.nmon
    nt = n
    nthings = nt + FIREBALL_POOL + FX_POOL
    cells, root = PC.missile_cells_fj(w)
    ft, code = _pj_text(w, nt)
    code = code.replace("sim.check_cells R\n", "sim.check_cells %s\n" % root)
    head, nxt = _lists_init(w, nthings)
    px, py, ang = F_SPOT
    body = ["stl.startup_and_init_all",
            "hex.set 8, viewx, %d" % (px & M32), "hex.set 8, viewy, %d" % (py & M32), "hex.set 8, viewangle, %d" % ang,
            *(["stl.fcall pl_spawn, pl_sret"] if fire else []),
            *["stl.fcall pj_phase, pj_pret"] * tics,
            "hex.print_as_digit 1, pj_act, 0", "hex.print_as_digit 2, pj_st, 0", "stl.output 10", "stl.loop",
            "kb_pz:", "    hex.zero 4, kb_pzv", "    stl.fret kb_pzret",
            "rk_blast:", "    stl.fret rk_bret",
            "dp_go:", "    stl.fret dp_ret", "dm_go:", "    stl.fret dm_ret", "ia_leaf:", "    stl.fret ia_ret"]
    ws = w.ws
    mon = [ln for j in range(n) for ln in ("hex.set 1, mon_solid + %d*dw, %d" % (j, ws.mon_solid[j]),
                                           "hex.set 1, mon_shootable + %d*dw, %d" % (j, ws.mon_shootable[j]))]
    decls = (PC.pool_decls(values={"rng_fx": ws.rng_fx}) + PC.pt_decls(ft) + PC.ROCKET_DECLS + PC.PLASMA_DECLS
             + COLLISION_STATE_DECLS + point_location_decls() + LEAF_LINK_DECLS + KC.KB_INTERFACE
             + KC.persisted_decls(n) + ["pw_z: hex.vec 4", "kb_pzv: hex.vec 4", "kb_pzret: hex.vec w/4"]
             + [d for d in MD.FIGHT_DECLS if d.split(":")[0].startswith(("ia_", "mt_tq"))]
             + _pool_decls_rt(w, nt, nthings, head, nxt))
    tables = (PC.tables_fj(rockets=True, plasma=True)
              + [generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry")])
    prog = "\n".join(body[:1] + mon + body[1:] + decls + [code, cells, generate_point_location_fj(w.cmap)]
                     + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    out = tmp_path / ("%s.fjm" % name)
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], out,
                memory_width=W, print_time=False)
    io = FixedIO(b"")
    stats = fj.run(out, io_device=io, print_time=False, print_termination=False)
    return stats.op_counter, io.get_output(allow_incomplete_output=True).decode("latin-1")


# a long open flight in E1M1's courtyard-facing start room: the player start, facing east (the model's flight below
# says how many tics the ball lives)
F_SPOT = (-416 << 16, 256 << 16, 0)


def test_the_cost_of_an_active_ball(tmp_path):
    w = _world()
    ws = w.ws
    ws.px, ws.py, ws.pangle = F_SPOT
    ev = TicEvents(0)
    w._spawn_plasma(ev)
    s = ev.plasma_spawns[0]
    flying = 0
    for _t in range(F_TICS):
        if ws.proj_active[s] and gd.STATE_NAMES[ws.proj_state[s]] in ("S_PLASBALL", "S_PLASBALL2"):
            flying += 1
        w._projectiles_phase(ev)
    assert flying >= 8, flying
    empty, _o0 = _fbuild(tmp_path, "cost0", False, flying)
    spawn, _o1 = _fbuild(tmp_path, "cost1", True, 0)
    base, _o2 = _fbuild(tmp_path, "cost2", False, 0)
    full, out = _fbuild(tmp_path, "cost3", True, flying)
    per_tic = ((full - spawn) - (empty - base)) / flying
    print("\nM8 C6 COST: an active plasma ball in flight (E1M1+rifle, %d monsters, %d barrels, real point location, "
          "missile cells, things): %.0f ops per tic = %.0f ops per frame (%d monster tics a frame); the spawn "
          "(pl_spawn, its try) %d ops; the empty pool's pj_phase %.0f ops a tic"
          % (w.layout.nmon, len(w.barrel_things), per_tic, per_tic * 2, 2, spawn - base, (empty - base) / flying))
    assert out.startswith("1"), out
    assert 0 < per_tic < 1_000_000
