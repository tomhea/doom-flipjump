"""S3b -- combat and game state for the gameplay model: weapons, hitscan, monster attacks, the
fireball and effect pools, damage and death, pickups, barrels, the player blocked by things, player
death and restart, the exit switch and nukage (docs/plan-gameplay.md sections 2, 5, 6.4, 6.7, 11).

`World` (doomfj.world) inherits `CombatMixin`: world.py keeps the schema, the tic's order and the
monster AI; this file keeps the combat rules. Every rule is DOOM's, from Chocolate Doom at the
commit `gamedata.SOURCE_COMMIT` (p_pspr.c, p_inter.c, p_map.c, p_mobj.c, p_enemy.c, p_user.c,
p_spec.c -- fetched raw with curl for S3b), except where a line below says otherwise.

THE APPROVED SIMPLIFICATIONS (owner, D5) this file implements:
  * NO INFIGHTING. Monster bullets and fireballs pass through monsters and barrels; only the player
    shoots monsters and barrels. So every damage source is the player (directly or through a
    barrel he set off), a monster attacking the player, or a nukage floor; a monster's target is
    always the player.
  * NO KNOCKBACK. P_DamageMobj's thrust block is skipped -- with it its one conditional
    `P_Random()&1` (damage < 40, damage > health, inflictor 64+ units below the target).
  * 2D PROJECTILES. A fireball has no z: it flies level, is stopped by one-sided lines and by
    two-sided lines whose opening is under its 8-unit height (a shut door), and ignores steps,
    ceilings and the sky hack. It hits the player's box and passes through every other thing
    (monsters and barrels by the rule above; solid decor because DOOM's 16-high decor sits under a
    fireball flying 32 up).
  * THE FIREBALL POOL has `world.FIREBALL_POOL` slots; when full the imp's missile attack FIZZLES
    (no spawn, no draw). PUFFS AND BLOOD share `world.FX_POOL` slots; when full the effect is
    skipped (no draw).
  * NO WEAPON RAISE/LOWER ANIMATION, but the timing stays: `p_wpn_sy` still steps 6 units a tic,
    so a switch takes DOOM's tics. No bob, so a ready weapon sits at WEAPONTOP.
  * No sound (A_Pain, A_Scream, ...), no extralight (A_Light0/1/2 do nothing), no status face.

MODEL CONVENTIONS, named so an fj mirror can copy them:
  * THE AIM IS A CALLBACK, `aim(world, col) -> None | ("mon", slot) | ("bar", index)`: the
    shootable living target a shot through screen column `col` hits. The plan's aim is the PICTURE
    (section 6.4: the 17-column window the renderer writes while drawing, wired in S5). The
    default here, `aim_geometric`, is the nearest target whose box, projected like a sprite from
    the tic-start view, covers `col`, within MISSILERANGE, that 2D line of sight reaches. Both
    resolve a pellet by its COLUMN: DOOM's spread `P_SubRandom() << 18` maps to a column through
    the renderer's own viewangletox, and all of them land in the window (72..88 at 160 wide).
  * The weapon acts BEFORE the player moves (plan section 2): it aims from the tic-start view, the
    picture the player saw. (DOOM turns and thrusts first and moves the mobj after the weapon.)
  * Melee (fist 64, chainsaw 65 units): the same pick, then P_AproxDistance to the target's centre
    must not exceed the reach (DOOM's trace crosses a thing's diagonal at its centre).
  * Blood and puffs sit 10 units in front of the target, stepped along the octant toward the
    player (DOOM: 10 units back along the trace). A shot that hits nothing makes no wall puff (the
    picture aim knows no wall point); monster shots and hits on the player make none (not seen).
  * MONSTER HITSCAN: `sight`, P_AproxDistance under 2048, and |spread| <= HWT[distance >> 4] -- the
    widest spread whose ray still passes within HIT_HALF_WIDTH of the player's centre, tabled from
    the repo's sine table (20 = DOOM's 16-unit box as its trace sees it on average, 16 * 4/pi).
  * FIREBALL DIRECTION: R_PointToAngle2 (the renderer's own kernel, `ReferenceModel.point_to_angle`)
    and a momentum TABLE by fine angle -- the one angle computation in combat, once per spawn, and
    no runtime multiply (plan section 4 rule 3).
  * PICKUPS happen at every position P_TryMove tries (DOOM's P_CheckPosition touches specials before
    it tests lines, so a refused move can still pick up). At one position the specials are touched
    first -- map things in order, then drops by monster slot -- and only then may a solid thing
    refuse the position (DOOM's blockmap walks the newest thing first, so a fresh drop is taken
    before its still-solid corpse blocks). The player's z for the reach test is his floor.
  * RNG: one stream per consumer (rng.py). The player's weapons, pain and death roll on the player
    stream; a monster's attacks, pain and death on its own; barrels on the world stream; effects and
    fireball impacts and tics on the effects stream. Every call site is an outcome table (D10):
    `rng.outcome_table` for one draw, `outcome_table_k` for k draws in one lookup. The puff/blood z
    jitter (2D) and sound-choosing draws are not made.
  * Saturation: `p_refire` and `p_bonuscount` stop at 255, `p_strength` at 0xFFFF, a barrel's health
    at -128 (DOOM's are unbounded ints; every reader only asks zero/non-zero, <= 0, or caps lower).
  * Phases after the monsters: projectiles, then barrels, then effects (DOOM interleaves thinkers by
    spawn order). Barrel explosions do not take a K slot.
  * Level done FREEZES the world. A restart (use while dead, or `new_game`) is applied at the START
    of the next tic -- the fj frame tail runs the restart block after the frame that asked for it.
  * The player's thing states (S_PLAY_*) are kept DOOM-shaped though first person never shows them;
    his pain/see target switch and reactiontime are not (nothing reads them).
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.fixedpoint import _signed, fixed_mul
from doomfj.reference_model import ANGLE_TURN, FORWARD_MOVE

# 16.16 side step per tic: DOOM's running sidemove/forwardmove (40/50) of the 16-unit
# FORWARD_MOVE, rounded (plan section 2, input). world.py re-exports it.
STRAFE_MOVE = 13 << 16

# the aim box's width is looked up on the view angle's top bits (aim_radius; gp-aim-window 1.7)
AIM_REFF_BITS = 8

M32 = 0xFFFFFFFF


def _W():
    """doomfj.world, imported at call time (world imports this module while it loads)."""
    from doomfj import world
    return world


# ================================================================================================
# RULES (combat). One definition each; the emitter is meant to read them too.
# ================================================================================================
MISSILERANGE_U = gd.MISSILERANGE >> 16      # 2048: bullets, monster hitscan
PUNCH_REACH = gd.MELEERANGE >> 16           # 64: A_Punch's MELEERANGE
SAW_REACH = PUNCH_REACH + 1                 # 65: A_Saw's MELEERANGE+1
HIT_HALF_WIDTH = 20                         # monster hitscan: the player's effective half-width
HWT_SHIFT = 4                               # ... tabled per 16 units of distance
HWT_SIZE = MISSILERANGE_U >> HWT_SHIFT      # 128 buckets cover 0..2047
FX_OFFSET = 10                              # blood/puff distance in front of the target
FX_STEP = ((10, 0), (7, 7), (0, 10), (-7, 7), (-10, 0), (-7, -7), (0, -10), (7, -7))  # by octant
FIREBALL_INFO = gd.MOBJINFO["MT_TROOPSHOT"]
FIREBALL_R = FIREBALL_INFO.radius >> 16     # 6
FIREBALL_H = FIREBALL_INFO.height >> 16     # 8
BARREL_INFO = gd.MOBJINFO["MT_BARREL"]
BARREL_R = BARREL_INFO.radius >> 16         # 10
BARREL_HEALTH_MIN = -128                    # bar_health saturates here (an 8-bit signed cell)
BOMB_DAMAGE = 128                           # A_Explode: P_RadiusAttack (thing, target, 128)
PLAYER_INFO = gd.MOBJINFO["MT_PLAYER"]
PLAYER_R = gd.PLAYERRADIUS >> 16            # 16
ITEM_RADIUS = 20                            # every E1M1 pickup, and both drops
REACH_UP, REACH_DOWN = PLAYER_INFO.height >> 16, 8   # P_TouchSpecialThing's delta window
MAX_HEALTH_BONUS = 200                      # deh_max_health: health bonus cap
MAX_ARMOR_BONUS = 200                       # deh_max_armor: armor bonus cap
SECTOR_HURT = {5: 10, 7: 5, 16: 20, 4: 20}  # P_PlayerInSpecialSector: damage every 32 tics
HURT_PERIOD_MASK = 0x1F
EXIT_SPECIALS = frozenset({11})             # S1 exit (E1M1: linedef 407)
KEY_DOOR_CARDS = {26: (gd.IT_BLUECARD, gd.IT_BLUESKULL), 32: (gd.IT_BLUECARD, gd.IT_BLUESKULL),
                  27: (gd.IT_YELLOWCARD, gd.IT_YELLOWSKULL),
                  34: (gd.IT_YELLOWCARD, gd.IT_YELLOWSKULL),
                  28: (gd.IT_REDCARD, gd.IT_REDSKULL), 33: (gd.IT_REDCARD, gd.IT_REDSKULL)}
WEAPON_KEYS = ("w1", "w2", "w3", "w4")      # DOOM's number keys 1..4 -> WP_FIST..WP_CHAINGUN
# The restart block (plan 6.7) writes every schema field back to its level-start value EXCEPT
# these: the skill (the menu's choice, and the block's input -- it picks WHICH level start), the
# menu mode and the held-key flags are input state, not level state.
RESTART_KEEP = ("skill", "mode", "kb_f", "kb_b", "kb_l", "kb_r", "kb_u")
SUBRANDOM_MAX = 255                         # |P_SubRandom()| <= 255
DROP_ITEM = {"MT_CLIP": 2007, "MT_SHOTGUN": 2001}   # the dropped thing's editor number
RUN_STATES = ("S_PLAY_RUN1", "S_PLAY_RUN2", "S_PLAY_RUN3", "S_PLAY_RUN4")
# P_TouchSpecialThing's cases for every gettable thing E1M1 holds (sprite name in the comment)
GETTABLE = frozenset({2018, 2019, 2014, 2015, 5, 2011, 2012, 2023, 2007, 2048, 2010, 2046, 2047,
                      17, 2008, 2049, 8, 2005, 2001})


# ================================================================================================
# RNG call sites -- k draws folded into ONE lookup (D10)
# ================================================================================================
def _check_index_generator() -> None:
    """`outcome_table_k` indexes by the stream state, sound only while the generator's state is
    DOOM's table index (post-state = pre-state + 1). A new generator must replace the composition."""
    for s in range(1 << R.STATE_BITS):
        assert R.p_random(s)[1] == (s + 1) & R.STATE_MASK, (
            "rng's state is no longer an index; outcome_table_k needs a new composition")


