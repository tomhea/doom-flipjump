"""M8 C8 part 2 (doomfj.soulcode): THE LOST SOUL on the real flipjump engine -- the very text the emitter splices,
against the model's own rules (doomfj.lostsoul), record by record, on E1M1 with three souls placed in front of the
player start (tests/host/test_lostsoul_model.py's map: the soul's own maps cannot build a World until their other
clusters land). ONE program: the move infrastructure the game tier holds (the player's and the monsters' cells, the
seed, the point location, the leaf lists, pk_go, pb_mon, mm_things, kb_xy with its soul path, kb_mtry / kb_ptry, kb_pz,
mt_load with the targets' z, ia_leaf, mm_todist / mm_octant, mm_move with the soul's float) and every soul leaf --
with P_DamageMobj's two entries STUBBED: `dm_go` and `dp_go` print what they were called with (the id, the damage, the
mode, the source and the inflictor the slam set), and the model's damage_monster / damage_player / damage_barrel are
recorders (the thrust, pain and death of the slammed thing are damagecode's, tested there).

THE RECORDS (each pokes the soul and its world identically on both sides, then prints the cells):
  XY      `sks<k>` -- P_XYMovement: flying or not, alive or a corpse, on its floor or in the air, momenta around
          MAXMOVE / 2 (the halving), STOPSPEED and FRACUNIT / 4, toward walls, ledges, lifts' WR lines, a monster,
          the player, a barrel, an item, a drop -- the slam's stub call, then the momentum, the position and its
          fraction, the floor, the leaf, the sector, kb_live, fly, momz, the ceiling, the stream, sk_lk;
  Z       `skz<k>` -- P_ZMovement: z, momz, the floor and the ceiling it meets, flying / floating / alive, the target
          (the player at his check_position floorz, or a monster: a plain one at its floor, a soul at its z) near and
          far -- z, momz;
  CHARGE  mt_load, mm_todist, mm_octant, `sk_charge` -- A_SkullAttack at the player or a monster: the facing, the
          momentum, momz;
  MOVE    `mm_move` with the soul context -- P_Move: the step, the float up or down a ledge (FLOATOK), a refusal (a wall,
          a thing, a monster door's press), floating's clear and the ceiling on an accept;
  RANGE   soulcode.decide_range_lines on every (d, v) edge -- the MT_SKULL roll.

R9 (each must part from the model): XY no_slam, slam_keeps (the charge goes on after a slam), fly_friction (friction
while flying), air_friction (friction in the air), slam_damage (a wrong roll row); Z no_bounce, float_sign, ceil_keep
(a flying soul's momz not reversed at the ceiling); CHARGE floor_div (momz by floor division), no_min (dist 0 kept);
MOVE no_float, float_down (always down); RANGE no_halve.
"""
import math
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import knockcode as KC
from doomfj import soulcode as SC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj, generate_trig_idioms_fj
from doomfj.reference_model import SLOPERANGE
from doomfj.sectorcode import msec_cell
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.wall_renderer import hoisted_scratch_fj
from doomfj.wad import Thing, WadFile
from doomfj.world import FIREBALL_POOL, FX_POOL, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
U = gd.FRACUNIT
NMOB = FIREBALL_POOL + FX_POOL
SOULS = [(-250, 240, 180), (-200, 300, 180), (-300, 200, 180)]
N_XY, N_Z, N_CHARGE, N_MOVE = 260, 260, 160, 160
pytestmark = pytest.mark.skipif(not (ROOT / "assets" / "freedoom1.wad").exists(), reason="needs the asset wad")


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def soul_wad():
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    base = mw.things
    mw.things = lambda name, base=base: base(name) + [Thing(x, y, a, 3006, 7) for x, y, a in SOULS]
    return mw


class Sv:
    """the harness world: the model, its cell sets and the runtime rows -- monster slot m is row m (the knock
    harness's layout), the mobiles NMOB rows, then the drops"""

    def __init__(self):
        from doomfj import lootcode as L
        from doomfj import monstermove as MM
        self.w = w = World(soul_wad(), "E1M1", skill=gd.SK_HARD, monsters="final", player="final")
        self.n = w.layout.nmon
        self.art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
        self.slots = L.pickup_slots(w, w.rm, w.mw, "E1M1", self.art)
        self.things, self.var = MM.static_blockers(w)
        self.drop = L.droppers(w)
        self.drop_rt = [self.n + NMOB + k for k in range(len(self.drop))]
        self.nrows = self.n + NMOB + len(self.drop)
        self.spots = _legal_spots(w)
        self.calls = []

    def record_damage(self):
        """the model's P_DamageMobj entries as recorders (the fj's are the dm_go / dp_go stubs)"""
        w, c = self.w, self

        def dm(i, dmg, src, inf, ev):
            c.calls.append("D%02x%02x%x%02x%s" % (1 + i, dmg, 3, 2 + src[1], c.kb(inf)))

        def db(b, dmg, src, ev):
            c.calls.append("D%02x%02x%x%02x%s" % (1 + w.layout.nmon + b, dmg, 3, 2 + src[1], "0"))

        def dp(dmg, src, inf, ev):
            c.calls.append("P%02x%02x%s" % (dmg, src[1] + 1, c.kb(inf)))
        w.damage_monster, w.damage_barrel, w.damage_player = dm, db, dp

    def kb(self, inf):
        """the inflictor the slam names (knockcode's interface): kb_on 1, the soul's whole units, its z"""
        ws = self.w.ws
        m = inf[1]
        return "1%04x%04x%04x" % (ws.mon_x[m] & 0xFFFF, ws.mon_y[m] & 0xFFFF,
                                  (ws.sk_z[self.w.soul_of[m]] >> 16) & 0xFFFF)


