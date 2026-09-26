"""S3a -- the gameplay model: the persistent-state SCHEMA, `WorldState`, and one TIC of the game.

This is the Python twin of the game logic the fj program will run (docs/plan-gameplay.md, phase 0
stream S3), written to become the oracle's extension: integer-exact, deterministic, and reading
every table from one place (`doomfj.gamedata` for DOOM's data, `doomfj.rng` for randomness, the
RULES block below for the approved simplifications).

SCHEMA FIRST. `build_schema(layout)` lists every persistent cell of the game -- name, width, count,
signedness, persisted or derived, owner phase, the fj label that already holds it. `WorldState` is
built from that table and wraps every write to the declared width, exactly as an fj cell would. The
same table is meant to drive the fj declarations, the M1 persist sets and the state probe, so it
carries the fields S3a does NOT simulate yet (player health, armor, ammo, the weapon state machine,
monster health, the 8-slot fireball pool, the effects pool, pickup and barrel state, the key):
S3b builds on them without a schema change.

THE TIC (`World.tic`), in this order:
  1. doors -- `doors.door_tic` for every door, pressed by the player's use key in its use box, or
     by a monster that bumped it last tic (`d_monreq`);
  2. the player -- weapon (S3b; today the `fire` key only makes a NOISE, standing in for
     P_FireWeapon's P_NoiseAlert), then the move through the oracle's own `step_sim`;
  3. monsters, in slot order from the scheduler's rotating cursor (see `_monsters_phase`);
  4. projectiles by pool slot (S3b; nothing spawns one yet);
  5. `leveltime += 1`.

MONSTERS are DOOM's A_Look / A_Chase / P_Move / P_TryMove / P_NewChaseDir (Chocolate Doom's
p_enemy.c and p_map.c, quoted in gamedata's sources), with the approved simplifications (D5) and a
few model conventions, all named here so nothing is silent:
  * K = 3 HEAVY actions per tic. A monster whose next state's action is heavy and finds no slot
    keeps tics = 0 and retries next tic; the cursor moves to the first deferred monster, so the
    deferred are served first (round robin, starvation-free, deterministic).
  * D-WAKE: A_Look is cheap (it runs in the monster's own slot), so waking ENTERS the see state
    without running its A_Chase this tic -- DOOM runs it at once. The first chase step comes
    `seestate.tics` later.
  * Rounded 8-direction steps: 8/6 for speed 8, 10/7 for speed 10 (DOOM: speed * 47000/65536).
    Monster positions are therefore whole map units, and the AI's geometry (distances, deltas, the
    field of view) is integer map units; the player's position enters as floor(x / 65536).
  * P_NewChaseDir: a direction that already failed in this call is not tried again (exactly
    equivalent -- a failed P_TryMove changes nothing), and at most NEWCHASEDIR_MAX_TRIES distinct
    tries are made; when capped the monster gets DI_NODIR and tries again on its next chase.
  * Facing is an OCTANT. A_Chase's `angle &= 7<<29` makes that exact while chasing; A_FaceTarget
    stores the NEAREST octant of the offset (`octant_of`), which is what the sprite rotation wants.
  * The field of view (P_LookForPlayers, allaround = false) is the half-plane test
    dot(facing, offset) < 0, i.e. DOOM's `ANG90 < an < ANG270` without the atan.
  * No sound playback: the RNG calls that only choose a sound (see sound, active sound) are not
    made. No `lastlook` (single player). No infighting (the target is always the player).
  * Monsters open plain doors (special 1, not ML_SECRET) when a move fails inside the door's use
    box and the door is shut or closing -- the only cases in which DOOM's EV_VerticalDoor answers a
    monster. The press lands on the next tic's door phase.
  * Sight is an injectable callback `sight(world, slot) -> bool`. The default, `los_to_player`, is
    2D: the segment between the two centres must not touch a one-sided line or a two-sided line
    whose opening is closed at this tic's door heights. Plan section 5 may replace it by "drawn
    last frame" (the `mon_seen` cell is reserved for that).
  * Sound: P_RecursiveSound as REGIONS -- the sectors joined by two-sided lines whose opening is
    static and positive collapse to one region; each door sector is its own node, joined to its
    neighbours while its opening is positive. E1M1 has no ML_SOUNDBLOCK line (asserted), so this
    is exactly DOOM's flood fill.
  * The player still walks through things (today's oracle and binary); monsters DO treat the player
    as solid.

LEAF LISTS. Every MOBILE thing (the monster slots now; the fireball and effect pools in S3b) has a
leaf, recomputed only when it moves and re-linked only when the leaf changes. Each leaf's list is
kept in ascending mobile index (`leaf_head` / `mob_next`, the fj `sshead` / `thnext` shape), so it
equals a from-scratch build at every tic -- `leaf_lists_from_scratch` is that build, and a test holds
the two equal. Monster slots are in WAD order, so merging these lists with the renderer's static
runtime things by WAD index reproduces the renderer's per-leaf order.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.doorcode import door_line_ids
from doomfj.doors import (CLOSING, IDLE, USE_RANGE, door_states, door_tic, heights_for_states,
                          in_use_box, in_use_box_fixed, pass_state, use_boxes_xy)
from doomfj.reference_model import (ReferenceModel, Scene, SimState, apply_sector_heights,
                                    spawn_state)

# ================================================================================================
# RULES -- the approved simplifications (D5) and the model's conventions. ONE definition each; the
# emitter reads them too, so changing one moves both mirrors.
# ================================================================================================
K_HEAVY = 3                        # heavy monster actions per tic (plan 6.1, D5)
NEWCHASEDIR_MAX_TRIES = 6          # distinct P_TryWalk directions per P_NewChaseDir call (D5)
DIAG_STEP = {8: 6, 10: 7}          # rounded diagonal step per monster speed (D5)
FIREBALL_POOL = 8                  # imp fireballs alive at once; a full pool fizzles (D5, S3b)
FX_POOL = 2                        # puffs and blood alive at once (D5, S3b)
TICS_FOREVER = 15                  # schema encoding of DOOM's tics == -1 (one nibble)
MOVECOUNT_FLOOR = -1               # movecount saturates here; see `_a_chase`
OCTANT_TAN_NUM, OCTANT_TAN_DEN = 106, 256   # tan(22.5 deg) ~ 106/256: the octant classifier
MONSTER_DOOR_SPECIALS = frozenset({1})       # P_UseSpecialLine: DR doors a monster may open
MELEE_REACH = (gd.MELEERANGE >> 16) - 20 + (gd.PLAYERRADIUS >> 16)   # 60: P_CheckMeleeRange
LOOK_BEHIND_REACH = gd.MELEERANGE >> 16      # 64: P_LookForPlayers sees behind within this
CHASE_DEADZONE = 10                # P_NewChaseDir: |delta| <= 10 units picks no axis direction
MISSILE_BIAS, MISSILE_NOMELEE_BIAS, MISSILE_CAP = 64, 128, 200      # P_CheckMissileRange
STEP_UP = gd.MAX_STEP_UP >> 16     # 24: the highest step up a thing can take
DROPOFF_MAX = 24                   # P_TryMove: a non-DROPOFF thing may not stand over a drop > 24
PLAYER_R = gd.PLAYERRADIUS >> 16   # 16
KEYS = ("forward", "back", "turn_left", "turn_right", "use", "fire")

assert all(DIAG_STEP[s] == (s * 47000 + 32768) // 65536 for s in DIAG_STEP), \
    "DIAG_STEP must be DOOM's speed * 47000/65536 rounded to the nearest unit"
assert max(s.tics for s in gd.STATES.values()) < TICS_FOREVER

# verdicts of a monster move
OK, V_THING, V_WALL, V_MONLINE, V_HEIGHT, V_STEP, V_DROPOFF = (
    "ok", "thing", "wall", "monsterline", "height", "step", "dropoff")
VERDICTS = (V_THING, V_WALL, V_MONLINE, V_HEIGHT, V_STEP, V_DROPOFF)


# ================================================================================================
# GEOMETRY -- integer, exact, no multiply by a runtime value except where the oracle already does
# ================================================================================================
def aprox_distance(dx: int, dy: int) -> int:
    """P_AproxDistance: |dx| + |dy| - min(|dx|, |dy|) / 2, in the units it is given."""
    dx, dy = abs(dx), abs(dy)
    if dx < dy:
        return dx + dy - (dx >> 1)
    return dx + dy - (dy >> 1)


def octant_of(dx: int, dy: int) -> int:
    """The DI_ direction NEAREST to the offset (dx, dy): 0 = east, counter-clockwise. The
    boundaries are the 22.5-degree lines, compared as |a| * 256 vs |b| * 106 (tan 22.5 ~ 0.41406);
    a tie goes to the axis. (0, 0) is east, as DOOM's R_PointToAngle2 gives angle 0."""
    ax, ay = abs(dx), abs(dy)
    if ay * OCTANT_TAN_DEN <= ax * OCTANT_TAN_NUM:
        return gd.DI_EAST if dx >= 0 else gd.DI_WEST
    if ax * OCTANT_TAN_DEN <= ay * OCTANT_TAN_NUM:
        return gd.DI_NORTH if dy > 0 else gd.DI_SOUTH
    if dx > 0:
        return gd.DI_NORTHEAST if dy > 0 else gd.DI_SOUTHEAST
    return gd.DI_NORTHWEST if dy > 0 else gd.DI_SOUTHWEST


