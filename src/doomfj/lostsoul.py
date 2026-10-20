"""M8 C8 part 2 -- THE LOST SOUL (MT_SKULL, thing 3006; E1M6 3, E1M7 8): the model's rules, both mirrors' source.

DOOM's code, from Chocolate Doom at `gamedata.SOURCE_COMMIT` (fetched raw with curl, 2026-10-19): info.c MT_SKULL and
S_SKULL_*; p_enemy.c A_SkullAttack (SKULLSPEED 20), P_Move's MF_FLOAT branch, P_CheckMissileRange's `dist >>= 1`;
p_map.c PIT_CheckThing's skull slam and P_TryMove's height rules; p_mobj.c P_MobjThinker, P_XYMovement and P_ZMovement
(the Ultimate Doom bounce: Freedoom phase 1 is a retail IWAD, `correct_lost_soul_bounce`); p_inter.c P_DamageMobj's
MF_SKULLFLY rules and P_KillMobj (SHOOTABLE, FLOAT and SKULLFLY cleared; NOGRAVITY kept: a dead soul hangs where it
died; no drop; not MF_COUNTKILL). `World` inherits `SoulMixin`; the fj half is `doomfj.soulcode`.

A FLYING MONSTER IS NEW TO THIS ENGINE: every other monster stands on its floor (`mon_floorz` is its z, combat's 2D
conventions). A soul keeps its own z, and only souls do -- a map without one has none of the cells below, so E1M1 and
E1M2 are untouched (no field, no line). Its cells, `soul_slots` order (the souls among the monster slots, ascending):

    sk_fly   1 bit      MF_SKULLFLY: charging
    sk_inf   1 bit      MF_INFLOAT: P_Move floated it this step (P_ZMovement's float toward the target waits)
    sk_z     32 signed  z, 16.16 (its sprite is drawn at z >> 16 -- the renderer's one non-floor monster)
    sk_momz  32 signed  momz, 16.16 a tic
    sk_ceil  16 signed  ceilingz, map units (its last accepted position's opening ceiling)

and the knock cells for its x / y momentum and its position's fraction (mon_momx, mon_momy, mon_fx, mon_fy: every map
with a soul carries them, knockback or not -- `world.build_schema`).

THE CONVENTIONS (each named so the fj copies it; DOOM's rule otherwise):
  * SPAWN: z = floorz << 16 (ONFLOORZ), momz 0, not flying, not floating; ceilingz = its leaf's sector ceiling in the
    collision map (P_SpawnMobj's subsector ceiling; doors at their open height, movers where they stand).
  * THE THINKER (P_MobjThinker), at the top of the slot's turn in each monster tic, before its tics: P_XYMovement when
    the momentum is not 0 OR it flies; then P_ZMovement when z != floorz << 16 or momz != 0. A soul's knock move IS
    this (it replaces the knock splice for a soul slot). The spawn state a slam or a stop sets (P_SetMobjState) has its
    A_Look RUN AFTER the XY move's loop -- DOOM runs it inside PIT_CheckThing; A_Look reads no position the rest of
    the loop changes except where the soul stands (its sector's noise, its sight), a difference only when a slam on
    the first half-step is followed by an accepted second half-step that changes either.
  * P_XYMovement: `combat._xy_move` (the clamp, the halving, a refused try stops the momentum) with the soul's TRY
    (`_soul_try`) and its friction: none while it flies (MF_SKULLFLY) or is airborne (z > floorz << 16); else the
    knock's (a dead soul on its floor is a corpse: the corpse rule, the stop, the friction). The momentum stopping in
    flight (`mom == 0 && fly`) ends the charge: fly 0, momz 0, the spawn state.
  * THE TRY (P_TryMove at the candidate's INTEGER part, the knock's convention: the same whole units are accepted
    untested -- only the fraction moves): flying, the FIRST thing its box (radius 16) overlaps is SLAMMED (`slam_thing`
    -- PIT_CheckThing's MF_SOLID | MF_SPECIAL | MF_SHOOTABLE, in the convention order: the monsters by slot (solid or
    shootable), the player alive, the standing barrels, the solid decorations, the pickups not taken, the drops lying;
    DOOM walks the blockmap): one P_Random on the SOUL's stream, ((v % 8) + 1) * 3 damage to it (P_DamageMobj, the
    soul the inflictor and the source: a monster, the player or a barrel; a decoration, a pickup or a drop takes
    nothing), the charge ends (fly 0, momentum and momz 0, the spawn state) and the try is refused. Not flying, a
    SOLID thing refuses (`_thing_blocker`). Then the lines (the monster cells' rule) and P_TryMove's heights: the
    opening must hold its height (56; a corpse 14), `ceilz - z < height` refuses (it must lower itself), `floorz - z >
    24` refuses (a step too high for where it FLIES); no drop-off rule (MF_FLOAT; a corpse is MF_DROPOFF). Accepted:
    the walk's move (`_move_monster`: floorz, the WR lifts, the teleports, the relink) and ceilingz.
  * P_ZMovement: z += momz; alive (MF_FLOAT), with a target, not flying and not floating: the float toward the target
    -- dist = P_AproxDistance of the 16.16 positions (the soul's (x << 16) + fraction, the target's `_target_pos16`),
    delta = (the target's z + 28) - z (28 = the SOUL's height >> 1, DOOM's `mo->height >> 1`): delta < 0 and dist <
    -3 delta -> z -= 4; delta > 0 and dist < 3 delta -> z += 4. Then the floor: z <= floorz << 16 -> flying, momz =
    -momz (the Ultimate bounce); momz < 0 -> 0; z = floorz << 16. Then the ceiling: z + height > ceilz << 16 -> momz
    > 0 -> 0; z = (ceilz << 16) - height; flying, momz = -momz. A thing's z: the player's check_position floorz, a
    monster's mon_floorz, a soul's sk_z (`thing_z16`).
  * A_SkullAttack (heavy: a K slot, as every attack): no target -> nothing; fly 1; A_FaceTarget (the model's octant
    facing, the ambush flag cleared); the charge along the EXACT angle from the soul's WHOLE units to `_target_pos16`
    (the fireball's convention), momx / momy = FixedMul(SKULLSPEED, finecosine / finesine) -- the rocket's momentum
    table (speed 20: `combat.fireball_momentum_table(MT_ROCKET)`); dist = P_AproxDistance(the same delta, 16.16) /
    SKULLSPEED, at least 1; momz = (the target's z + 28 << 16 - z) / dist, C's division (toward zero). In a mode
    whose attacks do not land (`world.monster_attacks_land`) only the A_FaceTarget runs.
  * P_Move (the chase step): the soul's try at the step (`soul_lines_try`); refused with FLOATOK (the position and
    the lines passed and the opening holds it: only the z tests failed) -> z += 4 if z < tmfloorz << 16 else z -= 4,
    floating 1, and the move counts as made (before any door press); accepted -> floating 0, ceilingz, and z stays
    (MF_FLOAT: no snap to the floor).
  * P_DamageMobj: flying -> momx = momy = momz = 0 before the thrust; the pain roll is always drawn (painchance 256)
    and the pain state entered only when NOT flying. P_KillMobj: fly 0 (its SKULLFLY and FLOAT cleared; z kept); the
    death states end in S_NULL -- P_RemoveMobj: the slot inactive and out of its leaf list (no corpse).
  * P_CheckMissileRange: `dist >>= 1` for MT_SKULL (an arithmetic shift of a possibly negative int, before the cap).
  * P_ChangeSector (a lift under it, world._door_phase_scene): a soul ON its floor (z == the old floorz << 16) moves
    with it; one in the air keeps its z (and its ceilingz: only its own moves set it).
  * EV_Teleport (world._teleport_monster): z = the destination floor << 16, momz 0, ceilingz the destination
    sector's ceiling (DOOM zeroes the momentum: a charge through a teleport ends on the next tic).
  * The knock thrust's z (`combat._knock_z`) of a soul is z >> 16.
  * 2D everywhere else, as every monster: sight, the aim window (the sprite's columns), missiles and hitscan meet it
    whatever its z; no fullbright (the renderer draws every sprite at its sector's light).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.fixedpoint import _signed, aprox_distance

SKULL_INFO = gd.MOBJINFO["MT_SKULL"]
SKULL_TYPE = SKULL_INFO.doomednum                    # 3006
SKULLSPEED = 20 * gd.FRACUNIT                         # p_enemy.c
FLOATSPEED = gd.FLOATSPEED                            # 4 << 16
SOUL_H = SKULL_INFO.height >> 16                      # 56
SOUL_HALF = SOUL_H >> 1                               # 28: P_ZMovement's mo->height >> 1
CORPSE_H = SOUL_H >> 2                                # 14: P_KillMobj's height >>= 2
TARGET_HALF = 28                                      # A_SkullAttack's dest->height >> 1 (every target is 56 tall)
SLAM_DAMAGE = SKULL_INFO.damage                       # 3: ((P_Random() % 8) + 1) * 3
M32 = 0xFFFFFFFF
assert SKULL_INFO.radius >> 16 == 16 and SKULL_INFO.painchance == 256 and not SKULL_INFO.flags & gd.MF_COUNTKILL
assert SKULL_INFO.flags & gd.MF_FLOAT and SKULL_INFO.meleestate == gd.S_NULL
assert gd.MOBJINFO["MT_ROCKET"].speed == SKULLSPEED, "the charge's momentum is the rocket's table (speed 20)"
SLAM_KINDS = ("mon", "player", "bar", "decor", "pickup", "drop")


def is_soul_type(doomednum: int) -> bool:
    return doomednum == SKULL_TYPE


def soul_fields() -> List[tuple]:
    """the soul cells (name, bits, signed, doc) -- world.build_schema declares each with count nsoul"""
    return [("sk_fly", 1, False, "MF_SKULLFLY: charging"),
            ("sk_inf", 1, False, "MF_INFLOAT: P_Move floated it (the float toward the target waits)"),
            ("sk_z", 32, True, "z, 16.16 (drawn at z >> 16)"),
            ("sk_momz", 32, True, "momz, 16.16 a tic"),
            ("sk_ceil", 16, True, "ceilingz, map units: its last accepted position's opening ceiling")]


def slam_roll(v: int) -> int:
    """PIT_CheckThing's skull damage for P_Random value v"""
    return ((v % 8) + 1) * SLAM_DAMAGE