def _legal_spots(w):
    out = []
    for s, ss in enumerate(w.cmap.subsectors):
        segs = [w.cmap.segs[ss.firstseg + i] for i in range(ss.numsegs)]
        xs = [w.cmap.vertexes[g.v1][0] for g in segs]
        ys = [w.cmap.vertexes[g.v1][1] for g in segs]
        cx, cy = sum(xs) // len(xs), sum(ys) // len(ys)
        if w.rm.point_in_subsector(w.cmap, cx, cy) != s:
            continue
        ok, fz, cz = w.rm.check_position(w.scene_c, cx << 16, cy << 16)
        if ok and cz - fz >= 56 and w._solid_thing_at(cx << 16, cy << 16) is None:
            out.append((cx, cy))
    return out


def _ledges(w):
    """(x, y, ux, uy): 23 units in on the HIGH or the LOW side of a ledge (floors > 24 apart), and the unit step across"""
    out = []
    for ld in w.lds:
        if ld.back == -1:
            continue
        fs, bs = w.secs[w.sds[ld.front].sector], w.secs[w.sds[ld.back].sector]
        if abs(fs.floor_h - bs.floor_h) <= 24:
            continue
        (x1, y1), (x2, y2) = w.cmap.vertexes[ld.v1], w.cmap.vertexes[ld.v2]
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 48:
            continue
        nx, ny = (y2 - y1) / L, -(x2 - x1) / L
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        for sgn in (1, -1):
            out.append((int(mx + sgn * 23 * nx), int(my + sgn * 23 * ny), -sgn * nx, -sgn * ny))
    return out


# ================================================================================================================
# THE PROGRAM
# ================================================================================================================
MUTANTS = {
    # XY
    "no_slam": ("    hex.if0 1, sk_hit, skt_l\n", "    ;skt_l\n"),
    "slam_keeps": ("    hex.zero 1, sw_fly\n    hex.zero 8, sw_mz\n    hex.set 1, sk_lk, 1\n    ;skt_no\n",
                   "    hex.set 1, sk_lk, 1\n    ;skt_no\n"),
    "fly_friction": ("    hex.if1 1, sw_fly, kq_xout\n", ""),
    "air_friction": ("    hex.scmp 8, sw_z, kb_t, kq_nsk, kq_nsk, kq_xout\n", "    ;kq_nsk\n"),
    "slam_damage": ("    trclaw.lookup dp_dmg, sw_rng\n", "    trclaw.lookup dp_dmg, sw_rng\n    hex.inc 2, dp_dmg\n"),
    # Z
    "no_bounce": ("    hex.if0 1, sz_fly, szm_hf2\n", "    ;szm_hf2\n"),
    "float_sign": ("  szm_up:\n    hex.add_constant 8, sz_z, %d\n" % (4 << 16),
                   "  szm_up:\n    hex.add_constant 8, sz_z, %d\n" % (-(4 << 16) & M32)),
    "ceil_keep": ("    hex.if0 1, sz_fly, szm_o\n    hex.neg 8, sz_mz\n", "    ;szm_o\n"),
    # CHARGE
    "floor_div": ("    hex.if0 1, sc_neg, skc_o\n    hex.neg 8, sc_mz\n",
                  "    hex.if0 1, sc_neg, skc_o\n    hex.neg 8, sc_mz\n    hex.if0 4, sc_r8, skc_o\n"
                  "    hex.dec 8, sc_mz\n"),
    "no_min": ("    hex.set 4, sc_q, 1\n", "    hex.set 4, sc_q, 2\n"),
    # MOVE
    "no_float": ("    hex.if0 1, sk_fok, mm_rfd\n", "    ;mm_rfd\n"),
    "float_down": ("    hex.scmp 8, mm_skz, sk_t, mm_fu, mm_fd, mm_fd\n", "    ;mm_fd\n"),
    # RANGE
    "no_halve": ("    hex.shl_bit 4, mo_t4\n", ""),
}