# the facing octant as an (unnormalised) direction vector; only the SIGN of a dot product is used
FACING_VEC = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))


def behind(facing: int, dx: int, dy: int) -> bool:
    """P_LookForPlayers' `ANG90 < an < ANG270` for a facing that is a multiple of 45 degrees: the
    target is behind exactly when dot(facing, offset) < 0 (perpendicular is NOT behind)."""
    fx, fy = FACING_VEC[facing]
    return fx * dx + fy * dy < 0


def turn_toward(facing: int, movedir: int) -> int:
    """A_Chase's `angle -= / += ANG90/2` toward movedir, on octants: delta = (facing - movedir)
    mod 8 read as DOOM's signed 32-bit angle difference -- 1..3 turn clockwise, 4..7 (4 is -2^31,
    negative) turn counter-clockwise."""
    diff = (facing - movedir) & 7
    if diff == 0:
        return facing
    return (facing - 1) & 7 if diff < 4 else (facing + 1) & 7


def step_delta(speed: int, movedir: int) -> Tuple[int, int]:
    """One P_Move step in map units: `speed` along an axis, DIAG_STEP[speed] on both for a diagonal."""
    s, d = speed, DIAG_STEP[speed]
    return ((s, 0), (d, d), (0, s), (-d, d), (-s, 0), (-d, -d), (0, -s), (d, -d))[movedir]


def _orient(ax, ay, bx, by, cx, cy) -> int:
    v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    return (v > 0) - (v < 0)


def segments_touch(p, q, a, b) -> bool:
    """Closed-segment intersection, exact on integers: True if segment p-q and segment a-b share any
    point (touching counts)."""
    o1 = _orient(*p, *q, *a)
    o2 = _orient(*p, *q, *b)
    o3 = _orient(*a, *b, *p)
    o4 = _orient(*a, *b, *q)
    if o1 != o2 and o3 != o4 and o1 * o2 <= 0 and o3 * o4 <= 0:
        if o1 != 0 or o2 != 0:
            return True
    if o1 == o2 == o3 == o4 == 0:      # collinear: overlap of the projections
        return (max(min(p[0], q[0]), min(a[0], b[0])) <= min(max(p[0], q[0]), max(a[0], b[0]))
                and max(min(p[1], q[1]), min(a[1], b[1])) <= min(max(p[1], q[1]), max(a[1], b[1])))
    return False