def c_div(a: int, b: int) -> int:
    """C's integer division (truncates toward zero)"""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


class SoulMixin:
    """the soul's rules for `world.World` (the module docstring). `soul_of[m]` is slot m's soul index."""

    # ---------------------------------------------------------------------------------------------- level
    def _soul_init(self) -> None:
        self.soul_slots = [m for m, t in enumerate(self.mon_things) if is_soul_type(t.type)]
        self.soul_of = {m: k for k, m in enumerate(self.soul_slots)}
        self._soul_spawn_due = False

    def is_soul(self, m: int) -> bool:
        return m in self.soul_of

    def _soul_reset(self, m: int) -> None:
        """P_SpawnMobj's z and ceilingz (the level start, which the restart copies)"""
        k, ws = self.soul_of[m], self.ws
        ws.sk_z[k] = ws.mon_floorz[m] << 16
        ws.sk_ceil[k] = self.secs_c[self.leaf_sector[ws.mon_leaf[m]]].ceil_h

    # ---------------------------------------------------------------------------------------------- z helpers
    def soul_height(self, m: int) -> int:
        return SOUL_H if self.ws.mon_shootable[m] else CORPSE_H

    def thing_z16(self, thing) -> int:
        """a thing's z, 16.16: the player's check_position floorz, a monster's mon_floorz, a soul's sk_z"""
        kind, i = thing
        ws = self.ws
        if kind == "player":
            return self.rm.check_position(self.scene_c, ws.px, ws.py)[1] << 16
        if i in self.soul_of:
            return ws.sk_z[self.soul_of[i]]
        return ws.mon_floorz[i] << 16

    def _target_thing(self, m: int):
        t = self.ws.mon_target[m]
        return ("mon", t - 2) if t >= 2 else ("player", -1)

    def soul_pos16(self, m: int) -> Tuple[int, int]:
        ws = self.ws
        return (ws.mon_x[m] << 16) + ws.mon_fx[m], (ws.mon_y[m] << 16) + ws.mon_fy[m]

    # ---------------------------------------------------------------------------------------------- A_SkullAttack
    def _a_skull_attack(self, m: int, ev) -> None:
        ws = self.ws
        ev.attacks.append((m, "A_SkullAttack"))
        if not ws.mon_target[m]:
            return
        from doomfj.world import monster_attacks_land
        self._a_face_target(m)
        if not monster_attacks_land(self.monsters):
            return
        k = self.soul_of[m]
        sx, sy = ws.mon_x[m] << 16, ws.mon_y[m] << 16
        tx, ty = self._target_pos16(m)
        an = self.rm.point_to_angle(sx, sy, tx, ty)
        ws.sk_fly[k] = 1
        ws.mon_momx[m], ws.mon_momy[m] = self.rocket_mom[an >> self.rm.angle_shift]
        dist = max(1, aprox_distance(_signed(tx - sx, 32), _signed(ty - sy, 32)) // SKULLSPEED)
        dz = self.thing_z16(self._target_thing(m)) + (TARGET_HALF << 16) - ws.sk_z[k]
        ws.sk_momz[k] = c_div(dz, dist)
        ev.souls.append(("charge", m, an, ws.sk_momz[k]))

    # ---------------------------------------------------------------------------------------------- the thinker
    def _soul_think(self, m: int, ev) -> None:
        """P_MobjThinker's movement half for soul slot m (before its tics): P_XYMovement, the spawn state a slam or a
        stop set (its A_Look runs now), then P_ZMovement"""
        if self._soul_xy(m, ev):                                 # the spawn state (and its A_Look) after the loop
            self._set_state(m, self.mon_info[m].spawnstate, True, ev)
        self._soul_z(m, ev)

    def _soul_xy(self, m: int, ev) -> bool:
        """P_XYMovement for soul slot m when its momentum is not 0 or it flies (fj: soulcode's sks<k>) -> whether
        the charge ended (a slam, or the stop): the spawn state is due"""
        ws = self.ws
        k = self.soul_of[m]
        self._soul_spawn_due = False
        if ws.mon_momx[m] or ws.mon_momy[m] or ws.sk_fly[k]:
            if not ws.mon_momx[m] and not ws.mon_momy[m]:
                ws.sk_fly[k] = 0                                 # "the skull slammed into something"
                ws.sk_momz[k] = 0
                ev.souls.append(("stop", m))
                self._soul_spawn_due = True
            else:
                self._xy_move(("mon", m), ev)
        due, self._soul_spawn_due = self._soul_spawn_due, False
        return due

    def _soul_z(self, m: int, ev=None) -> None:
        """P_ZMovement when z != floorz << 16 or momz != 0 (fj: soulcode's skz<k>)"""
        ws = self.ws
        k = self.soul_of[m]
        if ws.sk_z[k] != ws.mon_floorz[m] << 16 or ws.sk_momz[k]:
            self._soul_z_move(m, ev)

    def soul_airborne(self, m: int) -> bool:
        return self.ws.sk_z[self.soul_of[m]] > self.ws.mon_floorz[m] << 16

    def _soul_z_move(self, m: int, ev=None) -> None:
        """P_ZMovement for soul slot m (the module docstring)"""
        ws = self.ws
        k = self.soul_of[m]
        z = ws.sk_z[k] + ws.sk_momz[k]
        if ws.mon_shootable[m] and ws.mon_target[m] and not ws.sk_fly[k] and not ws.sk_inf[k]:
            sx, sy = self.soul_pos16(m)
            tx, ty = self._target_pos16(m)
            dist = aprox_distance(sx - tx, sy - ty)
            delta = self.thing_z16(self._target_thing(m)) + (SOUL_HALF << 16) - z
            if delta < 0 and dist < -(delta * 3):
                z -= FLOATSPEED
            elif delta > 0 and dist < delta * 3:
                z += FLOATSPEED
        floor16 = ws.mon_floorz[m] << 16
        if z <= floor16:
            if ws.sk_fly[k]:
                ws.sk_momz[k] = -ws.sk_momz[k]                   # the Ultimate bounce
                if ev is not None:
                    ev.souls.append(("bounce", m))
            if ws.sk_momz[k] < 0:
                ws.sk_momz[k] = 0
            z = floor16
        h16 = self.soul_height(m) << 16
        if z + h16 > ws.sk_ceil[k] << 16:
            if ws.sk_momz[k] > 0:
                ws.sk_momz[k] = 0
            z = (ws.sk_ceil[k] << 16) - h16
            if ws.sk_fly[k]:
                ws.sk_momz[k] = -ws.sk_momz[k]
        ws.sk_z[k] = z

    # ---------------------------------------------------------------------------------------------- the slam
    def slam_thing(self, m: int, nx: int, ny: int):
        """PIT_CheckThing for a CHARGING soul at the integer candidate (nx, ny): the first thing (the convention
        order) whose box overlaps -- (kind, index) or None"""
        from doomfj.combat import BARREL_R, ITEM_RADIUS, PLAYER_R
        ws = self.ws
        r = self.mon_radius[m]
        for j in range(self.layout.nmon):
            if j != m and ws.mon_active[j] and (ws.mon_solid[j] or ws.mon_shootable[j]):
                bd = r + self.mon_radius[j]
                if abs(ws.mon_x[j] - nx) < bd and abs(ws.mon_y[j] - ny) < bd:
                    return ("mon", j)
        bd16 = (r + PLAYER_R) << 16
        if self.player_alive() and abs(ws.px - (nx << 16)) < bd16 and abs(ws.py - (ny << 16)) < bd16:
            return ("player", -1)
        for b, t in enumerate(self.barrel_things):
            if ws.bar_solid[b] and abs(t.x - nx) < r + BARREL_R and abs(t.y - ny) < r + BARREL_R:
                return ("bar", b)
        now = set(id(t) for t in self._decor_now)
        for i, t in enumerate(self.decor_solid):
            if id(t) in now:
                bd = r + gd.THING_TYPES[t.type].radius
                if abs(t.x - nx) < bd and abs(t.y - ny) < bd:
                    return ("decor", i)
        for i, t in enumerate(self.pickup_things):
            if not ws.pickup_taken[i]:
                bd = r + gd.THING_TYPES[t.type].radius
                if abs(t.x - nx) < bd and abs(t.y - ny) < bd:
                    return ("pickup", i)
        if "mon_drop" in ws._fields:
            for j in range(self.layout.nmon):
                if self.dropper[j] is not None and ws.mon_drop[j] == 1:
                    dx, dy = self.drop_pos(j)
                    if abs(dx - nx) < r + ITEM_RADIUS and abs(dy - ny) < r + ITEM_RADIUS:
                        return ("drop", j)
        return None

    def _soul_slam(self, m: int, hit, ev) -> None:
        ws = self.ws
        k = self.soul_of[m]
        v, ws.mon_rng[m] = R.p_random(ws.mon_rng[m])
        dmg = slam_roll(v)
        kind, i = hit
        ev.souls.append(("slam", m, kind, i, dmg))
        src = ("mon", m)
        if kind == "mon":
            self.damage_monster(i, dmg, src, src, ev)
        elif kind == "player":
            self.damage_player(dmg, src, src, ev)
        elif kind == "bar":
            self.damage_barrel(i, dmg, src, ev)
        # P_DamageMobj on a decoration, a pickup or a drop: not shootable, nothing
        ws.sk_fly[k] = 0
        ws.mon_momx[m] = ws.mon_momy[m] = 0
        ws.sk_momz[k] = 0
        self._soul_spawn_due = True

    # ---------------------------------------------------------------------------------------------- the tries
    def soul_lines_try(self, m: int, nx: int, ny: int):
        """P_TryMove's lines and heights for soul m at the integer (nx, ny) -> (ok, floatok, floorz, ceilz)"""
        from doomfj.world import OK, STEP_UP
        ws = self.ws
        k = self.soul_of[m]
        h = self.soul_height(m)
        verdict, floorz, ceilz, _drop = self.check_lines(nx << 16, ny << 16, self.mon_radius[m] << 16, monster=True)
        if verdict != OK:
            return False, False, floorz, ceilz
        if ceilz - floorz < h:
            return False, False, floorz, ceilz
        z = ws.sk_z[k]
        if (ceilz << 16) - z < h << 16:
            return False, True, floorz, ceilz
        if (floorz << 16) - z > STEP_UP << 16:
            return False, True, floorz, ceilz
        return True, True, floorz, ceilz

    def _soul_try(self, m: int, cx16: int, cy16: int, ev) -> bool:
        """the soul's P_TryMove of an XY step to 16.16 (cx16, cy16) (the module docstring's TRY)"""
        ws = self.ws
        k = self.soul_of[m]
        nx, ny = cx16 >> 16, cy16 >> 16
        if (nx, ny) != (ws.mon_x[m], ws.mon_y[m]):
            if ws.sk_fly[k]:
                hit = self.slam_thing(m, nx, ny)
                if hit is not None:
                    self._soul_slam(m, hit, ev)
                    return False
            elif self._thing_blocker(m, nx, ny, self.mon_radius[m]) is not None:
                ev.blocked["thing"] += 1
                return False
            ok, _fok, floorz, ceilz = self.soul_lines_try(m, nx, ny)
            if not ok:
                ev.blocked["wall"] += 1
                return False
            self._teleported = False
            self._move_monster(m, nx, ny, floorz, ev, step=False)
            if self._teleported:
                return True
            ws.sk_ceil[k] = ceilz
        ws.mon_fx[m], ws.mon_fy[m] = cx16 & 0xFFFF, cy16 & 0xFFFF
        return True

    def _soul_p_move(self, m: int, nx: int, ny: int, ev) -> bool:
        """P_Move's try for soul m at the step (nx, ny): True moved (or floated); False refused (a door press may
        follow, world._p_move)"""
        ws = self.ws
        k = self.soul_of[m]
        if self._thing_blocker(m, nx, ny, self.mon_radius[m]) is not None:
            ev.blocked["thing"] += 1
            return False
        ok, fok, floorz, ceilz = self.soul_lines_try(m, nx, ny)
        if not ok:
            ev.blocked["wall"] += 1
            if fok:
                ws.sk_z[k] += FLOATSPEED if ws.sk_z[k] < floorz << 16 else -FLOATSPEED
                ws.sk_inf[k] = 1
                ev.souls.append(("float", m))
                return True
            return False
        ws.sk_inf[k] = 0
        self._teleported = False
        self._move_monster(m, nx, ny, floorz, ev)
        if not self._teleported:
            ws.sk_ceil[k] = ceilz
        return True

    # ---------------------------------------------------------------------------------------------- the others
    def _soul_teleported(self, m: int, tel) -> None:
        """EV_Teleport's z, momz and ceilingz (world._teleport_monster)"""
        k, ws = self.soul_of[m], self.ws
        ws.sk_z[k] = tel.dest_floor << 16
        ws.sk_momz[k] = 0
        ws.sk_ceil[k] = self.secs_c[tel.dest_sector].ceil_h

    def _soul_damaged(self, m: int, ev=None) -> None:
        """P_DamageMobj's `if (target->flags & MF_SKULLFLY) target->momx = momy = momz = 0`"""
        k, ws = self.soul_of[m], self.ws
        if ws.sk_fly[k]:
            if ev is not None:
                ev.souls.append(("flyhit", m))
            ws.mon_momx[m] = ws.mon_momy[m] = 0
            ws.sk_momz[k] = 0