def _program(c, mut=None):
    from doomfj import hurtcode as H
    from doomfj import lootcode as L
    from doomfj import monstercode as MC
    from doomfj import monsterdecide as MD
    from doomfj import monstermove as MM
    from doomfj import weaponcode as WC
    from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, cell_lists, collision_cells_fj,
                                  generate_point_location_fj, line_rows, monster_cells_fj, mover_line_openings,
                                  point_location_decls)
    from doomfj.doorcode import walkover_lines
    from doomfj.movercode import lift_walk_lines
    from doomfj.reference_model import ML_BLOCKING, PLAYER_RADIUS
    from doomfj.things import LEAF_LINK_DECLS, byte_array_decl, spawn_leaf_lists
    from doomfj.wall_renderer import DOOR_QUANT
    from doomfj.world import DROPOFF_MAX, STEP_UP
    w, n = c.w, c.n
    ws = w.ws
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    rows = line_rows(w.lds, w.cmap.vertexes, w.secs, w.sds, ML_BLOCKING, secs_open=kw["secs_open"],
                     door_line_ids=kw["door_line_ids"])
    obs = mover_line_openings(w.lds, w.sds, w.secs, kw["msecs"])
    movers = {li: (kw["mcell"][m_], obs[li]) for li in obs
              for m_ in [next(x for x in (w.sds[w.lds[li].front].sector, w.sds[w.lds[li].back].sector)
                              if x in kw["msecs"])]}
    lists, things = L.player_cell_things(w, cell_lists(rows, PLAYER_RADIUS))
    pcells, proot = collision_cells_fj("e1m1", rows, lists, doors=kw["doors"], movers=movers, things=things,
                                       thing_test=L.THING_TEST16)
    mcells, mroot = monster_cells_fj("e1m1", w.lds, w.cmap.vertexes, w.secs, w.sds, things=c.things, **kw)
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    lift_trigs = [(w.lift_order.index(tr[0]),) + tuple(tr[1:]) for tr in w.lift_walk_mon]
    after = (walkover_lines(w.walk_triggers, list(w.door_order), 16, prefix="kbwo")
             + lift_walk_lines(w.lift_walk, list(w.lift_order), 16, prefix="kblw"))
    thrust = "\n".join(KC.go_lines(KC.slots_of(w, list(range(n))), souls=dict(w.soul_of))) + chr(10)
    a = thrust.index("kb_pz:\n")
    kb_pz = thrust[a:thrust.index("    stl.fret kb_pzret\n", a) + len("    stl.fret kb_pzret\n")]
    dslot = {si: d for d, si in enumerate(w.door_order)}
    move = MM.move_leaf_lines(root=mroot, lift_trigs=lift_trigs,
                              door_boxes=[(dslot[si], w.mon_door_boxes[si]) for si in w.door_order
                                          if si in w.mon_door_boxes],
                              dropmax=DROPOFF_MAX, stepup=STEP_UP, height=56, soul=True)
    radii = [w.mon_radius[m] for m in range(n)]
    zs = [("soul", "sk_z + %d*dw" % (8 * w.soul_of[m])) if m in w.soul_of else ("floor", "mon_floorz + %d*dw" % (4 * m))
          for m in range(n)]
    decide = (MD.target_load_lines(list(range(n)), radii, zs) + MD.angle_leaf_lines() + MD.todist_leaf_lines(True)
              + MD.octant_leaf_lines() + MC.dist_leaf_lines())
    rng_lines = ["sk_range:"] + _range_lines() + ["  mm_dc_yes:", "    hex.set 1, rg_out, 1", "    stl.fret rg_ret",
                                                   "  mm_dc_mv:", "    hex.set 1, rg_out, 2", "    stl.fret rg_ret"]
    stubs = (["rt_unlink:", "    stl.fret rtu_ret"]
             + sum((["drop_take%d:" % k, "    hex.set 1, mdrop + %d*dw, 2" % k, "    hex.dec 2, dr_live",
                     "    stl.fret drt_ret"] for k in range(len(c.drop))), [])
             + ["pw_link:", "    sim.leaf_link pw_t, pw_leaf", "    stl.fret pw_lkret",
                "pw_unlink:", "    sim.leaf_unlink pw_t, pw_leaf", "    stl.fret pw_ulret",
                # P_DamageMobj, stubbed: what the slam named
                "dm_go:", "    stl.output 68",
                "    hex.print_as_digit 2, dm_id, 0", "    hex.print_as_digit 2, dm_dmg, 0",
                "    hex.print_as_digit 1, dm_melee, 0", "    hex.print_as_digit 2, dm_src, 0",
                "    hex.print_as_digit 1, kb_on, 0", "    hex.if0 1, kb_on, dmst_o",
                "    hex.print_as_digit 4, kb_ix, 0", "    hex.print_as_digit 4, kb_iy, 0",
                "    hex.print_as_digit 4, kb_iz, 0",
                "  dmst_o:", "    hex.zero 1, kb_on", "    stl.fret dm_ret",
                "dp_go:", "    stl.output 80",
                "    hex.print_as_digit 2, dp_dmg, 0", "    hex.print_as_digit 2, dp_src, 0",
                "    hex.print_as_digit 1, kb_on, 0",
                "    hex.print_as_digit 4, kb_ix, 0", "    hex.print_as_digit 4, kb_iy, 0",
                "    hex.print_as_digit 4, kb_iz, 0",
                "    hex.zero 1, kb_on", "    stl.fret dp_ret"])
    soul = SC.leaves(w, slot_rt=list(range(n)), mon_root=mroot, lift_trigs=lift_trigs, pick_slots=c.slots,
                     drop_rt=c.drop_rt, var=c.var)
    pick = L.pickup_lines(w, c.slots, list(range(n)), drop_rt=c.drop_rt)
    pb = L.pb_mon_lines(w, list(range(n)))
    things_leaf = MM.things_leaf_lines([(m, w.mon_radius[m]) for m in range(n)], solid="mon_solid", hurt=True)
    code = "\n".join(KC.cell_lines(proot) + KC.xy_lines(soul=True) + KC.ptry_lines(after)
                     + KC.mtry_lines(mroot, lift_trigs) + [kb_pz] + soul + decide + rng_lines + move
                     + pick + pb + things_leaf + seed + stubs) + "\n"
    if mut:
        old, new = MUTANTS[mut]
        assert code.count(old) == 1, (mut, code.count(old))
        code = code.replace(old, new)
    code += pcells + mcells
    nleaf = len(w.cmap.subsectors)
    head, nxt = spawn_leaf_lists([ws.mon_leaf[m] for m in range(n)] + [0] * (c.nrows - n), nleaf,
                                 present=[bool(ws.mon_active[m]) for m in range(n)] + [False] * (c.nrows - n))
    thpos = [((ws.mon_x[m] << 16) & M32) | (((ws.mon_y[m] << 16) & M32) << 32) for m in range(n)]
    vis = [1] * (c.slots["nvis"] + c.slots["nextra"])
    for i, s in enumerate(c.slots["slot"]):
        vis[s] = 1 - ws.pickup_taken[i]
    wstart = WC.level_start(w.mw, "E1M1")
    states, frames = WC.weapon_states(), WC.overlay_frames()
    nd, nl = len(w.door_order), len(w.lift_order)

    def vec(name, nib, vals):
        return "%s: hex.vec %d, %d" % (name, nib * len(vals), sum((v & (16 ** nib - 1)) << (4 * nib * i)
                                                                  for i, v in enumerate(vals)))
    decls = (KC.decls(n) + L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(wstart, states, frames) + COLLISION_STATE_DECLS + MON_CELL_DECLS
             + point_location_decls() + MM.monster_seed_decls() + MM.p32b_context(w.sec_nibbles) + LEAF_LINK_DECLS
             + SC.cell_decls(w, gd.SK_HARD) + SC.SCRATCH + list(MD.FIGHT_DECLS) + MD.context_decls()
             + ["pcard: hex.vec 1", "thvis:"] + ["    hex.vec 2, %d" % v for v in vis]
             + ["mdrop: hex.vec %d" % len(c.drop), "dr_live: hex.vec 2", "rtu_t: hex.vec w/4",
                "rtu_leaf: hex.vec w/4", "rtu_ret: hex.vec w/4", "drt_ret: hex.vec w/4",
                "viewx: hex.vec 8", "viewy: hex.vec 8",
                "thpos_rt: hex.vec %d, %d" % (16 * c.nrows, sum(v << (64 * t) for t, v in enumerate(thpos))),
                "thss_rt: hex.vec %d, %d" % (16 * c.nrows, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * c.nrows),
                vec("mon_solid", 1, [ws.mon_solid[m] for m in range(n)]),
                vec("mon_active", 1, [ws.mon_active[m] for m in range(n)]),
                vec("mon_shootable", 1, [ws.mon_shootable[m] for m in range(n)]),
                vec("mon_floorz", 4, [ws.mon_floorz[m] for m in range(n)]),
                vec("mon_rng", 2, [ws.mon_rng[m] for m in range(n)]),
                vec("msec", w.sec_nibbles, [w._mon_sector(m) for m in range(n)]),
                vec("bar_solid", 1, [ws.bar_solid[b] for b in range(len(w.barrel_things))]),
                "mc_don: hex.vec %d" % max(1, len(c.var)),
                "dstate: hex.vec %d" % nd, "ddir: hex.vec %d" % nd, "dreq: hex.vec %d" % nd,
                "wfired: hex.vec %d" % max(1, len(w.walk_triggers)),
                "lstate: hex.vec %d" % max(1, nl), "lreq: hex.vec %d" % max(1, nl), "fswitch: hex.vec 1",
                "pw_t: hex.vec w/4", "pw_leaf: hex.vec w/4", "pw_lkret: hex.vec w/4", "pw_ulret: hex.vec w/4",
                "dl_leaf: hex.vec 3", "dbox: hex.vec 8",
                "dm_id: hex.vec 2", "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2", "dm_ret: hex.vec w/4",

                "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
                "mt_t: hex.vec 4", "mt_ret: hex.vec w/4",
                vec("mon_target", 2, [ws.mon_target[m] for m in range(n)]),
                "rg_out: hex.vec 1", "rg_ret: hex.vec w/4"])
    tables = (L.tables_fj(w) + H.tables_fj(w.hwt)
              + [generate_point_location_fj(w.cmap),
                 generate_dispatch_table_fj("lfsec", list(w.leaf_sector), index_nibbles=3,
                                            result_nibbles=w.sec_nibbles),
                 generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry"),
                 generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
                 generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
                 generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)])
    return decls, code, tables