def _c_div(a: int, b: int) -> int:
    """C integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


# ================================================================================================
# SCHEMA
# ================================================================================================
@dataclass(frozen=True)
class Field:
    name: str
    bits: int
    count: int
    signed: bool
    kind: str          # "persist": authoritative state | "derived": a cache of a pure function
    group: str
    phase: str         # "existing" (in the binary today) | "S3a" | "S3b" | "P3"
    label: str         # the fj label that holds it today ("" = a new cell)
    doc: str

    @property
    def nibbles(self) -> int:
        return (self.bits + 3) // 4

    @property
    def lo(self) -> int:
        return -(1 << (self.bits - 1)) if self.signed else 0

    @property
    def hi(self) -> int:
        return (1 << (self.bits - 1)) - 1 if self.signed else (1 << self.bits) - 1


@dataclass(frozen=True)
class Layout:
    """The counts the schema depends on, derived from the level."""
    nmon: int          # monster slots: the union of every skill's monsters (the image holds all)
    ndoor: int
    nleaf: int         # subsectors
    nsound: int        # sound nodes (static regions + door sectors)
    npickup: int
    nbarrel: int

    @property
    def nmobile(self) -> int:
        return self.nmon + FIREBALL_POOL + FX_POOL


def _index_bits(n: int) -> int:
    return max(1, (n - 1).bit_length())


def build_schema(lay: Layout) -> Tuple[Field, ...]:
    """THE table of persistent cells. Order is the canonical order (digests, dumps, the probe)."""
    assert lay.nmobile <= 254, "leaf lists store mobile index + 1 in a byte"
    fs: List[Field] = []

    def f(name, bits, count=1, signed=False, kind="persist", group="", phase="S3a", label="",
          doc=""):
        fs.append(Field(name, bits, count, signed, kind, group, phase, label, doc))

    leaf_bits, mon_bits = _index_bits(lay.nleaf), _index_bits(lay.nmon)
    # -- game ------------------------------------------------------------------------------------
    f("skill", 2, group="game", doc="DOOM gameskill: 1 easy, 2 medium, 3 hard (D7, menu)")
    f("leveltime", 16, group="game", doc="tics since level start, wraps (nukage timing, S3b)")
    f("sched_cursor", mon_bits, group="game", doc="the K-slot scheduler's first slot this tic")
    # -- input and mode (existing standalone persist set) ----------------------------------------
    f("mode", 1, group="input", phase="existing", label="mode", doc="1 = menu frame producer")
    for k in "fblru":
        f("kb_" + k, 1, group="input", phase="existing", label="kb_" + k, doc="held key flag")
    # -- player --------------------------------------------------------------------------------
    f("px", 32, signed=True, group="player", phase="existing", label="viewx", doc="16.16")
    f("py", 32, signed=True, group="player", phase="existing", label="viewy", doc="16.16")
    f("pangle", 32, group="player", phase="existing", label="viewangle", doc="BAM")
    f("p_health", 12, signed=True, group="player", phase="S3b", doc="health; < 0 after a kill")
    f("p_armor", 8, group="player", phase="S3b", doc="armor points, 0..200")
    f("p_armortype", 2, group="player", phase="S3b", doc="0 none, 1 green, 2 blue")
    f("p_ammo", 10, count=gd.NUMAMMO, group="player", phase="S3b", doc="by AM_*, <= 2*MAXAMMO")
    f("p_backpack", 1, group="player", phase="S3b", doc="max ammo doubled")
    f("p_owned", 1, count=gd.NUMWEAPONS, group="player", phase="S3b", doc="by WP_*")
    f("p_ready", 4, group="player", phase="S3b", doc="readyweapon, WP_*")
    f("p_pending", 4, group="player", phase="S3b", doc="pendingweapon, WP_* or 10 = none")
    f("p_wpn_state", 8, group="player", phase="S3b", doc="weapon psprite state (gamedata index)")
    f("p_wpn_tics", 4, group="player", phase="S3b", doc="its tics; 15 = forever")
    f("p_wpn_sy", 8, group="player", phase="S3b", doc="weapon height, map units 32..128")
    f("p_flash_state", 8, group="player", phase="S3b", doc="flash psprite state")
    f("p_flash_tics", 4, group="player", phase="S3b", doc="its tics")
    f("p_refire", 8, group="player", phase="S3b", doc="shots since the trigger went down")
    f("p_attackdown", 1, group="player", phase="S3b", doc="fire held last tic")
    f("p_usedown", 1, group="player", phase="S3b", doc="use held last tic")
    f("p_damagecount", 8, group="player", phase="S3b", doc="red palette flash")
    f("p_bonuscount", 8, group="player", phase="S3b", doc="gold palette flash")
    f("p_strength", 16, group="player", phase="S3b", doc="berserk: powers[pw_strength] counter")
    f("p_cards", 1, count=gd.NUMCARDS, group="player", phase="S3b", doc="keys; E1M1: blue card")
    f("p_mobj_state", 8, group="player", phase="S3b", doc="the player thing's state")
    f("p_mobj_tics", 4, group="player", phase="S3b", doc="its tics; 15 = forever")
    f("p_dead", 1, group="player", phase="S3b", doc="playerstate == PST_DEAD")
    # -- doors (existing DOOR_PERSIST, plus the monster press) ------------------------------------
    f("d_state", 4, count=lay.ndoor, group="door", phase="existing", label="dstate",
      doc="door stop index; doors in ascending sector order")
    f("d_dir", 2, count=lay.ndoor, group="door", phase="existing", label="ddir",
      doc="IDLE 0, OPENING 1, CLOSING 2")
    f("d_sub", 4, count=lay.ndoor, group="door", phase="existing", label="dsub", doc="step timer")
    f("d_wait", 8, count=lay.ndoor, group="door", phase="existing", label="dwait",
      doc="open-wait timer")
    f("d_monreq", 1, count=lay.ndoor, group="door", doc="a monster pressed it; next door tic")
    # -- sound ------------------------------------------------------------------------------------
    f("snd_alert", 1, count=lay.nsound, group="sound",
      doc="node heard a shot (DOOM's sector soundtarget)")
    # -- rng --------------------------------------------------------------------------------------
    f("rng_world", R.STATE_BITS, group="rng", doc="stream 0: level start, barrels")
    f("rng_player", R.STATE_BITS, group="rng", doc="stream 1: weapon spread and damage (S3b)")
    f("rng_fx", R.STATE_BITS, group="rng", doc="stream 2: puffs, blood, impacts (S3b)")
    f("mon_rng", R.STATE_BITS, count=lay.nmon, group="rng", doc="stream 3 + slot")
    # -- monsters ---------------------------------------------------------------------------------
    n = lay.nmon
    f("mon_active", 1, count=n, group="monster", doc="spawned at this skill, not removed")
    f("mon_state", 8, count=n, group="monster", doc="gamedata state index")
    f("mon_tics", 4, count=n, group="monster", doc="tics left; 15 = forever")
    f("mon_x", 16, count=n, signed=True, group="monster", label="thpos_rt",
      doc="map units (fj: the integer half of thpos_rt's 16.16)")
    f("mon_y", 16, count=n, signed=True, group="monster", label="thpos_rt", doc="map units")
    f("mon_floorz", 16, count=n, signed=True, group="monster", doc="floorz = z, map units")
    f("mon_movedir", 4, count=n, group="monster", doc="DI_*, 8 = none")
    f("mon_facing", 3, count=n, group="monster", doc="facing octant, DI_ numbering")
    f("mon_movecount", 5, count=n, signed=True, group="monster", doc="-1..15, saturates at -1")
    f("mon_reaction", 4, count=n, group="monster", doc="reactiontime")
    f("mon_threshold", 7, count=n, group="monster", doc="threshold, <= BASETHRESHOLD")
    f("mon_target", 1, count=n, group="monster", doc="has a target (always the player)")
    f("mon_justattacked", 1, count=n, group="monster", doc="MF_JUSTATTACKED")
    f("mon_justhit", 1, count=n, group="monster", doc="MF_JUSTHIT (set by damage, S3b)")
    f("mon_ambush", 1, count=n, group="monster", doc="MF_AMBUSH (cleared by A_FaceTarget)")
    f("mon_solid", 1, count=n, group="monster", doc="MF_SOLID (cleared by A_Fall)")
    f("mon_shootable", 1, count=n, group="monster", doc="MF_SHOOTABLE (cleared on death, S3b)")
    f("mon_health", 12, count=n, signed=True, group="monster", phase="S3b", doc="health")
    f("mon_seen", 1, count=n, group="monster", phase="P3",
      doc="drawn last frame: sight from the picture (plan section 5), written by the renderer")
    f("mon_drop", 2, count=n, group="monster", phase="S3b", doc="0 none, 1 dropped, 2 taken")
    f("mon_leaf", leaf_bits, count=n, kind="derived", group="monster",
      doc="point location of (mon_x, mon_y)")
    # -- leaf lists -------------------------------------------------------------------------------
    f("leaf_head", 8, count=lay.nleaf, kind="derived", group="lists", label="sshead",
      doc="first mobile in the leaf, +1 (0 = empty), ascending order")
    f("mob_next", 8, count=lay.nmobile, kind="derived", group="lists", label="thnext",
      doc="next mobile in the same leaf, +1; mobiles = monsters, then fireballs, then fx")
    # -- fireball pool (S3b) ----------------------------------------------------------------------
    p = FIREBALL_POOL
    f("proj_active", 1, count=p, group="proj", phase="S3b", doc="slot in flight")
    f("proj_state", 8, count=p, group="proj", phase="S3b", doc="gamedata state index")
    f("proj_tics", 4, count=p, group="proj", phase="S3b", doc="tics left")
    f("proj_x", 32, count=p, signed=True, group="proj", phase="S3b", doc="16.16")
    f("proj_y", 32, count=p, signed=True, group="proj", phase="S3b", doc="16.16")
    f("proj_momx", 32, count=p, signed=True, group="proj", phase="S3b", doc="16.16 per tic")
    f("proj_momy", 32, count=p, signed=True, group="proj", phase="S3b", doc="16.16 per tic")
    f("proj_src", mon_bits, count=p, group="proj", phase="S3b", doc="shooter's monster slot")
    f("proj_leaf", leaf_bits, count=p, kind="derived", group="proj", phase="S3b",
      doc="point location")
    # -- puff/blood pool (S3b) --------------------------------------------------------------------
    q = FX_POOL
    f("fx_active", 1, count=q, group="fx", phase="S3b", doc="slot alive")
    f("fx_state", 8, count=q, group="fx", phase="S3b", doc="gamedata state index")
    f("fx_tics", 4, count=q, group="fx", phase="S3b", doc="tics left")
    f("fx_x", 32, count=q, signed=True, group="fx", phase="S3b", doc="16.16")
    f("fx_y", 32, count=q, signed=True, group="fx", phase="S3b", doc="16.16")
    f("fx_leaf", leaf_bits, count=q, kind="derived", group="fx", phase="S3b",
      doc="point location")
    # -- pickups and barrels (S3b) ----------------------------------------------------------------
    f("pickup_taken", 1, count=lay.npickup, group="pickup", phase="S3b", label="thvis",
      doc="picked up (fj thvis holds the inverse for baked things)")
    f("bar_state", 8, count=lay.nbarrel, group="barrel", phase="S3b", doc="state index")
    f("bar_tics", 4, count=lay.nbarrel, group="barrel", phase="S3b", doc="tics left")
    f("bar_health", 8, count=lay.nbarrel, signed=True, group="barrel", phase="S3b",
      doc="health (20 at spawn)")
    f("bar_solid", 1, count=lay.nbarrel, group="barrel", phase="S3b", doc="blocks things")
    names = [x.name for x in fs]
    assert len(names) == len(set(names)), "duplicate schema field"
    return tuple(fs)


def schema_table(schema: Sequence[Field]) -> str:
    """The schema as an ASCII table (the one to paste into docs and reports)."""
    head = "%-17s %4s %3s %5s %-3s %-7s %-7s %-8s %-9s %s" % (
        "name", "bits", "nib", "count", "sgn", "kind", "group", "phase", "label", "doc")
    rows = [head, "-" * len(head)]
    for x in schema:
        rows.append("%-17s %4d %3d %5d %-3s %-7s %-7s %-8s %-9s %s" % (
            x.name, x.bits, x.nibbles, x.count, "s" if x.signed else "u", x.kind, x.group,
            x.phase, x.label or "-", x.doc))
    return "\n".join(rows)


def _fit(value, fld: Field, strict: bool) -> int:
    if isinstance(value, bool):
        value = int(value)
    if not isinstance(value, int):
        raise TypeError("%s: expected an int, got %r" % (fld.name, value))
    if strict and not fld.lo <= value <= fld.hi:
        raise OverflowError("%s = %d outside %d..%d (%d bits %s)"
                            % (fld.name, value, fld.lo, fld.hi, fld.bits,
                               "signed" if fld.signed else "unsigned"))
    mask = (1 << fld.bits) - 1
    value &= mask
    if fld.signed and value >> (fld.bits - 1):
        value -= 1 << fld.bits
    return value


class FieldArray(list):
    """One array field: a list whose element writes wrap to the field's width."""
    __slots__ = ("field", "strict")

    def __init__(self, fld: Field, strict: bool):
        super().__init__([0] * fld.count)
        self.field = fld
        self.strict = strict

    def __setitem__(self, i, value):
        if isinstance(i, slice):
            raise TypeError("assign elements one at a time")
        super().__setitem__(i, _fit(value, self.field, self.strict))

    def append(self, v):                         # a fixed-size cell array does not grow
        raise TypeError("schema arrays have a fixed count")

    extend = insert = pop = remove = append      # type: ignore[assignment]


