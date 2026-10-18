"""M8 L4 -- THE TELEPORTERS (line special 97, WR teleport): the rules, ONE definition for both mirrors.

The model (`combat.CombatMixin._teleport_player`, `world.World._teleport_monster`) and the fj (`doomfj.teleportcode`)
both read this module's `teleporters`, `crossed_front`, `stomped` and `stomp_victims`; neither re-derives a
destination, a side or a constant.

DOOM (Chocolate Doom p_map.c P_TryMove, p_spec.c P_CrossSpecialLine, p_telept.c EV_Teleport, P_TeleportMove):

  * P_TryMove, after an ACCEPTED move: every special line the new box touched whose P_PointOnLineSide differs before
    and after the move calls P_CrossSpecialLine(line, OLDSIDE, thing). Here: `doors.crossed` (the walk-over doors'
    and the WR lifts' own test -- the centre changed side, the new box overlaps the segment's extent) and the old
    side is the FRONT (`front_le`). EV_Teleport: "Don't teleport if hit back of line, so you can get out of
    teleporter" -- `if (side == 1) return 0`.
  * 97 is on P_CrossSpecialLine's non-player list (39, 97, 125, 126, 4, 10, 88): MONSTERS teleport too (a corpse
    sliding on knockback is a monster thing: it teleports as DOOM's would). Missiles never (MF_MISSILE: the model's
    fireballs and rockets cross no special line at all). WR: no latch, every crossing.
  * the destination: the first MT_TELEPORTMAN (type 14) found -- sectors in index order with the line's tag, each
    searched in thinker (spawn = WAD) order -- `teleporters` bakes it. P_TeleportMove(thing, dest): PIT_StompThing on
    every MF_SHOOTABLE thing whose box overlaps the destination box (`abs(dx) < blockdist` on both axes, strict): a
    MONSTER's teleport FAILS there (`if (!tmthing->player && gamemap != 30) return false`; the move it made stays);
    the PLAYER's TELEFRAGS it (`P_DamageMobj(thing, tmthing, tmthing, 10000)`: the player is the inflictor -- at his
    position after the move, P_TryMove has set it -- and the source; `stomp_victims`, TELEFRAG_DAMAGE) and goes on;
    then x, y = the destination, floorz = the destination SUBSECTOR's sector floor (lines are not checked), z =
    floorz, angle = the destination's (ANG45 * (angle / 45)), momx = momy = momz = 0, and a player gets
    reactiontime = 18: P_PlayerThink skips P_MovePlayer (the turn and the walk) while it counts down.

THE SIMPLIFICATIONS (M8 L4, recorded; the owner's "you can remove some weird stuff", docs/handoff-e1m2.md 3):
  * TELEFRAG (the owner, 2026-10-18: the earlier "no telefrag" simplification REMOVED): DOOM's rule above, in both
    mirrors -- a monster takes P_DamageMobj's 10000 (`combat.damage_monster`: the thrust from the player, then the
    health, held at the 12-bit cell's floor MON_HEALTH_MIN -- 10000 takes any health there -- and the death: every
    gib rule of a kill, the tics roll, the drop, the kill count), a barrel would explode (`damage_barrel`; none stands
    within reach of a destination: `teleportcode.check_barrels`, so the fj tests none).
  * TELEPORT FOG (the owner, 2026-10-18: "if teleport fog is simple and cheap add it"): EV_Teleport's two MT_TFOG,
    after a teleport that happened -- one where the thing stood when it crossed (its position after the move), then
    one 20 units ahead of the destination along its angle (`fog_dest`: Teleporter.fog) -- through the EFFECTS POOL (world.FX_POOL's
    two slots, combat._spawn_fx(kind="fog"), no P_Random: P_SpawnMobj draws none), at whole units (the pool's
    convention), drawn on the floor; S_TFOG .. S_TFOG10, 6 tics each, then removed. Where DOOM has no limit the pool
    has two slots, so A FOG YIELDS: a fog takes only a free slot (else it is skipped), and blood or a puff takes the
    first slot that is free OR holds a fog (the fog removed) -- blood and puffs spawn exactly as they would with no
    fog at all. On every map with a teleport line in the modes whose player loots (`fog_on`: the game tier's; the
    fj's teleports exist only there). No sound.
  * ONE TELEPORT PER MOVE: DOOM's spechit loop goes on after a teleport, testing the remaining lines against the
    thing's NEW (teleported) position; `teleporters` asserts no destination lies within any teleport line's reach,
    so no second line can fire (exact on E1M2).
  * A monster's facing is the destination angle's octant (`Teleporter.facing`), the model's own octant facing.
  * One crossing test per P_TryMove of the model (the walk's accepted candidate, a knock step, a monster step), as
    `doors.crossed` already is for the walk-over lines.

E1M1 has no teleport line: `teleporters` returns [] and nothing anywhere changes (no schema field, no fj text).

M8 C5 -- THE MONSTER-ONLY TELEPORTS, 126 (WR) and 125 (W1) (E1M4, E1M5, E1M6: 126; E1M7: 125). P_CrossSpecialLine:
    case 125: if (!thing->player) { EV_Teleport (line, side, thing); line->special = 0; }
    case 126: if (!thing->player) EV_Teleport (line, side, thing);
  * the PLAYER never fires them (`Teleporter.monster_only`: combat._teleport_player and teleportcode.player_lines skip
    them; his crossing does not clear a W1 latch either);
  * a MONSTER fires them exactly as 97: the front side, P_TeleportMove's refusal at an occupied destination (a monster
    never telefrags), the two fogs, the destination's floor, facing, momentum -- the same code (`_teleport_monster`,
    `teleportcode.monster_lines`);
  * 125 is W1 (`Teleporter.once`): ANY monster crossing (either side -- P_CrossSpecialLine runs on a side change, the
    side is EV_Teleport's own test) clears the line's special for the level, whether or not the teleport happens
    (a back-side crossing, a refused stomp, a skill without a destination): one latch per W1 line (`once_lines`), the
    world's `tp_fired` / the fj's `tp_w1`, 0 at the level start and the restart, persisted across the M1 reset;
  * THE DESTINATION BY SKILL (`Teleporter.skills`): P_SpawnMapThing spawns an MT_TELEPORTMAN only on the skills its
    flags name, so EV_Teleport's search runs per skill -- E1M5's one destination is hard-only, so its 126 line
    teleports on hard and is inert on easy and medium (EV_Teleport finds nothing and returns 0). `skills` is the
    MTF_ bits whose search finds this destination; a line whose search finds DIFFERENT destinations on different
    skills is refused (none in E1M1..E1M9), and so is a PLAYER line some skill lacks. The fj tests `g_skill` (a line
    with every skill tests nothing: E1M2's text is unchanged).
  * KNOWN SIMPLIFICATION (the "one teleport per move" above, on lines that touch): DOOM runs P_CrossSpecialLine on
    EVERY line of spechit, each side test at the thing's position after the earlier lines ran -- so a monster whose
    box straddles two teleport lines at once (E1M7's four collinear 125 lines meet end to end; E1M6's two 126 lines
    are 32 units apart) can teleport twice in DOOM (and clear both W1 latches). Here the first line in linedef order
    that decides the move (a teleport, or a refused stomp) ends the tests, as for 97: the later lines of that move are
    not tested, so their W1 latches stay set. Both mirrors share it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

TELEPORT_SPECIALS = frozenset({97, 125, 126})   # every teleport line run: WR 97 (E1M2's four lines) and M8 C5's
                                                # monster-only W1 125 / WR 126; 39 (W1, the player too) is not run
MONSTER_ONLY_SPECIALS = frozenset({125, 126})   # M8 C5: P_CrossSpecialLine's `if (!thing->player)`
ONCE_SPECIALS = frozenset({125})                # M8 C5: W1 -- `line->special = 0` on a monster's crossing
ALL_SKILLS = 7                                  # gamedata MTF_EASY | MTF_NORMAL | MTF_HARD (asserted in teleporters)
TELEPORT_DEST_TYPE = 14                # MT_TELEPORTMAN (gamedata.TELEPORT_DEST_TYPE: one value, asserted)
REACTION_TICS = 18                     # EV_Teleport: `if (thing->player) thing->reactiontime = 18`
TELEFRAG_DAMAGE = 10000                # PIT_StompThing: `P_DamageMobj (thing, tmthing, tmthing, 10000)`
FOG_AHEAD = 20                         # EV_Teleport: the destination fog at m->x + 20*finecosine[an], m->y + 20*finesine
REACTION_BITS = 5                      # 0..18 (world schema `p_reaction`; fj `p_rct`, 2 nibbles)
REACH_MAX = 30                         # the largest thing radius a crossing test is run with (the monsters' 30)
ANG45 = 0x20000000


@dataclass(frozen=True)
class Teleporter:
    """one WR teleport line, axis-aligned (asserted): `axis` "x" -- a vertical line x = coord, y in [lo, hi] -- or "y"
    (horizontal), `doors.walkover_triggers`' shape; `front_le` -- the line's FRONT side (P_PointOnLineSide 0) is the
    `c <= coord` side; the destination `dest` (x, y) in map units, its BAM `angle`, its subsector `dest_leaf`, its
    sector `dest_sector` and that sector's floor `dest_floor` (P_TeleportMove's floorz); M8 `fog`, the destination
    fog's position (`fog_dest`)"""
    line: int
    tag: int
    axis: str
    coord: int
    lo: int
    hi: int
    front_le: bool
    dest: Tuple[int, int]
    angle: int
    dest_leaf: int
    dest_sector: int
    dest_floor: int
    fog: Tuple[int, int] = (0, 0)     # M8: EV_Teleport's destination fog, whole units (`fog_dest`, baked here)
    monster_only: bool = False        # M8 C5: 125 / 126 -- the player never fires it
    once: bool = False                # M8 C5: 125 (W1) -- a monster's crossing clears it for the level (`once_lines`)
    skills: int = ALL_SKILLS          # M8 C5: the MTF_ skill bits on which EV_Teleport finds `dest` (E1M5: hard only)

    def on_skill(self, skill: int) -> bool:
        """M8 C5: EV_Teleport finds this destination on `skill` (a gamedata SK_*)"""
        from doomfj import gamedata as gd
        return bool(self.skills & gd.skill_bit(skill))

    @property
    def trig(self) -> tuple:
        """the `doors.crossed` trigger tuple (its first field, a door sector there, is the line here)"""
        return (self.line, self.axis, self.coord, self.lo, self.hi)

    @property
    def facing(self) -> int:
        """the destination angle as a monster's facing octant (DI numbering: east 0, counter-clockwise)"""
        return self.angle >> 29