def _range_lines():
    lines = SC.decide_range_lines()
    return lines[1:]                     # its own label is the harness's entry


# ================================================================================================================
# THE RECORDS
# ================================================================================================================
def _place(c, m) -> list:
    """the model's slot m as it stands now, into the fj (the knock harness's, with the soul cells)"""
    w, ws = c.w, c.w.ws
    leaf = ws.mon_leaf[m]
    out = ["hex.set w/4, pw_t, %d" % m, "hex.zero w/4, pw_leaf", "hex.mov 3, pw_leaf, thss_rt + %d*dw" % (16 * m),
           "stl.fcall pw_unlink, pw_ulret",
           "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 4, ws.mon_x[m] & 0xFFFF),
           "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 12, ws.mon_y[m] & 0xFFFF),
           "hex.set 3, thss_rt + %d*dw, %d" % (16 * m, leaf), "hex.set w/4, pw_leaf, %d" % leaf]
    if ws.mon_active[m]:
        out.append("stl.fcall pw_link, pw_lkret")
    out += ["hex.set %d, %s, %d" % (w.sec_nibbles, msec_cell(m, w.sec_nibbles), w._mon_sector(m)),
            "hex.set 4, mon_floorz + %d*dw, %d" % (4 * m, ws.mon_floorz[m] & 0xFFFF),
            "hex.set 1, mon_solid + %d*dw, %d" % (m, ws.mon_solid[m]),
            "hex.set 1, mon_shootable + %d*dw, %d" % (m, ws.mon_shootable[m]),
            "hex.set 1, mon_active + %d*dw, %d" % (m, ws.mon_active[m]),
            "hex.set 4, mfx + %d*dw, %d" % (4 * m, ws.mon_fx[m]), "hex.set 4, mfy + %d*dw, %d" % (4 * m, ws.mon_fy[m]),
            "hex.set 8, mkx + %d*dw, %d" % (8 * m, ws.mon_momx[m] & M32),
            "hex.set 8, mky + %d*dw, %d" % (8 * m, ws.mon_momy[m] & M32),
            "hex.set 2, mon_rng + %d*dw, %d" % (2 * m, ws.mon_rng[m])]
    if m in w.soul_of:
        k = w.soul_of[m]
        out += ["hex.set 1, sk_fly + %d*dw, %d" % (k, ws.sk_fly[k]), "hex.set 1, sk_inf + %d*dw, %d" % (k, ws.sk_inf[k]),
                "hex.set 8, sk_z + %d*dw, %d" % (8 * k, ws.sk_z[k] & M32),
                "hex.set 8, sk_momz + %d*dw, %d" % (8 * k, ws.sk_momz[k] & M32),
                "hex.set 4, sk_ceil + %d*dw, %d" % (4 * k, ws.sk_ceil[k] & 0xFFFF)]
    return out


