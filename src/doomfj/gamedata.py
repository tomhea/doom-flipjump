"""S3a -- DOOM's engine data for every actor E1M1 needs, in ONE place (plan section 4 rule 7).

The emitter and the oracle both read these tables; neither restates a number. Everything here is
DOOM's own data, copied from the Chocolate Doom source at commit
895f581c5d91497bdda0516612da803fe5843e28 (master, 2026-09-08):

    info.c     https://raw.githubusercontent.com/chocolate-doom/chocolate-doom/895f581c5d91497bdda0516612da803fe5843e28/src/doom/info.c
    p_pspr.c   .../src/doom/p_pspr.c      LOWERSPEED, RAISESPEED, WEAPONBOTTOM, WEAPONTOP
    d_items.c  .../src/doom/d_items.c     weaponinfo[]
    p_inter.c  .../src/doom/p_inter.c     maxammo[], clipammo[], BONUSADD
    p_enemy.c  .../src/doom/p_enemy.c     dirtype_t, opposite[], diags[], xspeed[], yspeed[]
    p_local.h  .../src/doom/p_local.h     MELEERANGE, MISSILERANGE, MAXRADIUS, BASETHRESHOLD, ...
    p_mobj.h   .../src/doom/p_mobj.h      mobjflag_t
    doomdata.h .../src/doom/doomdata.h    ML_* linedef flags
    doomdef.h  .../src/doom/doomdef.h     weapontype_t, ammotype_t, card_t, powertype_t
    g_game.c   .../src/doom/g_game.c      G_PlayerReborn (initial health, bullets, weapons)
    p_mobj.c   .../src/doom/p_mobj.c      P_SpawnMapThing's skill bits and MTF_ options

HOW IT WAS COPIED, and why that matters. The files were read through a fetch tool whose answer
passes through a small language model, so every state row and every mobjinfo block below was
fetched TWICE -- once from Chocolate Doom and once, independently, from id Software's release
(https://raw.githubusercontent.com/id-Software/DOOM/master/linuxdoom-1.10/info.c) -- and the two
extractions were diffed by script: 212 states and 11 mobjinfo blocks, identical. The state rows
were then written into this file by a generator, not by hand.

TWO GAPS IN THAT PROVENANCE, stated rather than hidden:
  * MT_SHOTGUN's block (the dropped shotgun) lies past the part of info.c the fetch tool can see
    (it stops at MT_MISC18). Its values are the pickup TEMPLATE every weapon and ammo pickup in
    info.c shares, which MT_CLIP (verified) also has: 1000 hp, reactiontime 8, radius 20, height
    16, mass 100, MF_SPECIAL. Recorded as `MT_SHOTGUN` with source "template".
  * The DECOR on E1M1 (trees, columns, corpses) is needed only for thing-thing BLOCKING: its radius
    and whether it is MF_SOLID. Those came from GZDoom's actor definitions at commit
    c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7 (wadsrc/static/zscript/actors/doom/
    doomdecorations.zs and wadsrc/static/mapinfo/doomitems.txt), which keep vanilla's radius and
    solidity. See `THING_TYPES` and its `source` column. A later fetch of the tail of info.c
    should replace them.

Units are DOOM's: positions and radii in 16.16 fixed point (`FRACUNIT`), a monster's `speed` in map
units per step (DOOM multiplies it by xspeed[]), a missile's `speed` in 16.16. Nothing here is a
gameplay-model RULE -- the approved simplifications (K, the rounded diagonals, the pools) live in
`doomfj.world`, which imports this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

SOURCE_COMMIT = "895f581c5d91497bdda0516612da803fe5843e28"
SOURCE_BASE = ("https://raw.githubusercontent.com/chocolate-doom/chocolate-doom/%s/src/doom/"
               % SOURCE_COMMIT)
CROSSCHECK_BASE = "https://raw.githubusercontent.com/id-Software/DOOM/master/linuxdoom-1.10/"
DECOR_SOURCE = ("https://raw.githubusercontent.com/ZDoom/gzdoom/"
                "c26ce2e6ca2a0c770f140cb25dde0d30073ca8f7/wadsrc/static/")

FRACBITS = 16
FRACUNIT = 1 << FRACBITS
FF_FULLBRIGHT = 0x8000            # info.c frame bit: drawn at full brightness
FF_FRAMEMASK = 0x7FFF

# ---- p_mobj.h: mobjflag_t ----------------------------------------------------------------------
MF_SPECIAL = 1
MF_SOLID = 2
MF_SHOOTABLE = 4
MF_NOSECTOR = 8
MF_NOBLOCKMAP = 16
MF_AMBUSH = 32
MF_JUSTHIT = 64
MF_JUSTATTACKED = 128
MF_SPAWNCEILING = 256
MF_NOGRAVITY = 512
MF_DROPOFF = 0x400
MF_PICKUP = 0x800
MF_NOCLIP = 0x1000
MF_SLIDE = 0x2000
MF_FLOAT = 0x4000
MF_TELEPORT = 0x8000
MF_MISSILE = 0x10000
MF_DROPPED = 0x20000
MF_SHADOW = 0x40000
MF_NOBLOOD = 0x80000
MF_CORPSE = 0x100000
MF_INFLOAT = 0x200000
MF_COUNTKILL = 0x400000
MF_COUNTITEM = 0x800000
MF_SKULLFLY = 0x1000000
MF_NOTDMATCH = 0x2000000

# ---- doomdata.h: linedef flags -----------------------------------------------------------------
ML_BLOCKING = 1
ML_BLOCKMONSTERS = 2
ML_TWOSIDED = 4
ML_DONTPEGTOP = 8
ML_DONTPEGBOTTOM = 16
ML_SECRET = 32
ML_SOUNDBLOCK = 64
ML_DONTDRAW = 128
ML_MAPPED = 256

# ---- THINGS options, as P_SpawnMapThing reads them (p_mobj.c) ----------------------------------
MTF_EASY = 1                      # also sk_baby
MTF_NORMAL = 2
MTF_HARD = 4                      # also sk_nightmare
MTF_AMBUSH = 8
MTF_NOTSINGLE = 16                # multiplayer only: `if (!netgame && (mthing->options & 16)) return`

# ---- skill_t -----------------------------------------------------------------------------------
SK_BABY, SK_EASY, SK_MEDIUM, SK_HARD, SK_NIGHTMARE = range(5)
SKILL_NAMES = {"easy": SK_EASY, "medium": SK_MEDIUM, "hard": SK_HARD}


def skill_bit(gameskill: int) -> int:
    """P_SpawnMapThing: the THINGS-options bit a skill spawns. baby shares easy's, nightmare hard's;
    otherwise `1 << (gameskill - 1)`."""
    if gameskill == SK_BABY:
        return MTF_EASY
    if gameskill == SK_NIGHTMARE:
        return MTF_HARD
    return 1 << ((gameskill - 1) & 0x1F)


# ---- p_local.h (16.16 unless noted) ------------------------------------------------------------
FLOATSPEED = 4 * FRACUNIT
MAXHEALTH = 100
VIEWHEIGHT = 41 * FRACUNIT
PLAYERRADIUS = 16 * FRACUNIT
MAXRADIUS = 32 * FRACUNIT
USERANGE = 64 * FRACUNIT
MELEERANGE = 64 * FRACUNIT
MISSILERANGE = 32 * 64 * FRACUNIT
BASETHRESHOLD = 100               # a plain count, not fixed point
MAXMOVE = 30 * FRACUNIT
MAX_STEP_UP = 24 * FRACUNIT       # P_TryMove's `tmfloorz - thing->z > 24*FRACUNIT` (a literal there)

# ---- p_enemy.c: movement directions ------------------------------------------------------------
(DI_EAST, DI_NORTHEAST, DI_NORTH, DI_NORTHWEST, DI_WEST, DI_SOUTHWEST, DI_SOUTH, DI_SOUTHEAST,
 DI_NODIR) = range(9)
NUMDIRS = 9
OPPOSITE = (DI_WEST, DI_SOUTHWEST, DI_SOUTH, DI_SOUTHEAST,
            DI_EAST, DI_NORTHEAST, DI_NORTH, DI_NORTHWEST, DI_NODIR)
DIAGS = (DI_NORTHWEST, DI_NORTHEAST, DI_SOUTHWEST, DI_SOUTHEAST)
XSPEED = (FRACUNIT, 47000, 0, -47000, -FRACUNIT, -47000, 0, 47000)
YSPEED = (0, 47000, FRACUNIT, 47000, 0, -47000, -FRACUNIT, -47000)

# ---- doomdef.h enums ---------------------------------------------------------------------------
(WP_FIST, WP_PISTOL, WP_SHOTGUN, WP_CHAINGUN, WP_MISSILE, WP_PLASMA, WP_BFG, WP_CHAINSAW,
 WP_SUPERSHOTGUN) = range(9)
NUMWEAPONS = 9
WP_NOCHANGE = 10
AM_CLIP, AM_SHELL, AM_CELL, AM_MISL = range(4)
NUMAMMO = 4
AM_NOAMMO = 5
(IT_BLUECARD, IT_YELLOWCARD, IT_REDCARD, IT_BLUESKULL, IT_YELLOWSKULL, IT_REDSKULL) = range(6)
NUMCARDS = 6
(PW_INVULNERABILITY, PW_STRENGTH, PW_INVISIBILITY, PW_IRONFEET, PW_ALLMAP, PW_INFRARED) = range(6)
NUMPOWERS = 6

# ---- p_inter.c ---------------------------------------------------------------------------------
MAXAMMO = (200, 50, 300, 50)      # indexed by AM_*; a backpack doubles these
CLIPAMMO = (10, 4, 20, 1)
BONUSADD = 6

# ---- g_game.c G_PlayerReborn (deh_misc.c defaults) ---------------------------------------------
INITIAL_HEALTH = 100
INITIAL_BULLETS = 50
INITIAL_WEAPON = WP_PISTOL        # readyweapon = pendingweapon
INITIAL_WEAPONS_OWNED = (WP_FIST, WP_PISTOL)

# ---- p_pspr.c ----------------------------------------------------------------------------------
LOWERSPEED = 6 * FRACUNIT
RAISESPEED = 6 * FRACUNIT
WEAPONBOTTOM = 128 * FRACUNIT
WEAPONTOP = 32 * FRACUNIT


# ================================================================================================
# STATES -- info.c `states[]`, the rows every E1M1 actor and the four E1M1 weapons can reach, in
# DOOM's array order. (name, sprite, frame, tics, action, next). `frame` keeps FF_FULLBRIGHT.
# `tics == -1` is DOOM's "stay forever". Generated from the twice-fetched, diffed extraction.
# ================================================================================================
_STATE_ROWS: Tuple[Tuple, ...] = (
    ('S_NULL', 'TROO', 0, -1, None, 'S_NULL'),
    ('S_LIGHTDONE', 'SHTG', 4, 0, 'A_Light0', 'S_NULL'),
    ('S_PUNCH', 'PUNG', 0, 1, 'A_WeaponReady', 'S_PUNCH'),
    ('S_PUNCHDOWN', 'PUNG', 0, 1, 'A_Lower', 'S_PUNCHDOWN'),
    ('S_PUNCHUP', 'PUNG', 0, 1, 'A_Raise', 'S_PUNCHUP'),
    ('S_PUNCH1', 'PUNG', 1, 4, None, 'S_PUNCH2'),
    ('S_PUNCH2', 'PUNG', 2, 4, 'A_Punch', 'S_PUNCH3'),
    ('S_PUNCH3', 'PUNG', 3, 5, None, 'S_PUNCH4'),
    ('S_PUNCH4', 'PUNG', 2, 4, None, 'S_PUNCH5'),
    ('S_PUNCH5', 'PUNG', 1, 5, 'A_ReFire', 'S_PUNCH'),
    ('S_PISTOL', 'PISG', 0, 1, 'A_WeaponReady', 'S_PISTOL'),
    ('S_PISTOLDOWN', 'PISG', 0, 1, 'A_Lower', 'S_PISTOLDOWN'),
    ('S_PISTOLUP', 'PISG', 0, 1, 'A_Raise', 'S_PISTOLUP'),
    ('S_PISTOL1', 'PISG', 0, 4, None, 'S_PISTOL2'),
    ('S_PISTOL2', 'PISG', 1, 6, 'A_FirePistol', 'S_PISTOL3'),
    ('S_PISTOL3', 'PISG', 2, 4, None, 'S_PISTOL4'),
    ('S_PISTOL4', 'PISG', 1, 5, 'A_ReFire', 'S_PISTOL'),
    ('S_PISTOLFLASH', 'PISF', 32768, 7, 'A_Light1', 'S_LIGHTDONE'),
    ('S_SGUN', 'SHTG', 0, 1, 'A_WeaponReady', 'S_SGUN'),
    ('S_SGUNDOWN', 'SHTG', 0, 1, 'A_Lower', 'S_SGUNDOWN'),
    ('S_SGUNUP', 'SHTG', 0, 1, 'A_Raise', 'S_SGUNUP'),
    ('S_SGUN1', 'SHTG', 0, 3, None, 'S_SGUN2'),
    ('S_SGUN2', 'SHTG', 0, 7, 'A_FireShotgun', 'S_SGUN3'),
    ('S_SGUN3', 'SHTG', 1, 5, None, 'S_SGUN4'),
    ('S_SGUN4', 'SHTG', 2, 5, None, 'S_SGUN5'),
    ('S_SGUN5', 'SHTG', 3, 4, None, 'S_SGUN6'),
    ('S_SGUN6', 'SHTG', 2, 5, None, 'S_SGUN7'),
    ('S_SGUN7', 'SHTG', 1, 5, None, 'S_SGUN8'),
    ('S_SGUN8', 'SHTG', 0, 3, None, 'S_SGUN9'),
    ('S_SGUN9', 'SHTG', 0, 7, 'A_ReFire', 'S_SGUN'),
    ('S_SGUNFLASH1', 'SHTF', 32768, 4, 'A_Light1', 'S_SGUNFLASH2'),
    ('S_SGUNFLASH2', 'SHTF', 32769, 3, 'A_Light2', 'S_LIGHTDONE'),
    ('S_SAW', 'SAWG', 2, 4, 'A_WeaponReady', 'S_SAWB'),
    ('S_SAWB', 'SAWG', 3, 4, 'A_WeaponReady', 'S_SAW'),
    ('S_SAWDOWN', 'SAWG', 2, 1, 'A_Lower', 'S_SAWDOWN'),
    ('S_SAWUP', 'SAWG', 2, 1, 'A_Raise', 'S_SAWUP'),
    ('S_SAW1', 'SAWG', 0, 4, 'A_Saw', 'S_SAW2'),
    ('S_SAW2', 'SAWG', 1, 4, 'A_Saw', 'S_SAW3'),
    ('S_SAW3', 'SAWG', 1, 0, 'A_ReFire', 'S_SAW'),
    ('S_BLOOD1', 'BLUD', 2, 8, None, 'S_BLOOD2'),
    ('S_BLOOD2', 'BLUD', 1, 8, None, 'S_BLOOD3'),
    ('S_BLOOD3', 'BLUD', 0, 8, None, 'S_NULL'),
    ('S_PUFF1', 'PUFF', 32768, 4, None, 'S_PUFF2'),
    ('S_PUFF2', 'PUFF', 1, 4, None, 'S_PUFF3'),
    ('S_PUFF3', 'PUFF', 2, 4, None, 'S_PUFF4'),
    ('S_PUFF4', 'PUFF', 3, 4, None, 'S_NULL'),
    ('S_TBALL1', 'BAL1', 32768, 4, None, 'S_TBALL2'),
    ('S_TBALL2', 'BAL1', 32769, 4, None, 'S_TBALL1'),
    ('S_TBALLX1', 'BAL1', 32770, 6, None, 'S_TBALLX2'),
    ('S_TBALLX2', 'BAL1', 32771, 6, None, 'S_TBALLX3'),
    ('S_TBALLX3', 'BAL1', 32772, 6, None, 'S_NULL'),
    ('S_PLAY', 'PLAY', 0, -1, None, 'S_NULL'),
    ('S_PLAY_RUN1', 'PLAY', 0, 4, None, 'S_PLAY_RUN2'),
    ('S_PLAY_RUN2', 'PLAY', 1, 4, None, 'S_PLAY_RUN3'),
    ('S_PLAY_RUN3', 'PLAY', 2, 4, None, 'S_PLAY_RUN4'),
    ('S_PLAY_RUN4', 'PLAY', 3, 4, None, 'S_PLAY_RUN1'),
    ('S_PLAY_ATK1', 'PLAY', 4, 12, None, 'S_PLAY'),
    ('S_PLAY_ATK2', 'PLAY', 32773, 6, None, 'S_PLAY_ATK1'),
    ('S_PLAY_PAIN', 'PLAY', 6, 4, None, 'S_PLAY_PAIN2'),
    ('S_PLAY_PAIN2', 'PLAY', 6, 4, 'A_Pain', 'S_PLAY'),
    ('S_PLAY_DIE1', 'PLAY', 7, 10, None, 'S_PLAY_DIE2'),
    ('S_PLAY_DIE2', 'PLAY', 8, 10, 'A_PlayerScream', 'S_PLAY_DIE3'),
    ('S_PLAY_DIE3', 'PLAY', 9, 10, 'A_Fall', 'S_PLAY_DIE4'),
    ('S_PLAY_DIE4', 'PLAY', 10, 10, None, 'S_PLAY_DIE5'),
    ('S_PLAY_DIE5', 'PLAY', 11, 10, None, 'S_PLAY_DIE6'),
    ('S_PLAY_DIE6', 'PLAY', 12, 10, None, 'S_PLAY_DIE7'),
    ('S_PLAY_DIE7', 'PLAY', 13, -1, None, 'S_NULL'),
    ('S_PLAY_XDIE1', 'PLAY', 14, 5, None, 'S_PLAY_XDIE2'),
    ('S_PLAY_XDIE2', 'PLAY', 15, 5, 'A_XScream', 'S_PLAY_XDIE3'),
    ('S_PLAY_XDIE3', 'PLAY', 16, 5, 'A_Fall', 'S_PLAY_XDIE4'),
    ('S_PLAY_XDIE4', 'PLAY', 17, 5, None, 'S_PLAY_XDIE5'),
    ('S_PLAY_XDIE5', 'PLAY', 18, 5, None, 'S_PLAY_XDIE6'),
    ('S_PLAY_XDIE6', 'PLAY', 19, 5, None, 'S_PLAY_XDIE7'),
    ('S_PLAY_XDIE7', 'PLAY', 20, 5, None, 'S_PLAY_XDIE8'),
    ('S_PLAY_XDIE8', 'PLAY', 21, 5, None, 'S_PLAY_XDIE9'),
    ('S_PLAY_XDIE9', 'PLAY', 22, -1, None, 'S_NULL'),
    ('S_POSS_STND', 'POSS', 0, 10, 'A_Look', 'S_POSS_STND2'),
    ('S_POSS_STND2', 'POSS', 1, 10, 'A_Look', 'S_POSS_STND'),
    ('S_POSS_RUN1', 'POSS', 0, 4, 'A_Chase', 'S_POSS_RUN2'),
    ('S_POSS_RUN2', 'POSS', 0, 4, 'A_Chase', 'S_POSS_RUN3'),
    ('S_POSS_RUN3', 'POSS', 1, 4, 'A_Chase', 'S_POSS_RUN4'),
    ('S_POSS_RUN4', 'POSS', 1, 4, 'A_Chase', 'S_POSS_RUN5'),
    ('S_POSS_RUN5', 'POSS', 2, 4, 'A_Chase', 'S_POSS_RUN6'),
    ('S_POSS_RUN6', 'POSS', 2, 4, 'A_Chase', 'S_POSS_RUN7'),
    ('S_POSS_RUN7', 'POSS', 3, 4, 'A_Chase', 'S_POSS_RUN8'),
    ('S_POSS_RUN8', 'POSS', 3, 4, 'A_Chase', 'S_POSS_RUN1'),
    ('S_POSS_ATK1', 'POSS', 4, 10, 'A_FaceTarget', 'S_POSS_ATK2'),
    ('S_POSS_ATK2', 'POSS', 5, 8, 'A_PosAttack', 'S_POSS_ATK3'),
    ('S_POSS_ATK3', 'POSS', 4, 8, None, 'S_POSS_RUN1'),
    ('S_POSS_PAIN', 'POSS', 6, 3, None, 'S_POSS_PAIN2'),
    ('S_POSS_PAIN2', 'POSS', 6, 3, 'A_Pain', 'S_POSS_RUN1'),
    ('S_POSS_DIE1', 'POSS', 7, 5, None, 'S_POSS_DIE2'),
    ('S_POSS_DIE2', 'POSS', 8, 5, 'A_Scream', 'S_POSS_DIE3'),
    ('S_POSS_DIE3', 'POSS', 9, 5, 'A_Fall', 'S_POSS_DIE4'),
    ('S_POSS_DIE4', 'POSS', 10, 5, None, 'S_POSS_DIE5'),
    ('S_POSS_DIE5', 'POSS', 11, -1, None, 'S_NULL'),
    ('S_POSS_XDIE1', 'POSS', 12, 5, None, 'S_POSS_XDIE2'),
    ('S_POSS_XDIE2', 'POSS', 13, 5, 'A_XScream', 'S_POSS_XDIE3'),
    ('S_POSS_XDIE3', 'POSS', 14, 5, 'A_Fall', 'S_POSS_XDIE4'),
    ('S_POSS_XDIE4', 'POSS', 15, 5, None, 'S_POSS_XDIE5'),
    ('S_POSS_XDIE5', 'POSS', 16, 5, None, 'S_POSS_XDIE6'),
    ('S_POSS_XDIE6', 'POSS', 17, 5, None, 'S_POSS_XDIE7'),
    ('S_POSS_XDIE7', 'POSS', 18, 5, None, 'S_POSS_XDIE8'),
    ('S_POSS_XDIE8', 'POSS', 19, 5, None, 'S_POSS_XDIE9'),
    ('S_POSS_XDIE9', 'POSS', 20, -1, None, 'S_NULL'),
    ('S_POSS_RAISE1', 'POSS', 10, 5, None, 'S_POSS_RAISE2'),
    ('S_POSS_RAISE2', 'POSS', 9, 5, None, 'S_POSS_RAISE3'),
    ('S_POSS_RAISE3', 'POSS', 8, 5, None, 'S_POSS_RAISE4'),
    ('S_POSS_RAISE4', 'POSS', 7, 5, None, 'S_POSS_RUN1'),
    ('S_SPOS_STND', 'SPOS', 0, 10, 'A_Look', 'S_SPOS_STND2'),
    ('S_SPOS_STND2', 'SPOS', 1, 10, 'A_Look', 'S_SPOS_STND'),
    ('S_SPOS_RUN1', 'SPOS', 0, 3, 'A_Chase', 'S_SPOS_RUN2'),
    ('S_SPOS_RUN2', 'SPOS', 0, 3, 'A_Chase', 'S_SPOS_RUN3'),
    ('S_SPOS_RUN3', 'SPOS', 1, 3, 'A_Chase', 'S_SPOS_RUN4'),
    ('S_SPOS_RUN4', 'SPOS', 1, 3, 'A_Chase', 'S_SPOS_RUN5'),
    ('S_SPOS_RUN5', 'SPOS', 2, 3, 'A_Chase', 'S_SPOS_RUN6'),
    ('S_SPOS_RUN6', 'SPOS', 2, 3, 'A_Chase', 'S_SPOS_RUN7'),
    ('S_SPOS_RUN7', 'SPOS', 3, 3, 'A_Chase', 'S_SPOS_RUN8'),
    ('S_SPOS_RUN8', 'SPOS', 3, 3, 'A_Chase', 'S_SPOS_RUN1'),
    ('S_SPOS_ATK1', 'SPOS', 4, 10, 'A_FaceTarget', 'S_SPOS_ATK2'),
    ('S_SPOS_ATK2', 'SPOS', 32773, 10, 'A_SPosAttack', 'S_SPOS_ATK3'),
    ('S_SPOS_ATK3', 'SPOS', 4, 10, None, 'S_SPOS_RUN1'),
    ('S_SPOS_PAIN', 'SPOS', 6, 3, None, 'S_SPOS_PAIN2'),
    ('S_SPOS_PAIN2', 'SPOS', 6, 3, 'A_Pain', 'S_SPOS_RUN1'),
    ('S_SPOS_DIE1', 'SPOS', 7, 5, None, 'S_SPOS_DIE2'),
    ('S_SPOS_DIE2', 'SPOS', 8, 5, 'A_Scream', 'S_SPOS_DIE3'),
    ('S_SPOS_DIE3', 'SPOS', 9, 5, 'A_Fall', 'S_SPOS_DIE4'),
    ('S_SPOS_DIE4', 'SPOS', 10, 5, None, 'S_SPOS_DIE5'),
    ('S_SPOS_DIE5', 'SPOS', 11, -1, None, 'S_NULL'),
    ('S_SPOS_XDIE1', 'SPOS', 12, 5, None, 'S_SPOS_XDIE2'),
    ('S_SPOS_XDIE2', 'SPOS', 13, 5, 'A_XScream', 'S_SPOS_XDIE3'),
    ('S_SPOS_XDIE3', 'SPOS', 14, 5, 'A_Fall', 'S_SPOS_XDIE4'),
    ('S_SPOS_XDIE4', 'SPOS', 15, 5, None, 'S_SPOS_XDIE5'),
    ('S_SPOS_XDIE5', 'SPOS', 16, 5, None, 'S_SPOS_XDIE6'),
    ('S_SPOS_XDIE6', 'SPOS', 17, 5, None, 'S_SPOS_XDIE7'),
    ('S_SPOS_XDIE7', 'SPOS', 18, 5, None, 'S_SPOS_XDIE8'),
    ('S_SPOS_XDIE8', 'SPOS', 19, 5, None, 'S_SPOS_XDIE9'),
    ('S_SPOS_XDIE9', 'SPOS', 20, -1, None, 'S_NULL'),
    ('S_SPOS_RAISE1', 'SPOS', 11, 5, None, 'S_SPOS_RAISE2'),
    ('S_SPOS_RAISE2', 'SPOS', 10, 5, None, 'S_SPOS_RAISE3'),
    ('S_SPOS_RAISE3', 'SPOS', 9, 5, None, 'S_SPOS_RAISE4'),
    ('S_SPOS_RAISE4', 'SPOS', 8, 5, None, 'S_SPOS_RAISE5'),
    ('S_SPOS_RAISE5', 'SPOS', 7, 5, None, 'S_SPOS_RUN1'),
    ('S_TROO_STND', 'TROO', 0, 10, 'A_Look', 'S_TROO_STND2'),
    ('S_TROO_STND2', 'TROO', 1, 10, 'A_Look', 'S_TROO_STND'),
    ('S_TROO_RUN1', 'TROO', 0, 3, 'A_Chase', 'S_TROO_RUN2'),
    ('S_TROO_RUN2', 'TROO', 0, 3, 'A_Chase', 'S_TROO_RUN3'),
    ('S_TROO_RUN3', 'TROO', 1, 3, 'A_Chase', 'S_TROO_RUN4'),
    ('S_TROO_RUN4', 'TROO', 1, 3, 'A_Chase', 'S_TROO_RUN5'),
    ('S_TROO_RUN5', 'TROO', 2, 3, 'A_Chase', 'S_TROO_RUN6'),
    ('S_TROO_RUN6', 'TROO', 2, 3, 'A_Chase', 'S_TROO_RUN7'),
    ('S_TROO_RUN7', 'TROO', 3, 3, 'A_Chase', 'S_TROO_RUN8'),
    ('S_TROO_RUN8', 'TROO', 3, 3, 'A_Chase', 'S_TROO_RUN1'),
    ('S_TROO_ATK1', 'TROO', 4, 8, 'A_FaceTarget', 'S_TROO_ATK2'),
    ('S_TROO_ATK2', 'TROO', 5, 8, 'A_FaceTarget', 'S_TROO_ATK3'),
    ('S_TROO_ATK3', 'TROO', 6, 6, 'A_TroopAttack', 'S_TROO_RUN1'),
    ('S_TROO_PAIN', 'TROO', 7, 2, None, 'S_TROO_PAIN2'),
    ('S_TROO_PAIN2', 'TROO', 7, 2, 'A_Pain', 'S_TROO_RUN1'),
    ('S_TROO_DIE1', 'TROO', 8, 8, None, 'S_TROO_DIE2'),
    ('S_TROO_DIE2', 'TROO', 9, 8, 'A_Scream', 'S_TROO_DIE3'),
    ('S_TROO_DIE3', 'TROO', 10, 6, None, 'S_TROO_DIE4'),
    ('S_TROO_DIE4', 'TROO', 11, 6, 'A_Fall', 'S_TROO_DIE5'),
    ('S_TROO_DIE5', 'TROO', 12, -1, None, 'S_NULL'),
    ('S_TROO_XDIE1', 'TROO', 13, 5, None, 'S_TROO_XDIE2'),
    ('S_TROO_XDIE2', 'TROO', 14, 5, 'A_XScream', 'S_TROO_XDIE3'),
    ('S_TROO_XDIE3', 'TROO', 15, 5, None, 'S_TROO_XDIE4'),
    ('S_TROO_XDIE4', 'TROO', 16, 5, 'A_Fall', 'S_TROO_XDIE5'),
    ('S_TROO_XDIE5', 'TROO', 17, 5, None, 'S_TROO_XDIE6'),
    ('S_TROO_XDIE6', 'TROO', 18, 5, None, 'S_TROO_XDIE7'),
    ('S_TROO_XDIE7', 'TROO', 19, 5, None, 'S_TROO_XDIE8'),
    ('S_TROO_XDIE8', 'TROO', 20, -1, None, 'S_NULL'),
    ('S_TROO_RAISE1', 'TROO', 12, 8, None, 'S_TROO_RAISE2'),
    ('S_TROO_RAISE2', 'TROO', 11, 8, None, 'S_TROO_RAISE3'),
    ('S_TROO_RAISE3', 'TROO', 10, 6, None, 'S_TROO_RAISE4'),
    ('S_TROO_RAISE4', 'TROO', 9, 6, None, 'S_TROO_RAISE5'),
    ('S_TROO_RAISE5', 'TROO', 8, 6, None, 'S_TROO_RUN1'),
    ('S_SARG_STND', 'SARG', 0, 10, 'A_Look', 'S_SARG_STND2'),
    ('S_SARG_STND2', 'SARG', 1, 10, 'A_Look', 'S_SARG_STND'),
    ('S_SARG_RUN1', 'SARG', 0, 2, 'A_Chase', 'S_SARG_RUN2'),
    ('S_SARG_RUN2', 'SARG', 0, 2, 'A_Chase', 'S_SARG_RUN3'),
    ('S_SARG_RUN3', 'SARG', 1, 2, 'A_Chase', 'S_SARG_RUN4'),
    ('S_SARG_RUN4', 'SARG', 1, 2, 'A_Chase', 'S_SARG_RUN5'),
    ('S_SARG_RUN5', 'SARG', 2, 2, 'A_Chase', 'S_SARG_RUN6'),
    ('S_SARG_RUN6', 'SARG', 2, 2, 'A_Chase', 'S_SARG_RUN7'),
    ('S_SARG_RUN7', 'SARG', 3, 2, 'A_Chase', 'S_SARG_RUN8'),
    ('S_SARG_RUN8', 'SARG', 3, 2, 'A_Chase', 'S_SARG_RUN1'),
    ('S_SARG_ATK1', 'SARG', 4, 8, 'A_FaceTarget', 'S_SARG_ATK2'),
    ('S_SARG_ATK2', 'SARG', 5, 8, 'A_FaceTarget', 'S_SARG_ATK3'),
    ('S_SARG_ATK3', 'SARG', 6, 8, 'A_SargAttack', 'S_SARG_RUN1'),
    ('S_SARG_PAIN', 'SARG', 7, 2, None, 'S_SARG_PAIN2'),
    ('S_SARG_PAIN2', 'SARG', 7, 2, 'A_Pain', 'S_SARG_RUN1'),
    ('S_SARG_DIE1', 'SARG', 8, 8, None, 'S_SARG_DIE2'),
    ('S_SARG_DIE2', 'SARG', 9, 8, 'A_Scream', 'S_SARG_DIE3'),
    ('S_SARG_DIE3', 'SARG', 10, 4, None, 'S_SARG_DIE4'),
    ('S_SARG_DIE4', 'SARG', 11, 4, 'A_Fall', 'S_SARG_DIE5'),
    ('S_SARG_DIE5', 'SARG', 12, 4, None, 'S_SARG_DIE6'),
    ('S_SARG_DIE6', 'SARG', 13, -1, None, 'S_NULL'),
    ('S_SARG_RAISE1', 'SARG', 13, 5, None, 'S_SARG_RAISE2'),
    ('S_SARG_RAISE2', 'SARG', 12, 5, None, 'S_SARG_RAISE3'),
    ('S_SARG_RAISE3', 'SARG', 11, 5, None, 'S_SARG_RAISE4'),
    ('S_SARG_RAISE4', 'SARG', 10, 5, None, 'S_SARG_RAISE5'),
    ('S_SARG_RAISE5', 'SARG', 9, 5, None, 'S_SARG_RAISE6'),
    ('S_SARG_RAISE6', 'SARG', 8, 5, None, 'S_SARG_RUN1'),
    ('S_BAR1', 'BAR1', 0, 6, None, 'S_BAR2'),
    ('S_BAR2', 'BAR1', 1, 6, None, 'S_BAR1'),
    ('S_BEXP', 'BEXP', 32768, 5, None, 'S_BEXP2'),
    ('S_BEXP2', 'BEXP', 32769, 5, 'A_Scream', 'S_BEXP3'),
    ('S_BEXP3', 'BEXP', 32770, 5, None, 'S_BEXP4'),
    ('S_BEXP4', 'BEXP', 32771, 10, 'A_Explode', 'S_BEXP5'),
    ('S_BEXP5', 'BEXP', 32772, 10, None, 'S_NULL'),
    ('S_CLIP', 'CLIP', 0, -1, None, 'S_NULL'),
    ('S_SHOT', 'SHOT', 0, -1, None, 'S_NULL'),
)


@dataclass(frozen=True)
class State:
    name: str
    sprite: str
    frame: int                     # with FF_FULLBRIGHT
    tics: int                      # -1 = forever
    action: Optional[str]
    next: str

    @property
    def frame_index(self) -> int:
        return self.frame & FF_FRAMEMASK

    @property
    def fullbright(self) -> bool:
        return bool(self.frame & FF_FULLBRIGHT)


STATES: Dict[str, State] = {r[0]: State(*r) for r in _STATE_ROWS}
# The compact index the emitter and the schema use: position in DOOM's array order, S_NULL = 0.
# It fits one byte (asserted), which is the width of every state cell in the schema.
STATE_NAMES: Tuple[str, ...] = tuple(r[0] for r in _STATE_ROWS)
STATE_INDEX: Dict[str, int] = {n: i for i, n in enumerate(STATE_NAMES)}
S_NULL = "S_NULL"
assert STATE_NAMES[0] == S_NULL and len(STATE_NAMES) == len(STATES) <= 255


# ================================================================================================
# ACTIONS -- every action named by a state above. `domain`: which thinker runs it ("mobj" for
# things, "psprite" for the weapon). `cls` is what the K-slot scheduler charges (plan 6.1): a HEAVY
# action needs the monster's cells copied into the shared window, a CHEAP one runs in the monster's
# own slot. `phase`: where it is implemented -- S3a (this model), S3b (combat, next milestone),
# or "sound" (the action only plays a sound; there is no audio, so it does nothing).
# ================================================================================================
@dataclass(frozen=True)
class Action:
    name: str
    domain: str                   # "mobj" | "psprite"
    cls: str                      # "heavy" | "cheap" | "psprite"
    phase: str                    # "S3a" | "S3b" | "sound"
    doom: str                     # what DOOM does, in one line


ACTIONS: Dict[str, Action] = {a.name: a for a in (
    Action("A_Look", "mobj", "cheap", "S3a", "look for the player by sound and sight"),
    Action("A_Chase", "mobj", "heavy", "S3a", "turn, decide melee/missile, move or pick a dir"),
    Action("A_FaceTarget", "mobj", "heavy", "S3a", "turn to face the target, clear AMBUSH"),
    Action("A_PosAttack", "mobj", "heavy", "S3b", "zombieman hitscan"),
    Action("A_SPosAttack", "mobj", "heavy", "S3b", "shotgun guy: 3 hitscan pellets"),
    Action("A_TroopAttack", "mobj", "heavy", "S3b", "imp: claw in melee range, else fireball"),
    Action("A_SargAttack", "mobj", "heavy", "S3b", "demon bite"),
    Action("A_Explode", "mobj", "heavy", "S3b", "barrel radius damage"),
    Action("A_Pain", "mobj", "cheap", "sound", "pain sound"),
    Action("A_Scream", "mobj", "cheap", "sound", "death sound"),
    Action("A_XScream", "mobj", "cheap", "sound", "gib sound"),
    Action("A_PlayerScream", "mobj", "cheap", "sound", "player death sound"),
    Action("A_Fall", "mobj", "cheap", "S3a", "clear MF_SOLID: corpses do not block"),
    Action("A_WeaponReady", "psprite", "psprite", "S3b", "fire, switch or bob"),
    Action("A_Lower", "psprite", "psprite", "S3b", "lower for a switch"),
    Action("A_Raise", "psprite", "psprite", "S3b", "raise after a switch"),
    Action("A_ReFire", "psprite", "psprite", "S3b", "fire again while held"),
    Action("A_Punch", "psprite", "psprite", "S3b", "fist"),
    Action("A_FirePistol", "psprite", "psprite", "S3b", "pistol"),
    Action("A_FireShotgun", "psprite", "psprite", "S3b", "shotgun, 7 pellets"),
    Action("A_Saw", "psprite", "psprite", "S3b", "chainsaw"),
    Action("A_Light0", "psprite", "psprite", "S3b", "extralight 0"),
    Action("A_Light1", "psprite", "psprite", "S3b", "extralight 1"),
    Action("A_Light2", "psprite", "psprite", "S3b", "extralight 2"),
)}


# ================================================================================================
# MOBJINFO -- info.c `mobjinfo[]`, all 23 fields, for every E1M1 actor.
# ================================================================================================
@dataclass(frozen=True)
class MobjInfo:
    name: str
    doomednum: int
    spawnstate: str
    spawnhealth: int
    seestate: str
    seesound: str
    reactiontime: int
    attacksound: str
    painstate: str
    painchance: int
    painsound: str
    meleestate: str
    missilestate: str
    deathstate: str
    xdeathstate: str
    deathsound: str
    speed: int                     # monsters: map units per step; missiles: 16.16
    radius: int                    # 16.16
    height: int                    # 16.16
    mass: int
    damage: int
    activesound: str
    flags: int
    raisestate: str
    source: str = "info.c"

    def entry_states(self) -> Tuple[str, ...]:
        """Every state this type can be SET to from outside its own chains (a `0` in info.c is
        S_NULL, i.e. none)."""
        return tuple(s for s in (self.spawnstate, self.seestate, self.painstate, self.meleestate,
                                 self.missilestate, self.deathstate, self.xdeathstate,
                                 self.raisestate) if s != S_NULL)


def _mi(name, doomednum, spawnstate, spawnhealth, seestate, seesound, reactiontime, attacksound,
        painstate, painchance, painsound, meleestate, missilestate, deathstate, xdeathstate,
        deathsound, speed, radius, height, mass, damage, activesound, flags, raisestate,
        source="info.c"):
    # info.c writes "no state" as 0 in the melee/missile slots and S_NULL elsewhere
    z = lambda s: S_NULL if s in (0, "0") else s        # noqa: E731
    return MobjInfo(name, doomednum, z(spawnstate), spawnhealth, z(seestate), seesound,
                    reactiontime, attacksound, z(painstate), painchance, painsound, z(meleestate),
                    z(missilestate), z(deathstate), z(xdeathstate), deathsound, speed, radius,
                    height, mass, damage, activesound, flags, z(raisestate), source)


F = FRACUNIT
MOBJINFO: Dict[str, MobjInfo] = {m.name: m for m in (
    _mi("MT_PLAYER", -1, "S_PLAY", 100, "S_PLAY_RUN1", "sfx_None", 0, "sfx_None", "S_PLAY_PAIN",
        255, "sfx_plpain", S_NULL, "S_PLAY_ATK1", "S_PLAY_DIE1", "S_PLAY_XDIE1", "sfx_pldeth", 0,
        16 * F, 56 * F, 100, 0, "sfx_None",
        MF_SOLID | MF_SHOOTABLE | MF_DROPOFF | MF_PICKUP | MF_NOTDMATCH, S_NULL),
    _mi("MT_POSSESSED", 3004, "S_POSS_STND", 20, "S_POSS_RUN1", "sfx_posit1", 8, "sfx_pistol",
        "S_POSS_PAIN", 200, "sfx_popain", 0, "S_POSS_ATK1", "S_POSS_DIE1", "S_POSS_XDIE1",
        "sfx_podth1", 8, 20 * F, 56 * F, 100, 0, "sfx_posact",
        MF_SOLID | MF_SHOOTABLE | MF_COUNTKILL, "S_POSS_RAISE1"),
    _mi("MT_SHOTGUY", 9, "S_SPOS_STND", 30, "S_SPOS_RUN1", "sfx_posit2", 8, 0, "S_SPOS_PAIN",
        170, "sfx_popain", 0, "S_SPOS_ATK1", "S_SPOS_DIE1", "S_SPOS_XDIE1", "sfx_podth2", 8,
        20 * F, 56 * F, 100, 0, "sfx_posact", MF_SOLID | MF_SHOOTABLE | MF_COUNTKILL,
        "S_SPOS_RAISE1"),
    _mi("MT_TROOP", 3001, "S_TROO_STND", 60, "S_TROO_RUN1", "sfx_bgsit1", 8, 0, "S_TROO_PAIN",
        200, "sfx_popain", "S_TROO_ATK1", "S_TROO_ATK1", "S_TROO_DIE1", "S_TROO_XDIE1",
        "sfx_bgdth1", 8, 20 * F, 56 * F, 100, 0, "sfx_bgact",
        MF_SOLID | MF_SHOOTABLE | MF_COUNTKILL, "S_TROO_RAISE1"),
    _mi("MT_SERGEANT", 3002, "S_SARG_STND", 150, "S_SARG_RUN1", "sfx_sgtsit", 8, "sfx_sgtatk",
        "S_SARG_PAIN", 180, "sfx_dmpain", "S_SARG_ATK1", 0, "S_SARG_DIE1", S_NULL, "sfx_sgtdth",
        10, 30 * F, 56 * F, 400, 0, "sfx_dmact", MF_SOLID | MF_SHOOTABLE | MF_COUNTKILL,
        "S_SARG_RAISE1"),
    _mi("MT_SHADOWS", 58, "S_SARG_STND", 150, "S_SARG_RUN1", "sfx_sgtsit", 8, "sfx_sgtatk",
        "S_SARG_PAIN", 180, "sfx_dmpain", "S_SARG_ATK1", 0, "S_SARG_DIE1", S_NULL, "sfx_sgtdth",
        10, 30 * F, 56 * F, 400, 0, "sfx_dmact",
        MF_SOLID | MF_SHADOW | MF_SHOOTABLE | MF_COUNTKILL, "S_SARG_RAISE1"),
    _mi("MT_TROOPSHOT", -1, "S_TBALL1", 1000, S_NULL, "sfx_firsht", 8, "sfx_None", S_NULL, 0,
        "sfx_None", S_NULL, S_NULL, "S_TBALLX1", S_NULL, "sfx_firxpl", 10 * F, 6 * F, 8 * F, 100,
        3, "sfx_None", MF_NOBLOCKMAP | MF_MISSILE | MF_DROPOFF | MF_NOGRAVITY, S_NULL),
    _mi("MT_BARREL", 2035, "S_BAR1", 20, S_NULL, "sfx_None", 8, "sfx_None", S_NULL, 0,
        "sfx_None", S_NULL, S_NULL, "S_BEXP", S_NULL, "sfx_barexp", 0, 10 * F, 42 * F, 100, 0,
        "sfx_None", MF_SOLID | MF_SHOOTABLE | MF_NOBLOOD, S_NULL),
    _mi("MT_PUFF", -1, "S_PUFF1", 1000, S_NULL, "sfx_None", 8, "sfx_None", S_NULL, 0,
        "sfx_None", S_NULL, S_NULL, S_NULL, S_NULL, "sfx_None", 0, 20 * F, 16 * F, 100, 0,
        "sfx_None", MF_NOBLOCKMAP | MF_NOGRAVITY, S_NULL),
    _mi("MT_BLOOD", -1, "S_BLOOD1", 1000, S_NULL, "sfx_None", 8, "sfx_None", S_NULL, 0,
        "sfx_None", S_NULL, S_NULL, S_NULL, S_NULL, "sfx_None", 0, 20 * F, 16 * F, 100, 0,
        "sfx_None", MF_NOBLOCKMAP, S_NULL),
    _mi("MT_CLIP", 2007, "S_CLIP", 1000, S_NULL, "sfx_None", 8, "sfx_None", S_NULL, 0,
        "sfx_None", S_NULL, S_NULL, S_NULL, S_NULL, "sfx_None", 0, 20 * F, 16 * F, 100, 0,
        "sfx_None", MF_SPECIAL, S_NULL),
    _mi("MT_SHOTGUN", 2001, "S_SHOT", 1000, S_NULL, "sfx_None", 8, "sfx_None", S_NULL, 0,
        "sfx_None", S_NULL, S_NULL, S_NULL, S_NULL, "sfx_None", 0, 20 * F, 16 * F, 100, 0,
        "sfx_None", MF_SPECIAL, S_NULL, source="template"),
)}
del F

# The five monster types E1M1 spawns, by editor number.
MONSTER_DOOMEDNUMS: Dict[int, str] = {3004: "MT_POSSESSED", 9: "MT_SHOTGUY", 3001: "MT_TROOP",
                                      3002: "MT_SERGEANT", 58: "MT_SHADOWS"}
# What a kill drops (p_inter.c P_KillMobj: MT_POSSESSED -> MT_CLIP, MT_SHOTGUY -> MT_SHOTGUN).
DROPS: Dict[str, str] = {"MT_POSSESSED": "MT_CLIP", "MT_SHOTGUY": "MT_SHOTGUN"}


# ================================================================================================
# THING_TYPES -- every editor number in E1M1's THINGS lump (all skills, single player), with what
# thing-thing blocking needs: radius (map units) and flags. See the module docstring for sources.
# ================================================================================================
@dataclass(frozen=True)
class ThingType:
    doomednum: int
    name: str                      # MT_ name, or the GZDoom class name for decor
    radius: int                    # map units
    flags: int
    source: str                    # "info.c" | "template" | "gzdoom"

    @property
    def solid(self) -> bool:
        return bool(self.flags & MF_SOLID)


def _tt_from_info(mt: str) -> ThingType:
    m = MOBJINFO[mt]
    return ThingType(m.doomednum, mt, m.radius >> FRACBITS, m.flags, m.source)


THING_TYPES: Dict[int, ThingType] = {t.doomednum: t for t in (
    *(_tt_from_info(mt) for mt in ("MT_POSSESSED", "MT_SHOTGUY", "MT_TROOP", "MT_SERGEANT",
                                   "MT_SHADOWS", "MT_BARREL", "MT_CLIP", "MT_SHOTGUN")),
    # pickups verified in info.c's visible part (MT_MISC0..MT_MISC18)
    ThingType(2018, "MT_MISC0", 20, MF_SPECIAL, "info.c"),
    ThingType(2019, "MT_MISC1", 20, MF_SPECIAL, "info.c"),
    ThingType(2014, "MT_MISC2", 20, MF_SPECIAL | MF_COUNTITEM, "info.c"),
    ThingType(2015, "MT_MISC3", 20, MF_SPECIAL | MF_COUNTITEM, "info.c"),
    ThingType(5, "MT_MISC4", 20, MF_SPECIAL | MF_NOTDMATCH, "info.c"),
    ThingType(2011, "MT_MISC10", 20, MF_SPECIAL, "info.c"),
    ThingType(2012, "MT_MISC11", 20, MF_SPECIAL, "info.c"),
    ThingType(2023, "MT_MISC13", 20, MF_SPECIAL | MF_COUNTITEM, "info.c"),
    ThingType(2048, "MT_MISC17", 20, MF_SPECIAL, "info.c"),
    ThingType(2010, "MT_MISC18", 20, MF_SPECIAL, "info.c"),
    # pickups past the visible part: the shared pickup template (radius 20, MF_SPECIAL)
    ThingType(2008, "shells", 20, MF_SPECIAL, "template"),
    ThingType(2049, "box of shells", 20, MF_SPECIAL, "template"),
    ThingType(2047, "energy cell", 20, MF_SPECIAL, "template"),
    ThingType(17, "cell charge pack", 20, MF_SPECIAL, "template"),
    ThingType(8, "backpack", 20, MF_SPECIAL, "template"),
    ThingType(2005, "chainsaw", 20, MF_SPECIAL, "template"),
    # decor: radius and MF_SOLID from GZDoom (vanilla values); corpses and gore are not solid
    ThingType(43, "TorchTree", 16, MF_SOLID, "gzdoom"),
    ThingType(47, "Stalagtite", 16, MF_SOLID, "gzdoom"),
    ThingType(48, "TechPillar", 16, MF_SOLID, "gzdoom"),
    ThingType(54, "BigTree", 32, MF_SOLID, "gzdoom"),
    ThingType(26, "LiveStick", 16, MF_SOLID, "gzdoom"),
    ThingType(2028, "Column", 16, MF_SOLID, "gzdoom"),
    ThingType(60, "NonsolidMeat4", 20, MF_SPAWNCEILING | MF_NOGRAVITY, "gzdoom"),
    ThingType(10, "GibbedMarine", 20, 0, "gzdoom"),
    ThingType(12, "GibbedMarineExtra", 20, 0, "gzdoom"),
    ThingType(15, "DeadMarine", 20, 0, "gzdoom"),
    ThingType(18, "DeadZombieMan", 20, 0, "gzdoom"),
    ThingType(19, "DeadShotgunGuy", 20, 0, "gzdoom"),
    ThingType(20, "DeadDoomImp", 20, 0, "gzdoom"),
    ThingType(21, "DeadDemon", 20, 0, "gzdoom"),
    ThingType(24, "Gibs", 20, 0, "gzdoom"),
)}
# Editor numbers P_SpawnMapThing never turns into a thing (player and deathmatch starts).
NOT_THINGS = frozenset({1, 2, 3, 4, 11})


# ================================================================================================
# WEAPONS -- d_items.c `weaponinfo[]` for the four weapons E1M1 offers in single player.
# ================================================================================================
@dataclass(frozen=True)
class WeaponInfo:
    weapon: int                    # WP_*
    name: str
    ammo: int                      # AM_*
    upstate: str
    downstate: str
    readystate: str
    atkstate: str
    flashstate: str


WEAPONINFO: Dict[int, WeaponInfo] = {w.weapon: w for w in (
    WeaponInfo(WP_FIST, "fist", AM_NOAMMO, "S_PUNCHUP", "S_PUNCHDOWN", "S_PUNCH", "S_PUNCH1",
               S_NULL),
    WeaponInfo(WP_PISTOL, "pistol", AM_CLIP, "S_PISTOLUP", "S_PISTOLDOWN", "S_PISTOL",
               "S_PISTOL1", "S_PISTOLFLASH"),
    WeaponInfo(WP_SHOTGUN, "shotgun", AM_SHELL, "S_SGUNUP", "S_SGUNDOWN", "S_SGUN", "S_SGUN1",
               "S_SGUNFLASH1"),
    WeaponInfo(WP_CHAINSAW, "chainsaw", AM_NOAMMO, "S_SAWUP", "S_SAWDOWN", "S_SAW", "S_SAW1",
               S_NULL),
)}


# ================================================================================================
# INTEGRITY -- what the host test checks, as a function so the test can run it on a MUTATED copy
# (the negative control) and see it fail.
# ================================================================================================
MAX_FINITE_TICS = 14   # the schema stores tics in one nibble with 15 meaning "forever" (DOOM's -1)
# States that CODE sets directly, outside any mobjinfo/weaponinfo entry point:
#   p_pspr.c A_FirePistol / A_FireShotgun: P_SetMobjState (player->mo, S_PLAY_ATK2)
CODE_ENTRY_STATES: Dict[str, str] = {"S_PLAY_ATK2": "mobj"}


def check_integrity(states: Mapping[str, State] = None, infos: Mapping[str, MobjInfo] = None,
                    weapons: Mapping[int, WeaponInfo] = None,
                    actions: Mapping[str, Action] = None) -> List[str]:
    """[] when the tables are a closed, well-formed graph; else one line per defect:
      * every state's `next` exists; every action is a known Action;
      * every mobjinfo entry point and every weaponinfo state exists;
      * a state's action belongs to the domain that reaches it (a weapon state never runs a mobj
        action and vice versa);
      * finite tics fit the schema's nibble (0..MAX_FINITE_TICS) and -1 is the only negative;
      * every state except S_NULL is reachable from some entry point (nothing dead was copied)."""
    states = STATES if states is None else states
    infos = MOBJINFO if infos is None else infos
    weapons = WEAPONINFO if weapons is None else weapons
    actions = ACTIONS if actions is None else actions
    bad = []
    if S_NULL not in states:
        bad.append("S_NULL missing")
    for n, st in states.items():
        if st.next not in states:
            bad.append("%s: next %s does not exist" % (n, st.next))
        if st.action is not None and st.action not in actions:
            bad.append("%s: unknown action %s" % (n, st.action))
        if st.tics < -1 or st.tics > MAX_FINITE_TICS:
            bad.append("%s: tics %d outside -1..%d" % (n, st.tics, MAX_FINITE_TICS))
    roots_mobj, roots_psp = [], []
    for mt, mi in infos.items():
        for s in mi.entry_states():
            if s not in states:
                bad.append("%s: entry state %s does not exist" % (mt, s))
            else:
                roots_mobj.append(s)
    for s, dom in CODE_ENTRY_STATES.items():
        if s not in states:
            bad.append("code entry state %s does not exist" % s)
        else:
            (roots_mobj if dom == "mobj" else roots_psp).append(s)
    for w in weapons.values():
        for s in (w.upstate, w.downstate, w.readystate, w.atkstate, w.flashstate):
            if s == S_NULL:
                continue
            if s not in states:
                bad.append("weapon %s: state %s does not exist" % (w.name, s))
            else:
                roots_psp.append(s)

    def closure(roots):
        seen, stack = set(), list(roots)
        while stack:
            s = stack.pop()
            if s in seen or s not in states:
                continue
            seen.add(s)
            stack.append(states[s].next)
        return seen

    mobj_set, psp_set = closure(roots_mobj), closure(roots_psp)
    for s in mobj_set:
        a = states[s].action
        if a is not None and a in actions and actions[a].domain != "mobj":
            bad.append("%s: reached by a thing but runs %s action %s" % (s, actions[a].domain, a))
    for s in psp_set:
        a = states[s].action
        if a is not None and a in actions and actions[a].domain != "psprite":
            bad.append("%s: reached by a weapon but runs %s action %s" % (s, actions[a].domain, a))
    orphans = sorted(set(states) - mobj_set - psp_set - {S_NULL})
    for s in orphans:
        bad.append("%s: unreachable from any entry point" % s)
    return bad


assert not check_integrity(), check_integrity()