def front_le_of(v1: Tuple[int, int], v2: Tuple[int, int]) -> bool:
    """P_PointOnLineSide's axis shortcuts: a vertical line (dx 0) puts x <= v1.x on side `dy > 0`, a horizontal one
    (dy 0) puts y <= v1.y on side `dx < 0`; side 0 is the front -- so the `c <= coord` side is the front exactly when
    dy < 0 (vertical) / dx > 0 (horizontal)"""
    dx, dy = v2[0] - v1[0], v2[1] - v1[1]
    if dx == 0:
        assert dy != 0, "a zero-length line"
        return dy < 0
    assert dy == 0, "M8 L4: an axis-aligned teleport line only (doors.crossed's test)"
    return dx > 0


def teleporters(map_wad, mapname: str, *, rm=None, cmap=None) -> List[Teleporter]:
    """the level's WR teleport lines in linedef order, each with its destination (EV_Teleport's search, baked). [] on a
    level without one (E1M1). Refuses what the rules above do not cover: a slanted line, a tag with no destination, a
    destination some single-player skill lacks, a destination within a teleport line's reach."""
    from doomfj import gamedata as gd
    lds = map_wad.linedefs(mapname)
    if not any(ld.special in TELEPORT_SPECIALS for ld in lds):
        return []
    assert ALL_SKILLS == gd.MTF_EASY | gd.MTF_NORMAL | gd.MTF_HARD
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import ReferenceModel
    assert TELEPORT_DEST_TYPE == gd.TELEPORT_DEST_TYPE
    rm = rm or ReferenceModel()
    cmap = cmap or bake_bsp(map_wad, mapname)
    secs, sds, verts = map_wad.sectors(mapname), map_wad.sidedefs(mapname), map_wad.vertexes(mapname)
    things = map_wad.things(mapname)

    def leaf_sector(leaf: int) -> int:
        sg = cmap.segs[cmap.subsectors[leaf].firstseg]
        ld = lds[sg.linedef]
        return sds[ld.front if sg.side == 0 else ld.back].sector

    dests = []                                       # (thing, leaf, sector) in WAD (spawn) order
    for t in things:
        if t.type == TELEPORT_DEST_TYPE:
            leaf = rm.point_in_subsector(cmap, t.x, t.y)
            dests.append((t, leaf, leaf_sector(leaf)))

    def search(tag: int, bit: int):
        """EV_Teleport's search on the skill whose MTF_ bit is `bit`: the sectors with the tag in index order, each in
        thinker (spawn) order, over the destinations P_SpawnMapThing spawned on that skill in single player"""
        for si, sec in enumerate(secs):
            if sec.tag != tag:
                continue
            for t, leaf, s in dests:
                if s == si and t.flags & bit and not t.flags & gd.MTF_NOTSINGLE:
                    return (t, leaf, s)
        return None
    out = []
    for li, ld in enumerate(lds):
        if ld.special not in TELEPORT_SPECIALS:
            continue
        a, b = (verts[ld.v1].x, verts[ld.v1].y), (verts[ld.v2].x, verts[ld.v2].y)
        front_le = front_le_of(a, b)
        if a[0] == b[0]:
            axis, coord, lo, hi = "x", a[0], min(a[1], b[1]), max(a[1], b[1])
        else:
            axis, coord, lo, hi = "y", a[1], min(a[0], b[0]), max(a[0], b[0])
        # M8 C5: the search per skill (E1M5's destination is hard-only); one destination for every skill that has one
        per = {bit: search(ld.tag, bit) for bit in (gd.MTF_EASY, gd.MTF_NORMAL, gd.MTF_HARD)}
        found = {f for f in per.values() if f is not None}
        assert found, "teleport line %d (tag %d) has no destination" % (li, ld.tag)
        assert len(found) == 1, "M8 C5: teleport line %d (tag %d) finds a different destination per skill" % (li, ld.tag)
        (t, leaf, s), = found
        skills = sum(bit for bit, f in per.items() if f is not None)
        assert skills == ALL_SKILLS or ld.special in MONSTER_ONLY_SPECIALS, (
            "M8 L4: destination %r is not on every single-player skill" % (t,))
        angle = ((t.angle // 45) * ANG45) & 0xFFFFFFFF
        out.append(Teleporter(line=li, tag=ld.tag, axis=axis, coord=coord, lo=lo, hi=hi, front_le=front_le,
                              dest=(t.x, t.y), angle=angle, dest_leaf=leaf, dest_sector=s, dest_floor=secs[s].floor_h,
                              fog=fog_dest((t.x, t.y), angle, rm), monster_only=ld.special in MONSTER_ONLY_SPECIALS,
                              once=ld.special in ONCE_SPECIALS, skills=skills))
    check_one_per_move(out)
    return out


def player_teleporters(tels) -> list:
    """M8 C5: the lines the PLAYER fires (all but the monster-only 125 / 126), in order"""
    return [t for t in tels if not t.monster_only]


def once_lines(tels) -> list:
    """M8 C5: the W1 lines (125), in order: once line j is latch j (the world's `tp_fired[j]`, fj `tp_w1 + j*dw`)"""
    return [t for t in tels if t.once]


def crossed_side(tel: Teleporter, old16: tuple, new16: tuple, radius: int):
    """M8 C5: P_CrossSpecialLine's call on `tel` for a move (16.16 centres): None when the move does not cross it
    (`doors.crossed`: the centre changed side, the new box overlaps the extent), else True when the old centre was on
    its FRONT (EV_Teleport's `side == 0`) and False from its back"""
    from doomfj.doors import crossed
    if not crossed(tel.trig, old16, new16, radius):
        return None
    a = 1 if tel.axis == "y" else 0
    return (old16[a] <= tel.coord << 16) == tel.front_le


SELF_MARGIN = 4 * REACH_MAX           # a crossing thing's centre: <= 2 * REACH_MAX from the line (a knock step <= 30
                                      # past a radius-30 reach); + the largest blockdist, 2 * REACH_MAX


def fog_on(world) -> bool:
    """the ONE rule "a teleport spawns its fog": a map with a teleport line, the player in a looting mode (the game
    tier's -- world.player_loots; the fj's teleports, fogs and effects pool are emitted there)"""
    from doomfj.world import player_loots
    return bool(getattr(world, "teleports", None)) and player_loots(world.player)


def fog_dest(dest: Tuple[int, int], angle: int, rm) -> Tuple[int, int]:
    """EV_Teleport's destination fog, whole map units: the destination + FOG_AHEAD * (finecosine, finesine) of its
    angle (the repo's trig: rm's fine tables at angle >> angle_shift), floored to whole units (the effects pool's
    positions carry no fraction). `teleporters` bakes it into Teleporter.fog"""
    idx = (angle & 0xFFFFFFFF) >> rm.angle_shift

    def s32(v):
        v &= 0xFFFFFFFF
        return v - (1 << 32) if v >> 31 else v
    x16 = (dest[0] << 16) + FOG_AHEAD * s32(rm._finecos_idx(idx))
    y16 = (dest[1] << 16) + FOG_AHEAD * s32(rm._finesin_idx(idx))
    return x16 >> 16, y16 >> 16


def _near(t: Teleporter, x: int, y: int, margin: int) -> bool:
    """(x, y) lies within `margin` of t's segment on both axes"""
    c, o = (x, y) if t.axis == "x" else (y, x)
    return t.lo - margin <= o <= t.hi + margin and abs(c - t.coord) <= margin


def neighbours(t: Teleporter, u: Teleporter) -> bool:
    """M8 C5: one move's thing can touch both lines (DOOM's spechit could hold both): their segments' boxes, each
    inflated by SELF_MARGIN, overlap. A line is its own neighbour"""
    def box(v):
        return ((v.coord, v.coord, v.lo, v.hi) if v.axis == "x" else (v.lo, v.hi, v.coord, v.coord))
    (ax0, ax1, ay0, ay1), (bx0, bx1, by0, by1) = box(t), box(u)
    return (ax0 - SELF_MARGIN <= bx1 + SELF_MARGIN and bx0 - SELF_MARGIN <= ax1 + SELF_MARGIN
            and ay0 - SELF_MARGIN <= by1 + SELF_MARGIN and by0 - SELF_MARGIN <= ay1 + SELF_MARGIN)


def check_one_per_move(tels) -> None:
    """ONE TELEPORT PER MOVE, and no teleporting thing stomps ITSELF: every destination lies farther than SELF_MARGIN
    from its own line's segment and from every NEIGHBOUR line's (`neighbours`: a line one move can touch together
    with it) on one axis at least -- so a thing that just crossed a line (its centre and its pre-move centre within
    2 * REACH_MAX of the segment) is farther than any blockdist from the destination (the fj's stomp test may skip
    the mover's own slot without a test), and no line of the same move can fire from the destination. M8 C5 (E1M7):
    a destination NEXT TO A FAR line is fine -- that line is no part of the move that teleported (DOOM's spechit holds
    only lines the move's box touched), so the check is per neighbour pair, not every pair; the next move from the
    destination may cross that line, as in DOOM (E1M7's line 516 lands 32 units from line 521)"""
    for t in tels:
        for u in tels:
            if neighbours(t, u):
                assert not _near(u, t.dest[0], t.dest[1], SELF_MARGIN), (
                    "M8 L4: line %d's destination %r is within line %d's reach" % (t.line, t.dest, u.line))


def crossed_front(tel: Teleporter, old16: tuple, new16: tuple, radius: int) -> bool:
    """P_TryMove -> P_CrossSpecialLine -> EV_Teleport's side test: a move (16.16 centres) that crosses the line
    (`doors.crossed`, `radius` in map units) FROM ITS FRONT"""
    return bool(crossed_side(tel, old16, new16, radius))


def stomp_victims(world, dest: Tuple[int, int], radius: int, *, mover=None) -> List[tuple]:
    """PIT_StompThing's things at `dest` (map units) for a thing of `radius`, in the model's order (slots, then
    barrels, then the player): every SHOOTABLE thing whose box overlaps (|dx| < r + r', strict, both axes) -- the live
    monsters (active and shootable) but `mover` (the teleporting slot) as ("mon", slot), the standing barrels as
    ("bar", b), and the living player as ("player", -1) unless he is the one teleporting (`mover` None). A monster's
    teleport is refused by any (`stomped`); the player's kills each (combat._teleport_player)"""
    from doomfj.combat import BARREL_R, PLAYER_R
    ws = world.ws
    dx, dy = dest
    out = []
    for k in range(world.layout.nmon):
        if k == mover or not (ws.mon_active[k] and ws.mon_shootable[k]):
            continue
        bd = radius + world.mon_radius[k]
        if abs(ws.mon_x[k] - dx) < bd and abs(ws.mon_y[k] - dy) < bd:
            out.append(("mon", k))
    for b, t in enumerate(world.barrel_things):
        if ws.bar_state[b] and ws.bar_health[b] > 0:
            bd = radius + BARREL_R
            if abs(t.x - dx) < bd and abs(t.y - dy) < bd:
                out.append(("bar", b))
    if mover is not None and world.player_alive():
        bd = (radius + PLAYER_R) << 16
        if abs(ws.px - (dx << 16)) < bd and abs(ws.py - (dy << 16)) < bd:
            out.append(("player", -1))
    return out


def stomped(world, dest: Tuple[int, int], radius: int, *, mover=None) -> bool:
    """PIT_StompThing's refusal of a MONSTER's teleport (`mover` its slot) at `dest`: any `stomp_victims`"""
    return bool(stomp_victims(world, dest, radius, mover=mover))