def _scene(w, rec):
    ws = w.ws
    for d, v in enumerate(rec["doors"]):
        ws.d_state[d] = v
    for k, v in enumerate(rec["lifts"]):
        ws.l_state[k] = v
    w._door_phase_scene()
    for k in range(len(w.lift_order)):
        ws.l_req[k] = 0
    for d in range(len(w.door_order)):
        ws.d_monreq[d] = 0


def _scene_lines(c, rec) -> list:
    w = c.w
    return (["hex.set 1, dstate + %d*dw, %d" % (d, v) for d, v in enumerate(rec["doors"])]
            + ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(rec["lifts"])]
            + ["hex.zero %d, lreq" % max(1, len(w.lift_order)), "hex.zero %d, dreq" % len(w.door_order)])


def _player_lines(c) -> list:
    ws = c.w.ws
    return ["hex.set 8, viewx, %d" % (ws.px & M32), "hex.set 8, viewy, %d" % (ws.py & M32),
            "hex.set 1, p_dead, %d" % ws.p_dead, "hex.set 3, p_hp, %d" % (ws.p_health & 0xFFF)]


def _setup(c, rnd, kind):
    """a random scene around soul 0: -> (rec, slots moved). The model is poked; the fj lines come from _place"""
    w, ws = c.w, c.w.ws
    m = w.soul_slots[rnd.randrange(len(w.soul_slots))]
    k = w.soul_of[m]
    rec = {"m": m, "doors": [rnd.choice((0, 0, rnd.randrange(w.door_nstates[si]))) for si in w.door_order],
           "lifts": [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]}
    _scene(w, rec)
    ang = rnd.uniform(0, 2 * math.pi)
    if kind == "ledge":
        x, y, ux, uy = rnd.choice(_ledges(w))
        ang = math.atan2(uy, ux) + rnd.uniform(-0.3, 0.3)
    elif kind == "lift" and w.lift_walk_mon:
        tr = rnd.choice(w.lift_walk_mon)
        coord, lo, hi, axis = tr[2], tr[3], tr[4], tr[1]
        t = rnd.randint(lo, hi)
        side = rnd.choice((-1, 1))
        x, y = ((coord + side * rnd.randint(2, 8), t) if axis == "x" else (t, coord + side * rnd.randint(2, 8)))
        ang = (0 if side < 0 else math.pi) if axis == "x" else (math.pi / 2 if side < 0 else -math.pi / 2)
    else:
        x, y = rnd.choice(c.spots)
        x, y = x + rnd.randint(-30, 30), y + rnd.randint(-30, 30)
    w.teleport_monster(m, x, y)
    ws.mon_fx[m], ws.mon_fy[m] = rnd.choice((0, 0, 0xFFFF, 0x8000, rnd.randrange(1 << 16))), rnd.randrange(1 << 16)
    moved = [m]
    ws.px, ws.py, ws.p_dead, ws.p_health = -(5000 << 16), -(5000 << 16), 0, 100
    near = rnd.choice(("none", "none", "player", "mon", "item", "barrel", "decor", "drop"))
    d = rnd.choice((30, 36, 40, 45, 52, 60))
    tx, ty = x + int(d * math.cos(ang)), y + int(d * math.sin(ang))
    if near == "player":
        ws.px, ws.py = (tx << 16) + rnd.randrange(1 << 16), (ty << 16) + rnd.randrange(1 << 16)
        if rnd.random() < 0.2:
            ws.p_dead, ws.p_health = 1, 0
    elif near == "mon":
        j = rnd.choice([j for j in range(c.n) if j != m and ws.mon_active[j]])
        w.teleport_monster(j, tx, ty)
        ws.mon_solid[j], ws.mon_shootable[j] = rnd.choice(((1, 1), (1, 1), (1, 0), (0, 0)))
        moved.append(j)
    elif near == "item":
        free = [i for i, t in enumerate(w.pickup_things) if not ws.pickup_taken[i]]
        i = rnd.choice(free)
        t = w.pickup_things[i]
        w.teleport_monster(m, t.x - int(d * math.cos(ang)), t.y - int(d * math.sin(ang)))
    elif near == "barrel":
        b = rnd.randrange(len(w.barrel_things))
        t = w.barrel_things[b]
        ws.bar_solid[b] = rnd.choice((1, 1, 0))
        w.teleport_monster(m, t.x - int(d * math.cos(ang)), t.y - int(d * math.sin(ang)))
        rec["bar"] = b
    elif near == "decor" and w.decor_solid:
        t = rnd.choice(w._decor_now)
        w.teleport_monster(m, t.x - int(d * math.cos(ang)), t.y - int(d * math.sin(ang)))
    elif near == "drop" and c.drop:
        kk = rnd.randrange(len(c.drop))
        j = c.drop[kk]
        if j != m and ws.mon_active[j]:
            ws.mon_drop[j] = 1
            ws.drop_x[j], ws.drop_y[j] = tx, ty
            rec["drop"] = kk
    rec["near"] = near
    return rec, moved, m, k, ang


def _fj_scene_extra(c, rec) -> list:
    w, ws = c.w, c.w.ws
    out = []
    if "bar" in rec:
        b = rec["bar"]
        out.append("hex.set 1, bar_solid + %d*dw, %d" % (b, ws.bar_solid[b]))
    if "drop" in rec:
        kk = rec["drop"]
        j = c.drop[kk]
        d = c.drop_rt[kk]
        out += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * d + 4, ws.drop_x[j] & 0xFFFF),
                "hex.set 4, thpos_rt + %d*dw, %d" % (16 * d + 12, ws.drop_y[j] & 0xFFFF),
                "hex.set 1, mdrop + %d*dw, 1" % kk]
    return out


