"""M7 P8a (docs/gp-final-plan.md 1.2.3 / 3.0 / 4.2): KNOCKBACK in fj -- package 0's interface, PACKAGE K's leaves.

Everything here is emitted ONLY when `world.knockback_on(PLAYER_MODE, MONSTER_MODE)` (wall_renderer's `_KNOCK`), so the
"full" / "full" game tier -- blocked51's text -- holds none of it (scratchpad/cr/emit_baseline.py --check). The model
is `combat.CombatMixin._thrust` / `_xy_move` / `_player_knock_try` / `_knock_slides` and `world.World.
_monster_knock_try`; their conventions (combat's "M7 P8a: KNOCKBACK" block) are this module's.

THE THRUST'S INTERFACE (every damage site sets it; `kb_go` reads it):

    kb_tg    2 nibbles   the TARGET: 0 the player, 1 + slot a monster (barrels are not pushed: O-B1)
    kb_dm    2 nibbles   the RAW damage, before the armor (dp_dmg / dm_dmg: both <= 255)
    kb_on    1 nibble    1: the hit has an INFLICTOR, at (kb_ix, kb_iy); 0: none (sector damage, DOOM's NULL) --
                         set by the site right before its damage call, ZEROED by the damage leaf on every exit
                         (dp_go's dp_out, dm_leaf's dm_out), so a site that names none is "no inflictor"
    kb_ix    4 nibbles   the inflictor's whole-unit position (the integer half of its 16.16: thpos_rt's nibbles 4-7 /
    kb_iy    4 nibbles   12-15, viewx / viewy + 4*dw, a fireball's pw_x / pw_y + 4*dw)
    kb_iz    4 nibbles   the inflictor's z (signed map units), for the reversal (G-B4) -- unread when kb_izp is 1
    kb_izp   1 nibble    1: the inflictor is the PLAYER -- his z (check_position's floorz) is computed only when the
                         reversal's first two conditions hold (`kb_pz`)
    kb_sp    1 nibble    1: the SOURCE is the player (the chainsaw's exception: `source->player`)
    kb_az    4 nibbles   the attacking monster's mon_floorz (monstercode's attack stub sets it before md_attack): the
                         inflictor z of its hitscan and melee, and its fireball's spawn z (pw_z = kb_az + 32)
    stl.fcall kb_go, kb_ret
`inflictor_lines` / `inflictor_const_lines` set kb_on, kb_ix, kb_iy, kb_iz (or kb_izp) and kb_sp at a site -- ALL of
them at every site (kb_go zeroes kb_sp and kb_izp on its exit, but a damage leaf that returns before kb_go leaves them
as the site set them).

THE SITES:
  * hurtcode.dp_lines -- dp_go (the player hit): after its "dead / health <= 0" returns and BEFORE the armor, kb_tg = 0,
    kb_dm = dp_dmg, kb_go; dp_out zeroes kb_on;
  * damagecode.leaf_lines -- dm_leaf (a monster hit): after its "not shootable / dead" returns and BEFORE the health,
    kb_dm = dm_dmg, kb_go; the inflictor is THE PLAYER for a shot (viewx / viewy, kb_izp, kb_sp) and the caller's
    for a BLAST; dm_out zeroes kb_on. The slot stubs dmg<m> (go_lines) set kb_tg = 1 + m;
  * barrelcode.blast_lines -- the barrel (bl_px / bl_py, its floor from `kbbz` by bl_b, the source the player who set
    it off: package I's bar_src replaces that) before its dp_go and before each slot's dmg<m>;
  * projcode.pj_lines -- the fireball's impact on the player: the MISSILE (pw_x / pw_y, not yet moved: P_TryMove's
    tmthing; its z pw_z) before its dp_go;
  * monsterdecide.attack_leaf_lines -- the monster's hitscan and melee on the player: the ATTACKER (mm_x / mm_y, z
    kb_az) before each dp_go.
  Nukage (lootcode) calls dp_go with kb_on 0: no thrust.

THE LEAVES (`leaf_lines`, one expansion each; per-slot code only in the slot stubs):
  * `kb_go`: no inflictor, or the source the player holding the saw -> nothing; the player -> the window from viewx /
    viewy, p_hp, rng_pl, mass 100, then p_kmx / p_kmy += the thrust; a monster -> a two-level jump on kb_tg to the
    slot's stub `kbt<m>` (its fraction, floorz, mass class and momentum; the health and the stream are dm_leaf's
    window dm_hp / dm_rng) and `kb_gm` (the thrust, the momentum, kb_live);
  * `kb_th`, the thrust on the window: the reversal's tests in C's order (damage < 40, damage > health, target z -
    inflictor z > 64 -- the player's z by `kb_pz` -- then ONE coin on kb_rng: `mrnd`'s bit v & 1), the angle by
    proj.point_to_angle (inflictor << 16 -> target 16.16; + ANG180 on an odd coin), cos / sin from `finesine`, the
    product damage * trig by hex.mul_lo, then an arithmetic shift right by 3 (mass 100) or 5 (400), 2 less reversed:
    FixedMul(damage * (FRACUNIT >> 3) * 100 / mass [* 4], trig) exactly;
  * `kb_xy`, P_XYMovement on the move window (kb_vx / kb_vy the momentum, kb_px / kb_py the 16.16 position): the clamp,
    one halved try then the rest (the do-while's at most two iterations: after one halving no axis exceeds
    MAXMOVE / 2), or one try; a refused try zeroes the momentum; then the corpse rule, the stop or the friction
    (29 * mom >> 5, arithmetic: FixedMul(mom, FRICTION)). `kb_try` jumps to the player's or the monster's try;
  * `kb_ptry` (the player's: the floor he stands on -- `kb_cell` at viewx / viewy -- into cm_hf, pk_go, pb_mon, the
    cells at the candidate, the opening (56, a dead player's 14) and the step; an accept moves him and runs the
    walk-over lines the emitter hands in) and `kb_mtry` (a monster's: the candidate's integer part where it stands ->
    accepted untested, else mm_things, the seed, the monster cells, the opening (56, a corpse's 14), the step and
    (not a corpse) the drop-off; an accept crosses the WR lifts, moves it, takes the floor and relinks it through
    projcode's pw_unlink / pw_link);
  * `kb_pmove` (the player's splice calls it) and `kb_mmove` (a slot stub `kbs<m>` calls it: the slot into the move
    context and back; kb_live - 1 when the momentum ends at 0).

THE CELLS (docs/gp-final-plan.md 4.1; `PERSIST`, build.KNOCK_PERSIST):

    p_kmx, p_kmy   8 nibbles       the player's KNOCK momentum (p_momx / p_momy), 16.16 a tic, signed
    mkx, mky       8 x nmon        a monster's momentum (mon_momx / mon_momy)
    mfx, mfy       4 x nmon        the fraction of its 16.16 position (mon_fx / mon_fy): thpos_rt keeps the integer
    kb_live        2               the count of slots whose momentum is not 0 -- the slot splice's fast skip
    pj_z           4 x FIREBALL_POOL  a fireball's z (proj_z): its shooter's floorz + 32
The drops' own positions (drop_x / drop_y) are the drop rows nt + 10 + k that drop_link<k> writes at the kill
(barrelcode) -- the pickup reads them (lootcode.pickup_lines(drop_rt=)).
"""
from __future__ import annotations