class WorldState:
    """The persistent game state, built from a schema. Every write wraps to the declared width
    (two's complement for signed fields), as the fj cell would; `strict=True` raises instead, which
    is how the tests prove no field is too narrow for what the model writes."""

    def __init__(self, schema: Sequence[Field], *, strict: bool = False):
        object.__setattr__(self, "schema", tuple(schema))
        object.__setattr__(self, "strict", strict)
        object.__setattr__(self, "_fields", {x.name: x for x in schema})
        for x in schema:
            object.__setattr__(self, x.name, 0 if x.count == 1 else FieldArray(x, strict))

    def __setattr__(self, name, value):
        fld = self._fields.get(name)
        if fld is None:
            raise AttributeError("%s is not a schema field" % name)
        if fld.count != 1:
            raise TypeError("%s is an array field: assign its elements" % name)
        object.__setattr__(self, name, _fit(value, fld, self.strict))

    def as_dict(self) -> Dict[str, object]:
        return {x.name: (getattr(self, x.name) if x.count == 1 else list(getattr(self, x.name)))
                for x in self.schema}

    def load(self, values: Dict[str, object]) -> None:
        for x in self.schema:
            v = values[x.name]
            if x.count == 1:
                setattr(self, x.name, v)
            else:
                arr = getattr(self, x.name)
                assert len(v) == x.count, x.name
                for i, e in enumerate(v):
                    arr[i] = e

    def copy(self) -> "WorldState":
        out = WorldState(self.schema, strict=self.strict)
        out.load(self.as_dict())
        return out

    def digest(self) -> str:
        """sha256 over every field in schema order -- the trajectory hash."""
        blob = json.dumps([[x.name, getattr(self, x.name) if x.count == 1
                            else list(getattr(self, x.name))] for x in self.schema],
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode("ascii")).hexdigest()


# ================================================================================================
# EVENTS -- what happened in one tic (counts the tests and gates can require to be non-zero)
# ================================================================================================
@dataclass
class TicEvents:
    tic: int
    heavy: List[int] = field(default_factory=list)        # slots that took a K slot, in order
    deferred: List[int] = field(default_factory=list)     # slots that wanted one and waited
    wakes: List[Tuple[int, str]] = field(default_factory=list)   # (slot, "sight" | "sound")
    moves: List[int] = field(default_factory=list)
    leaf_changes: List[Tuple[int, int, int]] = field(default_factory=list)   # (slot, old, new)
    blocked: Dict[str, int] = field(default_factory=lambda: {v: 0 for v in VERDICTS})
    tries: int = 0                                         # P_Move position tests
    newchasedir: int = 0
    capped: int = 0                                        # NewChaseDir calls that hit the cap
    decisions: List[Tuple[int, str]] = field(default_factory=list)   # (slot, "melee"|"missile")
    attacks: List[Tuple[int, str]] = field(default_factory=list)     # (slot, action) -- S3b
    door_uses: List[Tuple[int, int]] = field(default_factory=list)   # (slot, door sector)
    noise: bool = False

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def next_cursor(cursor: int, first_deferred: Optional[int], nmon: int) -> int:
    """The rotating cursor: the next tic starts at the first monster that was deferred, so it is
    served first; with no deferral the cursor stays. Injectable (World(cursor_policy=...)) so a
    test can plant a starving policy and watch the fairness check catch it."""
    return cursor if first_deferred is None else first_deferred