def _undo_extra(c, rec) -> list:
    """the record's extra things gone again on both sides (barrels stand, the drop is no more)"""
    w, ws = c.w, c.w.ws
    out = []
    if "bar" in rec:
        ws.bar_solid[rec["bar"]] = 1
        out.append("hex.set 1, bar_solid + %d*dw, 1" % rec["bar"])
    if "drop" in rec:
        j = c.drop[rec["drop"]]
        ws.mon_drop[j] = 0
        out.append("hex.zero 1, mdrop + %d*dw" % rec["drop"])
    return out


def _xy_row(c, m, due):
    w, ws = c.w, c.w.ws
    k = w.soul_of[m]
    s = "%08x%08x%04x%04x%04x%04x%04x%03x" % (
        ws.mon_momx[m] & M32, ws.mon_momy[m] & M32, ws.mon_fx[m], ws.mon_fy[m], ws.mon_x[m] & 0xFFFF,
        ws.mon_y[m] & 0xFFFF, ws.mon_floorz[m] & 0xFFFF, ws.mon_leaf[m])
    s += "%0*x" % (w.sec_nibbles, w._mon_sector(m))
    s += "%02x" % sum(1 for j in range(c.n) if ws.mon_momx[j] or ws.mon_momy[j])
    s += "%x%08x%04x%02x%x" % (ws.sk_fly[k], ws.sk_momz[k] & M32, ws.sk_ceil[k] & 0xFFFF, ws.mon_rng[m], int(due))
    return s + "".join("%x" % ws.l_req[j] for j in range(len(w.lift_order)))


def _xy_print(c, m):
    w = c.w
    k = w.soul_of[m]
    return (["hex.print_as_digit 8, mkx + %d*dw, 0" % (8 * m), "hex.print_as_digit 8, mky + %d*dw, 0" % (8 * m),
             "hex.print_as_digit 4, mfx + %d*dw, 0" % (4 * m), "hex.print_as_digit 4, mfy + %d*dw, 0" % (4 * m),
             "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 4),
             "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 12),
             "hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m),
             "hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * m),
             "hex.print_as_digit %d, %s, 0" % (w.sec_nibbles, msec_cell(m, w.sec_nibbles)),
             "hex.print_as_digit 2, kb_live, 0",
             "hex.print_as_digit 1, sk_fly + %d*dw, 0" % k, "hex.print_as_digit 8, sk_momz + %d*dw, 0" % (8 * k),
             "hex.print_as_digit 4, sk_ceil + %d*dw, 0" % (4 * k), "hex.print_as_digit 2, mon_rng + %d*dw, 0" % (2 * m),
             "hex.print_as_digit 1, sk_lk, 0"]
            + ["hex.print_as_digit 1, lreq + %d*dw, 0" % j for j in range(len(w.lift_order))])


def _xy_records(c, rnd, body, want):
    w, ws = c.w, c.w.ws
    for r in range(N_XY):
        kind = rnd.choice(("open", "open", "open", "ledge", "lift", "near", "near"))
        rec, moved, m, k, ang = _setup(c, rnd, kind)
        mag = rnd.choice((20 * U, 20 * U, 15 * U, 15 * U + 1, 16 * U, 8 * U, 0x4001, 0x4000, 0x1000, 0xFFF,
                          rnd.randint(1, 31 * U)))
        mx, my = int(mag * math.cos(ang)), int(mag * math.sin(ang))
        if rnd.random() < 0.1:
            mx, my = (mx, 0) if rnd.random() < 0.5 else (0, my)
        if rnd.random() < 0.06:
            mx = my = 0                                   # flying and still: the stop
        ws.mon_momx[m], ws.mon_momy[m] = mx, my
        live = rnd.random() < 0.8
        ws.mon_shootable[m] = int(live)
        ws.mon_solid[m] = int(live or rnd.random() < 0.3)
        ws.sk_fly[k] = int(live and rnd.random() < 0.7) if (mx or my) else 1
        ws.sk_z[k] = (ws.mon_floorz[m] << 16) + rnd.choice((0, 0, rnd.randint(1, 40 << 16), 30 << 16))
        ws.sk_momz[k] = rnd.choice((0, rnd.randint(-6 << 16, 6 << 16)))
        ws.sk_ceil[k] = w.secs_c[w.leaf_sector[ws.mon_leaf[m]]].ceil_h
        body += _scene_lines(c, rec) + _fj_scene_extra(c, rec)
        body += sum((_place(c, j) for j in moved), []) + _player_lines(c)
        body += ["hex.set 2, kb_live, %d" % sum(1 for j in range(c.n) if ws.mon_momx[j] or ws.mon_momy[j])]
        c.calls = []
        due = w._soul_xy(m, TicEvents(0))
        body += ["stl.fcall sks%d, sks_ret" % k] + _xy_print(c, m) + ["stl.output 10"]
        want.append("".join(c.calls) + _xy_row(c, m, due))
        # both sides: the next record starts still, the extras gone
        ws.mon_momx[m] = ws.mon_momy[m] = 0
        body += ["hex.zero 8, mkx + %d*dw" % (8 * m), "hex.zero 8, mky + %d*dw" % (8 * m)] + _undo_extra(c, rec)