from typing import List, Sequence

from doomfj import gamedata as gd

M32 = 0xFFFFFFFF

# the persisted cells (build.KNOCK_PERSIST): docs/gp-final-plan.md 4.1
PERSIST: tuple = ("p_kmx", "p_kmy", "mkx", "mky", "mfx", "mfy", "kb_live", "pj_z")
# model field of each persisted cell (the gates' state check, the harnesses)
MODEL_FIELD = {"p_kmx": "p_momx", "p_kmy": "p_momy", "mkx": "mon_momx", "mky": "mon_momy", "mfx": "mon_fx",
               "mfy": "mon_fy", "pj_z": "proj_z"}
# the thrust's interface (the module docstring); scratch -- not persisted
KB_INTERFACE = ["kb_tg: hex.vec 2", "kb_dm: hex.vec 2", "kb_on: hex.vec 1", "kb_ix: hex.vec 4", "kb_iy: hex.vec 4",
                "kb_iz: hex.vec 4", "kb_ret: hex.vec w/4",
                "kb_izp: hex.vec 1", "kb_sp: hex.vec 1", "kb_az: hex.vec 4"]
# package K's scratch: the thrust window, the move window, the return registers (all set before read)
KB_SCRATCH = ["kb_tx: hex.vec 8", "kb_ty: hex.vec 8", "kb_i8x: hex.vec 8", "kb_i8y: hex.vec 8", "kb_hp: hex.vec 3",
              "kb_rng: hex.vec 2", "kb_tz: hex.vec 4", "kb_tzp: hex.vec 1", "kb_hv: hex.vec 1", "kb_rev: hex.vec 1",
              "kb_mx: hex.vec 8", "kb_my: hex.vec 8", "kb_ang: hex.vec 8", "kb_idx: hex.vec 3", "kb_cs: hex.vec 8",
              "kb_d8: hex.vec 8", "kb_rr: hex.vec 4", "kb_d4: hex.vec 4", "kb_c: hex.vec 8", "kb_t: hex.vec 8",
              "kb_was: hex.vec 1", "kb_pzv: hex.vec 4",
              "kb_vx: hex.vec 8", "kb_vy: hex.vec 8", "kb_xm: hex.vec 8", "kb_ym: hex.vec 8", "kb_px: hex.vec 8",
              "kb_py: hex.vec 8", "kb_cx: hex.vec 8", "kb_cy: hex.vec 8", "kb_ok: hex.vec 1", "kb_who: hex.vec 1",
              "kb_dead: hex.vec 1", "kb_ht: hex.vec 8", "kb_sv: hex.vec 1", "kb_lf: hex.vec w/4",
              "kb_tret: hex.vec w/4", "kb_pzret: hex.vec w/4", "kb_gmret: hex.vec w/4", "kb_xyret: hex.vec w/4",
              "kb_tyret: hex.vec w/4", "kb_cret: hex.vec w/4", "kb_mret: hex.vec w/4", "kb_pret: hex.vec w/4",
              "kbs_ret: hex.vec w/4",
              "pw_z: hex.vec 4"]              # projcode's window: the fireball's z (pj_lines(knock=True))

STOPSPEED, FRICTION, MAXMOVE = gd.STOPSPEED, gd.FRICTION, gd.MAXMOVE
CORPSE_QUARTER = gd.FRACUNIT // 4          # P_XYMovement's corpse rule: |mom| > FRACUNIT/4
REVERSE_DMG, REVERSE_DZ = 40, 64           # P_DamageMobj: damage < 40, target->z - inflictor->z > 64*FRACUNIT
MASS_SHIFT = {100: 3, 400: 5}              # FixedMul(dmg * (FRACUNIT >> 3) * 100 / mass, trig) == dmg * trig >> this


