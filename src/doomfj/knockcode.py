"""M7 P8a (docs/gp-final-plan.md 1.2.3 / 3.0 / 4.2): KNOCKBACK in fj -- PACKAGE 0's INTERFACE, which package K fills.

Everything here is emitted ONLY when `world.knockback_on(PLAYER_MODE, MONSTER_MODE)` (wall_renderer's `_KNOCK`), so the
"full" / "full" game tier -- blocked51's text -- holds none of it (scratchpad/cr/emit_baseline.py --check).

THE THRUST'S INTERFACE (package 0 sets it at every damage site; package K's `kb_go` reads it):

    kb_tg    2 nibbles   the TARGET: 0 the player, 1 + slot a monster (barrels are not pushed: O-B1)
    kb_dm    2 nibbles   the RAW damage, before the armor (dp_dmg / dm_dmg: both <= 255)
    kb_on    1 nibble    1: the hit has an INFLICTOR, at (kb_ix, kb_iy); 0: none (sector damage, DOOM's NULL) --
                         set by the site right before its damage call, ZEROED by the damage leaf on every exit
                         (dp_go's dp_out, dm_leaf's dm_out), so a site that names none is "no inflictor"
    kb_ix    4 nibbles   the inflictor's whole-unit position (the integer half of its 16.16: thpos_rt's nibbles 4-7 /
    kb_iy    4 nibbles   12-15, viewx / viewy + 4*dw, a fireball's pw_x / pw_y + 4*dw)
    kb_iz    4 nibbles   the inflictor's z, for the reversal (G-B4) -- declared here, written by K where it can apply
    stl.fcall kb_go, kb_ret

THE SITES (package 0; each behind `knock`):
  * hurtcode.dp_lines -- dp_go (the player hit): after its "dead / health <= 0" returns and BEFORE the armor (DOOM's
    order), kb_tg = 0, kb_dm = dp_dmg, kb_go; dp_out zeroes kb_on;
  * damagecode.leaf_lines -- dm_leaf (a monster hit): after its "not shootable / dead" returns and BEFORE the health,
    kb_dm = dm_dmg, kb_go; the inflictor is THE PLAYER for a shot (viewx / viewy: dm_melee is not BLAST) and the
    caller's for a BLAST; dm_out zeroes kb_on. The slot stubs dmg<m> (go_lines) set kb_tg = 1 + m;
  * barrelcode.blast_lines -- the barrel's blast: kb_on = 1 and the BARREL's position before its dp_go and before
    each slot's dmg<m> call;
  * projcode.pj_lines -- the fireball's impact on the player: kb_on = 1 and the MISSILE's position (pw_x / pw_y, not
    yet moved: P_TryMove's tmthing) before its dp_go;
  * monsterdecide.attack_leaf_lines -- the monster's hitscan and melee on the player: kb_on = 1 and the ATTACKER's
    position (mm_x / mm_y) before each dp_go.
  Nukage (lootcode) calls dp_go with kb_on 0: no thrust.

THE SPLICE POINTS (package 0; empty until K):
  * `player_move_lines()` -- the player's knock move, after `simmv_done` (docs/gp-final-plan.md 4.3 step 6: dead or
    alive, the corpse slides);
  * `monster_slot_lines(m)` -- the top of slot m's turn in the monsters' world (monstercode.p32a_slot, after its
    "not active" skip: 4.3 step 7, P_MobjThinker's P_XYMovement before the state's tics).

THE CELLS (docs/gp-final-plan.md 4.1): `PERSIST` -- empty until K declares p_kmx, p_kmy, mkx, mky, mfx, mfy, kb_live
and pj_z here; build.KNOCK_PERSIST reads it.
"""
from __future__ import annotations

from typing import List

# the persisted cells (build.KNOCK_PERSIST): K's, docs/gp-final-plan.md 4.1
PERSIST: tuple = ()
# the thrust's interface (the module docstring); scratch -- not persisted
KB_INTERFACE = ["kb_tg: hex.vec 2", "kb_dm: hex.vec 2", "kb_on: hex.vec 1", "kb_ix: hex.vec 4", "kb_iy: hex.vec 4",
                "kb_iz: hex.vec 4", "kb_ret: hex.vec w/4"]


def decls() -> List[str]:
    """the interface registers (and, from K, the cells and scratch)"""
    return list(KB_INTERFACE)


def go_lines() -> List[str]:
    """`kb_go` (stl.fcall kb_go, kb_ret): P_DamageMobj's thrust on kb_tg from the inflictor (kb_on, kb_ix, kb_iy,
    kb_iz) with kb_dm. PACKAGE 0'S STUB: returns at once -- K replaces the body (a leaf: every path frets)"""
    return ["// M7 P8a (doomfj.knockcode): P_DamageMobj's thrust -- package 0's stub, package K's leaf",
            "kb_go:",
            "    stl.fret kb_ret"]


def inflictor_lines(x: str, y: str) -> List[str]:
    """a site's inflictor: kb_on = 1 and the whole-unit position from the 4-nibble integer cells `x`, `y`"""
    return ["    hex.set 1, kb_on, 1", "    hex.mov 4, kb_ix, %s" % x, "    hex.mov 4, kb_iy, %s" % y]


def inflictor_const_lines(x: int, y: int) -> List[str]:
    """a site's inflictor at a position known at emit time (a barrel: barrels never move)"""
    return ["    hex.set 1, kb_on, 1", "    hex.set 4, kb_ix, %d" % (x & 0xFFFF),
            "    hex.set 4, kb_iy, %d" % (y & 0xFFFF)]


def player_move_lines() -> List[str]:
    """SPLICE POINT (package K, 4.3 step 6): the player's knock move after `simmv_done`. Empty until K"""
    return []


def monster_slot_lines(m: int) -> List[str]:
    """SPLICE POINT (package K, 4.3 step 7): slot `m`'s knock move at the top of its turn. Empty until K"""
    return []