def _z_records(c, rnd, body, want):
    w, ws = c.w, c.w.ws
    for r in range(N_Z):
        rec, moved, m, k, ang = _setup(c, rnd, rnd.choice(("open", "ledge")))
        fl = ws.mon_floorz[m]
        ws.sk_ceil[k] = fl + rnd.choice((56, 57, 72, 100, rnd.randint(56, 200)))
        ws.sk_z[k] = (fl << 16) + rnd.choice((0, 0, rnd.randint(-6 << 16, 100 << 16), 1, -1))
        ws.sk_momz[k] = rnd.choice((0, 0, rnd.randint(-10 << 16, 10 << 16)))
        ws.sk_fly[k], ws.sk_inf[k] = int(rnd.random() < 0.4), int(rnd.random() < 0.2)
        ws.mon_shootable[m] = int(rnd.random() < 0.85)
        tg = rnd.choice(("none", "player", "player", "mon", "soul"))
        d = rnd.choice((rnd.randint(0, 100), rnd.randint(0, 600)))
        tx, ty = ws.mon_x[m] + int(d * math.cos(ang)), ws.mon_y[m] + int(d * math.sin(ang))
        if tg == "player":
            ws.mon_target[m] = 1
            ws.px, ws.py = (tx << 16) + rnd.randrange(1 << 16), (ty << 16) + rnd.randrange(1 << 16)
        elif tg in ("mon", "soul"):
            pool = ([j for j in w.soul_slots if j != m] if tg == "soul" else
                    [j for j in range(c.n) if j not in w.soul_of and ws.mon_active[j]])
            j = rnd.choice(pool)
            w.teleport_monster(j, tx, ty)
            if j in w.soul_of:
                ws.sk_z[w.soul_of[j]] = (ws.mon_floorz[j] + rnd.randint(0, 60)) << 16
            ws.mon_target[m] = 2 + j
            moved.append(j)
        else:
            ws.mon_target[m] = 0
        body += _scene_lines(c, rec) + sum((_place(c, j) for j in moved), []) + _player_lines(c)
        body += ["hex.set 2, mon_target + %d*dw, %d" % (2 * m, ws.mon_target[m])]
        w._soul_z(m)
        body += ["stl.fcall skz%d, skz_ret" % k, "hex.print_as_digit 8, sk_z + %d*dw, 0" % (8 * k),
                 "hex.print_as_digit 8, sk_momz + %d*dw, 0" % (8 * k), "stl.output 10"]
        want.append("%08x%08x" % (ws.sk_z[k] & M32, ws.sk_momz[k] & M32))


def _charge_records(c, rnd, body, want):
    w, ws = c.w, c.w.ws
    for r in range(N_CHARGE):
        rec, moved, m, k, ang = _setup(c, rnd, "open")
        ws.sk_z[k] = (ws.mon_floorz[m] << 16) + rnd.choice((0, rnd.randint(0, 80 << 16)))
        ws.sk_fly[k], ws.mon_momx[m], ws.mon_momy[m], ws.sk_momz[k] = 0, 0, 0, 0
        d = rnd.choice((0, 1, 10, 19, 20, 21, 39, 40, rnd.randint(0, 300), rnd.randint(0, 3000)))
        tx, ty = ws.mon_x[m] + int(d * math.cos(ang)), ws.mon_y[m] + int(d * math.sin(ang))
        if rnd.random() < 0.6:
            ws.mon_target[m] = 1
            ws.px, ws.py = (tx << 16) + rnd.randrange(1 << 16), (ty << 16) + rnd.randrange(1 << 16)
        else:
            j = rnd.choice([j for j in range(c.n) if j != m and ws.mon_active[j]])
            w.teleport_monster(j, tx, ty)
            if j in w.soul_of:
                ws.sk_z[w.soul_of[j]] = (ws.mon_floorz[j] + rnd.randint(0, 60)) << 16
            ws.mon_target[m] = 2 + j
            moved.append(j)
        body += _scene_lines(c, rec) + sum((_place(c, j) for j in moved), []) + _player_lines(c)
        w._a_skull_attack(m, TicEvents(0))
        body += ["hex.set 2, mm_tg, %d" % ws.mon_target[m], "stl.fcall mt_load, mt_lret",
                 "hex.mov 4, mm_x, thpos_rt + %d*dw" % (16 * m + 4), "hex.mov 4, mm_y, thpos_rt + %d*dw" % (16 * m + 12),
                 "stl.fcall mm_todist, mm_tdret", "stl.fcall mm_octant, mm_ocret",
                 "hex.mov 8, sc_z, sk_z + %d*dw" % (8 * k), "stl.fcall sk_charge, sk_cret",
                 "hex.print_as_digit 1, mm_fa, 0", "hex.print_as_digit 8, sc_mx, 0", "hex.print_as_digit 8, sc_my, 0",
                 "hex.print_as_digit 8, sc_mz, 0", "stl.output 10"]
        want.append("%x%08x%08x%08x" % (ws.mon_facing[m], ws.mon_momx[m] & M32, ws.mon_momy[m] & M32,
                                        ws.sk_momz[k] & M32))
        ws.mon_momx[m] = ws.mon_momy[m] = ws.sk_momz[k] = ws.sk_fly[k] = 0


def check_missile_range_ref(d, v):
    """P_CheckMissileRange's roll for MT_SKULL (no melee): attack? (p_enemy.c)"""
    dist = d - 64 - 128
    dist >>= 1
    if dist > 200:
        dist = 200
    return not v < dist


def _range_records(rnd, body, want):
    cases = [(d, v) for d in (0, 192, 193, 194, 195, 196, 400, 593, 594, 595, 596, 3000)
             for v in (0, 1, 199, 200, 201, 255)]
    cases += [(rnd.randint(0, 1500), rnd.randrange(256)) for _ in range(150)]
    for d, v in cases:
        body += ["hex.set 4, mt_d, %d" % d, "hex.set 2, mm_rr, %d" % v, "hex.zero 1, rg_out",
                 "stl.fcall sk_range, rg_ret", "hex.print_as_digit 1, rg_out, 0"]
        want.append("1" if check_missile_range_ref(d, v) else "2")
    body += ["stl.output 10"]
    want[-len(cases):] = ["".join(want[-len(cases):])]