def check_model_rules(w=None) -> None:
    """the constants the fj bakes, against their sources: FRICTION is 29/32 (the shift-add), every mass a class of
    MASS_SHIFT, MAXMOVE / 2 a whole 16.16 value, the angle's fine shift 20 (kb_ang + 5*dw); a monster height of 56
    (a corpse 14) and every radius 20 or 30 (monstermove's context)"""
    assert FRICTION * 32 == 29 << 16, "the friction is the shift-add 29 * mom >> 5"
    assert MAXMOVE % 2 == 0 and STOPSPEED == 0x1000 and CORPSE_QUARTER == 0x4000
    assert gd.MOBJINFO["MT_PLAYER"].mass == 100
    for mass, sh in MASS_SHIFT.items():
        assert all(d * (gd.FRACUNIT >> 3) * 100 // mass == d << (16 - sh) for d in range(256)), mass
    if w is not None:
        assert w.rm.angle_shift == 20, "kb_idx is kb_ang's top 3 nibbles"
        n = w.layout.nmon
        assert {w.mon_info[m].mass for m in range(n)} <= set(MASS_SHIFT)
        assert set(w.mon_height[:n]) == {56} and set(w.mon_radius[:n]) <= {20, 30}
        from doomfj.combat import PLAYER_R
        from doomfj.reference_model import PLAYER_HEIGHT
        assert PLAYER_R == 16 and PLAYER_HEIGHT >> 16 == 56


def persisted_decls(nmon: int, pool: int = None) -> List[str]:
    """the persisted cells at their level start (all 0)"""
    if pool is None:
        from doomfj.world import FIREBALL_POOL as pool
    return ["p_kmx: hex.vec 8", "p_kmy: hex.vec 8", "mkx: hex.vec %d" % (8 * nmon), "mky: hex.vec %d" % (8 * nmon),
            "mfx: hex.vec %d" % (4 * nmon), "mfy: hex.vec %d" % (4 * nmon), "kb_live: hex.vec 2",
            "pj_z: hex.vec %d" % (4 * pool)]


def decls(nmon: int = None, pool: int = None) -> List[str]:
    """the interface registers; with `nmon` (package K) the persisted cells and the scratch too"""
    if nmon is None:
        return list(KB_INTERFACE)
    return list(KB_INTERFACE) + persisted_decls(nmon, pool) + list(KB_SCRATCH)


def restart_lines(nmon: int, pool: int = None) -> List[str]:
    """NEW GAME / the restart: every knock cell at its level start, 0"""
    return ["    hex.zero %s, %s" % (d.split("hex.vec ")[1].split(",")[0], d.split(":")[0])
            for d in persisted_decls(nmon, pool)]


def barrel_floor_values(w) -> List[int]:
    """`kbbz[b]`: barrel b's z, its sector's floor (combat._knock_z: barrels never move, no mover holds one)"""
    floors = [w._floor_at(t.x, t.y) for t in w.barrel_things]
    for t in w.barrel_things:
        sec = w.leaf_sector[w.rm.point_in_subsector(w.cmap, t.x, t.y)]
        assert sec not in w.mover_order, "a barrel on a mover: its z would move"
    return [f & 0xFFFF for f in floors]


def tables_fj(w) -> List[str]:
    """`kbbz` (barrel b's z) -- the knock's one table; the emit-time asserts run here (`check_model_rules`)"""
    from doomfj.lut_generator import generate_dispatch_table_fj
    check_model_rules(w)
    vals = barrel_floor_values(w)
    return [generate_dispatch_table_fj("kbbz", vals or [0], index_nibbles=2, result_nibbles=4)]


# ---- a site's inflictor ----------------------------------------------------------------------------------------------
def _site_flags(z, z_lines, z_player: bool, src_player: bool) -> List[str]:
    out = []
    if z is not None:
        out.append("    hex.mov 4, kb_iz, %s" % z)
    out += list(z_lines or ())
    out.append("    hex.set 1, kb_izp, 1" if z_player else "    hex.zero 1, kb_izp")
    out.append("    hex.set 1, kb_sp, 1" if src_player else "    hex.zero 1, kb_sp")
    return out


def inflictor_lines(x: str, y: str, *, z: str = None, z_lines=None, z_player: bool = False,
                    src_player: bool = False) -> List[str]:
    """a site's inflictor: kb_on = 1 and the whole-unit position from the 4-nibble integer cells `x`, `y`; its z from
    the 4-nibble cell `z` (or the `z_lines` that set kb_iz, or `z_player`: computed from the player's position when
    needed); `src_player`: the source is the player (the chainsaw's exception)"""
    return (["    hex.set 1, kb_on, 1", "    hex.mov 4, kb_ix, %s" % x, "    hex.mov 4, kb_iy, %s" % y]
            + _site_flags(z, z_lines, z_player, src_player))


def inflictor_const_lines(x: int, y: int, *, z: int = 0, src_player: bool = False) -> List[str]:
    """a site's inflictor at a position known at emit time (a barrel: barrels never move)"""
    return (["    hex.set 1, kb_on, 1", "    hex.set 4, kb_ix, %d" % (x & 0xFFFF),
             "    hex.set 4, kb_iy, %d" % (y & 0xFFFF), "    hex.set 4, kb_iz, %d" % (z & 0xFFFF)]
            + _site_flags(None, None, False, src_player))


# ---- small helpers ---------------------------------------------------------------------------------------------------
def _sar(cell: str, k: int, tag: str) -> List[str]:
    """cell[:8] >>= k, ARITHMETIC (a negative value: ~((~v) >> k))"""
    sh = ["    hex.shr_bit 8, %s" % cell] * k
    return (["    hex.if_flags %s + 7*dw, 0xFF00, %s_p, %s_n" % (cell, tag, tag),
             "  %s_n:" % tag, "    hex.not 8, %s" % cell] + sh + ["    hex.not 8, %s" % cell, "    ;%s_d" % tag,
                                                                 "  %s_p:" % tag] + sh + ["  %s_d:" % tag])


def _half_trunc(dst: str, src: str, tag: str) -> List[str]:
    """dst = src / 2, C's truncation toward zero: a negative src is (src + 1) >> 1"""
    return (["    hex.mov 8, %s, %s" % (dst, src),
             "    hex.if_flags %s + 7*dw, 0xFF00, %s_s, %s_i" % (dst, tag, tag),
             "  %s_i:" % tag, "    hex.inc 8, %s" % dst,
             "  %s_s:" % tag] + _sar(dst, 1, tag + "a"))


def _clamp(cell: str, tag: str) -> List[str]:
    """cell = max(-MAXMOVE, min(MAXMOVE, cell)), signed"""
    return ["    hex.set 8, kb_c, %d" % MAXMOVE,
            "    hex.scmp 8, %s, kb_c, %s_lo, %s_lo, %s_hi" % (cell, tag, tag, tag),
            "  %s_hi:" % tag, "    hex.mov 8, %s, kb_c" % cell, "    ;%s_ok" % tag,
            "  %s_lo:" % tag, "    hex.set 8, kb_c, %d" % (-MAXMOVE & M32),
            "    hex.scmp 8, %s, kb_c, %s_set, %s_ok, %s_ok" % (cell, tag, tag, tag),
            "  %s_set:" % tag, "    hex.mov 8, %s, kb_c" % cell,
            "  %s_ok:" % tag]


def _abs_cmp(cell: str, bound: int, lt: str, ge_eq: str, gt: str, tag: str) -> List[str]:
    """|cell| (8 nibbles) against an unsigned bound: to lt / eq / gt"""
    return ["    hex.mov 8, kb_t, %s" % cell, "    hex.abs 8, kb_t", "    hex.set 8, kb_c, %d" % bound,
            "    hex.cmp 8, kb_t, kb_c, %s, %s, %s" % (lt, ge_eq, gt)]


def _friction(cell: str, tag: str) -> List[str]:
    """cell = FixedMul(cell, FRICTION) = (29 * cell) >> 5, arithmetic: 32v - 3v, then the shift"""
    return (["    hex.mov 8, kb_c, %s" % cell, "    hex.shl_hex 8, kb_c", "    hex.shl_bit 8, kb_c",
             "    hex.mov 8, kb_t, %s" % cell, "    hex.add 8, kb_t, %s" % cell, "    hex.add 8, kb_t, %s" % cell,
             "    hex.mov 8, %s, kb_c" % cell, "    hex.sub 8, %s, kb_t" % cell]
            + _sar(cell, 5, tag))


# ---- kb_go and the thrust --------------------------------------------------------------------------------------------
def go_lines(slots: Sequence[tuple] = None) -> List[str]:
    """`kb_go` (stl.fcall kb_go, kb_ret), its slot stubs `kbt<m>`, `kb_gm` and the thrust `kb_th` (+ `kb_pz`, the
    player's z). `slots[m]` = (runtime thing, radius, mass) per monster slot. PACKAGE 0's STUB without `slots`"""
    if slots is None:
        return ["// M7 P8a (doomfj.knockcode): P_DamageMobj's thrust -- package 0's stub, package K's leaf",
                "kb_go:",
                "    stl.fret kb_ret"]
    n = len(slots)
    assert 0 < n < 255
    nh = n // 16 + 1                                      # kb_tg 1 .. n
    out = ["// M7 P8a (doomfj.knockcode, package K): P_DamageMobj's thrust",
           "kb_go:",
           "    hex.if0 1, kb_on, kq_out",                                    # no inflictor: nothing
           "    hex.if0 1, kb_sp, kq_ns",
           "    hex.if_flags wp_rdy, %d, kq_ns, kq_out" % (1 << gd.WP_CHAINSAW),   # the player holding the saw
           "  kq_ns:",
           "    hex.zero 4, kb_i8x", "    hex.mov 4, kb_i8x + 4*dw, kb_ix",
           "    hex.zero 4, kb_i8y", "    hex.mov 4, kb_i8y + 4*dw, kb_iy",
           "    hex.if1 2, kb_tg, kq_mon",
           # ---- the player: his 16.16 position, health, stream; mass 100; his z when needed
           "    hex.mov 8, kb_tx, viewx", "    hex.mov 8, kb_ty, viewy",
           "    hex.mov 3, kb_hp, p_hp", "    hex.mov 2, kb_rng, rng_pl",
           "    hex.set 1, kb_tzp, 1", "    hex.zero 1, kb_hv",
           "    stl.fcall kb_th, kb_tret",
           "    hex.mov 2, rng_pl, kb_rng",
           "    hex.add 8, p_kmx, kb_mx", "    hex.add 8, p_kmy, kb_my",
           "    ;kq_out",
           # ---- a monster: dm_leaf's window holds its health, stream and whole-unit position
           "  kq_mon:",
           "    hex.mov 3, kb_hp, dm_hp", "    hex.mov 2, kb_rng, dm_rng", "    hex.zero 1, kb_tzp",
           "    sim.jump16 kb_tg + 1*dw, " + ", ".join("kq_h%d" % h if h < nh else "kq_out" for h in range(16))]
    for h in range(nh):
        out += ["  kq_h%d:" % h, "    sim.jump16 kb_tg, " + ", ".join(
            "kbt%d" % (16 * h + l - 1) if 1 <= 16 * h + l <= n else "kq_out" for l in range(16))]
    for m, (rt, _r, mass) in enumerate(slots):
        out += ["  kbt%d:" % m,
                "    hex.mov 4, kb_tx, mfx + %d*dw" % (4 * m), "    hex.mov 4, kb_tx + 4*dw, dm_x",
                "    hex.mov 4, kb_ty, mfy + %d*dw" % (4 * m), "    hex.mov 4, kb_ty + 4*dw, dm_y",
                "    hex.mov 4, kb_tz, mon_floorz + %d*dw" % (4 * m),
                "    hex.set 1, kb_hv, %d" % int(MASS_SHIFT[mass] == 5),
                "    hex.mov 8, kb_vx, mkx + %d*dw" % (8 * m), "    hex.mov 8, kb_vy, mky + %d*dw" % (8 * m),
                "    stl.fcall kb_gm, kb_gmret",
                "    hex.mov 8, mkx + %d*dw, kb_vx" % (8 * m), "    hex.mov 8, mky + %d*dw, kb_vy" % (8 * m),
                "    ;kq_out"]
    out += ["  kq_out:",
            "    hex.zero 1, kb_sp", "    hex.zero 1, kb_izp",
            "    stl.fret kb_ret",
            # ---- a monster target: the thrust into its momentum window, the stream back, kb_live kept
            "kb_gm:",
            "    hex.zero 1, kb_was",
            "    hex.if1 8, kb_vx, kq_gw", "    hex.if0 8, kb_vy, kq_gt",
            "  kq_gw:", "    hex.set 1, kb_was, 1",
            "  kq_gt:",
            "    stl.fcall kb_th, kb_tret",
            "    hex.mov 2, dm_rng, kb_rng",
            "    hex.add 8, kb_vx, kb_mx", "    hex.add 8, kb_vy, kb_my",
            "    hex.if1 8, kb_vx, kq_gn", "    hex.if1 8, kb_vy, kq_gn",
            "    hex.if0 1, kb_was, kq_gr",                                   # 0 -> 0: no change
            "    hex.dec 2, kb_live", "    ;kq_gr",                           # moving -> stopped (a cancelling hit)
            "  kq_gn:",
            "    hex.if1 1, kb_was, kq_gr",
            "    hex.inc 2, kb_live",                                         # stopped -> moving
            "  kq_gr:",
            "    stl.fret kb_gmret"]
    out += thrust_lines()
    return out


def thrust_lines() -> List[str]:
    """`kb_th` (stl.fcall kb_th, kb_tret) on the window -- kb_tx / kb_ty (the target, 16.16), kb_i8x / kb_i8y (the
    inflictor << 16), kb_dm, kb_hp (health > 0), kb_rng (the target's stream), kb_tz / kb_tzp (its z, or the player's),
    kb_iz / kb_izp, kb_hv (mass 400) -- into kb_mx / kb_my (the momentum to add); and `kb_pz` (kb_pzv = the player's
    check_position floorz: `kb_cell` at viewx / viewy)"""
    return ["kb_th:",
            "    hex.zero 1, kb_rev",
            # the reversal, C's order: damage < 40 ...
            "    hex.set 2, kb_c, %d" % REVERSE_DMG,
            "    hex.cmp 2, kb_dm, kb_c, kq_r1, kq_nr, kq_nr",
            "  kq_r1:",                                                       # ... damage > health (health > 0) ...
            "    hex.if1 1, kb_hp + 2*dw, kq_nr",
            "    hex.cmp 2, kb_dm, kb_hp, kq_nr, kq_nr, kq_r2",
            "  kq_r2:",                                                       # ... target z - inflictor z > 64 ...
            "    hex.if0 1, kb_tzp, kq_r2t",
            "    stl.fcall kb_pz, kb_pzret", "    hex.mov 4, kb_tz, kb_pzv",
            "  kq_r2t:",
            "    hex.if0 1, kb_izp, kq_r2i",
            "    stl.fcall kb_pz, kb_pzret", "    hex.mov 4, kb_iz, kb_pzv",
            "  kq_r2i:",
            "    hex.mov 4, kb_d4, kb_tz", "    hex.sub 4, kb_d4, kb_iz",
            "    hex.set 4, kb_c, %d" % REVERSE_DZ,
            "    hex.scmp 4, kb_d4, kb_c, kq_nr, kq_nr, kq_r3",
            "  kq_r3:",                                                       # ... and the coin, P_Random() & 1
            "    hex.inc 2, kb_rng", "    mrnd.lookup kb_rr, kb_rng",
            "    hex.if_flags kb_rr + 2*dw, %d, kq_nr, kq_rv" % 0b1100110011001100,   # mrnd's bit 9: v & 1
            "  kq_rv:", "    hex.set 1, kb_rev, 1",
            "  kq_nr:",
            "    proj.point_to_angle kb_ang, kb_i8x, kb_i8y, kb_tx, kb_ty, 1",
            "    hex.if0 1, kb_rev, kq_a",
            "    hex.xor_by kb_ang + 7*dw, 8",                                # + ANG180
            "  kq_a:",
            "    hex.mov 3, kb_idx, kb_ang + 5*dw",                           # the fine angle: angle >> 20
            "    hex.zero 8, kb_d8", "    hex.mov 2, kb_d8, kb_dm",
            "    finesine.read_cos kb_cs, kb_idx",
            "    hex.mul_lo 8, kb_mx, kb_cs, kb_d8",
            "    finesine.read_sin kb_cs, kb_idx",
            "    hex.mul_lo 8, kb_my, kb_cs, kb_d8",
            # >> 3 (mass 100) or 5 (400), 2 less reversed (the thrust x4)
            *_sar("kb_mx", 1, "kq_s1x"), *_sar("kb_my", 1, "kq_s1y"),
            "    hex.if1 1, kb_rev, kq_s2",
            *_sar("kb_mx", 2, "kq_s2x"), *_sar("kb_my", 2, "kq_s2y"),
            "  kq_s2:",
            "    hex.if0 1, kb_hv, kq_s3",
            *_sar("kb_mx", 2, "kq_s3x"), *_sar("kb_my", 2, "kq_s3y"),
            "  kq_s3:",
            "    stl.fret kb_tret",
            "kb_pz:",
            "    hex.mov 8, cpx, viewx", "    hex.mov 8, cpy, viewy",
            "    stl.fcall kb_cell, kb_cret",
            "    hex.mov 4, kb_pzv, cp_floor",
            "    stl.fret kb_pzret"]


# ---- the moves -------------------------------------------------------------------------------------------------------
def cell_lines(player_root: str) -> List[str]:
    """`kb_cell` (stl.fcall kb_cell, kb_cret): the player's P_CheckPosition at (cpx, cpy) -- the seed by the point
    location and `ms_seed_leaf` (the sector under the integer position: doors open, movers where they stand -- what
    the walk's seed descent gives, tests/fj/test_player_move_fj's stand-in) and the player's cells: cp_ok, cp_floor,
    cp_ceil, cp_seedf"""
    return ["kb_cell:",
            "    hex.zero 10, ptx", "    hex.mov 4, ptx, cpx + 4*dw", "    hex.sign_extend 10, 4, ptx",
            "    hex.zero 10, pty", "    hex.mov 4, pty, cpy + 4*dw", "    hex.sign_extend 10, 4, pty",
            "    stl.fcall ptloc_walk, ptloc_ret",
            "    stl.fcall ms_seed_leaf, ms_seed_ret",
            "    hex.set 8, cprad, %d" % (16 << 16),
            "    sim.check_cells %s" % player_root,
            "    stl.fret kb_cret"]


def xy_lines() -> List[str]:
    """`kb_xy` (stl.fcall kb_xy, kb_xyret): P_XYMovement on the move window (combat._xy_move)"""
    def try_at(tag):
        return ["    stl.fcall kb_try, kb_tyret",
                "    hex.if1 1, kb_ok, %s" % tag,
                "    hex.zero 8, kb_vx", "    hex.zero 8, kb_vy",            # refused: the momentum stops
                "  %s:" % tag]
    out = ["kb_xy:",
           *_clamp("kb_vx", "kq_cx"), *_clamp("kb_vy", "kq_cy"),
           "    hex.mov 8, kb_xm, kb_vx", "    hex.mov 8, kb_ym, kb_vy",
           # xmove > MAXMOVE/2 || ymove > MAXMOVE/2 (signed: a negative move is never halved)
           "    hex.set 8, kb_c, %d" % (MAXMOVE // 2),
           "    hex.scmp 8, kb_xm, kb_c, kq_hy, kq_hy, kq_half",
           "  kq_hy:",
           "    hex.scmp 8, kb_ym, kb_c, kq_full, kq_full, kq_half",
           "  kq_half:",                                                      # x + xmove/2, then xmove >>= 1
           *_half_trunc("kb_cx", "kb_xm", "kq_tx"), "    hex.add 8, kb_cx, kb_px",
           *_half_trunc("kb_cy", "kb_ym", "kq_ty"), "    hex.add 8, kb_cy, kb_py",
           *_sar("kb_xm", 1, "kq_hx"), *_sar("kb_ym", 1, "kq_hy2"),
           *try_at("kq_t1"),
           # the second (and last) iteration: no axis is above MAXMOVE/2 now, and one is not 0
           "  kq_full:",
           "    hex.mov 8, kb_cx, kb_px", "    hex.add 8, kb_cx, kb_xm",
           "    hex.mov 8, kb_cy, kb_py", "    hex.add 8, kb_cy, kb_ym",
           *try_at("kq_t2"),
           # the corpse rule: no friction while |mom| > FRACUNIT/4 on an axis and floorz is not the leaf's floor
           "    hex.if0 1, kb_dead, kq_stop",
           *_abs_cmp("kb_vx", CORPSE_QUARTER, "kq_cr1", "kq_cr1", "kq_crf", "kq_c1"),
           "  kq_cr1:",
           *_abs_cmp("kb_vy", CORPSE_QUARTER, "kq_stop", "kq_stop", "kq_crf", "kq_c2"),
           "  kq_crf:",
           "    hex.if1 1, kb_who, kq_crm",
           "    hex.mov 8, cpx, viewx", "    hex.mov 8, cpy, viewy",          # the player: his box's floorz ...
           "    stl.fcall kb_cell, kb_cret",
           "    hex.cmp 8, cp_floor, cp_seedf, kq_out, kq_stop, kq_out",     # ... against his leaf's floor
           "  kq_crm:",                                                       # a monster: its floorz ...
           "    hex.zero w/4, ptss", "    hex.mov 3, ptss, mm_leafw",
           "    stl.fcall ms_seed_leaf, ms_seed_ret",
           "    hex.cmp 8, mm_z, cp_seedf, kq_out, kq_stop, kq_out",         # ... against its leaf's floor
           # the stop, or the friction
           "  kq_stop:",
           *_abs_cmp("kb_vx", STOPSPEED, "kq_sy", "kq_fr", "kq_fr", "kq_s1"),
           "  kq_sy:",
           *_abs_cmp("kb_vy", STOPSPEED, "kq_zero", "kq_fr", "kq_fr", "kq_s2"),
           "  kq_zero:",
           "    hex.zero 8, kb_vx", "    hex.zero 8, kb_vy", "    ;kq_out",
           "  kq_fr:",
           *_friction("kb_vx", "kq_frx"), *_friction("kb_vy", "kq_fry"),
           "  kq_out:",
           "    stl.fret kb_xyret",
           "kb_try:",
           "    hex.if1 1, kb_who, kb_mtry",
           "    ;kb_ptry"]
    return out


def ptry_lines(after_accept: Sequence[str] = ()) -> List[str]:
    """`kb_ptry` (via kb_try; frets kb_tyret): the player's knock try at (kb_cx, kb_cy) -- combat._player_knock_try.
    `after_accept`: the walk-over lines (doorcode.walkover_lines / movercode.lift_walk_lines with their own prefix),
    run on an accept with the move in (cm_ox, cm_oy) -> (viewx, viewy)"""
    return ["kb_ptry:",
            "    hex.zero 1, kb_ok",
            "    hex.mov 8, cpx, viewx", "    hex.mov 8, cpy, viewy",          # the floor he stands on
            "    stl.fcall kb_cell, kb_cret",
            "    hex.mov 8, cm_hf, cp_floor",
            "    hex.mov 8, cpx, kb_cx", "    hex.mov 8, cpy, kb_cy",
            "    stl.fcall pk_go, pk_ret",                                     # pickups (pk_go: a dead player none)
            "    stl.fcall pb_mon, pb_ret",                                    # a solid monster refuses
            "    hex.if1 1, pb_hit, kq_pno",
            "    stl.fcall kb_cell, kb_cret",                                  # the lines and the static blockers
            "    hex.if0 1, cp_ok, kq_pno",
            "    hex.mov 8, kb_t, cp_ceil", "    hex.sub 8, kb_t, cp_floor",   # the opening fits him
            "    hex.scmp 8, kb_t, kb_ht, kq_pno, kq_pst, kq_pst",
            "  kq_pst:",
            "    hex.mov 8, kb_t, cp_floor", "    hex.sub 8, kb_t, cm_hf",     # no step up of more than 24
            "    hex.set 8, kb_c, %d" % (gd.MAX_STEP_UP >> 16),
            "    hex.scmp 8, kb_t, kb_c, kq_pok, kq_pok, kq_pno",
            "  kq_pok:",
            "    hex.mov 8, cm_ox, viewx", "    hex.mov 8, cm_oy, viewy",
            "    hex.mov 8, viewx, kb_cx", "    hex.mov 8, viewy, kb_cy",
            "    hex.mov 8, kb_px, kb_cx", "    hex.mov 8, kb_py, kb_cy",
            *after_accept,
            "    hex.set 1, kb_ok, 1",
            "  kq_pno:",
            "    stl.fret kb_tyret"]


def mtry_lines(mon_root: str, lift_trigs=()) -> List[str]:
    """`kb_mtry` (via kb_try; frets kb_tyret): a monster's knock try at (kb_cx, kb_cy) -- world._monster_knock_try --
    on monstermove's context (mm_x, mm_y, mm_z, mm_r, mm_r30, mm_tw, mm_leafw, mm_sec: the slot stub set them).
    `mon_root`: the monster cells; `lift_trigs`: [(lift slot, axis, coord, lo, hi)] (monstermove.move_leaf_lines')"""
    from doomfj.doorcode import _crossed_lines
    from doomfj.world import DROPOFF_MAX, STEP_UP
    out = ["kb_mtry:",
           "    hex.set 1, kb_ok, 1",
           "    hex.cmp 4, kb_cx + 4*dw, mm_x, kq_mt, kq_msx, kq_mt",
           "  kq_msx:",
           "    hex.cmp 4, kb_cy + 4*dw, mm_y, kq_mt, kq_mfr, kq_mt",         # the same whole units: untested
           "  kq_mt:",
           "    hex.mov 4, mm_nx, kb_cx + 4*dw", "    hex.mov 4, mm_ny, kb_cy + 4*dw",
           "    hex.zero 4, cpx", "    hex.mov 4, cpx + 4*dw, mm_nx",
           "    hex.zero 4, cpy", "    hex.mov 4, cpy + 4*dw, mm_ny",
           "    stl.fcall mm_things, mm_tret",
           "    hex.if1 1, mm_blk, kq_mno",
           "    hex.zero 10, ptx", "    hex.mov 4, ptx, mm_nx", "    hex.sign_extend 10, 4, ptx",
           "    hex.zero 10, pty", "    hex.mov 4, pty, mm_ny", "    hex.sign_extend 10, 4, pty",
           "    stl.fcall ptloc_walk, ptloc_ret",
           "    stl.fcall ms_seed_leaf, ms_seed_ret",
           "    hex.zero 8, cprad", "    hex.mov 2, cprad + 4*dw, mm_r",
           # P_TryMove for a monster -- a corpse fits 14 and skips the drop-off (world.try_move_lines(corpse=))
           "    hex.mov 8, cp_drop, cp_seedf",
           "    sim.check_cells %s" % mon_root,
           "    hex.if0 1, cp_ok, kq_mno",
           "    hex.mov 8, kb_t, cp_ceil", "    hex.sub 8, kb_t, cp_floor",
           "    hex.scmp 8, kb_t, kb_ht, kq_mno, kq_m1, kq_m1",
           "  kq_m1:",
           "    hex.mov 8, kb_t, cp_ceil", "    hex.sub 8, kb_t, mm_z",
           "    hex.scmp 8, kb_t, kb_ht, kq_mno, kq_m2, kq_m2",
           "  kq_m2:",
           "    hex.mov 8, kb_t, cp_floor", "    hex.sub 8, kb_t, mm_z",
           "    hex.set 8, kb_c, %d" % STEP_UP,
           "    hex.scmp 8, kb_t, kb_c, kq_m3, kq_m3, kq_mno",
           "  kq_m3:",
           "    hex.if1 1, kb_dead, kq_mok",
           "    hex.mov 8, kb_t, cp_floor", "    hex.sub 8, kb_t, cp_drop",
           "    hex.set 8, kb_c, %d" % DROPOFF_MAX,
           "    hex.scmp 8, kb_t, kb_c, kq_mok, kq_mok, kq_mno",
           # ---- accepted: the WR lifts crossed (old whole units << 16 -> cpx / cpy), the move, the floor, the leaf
           "  kq_mok:",
           "    hex.zero 4, mm_ox16", "    hex.mov 4, mm_ox16 + 4*dw, mm_x",
           "    hex.zero 4, mm_oy16", "    hex.mov 4, mm_oy16 + 4*dw, mm_y",
           "    hex.if1 1, mm_r30, kq_lw30"]
    for rad in (20, 30):
        if rad == 30:
            out.append("  kq_lw30:")
        for k, (slot, axis, coord, lo, hi) in enumerate(lift_trigs):
            out += _crossed_lines("kql%d_%d" % (rad, k), axis, coord, lo, hi, rad,
                                  ["    hex.set 1, lreq + %d*dw, 1" % slot],
                                  regs=("mm_ox16", "mm_oy16", "cpx", "cpy"))
        out.append("    ;kq_lwd")
    out += ["  kq_lwd:",
            "    hex.mov 4, mm_x, mm_nx", "    hex.mov 4, mm_y, mm_ny",
            "    hex.mov 8, mm_z, cp_floor",
            "    hex.zero w/4, kb_lf", "    hex.mov 3, kb_lf, ptss",
            "    hex.cmp 3, kb_lf, mm_leafw, kq_rl, kq_mfr, kq_rl",
            "  kq_rl:",                                                         # a new leaf: out, in, its sector
            "    hex.mov w/4, pw_t, mm_tw", "    hex.mov w/4, pw_leaf, mm_leafw",
            "    stl.fcall pw_unlink, pw_ulret",
            "    hex.mov w/4, mm_leafw, kb_lf",
            "    hex.mov w/4, pw_t, mm_tw", "    hex.mov w/4, pw_leaf, mm_leafw",
            "    stl.fcall pw_link, pw_lkret",
            "    lfsec.lookup mm_sec, mm_leafw",
            "  kq_mfr:",                                                        # the position, its fraction too
            "    hex.mov 8, kb_px, kb_cx", "    hex.mov 8, kb_py, kb_cy",
            "    stl.fret kb_tyret",
            "  kq_mno:",
            "    hex.zero 1, kb_ok",
            "    stl.fret kb_tyret"]
    return out


def move_lines(slots: Sequence[tuple], *, solid: str = "mon_solid") -> List[str]:
    """`kb_pmove` (the player's: stl.fcall kb_pmove, kb_pret), `kb_mmove` (a monster's, on the context) and the slot
    stubs `kbs<m>` (stl.fcall kbs<m>, kbs_ret: the slot's momentum not 0 -> its cells into the context, its own
    `solid` flag cleared so mm_things skips it, kb_mmove, the cells back). `slots[m]` = (runtime thing, radius, mass)"""
    from doomfj.reference_model import PLAYER_HEIGHT
    h, hd = PLAYER_HEIGHT >> 16, PLAYER_HEIGHT >> 18
    out = ["kb_pmove:",
           "    hex.zero 1, kb_who",
           "    hex.mov 1, kb_dead, p_dead",
           "    hex.set 8, kb_ht, %d" % h,
           "    hex.if0 1, p_dead, kq_pa", "    hex.set 8, kb_ht, %d" % hd,      # a dead player: a corpse's height
           "  kq_pa:",
           "    hex.mov 8, kb_vx, p_kmx", "    hex.mov 8, kb_vy, p_kmy",
           "    hex.mov 8, kb_px, viewx", "    hex.mov 8, kb_py, viewy",
           "    stl.fcall kb_xy, kb_xyret",
           "    hex.mov 8, p_kmx, kb_vx", "    hex.mov 8, p_kmy, kb_vy",
           "    stl.fret kb_pret",
           "kb_mmove:",
           "    hex.set 1, kb_who, 1",
           "    hex.set 8, kb_ht, %d" % h,
           "    hex.if0 1, kb_dead, kq_ma", "    hex.set 8, kb_ht, %d" % hd,     # a corpse: height >> 2
           "  kq_ma:",
           "    stl.fcall kb_xy, kb_xyret",
           "    hex.if1 8, kb_vx, kq_mlv", "    hex.if1 8, kb_vy, kq_mlv",
           "    hex.dec 2, kb_live",                                          # it stopped
           "  kq_mlv:",
           "    stl.fret kb_mret"]
    for m, (rt, r, _mass) in enumerate(slots):
        assert r in (20, 30), r
        X, Y = "thpos_rt + %d*dw" % (16 * rt + 4), "thpos_rt + %d*dw" % (16 * rt + 12)
        out += ["kbs%d:" % m,
                "    hex.if1 8, mkx + %d*dw, kbs%d_go" % (8 * m, m),
                "    hex.if0 8, mky + %d*dw, kbs%d_o" % (8 * m, m),
                "  kbs%d_go:" % m,
                "    hex.mov 8, kb_vx, mkx + %d*dw" % (8 * m), "    hex.mov 8, kb_vy, mky + %d*dw" % (8 * m),
                "    hex.mov 4, kb_px, mfx + %d*dw" % (4 * m), "    hex.mov 4, kb_px + 4*dw, %s" % X,
                "    hex.mov 4, kb_py, mfy + %d*dw" % (4 * m), "    hex.mov 4, kb_py + 4*dw, %s" % Y,
                "    hex.mov 4, mm_x, %s" % X, "    hex.mov 4, mm_y, %s" % Y,
                "    hex.mov 4, mm_z, mon_floorz + %d*dw" % (4 * m), "    hex.sign_extend 8, 4, mm_z",
                "    hex.set 2, mm_r, %d" % r, "    hex.set 1, mm_r30, %d" % int(r == 30),
                "    hex.set w/4, mm_tw, %d" % rt,
                "    hex.zero w/4, mm_leafw", "    hex.mov 3, mm_leafw, thss_rt + %d*dw" % (16 * rt),
                "    hex.mov 2, mm_sec, msec + %d*dw" % (2 * m),
                "    hex.mov 1, kb_dead, mon_shootable + %d*dw" % m, "    hex.xor_by kb_dead, 1",   # a corpse
                "    hex.mov 1, kb_sv, %s + %d*dw" % (solid, m), "    hex.zero 1, %s + %d*dw" % (solid, m),
                "    stl.fcall kb_mmove, kb_mret",
                "    hex.mov 1, %s + %d*dw, kb_sv" % (solid, m),
                "    hex.mov 8, mkx + %d*dw, kb_vx" % (8 * m), "    hex.mov 8, mky + %d*dw, kb_vy" % (8 * m),
                "    hex.mov 4, mfx + %d*dw, kb_px" % (4 * m), "    hex.mov 4, mfy + %d*dw, kb_py" % (4 * m),
                "    hex.mov 4, %s, mm_x" % X, "    hex.mov 4, %s, mm_y" % Y,
                "    hex.mov 4, mon_floorz + %d*dw, mm_z" % (4 * m),
                "    hex.mov 3, thss_rt + %d*dw, mm_leafw" % (16 * rt),
                "    hex.mov 2, msec + %d*dw, mm_sec" % (2 * m),
                "  kbs%d_o:" % m,
                "    stl.fret kbs_ret"]
    return out


def leaf_lines(slots: Sequence[tuple], *, player_root: str, mon_root: str, lift_trigs=(),
               after_accept: Sequence[str] = (), solid: str = "mon_solid") -> List[str]:
    """every knock leaf, jumping over itself: kb_go (+ kbt<m>, kb_gm, kb_th, kb_pz), kb_cell, kb_xy (+ kb_try),
    kb_ptry, kb_mtry, kb_pmove, kb_mmove, kbs<m>. The program must hold: the cells (`decls(nmon)`), `tables_fj`,
    mrnd, finesine, the point_to_angle tables, ptloc_walk, ms_seed_leaf, the player's and the monsters' cells (their
    roots), monstermove's context and mm_things, pk_go, pb_mon, projcode's pw_link / pw_unlink, lfsec, dm_leaf's window
    (dm_hp, dm_rng, dm_x, dm_y), p_hp / p_dead / rng_pl / wp_rdy, thpos_rt / thss_rt / msec / mon_floorz /
    mon_shootable / `solid`, lreq"""
    return (["// M7 P8a (doomfj.knockcode, package K): knockback's leaves", ";kq_end"]
            + go_lines(slots) + cell_lines(player_root) + xy_lines() + ptry_lines(after_accept)
            + mtry_lines(mon_root, lift_trigs) + move_lines(slots, solid=solid) + ["kq_end:"])


# ---- the splice points -----------------------------------------------------------------------------------------------
def player_move_lines() -> List[str]:
    """SPLICE (4.3 step 6): the player's knock move after `simmv_done` -- dead or alive (the corpse slides)"""
    return ["hex.if1 8, p_kmx, kbp_go", "hex.if0 8, p_kmy, kbp_done",
            "kbp_go:", "stl.fcall kb_pmove, kb_pret",
            "kbp_done:"]


def monster_slot_lines(m: int) -> List[str]:
    """SPLICE (4.3 step 7): slot `m`'s knock move at the top of its turn -- the fast skip while no slot moves
    (kb_live 0), else its stub (its own momentum test, kb_mmove)"""
    return ["    hex.if0 2, kb_live, kbm%d_n" % m,
            "    stl.fcall kbs%d, kbs_ret" % m,
            "  kbm%d_n:" % m]


def slots_of(w, slot_rt: Sequence[int]) -> List[tuple]:
    """[(runtime thing, radius, mass)] per monster slot"""
    return [(slot_rt[m], w.mon_radius[m], w.mon_info[m].mass) for m in range(w.layout.nmon)]
