"""M8 C6 -- THE TIMED POWERS a map can hold: partial invisibility (2024, pw_invisibility) and the radiation suit (2025,
pw_ironfeet). ONE definition of every rule both mirrors read (the model: world / combat; the fj: doomfj.powercode):

  * which powers a map has (`map_powers`: the single-player things -- E1M1 and E1M2 hold neither, so their schema,
    their program and every digest they recorded are untouched);
  * the cells: `p_invis` / `p_ironfeet` (schema, 12 bits: 0 .. INVISTICS / IRONTICS = 2100), the fj's `p_inv` / `p_rad`
    (3 nibbles);
  * P_GivePower (p_inter.c): the counter SET to 60 * TICRATE, always taken (re-taking restarts it); the invisibility's
    MF_SHADOW is "the counter is not 0" (P_GivePower sets the flag with the counter, P_PlayerThink clears it when the
    counter reaches 0);
  * P_PlayerThink's countdown: once a PLAYER tic (here once a frame, as strength, damagecount and bonuscount are; the
    dead player's think returns before it, so the counters stop while he is dead);
  * `blinking(counter)`: `counter > 4*32 || counter & 8` -- ST_doPaletteStuff's radiation tint (RADIATIONPAL) and
    R_DrawPSprite's shadow draw of the weapon, the end-of-power flicker of both;
  * P_PlayerInSpecialSector with the suit: sectors 5 / 7 hurt nothing; 16 / 4 (the 20-damage kinds) hurt only when
    `P_Random() < SUIT_LEAK` -- CONVENTION (recorded): DOOM draws that number every tic the player stands on the floor
    of such a sector; here it is drawn only on the hurt tic (leveltime & 31 == 0), from the player's stream `rng_pl`.
    The chance of a hurt per 32 tics is DOOM's (5 / 256); only the stream's draw count differs;
  * MF_SHADOW on the player, the monsters' aim (p_enemy.c A_FaceTarget, p_mobj.c P_SpawnMissile): A_FaceTarget at a
    shadow target turns the shooter by `P_SubRandom() << 21` (2 draws on the shooter's stream `mon_rng`, at EVERY
    A_FaceTarget at the player while he is invisible: the attack states' and the attacks' own); a hitscan's bullets
    leave along that angle, so each bullet's spread is `P_SubRandom() << 20` PLUS the jitter (in the spread's unit,
    2^20 BAM: 2 * (a - b)); P_SpawnMissile at a shadow target turns the fireball by `P_SubRandom() << 20` (2 more
    draws, the shooter's stream). CONVENTIONS (recorded): the shooter's FACING (`mon_facing`, the model's octant --
    `world.octant_of`, the nearest octant of the offset) does not take the jitter (the octant model has no sub-octant
    angle to turn); only the PLAYER is a shadow target (a spectre target's MF_SHADOW stays undrawn, combat's P8a
    convention).
"""
from __future__ import annotations

from typing import Tuple

from doomfj import gamedata as gd

INVIS_TYPE, SUIT_TYPE = 2024, 2025          # MT_INS, MT_MISC14
POWER_TYPES = (INVIS_TYPE, SUIT_TYPE)
TICS = {INVIS_TYPE: gd.INVISTICS, SUIT_TYPE: gd.IRONTICS}
FIELD = {INVIS_TYPE: "p_invis", SUIT_TYPE: "p_ironfeet"}      # world schema
CELL = {INVIS_TYPE: "p_inv", SUIT_TYPE: "p_rad"}              # the fj's cells (the schema's labels)
BITS = 12                                   # 2100 < 4096
NIBBLES = 3
BLINK_TICS = 4 * 32                         # `> 4*32 || & 8`
BLINK_BIT = 8
RADIATIONPAL = 13                           # st_stuff.c
SUIT_LEAK = 5                               # p_spec.c: `P_Random() < 5` on a 20-damage floor with the suit on
SUIT_LEAK_DAMAGE = 20                       # the floors the suit leaks on: combat.SECTOR_HURT's 16 and 4
FACE_SHIFT, MISSILE_SHIFT = 21, 20          # A_FaceTarget's `<< 21`, P_SpawnMissile's `<< 20`
SPREAD_SHIFT = 20                           # the bullets' spread unit (combat.Sites.mon_bullet: P_SubRandom() << 20)

assert all(t < (1 << BITS) for t in TICS.values()) and NIBBLES * 4 == BITS


def map_powers(things) -> Tuple[int, ...]:
    """THE ONE RULE: the power kinds (POWER_TYPES order) a map holds among `things` (a WAD's raw list, or a World's),
    single-player ones (things.single_player, the World's own filter) -- E1M1, E1M2: none"""
    from doomfj.things import single_player
    return tuple(k for k in POWER_TYPES if any(t.type == k and single_player(t) for t in things))


def blinking(counter: int) -> bool:
    """`counter > 4*32 || counter & 8` -- the radiation palette's and the shadow weapon's condition"""
    return counter > BLINK_TICS or bool(counter & BLINK_BIT)


def face_jitter(a: int, b: int) -> int:
    """A_FaceTarget's turn at a shadow target, `P_SubRandom() << 21` (P_SubRandom = a - b), in the bullets' spread
    unit (2^20 BAM)"""
    return (a - b) << (FACE_SHIFT - SPREAD_SHIFT)


def missile_jitter(a: int, b: int) -> int:
    """P_SpawnMissile's turn at a shadow target, `P_SubRandom() << 20`, in BAM (signed)"""
    return (a - b) << MISSILE_SHIFT


def suit_leaks(v: int) -> bool:
    """`P_Random() < 5`"""
    return v < SUIT_LEAK