def build(tmp_path, name, mut=None):
    """ONE program, every group's records (one assembly: the program is the game tier's move machinery)"""
    c = Sv()
    c.record_damage()
    decls, code, tables = _program(c, mut)              # the cells' initial values: the world BEFORE the records
    body, want = ["stl.startup_and_init_all"], []
    _xy_records(c, random.Random(0x5101), body, want)
    _z_records(c, random.Random(0x5102), body, want)
    _charge_records(c, random.Random(0x5103), body, want)
    _move_records_fixed(c, random.Random(0x5104), body, want)
    _range_records(random.Random(0x5105), body, want)
    body += ["stl.loop"]
    prog = "\n".join(body + decls + [code] + tables) + "\n" + hoisted_scratch_fj()
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, ("\n".join(want) + "\n").encode()


def _move_records_fixed(c, rnd, body, want):
    """MOVE with the direction chosen before the model moves (the fj reads the same one)"""
    w, ws = c.w, c.w.ws
    for r in range(N_MOVE):
        rec, moved, m, k, ang = _setup(c, rnd, rnd.choice(("ledge", "ledge", "open", "near", "lift")))
        d = rnd.randrange(8) if rnd.random() < 0.4 else int(round(((ang % (2 * math.pi)) / (math.pi / 4)))) % 8
        ws.mon_movedir[m] = d
        ws.sk_z[k] = (ws.mon_floorz[m] << 16) + rnd.choice((0, 0, rnd.randint(1, 40) << 16, rnd.randint(-8, 40) << 16))
        ws.sk_inf[k] = int(rnd.random() < 0.3)
        ws.sk_ceil[k] = w.secs_c[w.leaf_sector[ws.mon_leaf[m]]].ceil_h
        ws.mon_shootable[m] = ws.mon_solid[m] = 1
        body += _scene_lines(c, rec) + _fj_scene_extra(c, rec) + sum((_place(c, j) for j in moved), [])
        body += _player_lines(c)
        ok = w._p_move(m, TicEvents(0))
        body += ["hex.mov 4, mm_x, thpos_rt + %d*dw" % (16 * m + 4), "hex.mov 4, mm_y, thpos_rt + %d*dw" % (16 * m + 12),
                 "hex.mov 4, mm_z, mon_floorz + %d*dw" % (4 * m), "hex.sign_extend 8, 4, mm_z",
                 "hex.set 2, mm_r, 16", "hex.zero 1, mm_r30", "hex.zero 1, mm_spd", "hex.set 1, mm_dir, %d" % d,
                 "hex.set w/4, mm_tw, %d" % m, "hex.zero w/4, mm_leafw",
                 "hex.mov 3, mm_leafw, thss_rt + %d*dw" % (16 * m),
                 "hex.mov %d, mm_sec, %s" % (w.sec_nibbles, msec_cell(m, w.sec_nibbles)),
                 "hex.zero 1, mon_solid + %d*dw" % m,
                 *SC.move_context_lines(w, m, False),
                 "stl.fcall mm_move, mm_ret",
                 "hex.set 1, mon_solid + %d*dw, 1" % m,
                 "hex.mov 4, thpos_rt + %d*dw, mm_x" % (16 * m + 4), "hex.mov 4, thpos_rt + %d*dw, mm_y" % (16 * m + 12),
                 "hex.mov 4, mon_floorz + %d*dw, mm_z" % (4 * m), "hex.mov 3, thss_rt + %d*dw, mm_leafw" % (16 * m),
                 "hex.mov %d, %s, mm_sec" % (w.sec_nibbles, msec_cell(m, w.sec_nibbles)),
                 *SC.move_context_lines(w, m, True),
                 "hex.print_as_digit 1, mm_ok, 0", "hex.print_as_digit 1, mm_dir, 0",
                 "hex.print_as_digit 4, mm_x, 0", "hex.print_as_digit 4, mm_y, 0", "hex.print_as_digit 4, mm_z, 0",
                 "hex.print_as_digit 8, sk_z + %d*dw, 0" % (8 * k), "hex.print_as_digit 1, sk_inf + %d*dw, 0" % k,
                 "hex.print_as_digit 4, sk_ceil + %d*dw, 0" % (4 * k)]
        body += ["hex.print_as_digit 1, dreq + %d*dw, 0" % dd for dd in range(len(w.door_order))]
        body += ["hex.print_as_digit 1, lreq + %d*dw, 0" % j for j in range(len(w.lift_order))] + ["stl.output 10"]
        want.append("%x%x%04x%04x%04x%08x%x%04x" % (int(ok), ws.mon_movedir[m], ws.mon_x[m] & 0xFFFF,
                                                   ws.mon_y[m] & 0xFFFF, ws.mon_floorz[m] & 0xFFFF, ws.sk_z[k] & M32,
                                                   ws.sk_inf[k], ws.sk_ceil[k] & 0xFFFF)
                    + "".join("%x" % ws.d_monreq[dd] for dd in range(len(w.door_order)))
                    + "".join("%x" % ws.l_req[j] for j in range(len(w.lift_order))))
        body += _undo_extra(c, rec)


def run(tmp_path, name, mut=None) -> bool:
    srcs, want = build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


@pytest.mark.xfail(strict=True, reason="issue #153: the fj P_Move refuses 2 of 160 MOVE records the model accepts")
def test_the_soul_follows_the_model(tmp_path):
    assert run(tmp_path, "soul")


@pytest.mark.slow
@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_soul_is_caught(tmp_path, mut):
    assert not run(tmp_path, "soul_" + mut, mut)