_check_index_generator()


def outcome_table_k(f: Callable, k: int) -> List:
    """The k-draw composition: slot n holds f(v1, ..., vk), the k values P_Random returns starting
    from stream state n - 1 -- indexed, like `rng.outcome_table`, by the POST-increment state of the
    FIRST draw. k = 1 is exactly `rng.outcome_table` (tested)."""
    size = 1 << R.STATE_BITS
    table: List = [None] * size
    for s in range(size):
        vals, st = [], s
        for _ in range(k):
            v, st = R.p_random(st)
            vals.append(v)
        table[(s + 1) & R.STATE_MASK] = f(*vals)
    return table


def p_random_outcome_k(state: int, table: Sequence, k: int):
    """One k-draw call site: (outcome, next state) -- one lookup plus a +k on the state."""
    return table[(state + 1) & R.STATE_MASK], (state + k) & R.STATE_MASK


class Sites:
    """Every RNG call site of the combat rules, as (draws, outcome table), with the DOOM formula
    each one bakes. `col(s)` maps a spread s (P_SubRandom() << 18) to its screen column through the
    renderer's viewangletox."""

    def __init__(self, rm):
        def col(s: int) -> int:
            return rm.angle_to_x((s << 18) & M32)
        self.col = col
        one = R.outcome_table
        # P_GunShot: damage = 5*(P_Random()%3+1); if (!accurate) angle += P_SubRandom() << 18
        self.pistol_acc = (1, one(lambda v: 5 * (v % 3 + 1)))
        self.gunshot = (3, outcome_table_k(lambda a, b, c: (5 * (a % 3 + 1), col(b - c)), 3))
        # A_Punch: damage = (P_Random()%10+1)<<1; angle += P_SubRandom() << 18
        self.punch = (3, outcome_table_k(lambda a, b, c: ((a % 10 + 1) << 1, col(b - c)), 3))
        # A_Saw: damage = 2*(P_Random()%10+1); angle += P_SubRandom() << 18
        self.saw = (3, outcome_table_k(lambda a, b, c: (2 * (a % 10 + 1), col(b - c)), 3))
        # A_PosAttack / A_SPosAttack, per bullet: angle += P_SubRandom() << 20;
        # damage = ((P_Random()%5)+1)*3 -- the outcome is (spread, damage)
        self.mon_bullet = (3, outcome_table_k(lambda a, b, c: (a - b, (c % 5 + 1) * 3), 3))
        # A_TroopAttack's claw: damage = (P_Random()%8+1)*3
        self.troop_claw = (1, one(lambda v: (v % 8 + 1) * 3))
        # A_SargAttack: damage = ((P_Random()%10)+1)*4
        self.sarg_bite = (1, one(lambda v: (v % 10 + 1) * 4))
        # PIT_CheckThing, a missile hitting: damage = ((P_Random()%8)+1)*tmthing->info->damage
        self.fireball_hit = (1, one(lambda v: (v % 8 + 1) * FIREBALL_INFO.damage))
        # `tics -= P_Random()&3`: P_KillMobj, P_ExplodeMissile, P_CheckMissileSpawn, puff, blood
        self.tics_roll = (1, one(lambda v: v & 3))
        # P_DamageMobj: P_Random () < target->info->painchance -- one table per painchance value
        self.pain: Dict[int, Tuple[int, List]] = {}
        for info in gd.MOBJINFO.values():
            pc = info.painchance
            if pc not in self.pain:
                self.pain[pc] = (1, one(lambda v, pc=pc: int(v < pc)))

    def all_sites(self) -> Dict[str, Tuple[int, List]]:
        """name -> (draws, table): what the emitter bakes, one D4 dispatch table each."""
        out = {k: v for k, v in sorted(vars(self).items()) if isinstance(v, tuple)}
        out.update({"pain_%d" % pc: t for pc, t in sorted(self.pain.items())})
        return out


# The DOOM formula of every site, evaluated the slow way (successive P_Random calls) -- the reference
# the tests hold the tables to.
def site_formulas(col: Callable[[int], int]) -> Dict[str, Tuple[int, Callable]]:
    pains = {"pain_%d" % pc: (1, (lambda v, pc=pc: int(v < pc)))
             for pc in sorted({i.painchance for i in gd.MOBJINFO.values()})}
    return {
        "pistol_acc": (1, lambda v: 5 * (v % 3 + 1)),
        "gunshot": (3, lambda a, b, c: (5 * (a % 3 + 1), col(b - c))),
        "punch": (3, lambda a, b, c: ((a % 10 + 1) << 1, col(b - c))),
        "saw": (3, lambda a, b, c: (2 * (a % 10 + 1), col(b - c))),
        "mon_bullet": (3, lambda a, b, c: (a - b, (c % 5 + 1) * 3)),
        "troop_claw": (1, lambda v: (v % 8 + 1) * 3),
        "sarg_bite": (1, lambda v: (v % 10 + 1) * 4),
        "fireball_hit": (1, lambda v: (v % 8 + 1) * 3),
        "tics_roll": (1, lambda v: v & 3),
        **pains,
    }


def half_width_table(sine: Sequence[int], half_width: int = HIT_HALF_WIDTH) -> List[int]:
    """HWT[q]: the widest |spread| (one unit = 2^20 BAM = one entry of the 4096-entry sine table)
    whose ray still passes within `half_width` of a target at distance 16q + 8 -- the largest s in
    0..255 with sin(s) * d <= half_width. Integer compares on the repo's sine table only."""
    out = []
    for q in range(HWT_SIZE):
        d = max((q << HWT_SHIFT) + (1 << (HWT_SHIFT - 1)), half_width + 1)
        s = 0
        while s < SUBRANDOM_MAX and _signed(sine[s + 1], 32) * d <= (half_width << 16):
            s += 1
        out.append(s)
    return out


def fireball_momentum_table(rm) -> List[Tuple[int, int]]:
    """(momx, momy) by fine angle index: FixedMul(speed, finecosine/finesine) at emit time, so a
    spawn needs no runtime multiply. The same fixed_mul and trig table as the player's move."""
    speed = FIREBALL_INFO.speed
    return [(_signed(fixed_mul(speed, rm._finecos_idx(i), 8, 4), 32),
             _signed(fixed_mul(speed, rm._finesin_idx(i), 8, 4), 32))
            for i in range(rm.cfg.TRIG_N)]