# ================================================================================================
# THE WORLD
# ================================================================================================
class World:
    """E1M1's game state plus the static level data it is simulated against.

    `World(skill=gd.SK_HARD)` spawns the level; `tic(keys)` advances one tic and returns its
    `TicEvents`; `ws` is the `WorldState`; `reset(skill)` is the restart block (NEW GAME)."""

    def __init__(self, map_wad=None, mapname: str = "E1M1", skill: int = gd.SK_HARD, *,
                 rm: Optional[ReferenceModel] = None,
                 sight: Optional[Callable[["World", int], bool]] = None,
                 k_heavy: int = K_HEAVY, cursor_policy: Callable = next_cursor,
                 strict: bool = False):
        if map_wad is None:
            from doomfj.config import DEFAULT_MAP_WAD
            from doomfj.wad import WadFile
            map_wad = WadFile.from_path(DEFAULT_MAP_WAD)
        self.mw, self.mapname = map_wad, mapname
        self.rm = rm or ReferenceModel()
        self.sight = sight or World.los_to_player
        self.k_heavy = k_heavy
        self.cursor_policy = cursor_policy
        self.strict = strict
        self._build_level()
        self.layout = Layout(nmon=len(self.mon_things), ndoor=len(self.door_order),
                             nleaf=len(self.cmap.subsectors), nsound=self.nsound,
                             npickup=len(self.pickup_things), nbarrel=len(self.barrel_things))
        self.schema = build_schema(self.layout)
        self.reset(skill)

    # ---------------------------------------------------------------------------- static level
    def _build_level(self) -> None:
        mw, M = self.mw, self.mapname
        from doomfj.mapcompiler import bake_bsp
        self.cmap = bake_bsp(mw, M)
        self.lds, self.sds, self.secs = mw.linedefs(M), mw.sidedefs(M), mw.sectors(M)
        lds, sds, secs, cmap = self.lds, self.sds, self.secs, self.cmap
        assert not any(ld.flags & gd.ML_SOUNDBLOCK for ld in lds), (
            "ML_SOUNDBLOCK lines need P_RecursiveSound's (sector, blocks) state; the region "
            "model assumes a map without them")
        # -- things: the union of every single-player skill, in WAD order ----------------------
        self.things = [t for t in mw.things(M)
                       if t.type not in gd.NOT_THINGS and not t.flags & gd.MTF_NOTSINGLE
                       and t.flags & (gd.MTF_EASY | gd.MTF_NORMAL | gd.MTF_HARD)]
        unknown = sorted({t.type for t in self.things} - set(gd.THING_TYPES))
        assert not unknown, "thing types missing from gamedata.THING_TYPES: %s" % unknown
        self.mon_things = [t for t in self.things if t.type in gd.MONSTER_DOOMEDNUMS]
        self.barrel_things = [t for t in self.things if t.type == 2035]
        self.pickup_things = [t for t in self.things
                              if gd.THING_TYPES[t.type].flags & gd.MF_SPECIAL]
        self.decor_solid = [t for t in self.things
                            if t.type not in gd.MONSTER_DOOMEDNUMS and t.type != 2035
                            and gd.THING_TYPES[t.type].solid]
        self.mon_info = [gd.MOBJINFO[gd.MONSTER_DOOMEDNUMS[t.type]] for t in self.mon_things]
        self.mon_radius = [mi.radius >> 16 for mi in self.mon_info]
        self.mon_height = [mi.height >> 16 for mi in self.mon_info]
        self.mon_speed = [mi.speed for mi in self.mon_info]
        # -- leaf -> sector index (mapcompiler.seg_sector's rule, as an index) --------------------
        self.leaf_sector = []
        for ss in cmap.subsectors:
            if not ss.numsegs:
                self.leaf_sector.append(-1)
                continue
            sg = cmap.segs[ss.firstseg]
            ld = lds[sg.linedef]
            self.leaf_sector.append(sds[ld.front if sg.side == 0 else ld.back].sector)
        assert min(self.leaf_sector) >= 0, (
            "a seg-less leaf has no sector; point location could land a thing in it, and the "
            "model has no rule for that -- refuse the map rather than index sector -1")
        # -- doors (doors.py is the SSOT; the gate steps them exactly this way) ------------------
        tbl = door_states(secs, lds, sds)
        self.door_order = sorted(tbl)
        self.door_nstates = {si: len(v) for si, v in tbl.items()}
        self.door_pass = {si: pass_state(secs, lds, sds, si) for si in self.door_order}
        self.door_boxes = use_boxes_xy(secs, lds, sds, cmap.vertexes)
        self.door_lines = door_line_ids(secs, lds, sds, tbl)
        self.open_h = {si: (secs[si].floor_h, tbl[si][-1]) for si in self.door_order}
        self.secs_c = apply_sector_heights(secs, self.open_h)   # the collision map: doors open
        self.mon_door_boxes = {}
        for si in self.door_order:
            vs = [v for ld in lds if ld.special in MONSTER_DOOR_SPECIALS
                  and not ld.flags & gd.ML_SECRET and 0 <= ld.back < len(sds)
                  and sds[ld.back].sector == si for v in (ld.v1, ld.v2)]
            if vs:
                xs = [cmap.vertexes[v][0] for v in vs]
                ys = [cmap.vertexes[v][1] for v in vs]
                self.mon_door_boxes[si] = (min(xs) - USE_RANGE, min(ys) - USE_RANGE,
                                           max(xs) + USE_RANGE, max(ys) + USE_RANGE)
        # -- lines, in 16.16, for the exhaustive monster line test and for sight ------------------
        V = cmap.vertexes
        self._lines = []
        for li, ld in enumerate(lds):
            (x1, y1), (x2, y2) = V[ld.v1], V[ld.v2]
            one = ld.back == -1
            fs = sds[ld.front].sector
            bs = -1 if one else sds[ld.back].sector
            self._lines.append((li, min(x1, x2) << 16, max(x1, x2) << 16, min(y1, y2) << 16,
                                max(y1, y2) << 16, x1 << 16, y1 << 16, x2 << 16, y2 << 16,
                                one, ld.flags, fs, bs))
        doors = set(self.door_order)
        self._sight_walls, self._sight_doors = [], []
        for (li, x0, x1_, y0, y1_, ax, ay, bx, by, one, flags, fs, bs) in self._lines:
            seg = ((ax, ay), (bx, by), (x0, x1_, y0, y1_))
            if one:
                self._sight_walls.append(seg)
            elif fs in doors or bs in doors:
                self._sight_doors.append((seg, fs, bs))
            elif (min(secs[fs].ceil_h, secs[bs].ceil_h)
                  - max(secs[fs].floor_h, secs[bs].floor_h)) <= 0:
                self._sight_walls.append(seg)      # a statically closed opening
        # -- sound regions --------------------------------------------------------------------------
        parent = list(range(len(secs)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        self._sound_door_edges = []
        for ld in lds:
            if not ld.flags & gd.ML_TWOSIDED or not 0 <= ld.back < len(sds):
                continue
            a, b = sds[ld.front].sector, sds[ld.back].sector
            if a == b:
                continue
            if a in doors or b in doors:
                self._sound_door_edges.append((a, b))
                continue
            if min(secs[a].ceil_h, secs[b].ceil_h) - max(secs[a].floor_h, secs[b].floor_h) > 0:
                parent[find(a)] = find(b)
        roots = sorted({find(s) for s in range(len(secs)) if s not in doors},
                       key=lambda r: min(s for s in range(len(secs)) if find(s) == r))
        node_of_root = {r: k for k, r in enumerate(roots)}
        self.sector_node = [0] * len(secs)
        for s in range(len(secs)):
            if s not in doors:
                self.sector_node[s] = node_of_root[find(s)]
        for k, si in enumerate(self.door_order):
            self.sector_node[si] = len(roots) + k
        self.nsound = len(roots) + len(self.door_order)

    # ---------------------------------------------------------------------------- level start
    def reset(self, skill: int) -> None:
        """Level start for `skill` -- the restart block (NEW GAME). Every persistent cell gets its
        level-start value; monsters of other skills stay in their slots, inactive."""
        assert skill in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD), skill
        self.ws = ws = WorldState(self.schema, strict=self.strict)
        self.tic_count = 0
        self.events: List[TicEvents] = []
        ws.skill = skill
        ws.rng_world = R.stream_seed(R.STREAM_WORLD)
        ws.rng_player = R.stream_seed(R.STREAM_PLAYER)
        ws.rng_fx = R.stream_seed(R.STREAM_FX)
        # player: G_PlayerReborn + P_SetupPsprites (the pistol comes up: S_PISTOLUP, A_Raise once)
        st = spawn_state(self.mw, self.mapname)
        ws.px, ws.py, ws.pangle = st.x, st.y, st.angle
        ws.p_health = gd.INITIAL_HEALTH
        ws.p_ammo[gd.AM_CLIP] = gd.INITIAL_BULLETS
        for w in gd.INITIAL_WEAPONS_OWNED:
            ws.p_owned[w] = 1
        ws.p_ready, ws.p_pending = gd.INITIAL_WEAPON, gd.WP_NOCHANGE
        up = gd.WEAPONINFO[gd.INITIAL_WEAPON].upstate
        ws.p_wpn_state, ws.p_wpn_tics = gd.STATE_INDEX[up], gd.STATES[up].tics
        ws.p_wpn_sy = (gd.WEAPONBOTTOM - gd.RAISESPEED) >> 16
        ws.p_attackdown = ws.p_usedown = 1
        ws.p_mobj_state, ws.p_mobj_tics = gd.STATE_INDEX["S_PLAY"], TICS_FOREVER
        # monsters
        bit = gd.skill_bit(skill)
        for m, t in enumerate(self.mon_things):
            info = self.mon_info[m]
            ws.mon_rng[m] = R.stream_seed(R.STREAM_MONSTER0 + m)
            ws.mon_x[m], ws.mon_y[m] = t.x, t.y
            ws.mon_facing[m] = _c_div(t.angle, 45) & 7        # ANG45 * (angle / 45)
            ws.mon_ambush[m] = 1 if t.flags & gd.MTF_AMBUSH else 0
            ws.mon_state[m] = gd.STATE_INDEX[info.spawnstate]
            ws.mon_health[m] = info.spawnhealth
            ws.mon_reaction[m] = info.reactiontime             # skill != nightmare
            ws.mon_movedir[m] = gd.DI_EAST                     # P_SpawnMobj memsets the mobj
            leaf = self.rm.point_in_subsector(self.cmap, t.x, t.y)
            ws.mon_leaf[m] = leaf
            ws.mon_floorz[m] = self.secs_c[self.leaf_sector[leaf]].floor_h
            if not t.flags & bit:
                ws.mon_active[m] = 0
                ws.mon_tics[m] = TICS_FOREVER
                continue
            ws.mon_active[m] = 1
            ws.mon_solid[m] = 1 if info.flags & gd.MF_SOLID else 0
            ws.mon_shootable[m] = 1 if info.flags & gd.MF_SHOOTABLE else 0
            tics = gd.STATES[info.spawnstate].tics
            if tics > 0:                                       # P_SpawnMapThing's phase roll
                v, ws.mon_rng[m] = R.p_random(ws.mon_rng[m])
                tics = 1 + v % tics
            ws.mon_tics[m] = TICS_FOREVER if tics < 0 else tics
            self._list_insert(m, leaf)
        # barrels (S3b ticks them; their level-start phase uses the world stream, in WAD order)
        for b, t in enumerate(self.barrel_things):
            if not t.flags & bit:
                continue
            ws.bar_state[b] = gd.STATE_INDEX["S_BAR1"]
            ws.bar_health[b] = gd.MOBJINFO["MT_BARREL"].spawnhealth
            ws.bar_solid[b] = 1
            v, ws.rng_world = R.p_random(ws.rng_world)
            ws.bar_tics[b] = 1 + v % gd.STATES["S_BAR1"].tics
        self._pickups_spawned = [bool(t.flags & bit) for t in self.pickup_things]
        self._decor_now = [t for t in self.decor_solid if t.flags & bit]
        self._barrel_spawned = [bool(t.flags & bit) for t in self.barrel_things]
        self._door_phase_scene()

    # ---------------------------------------------------------------------------- the tic
    def tic(self, keys: Optional[dict] = None) -> TicEvents:
        keys = {k: bool((keys or {}).get(k)) for k in KEYS}
        ev = TicEvents(tic=self.tic_count)
        self._doors_phase(keys, ev)
        self._player_phase(keys, ev)
        self._monsters_phase(ev)
        self._projectiles_phase(ev)
        self.ws.leveltime = (self.ws.leveltime + 1) & 0xFFFF
        self.tic_count += 1
        self.events.append(ev)
        return ev

    def run(self, key_script: Sequence[dict]) -> List[TicEvents]:
        return [self.tic(k) for k in key_script]

    # -- 1. doors
    def _doors_phase(self, keys: dict, ev: TicEvents) -> None:
        ws = self.ws
        for d, si in enumerate(self.door_order):
            pressed = keys["use"] and in_use_box_fixed(self.door_boxes[si], ws.px, ws.py)
            st = door_tic((ws.d_state[d], ws.d_dir[d], ws.d_sub[d], ws.d_wait[d]),
                          self.door_nstates[si], bool(pressed or ws.d_monreq[d]))
            ws.d_state[d], ws.d_dir[d], ws.d_sub[d], ws.d_wait[d] = st
            ws.d_monreq[d] = 0
        self._door_phase_scene()

    def _door_phase_scene(self) -> None:
        """This tic's collision scene (doors at their OPEN height, the not-yet-passable doors'
        lines blocked -- m2_std_gate's construction) and the true door heights (sight, sound)."""
        ws = self.ws
        states = {si: ws.d_state[d] for d, si in enumerate(self.door_order)}
        self.blocked_now = frozenset(li for si in self.door_order
                                     if states[si] < self.door_pass[si]
                                     for li in self.door_lines.get(si, ()))
        self.scene_c = Scene(self.mw, self.mw, self.mapname, self.cmap, self.open_h,
                             self.blocked_now)
        self.heights_now = heights_for_states(self.secs, self.lds, self.sds, states)

    # -- 2. the player
    def _player_phase(self, keys: dict, ev: TicEvents) -> None:
        ws = self.ws
        # WEAPON (S3b). Until the weapon state machine lands, `fire` stands in for P_FireWeapon's
        # P_NoiseAlert (player, player) so waking by sound can be driven and tested.
        if keys["fire"]:
            self.noise_alert(ev)
        # MOVE: the oracle's own tic, against this tic's collision scene (m2_std_gate's way)
        st = self.rm.step_sim(SimState(ws.px, ws.py, ws.pangle, self.mapname), keys,
                              scene=self.scene_c)
        ws.px, ws.py, ws.pangle = st.x, st.y, st.angle

    # -- 3. monsters: the K-slot scheduler
    def _monsters_phase(self, ev: TicEvents) -> None:
        """Every active monster, in slot order starting at `sched_cursor`:
          * tics > 0: decrement; still > 0: done for this tic;
          * tics == 0: READY -- enter the next state. If that state's action is HEAVY it needs one
            of `k_heavy` slots; without one the monster keeps tics = 0 and waits.
        The cursor then moves by `cursor_policy` (default: to the first deferred monster)."""
        ws, n = self.ws, self.layout.nmon
        used, first_deferred = 0, None
        start = ws.sched_cursor
        for j in range(n):
            m = (start + j) % n
            if not ws.mon_active[m] or ws.mon_tics[m] == TICS_FOREVER:
                continue
            if ws.mon_tics[m] > 0:
                ws.mon_tics[m] -= 1
                if ws.mon_tics[m] > 0:
                    continue
            nxt = gd.STATES[gd.STATE_NAMES[ws.mon_state[m]]].next
            act = gd.STATES[nxt].action
            if act is not None and gd.ACTIONS[act].cls == "heavy":
                if used >= self.k_heavy:
                    ev.deferred.append(m)
                    if first_deferred is None:
                        first_deferred = m
                    continue
                used += 1
                ev.heavy.append(m)
            self._set_state(m, nxt, True, ev)
        ws.sched_cursor = self.cursor_policy(ws.sched_cursor, first_deferred, n)

    # -- 4. projectiles (S3b)
    def _projectiles_phase(self, ev: TicEvents) -> None:
        """S3b: each active fireball slot moves, tests the player's box and the walls, re-links its
        leaf. Nothing spawns a fireball in S3a (A_TroopAttack's effect is S3b)."""
        assert not any(self.ws.proj_active), "S3a spawns no projectiles"

    # ---------------------------------------------------------------------------- states
    def _set_state(self, m: int, name: str, run_action: bool, ev: TicEvents) -> bool:
        """P_SetMobjState: set, run the action, and keep going while the new tics are 0. The loop
        test reads the tics AFTER the action, which may itself have set another state -- DOOM's
        exact shape."""
        ws = self.ws
        for _guard in range(64):
            if name == gd.S_NULL:
                ws.mon_active[m] = 0                     # P_RemoveMobj; unreachable for monsters
                self._list_remove(m, ws.mon_leaf[m])
                return False
            st = gd.STATES[name]
            ws.mon_state[m] = gd.STATE_INDEX[name]
            ws.mon_tics[m] = TICS_FOREVER if st.tics < 0 else st.tics
            if run_action and st.action is not None:
                self._run_action(m, st.action, ev)
            name = st.next
            if ws.mon_tics[m] != 0:
                return True
        raise AssertionError("state cycle through zero-tic states at slot %d" % m)

    def _run_action(self, m: int, action: str, ev: TicEvents) -> None:
        a = gd.ACTIONS[action]
        if action == "A_Look":
            self._a_look(m, ev)
        elif action == "A_Chase":
            self._a_chase(m, ev)
        elif action == "A_FaceTarget":
            self._a_face_target(m)
        elif action in ("A_PosAttack", "A_SPosAttack", "A_TroopAttack", "A_SargAttack"):
            # every monster attack starts with A_FaceTarget; the effect itself is S3b
            self._a_face_target(m)
            ev.attacks.append((m, action))
        elif action == "A_Fall":
            self.ws.mon_solid[m] = 0
        elif a.phase == "sound":
            pass
        else:
            raise NotImplementedError("%s on a monster (phase %s)" % (action, a.phase))

    # ---------------------------------------------------------------------------- AI
    def player_alive(self) -> bool:
        """MF_SHOOTABLE on the player: alive until S3b's death clears it."""
        return self.ws.p_health > 0 and not self.ws.p_dead

    def _to_player(self, m: int) -> Tuple[int, int]:
        """Target offset in integer map units (the player's position floored)."""
        ws = self.ws
        return (ws.px >> 16) - ws.mon_x[m], (ws.py >> 16) - ws.mon_y[m]

    def _rand(self, m: int) -> int:
        v, self.ws.mon_rng[m] = R.p_random(self.ws.mon_rng[m])
        return v

    def _a_look(self, m: int, ev: TicEvents) -> None:
        """A_Look, in DOOM's order: a heard shot wakes at once (an AMBUSH monster also needs
        sight, and otherwise falls through to the look); else P_LookForPlayers with the facing."""
        ws = self.ws
        ws.mon_threshold[m] = 0
        if self.player_alive() and ws.snd_alert[self.sector_node[self._mon_sector(m)]]:
            ws.mon_target[m] = 1
            if not ws.mon_ambush[m] or self.sight(self, m):
                self._wake(m, "sound", ev)
                return
        if self._look_for_player(m, allaround=False):
            self._wake(m, "sight", ev)

    def _wake(self, m: int, how: str, ev: TicEvents) -> None:
        ev.wakes.append((m, how))
        self._set_state(m, self.mon_info[m].seestate, False, ev)    # D-WAKE: no A_Chase now

    def _look_for_player(self, m: int, allaround: bool) -> bool:
        """P_LookForPlayers for the single player: alive, in sight, and (unless `allaround`) not
        behind the monster -- or behind it but within MELEERANGE."""
        if not self.player_alive() or not self.sight(self, m):
            return False
        if not allaround:
            dx, dy = self._to_player(m)
            if behind(self.ws.mon_facing[m], dx, dy) and aprox_distance(dx, dy) > LOOK_BEHIND_REACH:
                return False
        self.ws.mon_target[m] = 1
        return True

    def _a_face_target(self, m: int) -> None:
        ws = self.ws
        if not ws.mon_target[m]:
            return
        ws.mon_ambush[m] = 0
        ws.mon_facing[m] = octant_of(*self._to_player(m))

    def _a_chase(self, m: int, ev: TicEvents) -> None:
        """A_Chase (p_enemy.c), single player, skill < nightmare."""
        ws, info = self.ws, self.mon_info[m]
        if ws.mon_reaction[m]:
            ws.mon_reaction[m] -= 1
        if ws.mon_threshold[m]:
            if not ws.mon_target[m] or not self.player_alive():
                ws.mon_threshold[m] = 0
            else:
                ws.mon_threshold[m] -= 1
        if ws.mon_movedir[m] < 8:
            ws.mon_facing[m] = turn_toward(ws.mon_facing[m], ws.mon_movedir[m])
        if not ws.mon_target[m] or not self.player_alive():
            if self._look_for_player(m, allaround=True):
                return
            self._set_state(m, info.spawnstate, True, ev)
            return
        if ws.mon_justattacked[m]:
            ws.mon_justattacked[m] = 0
            self._new_chase_dir(m, ev)
            return
        if info.meleestate != gd.S_NULL and self._check_melee_range(m):
            ev.decisions.append((m, "melee"))
            self._set_state(m, info.meleestate, True, ev)
            return
        if info.missilestate != gd.S_NULL and ws.mon_movecount[m] == 0 \
                and self._check_missile_range(m):
            ev.decisions.append((m, "missile"))
            self._set_state(m, info.missilestate, True, ev)
            ws.mon_justattacked[m] = 1
            return
        # `if (--actor->movecount < 0 || !P_Move (actor))`. DOOM's movecount is an int that keeps
        # falling while a monster is stuck; every reader only asks "< 0" or "!= 0", so saturating
        # at -1 is observably identical and fits the 5-bit cell.
        ws.mon_movecount[m] = max(MOVECOUNT_FLOOR, ws.mon_movecount[m] - 1)
        if ws.mon_movecount[m] < 0 or not self._p_move(m, ev):
            self._new_chase_dir(m, ev)

    def _check_melee_range(self, m: int) -> bool:
        if not self.ws.mon_target[m]:
            return False
        if aprox_distance(*self._to_player(m)) >= MELEE_REACH:
            return False
        return self.sight(self, m)

    def _check_missile_range(self, m: int) -> bool:
        ws = self.ws
        if not self.sight(self, m):
            return False
        if ws.mon_justhit[m]:
            ws.mon_justhit[m] = 0
            return True
        if ws.mon_reaction[m]:
            return False
        dist = aprox_distance(*self._to_player(m)) - MISSILE_BIAS
        if self.mon_info[m].meleestate == gd.S_NULL:
            dist -= MISSILE_NOMELEE_BIAS
        dist = min(dist, MISSILE_CAP)
        return not self._rand(m) < dist

    def _new_chase_dir(self, m: int, ev: TicEvents) -> None:
        """P_NewChaseDir with the D5 cap: DOOM's try order, a direction already tried in this call
        skipped (it would fail identically), at most NEWCHASEDIR_MAX_TRIES distinct tries."""
        ws = self.ws
        ev.newchasedir += 1
        olddir = ws.mon_movedir[m]
        turnaround = gd.OPPOSITE[olddir]
        dx, dy = self._to_player(m)
        d1 = (gd.DI_EAST if dx > CHASE_DEADZONE else gd.DI_WEST if dx < -CHASE_DEADZONE
              else gd.DI_NODIR)
        d2 = (gd.DI_SOUTH if dy < -CHASE_DEADZONE else gd.DI_NORTH if dy > CHASE_DEADZONE
              else gd.DI_NODIR)
        tried: List[int] = []

        class _Capped(Exception):
            pass

        def walk(d: int) -> bool:
            if d in tried:
                return False
            if len(tried) >= NEWCHASEDIR_MAX_TRIES:
                raise _Capped
            tried.append(d)
            ws.mon_movedir[m] = d
            return self._try_walk(m, ev)

        try:
            if d1 != gd.DI_NODIR and d2 != gd.DI_NODIR:
                dg = gd.DIAGS[((dy < 0) << 1) + (dx > 0)]
                if dg != turnaround and walk(dg):
                    return
            if self._rand(m) > 200 or abs(dy) > abs(dx):
                d1, d2 = d2, d1
            if d1 == turnaround:
                d1 = gd.DI_NODIR
            if d2 == turnaround:
                d2 = gd.DI_NODIR
            if d1 != gd.DI_NODIR and walk(d1):
                return
            if d2 != gd.DI_NODIR and walk(d2):
                return
            if olddir != gd.DI_NODIR and walk(olddir):
                return
            order = range(gd.DI_EAST, gd.DI_SOUTHEAST + 1) if self._rand(m) & 1 \
                else range(gd.DI_SOUTHEAST, gd.DI_EAST - 1, -1)
            for t in order:
                if t != turnaround and walk(t):
                    return
            if turnaround != gd.DI_NODIR and walk(turnaround):
                return
        except _Capped:
            ev.capped += 1
        ws.mon_movedir[m] = gd.DI_NODIR

    def _try_walk(self, m: int, ev: TicEvents) -> bool:
        if not self._p_move(m, ev):
            return False
        self.ws.mon_movecount[m] = self._rand(m) & 15
        return True

    def _p_move(self, m: int, ev: TicEvents) -> bool:
        """P_Move: one step along movedir through P_TryMove. A failed step inside a monster door's
        use box presses the door instead (D5) -- DOOM's spechit path: movedir = DI_NODIR, and the
        move counts as made."""
        ws = self.ws
        d = ws.mon_movedir[m]
        if d == gd.DI_NODIR:
            return False
        sx, sy = step_delta(self.mon_speed[m], d)
        nx, ny = ws.mon_x[m] + sx, ws.mon_y[m] + sy
        ev.tries += 1
        verdict, floorz = self.try_move_monster(m, nx, ny)
        if verdict != OK:
            ev.blocked[verdict] += 1
            door = self._monster_door(m)
            if door is None:
                return False
            ws.d_monreq[self.door_order.index(door)] = 1
            ws.mon_movedir[m] = gd.DI_NODIR
            ev.door_uses.append((m, door))
            return True
        self._move_monster(m, nx, ny, floorz, ev)
        return True

    def _monster_door(self, m: int) -> Optional[int]:
        """The first door (ascending sector) whose monster use box holds the monster and that a
        monster's press would move: shut and idle, or closing (EV_VerticalDoor ignores a monster
        otherwise)."""
        ws = self.ws
        for d, si in enumerate(self.door_order):
            box = self.mon_door_boxes.get(si)
            if box is None or not in_use_box(box, ws.mon_x[m], ws.mon_y[m]):
                continue
            if ws.d_dir[d] == CLOSING or (ws.d_dir[d] == IDLE and ws.d_state[d] == 0):
                return si
        return None

    # ---------------------------------------------------------------------------- collision
    def try_move_monster(self, m: int, nx: int, ny: int) -> Tuple[str, Optional[int]]:
        """P_TryMove for monster `m` to (nx, ny) in map units: (verdict, new floorz). Things first,
        then lines (P_CheckPosition's order; the verdict does not depend on it), then P_TryMove's
        height, step and drop-off rules."""
        ws = self.ws
        r, h = self.mon_radius[m], self.mon_height[m]
        if self._thing_blocker(m, nx, ny, r) is not None:
            return V_THING, None
        verdict, floorz, ceilz, dropoffz = self.check_lines(nx << 16, ny << 16, r << 16,
                                                            monster=True)
        if verdict != OK:
            return verdict, None
        z = ws.mon_floorz[m]
        if ceilz - floorz < h or ceilz - z < h:
            return V_HEIGHT, None
        if floorz - z > STEP_UP:
            return V_STEP, None
        if not self.mon_info[m].flags & (gd.MF_DROPOFF | gd.MF_FLOAT) \
                and floorz - dropoffz > DROPOFF_MAX:
            return V_DROPOFF, None
        return OK, floorz

    def check_lines(self, x16: int, y16: int, r16: int, *, monster: bool):
        """PIT_CheckLine over EVERY linedef (the oracle's exhaustive loop, so no accelerator stands
        between the model and DOOM's rule): (verdict, floorz, ceilz, dropoffz) in map units. A
        refusal returns the seed heights, as `ReferenceModel.check_position` does.

        On top of the oracle's player test: ML_BLOCKMONSTERS refuses a monster, and the drop-off
        floor (lowfloor) is tracked."""
        leaf = self.rm.point_in_subsector(self.cmap, x16 >> 16, y16 >> 16)
        seed = self.secs_c[self.leaf_sector[leaf]]
        floorz = dropoffz = seed.floor_h
        ceilz = seed.ceil_h
        top, bottom, left, right = y16 + r16, y16 - r16, x16 - r16, x16 + r16
        secs, blocked, box = self.secs_c, self.blocked_now, None
        for (li, minx, maxx, miny, maxy, ax, ay, bx, by, one, flags, fs, bs) in self._lines:
            if right <= minx or left >= maxx or top <= miny or bottom >= maxy:
                continue
            if box is None:
                box = (top, bottom, left, right)
            if self.rm.box_on_line_side(box, ax, ay, bx, by) != -1:
                continue
            if one or flags & gd.ML_BLOCKING or li in blocked:
                return V_WALL, seed.floor_h, seed.ceil_h, seed.floor_h
            if monster and flags & gd.ML_BLOCKMONSTERS:
                return V_MONLINE, seed.floor_h, seed.ceil_h, seed.floor_h
            opentop, openbottom, lowfloor = self.rm.line_opening(secs[fs], secs[bs])
            ceilz = min(ceilz, opentop)
            floorz = max(floorz, openbottom)
            dropoffz = min(dropoffz, lowfloor)
        return OK, floorz, ceilz, dropoffz

    def _thing_blocker(self, m: int, nx: int, ny: int, r: int):
        """PIT_CheckThing for a monster (no missiles, no skull fly): the first SOLID thing whose box
        overlaps -- `abs(dx) < blockdist` on both axes. The player is tested at 16.16."""
        ws = self.ws
        for j in range(self.layout.nmon):
            if j != m and ws.mon_active[j] and ws.mon_solid[j]:
                bd = r + self.mon_radius[j]
                if abs(ws.mon_x[j] - nx) < bd and abs(ws.mon_y[j] - ny) < bd:
                    return ("monster", j)
        bd16 = (r + PLAYER_R) << 16
        if abs(ws.px - (nx << 16)) < bd16 and abs(ws.py - (ny << 16)) < bd16:
            return ("player", -1)
        for b, t in enumerate(self.barrel_things):
            if ws.bar_solid[b]:
                bd = r + gd.THING_TYPES[2035].radius
                if abs(t.x - nx) < bd and abs(t.y - ny) < bd:
                    return ("barrel", b)
        for t in self._decor_now:
            bd = r + gd.THING_TYPES[t.type].radius
            if abs(t.x - nx) < bd and abs(t.y - ny) < bd:
                return ("decor", t.type)
        return None

    def _move_monster(self, m: int, nx: int, ny: int, floorz: int, ev: TicEvents) -> None:
        ws = self.ws
        ws.mon_x[m], ws.mon_y[m], ws.mon_floorz[m] = nx, ny, floorz
        ev.moves.append(m)
        leaf = self.rm.point_in_subsector(self.cmap, nx, ny)
        old = ws.mon_leaf[m]
        if leaf != old:
            self._list_remove(m, old)
            ws.mon_leaf[m] = leaf
            self._list_insert(m, leaf)
            ev.leaf_changes.append((m, old, leaf))

    # ---------------------------------------------------------------------------- leaf lists
    def _list_insert(self, k: int, leaf: int) -> None:
        """Link mobile `k` into `leaf`'s list at its ascending position."""
        ws, enc = self.ws, k + 1
        cur = ws.leaf_head[leaf]
        if cur == 0 or cur > enc:
            ws.mob_next[k] = cur
            ws.leaf_head[leaf] = enc
            return
        while True:
            nxt = ws.mob_next[cur - 1]
            if nxt == 0 or nxt > enc:
                ws.mob_next[k] = nxt
                ws.mob_next[cur - 1] = enc
                return
            cur = nxt

    def _list_remove(self, k: int, leaf: int) -> None:
        ws, enc = self.ws, k + 1
        cur = ws.leaf_head[leaf]
        if cur == enc:
            ws.leaf_head[leaf] = ws.mob_next[k]
            ws.mob_next[k] = 0
            return
        while cur:
            nxt = ws.mob_next[cur - 1]
            if nxt == enc:
                ws.mob_next[cur - 1] = ws.mob_next[k]
                ws.mob_next[k] = 0
                return
            cur = nxt
        raise AssertionError("mobile %d is not in leaf %d's list" % (k, leaf))

    def leaf_lists(self) -> Dict[int, List[int]]:
        """{leaf: [mobile, ...]} read from the linked lists."""
        ws, out = self.ws, {}
        for leaf in range(self.layout.nleaf):
            cur, seq = ws.leaf_head[leaf], []
            while cur:
                seq.append(cur - 1)
                cur = ws.mob_next[cur - 1]
                assert len(seq) <= self.layout.nmobile, "cycle in leaf %d" % leaf
            if seq:
                out[leaf] = seq
        return out

    def leaf_lists_from_scratch(self) -> Dict[int, List[int]]:
        """The same lists rebuilt from positions alone (the invariant the incremental lists keep)."""
        ws, out = self.ws, {}
        for m in range(self.layout.nmon):
            if ws.mon_active[m]:
                leaf = self.rm.point_in_subsector(self.cmap, ws.mon_x[m], ws.mon_y[m])
                out.setdefault(leaf, []).append(m)
        return out

    # ---------------------------------------------------------------------------- sound, sight
    def _mon_sector(self, m: int) -> int:
        return self.leaf_sector[self.ws.mon_leaf[m]]

    def player_sector(self) -> int:
        ws = self.ws
        return self.leaf_sector[self.rm.point_in_subsector(self.cmap, ws.px >> 16, ws.py >> 16)]

    def _sector_hts(self, s: int) -> Tuple[int, int]:
        return self.heights_now.get(s, (self.secs[s].floor_h, self.secs[s].ceil_h))

    def noise_alert(self, ev: Optional[TicEvents] = None) -> None:
        """P_NoiseAlert (player, player): every sound node reachable from the player's sector
        through open door edges hears it. Idempotent."""
        ws = self.ws
        reached = {self.sector_node[self.player_sector()]}
        changed = True
        while changed:
            changed = False
            for a, b in self._sound_door_edges:
                na, nb = self.sector_node[a], self.sector_node[b]
                if (na in reached) == (nb in reached):
                    continue
                (fa, ca), (fb, cb) = self._sector_hts(a), self._sector_hts(b)
                if min(ca, cb) - max(fa, fb) > 0:
                    reached.add(nb if na in reached else na)
                    changed = True
        for k in reached:
            ws.snd_alert[k] = 1
        if ev is not None:
            ev.noise = True

    @staticmethod
    def los_to_player(world: "World", m: int) -> bool:
        """The default sight: the segment between the monster's and the player's centres touches no
        one-sided line, no statically closed two-sided line, and no door line whose opening is
        closed at this tic's door heights. 2D (no eye heights) and exact on 16.16 integers."""
        ws = world.ws
        p = (ws.mon_x[m] << 16, ws.mon_y[m] << 16)
        q = (ws.px, ws.py)
        x0, x1 = min(p[0], q[0]), max(p[0], q[0])
        y0, y1 = min(p[1], q[1]), max(p[1], q[1])
        for a, b, (lx0, lx1, ly0, ly1) in world._sight_walls:
            if lx1 < x0 or lx0 > x1 or ly1 < y0 or ly0 > y1:
                continue
            if segments_touch(p, q, a, b):
                return False
        for (a, b, (lx0, lx1, ly0, ly1)), fs, bs in world._sight_doors:
            if lx1 < x0 or lx0 > x1 or ly1 < y0 or ly0 > y1:
                continue
            (ff, fc), (bf, bc) = world._sector_hts(fs), world._sector_hts(bs)
            if min(fc, bc) - max(ff, bf) > 0:
                continue
            if segments_touch(p, q, a, b):
                return False
        return True

    # ---------------------------------------------------------------------------- views
    def wake_all(self) -> None:
        """Scenario helper: every active monster has seen the player (target set, see state
        entered) -- the all-awake stress state of plan section 9."""
        ws = self.ws
        for m in range(self.layout.nmon):
            if ws.mon_active[m] and ws.mon_tics[m] != TICS_FOREVER:
                ws.mon_target[m] = 1
                self._set_state(m, self.mon_info[m].seestate, False, TicEvents(self.tic_count))

    def digest(self) -> str:
        return self.ws.digest()

    def monster_view(self, m: int) -> dict:
        ws = self.ws
        return {"slot": m, "type": self.mon_things[m].type, "active": ws.mon_active[m],
                "state": gd.STATE_NAMES[ws.mon_state[m]], "tics": ws.mon_tics[m],
                "x": ws.mon_x[m], "y": ws.mon_y[m], "floorz": ws.mon_floorz[m],
                "movedir": ws.mon_movedir[m], "facing": ws.mon_facing[m],
                "movecount": ws.mon_movecount[m], "reaction": ws.mon_reaction[m],
                "target": ws.mon_target[m], "leaf": ws.mon_leaf[m]}