# ================================================================================================
# THE MIXIN
# ================================================================================================
class CombatMixin:
    """The combat half of `World`. Uses the S3a attributes (`ws`, `rm`, `cmap`, `_lines`, `layout`,
    `sight`, the leaf-list and state methods) and adds the S3b rules."""

    # -------------------------------------------------------------------------------- setup
    def _combat_init(self, aim=None, player_blocking: bool = True) -> None:
        W = _W()
        rm = self.rm
        self.aim = aim or type(self).aim_geometric
        self.player_blocking = player_blocking
        self.sites = Sites(rm)
        self.aim_centre = rm.angle_to_x(0)
        self.aim_lo = self.sites.col(SUBRANDOM_MAX)
        self.aim_hi = self.sites.col(-SUBRANDOM_MAX)
        assert self.aim_lo < self.aim_centre < self.aim_hi
        self.hwt = half_width_table(rm.sine)
        self.fireball_mom = fireball_momentum_table(rm)
        self.restart_fields = tuple(f.name for f in self.schema if f.name not in RESTART_KEEP)
        assert set(RESTART_KEEP) <= {f.name for f in self.schema}
        self._level_starts: Dict[int, object] = {}
        self.pickup_z = [self._floor_at(t.x, t.y) for t in self.pickup_things]
        assert {t.type for t in self.pickup_things} <= GETTABLE
        self.dropper = [DROP_ITEM.get(gd.DROPS.get(gd.MONSTER_DOOMEDNUMS[t.type]))
                        for t in self.mon_things]
        # the exit switch: the door-style proximity box around each exit line (plan 6.7)
        V = self.cmap.vertexes
        self.exit_boxes = []
        for ld in self.lds:
            if ld.special in EXIT_SPECIALS:
                xs, ys = [V[ld.v1][0], V[ld.v2][0]], [V[ld.v1][1], V[ld.v2][1]]
                self.exit_boxes.append((min(xs) - W.USE_RANGE, min(ys) - W.USE_RANGE,
                                        max(xs) + W.USE_RANGE, max(ys) + W.USE_RANGE))
        # key doors: the cards that open each door sector (EV_VerticalDoor)
        self.door_cards: Dict[int, Tuple[int, int]] = {}
        for ld in self.lds:
            if ld.special in KEY_DOOR_CARDS and 0 <= ld.back < len(self.sds):
                si = self.sds[ld.back].sector
                if si in self.door_order:
                    self.door_cards[si] = KEY_DOOR_CARDS[ld.special]
        self.decor_radius = {t.type: gd.THING_TYPES[t.type].radius for t in self.decor_solid}

    def _floor_at(self, x: int, y: int) -> int:
        """The floor a thing at map units (x, y) spawns on (ONFLOORZ: its subsector's sector)."""
        leaf = self.rm.point_in_subsector(self.cmap, x, y)
        return self.secs_c[self.leaf_sector[leaf]].floor_h

    # -------------------------------------------------------------------------------- RNG
    def _roll(self, stream: str, site, idx: Optional[int] = None):
        """One call site on a stream: `stream` names a scalar RNG field, or an array one with `idx`."""
        k, table = site
        ws = self.ws
        state = getattr(ws, stream) if idx is None else getattr(ws, stream)[idx]
        if k == 1:
            out, state = R.p_random_outcome(state, table)
        else:
            out, state = p_random_outcome_k(state, table, k)
        if idx is None:
            setattr(ws, stream, state)
        else:
            getattr(ws, stream)[idx] = state
        return out

    # -------------------------------------------------------------------------------- restart
    def level_start(self, skill: int):
        """The level-start WorldState for `skill` (built once, cached): what the restart writes."""
        if skill not in self._level_starts:
            keep = (self.ws, self.tic_count, self.events, self._decor_now)
            self._reset_state(skill)
            self._level_starts[skill] = self.ws.copy()
            self.ws, self.tic_count, self.events, self._decor_now = keep
        return self._level_starts[skill]

    def new_game(self, skill: Optional[int] = None) -> None:
        """The menu's NEW GAME (or a restart request from a driver): the restart block runs at the
        start of the next tic, for `skill` when given."""
        if skill is not None:
            assert skill in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD), skill
            self.ws.skill = skill
        self.ws.g_restart = 1

    def _restart(self, ev) -> None:
        """THE RESTART BLOCK: every field of `restart_fields` back to its level-start value for the
        current skill, one field at a time -- as the fj block writes each persisted cell from the
        pristine image. The skill, the menu mode and the held keys (RESTART_KEEP) are left alone."""
        ws = self.ws
        snap = self.level_start(ws.skill)
        for name in self.restart_fields:
            fld = ws._fields[name]
            if fld.count == 1:
                setattr(ws, name, getattr(snap, name))
            else:
                dst, src = getattr(ws, name), getattr(snap, name)
                for i in range(fld.count):
                    dst[i] = src[i]
        self._decor_now = self._decor_for(ws.skill)
        self._door_phase_scene()
        ev.restarts += 1

    # -------------------------------------------------------------------------------- the player
    def _player_phase(self, keys: dict, ev) -> None:
        """P_PlayerThink for the single player, in the plan's order (the weapon before the move)."""
        ws = self.ws
        if ws.p_dead:
            self._death_think(keys, ev)
            self._player_mobj_tick()
            return
        self._special_sector(ev)                 # at the tic-start position, as in DOOM
        moving = keys["forward"] != keys["back"] or keys["strafe_left"] != keys["strafe_right"]
        if moving and ws.p_mobj_state == gd.STATE_INDEX["S_PLAY"]:
            self._set_player_mobj("S_PLAY_RUN1")                      # P_MovePlayer
        self._weapon_keys(keys)
        if keys["use"]:
            if not ws.p_usedown:
                ws.p_usedown = 1
                self._use_lines(ev)
        else:
            ws.p_usedown = 0
        self._move_psprites(keys, ev)
        if ws.p_strength:
            ws.p_strength = min(ws.p_strength + 1, 0xFFFF)
        if ws.p_damagecount:
            ws.p_damagecount -= 1
        if ws.p_bonuscount:
            ws.p_bonuscount -= 1
        self._player_move(keys, ev)
        if not moving and gd.STATE_NAMES[ws.p_mobj_state] in RUN_STATES:
            self._set_player_mobj("S_PLAY")      # P_XYMovement: stopped in a walking frame
        self._player_mobj_tick()

    def _death_think(self, keys: dict, ev) -> None:
        """P_DeathThink without the view drop or the turn to the killer: the weapon keeps lowering,
        the damage flash fades, and use (held, as DOOM reads it) asks for the restart."""
        ws = self.ws
        self._move_psprites(keys, ev)
        if ws.p_damagecount:
            ws.p_damagecount -= 1
        if keys["use"]:
            ws.g_restart = 1
            ev.restart_requests += 1

    def _special_sector(self, ev) -> None:
        """P_PlayerInSpecialSector's damaging floors, only when standing ON the sector's floor."""
        ws = self.ws
        sec = self.player_sector()
        dmg = SECTOR_HURT.get(self.secs[sec].special)
        if dmg is None or ws.leveltime & HURT_PERIOD_MASK:
            return
        _ok, floorz, _c = self.rm.check_position(self.scene_c, ws.px, ws.py)
        if floorz != self.secs_c[sec].floor_h:
            return                               # "Falling, not all the way down yet?"
        ev.nukage += 1
        self.damage_player(dmg, ("sector", sec), ev)

    def _weapon_keys(self, keys: dict) -> None:
        """P_PlayerThink's BT_CHANGE: the lowest held number key names the weapon."""
        ws = self.ws
        new = next((i for i, k in enumerate(WEAPON_KEYS) if keys.get(k)), None)
        if new is None:
            return
        if new == gd.WP_FIST and ws.p_owned[gd.WP_CHAINSAW] \
                and not (ws.p_ready == gd.WP_CHAINSAW and ws.p_strength):
            new = gd.WP_CHAINSAW
        if ws.p_owned[new] and new != ws.p_ready:
            ws.p_pending = new

    def _use_lines(self, ev) -> None:
        """P_UseLines for the switches (the doors keep their own use-box phase): the exit."""
        W = _W()
        ws = self.ws
        for box in self.exit_boxes:
            if W.in_use_box_fixed(box, ws.px, ws.py):
                ws.g_leveldone = 1
                ev.level_done = True
                return

    def player_can_open(self, si: int) -> bool:
        """EV_VerticalDoor's key check: a key door needs its card or skull; other doors nothing."""
        cards = self.door_cards.get(si)
        return cards is None or any(self.ws.p_cards[c] for c in cards)

    # -- the player thing's own state (first person never shows it; kept DOOM-shaped)
    def _set_player_mobj(self, name: str) -> None:
        ws, W = self.ws, _W()
        for _guard in range(16):
            st = gd.STATES[name]
            ws.p_mobj_state = gd.STATE_INDEX[name]
            ws.p_mobj_tics = W.TICS_FOREVER if st.tics < 0 else st.tics
            if st.tics != 0:
                return
            name = st.next
        raise AssertionError("player state cycle")

    def _player_mobj_tick(self) -> None:
        ws, W = self.ws, _W()
        if ws.p_mobj_tics == W.TICS_FOREVER:
            return
        ws.p_mobj_tics -= 1
        if ws.p_mobj_tics == 0:
            self._set_player_mobj(gd.STATES[gd.STATE_NAMES[ws.p_mobj_state]].next)

    # -------------------------------------------------------------------------------- psprites
    @staticmethod
    def _psp_fields(which: str) -> Tuple[str, str]:
        return (("p_wpn_state", "p_wpn_tics") if which == "wpn"
                else ("p_flash_state", "p_flash_tics"))

    def _move_psprites(self, keys: dict, ev) -> None:
        """P_MovePsprites: the weapon, then the flash (a flash the weapon set this tic already
        counts down this tic, as in DOOM)."""
        ws, W = self.ws, _W()
        for which in ("wpn", "flash"):
            sf, tf = self._psp_fields(which)
            if getattr(ws, sf) == 0:
                continue                         # S_NULL: not active
            tics = getattr(ws, tf)
            if tics == W.TICS_FOREVER:
                continue
            setattr(ws, tf, tics - 1)
            if tics - 1 == 0:
                self._set_psprite(which, gd.STATES[gd.STATE_NAMES[getattr(ws, sf)]].next, keys, ev)

    def _set_psprite(self, which: str, name: str, keys: dict, ev) -> None:
        """P_SetPsprite, DOOM's loop: set the state and its tics, run the action (which may set the
        psprite again), then follow the CURRENT state's next while its tics are 0."""
        ws, W = self.ws, _W()
        sf, tf = self._psp_fields(which)
        for _guard in range(64):
            if name == gd.S_NULL:
                setattr(ws, sf, 0)
                setattr(ws, tf, 0)
                return
            st = gd.STATES[name]
            setattr(ws, sf, gd.STATE_INDEX[name])
            setattr(ws, tf, W.TICS_FOREVER if st.tics < 0 else st.tics)
            if st.action is not None:
                self._psp_action(st.action, keys, ev)
                if getattr(ws, sf) == 0:
                    return
            name = gd.STATES[gd.STATE_NAMES[getattr(ws, sf)]].next
            if getattr(ws, tf) != 0:
                return
        raise AssertionError("psprite state cycle")

    def _psp_action(self, action: str, keys: dict, ev) -> None:
        if action == "A_WeaponReady":
            self._a_weapon_ready(keys, ev)
        elif action == "A_Lower":
            self._a_lower(keys, ev)
        elif action == "A_Raise":
            self._a_raise(keys, ev)
        elif action == "A_ReFire":
            self._a_refire(keys, ev)
        elif action == "A_FirePistol":
            self._a_fire_bullets("pistol", 1, keys, ev)
        elif action == "A_FireShotgun":
            self._a_fire_bullets("shotgun", 7, keys, ev)
        elif action == "A_Punch":
            self._a_melee("fist", ev)
        elif action == "A_Saw":
            self._a_melee("chainsaw", ev)
        elif action in ("A_Light0", "A_Light1", "A_Light2"):
            pass                                 # extralight: dropped (plan section 2, C)
        else:
            raise NotImplementedError("%s on a psprite" % action)

    def _a_weapon_ready(self, keys: dict, ev) -> None:
        ws = self.ws
        if gd.STATE_NAMES[ws.p_mobj_state] in ("S_PLAY_ATK1", "S_PLAY_ATK2"):
            self._set_player_mobj("S_PLAY")      # "get out of attack state"
        if ws.p_pending != gd.WP_NOCHANGE or ws.p_health <= 0:
            self._set_psprite("wpn", gd.WEAPONINFO[ws.p_ready].downstate, keys, ev)
            return
        if keys["fire"]:
            # "the missile launcher and bfg do not auto fire" -- neither is in E1M1
            if not ws.p_attackdown or ws.p_ready not in (gd.WP_MISSILE, gd.WP_BFG):
                ws.p_attackdown = 1
                self._fire_weapon(keys, ev)
                return
        else:
            ws.p_attackdown = 0
        ws.p_wpn_sy = gd.WEAPONTOP >> 16         # no bob (plan section 2, C)

    def _a_lower(self, keys: dict, ev) -> None:
        ws = self.ws
        ws.p_wpn_sy = ws.p_wpn_sy + (gd.LOWERSPEED >> 16)
        if ws.p_wpn_sy < gd.WEAPONBOTTOM >> 16:
            return
        if ws.p_dead:
            ws.p_wpn_sy = gd.WEAPONBOTTOM >> 16  # don't bring the weapon back up
            return
        if ws.p_health <= 0:
            self._set_psprite("wpn", gd.S_NULL, keys, ev)
            return
        ws.p_ready = ws.p_pending
        self._bring_up_weapon(keys, ev)

    def _bring_up_weapon(self, keys: dict, ev) -> None:
        ws = self.ws
        if ws.p_pending == gd.WP_NOCHANGE:
            ws.p_pending = ws.p_ready
        new = gd.WEAPONINFO[ws.p_pending].upstate
        ws.p_pending = gd.WP_NOCHANGE
        ws.p_wpn_sy = gd.WEAPONBOTTOM >> 16
        self._set_psprite("wpn", new, keys, ev)

    def _a_raise(self, keys: dict, ev) -> None:
        ws = self.ws
        ws.p_wpn_sy = ws.p_wpn_sy - (gd.RAISESPEED >> 16)
        if ws.p_wpn_sy > gd.WEAPONTOP >> 16:
            return
        ws.p_wpn_sy = gd.WEAPONTOP >> 16
        self._set_psprite("wpn", gd.WEAPONINFO[ws.p_ready].readystate, keys, ev)

    def _a_refire(self, keys: dict, ev) -> None:
        ws = self.ws
        if keys["fire"] and ws.p_pending == gd.WP_NOCHANGE and ws.p_health > 0:
            ws.p_refire = min(ws.p_refire + 1, 255)
            self._fire_weapon(keys, ev)
        else:
            ws.p_refire = 0
            self._check_ammo(keys, ev)

    def _check_ammo(self, keys: dict, ev) -> bool:
        """P_CheckAmmo: enough for one shot, or pick the next weapon in DOOM's preference order and
        start lowering. (The plasma, chaingun, launcher and BFG arms are DOOM's; E1M1's single
        player can own none of them. The super shotgun's needs a Doom 2 IWAD.)"""
        ws = self.ws
        ammo = gd.WEAPONINFO[ws.p_ready].ammo
        if ammo == gd.AM_NOAMMO or ws.p_ammo[ammo] >= 1:
            return True
        o, a = ws.p_owned, ws.p_ammo
        if o[gd.WP_PLASMA] and a[gd.AM_CELL]:
            ws.p_pending = gd.WP_PLASMA
        elif o[gd.WP_CHAINGUN] and a[gd.AM_CLIP]:
            ws.p_pending = gd.WP_CHAINGUN
        elif o[gd.WP_SHOTGUN] and a[gd.AM_SHELL]:
            ws.p_pending = gd.WP_SHOTGUN
        elif a[gd.AM_CLIP]:
            ws.p_pending = gd.WP_PISTOL
        elif o[gd.WP_CHAINSAW]:
            ws.p_pending = gd.WP_CHAINSAW
        elif o[gd.WP_MISSILE] and a[gd.AM_MISL]:
            ws.p_pending = gd.WP_MISSILE
        elif o[gd.WP_BFG] and a[gd.AM_CELL] > 40:
            ws.p_pending = gd.WP_BFG
        else:
            ws.p_pending = gd.WP_FIST
        assert ws.p_pending in gd.WEAPONINFO, "E1M1 cannot own weapon %d" % ws.p_pending
        self._set_psprite("wpn", gd.WEAPONINFO[ws.p_ready].downstate, keys, ev)
        return False

    def _fire_weapon(self, keys: dict, ev) -> None:
        """P_FireWeapon: the ammo check, the attack state, and the shot's NOISE (P_NoiseAlert)."""
        ws = self.ws
        if not self._check_ammo(keys, ev):
            return
        self._set_player_mobj("S_PLAY_ATK1")
        ev.fired.append(gd.WEAPONINFO[ws.p_ready].name)
        self._set_psprite("wpn", gd.WEAPONINFO[ws.p_ready].atkstate, keys, ev)
        self.noise_alert(ev)

    def _a_fire_bullets(self, weapon: str, pellets: int, keys: dict, ev) -> None:
        """A_FirePistol (the first shot of a trigger pull is accurate) / A_FireShotgun (7 pellets):
        the player's attack state, one round of ammo, the flash, P_BulletSlope (the aim does it),
        then P_GunShot per pellet."""
        ws = self.ws
        self._set_player_mobj("S_PLAY_ATK2")
        ws.p_ammo[gd.WEAPONINFO[ws.p_ready].ammo] -= 1
        self._set_psprite("flash", gd.WEAPONINFO[ws.p_ready].flashstate, keys, ev)
        accurate = pellets == 1 and not ws.p_refire
        for _ in range(pellets):
            if accurate:
                dmg = self._roll("rng_player", self.sites.pistol_acc)
                col = self.aim_centre
            else:
                dmg, col = self._roll("rng_player", self.sites.gunshot)
            self._line_attack(weapon, col, dmg, MISSILERANGE_U, ev)

    def _a_melee(self, weapon: str, ev) -> None:
        """A_Punch (berserk x10, reach 64) and A_Saw (reach 65). Neither turns the view to the
        target, and the saw's MF_JUSTATTACKED forward pull is not modelled."""
        ws = self.ws
        if weapon == "fist":
            dmg, col = self._roll("rng_player", self.sites.punch)
            if ws.p_strength:
                dmg *= 10
            reach = PUNCH_REACH
        else:
            dmg, col = self._roll("rng_player", self.sites.saw)
            reach = SAW_REACH
        self._line_attack(weapon, col, dmg, reach, ev)

    def _line_attack(self, weapon: str, col: int, dmg: int, reach: int, ev) -> None:
        """P_LineAttack by the player through screen column `col`: the AIM names the target, its
        centre must be within `reach`, then the effect (blood, or a puff on a no-blood thing) and
        the damage, in PTR_ShootTraverse's order."""
        ws, W = self.ws, _W()
        tgt = self.aim(self, col)
        if tgt is not None:
            x, y = self._target_xy(tgt)
            if W.aprox_distance(x - (ws.px >> 16), y - (ws.py >> 16)) > reach:
                tgt = None
        ev.shots.append((weapon, col, tgt, dmg))
        if tgt is None:
            return
        kind, i = tgt
        self._spawn_fx_at_target("puff" if kind == "bar" else "blood", x, y, dmg,
                                 weapon == "fist", ev)
        if kind == "mon":
            self.damage_monster(i, dmg, ("player", -1), ev)
        else:
            self.damage_barrel(i, dmg, ev)
        ev.hits.append((weapon, kind, i, dmg))

    def _target_xy(self, tgt) -> Tuple[int, int]:
        kind, i = tgt
        if kind == "mon":
            return self.ws.mon_x[i], self.ws.mon_y[i]
        t = self.barrel_things[i]
        return t.x, t.y

    # -------------------------------------------------------------------------------- the aim
    def shootable_targets(self) -> List[Tuple[str, int, int, int, int]]:
        """(kind, index, x, y, radius) of every shootable living target: monsters, then barrels."""
        ws = self.ws
        out = []
        for m in range(self.layout.nmon):
            if ws.mon_active[m] and ws.mon_shootable[m] and ws.mon_health[m] > 0:
                out.append(("mon", m, ws.mon_x[m], ws.mon_y[m], self.mon_radius[m]))
        for b, t in enumerate(self.barrel_things):
            if ws.bar_state[b] and ws.bar_health[b] > 0:
                out.append(("bar", b, t.x, t.y, BARREL_R))
        return out

    @staticmethod
    def aim_radius(rm, angle: int, r: int) -> int:
        """DOOM's hit width for a box of radius `r` seen along view angle `angle`: the half-width of
        the corner-to-corner diagonal PIT_AddThingIntercepts tests, r * (|sin v| + |cos v|) (r on an
        axis, 1.41r at 45 degrees) -- docs/gp-aim-window.md 1.7, adopted 2026-09-26. ONE definition
        for the model and the emitter: the view angle's top AIM_REFF_BITS bits index it (the fj side
        is one lookup into a table built from this function), rounded half up, from the repo's
        16.16 sine table."""
        a = (angle >> (32 - AIM_REFF_BITS)) << (32 - AIM_REFF_BITS)
        s = abs(_signed(rm.read_sin(a) & M32, 32))
        c = abs(_signed(rm.read_cos(a) & M32, 32))
        return (r * (s + c) + 32768) >> 16

    @staticmethod
    def aim_geometric(world, col: int):
        """The DEFAULT aim: the nearest (view depth) shootable living target whose box, projected
        from the tic-start view as `ReferenceModel.project_thing` projects a sprite (with DOOM's
        diagonal width `aim_radius` for the sprite's width), covers screen column `col`, within
        MISSILERANGE, with 2D line of sight. Ties go to monsters before barrels, then the lower
        index."""
        ws, rm = world.ws, world.rm
        cfg = rm.cfg
        vcos, vsin = rm.read_cos(ws.pangle), rm.read_sin(ws.pangle)
        cxf = cfg.CENTERX << 16
        best = None
        for order, (kind, i, x, y, r) in enumerate(world.shootable_targets()):
            tr_x = _signed((x << 16) - ws.px, 32)
            tr_y = _signed((y << 16) - ws.py, 32)
            gxt = _signed(fixed_mul(tr_x & M32, vcos, 8, 4), 32)
            gyt = -_signed(fixed_mul(tr_y & M32, vsin, 8, 4), 32)
            tz = gxt - gyt
            if tz < (4 << 16) or tz > (MISSILERANGE_U << 16):
                continue
            gxt2 = -_signed(fixed_mul(tr_x & M32, vsin, 8, 4), 32)
            gyt2 = _signed(fixed_mul(tr_y & M32, vcos, 8, 4), 32)
            tx = -(gyt2 + gxt2)
            xscale = rm._scale_recip_div(cfg.PROJECTION << 16, tz)
            re = CombatMixin.aim_radius(rm, ws.pangle, r)       # DOOM's diagonal width (1.7)
            x1 = (cxf + _signed(fixed_mul((tx - (re << 16)) & M32, xscale, 8, 4), 32)) >> 16
            x2 = ((cxf + _signed(fixed_mul((tx + (re << 16)) & M32, xscale, 8, 4), 32)) >> 16) - 1
            if not x1 <= col <= x2:
                continue
            if best is not None and (tz, order) >= best[0]:
                continue
            if not world.los_points((ws.px, ws.py), (x << 16, y << 16)):
                continue
            best = ((tz, order), (kind, i))
        return None if best is None else best[1]

    # -------------------------------------------------------------------------------- damage
    def damage_monster(self, m: int, dmg: int, source, ev) -> None:
        """P_DamageMobj on a monster (no knockback): health; death; the pain roll on the monster's
        stream; reactiontime 0; and, when its threshold is 0, the target switch to the player --
        which wakes a monster still in its spawn state (into the see state, D-WAKE: no A_Chase)."""
        ws = self.ws
        if not ws.mon_shootable[m] or ws.mon_health[m] <= 0:
            return
        ws.mon_health[m] -= dmg
        if ws.mon_health[m] <= 0:
            self._kill_monster(m, ev)
            return
        info = self.mon_info[m]
        if self._roll("mon_rng", self.sites.pain[info.painchance], m):
            ws.mon_justhit[m] = 1
            self._set_state(m, info.painstate, True, ev)
        ws.mon_reaction[m] = 0
        if not ws.mon_threshold[m] and source[0] == "player":
            ws.mon_target[m] = 1
            ws.mon_threshold[m] = gd.BASETHRESHOLD
            if ws.mon_state[m] == gd.STATE_INDEX[info.spawnstate] and info.seestate != gd.S_NULL:
                self._set_state(m, info.seestate, False, ev)

    def _kill_monster(self, m: int, ev) -> None:
        """P_KillMobj on a monster: not shootable, the death (or gib) state, `tics -= P_Random()&3`,
        and the drop. MF_SOLID stays until the death sequence's A_Fall."""
        ws = self.ws
        info = self.mon_info[m]
        ws.mon_shootable[m] = 0
        gib = ws.mon_health[m] < -info.spawnhealth and info.xdeathstate != gd.S_NULL
        self._set_state(m, info.xdeathstate if gib else info.deathstate, True, ev)
        v = self._roll("mon_rng", self.sites.tics_roll, m)
        ws.mon_tics[m] = max(1, ws.mon_tics[m] - v)
        if self.dropper[m] is not None:
            ws.mon_drop[m] = 1
        ev.kills.append(("mon", m, "gib" if gib else "death"))

    def damage_barrel(self, b: int, dmg: int, ev) -> None:
        """P_DamageMobj on a barrel: the killing blow starts S_BEXP with its tics roll; otherwise
        its pain roll (painchance 0) is drawn and never fires."""
        ws = self.ws
        if not ws.bar_state[b] or ws.bar_health[b] <= 0:
            return
        ws.bar_health[b] = max(ws.bar_health[b] - dmg, BARREL_HEALTH_MIN)
        if ws.bar_health[b] <= 0:
            self._barrel_set_state(b, BARREL_INFO.deathstate, ev)
            v = self._roll("rng_world", self.sites.tics_roll)
            ws.bar_tics[b] = max(1, ws.bar_tics[b] - v)
            ev.kills.append(("bar", b, "death"))
            return
        self._roll("rng_world", self.sites.pain[BARREL_INFO.painchance])

    def damage_player(self, dmg: int, source, ev) -> None:
        """P_DamageMobj on the player: armor (green saves 1/3, blue 1/2), the damage flash, health
        (`p_health` is the thing's health: the killing blow can take it below 0, and the HUD shows
        max(0, p_health) as DOOM's player->health), death, else the pain roll."""
        ws = self.ws
        if ws.p_dead or ws.p_health <= 0:
            return
        raw = dmg
        if ws.p_armortype:
            saved = dmg // 3 if ws.p_armortype == 1 else dmg // 2
            if ws.p_armor <= saved:
                saved = ws.p_armor
                ws.p_armortype = 0
            ws.p_armor -= saved
            dmg -= saved
        ws.p_damagecount = min(100, ws.p_damagecount + dmg)
        ws.p_health -= dmg
        ev.player_hurt.append((source, raw, dmg))
        if ws.p_health <= 0:
            self._kill_player(ev)
            return
        if self._roll("rng_player", self.sites.pain[PLAYER_INFO.painchance]):
            self._set_player_mobj(PLAYER_INFO.painstate)

    def _kill_player(self, ev) -> None:
        """P_KillMobj on the player: dead (and no longer solid), P_DropWeapon, the death state."""
        ws = self.ws
        ws.p_dead = 1
        self._set_psprite("wpn", gd.WEAPONINFO[ws.p_ready].downstate,
                          dict.fromkeys(_W().KEYS, False), ev)
        gib = ws.p_health < -PLAYER_INFO.spawnhealth
        self._set_player_mobj(PLAYER_INFO.xdeathstate if gib else PLAYER_INFO.deathstate)
        v = self._roll("rng_player", self.sites.tics_roll)
        ws.p_mobj_tics = max(1, ws.p_mobj_tics - v)
        ev.deaths += 1

    # -------------------------------------------------------------------------------- monsters
    def _monster_attack(self, m: int, action: str, ev) -> None:
        """A monster attack action: `if (!actor->target) return; A_FaceTarget`, then the effect."""
        ev.attacks.append((m, action))
        if not self.ws.mon_target[m]:
            return
        self._a_face_target(m)
        if action == "A_PosAttack":
            self._mon_hitscan(m, 1, ev)
        elif action == "A_SPosAttack":
            self._mon_hitscan(m, 3, ev)
        elif action == "A_TroopAttack":
            if self._check_melee_range(m):
                self._mon_melee(m, self.sites.troop_claw, ev)
            else:
                self._spawn_fireball(m, ev)
        elif action == "A_SargAttack":
            if self._check_melee_range(m):
                self._mon_melee(m, self.sites.sarg_bite, ev)
        else:
            raise NotImplementedError(action)

    def _mon_melee(self, m: int, site, ev) -> None:
        dmg = self._roll("mon_rng", site, m)
        ev.mon_melee.append((m, dmg))
        self.damage_player(dmg, ("mon", m), ev)

    def _mon_hitscan(self, m: int, bullets: int, ev) -> None:
        """A_PosAttack / A_SPosAttack: one aim (sight and range), then each bullet's spread against
        the player's width at that distance. Every bullet draws, hit or not."""
        W = _W()
        seen = self.player_alive() and self.sight(self, m)
        dist = W.aprox_distance(*self._to_player(m))
        for _ in range(bullets):
            spread, dmg = self._roll("mon_rng", self.sites.mon_bullet, m)
            hit = seen and dist < MISSILERANGE_U and abs(spread) <= self.hwt[dist >> HWT_SHIFT]
            ev.mon_shots.append((m, spread, dmg, hit))
            if hit:
                self.damage_player(dmg, ("mon", m), ev)

    # -------------------------------------------------------------------------------- fireballs
    def _mobile_proj(self, s: int) -> int:
        return self.layout.nmon + s

    def _mobile_fx(self, s: int) -> int:
        return self.layout.nmon + _W().FIREBALL_POOL + s

    def _leaf16(self, x16: int, y16: int) -> int:
        return self.rm.point_in_subsector(self.cmap, x16 >> 16, y16 >> 16)

    def _spawn_fireball(self, m: int, ev) -> None:
        """P_SpawnMissile (MT_TROOPSHOT) + P_CheckMissileSpawn, 2D, into the lowest free slot; a
        full pool fizzles."""
        ws = self.ws
        slot = next((s for s in range(_W().FIREBALL_POOL) if not ws.proj_active[s]), None)
        if slot is None:
            ev.fizzles.append(m)
            return
        sx, sy = ws.mon_x[m] << 16, ws.mon_y[m] << 16
        an = self.rm.point_to_angle(sx, sy, ws.px, ws.py)
        momx, momy = self.fireball_mom[an >> self.rm.angle_shift]
        ws.proj_active[slot], ws.proj_src[slot] = 1, m
        ws.proj_momx[slot], ws.proj_momy[slot] = momx, momy
        self._proj_set_state(slot, FIREBALL_INFO.spawnstate)
        v = self._roll("rng_fx", self.sites.tics_roll)
        ws.proj_tics[slot] = max(1, ws.proj_tics[slot] - v)
        ws.proj_x[slot] = _signed(sx + (momx >> 1), 32)        # "move a little forward"
        ws.proj_y[slot] = _signed(sy + (momy >> 1), 32)
        leaf = self._leaf16(ws.proj_x[slot], ws.proj_y[slot])
        ws.proj_leaf[slot] = leaf
        self._list_insert(self._mobile_proj(slot), leaf)
        ev.proj_spawns.append((slot, m))
        if not self._missile_try(slot, ws.proj_x[slot], ws.proj_y[slot], ev):
            self._explode(slot)

    def _proj_set_state(self, s: int, name: str) -> None:
        ws = self.ws
        ws.proj_state[s], ws.proj_tics[s] = gd.STATE_INDEX[name], gd.STATES[name].tics

    def missile_lines_block(self, x16: int, y16: int) -> bool:
        """PIT_CheckLine for a 2D missile: its box straddles a one-sided line, or a two-sided line
        whose opening at this tic's door heights is shorter than the missile. ML_BLOCKING and
        ML_BLOCKMONSTERS do not stop missiles."""
        r = FIREBALL_R << 16
        top, bottom, left, right = y16 + r, y16 - r, x16 - r, x16 + r
        box = (top, bottom, left, right)
        for (_li, minx, maxx, miny, maxy, ax, ay, bx, by, one, _fl, fs, bs) in self._lines:
            if right <= minx or left >= maxx or top <= miny or bottom >= maxy:
                continue
            if self.rm.box_on_line_side(box, ax, ay, bx, by) != -1:
                continue
            if one:
                return True
            (ff, fc), (bf, bc) = self._sector_hts(fs), self._sector_hts(bs)
            if min(fc, bc) - max(ff, bf) < FIREBALL_H:
                return True
        return False

    def _missile_try(self, s: int, nx: int, ny: int, ev) -> bool:
        """P_TryMove for fireball `s`: things first (the living player's box: damage, stop), then
        the lines; on success it moves and re-links when its leaf changes."""
        ws = self.ws
        if self.player_alive():
            bd = (FIREBALL_R + PLAYER_R) << 16
            if abs(ws.px - nx) < bd and abs(ws.py - ny) < bd:
                dmg = self._roll("rng_fx", self.sites.fireball_hit)
                ev.proj_impacts.append((s, dmg))
                self.damage_player(dmg, ("mon", ws.proj_src[s]), ev)
                return False
        if self.missile_lines_block(nx, ny):
            ev.proj_walls.append(s)
            return False
        ws.proj_x[s], ws.proj_y[s] = nx, ny
        leaf = self._leaf16(nx, ny)
        if leaf != ws.proj_leaf[s]:
            self._list_remove(self._mobile_proj(s), ws.proj_leaf[s])
            ws.proj_leaf[s] = leaf
            self._list_insert(self._mobile_proj(s), leaf)
        return True

    def _explode(self, s: int) -> None:
        """P_ExplodeMissile: stop, the death state, `tics -= P_Random()&3`."""
        ws = self.ws
        ws.proj_momx[s] = ws.proj_momy[s] = 0
        self._proj_set_state(s, FIREBALL_INFO.deathstate)
        v = self._roll("rng_fx", self.sites.tics_roll)
        ws.proj_tics[s] = max(1, ws.proj_tics[s] - v)

    def _projectiles_phase(self, ev) -> None:
        """P_MobjThinker per fireball slot: the XY move (a blocked move explodes it), then the
        state tics; S_NULL frees the slot."""
        ws = self.ws
        for s in range(_W().FIREBALL_POOL):
            if not ws.proj_active[s]:
                continue
            if ws.proj_momx[s] or ws.proj_momy[s]:
                nx = _signed(ws.proj_x[s] + ws.proj_momx[s], 32)
                ny = _signed(ws.proj_y[s] + ws.proj_momy[s], 32)
                if not self._missile_try(s, nx, ny, ev):
                    self._explode(s)
            ws.proj_tics[s] -= 1
            if ws.proj_tics[s]:
                continue
            nxt = gd.STATES[gd.STATE_NAMES[ws.proj_state[s]]].next
            if nxt != gd.S_NULL:
                self._proj_set_state(s, nxt)
                continue
            self._list_remove(self._mobile_proj(s), ws.proj_leaf[s])      # P_RemoveMobj
            for f in ("proj_active", "proj_state", "proj_tics", "proj_x", "proj_y", "proj_momx",
                      "proj_momy", "proj_src", "proj_leaf"):
                getattr(ws, f)[s] = 0

    # -------------------------------------------------------------------------------- effects
    def _spawn_fx_at_target(self, kind: str, x: int, y: int, dmg: int, melee: bool, ev) -> None:
        """P_SpawnPuff / P_SpawnBlood FX_OFFSET units in front of the target, toward the player."""
        ws, W = self.ws, _W()
        ox, oy = FX_STEP[W.octant_of((ws.px >> 16) - x, (ws.py >> 16) - y)]
        self._spawn_fx(kind, (x + ox) << 16, (y + oy) << 16, dmg, melee, ev)

    def _spawn_fx(self, kind: str, x16: int, y16: int, dmg: int, melee: bool, ev) -> None:
        ws = self.ws
        slot = next((s for s in range(_W().FX_POOL) if not ws.fx_active[s]), None)
        if slot is None:
            ev.fx_skipped += 1
            return
        first = "S_PUFF1" if kind == "puff" else "S_BLOOD1"
        ws.fx_active[slot] = 1
        ws.fx_state[slot], ws.fx_tics[slot] = gd.STATE_INDEX[first], gd.STATES[first].tics
        v = self._roll("rng_fx", self.sites.tics_roll)
        ws.fx_tics[slot] = max(1, ws.fx_tics[slot] - v)
        # "don't make punches spark on the wall" (attackrange == MELEERANGE: the fist, not the saw)
        # and blood by damage -- each a P_SetMobjState, which resets the tics just rolled
        again = ("S_PUFF3" if kind == "puff" and melee else
                 "S_BLOOD2" if kind == "blood" and 9 <= dmg <= 12 else
                 "S_BLOOD3" if kind == "blood" and dmg < 9 else None)
        if again:
            ws.fx_state[slot], ws.fx_tics[slot] = gd.STATE_INDEX[again], gd.STATES[again].tics
        ws.fx_x[slot], ws.fx_y[slot] = x16, y16
        leaf = self._leaf16(x16, y16)
        ws.fx_leaf[slot] = leaf
        self._list_insert(self._mobile_fx(slot), leaf)
        ev.fx_spawns.append((slot, kind))

    def _fx_phase(self, ev) -> None:
        ws = self.ws
        for s in range(_W().FX_POOL):
            if not ws.fx_active[s]:
                continue
            ws.fx_tics[s] -= 1
            if ws.fx_tics[s]:
                continue
            nxt = gd.STATES[gd.STATE_NAMES[ws.fx_state[s]]].next
            if nxt != gd.S_NULL:
                ws.fx_state[s], ws.fx_tics[s] = gd.STATE_INDEX[nxt], gd.STATES[nxt].tics
                continue
            self._list_remove(self._mobile_fx(s), ws.fx_leaf[s])
            for f in ("fx_active", "fx_state", "fx_tics", "fx_x", "fx_y", "fx_leaf"):
                getattr(ws, f)[s] = 0

    # -------------------------------------------------------------------------------- barrels
    def _barrel_set_state(self, b: int, name: str, ev) -> None:
        """P_SetMobjState for a barrel; A_Explode is its one action, S_NULL removes it."""
        ws, W = self.ws, _W()
        for _guard in range(16):
            if name == gd.S_NULL:                # P_RemoveMobj: gone, no longer blocks
                ws.bar_state[b] = ws.bar_tics[b] = ws.bar_solid[b] = 0
                return
            st = gd.STATES[name]
            ws.bar_state[b] = gd.STATE_INDEX[name]
            ws.bar_tics[b] = W.TICS_FOREVER if st.tics < 0 else st.tics
            if st.action == "A_Explode":
                self._radius_attack(b, ev)
            name = st.next
            if ws.bar_tics[b] != 0:
                return
        raise AssertionError("barrel state cycle")

    def _barrels_phase(self, ev) -> None:
        ws, W = self.ws, _W()
        for b in range(self.layout.nbarrel):
            if not ws.bar_state[b] or ws.bar_tics[b] == W.TICS_FOREVER:
                continue
            ws.bar_tics[b] -= 1
            if ws.bar_tics[b] == 0:
                self._barrel_set_state(b, gd.STATES[gd.STATE_NAMES[ws.bar_state[b]]].next, ev)

    def _radius_attack(self, b: int, ev) -> None:
        """P_RadiusAttack (barrel b, the player, 128): every shootable thing whose Chebyshev
        distance to the blast, minus its radius, is under 128 and that 2D sight reaches takes
        128 - dist -- the player, then monsters by slot, then barrels by index. Each target rolls
        on its own stream except the barrels, which share the world stream in index order."""
        ws = self.ws
        t = self.barrel_things[b]
        spot = (t.x << 16, t.y << 16)
        ev.barrel_blasts.append(b)

        def dist(x16: int, y16: int, r: int) -> int:
            d = max(abs(x16 - spot[0]), abs(y16 - spot[1]))
            return max(0, (d - (r << 16)) >> 16)

        if self.player_alive():
            d = dist(ws.px, ws.py, PLAYER_R)
            if d < BOMB_DAMAGE and self.los_points((ws.px, ws.py), spot):
                self.damage_player(BOMB_DAMAGE - d, ("bar", b), ev)
        for m in range(self.layout.nmon):
            if not (ws.mon_active[m] and ws.mon_shootable[m] and ws.mon_health[m] > 0):
                continue
            p = (ws.mon_x[m] << 16, ws.mon_y[m] << 16)
            d = dist(p[0], p[1], self.mon_radius[m])
            if d < BOMB_DAMAGE and self.los_points(p, spot):
                ev.hits.append(("barrel", "mon", m, BOMB_DAMAGE - d))
                self.damage_monster(m, BOMB_DAMAGE - d, ("player", -1), ev)
        for c, tc in enumerate(self.barrel_things):
            if c == b or not ws.bar_state[c] or ws.bar_health[c] <= 0:
                continue
            p = (tc.x << 16, tc.y << 16)
            d = dist(p[0], p[1], BARREL_R)
            if d < BOMB_DAMAGE and self.los_points(p, spot):
                ev.hits.append(("barrel", "bar", c, BOMB_DAMAGE - d))
                self.damage_barrel(c, BOMB_DAMAGE - d, ev)

    # -------------------------------------------------------------------------------- the move
    def _player_move(self, keys: dict, ev) -> None:
        """`ReferenceModel.step_sim` with things: the same turn, the same FixedMul step and the same
        three candidates (full step, x only, y only) through the oracle's own `try_move`. At each
        candidate the specials are touched, then a solid thing refuses it -- unless
        `player_blocking` is off (the legacy walk-through, for regression comparison). With nothing
        in the way this IS step_sim (a test holds the two equal)."""
        rmod, ws = self.rm, self.ws
        angle = ws.pangle
        if keys["turn_left"]:
            angle = (angle + ANGLE_TURN) & M32
        if keys["turn_right"]:
            angle = (angle - ANGLE_TURN) & M32
        ws.pangle = angle
        move = (FORWARD_MOVE if keys["forward"] else 0) - (FORWARD_MOVE if keys["back"] else 0)
        side = (STRAFE_MOVE if keys["strafe_right"] else 0) - (STRAFE_MOVE if keys["strafe_left"] else 0)
        if not move and not side:
            return
        # DOOM's P_MovePlayer: forward along `angle`, side along `angle - ANG90`, i.e.
        # (sin a, -cos a) -- each a FixedMul like the forward step, so the fj path can mirror it.
        dx = dy = 0
        if move:
            m = move & M32
            dx += fixed_mul(m, rmod.read_cos(angle), 8, 4)
            dy += fixed_mul(m, rmod.read_sin(angle), 8, 4)
        if side:
            sd = side & M32
            dx += fixed_mul(sd, rmod.read_sin(angle), 8, 4)
            dy -= fixed_mul(sd, rmod.read_cos(angle), 8, 4)
        x, y = ws.px, ws.py
        here_z = rmod.check_position(self.scene_c, x, y)[1]
        for cand in (((x + dx) & M32, (y + dy) & M32), ((x + dx) & M32, y),
                     (x, (y + dy) & M32)):
            if cand == (x, y):
                continue
            cx, cy = _signed(cand[0], 32), _signed(cand[1], 32)
            self._touch_specials(cx, cy, here_z, ev)
            if self.player_blocking and self._solid_thing_at(cx, cy) is not None:
                ev.player_blocked += 1
                continue
            if rmod.try_move(self.scene_c, x, y, cx, cy):
                ws.px, ws.py = cx, cy
                return

    def _solid_thing_at(self, x16: int, y16: int):
        """PIT_CheckThing's refusal for the player's box at (x16, y16): the first solid monster,
        barrel or decor thing whose box overlaps (`abs(dx) < blockdist` on both axes)."""
        ws = self.ws
        for m in range(self.layout.nmon):
            if ws.mon_active[m] and ws.mon_solid[m]:
                bd = (self.mon_radius[m] + PLAYER_R) << 16
                if abs((ws.mon_x[m] << 16) - x16) < bd and abs((ws.mon_y[m] << 16) - y16) < bd:
                    return ("mon", m)
        for b, t in enumerate(self.barrel_things):
            if ws.bar_solid[b]:
                bd = (BARREL_R + PLAYER_R) << 16
                if abs((t.x << 16) - x16) < bd and abs((t.y << 16) - y16) < bd:
                    return ("bar", b)
        for t in self._decor_now:
            bd = (self.decor_radius[t.type] + PLAYER_R) << 16
            if abs((t.x << 16) - x16) < bd and abs((t.y << 16) - y16) < bd:
                return ("decor", t.type)
        return None

    # -------------------------------------------------------------------------------- pickups
    def _touch_specials(self, x16: int, y16: int, z: int, ev) -> None:
        """PIT_CheckThing's pickups at the player's tried position: every untaken item whose box
        overlaps (item radius 20 + player radius 16), map things by index, then drops by slot."""
        ws = self.ws
        if not self.player_alive():
            return                               # "Dead thing touching"
        bd = (ITEM_RADIUS + PLAYER_R) << 16
        for i, t in enumerate(self.pickup_things):
            if ws.pickup_taken[i]:
                continue
            if abs((t.x << 16) - x16) >= bd or abs((t.y << 16) - y16) >= bd:
                continue
            if self._touch(t.type, False, self.pickup_z[i], z):
                ws.pickup_taken[i] = 1
                ev.pickups.append(("item", i, t.type))
        for m in range(self.layout.nmon):
            if ws.mon_drop[m] != 1:
                continue
            if abs((ws.mon_x[m] << 16) - x16) >= bd or abs((ws.mon_y[m] << 16) - y16) >= bd:
                continue
            if self._touch(self.dropper[m], True, self._floor_at(ws.mon_x[m], ws.mon_y[m]), z):
                ws.mon_drop[m] = 2
                ev.pickups.append(("drop", m, self.dropper[m]))

    def _touch(self, kind: int, dropped: bool, item_z: int, z: int) -> bool:
        """P_TouchSpecialThing: the reach test, then the give routine by type (the comments are
        DOOM's sprite names). True when the thing is taken (P_RemoveMobj, bonuscount += 6)."""
        ws = self.ws
        delta = item_z - z
        if delta > REACH_UP or delta < -REACH_DOWN:
            return False                         # "out of reach"
        if kind not in GETTABLE:
            raise NotImplementedError("P_TouchSpecialThing: unknown gettable thing %d" % kind)
        if kind == 2018:                                              # ARM1
            taken = self._give_armor(1)
        elif kind == 2019:                                            # ARM2
            taken = self._give_armor(2)
        elif kind == 2014:                                            # BON1: can go over 100%
            ws.p_health = min(ws.p_health + 1, MAX_HEALTH_BONUS)
            taken = True
        elif kind == 2015:                                            # BON2
            ws.p_armor = min(ws.p_armor + 1, MAX_ARMOR_BONUS)
            if not ws.p_armortype:
                ws.p_armortype = 1
            taken = True
        elif kind == 5:                                               # BKEY: P_GiveCard
            if not ws.p_cards[gd.IT_BLUECARD]:
                ws.p_bonuscount = gd.BONUSADD                         # ... SETS the flash
                ws.p_cards[gd.IT_BLUECARD] = 1
            taken = True
        elif kind == 2011:                                            # STIM
            taken = self._give_body(10)
        elif kind == 2012:                                            # MEDI
            taken = self._give_body(25)
        elif kind == 2023:                                            # PSTR: P_GivePower
            self._give_body(100)
            ws.p_strength = 1
            if ws.p_ready != gd.WP_FIST:
                ws.p_pending = gd.WP_FIST
            taken = True
        elif kind == 2007:                                            # CLIP (dropped: half)
            taken = self._give_ammo(gd.AM_CLIP, 0 if dropped else 1)
        elif kind == 2048:                                            # AMMO
            taken = self._give_ammo(gd.AM_CLIP, 5)
        elif kind == 2010:                                            # ROCK
            taken = self._give_ammo(gd.AM_MISL, 1)
        elif kind == 2046:                                            # BROK
            taken = self._give_ammo(gd.AM_MISL, 5)
        elif kind == 2047:                                            # CELL
            taken = self._give_ammo(gd.AM_CELL, 1)
        elif kind == 17:                                              # CELP
            taken = self._give_ammo(gd.AM_CELL, 5)
        elif kind == 2008:                                            # SHEL
            taken = self._give_ammo(gd.AM_SHELL, 1)
        elif kind == 2049:                                            # SBOX
            taken = self._give_ammo(gd.AM_SHELL, 5)
        elif kind == 8:                                               # BPAK
            ws.p_backpack = 1
            for a in range(gd.NUMAMMO):
                self._give_ammo(a, 1)
            taken = True
        elif kind == 2005:                                            # CSAW
            taken = self._give_weapon(gd.WP_CHAINSAW, False)
        else:                                                         # SHOT (2001)
            taken = self._give_weapon(gd.WP_SHOTGUN, dropped)
        if taken:
            ws.p_bonuscount = min(ws.p_bonuscount + gd.BONUSADD, 255)
        return taken

    def max_ammo(self, a: int) -> int:
        return gd.MAXAMMO[a] * (2 if self.ws.p_backpack else 1)

    def _give_ammo(self, a: int, num: int) -> bool:
        """P_GiveAmmo: `num` clips (0 = half a clip), capped; from empty, DOOM's auto-switch."""
        ws = self.ws
        if ws.p_ammo[a] == self.max_ammo(a):
            return False
        num = num * gd.CLIPAMMO[a] if num else gd.CLIPAMMO[a] // 2
        old = ws.p_ammo[a]
        ws.p_ammo[a] = min(old + num, self.max_ammo(a))
        if old:
            return True                          # "player was lower on purpose"
        r = ws.p_ready
        if a == gd.AM_CLIP:
            if r == gd.WP_FIST:
                ws.p_pending = gd.WP_CHAINGUN if ws.p_owned[gd.WP_CHAINGUN] else gd.WP_PISTOL
        elif a == gd.AM_SHELL:
            if r in (gd.WP_FIST, gd.WP_PISTOL) and ws.p_owned[gd.WP_SHOTGUN]:
                ws.p_pending = gd.WP_SHOTGUN
        elif a == gd.AM_CELL:
            if r in (gd.WP_FIST, gd.WP_PISTOL) and ws.p_owned[gd.WP_PLASMA]:
                ws.p_pending = gd.WP_PLASMA
        elif a == gd.AM_MISL:
            if r == gd.WP_FIST and ws.p_owned[gd.WP_MISSILE]:
                ws.p_pending = gd.WP_MISSILE
        return True

    def _give_weapon(self, w: int, dropped: bool) -> bool:
        """P_GiveWeapon, single player: one clip with a dropped weapon, two with a found one; a new
        weapon becomes the pending one."""
        ws = self.ws
        ammo = gd.WEAPONINFO[w].ammo
        gave_ammo = ammo != gd.AM_NOAMMO and self._give_ammo(ammo, 1 if dropped else 2)
        if ws.p_owned[w]:
            return gave_ammo
        ws.p_owned[w] = 1
        ws.p_pending = w
        return True

    def _give_body(self, num: int) -> bool:
        ws = self.ws
        if ws.p_health >= gd.MAXHEALTH:
            return False
        ws.p_health = min(ws.p_health + num, gd.MAXHEALTH)
        return True

    def _give_armor(self, armortype: int) -> bool:
        ws = self.ws
        hits = armortype * 100
        if ws.p_armor >= hits:
            return False                         # "don't pick up"
        ws.p_armortype, ws.p_armor = armortype, hits
        return True

    # -------------------------------------------------------------------------------- summaries
    EVENT_COUNTERS = ("fired", "shots", "hits", "kills", "pickups", "proj_spawns", "proj_impacts",
                      "proj_walls", "fizzles", "barrel_blasts", "fx_spawns", "fx_skipped",
                      "mon_shots", "mon_melee", "player_hurt", "deaths", "restarts",
                      "restart_requests", "nukage", "player_blocked", "level_done")

    def event_totals(self, events=None) -> Dict[str, int]:
        """Counts over a run's TicEvents -- what the gates require to be non-zero."""
        out = dict.fromkeys(self.EVENT_COUNTERS, 0)
        for ev in (self.events if events is None else events):
            for k in out:
                v = getattr(ev, k)
                out[k] += len(v) if isinstance(v, list) else int(v)
        return out

    def player_view(self) -> dict:
        """The player's game state in one dict (model_run, the HUD numbers)."""
        ws = self.ws
        return {"health": max(0, ws.p_health), "armor": ws.p_armor, "armortype": ws.p_armortype,
                "ammo": list(ws.p_ammo), "backpack": ws.p_backpack,
                "weapon": gd.WEAPONINFO[ws.p_ready].name,
                "pending": (gd.WEAPONINFO[ws.p_pending].name
                            if ws.p_pending in gd.WEAPONINFO else None),
                "owned": [gd.WEAPONINFO[w].name for w in sorted(gd.WEAPONINFO) if ws.p_owned[w]],
                "wpn_state": gd.STATE_NAMES[ws.p_wpn_state], "wpn_sy": ws.p_wpn_sy,
                "cards": [c for c in range(gd.NUMCARDS) if ws.p_cards[c]],
                "damagecount": ws.p_damagecount, "bonuscount": ws.p_bonuscount,
                "strength": ws.p_strength, "dead": ws.p_dead}
