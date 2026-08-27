"""H5 — reference model / oracle (M9). The host-side **exact-integer** golden renderer + sim (D12):
the test oracle every fj-program milestone (M11+) diffs against, byte-for-byte.

It composes only the **shared** integer kernels — `tables.py` (finesine), `fixedpoint.py` (signed
Q-format mul), `mapcompiler.py` (the built BSP + its `_point_side` geometry), `config.py` (the
resolution SSOT), and the WAD's own COLORMAP — so the oracle and the program cannot drift (R6).
Nothing here re-derives a constant or a formula that already lives in one of those modules.

M9 is the smallest honest cut (it grows as F5 features land, per the ladder):
  * `step_sim`  — turn (BAM add) + collision-free move (FixedMul against the finesine table). S0's
    line-based collision lands at M14; until then a step is pure turn/translate.
  * `point_in_subsector` — R_PointInSubsector: the permanent BSP point-location primitive (signed
    side tests, DOOM right=front convention) shared by both the sim and the renderer.
  * `render_frame` — the spawn frame: a colormap-shaded ceiling/floor background at the sub-sector's
    sector light. With no walls/visplanes yet (M12/M13) an empty view IS this two-band clear; walls
    will overwrite columns later. The band base indices are placeholders (CEIL_BG/FLOOR_BG) until
    real flats land — refining them only re-blesses the goldens off this oracle, which is the point.

Angles are BAM (binary angle measurement: a full turn = 2**32). The finesine table is indexed by the
top log2(TRIG_N) bits (ANGLE_TO_FINE_SHIFT, config-derived — never a literal 20/12), and cosine
shares the sine table at +TRIG_N/4 (the M6 idiom). Player position is the only genuine 16.16 quantity
(§1.1.4); BSP side tests truncate it to 16.0 integer map coords.
"""
from __future__ import annotations

import hashlib
import dataclasses
from dataclasses import dataclass, replace

from doomfj.config import Config, PNEAR_SEG_BUDGET
from doomfj.fixedpoint import fixed_mul, fixed_div, _signed  # shared signed Q-format kernels (R6)
from doomfj.mapcompiler import (  # shared geometry (R6)
    NF_SUBSECTOR, CompiledMap, bake_bsp, _point_side, seg_affine_coeffs,
    bbox_gate_boxes, bbox_wedge_miss, wedge_planes_bam, seg_sector,
    thing_live_subsectors, blockmap_candidates,
)
from doomfj.things import (baked_thing_mask, drawable_things,   # M14.5: the split SSOT (R6)
                           vanishable_slots)
from doomfj.tables import (
    sine_table, tantoangle_table, viewangletox_table, xtoviewangle_table, finetangent_table,
    yslope_table, zlight_table, scalelight_table, distscale_table, LIGHTLEVELS, LIGHTSEGSHIFT,
    MAXLIGHTSCALE, MAXLIGHTZ, LIGHTZSHIFT, LIGHTSCALESHIFT,
    slopediv_recip_table, SLOPEDIV_RECIP_RK,
)
from doomfj.texturecompiler import (  # shared D5 downscale lever + texture compositing (R6/D12)
    downscale_canvas, composite_texture, texture_texels,
)
from doomfj.wad import WadFile, decode_picture

# ── sim / angle constants (BAM: full turn = 2**32) ──
FULL_CIRCLE = 1 << 32
ANGLE_MASK = FULL_CIRCLE - 1      # wrap BAM arithmetic to unsigned 32-bit
ANG90 = FULL_CIRCLE // 4          # 0x40000000 — 90deg, sanity anchor for the trig index
ANG180 = FULL_CIRCLE // 2         # 0x80000000
ANG270 = 3 * (FULL_CIRCLE // 4)   # 0xC0000000
ANG45 = FULL_CIRCLE // 8          # 0x20000000
CLIPANGLE = ANG45                 # half the 90° FOV — the view frustum's edge angle (R_AddLine clip)
SLOPERANGE = 2048                 # R_PointToAngle slope quotient range (DOOM SLOPERANGE); tantoangle has +1
DBITS = 5                          # FRACBITS(16) - SLOPEBITS(11): the FixedDiv→tantoangle index shift (R_PointToDist)
SCALE_MIN = 256                    # R_ScaleFromGlobalAngle clamp floor (16.16)
SCALE_MAX = 64 << 16               # R_ScaleFromGlobalAngle clamp ceiling = 64.0 (16.16)
VIEWHEIGHT = 41                    # DOOM player eye height above the floor (map units)
FORWARD_MOVE = 50 << 16           # 16.16 map-units per tic (DOOM run forwardmove 0x32); S0 magnitude
ANGLE_TURN = 640 << 16            # BAM per tic (DOOM angleturn[]); turn-left adds, turn-right subtracts

# ── M14-d: line collision (P_CheckPosition / PIT_CheckLine) ───────────────────────────────────
PLAYER_RADIUS = 16 << 16          # MT_PLAYER radius, 16.16 (the half-width of the collision box)
PLAYER_HEIGHT = 56 << 16          # MT_PLAYER height -- an opening shorter than this blocks
MAX_STEP = 24 << 16               # P_TryMove: a floor more than 24 units up is a wall, not a step
ML_BLOCKING = 0x0001              # linedef flag: blocks everything, two-sided or not

# ── render: placeholder band base indices (until real flats/visplanes, M13 / wall textures) ──
CEIL_BG = 0                       # ceiling band palette index (pre-colormap)
FLOOR_BG = 96                     # floor band palette index (pre-colormap)
WALL_BG = 4                       # flat-shaded wall palette index (pre-colormap) until textures land
WPX_RUN_CAP = 24                  # M13-WPX: max colour runs per 1x1 wall column (ops + bank knob)
WPX_U_SCALE = 768                 # M13-WPX: u = scale//h -- the free perspective-shaped h->texture-column map
WALL_NOISE_BITS = 2               # V1: colormap steps the per-column grain may darken by (0..3)
STEP_SEG_BUDGET = 8              # V3: boundaries allowed a step face (the NEAREST ones)
V5_STACK = 2                      # V5: stacked boundary pieces kept per column per side
STEP_FACE_BASE = 96               # V3: flat-shaded step-face texel. NOT WALL_BG (=4),
                                  # which is near-WHITE in DOOM's ramp and blows out
# V2: sky-texture widths swept per full 360 turn. A LOOK knob, but not a free one -- it sets the
# BAM shift, and fj only shifts cheaply by whole NIBBLES. With tw=128, shift = 32-7-log2(TURN), so
# TURN=2 gives 24 (exactly 6 nibbles, one `hex.shr_hex 8, 6`) while TURN=4 gives 23 and would cost a
# bit-shift chain per frame. Pick the knob that lands on a nibble.
SKY_TURN = 2

# ── V4 THINGS ────────────────────────────────────────────────────────────────────────────────────
# One frame, one rotation per thing type -- enough to make the level's 292 things VISIBLE, which is
# what the feature is for. The fj bakes a run-list per (sprite, texture column, height BUCKET), so
# both of those bounds matter to the bank size, not just to the look.
THING_SPRITE = {
    2014: "BON1", 2015: "BON2", 2035: "BAR1", 47: "SMIT", 3001: "TROO", 2008: "SHEL",
    54: "TRE2", 9: "SPOS", 43: "TRE1", 3004: "POSS", 3002: "SARG", 2010: "ROCK",
    2028: "COLU", 2011: "STIM", 2012: "MEDI", 2018: "ARM1", 2019: "ARM2", 2001: "SHOT",
    2002: "MGUN", 2005: "CSAW", 2006: "BFUG", 2003: "LAUN", 2004: "PLAS", 2013: "SOUL",
    2022: "PINV", 2023: "PSTR", 2024: "PINS", 2025: "SUIT", 2026: "PMAP", 2045: "PVIS",
    2007: "CLIP", 2048: "AMMO", 2046: "BROK", 2047: "CELL", 2049: "SBOX", 8: "BPAK",
    34: "CAND", 35: "CBRA", 44: "TBLU", 45: "TGRN", 46: "TRED", 55: "SMBT", 56: "SMGT",
    57: "SMRT", 48: "ELEC", 30: "COL1", 31: "COL2", 32: "COL3", 33: "COL4", 36: "COL5",
    37: "COL6", 41: "CEYE", 42: "FSKU", 49: "GOR1", 50: "GOR2",
    58: "SARG",                   # the SPECTRE. DOOM draws it as a fuzzed SARG; there is no fuzz
                                  # here, so it renders as a plain demon -- which is a great deal
                                  # better than the previous behaviour, where the one spectre in
                                  # E1M1 had no sprite mapping at all and was silently invisible.
}
SPRITE_HEIGHT_BUCKETS = 32        # V4: on-screen heights the sprite bank bakes a run-list for.
                                  # ~700 (sprite, downscaled column) blocks x 101 EXACT heights (the
                                  # WPX wall bank's shape) would be ~17M characters against a program
                                  # already at 36M and an assembler that is ~cubic. 32 buckets is 3px
                                  # of quantisation on a full-height sprite and 1/3 the bank.
SPRITE_MINZ = 4 << 16             # DOOM's MINZ: nearer than this the projection blows up
SPRITE_RUN_CAP = 12               # colour runs per baked sprite column (as WPX_RUN_CAP is for walls)
SPRITE_HD_H = 40                  # V4-HD: buckets at least this tall bake from FULL-RES art with
SPRITE_RUN_CAP_HD = 24            # a deeper run cap -- near sprites were visibly blocky at cap 12
                                  # over 2x-downscaled texels (the owner's "closer sprites seem
                                  # very pixelated"). Vertical only: u stays downscaled.
DEG_SPR_NEAR_TZ = 384             # SPR-NEAR (owner, 2026-08-05): the DETAIL RADIUS in map
                                  # units. A sprite nearer than this ALWAYS bakes full detail,
                                  # however short it projects (a potion at your feet is small
                                  # on screen but deserves its pixels); the coarse low-res cap
                                  # applies only to things both SHORT and beyond this radius.
DEG_SPR_MID_CAP = 12              # (owner, 2026-08-04: cap 8 was "too much" -- mid sprites keep
                                  # the full 12-run bake) the MIDDLE buckets (between low-res and HD
                                  # tiers) bake at this cap instead of SPRITE_RUN_CAP(12) --
                                  # mid-distance sprites get slightly coarser color runs.
                                  # ⚠ read at CALL time (a `cap=SPRITE_RUN_CAP` signature
                                  # default binds at import and is NOT knob-patchable -- R49).
DEG_SPR_LOWRES_H = 32             # 20M-RECOVERY (owner, 2026-08-04: "far sprites can be a bit
DEG_SPR_LOWRES_CAP = 4            # more color-inaccurate"): buckets SHORTER than this bake with
                                  # this run cap instead of SPRITE_RUN_CAP -- a far monster
                                  # becomes a 2-3 colour silhouette at the right shape and size.
                                  # BAKE-ONLY: the emit just walks fewer pairs; no new runtime.
MIN_SPRITE_H = 3                  # V4: a SCENERY sprite shorter than this on screen is not drawn.
                                  # EXP-7 rejects the depth past which a sprite projects to ZERO
                                  # rows; this is the same one compare with a bigger constant, and
                                  # it is the RIGHT knob -- a 1-2px speck is not a monster, it is a
                                  # coloured pixel, and paying ~47k ops for it while a real monster
                                  # loses its budget slot is the trade EXP-8a caught us making.
                                  # ⚠ The per-sprite tz thresholds fj compares against are NOT the
                                  # analytic wph*PROJECTION/MIN_SPRITE_H -- the block-FP reciprocal
                                  # puts the true boundary up to a whole map unit either side, so
                                  # `sprite_tz_min_size` SCANS for it (scratchpad/minsize_verify.py
                                  # proves the scanned bound exact for MIN_SPRITE_H 2, 3 and 4).
MIN_SPRITE_H_MONSTER = 1          # ... but a MONSTER is never dropped for being small: it keeps
                                  # EXP-7's bound (drawn while it projects at least one row). The
                                  # threshold is baked PER THING, so splitting it by category costs
                                  # exactly zero ops -- a different constant in the same compare.
                                  # This is the whole policy: scenery thins out with distance, the
                                  # things that shoot back never do.
MONSTER_TYPES = frozenset({7, 9, 16, 58, 64, 65, 66, 67, 68, 69, 71, 84, 88,
                           3001, 3002, 3003, 3004, 3005, 3006})

# ── M14.5: WHAT CAN VANISH ────────────────────────────────────────────────────────────────────
# A thing baked into its leaf is CODE, so the only way it ever stops being drawn is a runtime flag.
# These are the types that DOOM removes from the world while the level runs -- everything the
# player picks up, plus the barrel (destroyed). Everything else on this map (trees, columns,
# candles, gore, techno-pillars) is scenery that stands for the whole level and needs no flag,
# which is why the flag is per-TYPE-class and not universal: a guard nothing can ever clear is
# pure cost. See `doomfj.things.vanishable_slots` and handoff-m14_5.md section 3.3.
VANISHABLE_TYPES = frozenset({
    2018, 2019,                             # ARM1 ARM2  armor
    2011, 2012, 2013, 2014, 2015,           # STIM MEDI SOUL BON1 BON2  health + bonuses
    2022, 2023, 2024, 2025, 2026, 2045,     # PINV PSTR PINS SUIT PMAP PVIS  powerups
    2001, 2002, 2003, 2004, 2005, 2006,     # SHOT MGUN LAUN PLAS CSAW BFUG  weapons
    2007, 2008, 2010, 2046, 2047, 2048, 2049, 8,   # CLIP SHEL ROCK BROK CELL AMMO SBOX BPAK
    5, 6, 13, 38, 39, 40,                   # the keys (none drawable on E1M1 today; harmless)
    2035,                                   # BAR1  the barrel -- destroyed, not picked up
})

# ── THE 25M PACKAGE (owner goal, 2026-08-14) — A DELIBERATE PICTURE CHANGE ─────────────────────
#
# MEASURED, and this constant exists only because the measurement forced it. The whole sprite bill
# is 14,352,586 ops at the median — 41% of the frame — because the walk LOADS ~71 things per frame
# at 69,130 ops each to accept 6: 94.1% are rejected AFTER being loaded. Removing every sprite
# takes the median from 35,293,677 to 20,941,091 (scratchpad/sweep_base_nothings.csv, gated
# byte-exact at four viewpoints). No picture-neutral lever remains that can close a 10.3M gap —
# the base renderer alone is 28.19M against a 25M ceiling (docs/handoff-perf.md §4) — so the band
# is reachable ONLY through sprites, and it needs ~72% of them gone. Cost tracks COUNT, because
# the reject rate barely varies with what is dropped.
#
# The line is drawn where this file already draws it (see MONSTER_TYPES: "scenery thins out with
# distance, the things that shoot back never do"): MONSTERS STAY, everything else goes — 53 of
# E1M1's 251 drawable things kept, 198 dropped (60 pure scenery, 52 bonus dots, 22 barrels, 64
# pickups).
#
# ⚠ SET THIS TO frozenset() TO RESTORE EVERY SPRITE. It is ONE constant because THING_SPRITE is
# the SSOT all three drawable filters read — the oracle's `_drawable`, the emitter's `thing_rows`,
# and every gate/sweep's DRAWABLE — so the two mirrors cannot drift apart on it. That is exactly
# what handoff-perf.md §7.1 demands of a sprite cut: one data change, both mirrors, one commit.
THING_SPRITE_ALL = THING_SPRITE          # the full table, kept so the before/after sheet can
                                         # render what the cut removes (scratchpad/spr25_sheet.py)
# KEPT ALONGSIDE THE MONSTERS (owner, 2026-08-14, ceiling raised to 27M). The headroom above the
# monsters-only 25,853,174 is 1,146,826 ops, and the set below was CHOSEN BY MEASUREMENT rather
# than by count: `scratchpad/m14_class_cost.py` counts, per class, how many (frame, thing) LOADS it
# causes over the sweep's 260 frames — i.e. how often the walk reaches its leaf before `full`
# latches. Cost tracks THAT, not sprite size, so a class of one prop in a corridor nobody looks
# down is ~22k ops/frame while 30 bonus dots in the open courtyard are 1.4M.
#
# ⚠ THE PROXY UNDERSTATES, AND IT WAS MEASURED DOING SO. The load count ignores that an ACCEPTED
# thing also DRAWS, so mid-size classes cost more than their loads suggest. Barrels + these six
# were predicted at 932,100 and measured at 1,558,963 (median 25,853,174 -> 27,412,137): actual =
# proxy x 1.673. ⇒ THE 22 BARRELS ALONE ARE ~1.34M AGAINST A 1,146,826 BUDGET AND DO NOT FIT AT
# 27M. They are the thing to buy back first if the ceiling ever rises.
#
# So the set is the classes whose things are small and rarely reached, where proxy ~ actual:
#   BPAK PSTR SOUL CSAW PLAS CELL  1 each   21,840-46,280   distinctive one-off pickups
#   SHOT  4                                    153,140
#   MEDI  5                                    210,080
#   proxy 582,140 x 1.673 = ~974k  =>  ~26.83M, inside 27M with margin held for the ratio.
#
# Deliberately out: BAR1 (see above), BON1/BON2 (52 bonus dots, 5.6M — the most expensive thing on
# the map and sub-pixel at most distances), SHEL/SMIT/TRE1/TRE2 (bulk classes, 0.7-1.1M each).
SPRITE_KEEP_EXTRA = frozenset({
    8, 2023, 2013, 2005, 2004, 2047,     # BPAK PSTR SOUL CSAW PLAS CELL, 1 each
    2001,                                # SHOT  shotgun, 4
    2012,                                # MEDI  medikit, 5
})
# ── M14.5: EVERY SPRITE COMES BACK (owner, 2026-08-14: "anyway i want to use all sprites") ──────
#
# The cut above was forced by a measurement that no longer holds. It priced 198 sprites on the
# RUNTIME path, where a thing costs a table read, a position read, a binding and a list insert every
# frame. M14.5 bakes any thing no monster shares a leaf with -- 176 of those 198 -- back into its
# leaf as compile-time constants, which is where they were before M14-e and roughly half the price
# (docs/handoff-m14_5.md section 0). So the set is restored in full and the ceiling moves to
# whatever it measures; the sprite question closes and the base renderer's 20,941,091 becomes the
# thing standing between this and the 12-25M target.
#
# ⚠ THE CUT'S OWN CONSTANT IS KEPT, not deleted: `SPRITE_KEEP_EXTRA` and the reasoning above it are
# the record of how the 27M package was chosen, and re-cutting is one edit if a ceiling ever
# demands it. Restoring is this one line.
DROPPED_SPRITE_TYPES = frozenset()
THING_SPRITE = {k: v for k, v in THING_SPRITE_ALL.items() if k not in DROPPED_SPRITE_TYPES}
MONSTER_BUDGET = 255              # V4: NO COUNT LIMIT (owner, 2026-08-01). 255 is the widest value
                                  # the 2-nibble `n_mon`/`n_thing` counters hold, and E1M1's heaviest
                                  # viewpoint projects 52 things, so neither budget can bind -- what
                                  # a frame draws is decided ENTIRELY by distance now, via the
                                  # per-thing min-size reject. The counters and their compares stay:
                                  # they cost ~one test per thing, and they are the backstop that
                                  # keeps a pathological map from unbounded per-frame work.
                                  # ⚠ Both are kept SEPARATE deliberately. If a limit is ever needed
                                  # again, lowering THING_BUDGET alone thins scenery without ever
                                  # touching monsters -- which is the whole lesson of EXP-8a, where
                                  # one shared counter let six ONE-PIXEL bonus dots hold the frame's
                                  # slots while 24 monsters were turned away.
THING_BUDGET = 255                # V4: things PROJECTED per frame. Each pays ~47k fj ops (4 FixedMuls
                                  # + 2 FixedDivs), so this is the knob that bounds the feature the
                                  # way STEP_SEG_BUDGET bounds V3 -- and, as there, the walk is
                                  # front-to-back so what the budget drops is the FURTHEST things.
                                  # Was 16 (EXP-8); RETIRED as a count limit 2026-08-01 -- see
                                  # MONSTER_BUDGET above. Distance, not arrival order, decides.

# ── 25M-CAP (owner, 2026-08-03): load-adaptive degradation. Light frames render identically;
# once a frame is already heavy (the SOFT counters below have filled) the importance bar rises,
# so the frames in the sweep tail shed their least-visible work. All thresholds are ONE compare
# against a register/constant fj also holds -- exact-mirrorable, R6.
# 20M-RECOVERY (owner, 2026-08-04): these DEG constants were retuned as a SET so the
# sweep lands under 20M median AND mean after the two correctness features (sprite-stop
# fix + V5-DROP). Certified b_1b18612522b42204: median 19.96M / mean 19.74M / worst
# 39.08M. The ladder and the per-knob shares are in the session sheets (opt20_*).
DEG_SOFT_SCENERY = 3              # after this many accepted scenery things, scenery must project...
DEG_MINH2_SCENERY = 24            # ...at least this many rows (baseline MIN_SPRITE_H = 3)
DEG_SOFT_MON = 4                  # monsters keep their own, looser pair (the owner's policy:
DEG_MINH2_MON = 10                 # the things that shoot back thin LAST)
DEG_SPRB_MINH = 32                # slot-B (behind-sprite) fragments only for things at least this
                                  # tall on screen -- B slots under small/far overlaps are almost
                                  # always occluded by slot A (measured px-diff ~0)
DEG_SLIVER_W = 3                  # a wall whose whole projected span is <= this many columns
                                  # renders flat (no W1R pattern): 1-2 col horizon slivers
DEG_STACK_SCALE = 32768           # the SECOND stacked V5 piece only when the boundary's scale is
                                  # at least this (16.16: 16384 = tz <~ 320 map units). Near
                                  # stairs keep both risers; far doorways show one.
DEG_PNEAR = 4095                  # the marking-seg budget under degrade. SMUDGE FIX (owner's
                                  # (1698,892) phantom columns, 2026-08-09): any budget that can
                                  # BIND hands mid-screen columns to a far one-sided wall's
                                  # sector -- giant wrong-colour shafts (73 of 260 sweep frames
                                  # at the old 64; 17 still wrong at 256). 4095 = the 3-nibble
                                  # fj counter's max, and the EMITTER ASSERTS the map's total
                                  # seg count stays below it (n_ts counts a subset of segs), so
                                  # the budget provably never binds: attribution runs to its
                                  # natural stops (claim-complete / faces-spent / wall-drawn)
                                  # and the count survives only as the assembler-width fuse.
                                  # (CR-2026-08: an earlier 1024 claimed "never binds, < 731
                                  # segs" -- wrong on both counts: lite has 1378, stock 2057.)
DEG_LIP_SCALE = 16384             # V5-DROP far gate: LIP pieces (drop-offs / level flat changes)
                                  # only when the boundary's scale is at least this (16.16:
                                  # 16384 = tz <~ 320 map units, the stack gate's radius). A
                                  # farther drop edge projects to a sub-pixel line; skipping it
                                  # reclaims the lip cost where it cannot be seen. RISERS are
                                  # never lip-gated (they are the visible stairs). Knob-tunable.
DEG_HD_BUDGET = 0                 # OPTION B (0 = off): only the first N accepted TALL-bucket
                                  # things keep the V4-HD cap-24 full-res bake; later tall things
                                  # fall back to the cap-12 low-res blocks (a packed LD bank
                                  # region). Walk order makes the first N the nearest N.
DEG_DDA_FACES = 1                 # OPTION A (DEFAULT ON): step-face/stacked-piece rows advance by
                                  # a per-seg frac DDA (DOOM's topstep/bottomstep) instead of two
                                  # multiplies per column-side. BIT-EXACT by the mapmul identity
                                  # (frac accumulates mod 2^32, no shift -- zero pixel change,
                                  # verified 0 px on every probe + byte-exact gates). Measured on
                                  # the 260-frame sweep: median 17.19 -> 16.51M, mean -0.23M,
                                  # worst -1.0M. The per-seg setup loses ~0.5M on a few
                                  # narrow-face-seg gate frames but wins the distribution.


def sprite_bucket(h: int, view_h: int) -> int:
    """Which baked height bucket a sprite `h` screen pixels tall renders at."""
    return min(SPRITE_HEIGHT_BUCKETS - 1,
               max(0, ((h - 1) * SPRITE_HEIGHT_BUCKETS) // (view_h + 1)))


def sprite_bucket_height(b: int, view_h: int) -> int:
    """The exact pixel height bucket `b` renders at — the largest h that maps to it, so a sprite is
    never drawn SHORTER than the bucket below it and the ladder stays monotone."""
    hi = 1
    for h in range(1, view_h + 1):
        if sprite_bucket(h, view_h) == b:
            hi = h
    return hi


def _sky_shift(tw: int) -> int:
    """BAM bits to drop so a 32-bit angle indexes `tw` sky columns, `SKY_TURN` widths per turn."""
    return 32 - tw.bit_length() + 1 - SKY_TURN.bit_length() + 1
LIGHT_SHIFT = 3                   # sector light (0..255) -> colormap row (0..31): light >> 3
COLORMAP_LIGHTS = 32              # COLORMAP usable light rows (0..31; invuln/black sit past these)
_SLOPEDIV_RECIP = slopediv_recip_table()   # perf #13: shared block-FP reciprocal table for _slope_div


def _deg_to_bam(deg: int) -> int:
    """A THINGS angle (degrees) as BAM. 90deg -> 0x40000000 exactly (360 divides 2**32 evenly here)."""
    return round(deg / 360 * FULL_CIRCLE) % FULL_CIRCLE


@dataclass(frozen=True)
class SimState:
    """The player's world state. `x`/`y` are 16.16 (the only genuine 16.16 quantities, §1.1.4).

    ⚠ x/y are normalised to SIGNED 32-bit on construction, and that is not cosmetic. Most readers
    go through `_signed(state.x, 32)`, but the projection reads `state.x` RAW -- so before M14 a
    state built from `spawn_state` (signed, e.g. -27262976) and the mathematically equal state
    built from `step_sim`'s masked output (0xFE600000) rendered DIFFERENT FRAMES. Nothing had ever
    composed the two: every gate fed `SimState(vx << 16, ...)` by hand. M14's multi-frame gate is
    the first code to feed a simulated state back into the renderer, and it found this immediately
    -- 14,845 of 16,000 pixels, with the fj side blameless. Normalising here fixes it once for
    every caller rather than at each of the two raw reads.
    """
    x: int          # player position, 16.16 signed
    y: int          # 16.16 signed
    angle: int      # 32-bit BAM (modular: NOT normalised, 0 and 2**32 are the same angle anyway)
    level: str      # current level lump name

    def __post_init__(self):
        object.__setattr__(self, "x", _signed(self.x, 32))
        object.__setattr__(self, "y", _signed(self.y, 32))
        object.__setattr__(self, "angle", self.angle & 0xFFFFFFFF)


@dataclass(frozen=True)
class Scene:
    """The static data a frame is rendered against — the SAME inputs the program is built from (R6).
    `map_wad` carries geometry (VERTEXES/LINEDEFS/SIDEDEFS/SECTORS + the THINGS spawn + the baked
    SEGS/SSECTORS/NODES); `asset_wad` carries graphics (PLAYPAL/COLORMAP). `cmap` is the BSP baked
    once from those lumps by mapcompiler (H3).

    B2/DOORS: `sector_heights` is the ONE place a sector stops being static. It maps
    `sector index -> (floor_h, ceil_h)` and OVERRIDES the wad's values for that sector only.
    Everything else about the sector (textures, light, tag) is unchanged, and every sector not in
    the dict is the wad's, byte-for-byte — so a scene with no doors moving is bit-identical to one
    built before doors existed, which is what keeps every existing golden valid.

    M2-R4: `blocked_lines` is the collision half of a RUNTIME door. The emitted program bakes a
    door's opening at its OPEN height and marks its lines BLOCKING, then clears that bit with one
    `wflip` when the door reaches `doors.pass_state`. So the oracle is handed the same two facts:
    a scene whose door sectors are open, plus the set of linedefs that are still walls this frame.
    It lives on the Scene rather than in three signatures because `check_position`, `try_move` and
    `move_with_collision` would all have to grow the same argument and every caller pass it
    through -- and a mirror that is only right when every caller remembers is not a mirror."""
    map_wad: WadFile
    asset_wad: WadFile
    mapname: str
    cmap: CompiledMap
    sector_heights: dict | None = None
    blocked_lines: frozenset = frozenset()


def apply_sector_heights(secs, sector_heights):
    """THE door override, and there is exactly one of it.

    ⚠ B2/M2: the ORACLE applies it through `scene_sectors` and the EMITTER applies it to the one
    `map_wad.sectors()` read it makes, so if these two rounded, clamped or ordered differently the
    mirrors would disagree about where a door is — the exact failure this repo has paid for three
    times (M14-c, PJ-1, PJ-2). They call this.

    With no override the wad's own list comes back UNCHANGED (no copy, no allocation), so the
    door-free path is bit-identical to what it was before doors existed."""
    if not sector_heights:
        return secs
    out = list(secs)
    for idx, (floor_h, ceil_h) in sector_heights.items():
        out[idx] = dataclasses.replace(out[idx], floor_h=floor_h, ceil_h=ceil_h)
    return out


def scene_sectors(scene: Scene):
    """The level's SECTORS with any door override applied — the SSOT every reader must go through.

    ⚠ B2: there were FOUR independent `scene.map_wad.sectors(...)` reads in this file. A door that
    moved for three of them and not the fourth is precisely the class of bug this repo keeps paying
    for (M14-c, PJ-1, PJ-2: one mirror updated, its twin not). Route new readers through here.
    ⚠ With no override this returns the wad's own list UNCHANGED -- we add no copy and no
    allocation, so the door-free path is exactly what it was. (It is not the identical OBJECT
    across calls: `WadFile.sectors()` builds a fresh list each time. Checked, because the first
    version of this comment claimed identity and was wrong.)"""
    return apply_sector_heights(scene.map_wad.sectors(scene.mapname), scene.sector_heights)


def build_scene(map_wad: WadFile, asset_wad: WadFile, mapname: str,
                sector_heights: dict | None = None,
                blocked_lines: frozenset = frozenset()) -> Scene:
    """Bake the level's BSP once (from the WAD's NODES/SSECTORS/SEGS) and bundle the render inputs.

    ⚠ B2: `sector_heights` changes only SECTOR HEIGHTS. The BSP itself is baked from geometry that
    doors do not move (vertices, linedefs, the node tree), so a door opening does NOT invalidate
    `cmap` -- which is what makes doors affordable at all."""
    return Scene(map_wad, asset_wad, mapname, bake_bsp(map_wad, mapname), sector_heights,
                 frozenset(blocked_lines))


def spawn_state(wad: WadFile, mapname: str, *, player: int = 1) -> SimState:
    """The player-`player` start (THINGS type 1 = Player 1) as a SimState: pos<<16, angle as BAM."""
    th = next(t for t in wad.things(mapname) if t.type == player)
    return SimState(th.x << 16, th.y << 16, _deg_to_bam(th.angle), mapname)


def frame_hash(frame: bytes) -> str:
    """The per-frame sha256 the present layer logs (ScreenIO) — the bit-exact golden key (D12)."""
    return hashlib.sha256(frame).hexdigest()


def screen_frame_hash(indices, palette_rgb) -> str:
    """The device's per-frame sha256 (ScreenIO logs it per present, D12): sha256 over the raw palette
    indices followed by the palette RGB bytes. The golden key M11a+ diffs against."""
    return hashlib.sha256(bytes(indices) + bytes(palette_rgb)).hexdigest()


class ReferenceModel:
    """Holds the config + the shared finesine table (built once) and exposes the oracle entry points
    `step_sim(state, keys) -> state` and `render_frame(state, scene) -> bytes` (the H5 signatures)."""

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.sine = sine_table(self.cfg.TRIG_N, 16, 32)        # shared LUT values (R6)
        # finesine index = top log2(TRIG_N) bits of the BAM angle (config-derived, not a literal 20)
        self.angle_shift = 32 - (self.cfg.TRIG_N.bit_length() - 1)
        self.downscale = self.cfg.TEXTURE_DOWNSCALE   # the shared D5 factor (used once textures sample, M11b)
        self.tantoangle = tantoangle_table(SLOPERANGE)        # R_PointToAngle slope->BAM (M12b, shared R6)
        self.viewangletox = viewangletox_table(self.cfg.VIEW_W, self.cfg.TRIG_N)   # angle->column (M12c, R6)
        self.xtoviewangle = xtoviewangle_table(self.cfg.VIEW_W, self.cfg.TRIG_N)   # column->angle (M12h, R6)
        self.finetangent = finetangent_table(self.cfg.TRIG_N)   # tan(angle-90°) for texture-u (M12tex, R6)
        self.yslope = yslope_table(self.cfg.VIEW_W, self.cfg.VIEW_H)   # row -> distance slope (M13, R6)
        self.zlight = zlight_table(self.cfg.VIEW_W, COLORMAP_LIGHTS)   # (light,z) -> colormap row (M13, R6)
        self.scalelight = scalelight_table(self.cfg.VIEW_W, COLORMAP_LIGHTS)   # (light,scale) -> row, WALLS (M13-WPXLIGHT)
        self.distscale = distscale_table(self.cfg.VIEW_W, self.cfg.TRIG_N)  # col -> 1/cos fisheye (M13b, R6)
        self._tzmin_cache: dict = {}          # V4: scanned min-size depth bounds (sprite_tz_min_size)

    # ── trig (the M6 read_sin/read_cos idioms; cos shares the sine table at +N/4) ──
    def read_sin(self, angle: int) -> int:
        return self.sine[(angle >> self.angle_shift) & (self.cfg.TRIG_N - 1)]

    def read_cos(self, angle: int) -> int:
        idx = (angle >> self.angle_shift) + self.cfg.TRIG_N // 4
        return self.sine[idx & (self.cfg.TRIG_N - 1)]

    # finesine/finecosine indexed by an ALREADY-shifted fine index (R_MapPlane / R_ClearPlanes idiom)
    def _finesin_idx(self, idx: int) -> int:
        return self.sine[idx & (self.cfg.TRIG_N - 1)]

    def _finecos_idx(self, idx: int) -> int:
        return self.sine[(idx + self.cfg.TRIG_N // 4) & (self.cfg.TRIG_N - 1)]

    # ── projection angles (R_PointToAngle2, M12b) ──
    @staticmethod
    def _slope_div(num: int, den: int) -> int:
        """DOOM SlopeDiv: the tantoangle index for slope num/den (num <= den, both >= 0). Tuned for
        16.16 magnitudes — `den < 512` ⇒ the slope is ~0/clamped to SLOPERANGE.

        **perf #13 [re-bless]:** the exact `(num<<3)//(den>>8)` divide is replaced by a BLOCK-FP
        RECIPROCAL (the owner table-law form, NOT a naive 1/y table): normalize `sden = den>>8` to a
        top-3-nibble mantissa `m` with a nibble-exponent, `recip = slopediv_recip_table[m]` (= (1<<24)//m).

        **M13-coarseslope [re-bless, owner-approved ±1 column, 2026-07-26]:** the NUMERATOR is now
        normalized by the SAME shift as the denominator, truncating it to den's 3-nibble mantissa
        frame BEFORE the multiply — `wnum = (num >> (8+k)) << 3` (right-normalize) or
        `((num>>8) << k) << 3` (left-normalize) — so `ans = (wnum * recip) >> (RK-8)` needs only a
        3-nibble multiplier and a FIXED final shift (no per-exponent shift tree in fj). Precision:
        the extra num truncation costs ≤ 1/mantissa ≤ 1/256 of the slope ⇒ ≤ ~8 tantoangle-idx
        ⇒ ≤ 1 screen column (measured: max deviation 1 column over 73,600 real seg evaluations ×
        128 viewpoints; every golden-gate frame — square+E1M1, W1/flat AND textured — is PIXEL-
        IDENTICAL, scratchpad/coarse_gate_check.py). The fj `slope_div` macro mirrors THIS exactly
        (same table values via the <<3-prefolded `slopediv_recip8`, same integer steps) so they
        cannot drift (R6)."""
        if den < 512:
            return SLOPERANGE
        sden = den >> 8                                  # >= 2
        P = (sden.bit_length() - 1) // 4                 # leading-nibble index (0..4 for E1M1 magnitudes)
        if P >= 2:
            k = 4 * (P - 2)
            m = (sden >> k) & 0xFFF                      # top 3 nibbles (m in [0x100, 0xFFF])
            wnum = (num >> (8 + k)) << 3
        else:
            k = 4 * (2 - P)
            m = (sden << k) & 0xFFF                      # left-normalize small sden into 3 nibbles
            wnum = ((num >> 8) << k) << 3
        ans = (wnum * _SLOPEDIV_RECIP[m]) >> (SLOPEDIV_RECIP_RK - 8)
        return ans if ans <= SLOPERANGE else SLOPERANGE

    @staticmethod
    def _recip_div32(divisor: int) -> int:
        """perf #11 [re-bless]: (1<<32)//divisor via the SHARED slopediv_recip block-FP table — i.e.
        fixed_div(1<<16, divisor, 8, 4) without the divide. Used for the per-column `iscale = 1/scale`
        (the numerator 1<<32 is a power of 2, so the fj side is a pure shift of the reciprocal, no mul).
        `divisor` (the clamped, interpolated wall scale) is > 0. Same nibble-normalize + table as
        _slope_div; the fj column_setup mirrors this EXACTLY."""
        P = (divisor.bit_length() - 1) // 4
        if P >= 2:
            m = (divisor >> (4 * (P - 2))) & 0xFFF
            sh = SLOPEDIV_RECIP_RK + 4 * (P - 2)
        else:
            m = (divisor << (4 * (2 - P))) & 0xFFF
            sh = SLOPEDIV_RECIP_RK - 4 * (2 - P)
        return ((1 << 32) * _SLOPEDIV_RECIP[m]) >> sh

    def point_to_angle(self, x1: int, y1: int, x2: int, y2: int) -> int:
        """R_PointToAngle2: the BAM angle of the vector (x1,y1) -> (x2,y2). Octant fold + `tantoangle`
        lookup on the SlopeDiv quotient (the shared kernel, R6) — no atan at runtime. Coords are 16.16
        world units (the SlopeDiv tuning is scale-dependent). Returns a 32-bit BAM (East=0, North≈ANG90,
        with DOOM's ±1 octant-boundary quirks; e.g. due north = ANG90-1). The fj renderer matches this."""
        x, y = x2 - x1, y2 - y1
        if x == 0 and y == 0:
            return 0
        t = self.tantoangle
        if x >= 0:
            if y >= 0:
                return t[self._slope_div(y, x)] if x > y \
                    else (ANG90 - 1 - t[self._slope_div(x, y)]) & ANGLE_MASK
            y = -y
            return (-t[self._slope_div(y, x)]) & ANGLE_MASK if x > y \
                else (ANG270 + t[self._slope_div(x, y)]) & ANGLE_MASK
        x = -x
        if y >= 0:
            return (ANG180 - 1 - t[self._slope_div(y, x)]) & ANGLE_MASK if x > y \
                else (ANG90 + t[self._slope_div(x, y)]) & ANGLE_MASK
        y = -y
        return (ANG180 + t[self._slope_div(y, x)]) & ANGLE_MASK if x > y \
            else (ANG270 - 1 - t[self._slope_div(x, y)]) & ANGLE_MASK

    def angle_to_x(self, view_relative_angle: int) -> int:
        """Screen column for a view-relative BAM angle (0 = straight ahead, + = left, per the BAM/CCW
        convention). Index `viewangletox` at `(angle + ANG90) >> angle_shift`; the angle should already be
        clipped to the FOV [-ANG90, ANG90) by the wall path — out-of-range indices clamp to the table ends
        (DOOM's off-screen sentinels). Returns a column in [-1, VIEW_W+1]."""
        idx = ((view_relative_angle + ANG90) & ANGLE_MASK) >> self.angle_shift
        idx = max(0, min(len(self.viewangletox) - 1, idx))
        return self.viewangletox[idx]

    def point_to_dist(self, viewx: int, viewy: int, x: int, y: int) -> int:
        """R_PointToDist: the distance from (viewx,viewy) to (x,y) — `dist = dx / cos(atan(dy/dx))` =
        sqrt(dx²+dy²), computed via tantoangle + finesine + FixedDiv (no sqrt). Fold to the major octant
        (dx >= dy), index tantoangle by the FixedDiv slope >> DBITS, then divide dx by sin(angle+90°) =
        cos(angle). Coords + result are 16.16 (the FixedDiv tuning is scale-dependent). Exact for
        axis-aligned (dy=0 ⇒ dist=dx); ~quantization error off-axis. Returns 0 for the degenerate point."""
        dx, dy = abs(x - viewx), abs(y - viewy)
        if dy > dx:
            dx, dy = dy, dx
        if dx == 0:
            return 0
        idx = min((fixed_div(dy, dx, 8, 4) >> DBITS), SLOPERANGE)   # slope dy/dx in [0,1] -> [0,SLOPERANGE]
        angle = (self.tantoangle[idx] + ANG90) & ANGLE_MASK
        sine = self.read_sin(angle)                                 # sin(atan(slope)+90deg) = cos(atan(slope))
        return fixed_div(dx, sine, 8, 4) if sine else 0

    # ── wall scale (R_StoreWallRange setup + R_ScaleFromGlobalAngle, M12e) ──
    def wall_setup(self, viewx: int, viewy: int, seg, verts) -> tuple:
        """The per-wall projection setup (DOOM R_StoreWallRange): returns `(rw_normalangle, rw_distance)`.
        `rw_normalangle = seg.angle_BAM + ANG90` (the wall's normal — DOOM's native convention, valid now
        the segs are BAKED with DOOM-standard winding). `rw_distance` = the perpendicular view→wall-line
        distance, 16.16.

        **perf #9 [re-bless]:** rw_distance is now the AFFINE signed distance `|fixed_mul(a,viewx) +
        fixed_mul(b,viewy) + c|` using baked per-seg coeffs (`seg_affine_coeffs`, the shared SSOT) — the
        cross-product perpendicular distance — instead of `hyp·sin(distangle)` (point_to_angle + the
        two-divide point_to_dist + finesine). Same geometric quantity, but exact-affine with no atan/divide;
        the value differs from the old tantoangle-quantized divide path at the sub-bit level (verified
        sub-pixel downstream on E1M1 — a deliberate re-bless, not a divide). Front-facing segs (those that
        survive wall_x_range's span<ANG180 cull) give signed>0, so abs is a no-op; the pre-abs SIGN is what
        perf #10's back-face cull will test. `viewx/y` are 16.16; `verts` are 16.0."""
        rw_normalangle = ((seg.angle << 16) + ANG90) & ANGLE_MASK
        a, b, c = seg_affine_coeffs(seg, verts)
        signed = (fixed_mul(a, viewx, 8, 4) + fixed_mul(b, viewy, 8, 4) + c) & ANGLE_MASK
        rw_distance = abs(_signed(signed, 32))
        return rw_normalangle, rw_distance

    @staticmethod
    def _scale_recip_div(num_abs: int, den_abs: int) -> int:
        """M13-scalerecip [re-bless]: `(num_abs<<16) // den_abs` via the SHARED slopediv_recip
        block-FP table — the fj `proj.scale_recip_div` macro's integer recipe, bit for bit (R6):
        normalize den_abs to a 3-nibble mantissa (fsh counts whole nibbles, base 6 = RK/4), take the
        14-NIBBLE truncated product with recip[m], ONE whole-nibble shift, low 8 nibbles. 14 nibbles
        is the measured-exact width for real scale operands (12 truncates); precision vs the exact
        divide: 0.29% max relative over the 320 real spawn scale calls = sub-pixel wall-edge shift
        (<0.3px), re-blessed under the owner's 'game standards' rule."""
        # CR-2026-08: den_abs == 0 would spin the left-normalize loop forever -- fail loudly.
        # (This is the shared SSOT reciprocal kernel; every caller owns a nonzero denominator.)
        assert den_abs > 0, f"_scale_recip_div: den_abs must be positive, got {den_abs}"
        sden = den_abs
        fsh = 6
        while sden > 0xFFF:
            sden >>= 4
            fsh += 1
        while sden < 0x100:
            sden <<= 4
            fsh -= 1
        wnum = (num_abs << 16) & (16 ** 14 - 1)
        prod = (wnum * _SLOPEDIV_RECIP[sden & 0xFFF]) & (16 ** 14 - 1)
        return (prod >> (4 * fsh)) & 0xFFFFFFFF

    def scale_from_global_angle(self, visangle: int, viewangle: int,
                                rw_normalangle: int, rw_distance: int) -> int:
        """R_ScaleFromGlobalAngle: the wall's projected scale (16.16 pixels per world unit) for the screen
        column whose ABSOLUTE view angle is `visangle`. scale = PROJECTION·sin(angleb) / (rw_distance·
        sin(anglea)), where anglea = ANG90+(visangle-viewangle), angleb = ANG90+(visangle-rw_normalangle),
        PROJECTION = CENTERX<<16. Clamped to [SCALE_MIN, SCALE_MAX]. At the centre of a perpendicular wall
        (visangle=viewangle=rw_normalangle) this is exactly PROJECTION/rw_distance.

        **M13-scalerecip [re-bless, 2026-07-26]:** the signed `fixed_div` is re-expressed as a
        sign-split + `_scale_recip_div` on the magnitudes. A sign MISMATCH (negative true quotient)
        returns SCALE_MAX directly — PROVEN identical to the old unsigned-wraparound-then-clamp
        behavior (any negative 32-bit quotient's unsigned reading is in [2^31, 2^32-1], always above
        SCALE_MAX=0x400000, so it always clamped to SCALE_MAX). The fj macro mirrors this exactly."""
        anglea = (ANG90 + (visangle - viewangle)) & ANGLE_MASK
        angleb = (ANG90 + (visangle - rw_normalangle)) & ANGLE_MASK
        num = fixed_mul(self.cfg.PROJECTION << 16, self.read_sin(angleb), 8, 4)
        den = fixed_mul(rw_distance, self.read_sin(anglea), 8, 4)
        if den == 0:
            return SCALE_MAX
        sn, sd = _signed(num, 32), _signed(den, 32)
        if (sn < 0) != (sd < 0):
            return SCALE_MAX
        return max(SCALE_MIN, min(SCALE_MAX, self._scale_recip_div(abs(sn), abs(sd))))

    def wall_x_range(self, viewx: int, viewy: int, viewangle: int, seg, verts):
        """R_AddLine: the seg's screen column range. Returns `(x1, x2, rw_angle1)` — x1 the left column,
        x2 the right column (x1 < x2; the wall covers [x1, x2) per DOOM) and rw_angle1 the absolute angle
        to v1 (for the per-column scale, M12g) — or None if the seg is back-facing or entirely outside the
        90° FOV. Both seg endpoints' absolute angles (point_to_angle), back-face cull (span ≥ ANG180),
        then make view-relative and clip to [-CLIPANGLE, CLIPANGLE] via DOOM's unsigned tspan logic, then
        map to columns via angle_to_x. `viewx/y/angle` are 16.16/BAM; `verts` are 16.0 (shifted <<16)."""
        v1, v2 = verts[seg.v1], verts[seg.v2]
        # perf #10 [exact]: affine back-face PRE-cull BEFORE the two atans. The signed affine distance
        # (seg_affine_coeffs) is >0 iff the eye is on the seg-line's FRONT side; a one-sided wall whose
        # front faces away (signed<=0) is invisible, so cull it without paying point_to_angle×2. Verified
        # byte-exact: every seg this culls that DOOM's span<ANG180 test would keep is frustum-culled
        # (wall_x_range would return None anyway) — so the rendered frame is unchanged.
        a, b, c = seg_affine_coeffs(seg, verts)
        if _signed((fixed_mul(a, viewx, 8, 4) + fixed_mul(b, viewy, 8, 4) + c) & ANGLE_MASK, 32) <= 0:
            return None
        # DOOM-standard winding (baked segs): v1 is the seg's LEFT screen vertex, v2 the RIGHT — so a
        # front-facing wall gives span < ANG180 (verified on real E1M1; the M7-era v1/v2 swap is gone).
        angle1 = self.point_to_angle(viewx, viewy, v1[0] << 16, v1[1] << 16)   # left vertex
        angle2 = self.point_to_angle(viewx, viewy, v2[0] << 16, v2[1] << 16)   # right vertex
        span = (angle1 - angle2) & ANGLE_MASK
        if span >= ANG180:
            return None                                  # back-facing (or degenerate)
        rw_angle1 = angle1
        angle1 = (angle1 - viewangle) & ANGLE_MASK        # view-relative
        angle2 = (angle2 - viewangle) & ANGLE_MASK
        two_clip = 2 * CLIPANGLE                           # = ANG90 (full FOV)

        tspan = (angle1 + CLIPANGLE) & ANGLE_MASK          # clip to the LEFT frustum edge
        if tspan > two_clip:
            if ((tspan - two_clip) & ANGLE_MASK) >= span:
                return None                              # wall entirely off the left
            angle1 = CLIPANGLE
        tspan = (CLIPANGLE - angle2) & ANGLE_MASK          # clip to the RIGHT frustum edge
        if tspan > two_clip:
            if ((tspan - two_clip) & ANGLE_MASK) >= span:
                return None                              # wall entirely off the right
            angle2 = (-CLIPANGLE) & ANGLE_MASK

        x1, x2 = self.angle_to_x(angle1), self.angle_to_x(angle2)
        if x1 >= x2:
            return None                                  # sub-column / not visible
        return x1, x2, rw_angle1

    # ── wall heights (R_RenderSegLoop top/bottom projection, M12g) ──
    @staticmethod
    def view_z(floor_h: int) -> int:
        """The view (eye) z in 16.16 — for a flat level the player z is the floor height, so the eye sits
        VIEWHEIGHT(41) map units above it."""
        return (floor_h + VIEWHEIGHT) << 16

    def wall_screen_span(self, ceil_h: int, floor_h: int, viewz: int, scale: int) -> tuple:
        """The screen rows `(top, bottom)` a wall column occupies, for the front sector's ceiling/floor
        heights (map units), the eye `viewz` (16.16), and the column's `scale` (16.16). DOOM: worldtop =
        ceiling - viewz, worldbottom = floor - viewz (16.16); top = CENTERY - worldtop·scale, bottom =
        CENTERY - worldbottom·scale. Rows may be off-screen (< 0 or >= VIEW_H) — the render loop (M12h)
        clips them. `top < bottom` always (ceiling above floor)."""
        centeryfrac = self.cfg.CENTERY << 16
        worldtop = (ceil_h << 16) - viewz
        worldbottom = (floor_h << 16) - viewz
        topfrac = centeryfrac - _signed(fixed_mul(worldtop, scale, 8, 4), 32)
        bottomfrac = centeryfrac - _signed(fixed_mul(worldbottom, scale, 8, 4), 32)
        return topfrac >> 16, bottomfrac >> 16

    # ── M14-d: line collision ──────────────────────────────────────────────────────────────────
    #
    # DOOM's P_CheckPosition, minus the blockmap. The blockmap exists to avoid testing every line;
    # here the whole line list is tested and the per-line bbox reject does that job instead -- E1M1
    # has ~1.5k linedefs and a reject is four compares, which is cheap next to a ~34M-op frame and
    # spares both mirrors an entire baked acceleration structure they would have to agree on.
    #
    # Everything is 16.16, exactly as DOOM's fixed_t is, so the fj mirror is the same arithmetic on
    # the same widths. Vertices are int16 map units, widened on read.

    @staticmethod
    def point_on_line_side(x: int, y: int, v1x: int, v1y: int, v2x: int, v2y: int) -> int:
        """P_PointOnLineSide: 0 = front/right of v1->v2, 1 = back/left. `x`/`y` are 16.16; the
        vertices are 16.16 too. The axis-aligned shortcuts are DOOM's and are not an optimisation
        that can be dropped -- they decide the `<=` boundary cases differently from the cross
        product, so a mirror without them disagrees exactly on the lines a player hugs."""
        dx_l, dy_l = v2x - v1x, v2y - v1y
        if dx_l == 0:
            return int(dy_l > 0) if x <= v1x else int(dy_l < 0)
        if dy_l == 0:
            return int(dx_l < 0) if y <= v1y else int(dx_l > 0)
        left = fixed_mul(_signed(dy_l >> 16, 32) & 0xFFFFFFFF, (x - v1x) & 0xFFFFFFFF, 8, 4)
        right = fixed_mul((y - v1y) & 0xFFFFFFFF, _signed(dx_l >> 16, 32) & 0xFFFFFFFF, 8, 4)
        return 0 if _signed(right, 32) < _signed(left, 32) else 1

    def box_on_line_side(self, box, v1x, v1y, v2x, v2y) -> int:
        """P_BoxOnLineSide: the side the whole box is on, or -1 when the box straddles the line.
        `box` is (top, bottom, left, right) in 16.16 -- DOOM's BOXTOP/BOXBOTTOM/BOXLEFT/BOXRIGHT
        order. Only a straddling box can be blocked by the line."""
        top, bottom, left, right = box
        dx_l, dy_l = v2x - v1x, v2y - v1y
        if dy_l == 0:                                            # ST_HORIZONTAL
            p1, p2 = int(top > v1y), int(bottom > v1y)
            if dx_l < 0:
                p1 ^= 1
                p2 ^= 1
        elif dx_l == 0:                                          # ST_VERTICAL
            p1, p2 = int(right < v1x), int(left < v1x)
            if dy_l < 0:
                p1 ^= 1
                p2 ^= 1
        elif (dy_l > 0) == (dx_l > 0):                            # ST_POSITIVE: test the \ diagonal
            p1 = self.point_on_line_side(left, top, v1x, v1y, v2x, v2y)
            p2 = self.point_on_line_side(right, bottom, v1x, v1y, v2x, v2y)
        else:                                                     # ST_NEGATIVE: the / diagonal
            p1 = self.point_on_line_side(right, top, v1x, v1y, v2x, v2y)
            p2 = self.point_on_line_side(left, bottom, v1x, v1y, v2x, v2y)
        return p1 if p1 == p2 else -1

    @staticmethod
    def line_opening(fs, bs):
        """P_LineOpening for a two-sided line: (opentop, openbottom, lowfloor), map units. The
        opening is what a thing has to fit through; `lowfloor` is the drop the far side offers."""
        return (min(fs.ceil_h, bs.ceil_h), max(fs.floor_h, bs.floor_h),
                min(fs.floor_h, bs.floor_h))

    def check_position(self, scene, x: int, y: int, *, radius: int = PLAYER_RADIUS, blockmap=None):
        """P_CheckPosition: may a thing of `radius` stand at (x, y)? Returns
        `(ok, floorz, ceilingz)` in MAP UNITS -- `ok` False means a line refuses the position
        outright, and the two heights are the opening the touched lines leave.

        The rules, in DOOM's order, are: bbox reject; `P_BoxOnLineSide != -1` reject (the box is
        wholly on one side, so the line is not hit); then a hit line blocks if it is one-sided or
        carries ML_BLOCKING, and otherwise narrows floorz/ceilingz to its opening.

        ⚠ NOT IMPLEMENTED, deliberately and permissively: the `tmfloorz - tmdropoffz > 24` "don't
        stand over a dropoff" test. It only ever REFUSES moves, so leaving it out cannot block a
        move DOOM would allow -- it can only allow one DOOM would refuse (walking off a tall
        ledge). Both mirrors omit it identically, so it is a stated behaviour difference from
        vanilla and not a divergence between the two halves of this project."""
        cmap = scene.cmap
        lds = scene.map_wad.linedefs(scene.mapname)
        sds = scene.map_wad.sidedefs(scene.mapname)
        secs = scene_sectors(scene)
        box = (y + radius, y - radius, x - radius, x + radius)   # top, bottom, left, right
        # P_CheckPosition seeds the opening from the SUBSECTOR the position lands in, before any
        # line is looked at. Without that seed a position with no line near it is unconstrained,
        # and the far outside of the map -- where no bbox overlaps -- reads as open space. The BSP
        # partitions the whole plane, so there is always a subsector to ask; outside the level it
        # is a solid one and its zero opening does the refusing.
        _sec = self._seg_sector(lds, sds, secs,
                                cmap.segs[cmap.subsectors[
                                    self.point_in_subsector(cmap, x >> 16, y >> 16)].firstseg])
        floorz, ceilingz = seed_floor, seed_ceil = _sec.floor_h, _sec.ceil_h
        # M14-d: `blockmap` is a pure ACCELERATOR -- the same answer from the ~0-8 lines whose block
        # the box touches instead of all ~1.5k. It exists because the fj mirror cannot afford the
        # full sweep (~7M ops/tic); the oracle's default stays the exhaustive loop, and
        # tests/host/test_collision.py proves the two agree over thousands of positions rather than
        # trusting the argument in `build_blockmap`'s docstring.
        blocked = getattr(scene, "blocked_lines", frozenset())
        if blockmap is not None:
            cand = blockmap_candidates(blockmap, x >> 16, y >> 16, radius >> 16)
            lds = [(i, lds[i]) for i in cand]
        else:
            lds = list(enumerate(lds))
        for _li, ld in lds:
            v1x, v1y = cmap.vertexes[ld.v1]
            v2x, v2y = cmap.vertexes[ld.v2]
            v1x, v1y, v2x, v2y = v1x << 16, v1y << 16, v2x << 16, v2y << 16
            if (box[3] <= min(v1x, v2x) or box[2] >= max(v1x, v2x)
                    or box[0] <= min(v1y, v2y) or box[1] >= max(v1y, v2y)):
                continue                                          # bbox reject
            if self.box_on_line_side(box, v1x, v1y, v2x, v2y) != -1:
                continue                                          # wholly on one side: not hit
            # ⚠ On a refusal the openings are returned as the SEED, not as whatever had
            # accumulated. DOOM's P_CheckPosition returns false out of the blockmap iterator and
            # leaves tmfloorz/tmceilingz partially updated — `try_move` never reads them on that
            # path, so they are dead. But "dead" means ORDER-DEPENDENT, and the fj mirror walks the
            # lines in blockmap order while this walks them in linedef order: comparing the two
            # would compare garbage. Pinning them to the seed makes the refusal comparable.
            if ld.back == -1:
                return False, seed_floor, seed_ceil               # one-sided: a wall
            # M2-R4: ...or it is a door that is not open far enough yet. Same refusal, same
            # place: a shut door IS a wall, which is exactly what the emitted program's baked
            # FLAG_BLOCKING bit says until the `wflip` clears it.
            if (ld.flags & ML_BLOCKING) or _li in blocked:
                return False, seed_floor, seed_ceil
            opentop, openbottom, _low = self.line_opening(
                secs[sds[ld.front].sector], secs[sds[ld.back].sector])
            floorz = max(floorz, openbottom)
            ceilingz = min(ceilingz, opentop)
        return True, floorz, ceilingz

    def try_move(self, scene, x: int, y: int, nx: int, ny: int, *,
                 radius: int = PLAYER_RADIUS, height: int = PLAYER_HEIGHT) -> tuple:
        """P_TryMove: is (nx, ny) a legal position to move to from (x, y)? All 16.16.

        On top of `check_position`, a position is refused when the opening is shorter than the
        thing (`ceilingz - floorz < height`) or the floor is more than MAX_STEP above where the
        thing stands now -- DOOM's "too big a step up". The current floor comes from the position
        being left, so a move is judged against the step it actually takes."""
        ok, floorz, ceilingz = self.check_position(scene, nx, ny, radius=radius)
        if not ok:
            return False
        if (ceilingz - floorz) << 16 < height:
            return False
        _here_ok, here_floor, _here_ceil = self.check_position(scene, x, y, radius=radius)
        if (floorz - here_floor) << 16 > MAX_STEP:
            return False
        return True

    def move_with_collision(self, scene, x: int, y: int, dx: int, dy: int, **kw) -> tuple:
        """The blocked-move policy: try the whole step, then the two axis-separated halves.

        ⚠ This is NOT DOOM's `P_SlideMove`, which projects the residual momentum along the wall.
        Sliding needs a fixed-point divide per blocking line and a second full P_TryMove pass; the
        axis retry gets the property that matters for a walkable level -- you do not stick to a
        wall you approach at an angle -- with three position tests and no new arithmetic. Both
        mirrors implement THIS policy, so it is a stated difference from vanilla, not a drift.
        Returns the (possibly unchanged) 16.16 position."""
        M = 0xFFFFFFFF
        for cand in (((x + dx) & M, (y + dy) & M), ((x + dx) & M, y), (x, (y + dy) & M)):
            if cand == (x, y):
                continue
            if self.try_move(scene, x, y, _signed(cand[0], 32), _signed(cand[1], 32), **kw):
                return cand
        return x, y

    # ── sim ──
    def step_sim(self, state: SimState, keys: dict, *, scene=None) -> SimState:
        """One tic: turn, then move -- against the level's lines when `scene` is given (M14-d), and
        freely when it is not (the M9 collision-free sim every earlier gate speaks).
        FixedMul(move, cos/sin) in 16.16 (n=8 nibbles, f=4 fraction nibbles) mirrors the fj path
        exactly; angle wraps mod 2**32."""
        angle = state.angle
        if keys.get("turn_left"):
            angle = (angle + ANGLE_TURN) & 0xFFFFFFFF
        if keys.get("turn_right"):
            angle = (angle - ANGLE_TURN) & 0xFFFFFFFF

        move = 0
        if keys.get("forward"):
            move += FORWARD_MOVE
        if keys.get("back"):
            move -= FORWARD_MOVE

        x, y = state.x, state.y
        if move:
            m = move & 0xFFFFFFFF  # two's-complement; fixed_mul interprets the sign (n=8)
            dx = fixed_mul(m, self.read_cos(angle), 8, 4)
            dy = fixed_mul(m, self.read_sin(angle), 8, 4)
            if scene is None:
                x, y = (x + dx) & 0xFFFFFFFF, (y + dy) & 0xFFFFFFFF
            else:
                x, y = self.move_with_collision(scene, _signed(x, 32), _signed(y, 32), dx, dy)
                x, y = x & 0xFFFFFFFF, y & 0xFFFFFFFF
        return replace(state, x=x, y=y, angle=angle)

    def render_textured_column(self, texels, texheight, texcol, colormap, light, *,
                               count, frac0, step, fracbits=8):
        """One textured wall column (F5 core) — the texture-v DDA. For `count` screen rows, sample the
        texture's `texcol` column at v = (frac >> fracbits) & (texheight-1) (heightmask, pow2 height),
        apply the colormap at `light`, accumulate frac += step in 8.8 (wraps mod 2**16). Returns the
        lit palette bytes top-to-bottom. The fj renderer reproduces this exactly (D12); `texels` and
        `colormap` are the shared M8 data (R6). texel index is column-major: col*texheight + v."""
        out = bytearray()
        frac = frac0
        mask = texheight - 1
        for _ in range(count):
            v = (frac >> fracbits) & mask
            pal = texels[texcol * texheight + v]
            out.append(colormap[light][pal])
            frac = (frac + step) & 0xFFFF
        return bytes(out)

    def render_unroll_frame(self, texels, texheight, texwidth, colormap, light, *,
                            width, count, frac0, step, fracbits=8) -> bytes:
        """The M11c synthetic full-unroll frame (the D2 bake-off workload): every screen column x in
        [0, width) is the texture-v DDA over texcol = x % texwidth (a full-width texture splat), `count`
        rows tall, at a constant column `light`. Returns a row-major W*H frame; the rendered region is
        [row<count][x<width], everything else stays zero (the register framebuffer's zero-init). The fj
        full-unroll renderer reproduces this bit-exactly (D12) — each column is render_textured_column,
        placed row-major at (x, row)."""
        cfg = self.cfg
        fb = bytearray(cfg.FB_SIZE)
        for x in range(width):
            col = self.render_textured_column(texels, texheight, x % texwidth, colormap, light,
                                              count=count, frac0=frac0, step=step, fracbits=fracbits)
            for row in range(count):
                fb[row * cfg.W + x] = col[row]
        return bytes(fb)

    def render_solid_column(self, col_x: int, color: int, *, bg: int = 0) -> bytes:
        """M11a's golden frame: a framebuffer cleared to `bg` with column `col_x` filled with `color`
        (row-major W*H palette indices). The simplest renderer-primitive frame — the fj program
        produces it bit-exactly via F4 fixed-address packed stores + the F7 0x03 present."""
        cfg = self.cfg
        fb = bytearray([bg]) * cfg.FB_SIZE
        for row in range(cfg.H):
            fb[row * cfg.W + col_x] = color
        return bytes(fb)

    # ── BSP point location (R_PointInSubsector) ──
    def point_in_subsector(self, cmap: CompiledMap, x: int, y: int) -> int:
        """Walk the BSP from the root to the leaf containing integer map point (x, y). The side test is
        mapcompiler's shared `_point_side` (>0 back/left, else front/right — DOOM's right=front, with
        on-the-line counted as front). Returns the subsector index (the NF_SUBSECTOR bit stripped)."""
        node = cmap.root
        while not node & NF_SUBSECTOR:
            n = cmap.nodes[node]
            side = _point_side(n.x, n.y, n.dx, n.dy, x, y)
            node = n.left if side > 0 else n.right
        return node & (NF_SUBSECTOR - 1)

    def bsp_render_order(self, cmap: CompiledMap, vx: int, vy: int, *,
                         bbox_gate: dict | None = None, va: int | None = None,
                         eye16: tuple | None = None) -> list:
        """R_RenderBSPNode: the front-to-back subsector visit order from viewpoint (vx, vy) [16.0 map
        coords]. At each node the viewer's side (`_point_side > 0` ⇒ back/left, else front/right, R6) is
        the NEAR child — descend it first, then the far child — so subsectors come out nearest-first (the
        order walls are drawn for solid-seg clipping). Iterative (explicit stack): the M7-built BSP is
        unbalanced/deep (~1829 segs on E1M1), so recursion would overflow — exactly why F5 reserves the
        runtime stack for the BSP's upper levels (§2.1). Returns subsector indices.

        M13-15M `bbox_gate` (with `va`): the BBOX WEDGE CULL's oracle mirror. A gated node whose
        union subtree box lies wholly outside either of the frame's two wedge half-planes is
        SKIPPED — subtree, segs, budget increments and all — exactly as the emitted fj gate skips
        it. The gate dict must come from mapcompiler.bbox_gate_boxes (the SSOT), or the two sides
        disagree on which marking segs spend PNEAR budget."""
        gA = gB = None
        # CR-2026-08 (PJ-1): the wedge test needs the FRACTIONAL eye, because its combined terms are
        # floored after combining (see bbox_wedge_miss). Defaulting to the floored eye reproduces the
        # old behaviour exactly at a whole map unit, which is every pre-M14 viewpoint.
        ex16, ey16 = eye16 if eye16 is not None else (vx << 16, vy << 16)
        if bbox_gate:
            gA, gB = wedge_planes_bam(va & 0xFFFFFFFF)
        order = []
        stack = [cmap.root]
        while stack:
            child = stack.pop()
            if child & NF_SUBSECTOR:
                order.append(child & (NF_SUBSECTOR - 1))
            else:
                if bbox_gate is not None:
                    box = bbox_gate.get(child)
                    if box is not None and (bbox_wedge_miss(gA, box, vx, vy, ex16, ey16)
                                            or bbox_wedge_miss(gB, box, vx, vy, ex16, ey16)):
                        continue
                n = cmap.nodes[child]
                back = _point_side(n.x, n.y, n.dx, n.dy, vx, vy) > 0
                near, far = (n.left, n.right) if back else (n.right, n.left)
                stack.append(far)    # far pushed first ⇒ popped (drawn) after the whole near subtree
                stack.append(near)   # near on top ⇒ drawn first (front-to-back)
        return order

    def visible_segs(self, cmap: CompiledMap, vx: int, vy: int, *,
                     bbox_gate: dict | None = None, va: int | None = None,
                     eye16: tuple | None = None) -> list:
        """The seg indices (into `cmap.segs`) of every visible subsector, flattened in BSP front-to-back
        order — the wall draw order. Each subsector contributes its `firstseg .. firstseg+numsegs`.

        `eye16` (CR-2026-08 PJ-1) is the SIGNED 16.16 view position, needed only by the `bbox_gate`
        wedge test, whose combined terms must be floored AFTER combining to mirror
        `proj.wedge_setup`. Omitted ⇒ the whole-map-unit case, identical by construction."""
        segs = []
        for ss in self.bsp_render_order(cmap, vx, vy, bbox_gate=bbox_gate, va=va, eye16=eye16):
            s = cmap.subsectors[ss]
            segs.extend(range(s.firstseg, s.firstseg + s.numsegs))
        return segs

    @staticmethod
    def _seg_sector(lds, sds, secs, seg):
        """The sector a seg fronts: seg -> linedef -> (front|back) sidedef -> sector. `lds/sds/secs` are
        the level's parsed LINEDEFS/SIDEDEFS/SECTORS (parsed once per frame and threaded in, R6).
        The rule itself lives in `mapcompiler.seg_sector` -- `thing_live_subsectors` needs it too and
        mapcompiler cannot import this module, so this delegates rather than restating it."""
        return seg_sector(lds, sds, secs, seg)

    def _sector_light(self, scene: Scene, subsector: int) -> int:
        """Light level of the sector the subsector belongs to (subsector -> first seg -> sector)."""
        seg = scene.cmap.segs[scene.cmap.subsectors[subsector].firstseg]
        return self._seg_sector(scene.map_wad.linedefs(scene.mapname),
                                scene.map_wad.sidedefs(scene.mapname),
                                scene_sectors(scene), seg).light

    # ── render ──
    def render_frame(self, state: SimState, scene: Scene) -> bytes:
        """The spawn frame: a colormap-shaded ceiling/floor background. Find the player's subsector
        (16.0 truncation of the 16.16 position), read its sector light, pick the colormap row, and
        fill the top VIEW_H/2 rows with the shaded ceiling index and the rest with the floor index.
        Returns W*H packed palette-index bytes (row-major, D3)."""
        cfg = self.cfg
        colormap = scene.asset_wad.colormap()

        px = _signed(state.x, 32) >> 16   # 16.16 -> 16.0 integer map coord (sign-extended, §1.1.4)
        py = _signed(state.y, 32) >> 16
        subsector = self.point_in_subsector(scene.cmap, px, py)
        light = self._sector_light(scene, subsector)
        row = max(0, min(COLORMAP_LIGHTS - 1, light >> LIGHT_SHIFT))

        ceil = colormap[row][CEIL_BG]
        floor = colormap[row][FLOOR_BG]

        fb = bytearray(cfg.FB_SIZE)
        horizon = cfg.VIEW_H // 2
        for y in range(cfg.VIEW_H):
            val = ceil if y < horizon else floor
            base = y * cfg.VIEW_W
            for x in range(cfg.VIEW_W):
                fb[base + x] = val
        return bytes(fb)

    def _wall_offset(self, viewx, viewy, viewangle, seg, verts, rw_normalangle, rw_angle1, sd):
        """R_StoreWallRange's texture-horizontal setup: returns `(rw_offset, rw_centerangle)` (both BAM/
        16.16). `rw_offset` (16.16 texels) is the wall-space horizontal coordinate of v1 = ±hyp·sin(the
        clamped normal↔v1 offset angle), signed by which side v1 is on, plus the seg + sidedef texture
        offsets; `rw_centerangle = ANG90 + viewangle - rw_normalangle` seeds the per-column finetangent
        lookup. hyp = point_to_dist(view, v1)."""
        v1x, v1y = verts[seg.v1]
        hyp = self.point_to_dist(viewx, viewy, v1x << 16, v1y << 16)
        offsetangle = (rw_normalangle - rw_angle1) & ANGLE_MASK
        oa = (-offsetangle) & ANGLE_MASK if offsetangle > ANG180 else offsetangle   # BAM abs
        if oa > ANG90:
            oa = ANG90
        rw_offset = fixed_mul(hyp, self.read_sin(oa), 8, 4)
        if offsetangle < ANG180:                              # DOOM sign rule (uses the unfolded angle)
            rw_offset = (-rw_offset) & ANGLE_MASK
        rw_offset = (rw_offset + (seg.offset << 16) + (sd.x_off << 16)) & ANGLE_MASK
        rw_centerangle = (ANG90 + viewangle - rw_normalangle) & ANGLE_MASK
        return rw_offset, rw_centerangle

    def _wall_texture(self, asset_wad, name, cache, *, wall_mode="textured"):
        """Composite + downscale (the shared D5 lever) a wall texture by name → (texels, height, width),
        column-major texels (R6). Cached per frame; returns None for an empty/absent texture ('-' or a
        name not in TEXTURE1) so the caller falls back to the flat shade.

        `wall_mode` (M13p4a): "textured" (default, the real texture) or "W1"/"W2" — a tiny synthetic
        canvas (`_tiny_wall_canvas`, the SAME helper `wall_renderer.emit_wall_renderer` calls, so the fj
        combined table can never drift from this oracle). ⚠ The cache key MUST carry the mode: the old
        "one render = one mode" assumption broke when V2's sky started requesting `textured` INSIDE a
        W1/W2 render — a visible WALL textured with SKY1 (E1M1-lite at (1869,479,W) has one) then
        poisoned the sky's cache entry with the flattened canvas, or vice versa, whichever loaded
        first (M13-15M, the 89-px W1 divergence)."""
        nm = name.upper()
        key = (nm, wall_mode)
        if key in cache:
            return cache[key]
        defs = cache.get("__defs__")
        if defs is None:
            defs = {d.name.upper(): d for d in asset_wad.texture_defs("TEXTURE1")}
            cache["__defs__"] = defs
        if not nm or nm == "-" or nm not in defs:
            cache[key] = None
            return None
        canvas = downscale_canvas(composite_texture(asset_wad, defs[nm]), self.downscale)
        texels, th, tw = texture_texels(canvas), len(canvas), len(canvas[0])
        if wall_mode not in ("textured", "WPX"):     # WPX samples the REAL texture (see wpx_strip)
            texels, th, tw = self._tiny_wall_canvas(
                texels, th, wall_mode,
                pal=asset_wad.playpal() if wall_mode == "W1R" else None)
        cache[key] = (texels, th, tw)
        return cache[key]

    @staticmethod
    def _mode_texel(texels) -> int:
        """The most common palette index in a texel list — a real representative color (M13p4a W1;
        NOT a mean index, palette indices aren't luminance-ordered, so a mean is a random hue)."""
        from collections import Counter
        return Counter(texels).most_common(1)[0][0]

    @staticmethod
    def wall_fake_contrast(v1, v2) -> int:
        """DOOM's FAKE CONTRAST (R_StoreWallRange): an AXIS-ALIGNED wall is shaded one light level
        down if it runs east-west and one up if it runs north-south.

        This exists in DOOM for exactly the complaint it answers -- two walls meeting at a corner
        otherwise render as one flat expanse of identical colour, with no visible edge between them.
        It is per-SEG and orientation-only, so it costs nothing at runtime here: the light level is
        part of the baked block key."""
        if v1[1] == v2[1]:
            return -1                                  # east-west wall: one level darker
        if v1[0] == v2[0]:
            return 1                                   # north-south wall: one level brighter
        return 0                                       # diagonal: unchanged

    @staticmethod
    def wall_lightnum(sec_light: int, contrast: int) -> int:
        """The seg's DOOM light level (0..LIGHTLEVELS-1): the sector's level plus fake contrast.
        A per-seg constant, so it is part of the baked block key, never a runtime value."""
        return max(0, min(LIGHTLEVELS - 1, (sec_light >> LIGHTSEGSHIFT) + contrast))

    def wall_light_row(self, lightnum: int, h: int, wall_units: int) -> int:
        """The colormap row for a wall column `h` pixels tall in a sector whose ceiling-to-floor
        span is `wall_units` map units — DOOM's `scalelight[lightnum][rw_scale >> LIGHTSCALESHIFT]`.

        The column's projection scale is recovered from its own height: `h ≈ wall_units * scale >>
        16`, so `scale ≈ (h << 16) / wall_units`. That is what makes the whole thing FREE — the WPX
        bank is already indexed by h, so the distance light folds into the baked colour byte and
        costs zero runtime ops (the same lever as `wpx_texcol`).

        ⚠ APPROXIMATION: `h` is the CLIPPED on-screen height, so a wall extending past the top or
        bottom of the view reports a smaller h than its true extent and is shaded as if it were
        further away. The error only affects the very nearest walls, it is constant down each such
        column, and it is monotone in h — so near still reads brighter than far, which is the cue
        that matters. Fixing it exactly would need the UNCLIPPED height as the bank index, which
        costs a per-run clip compare in the fj emit."""
        scale = (max(1, h) << 16) // max(1, wall_units)
        return self.scalelight[lightnum][min(MAXLIGHTSCALE - 1, scale >> LIGHTSCALESHIFT)]

    @staticmethod
    def wpx_texcol(tw, h, scale=WPX_U_SCALE):
        """M13-WPX horizontal: which texture COLUMN an `h`-pixel-tall wall column samples.

        For a flat wall the screen height goes as h ∝ 1/z, and (this is the real DOOM relation)
        the texture coordinate is affine in the depth z — so u ∝ 1/h is the perspective-SHAPED
        advance: the texture compresses exactly where the wall recedes. Deriving u from h instead
        of from x is what makes it free — the run-list bank is already indexed by height, so the
        horizontal detail costs no runtime op, no extra bank, and (being a function of the clip
        rows alone) it does not break a single ditto column. `scale` sets how many texture widths
        a wall sweeps across its depth range; it is a look knob, not a correctness one."""
        return (scale // max(1, h)) % tw

    @staticmethod
    def wall_noise(x: int, run: int = 0) -> int:
        """V1 — the PSEUDO-RANDOM wall grain: how many colormap steps to darken run `run` of screen
        column `x` by. The owner's idea, and the cheap answer to wall texturing: a real texture
        needs a texel fetch per wall row (5,612 rows a frame at ~1.4k each = +19.6M) whereas this
        needs no lookup at all.

        ⚠ It darkens through the COLORMAP, it does NOT xor the palette index. DOOM's palette runs
        dark→bright with the index, so `0 ^ 3` turns black into light grey and a dark wall erupts in
        white confetti — the first prototype did exactly that. A colormap step is by construction
        the same colour, dimmer, so the grain always reads as surface roughness.

        XORs and constant shifts ONLY: those are ~27 ops each in fj, where a `read_byte` is ~1,060
        and a multiply is thousands. The fj emit loop reproduces this expression exactly (R6).

        Two constants were chosen by MEASUREMENT, not taste (5 variants swept, spawn + (-480,256)):

        * **the grain is keyed on `x >> 2`, not `x`.** Per-column noise breaks DITTO — one differing
          pixel forces the whole column to be emitted — and ditto is worth 4.83M. Grouping four
          columns keeps ditto alive (100 → 76 columns rather than 100 → 44) and costs +375 pairs
          instead of +1,198, i.e. a THIRD of the emit for MORE visible grain.
        * **the step is `<< 2`, so 0/4/8/12 rows, not 0..3.** Colormap row 0 is the identity and one
          step barely moves an already-dark colour: at 0..3 only 375 pixels changed on the whole
          frame. At 0/4/8/12 it is 2,896 — 7.7x the effect for less than a third of the pairs.

        `run` is accepted but DELIBERATELY UNUSED: varying the grain per run as well measured
        identical (2,910 px / +373 pairs against 2,961 / +429 for column-group alone), and dropping
        it means the fj sets the colormap row ONCE PER COLUMN instead of once per run — the emit loop
        then only rebuilds the low byte of the `cm.apply` index. Kept in the signature because the
        run-varying form is the obvious thing to try again, and this is the note that says don't."""
        h = (x >> 2) ^ (x >> 4)
        h ^= h >> 3
        return (h & ((1 << WALL_NOISE_BITS) - 1)) << 2

    @staticmethod
    def wall_noise2(x: int) -> int:
        """W1R-LOD -- the FINE column-group hash (2-px groups, x>>1): FAR tiers mix it into
        their pattern pick so distant walls get 2-px-wide texture cells. Its ditto compare is
        GATED on the column's tier, so only far-wall columns pay the extra breaks."""
        h = (x >> 1) ^ (x >> 3)
        h ^= h >> 2
        return (h & ((1 << WALL_NOISE_BITS) - 1)) << 2

    @staticmethod
    def wall_noise3(x: int) -> int:
        """W1R-LOD -- the COARSE column-group hash (8-px groups, x>>3): the NEAR tier picks its
        pattern by it, so close walls get 8-px-wide cells (bigger texels up close)."""
        h = (x >> 3) ^ (x >> 5)
        h ^= h >> 3
        return (h & ((1 << WALL_NOISE_BITS) - 1)) << 2

    # ------------------------------------------------------------------ M13-W1R
    # The RANDOMIZED W1 wall tier: the wall keeps W1's single baked lit byte, but is emitted as
    # PSEUDO-RANDOM VERTICAL RUNS re-shaded through the colormap (V1's grain mechanism -- same
    # colour, dimmer, so it reads as surface texture and never as a hue jump). The pattern is
    # keyed on (a) the V1 COLUMN-GROUP hash `wall_noise(x)` -- already part of the fj ditto
    # signature, so W1R breaks ZERO additional dittos -- and (b) a HEIGHT TIER: short (= far)
    # walls draw from darker rows than tall (= near) ones, which is the distance-light cue the
    # flat W1 tier dropped. Rows are ABSOLUTE colormap rows composed over the already-lit byte
    # (row 0 = identity), exactly like the WPX grain.
    W1R_TIER_BOUNDS = (6, 16, 40)      # wlen < 6 -> tier 0 (far) ... >= 40 -> tier 3 (near)

    # The W1R BASE is baked BRIGHTER than W1's by this many colormap rows (clamped at 0), so the
    # pattern rows below can move the tone BOTH ways around today's W1 colour: row 3 ~ the W1
    # tone, rows 0-2 brighter, rows 4+ darker. Without this, colormap composition can only
    # darken, and on the map's dark walls the texture was nearly invisible (first proto sheet).
    W1R_BASE_BRIGHTEN = 8

    # W1R_PATTERNS[tier][wall_noise(x) >> 2] = ((run_len, colormap_row, alt), ...), cycled down
    # the wall. Hand-tuned literals (an SSOT, not a runtime RNG): the fj `w1rpat.walk` bakes
    # these very tuples as code, so oracle and fj cannot drift (R6). Adjacent-run row deltas
    # are kept >= 4 -- the V1 grain sweep measured smaller steps as invisible.
    # W1R-2C (owner ask): `alt`=1 draws the run over the texture's SECOND representative texel
    # (`_w1r_texel2` -> the baked seg_lit2) -- scattered on ~30% of runs so it reads as embedded
    # stones/panels -- and the run lens are FINER (~2-6 px) than the first cut's 2-9.
    # W1R-MASONRY (owner pick, 2026-08-03): every group in a tier shares the SAME run-length
    # sequence, so run boundaries ALIGN horizontally across the wall (mortar lines) and only the
    # brick shade varies per group -- the pattern reads as coursed masonry instead of static.
    # Same mechanism, same costs: the tables are compile-time data.
    W1R_PATTERNS = (
        (   # tier 0, wlen < 6 (farthest): LONG calm courses -- 20M-RECOVERY: a 6px cycle
            # halves the emitted pairs on the smallest far walls (1-2 runs a column)
            ((4, 14, 0), (2, 16, 0)),
            ((4, 15, 0), (2, 13, 1)),
            ((4, 13, 0), (2, 15, 0)),
            ((4, 16, 0), (2, 14, 0)),
        ),
        (   # tier 1, 6 <= wlen < 16: 4px brick + 2px mortar (row 15) -- the same aligned
            # courses at half the pair count (20M-RECOVERY: far walls carry no fine detail)
            ((4, 10, 0), (2, 15, 0)),
            ((4, 12, 0), (2, 15, 0)),
            ((4, 13, 0), (2, 15, 0)),
            ((4, 9, 1), (2, 15, 0)),
        ),
        (   # tier 2, 16 <= wlen < 40: 3px brick + 1px mortar (row 12)
            ((3, 5, 0), (1, 12, 0), (3, 8, 0), (1, 12, 0)),
            ((3, 7, 0), (1, 12, 0), (3, 4, 1), (1, 12, 0)),
            ((3, 9, 0), (1, 12, 0), (3, 6, 0), (1, 12, 0)),
            ((3, 4, 0), (1, 12, 0), (3, 8, 1), (1, 12, 0)),
        ),
        (   # tier 3, wlen >= 40 (near): 6px brick + 2px mortar (row 8), two courses per cycle
            ((6, 1, 0), (2, 8, 0), (6, 3, 0), (2, 8, 0)),
            ((6, 2, 0), (2, 8, 0), (6, 0, 1), (2, 8, 0)),
            ((6, 4, 0), (2, 8, 0), (6, 1, 0), (2, 8, 0)),
            ((6, 0, 0), (2, 8, 0), (6, 3, 1), (2, 8, 0)),
        ),
    )

    @staticmethod
    def v5_side_modes(fsec, bsec, sky: bool):
        """V5-DROP -- what piece each SIDE of a marking boundary places, from ITS OWN banding
        triple: (upper_mode, lower_mode), 0 = none, 1 = RISER face (the far side is higher --
        stair risers, lintels: the existing V3/V5 faces), 2 = LIP (the far side is lower or
        only the flat/light changes): a 1-ROW face at the near surface's edge row. The lip is
        what makes DROP-OFFS visible -- the region-behind machinery then paints the far flat
        beyond the edge, so descending stairs show treads and the nukage pool shows from its
        bank (the owner's green-floor/stairs asks, 2026-08-04). Any upper piece between two
        F_SKY1 ceilings is suppressed (the V2 sky rule: nothing may draw lines in the sky)."""
        # V5-DROP-P2 (owner's (1210,1187) field-flip, 2026-08-04): lips fire on HEIGHT or
        # MATERIAL changes only, never light-only shading. Light-lips were stealing both
        # per-column piece slots from the structural drop-off behind them (the pool edge),
        # and WHICH light boundary won flipped with the walk order -- the whole far field
        # then changed colour on a single step. Light-only transitions keep the pre-DROP
        # look (the near attribution), which reads fine and costs nothing.
        up = fsec.ceil_h != bsec.ceil_h or fsec.ceil_tex != bsec.ceil_tex
        lo = fsec.floor_h != bsec.floor_h or fsec.floor_tex != bsec.floor_tex
        um = 0 if not up else (1 if fsec.ceil_h > bsec.ceil_h else 2)
        lm = 0 if not lo else (1 if bsec.floor_h > fsec.floor_h else 2)
        # CR-2026-08: BOTH upper modes are suppressed between two F_SKY1 ceilings, not just
        # the lip -- a RISER there is a face floating in the sky (DOOM's own sky hack skips
        # the upper entirely when both sides are sky).
        if um and sky and (fsec.ceil_tex or "").upper() == "F_SKY1" \
                and (bsec.ceil_tex or "").upper() == "F_SKY1":
            um = 0
        return um, lm

    @staticmethod
    def w1r_tier(wlen: int) -> int:
        """The W1R height tier of a `wlen`-pixel wall column (0 = far ... 3 = near)."""
        b = ReferenceModel.W1R_TIER_BOUNDS
        return 0 if wlen < b[0] else 1 if wlen < b[1] else 2 if wlen < b[2] else 3

    @staticmethod
    def w1r_runs(wlen: int, x: int):
        """The W1R run list of a `wlen`-pixel wall column at SCREEN COLUMN `x`:
        [(y2_rel_exclusive, colormap_row, alt), ...], the last ending exactly at `wlen`.
        Cycles the (tier, group) pattern down the wall and CLAMPS the final run -- the exact
        walk the generated fj `w1rpat.walk` performs, so the two sides cannot drift (R6).
        `alt`=1 means the SECOND colour byte (walls: seg_lit2; faces ignore it).
        W1R-LOD: the pattern GROUP key is per tier -- far tiers mix the fine 2-px hash
        (gnrow ^ gnrow2), the mid tier keeps the 4-px hash, the near tier uses the coarse
        8-px hash -- so texel width scales with distance. `wlen` must be >= 1."""
        tier = ReferenceModel.w1r_tier(wlen)
        if tier >= 3:
            key = ReferenceModel.wall_noise3(x)
        elif tier == 2:
            key = ReferenceModel.wall_noise(x)
        else:
            key = ReferenceModel.wall_noise(x) ^ ReferenceModel.wall_noise2(x)
        pat = ReferenceModel.W1R_PATTERNS[tier][(key >> 2) & 3]
        runs, rel, k = [], 0, 0
        while True:
            ln, row, alt = pat[k % len(pat)]
            rel += ln
            if rel >= wlen:
                runs.append((wlen, row, alt))
                return runs
            runs.append((rel, row, alt))
            k += 1

    @staticmethod
    def wpx_strip(texels, th, tw, colormap, light_row, h, *, cap=WPX_RUN_CAP):
        """M13-WPX — the 1×1 run-list of an `h`-pixel-tall wall column: entry j is
        `[rel_end_exclusive, colour]`, the last one ending exactly at `rel = h`.

        The column is sampled at FULL vertical resolution (row r of the wall takes texture texel
        `r*th//h`, i.e. one texel per PIXEL, no 16-band stretch) through the sector's colormap row,
        then RUN-MERGED — so the cost is the number of visible colour CHANGES, not the pixel count.
        The texture COLUMN comes from `wpx_texcol(tw, h)` -- horizontal detail for free (see there).

        `cap` bounds the run count (and hence both the fj loop and the baked bank): while over
        budget, the SHORTEST run is absorbed into its neighbour, which drops single-pixel noise
        first and keeps the big structural bands. Shared verbatim by this oracle and
        `wall_renderer._lines_wall_pix_bank`, so fj and oracle can never drift (R6)."""
        if texels is None:
            return [[h, colormap[light_row][WALL_BG]]]
        col = texels[ReferenceModel.wpx_texcol(tw, h) * th:][:th]
        px = [colormap[light_row][col[min(th - 1, (r * th) // h)]] for r in range(h)]
        runs: list[list[int]] = []
        for j, c in enumerate(px):
            if runs and runs[-1][1] == c:
                runs[-1][0] = j + 1
            else:
                runs.append([j + 1, c])
        while len(runs) > cap:
            lens = [runs[i][0] - (runs[i - 1][0] if i else 0) for i in range(len(runs))]
            i = lens.index(min(lens))                 # deterministic: the FIRST shortest run
            if i:
                runs[i - 1][0] = runs[i][0]           # the run above absorbs it
            runs.pop(i)                               # (i == 0: the run below just starts at 0)
        return runs

    def sprite_tz_min_size(self, wph: int, min_h: int | None = None) -> int:
        """The largest depth `tz` at which a sprite `wph` map units tall still projects to at least
        `min_h` screen rows. Beyond it `project_thing` rejects on height, so fj can reject on DEPTH
        instead -- before the two lateral multiplies and the reciprocal (EXP-7's shape, bigger
        constant). Baked per thing as `sp_tzmin`; R6 single source, the emitter calls this.

        ⚠ NOT the analytic `(wph*PROJECTION<<16)//min_h`. `xscale` comes from the block-FP
        `_scale_recip_div`, not a true divide, so the real boundary sits up to a whole map unit
        either side of it (measured: -65,537 .. +43,690). Binary-searched against the REAL chain and
        checked at the boundary, so the oracle's `h < min_h` and fj's `tz > sp_tzmin` reject exactly
        the same set -- which is what byte-exactness needs."""
        min_h = MIN_SPRITE_H if min_h is None else min_h
        key = (wph, min_h)
        if key in self._tzmin_cache:
            return self._tzmin_cache[key]
        proj = self.cfg.PROJECTION

        def h_at(tz):
            xs = self._scale_recip_div(proj << 16, tz)
            return _signed(fixed_mul((wph << 16) & ANGLE_MASK, xs, 8, 4), 32) >> 16

        # ⚠ ALWAYS scan, including min_h == 1. EXP-7's analytic `(wph*PROJECTION)<<16` is the depth
        # where the ANALYTIC height hits zero, and the block-FP reciprocal's real boundary sits a
        # unit or so off it -- close enough that EXP-7's reject stayed exact (it only had to be
        # conservative), NOT close enough to be the sharp boundary this returns.
        lo, hi = SPRITE_MINZ, ((wph * proj) << 16) // min_h + (8 << 16)
        while lo < hi:                                    # largest tz with h >= min_h
            mid = (lo + hi + 1) // 2
            if h_at(mid) >= min_h:
                lo = mid
            else:
                hi = mid - 1
        best = lo
        assert h_at(best) >= min_h > h_at(best + 1), \
            f"sprite_tz_min_size({wph}, {min_h}): boundary not sharp at {best}"
        self._tzmin_cache[key] = best
        return best

    # ── V4 THINGS: sprite art, and the run-list the fj bank bakes from it ─────────────────────────
    def sprite_art(self, sprite_wad, kind: int, cache: dict):
        """A thing type's sprite, DOWNSCALED like a wall texture: `(cols, dh, dw, wpx, wph, left,
        top)` where `cols[u]` is a `dh`-long list of palette indices with -1 for transparent, and
        `wpx/wph/left/top` are the ORIGINAL picture's world size and offsets (a DOOM sprite pixel is
        one map unit, so the geometry must not be downscaled — only the sampling is).

        Returns None for a type with no sprite in this wad (starts, teleport spots, and — in the
        cut-down test fixture — everything, which is why `sprite_wad` is a separate argument)."""
        if kind in cache:
            return cache[kind]
        pre = THING_SPRITE.get(kind)
        pic = None
        if pre is not None:
            for suffix in ("A0", "A1", "A2A8", "A1D1"):
                try:
                    pic = decode_picture(sprite_wad.get_data(pre + suffix))
                    break
                except (KeyError, ValueError, IndexError):
                    continue
        if pic is None:
            cache[kind] = None
            return None
        ds = self.downscale
        dw, dh = max(1, pic.width // ds), max(1, pic.height // ds)
        cols = []
        for u in range(dw):
            dense = [-1] * pic.height
            for (v, t) in pic.columns[min(pic.width - 1, u * ds)]:
                if 0 <= v < pic.height:
                    dense[v] = t
            cols.append([dense[min(pic.height - 1, v * ds)] for v in range(dh)])
        # V4-HD: the SAME columns at FULL vertical resolution (u stays downscaled) -- the
        # near height buckets sample these so close sprites keep the art's real detail
        fcols = []
        for u in range(dw):
            dense = [-1] * pic.height
            for (v, t_) in pic.columns[min(pic.width - 1, u * ds)]:
                if 0 <= v < pic.height:
                    dense[v] = t_
            fcols.append(dense)
        cache[kind] = (cols, dh, dw, pic.width, pic.height, pic.leftoffset, pic.topoffset,
                       fcols, pic.height)
        return cache[kind]

    @staticmethod
    def sprite_strip(col, dh: int, h: int, *, cap=SPRITE_RUN_CAP):
        """V4 — one sprite column drawn `h` screen pixels tall, as `(r0, runs)`: `r0` is the first
        screen row (relative to the sprite's top) the column paints, and `runs` is
        `[rel_end_exclusive, RAW texel]` measured from `r0`, run-merged exactly as `wpx_strip` does.
        Returns None for a fully transparent column.

        ⚠ Only the column's OPAQUE EXTENT is painted, and INTERIOR gaps take the nearest opaque
        texel ABOVE them. That is not an aesthetic choice — the 0x0B column protocol fills forward
        from a cursor that never moves back, so a transparent run in the MIDDLE of a fragment would
        need background the emit has already passed. The visible cost is small (it fattens holes in
        open sprites like trees); the alternative is a second pass over every column.

        Texels are RAW: the light row is applied at emit time through `cm.emit`, exactly as V1's
        grain is, so the bank is shared by every light level instead of multiplied by it."""
        idx = [v for v, t in enumerate(col) if t >= 0]
        if not idx or h <= 0:
            return None
        v0, v1 = idx[0], idx[-1]
        filled, last = list(col), col[v0]
        for v in range(v0, v1 + 1):
            if col[v] >= 0:
                last = col[v]
            else:
                filled[v] = last
        rows = [r for r in range(h) if v0 <= min(dh - 1, (r * dh) // h) <= v1]
        if not rows:
            return None
        r0 = rows[0]
        px = [filled[min(dh - 1, (r * dh) // h)] for r in rows]
        runs: list[list[int]] = []
        for j, c in enumerate(px):
            if runs and runs[-1][1] == c:
                runs[-1][0] = j + 1
            else:
                runs.append([j + 1, c])
        while len(runs) > cap:                        # identical reduction to wpx_strip's
            lens = [runs[i][0] - (runs[i - 1][0] if i else 0) for i in range(len(runs))]
            i = lens.index(min(lens))
            if i:
                runs[i - 1][0] = runs[i][0]
            runs.pop(i)
        return r0, runs

    def project_thing(self, viewx, viewy, viewangle, viewz, tx_map, ty_map, tz_map, art,
                      min_h: int | None = None):
        """V4 — R_ProjectSprite in this repo's fixed point: the billboard's screen box.

        Returns `(x1, x2, ytop, h, istep, tz)` — inclusive column range, the screen row of the
        sprite's top, its exact on-screen pixel height, the DOWNSCALED-texel-per-column DDA step,
        and the view-space depth (SPR-NEAR keys quality tiers off it) — or
        None if the thing is behind the eye, too near, or outside the view. Mirrors DOOM: the two
        rotated coordinates `tz` (depth) and `tx` (lateral) from one cos/sin pair and four
        FixedMuls, then ONE FixedDiv for the scale."""
        cfg = self.cfg
        _cols, dh, _dw, wpx, wph, left, top = art[:7]
        tr_x = _signed((tx_map << 16) - viewx, 32)
        tr_y = _signed((ty_map << 16) - viewy, 32)
        vcos, vsin = self.read_cos(viewangle), self.read_sin(viewangle)
        gxt = _signed(fixed_mul(tr_x & ANGLE_MASK, vcos, 8, 4), 32)
        gyt = -_signed(fixed_mul(tr_y & ANGLE_MASK, vsin, 8, 4), 32)
        tz = gxt - gyt
        if tz < SPRITE_MINZ:
            return None
        # the shared block-FP reciprocal, NOT a true divide: `hex.fixed_div 8,4` is 38,500 fj ops
        # and this runs for every thing that survives the FOV reject. Same re-bless the wall scale
        # took (M13-scalerecip); `proj.scale_recip_div` mirrors this bit for bit (R6).
        xscale = self._scale_recip_div(cfg.PROJECTION << 16, tz)
        gxt2 = -_signed(fixed_mul(tr_x & ANGLE_MASK, vsin, 8, 4), 32)
        gyt2 = _signed(fixed_mul(tr_y & ANGLE_MASK, vcos, 8, 4), 32)
        tx = -(gyt2 + gxt2)
        if abs(tx) > (tz << 2):                       # DOOM's off-screen reject
            return None
        cxf = cfg.CENTERX << 16
        txl = tx - (left << 16)
        x1 = (cxf + _signed(fixed_mul(txl & ANGLE_MASK, xscale, 8, 4), 32)) >> 16
        x2 = ((cxf + _signed(fixed_mul((txl + (wpx << 16)) & ANGLE_MASK, xscale, 8, 4), 32)) >> 16) - 1
        if x2 < 0 or x1 >= cfg.VIEW_W or x2 < x1:
            return None
        gzt = ((tz_map + top) << 16) - viewz
        ytop = (cfg.CENTERY << 16) - _signed(fixed_mul(gzt & ANGLE_MASK, xscale, 8, 4), 32)
        h = _signed(fixed_mul((wph << 16) & ANGLE_MASK, xscale, 8, 4), 32) >> 16
        if h < (MIN_SPRITE_H if min_h is None else min_h):
            return None                               # too small to see
            # ⚠ fj does NOT reach this test for the small case: `sp_tzmin` rejects on DEPTH right
            # after tz, before the lateral multiplies and the reciprocal (EXP-7's shape). The two
            # reject the identical set -- `sprite_tz_min_size` scans for the exact boundary.
        ytop_r = ytop >> 16
        if h > cfg.VIEW_H:
            # SPR-NEAR (owner, 2026-08-05): a TOO-NEAR sprite CLAMPS to the tallest bucket
            # instead of vanishing -- feet planted: the top moves DOWN by the overflow rows so
            # the bottom row stays true, and the emit clips the off-screen part as usual.
            # Integer-row arithmetic, exactly as fj does it after its own >>16.
            ytop_r += h - cfg.VIEW_H
            h = cfg.VIEW_H
        # the texture-column DDA step, through the SAME block-FP reciprocal `proj.scale_recip_div`
        # already implements (not `_recip_div32`, which is a different normalise/shift recipe --
        # reusing the macro that exists beats adding a second one for a sub-texel difference).
        istep = self._scale_recip_div(1 << 16, xscale) // self.downscale
        return x1, x2, ytop_r, h, istep, tz

    @staticmethod
    def _w1r_texel(texels, pal) -> int:
        """The W1R representative texel: the MODE of the texture's BRIGHTER half (true palette
        luminance). W1's plain mode texel is often a near-black one, and colormap composition
        over black is black -- the whole point of W1R (visible runs) then dies in dark sectors
        (measured at spawn: the wood side walls rendered palette 0 at every row). Picking from
        the brighter half keeps the dominant hue but leaves the colormap headroom to work in."""
        lum = {t: sum(pal[t]) for t in set(texels)}
        med = sorted(lum[t] for t in texels)[len(texels) // 2]
        bright = [t for t in texels if lum[t] >= med]
        return ReferenceModel._mode_texel(bright or texels)

    @staticmethod
    def _w1r_texel2(texels, pal, texel1) -> int:
        """W1R-2C -- the SECOND representative texel: the most common texel among those
        RGB-DISTANT from texel1 (so the accent reads as a different embedded material, not a
        shade of the same one), searched in the brighter half like texel1. Falls back to
        texel1: a single-hue texture stays single-hue and the alt runs change nothing."""
        from collections import Counter
        lum = {t: sum(pal[t]) for t in set(texels)}
        med = sorted(lum[t] for t in texels)[len(texels) // 2]
        bright = [t for t in texels if lum[t] >= med]
        r1, g1, b1 = pal[texel1]
        far = [t for t in bright
               if abs(pal[t][0] - r1) + abs(pal[t][1] - g1) + abs(pal[t][2] - b1) >= 60]
        if not far:
            return texel1
        return Counter(far).most_common(1)[0][0]

    @staticmethod
    def _tiny_wall_canvas(texels, th: int, wall_mode: str, pal=None):
        """M13p4a — reduce a full (column-major `texels`, height `th`) wall texture to a tiny synthetic
        canvas: "W1" = 1×1 (the MODE texel, `_mode_texel`) or "W2" = 1×16 (a vertical band strip sampled
        from the real texture's column 0). Both keep the wall raster pipeline (`texcol % tw`, the
        heightmask wrap) completely unchanged — `tw=1` and `th∈{1,16}` (powers of 2) sail through it.
        Shared by both this oracle and `wall_renderer.emit_wall_renderer`'s combined table build, so the
        two can never drift (R6)."""
        if wall_mode == "W1":
            return [ReferenceModel._mode_texel(texels)], 1, 1
        if wall_mode == "W1R":
            # M13-W1R: a TWO-texel canvas -- the BRIGHT-half mode (`_w1r_texel`) plus the
            # RGB-distant second representative (`_w1r_texel2`, W1R-2C's alt colour). The
            # randomization itself is applied at emit time through the colormap (`w1r_runs`),
            # never by sampling more texels.
            assert pal is not None, "wall_mode='W1R' needs the palette for _w1r_texel"
            t1 = ReferenceModel._w1r_texel(texels, pal)
            return [t1, ReferenceModel._w1r_texel2(texels, pal, t1)], 2, 1
        if wall_mode in ("W2", "W2S"):
            # M13-W2S shares W2's 16-texel strip; the tiers differ only in how a wall column MAPS
            # it (W2 = the real v-DDA tiling; W2S = the strip STRETCHED over [top,bottom], see
            # render_wall_frame). Sharing the strip keeps one texture-reduction SSOT (R6).
            col0 = texels[:th]                                  # column-major: the first `th` entries = column 0
            n = 16
            band = [col0[min(th - 1, r * th // n)] for r in range(n)]
            return band, n, 1
        raise ValueError(f"unknown wall_mode: {wall_mode!r}")

    def _flat_base(self, asset_wad, name, cache):
        """The flat-colored representative palette index of a flat (M13a fidelity tier — the cheaper
        floor mode, DESIGN §1/§2): the flat's top-left texel (texel 0,0), pre-colormap. The per-pixel
        distance light (zlight) then shades it. A missing flat (e.g. the sky placeholder before M16) maps
        to WALL_BG so the column is still a defined fill. Cached per frame."""
        key = name.upper()
        if key in cache:
            return cache[key]
        try:
            base = asset_wad.flat(key)[0]
        except (KeyError, ValueError, IndexError):
            base = WALL_BG
        cache[key] = base
        return base

    def _flat_texels(self, asset_wad, name, cache):
        """A flat's raw 64×64 palette-index texels (4096 bytes, row-major `[v*64+u]`, no patch composite,
        no downscale — flats stay native, the `&63` masks wrap them). M13b textured floors sample this per
        pixel. A missing flat (the sky placeholder before M16) → a uniform WALL_BG tile so the column is
        still a defined fill. Cached per frame under a distinct key from `_flat_base`."""
        key = ("texels", name.upper())
        if key in cache:
            return cache[key]
        try:
            data = bytes(asset_wad.flat(name.upper()))
        except (KeyError, ValueError):
            data = b""
        if len(data) != 4096:                                   # pad/truncate to the 64×64 the &63 assumes
            data = (data + bytes([WALL_BG]) * 4096)[:4096]
        cache[key] = data
        return data

    def plane_light_row(self, light: int, distance: int) -> int:
        """R_MapPlane's distance-based colormap-row select (zlight): bucket the 16.16 `distance` by
        `>> LIGHTZSHIFT` (clamped to MAXLIGHTZ-1) and the sector `light` by `>> LIGHTSEGSHIFT` (clamped to
        LIGHTLEVELS-1); the further the span, the darker the row. Distinct from the per-seg wall light
        (which is `light >> LIGHT_SHIFT` directly)."""
        zidx = min(MAXLIGHTZ - 1, distance >> LIGHTZSHIFT)
        lvl = min(LIGHTLEVELS - 1, light >> LIGHTSEGSHIFT)
        return self.zlight[lvl][zidx]

    def _plane_pixel(self, colormap, planeheight: int, light: int, flat_base: int, y: int) -> int:
        """One flat-colored floor/ceiling pixel at screen row y (M13a): `distance =
        FixedMul(planeheight, yslope[y])` (planeheight = |plane_z - viewz|, 16.16), distance-light the
        flat's base index. The textured u,v DDA replaces `flat_base` with a per-pixel sample at M13b."""
        distance = fixed_mul(planeheight, self.yslope[y], 8, 4)
        return colormap[self.plane_light_row(light, distance)][flat_base]

    def _zidx_band_walk(self, planeheight: int, rows: list) -> list:
        """M13pS2 (LS2, the F4 [re-bless]): the per-row zidx (MAXLIGHTZ distance bucket) for a WINDOW
        of screen rows, computed via ONE exact evaluation (seeding the window's first row bit-for-bit,
        the same FixedMul `_plane_pixel` uses) plus a cheap per-row THRESHOLD WALK for every
        subsequent row — the SAME block-FP reciprocal(planeheight) the wall-side divide-elimination
        campaign already shares (`_recip_div32`, perf #11's table), stepping the zidx bucket boundary
        by `step = 16*recip` instead of re-evaluating FixedMul per row (that per-row FixedMul, at
        ~11.5k ops each, is exactly what LS2 exists to avoid — see docs/m13p-procedural-plan.md's pS
        section). `rows` MUST be a run of screen rows in EMISSION order (ascending y) drawn from a
        SINGLE monotonic window: `yslope[]` increases with y in the ceiling half and decreases with y
        in the floor half (never monotonic across the whole screen), so a window may not straddle the
        horizon row.
        ⚠ Validated (`scratchpad/proto_plane_bands.py`) against every REAL E1M1 spawn-frame
        planeheight: max |approx-exact| shift = 1 row — this is the ledger's accepted F4 bound, not an
        exact match; re-bless whatever goldens change. NOT validated for implausibly tall sectors
        (~3000+ world units, where 32-bit FixedMul itself wraps) — E1M1's tallest is 495 units; a
        future map needing taller sectors should re-run the prototype's synthetic sweep first."""
        if not rows:
            return []
        if planeheight == 0:
            return [0] * len(rows)
        # M13pS2 straddle split: yslope is non-decreasing on [0, CENTERY) and non-increasing on
        # [CENTERY, H) (peak at CENTERY-1, with ys[CENTERY-1]==ys[CENTERY]); a window crossing
        # CENTERY (a floor above the eye / a ceiling below it -- negative-viewz areas produce these)
        # violates the single-monotonic-window contract below, so walk each half separately. The fj
        # stream leaf (seg_pass1_leaf_body_stream) mirrors this split at its build_bands call sites.
        P = self.cfg.CENTERY
        if rows[0] < P <= rows[-1]:
            k = P - rows[0]
            return self._zidx_band_walk(planeheight, rows[:k]) + self._zidx_band_walk(planeheight, rows[k:])
        recip = self._recip_div32(planeheight)
        step = 16 * recip
        y0 = rows[0]
        zidx = min(MAXLIGHTZ - 1, fixed_mul(planeheight, self.yslope[y0], 8, 4) >> LIGHTZSHIFT)
        ascending = len(rows) < 2 or self.yslope[rows[1]] >= self.yslope[y0]
        threshold_hi = step * (zidx + 1)
        threshold_lo = step * zidx
        out = [zidx]
        for y in rows[1:]:
            ys = self.yslope[y]
            if ascending:
                while zidx < MAXLIGHTZ - 1 and ys >= threshold_hi:
                    zidx += 1
                    threshold_hi += step
            else:
                while zidx > 0 and ys < threshold_lo:
                    zidx -= 1
                    threshold_lo -= step
            out.append(zidx)
        return out

    def render_wall_frame(self, state: SimState, scene: Scene, *, floor_texturing: bool = True,
                          wall_mode: str = "textured", floor_mode_ft1: bool = False,
                          plane_near: bool = False, planes_out: list | None = None,
                          wall_noise: bool = False, sky: bool = False,
                          near_steps: bool = False, things: bool = False,
                          sprite_wad=None, things_out: list | None = None,
                          bbox_cull: bool = False, stack_steps: bool = False,
                          steps_out: list | None = None,
                          deg_things: tuple | None = None, deg_sliver: int | None = None,
                          deg_stack_scale: int | None = None, deg_mark: int | None = None,
                          deg_lip_scale: int | None = None,
                          thing_positions=None, thing_hidden=None,
                          degrade: bool = False) -> bytes:
        """The first rendered 3D frame, TEXTURED: composite every visible wall over the floor/ceiling
        visplanes (R_RenderBSPNode + R_StoreWallRange + R_RenderSegLoop). Walk the BSP front-to-back; for
        each seg: `wall_x_range` (skip culled) -> `wall_setup`/`_wall_offset` -> DOOM's scale INTERPOLATION
        (scale at x1, linear `scalestep` to x2 via a plain truncated divide — NOT FixedDiv — so the fj
        renderer must divide the same way) -> per column the textured wall column:
          * texture u = `(rw_offset - FixedMul(finetangent[rw_centerangle + xtoviewangle[x]], rw_distance))
            >> 16`, taken mod the texture width;
          * the vertical texture DDA (M11b `render_textured_column`, 8.8): `iscale` = FixedDiv(1, scale) /
            downscale (downscaled-texels per screen pixel), `texturemid` = (ceil - viewz) / downscale (the
            texel-v at the horizon), `frac0` = texturemid + (top - CENTERY)·iscale, both converted 16.16->8.8;
          * `wall_screen_span` gives the [top, bottom] rows, clipped to [0, VIEW_H).
        Front-to-back **solid-seg clipping** via a per-column `drawn` flag (one-sided walls opaque). A wall
        with no middle texture falls back to the flat `WALL_BG` shade. **Ceiling/floor are M13 visplanes**:
        when a column is first claimed by a one-sided wall covering screen rows [top,bottom], the rows ABOVE
        (0..top-1) record that sector's ceiling flat and the rows BELOW (bottom+1..H-1) its floor flat. After
        the walk they are rasterized: `floor_texturing=True` (M13b/default) = the full DOOM perspective u,v
        span raster (R_MapPlane/R_DrawSpan — per-row spans, `yslope`/`distscale`/`basexscale` DDA, distance-
        lit); `floor_texturing=False` (M13a) = the cheaper flat-colored tier (the flat's base index per
        `_plane_pixel`). `wall_mode` (M13p4a) picks the wall TEXTURE tier: "textured" (default, the real
        texture) or "W1"/"W2" (a tiny synthetic canvas — see `_tiny_wall_canvas`); the rest of the wall
        raster (texture-v DDA, heightmask, screen span) is untouched, just sampling a smaller texture.

        `plane_near` (M13-2S rung 3a, OPT-IN because it changes pixels): the plane record above comes
        from whichever wall CLAIMS the column, and since two-sided linedefs draw no wall, the claimer
        is usually a wall in another room -- measured at E1M1 spawn, the flat the player is standing
        on (AQF054) appeared in 27 of 160 columns; the rest took other rooms' flat, height AND light
        ("the close floor in the middle is gray, yet the sides are yellow"). With `plane_near` the
        nearest MARKING seg (two-sided included) sets the record instead, marking being DOOM's
        R_StoreWallRange markfloor/markceiling test: the two sides differ in (height, light, flat).
        The region EXTENTS still come from the one-sided wall, so each column keeps ONE ceiling and
        one floor region and there are no upper/lower wall runs (that is rung 3b). `planes_out`, if
        given, receives the per-column plane records
        (ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff) for the gates to inspect.
        Returns W*H packed palette-index bytes (row-major, D3); the fj renderer reproduces this
        bit-exactly (D12)."""
        cfg = self.cfg
        # 25M-CAP: `degrade=True` turns on the whole certified adaptive-degradation package;
        # the individual deg_* kwargs stay as research overrides (any explicit value wins --
        # CR-2026-08: the sentinel is None, not falsiness, so an explicit 0 = "this lever OFF").
        if degrade:
            if deg_things is None:
                deg_things = (DEG_SOFT_SCENERY, DEG_MINH2_SCENERY,
                              DEG_SOFT_MON, DEG_MINH2_MON)
            if deg_sliver is None:
                deg_sliver = DEG_SLIVER_W
            if deg_stack_scale is None:
                deg_stack_scale = DEG_STACK_SCALE
            if deg_mark is None:
                deg_mark = DEG_PNEAR
            if deg_lip_scale is None:
                deg_lip_scale = DEG_LIP_SCALE
        deg_sliver = deg_sliver or 0
        deg_stack_scale = deg_stack_scale or 0
        deg_mark = deg_mark or 0
        deg_lip_scale = deg_lip_scale or 0
        b_minh = DEG_SPRB_MINH if degrade else 0
        W, H = cfg.VIEW_W, cfg.VIEW_H
        fb = bytearray(cfg.FB_SIZE)                          # zero-init; visplanes + walls fill every column
        colormap = scene.asset_wad.colormap()
        flatcache: dict = {}
        lds = scene.map_wad.linedefs(scene.mapname)
        sds = scene.map_wad.sidedefs(scene.mapname)
        secs = scene_sectors(scene)
        verts = scene.cmap.vertexes
        texcache: dict = {}

        viewx, viewy, viewangle = state.x, state.y, state.angle
        # W1R-ANCHOR: the pattern key is (x + this) -- viewangle * 640 columns-per-turn >> 32
        # (= *5 >> 25 exactly), so TURNING slides the pattern with the walls instead of
        # re-rolling it every frame. fj computes the identical value once per frame (wnoff).
        w1r_xoff = ((viewangle & 0xFFFFFFFF) * 5) >> 25
        px = _signed(state.x, 32) >> 16
        py = _signed(state.y, 32) >> 16
        # the eye z = the player's own sector floor + VIEWHEIGHT
        pss = scene.cmap.subsectors[self.point_in_subsector(scene.cmap, px, py)]
        viewz = self.view_z(self._seg_sector(lds, sds, secs, scene.cmap.segs[pss.firstseg]).floor_h)
        viewz_world = _signed(viewz, 32) >> 16
        centery, ds = cfg.CENTERY, self.downscale

        # per-column visplane records (claimed columns only): ceiling = rows [0, ceil_hi], floor = [floor_lo, H-1]
        ceil_hi = [-1] * W                                   # -1 / H = "no region in this column"
        floor_lo = [H] * W
        col_ch = [0] * W; col_fh = [0] * W; col_lt = [0] * W            # per-col ceil/floor height + sector light
        col_cf: list = [None] * W; col_ff: list = [None] * W           # per-col ceil/floor flat name

        drawn = bytearray(cfg.VIEW_W)                        # per-column solid-seg clip (1 = already drawn)
        pclaim = bytearray(cfg.VIEW_W)                        # M13-2S rung 3a: plane record claimed?
        # V3: this column's upper/lower step faces, nearest first (write-once slots; V5 stacks
        # up to V5_STACK per side when `stack_steps`, each entry carrying the boundary's BACK
        # sector for the region behind it)
        n_stack = V5_STACK if stack_steps else 1
        ups: list = [[] for _ in range(W)]
        los: list = [[] for _ in range(W)]
        n_face = [0]                  # V3: face-carrying boundaries used, vs STEP_SEG_BUDGET
        n_claimed = 0                                         # ... and its two STOP conditions, both of
        n_ts = 0                                              # which the fj mirrors (see below)
        n_wdrawn = 0                  # columns closed by a WALL (fj: n_drawn -> the `full` latch).
                                      # ⚠ NOT n_claimed: plane ATTRIBUTION completes long before
                                      # the walls do, and a sprite can still record into any
                                      # column no wall has drawn -- the thing pre-pass stop must
                                      # use THIS counter (the (1329,1065) one-step vanish bug).
        # V4 THINGS — one write-once SPRITE FRAGMENT per column, `(y0, runs, light_row)`. Recorded
        # during the walk, at the moment it reaches the thing's own subsector, and only into columns
        # no wall has claimed yet: front-to-back order is what makes "the first writer is the
        # nearest" true, and it is also the whole occlusion test (a wall nearer than the thing has
        # already claimed the column, so the thing simply cannot record there). That is the same
        # trick V3's step faces use, and it is what lets a WRITE-ONCE, forward-only column protocol
        # show sprites at all: DOOM draws them last, back-to-front, and this cannot.
        sfrag: list = [None] * W
        sfrag2: list = [None] * W     # V4b: the SECOND (farther) fragment, drawn under slot A
        n_thing = 0                   # ... against THING_BUDGET: scenery (decor + pickups)
        n_hd = 0                      # OPTION B: accepted TALL-bucket things granted the HD bake
        n_mon = 0                     # ... against MONSTER_BUDGET: monsters, counted SEPARATELY so
        spr_cache: dict = {}          #     walk order can never spend a monster's slot on a barrel
        things_by_ss: dict = {}
        ss_first: dict = {}
        if things:
            assert sprite_wad is not None, "things=True needs sprite_wad (the fixture wad has none)"
            # M14-e: `thing_positions` overrides where the drawable things ARE, in drawable order
            # (index i = the i-th thing whose type has a sprite). Without it the WAD's spawn
            # positions are used, which is every gate and golden this repo has.
            # ⚠ CR-2026-08 (RM-1/ST-1) — this list is THE index space: `thing_positions`, the
            # `thvis` wire slots and `baked_thing_mask` are all keyed by position in it, so the
            # emitter and the oracle must build it with the SAME predicate. They did not. The
            # emitter asks `things.drawable_things` (i.e. `sprite_art(...) is not None`, which is
            # also None when the TYPE is in the table but the WAD HAS NO LUMP for it); this asked
            # only whether the type is in `THING_SPRITE`. The two coincide on the full Freedoom
            # art wad -- which is why every gate passes -- and diverge on any wad missing a lump,
            # shifting every index after the first absent sprite in one mirror only.
            _drawable, _ = drawable_things(self, scene.map_wad.things(scene.mapname),
                                           sprite_wad, spr_cache)
            # M14.5: the BAKED/RUNTIME split, from the SSOT both mirrors read, computed at SPAWN
            # positions -- a thing's class is a property of the thing, not of where it now stands.
            _baked = baked_thing_mask(self, scene.cmap, _drawable, MONSTER_TYPES)
            _drawable_spawn = _drawable          # the classification's own (pre-override) list
            if thing_positions is not None:
                assert len(thing_positions) == len(_drawable), (
                    f"thing_positions has {len(thing_positions)} entries, "
                    f"{scene.mapname} has {len(_drawable)} drawable things")
                # ⚠ A BAKED thing is CODE inside its leaf: fj cannot move it, and the wire does not
                # even carry its position. Moving one here would compare two different worlds.
                _moved = [i for i, (t, (px, py)) in enumerate(zip(_drawable, thing_positions))
                          if _baked[i] and (px, py) != (t.x, t.y)]
                assert not _moved, (
                    f"thing_positions moves BAKED things {_moved[:8]} -- they are baked into their "
                    f"leaf's code and cannot move (see doomfj.things.baked_thing_mask)")
                _drawable = [replace(t, x=px, y=py)
                             for t, (px, py) in zip(_drawable, thing_positions)]
            # M14.5 §3.3: the visibility flags. `thing_hidden` is a set of DRAWABLE indices the
            # host has removed from the world (picked up, destroyed). Only a baked VANISHABLE thing
            # has a flag to clear, and asking to hide anything else is a host bug, not a picture.
            _hidden = frozenset(thing_hidden or ())
            if _hidden:
                _slots = vanishable_slots(_drawable_spawn, _baked, VANISHABLE_TYPES)
                _bad = sorted(_hidden - set(_slots))
                assert not _bad, (
                    f"thing_hidden names things {_bad[:8]} that have no visibility flag -- only "
                    f"BAKED VANISHABLE things do (see doomfj.things.vanishable_slots)")
            # ⚠ BAKED FIRST, THEN RUNTIME, per leaf -- the ONE order fj can produce, because the
            # baked things are call sites emitted in the leaf and the runtime ones are a list walked
            # after them. It is wad order within each class, and at spawn every leaf holds only one
            # class, so this is wad order outright (§4b of docs/handoff-m14_5.md).
            for _pass in (True, False):
                for _di, (t, b) in enumerate(zip(_drawable, _baked)):
                    if b is not _pass or _di in _hidden:
                        continue
                    # binding is ALREADY position-driven, so M14-e needs no new logic here
                    things_by_ss.setdefault(
                        self.point_in_subsector(scene.cmap, t.x, t.y), []).append(t)
            for _si, _ss in enumerate(scene.cmap.subsectors):
                if _ss.numsegs and _si in things_by_ss:
                    ss_first[_ss.firstseg] = _si              # the walk's arrival point for its things
        # M13-15M: the bbox wedge cull's oracle half. The gate set and boxes come from the SSOT
        # (bbox_gate_boxes) — thing-live subtrees get inflated boxes, so this is computed whether or
        # not `things` is on (the fj bake does the same).
        # M14-a: the inflated set is now `thing_live_subsectors` (every subtree a thing COULD enter)
        # rather than the spawn occupancy — a thing that walks into an un-inflated subtree would
        # otherwise lose its off-wedge columns with no other symptom. The emitter's half changed in
        # the same commit; these two must agree to the node or the mirrors diverge.
        _gate = None
        if bbox_cull:
            _tss = thing_live_subsectors(scene.cmap, lds, sds, secs)
            _gate = bbox_gate_boxes(scene.cmap, thing_subsectors=_tss)
        # debug stats (cheap, always on): who reached the thing pre-pass and what stopped it --
        # the (1329,1065) vanishing-sprites diagnosis needed exactly this visibility
        self._thing_stats = {"ss_total": len(ss_first), "ss_arrived": 0, "th_arrived": 0,
                             "th_claim_stopped": 0}
        for seg_i in self.visible_segs(scene.cmap, px, py, bbox_gate=_gate,
                                       va=viewangle & 0xFFFFFFFF,
                                       # CR-2026-08 (PJ-1): the wedge test floors AFTER combining,
                                       # so it needs the fraction px/py threw away.
                                       eye16=(_signed(state.x, 32), _signed(state.y, 32))
                                       ):  # front-to-back order
            if things and seg_i in ss_first:
                self._thing_stats["ss_arrived"] += 1
                for t in things_by_ss[ss_first[seg_i]]:
                    self._thing_stats["th_arrived"] += 1
                    if n_wdrawn == W:
                        self._thing_stats["th_claim_stopped"] += 1
                        break                            # every column WALL-drawn: no fragment
                                                         # can land anywhere (monotone stop)
                    # TWO budgets, not one. Slots are handed out in BSP walk-arrival order, which is
                    # NOT distance order (EXP-8a), so a single counter let six 1-pixel bonus dots
                    # spend the frame's budget while 24 monsters were turned away. Both counters are
                    # monotone, so fj still latches `tstop` once BOTH are spent.
                    mon = t.type in MONSTER_TYPES
                    if (n_mon >= MONSTER_BUDGET) if mon else (n_thing >= THING_BUDGET):
                        continue                         # ... `continue`, not `break`: a scenery
                    art = self.sprite_art(sprite_wad, t.type, spr_cache)   # budget must not stop the
                    if art is None:                                        # walk finding a monster
                        continue
                    tss = scene.cmap.subsectors[ss_first[seg_i]]
                    tsec = self._seg_sector(lds, sds, secs, scene.cmap.segs[tss.firstseg])
                    # 25M-CAP GRADUATED ACCEPTANCE: once the frame has accepted its first
                    # (nearest -- the walk is front-to-back) SOFT things of a category, the
                    # min-size bar rises, so far specks stop paying the record loop exactly on
                    # the frames that are already heavy. Light frames never reach SOFT and keep
                    # every speck. Monsters keep their own (looser) pair, per the owner's policy.
                    minh_ = MIN_SPRITE_H_MONSTER if mon else MIN_SPRITE_H
                    if deg_things is not None:
                        soft_s, minh2_s, soft_m, minh2_m = deg_things
                        if mon and n_mon >= soft_m:
                            minh_ = minh2_m
                        elif not mon and n_thing >= soft_s:
                            minh_ = minh2_s
                    pr = self.project_thing(viewx, viewy, viewangle, viewz,
                                            t.x, t.y, tsec.floor_h, art, minh_)
                    if pr is None:
                        continue
                    if mon:
                        n_mon += 1
                    else:
                        n_thing += 1
                    tx1, tx2, ytop, th_px, istep, pr_tz = pr
                    # SPR-NEAR: coarse bake only for things both SHORT and beyond the radius
                    far_ = bool(DEG_SPR_NEAR_TZ) and pr_tz > (DEG_SPR_NEAR_TZ << 16)
                    bkt = sprite_bucket(th_px, H)
                    hb = sprite_bucket_height(bkt, H)
                    # OPTION B (DEG_HD_BUDGET): the first N accepted tall things keep the HD
                    # bake; the rest use the cap-12 low-res blocks. Counted per THING right
                    # here (post-acceptance, pre-columns), exactly where fj counts it.
                    hd_ok = hb >= SPRITE_HD_H
                    if hd_ok and DEG_HD_BUDGET:
                        if n_hd < DEG_HD_BUDGET:
                            n_hd += 1
                        else:
                            hd_ok = False
                    ytop_b = ytop + th_px - hb                # FEET planted: the bucket moves the top
                    lr = self.wall_light_row(self.wall_lightnum(tsec.light, 0), hb, art[4])
                    frac = (max(0, tx1) - tx1) * istep
                    for x in range(max(0, tx1), min(W, tx2 + 1)):
                        u = min(art[2] - 1, max(0, frac >> 16))
                        frac += istep
                        if drawn[x] or sfrag2[x] is not None:
                            continue                     # V4b: both fragment slots spent
                        # V4-HD: tall buckets sample the full-res column with the deeper cap
                        # (unless OPTION B's HD budget already went to nearer things);
                        # 20M-RECOVERY: SHORT buckets take the coarse low-res cap instead
                        st = (self.sprite_strip(art[7][u], art[8], hb, cap=SPRITE_RUN_CAP_HD)
                              if hd_ok else
                              self.sprite_strip(art[0][u], art[1], hb,
                                                cap=DEG_SPR_LOWRES_CAP)
                              if (hb < DEG_SPR_LOWRES_H and far_) else
                              self.sprite_strip(art[0][u], art[1], hb,
                                                cap=DEG_SPR_MID_CAP))
                        if st is None:
                            continue
                        # V4b: TWO write-once fragment slots per column, filled in walk-arrival
                        # (~front-to-back) order -- slot A is the near sprite, slot B the one
                        # behind it. One slot chopped the farther sprite's whole column wherever
                        # two overlapped in x (the owner's (664,291) frame: a tall zombie lost
                        # its head to a potion's columns).
                        if sfrag[x] is None:
                            sfrag[x] = (ytop_b + st[0], st[1], lr)
                        elif not b_minh or hb >= b_minh:
                            # 25M-CAP B-GATE: slot B only for fragments tall enough to plausibly
                            # show through slot A's gaps; a small/far B fragment is ~always
                            # occluded. The slot stays OPEN, so a later (taller) thing may claim
                            # it -- fj tests the same baked bucket height before its bank walk.
                            sfrag2[x] = (ytop_b + st[0], st[1], lr)
            seg = scene.cmap.segs[seg_i]
            ld = lds[seg.linedef]
            if ld.back != -1:
                if not plane_near:
                    continue                                 # two-sided (opening/window): not a solid wall
                # M13-2S rung 3a — a two-sided seg paints no wall here, but it still BOUNDS the near
                # plane surface, and that is what the owner's "the close floor in the middle is gray,
                # yet the sides are yellow" bug is: the plane record used to come from whichever
                # (necessarily one-sided, hence distant) wall claimed the column, so a single
                # continuous floor was painted with several other rooms' flat/height/light.
                # MARKING test = DOOM's R_StoreWallRange markfloor/markceiling: the two sides differ
                # in the band-bank key (height, light, flat). When they are equal the seg is skipped
                # (a baked compile-time flag in fj) and that is free of error BY CONSTRUCTION --
                # attributing the plane to the back sector then renders identically.
                fsec = self._seg_sector(lds, sds, secs, seg)
                bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
                if ((fsec.ceil_h, fsec.light, fsec.ceil_tex)
                        == (bsec.ceil_h, bsec.light, bsec.ceil_tex)
                        and (fsec.floor_h, fsec.light, fsec.floor_tex)
                        == (bsec.floor_h, bsec.light, bsec.floor_tex)):
                    continue
                # the two STOP conditions the fj shares (one `tsstop` flag there): every column
                # attributed, or the per-frame seg BUDGET spent. The budget is what bounds the cost
                # when part of the view is open sky/void so the first condition never fires --
                # see config.PNEAR_SEG_BUDGET.
                # V5-DROP-P2 (R48's sibling): the stop for PIECE-carrying segs is WALL-drawn
                # completion (pieces record into attributed-but-undrawn columns); LIGHT-ONLY
                # segs -- attribution was their whole job -- still stop at claim-completion.
                um_, lm_ = self.v5_side_modes(fsec, bsec, sky)
                if n_wdrawn == cfg.VIEW_W or n_ts >= (deg_mark or PNEAR_SEG_BUDGET):
                    continue
                if um_ == 0 == lm_ and n_claimed == cfg.VIEW_W:
                    continue
                # SMUDGE FIX part 2 (2026-08-09): the PIECE-seg idle stop. With the count budget
                # at never-binds (DEG_PNEAR 4095, emitter-asserted), the cost bound moves here:
                # once every column
                # is attributed AND the face budget is spent, a piece-carrying seg's scan is
                # pure reads (face_seg is false, pclaim[] all set) -- skipping it is
                # PIXEL-NEUTRAL by construction, it only cuts the idle tail (~+14M/frame
                # measured on stock E1M1 without this stop).
                if n_claimed == cfg.VIEW_W and n_face[0] >= STEP_SEG_BUDGET:
                    continue
                n_ts += 1
                rng2 = self.wall_x_range(viewx, viewy, viewangle, seg, verts)
                if rng2 is None:
                    continue
                # V3 - STEP FACES: the upper/lower wall pieces of a two-sided boundary (stair
                # risers, ledge fronts, door lintels). Without them a step you can walk up is
                # invisible: the floor just changes colour where it rises.
                # Only the NEAREST run per column is kept -- write-once slots, and the walk is
                # front-to-back so the first writer IS the nearest -- and only the first
                # STEP_SEG_BUDGET boundaries that actually HAVE a face may place one. That second
                # bound is what makes the cost viewpoint-INDEPENDENT: a face-carrying seg pays a
                # full ~93k wall_scale_setup, and at a heavy viewpoint 128 marking segs would all
                # otherwise qualify. Measured: only 2 boundaries at spawn have a face at all.
                # V5-DROP: um_/lm_ (0 none / 1 riser / 2 lip) computed above, before the stop
                face_seg = near_steps and (um_ or lm_) and n_face[0] < STEP_SEG_BUDGET
                if face_seg:
                    n_face[0] += 1
                    rwn2, rwd2 = self.wall_setup(viewx, viewy, seg, verts)
                    # The face scale is INTERPOLATED across the seg, exactly as the one-sided wall
                    # path's is (fj: proj.wall_scale_setup_m once, then `scale += scalestep` per
                    # column) -- and exactly as DOOM's own rw_scale is. An EXACT per-column
                    # scale_from_global_angle is what a first draft of this used, and it is not
                    # affordable: ~40k fj ops per COLUMN against ~93k once per SEG. Measured
                    # (scratchpad/v3_pop.py) the interpolation moves 1 of 108 projected rows at
                    # spawn and 10 of 210 at the worst viewpoint, each by a row.
                    sc2 = self.scale_from_global_angle(
                        (viewangle + self.xtoviewangle[rng2[0]]) & ANGLE_MASK, viewangle, rwn2, rwd2)
                    if rng2[1] > rng2[0]:
                        sc2b = self.scale_from_global_angle(
                            (viewangle + self.xtoviewangle[rng2[1]]) & ANGLE_MASK, viewangle,
                            rwn2, rwd2)
                        d2, sp2 = sc2b - sc2, rng2[1] - rng2[0]
                        st2 = -(abs(d2) // sp2) if d2 < 0 else d2 // sp2   # trunc toward zero
                    else:
                        st2 = 0
                    # OPTION A (DEG_DDA_FACES): per-seg frac bases + steps replace the four
                    # per-column wall_screen_span multiplies. EXACT by the mapmul identity:
                    # frac = CY - wt*scale accumulates mod 2^32 with no shift, so stepping by
                    # -wt*st2 reproduces the per-column product bit for bit (zero px change).
                    if DEG_DDA_FACES:
                        _w4 = (fsec.ceil_h - viewz_world, bsec.ceil_h - viewz_world,
                               bsec.floor_h - viewz_world, fsec.floor_h - viewz_world)
                        _CY = cfg.CENTERY << 16
                        _fr = [(_CY - w * (sc2 & ANGLE_MASK)) & 0xFFFFFFFF for w in _w4]
                        _fst = [(w * (st2 & ANGLE_MASK)) & 0xFFFFFFFF for w in _w4]
                for x in range(rng2[0], rng2[1]):
                    if face_seg and not drawn[x] and not (
                            (not um_ or len(ups[x]) >= n_stack)
                            and (not lm_ or len(los[x]) >= n_stack)):
                        sc2m = sc2 & ANGLE_MASK
                        # V5 STORED-VALUE SEMANTICS (the fj slot's exact bytes, R6): a piece is
                        # stored CLIPPED to the screen, with two off-screen SENTINELS -- fully
                        # ABOVE = (1, 0) (the region behind it starts at row ~0), fully BELOW =
                        # (255, 254) (the region behind it is off-screen). The piece-2 monotone
                        # clamp reads the STORED previous value, sentinel included, so oracle
                        # and fj can never disagree about a clamped piece.
                        Hs = cfg.VIEW_H - 1
                        # 25M-CAP STACK FAR GATE: the SECOND stacked piece only for boundaries
                        # near enough to matter (scale = projection/tz, so the compare is one
                        # register fj already holds). Near stairs keep their two risers.
                        stk2 = deg_stack_scale == 0 or sc2m >= deg_stack_scale
                        # V5-DROP far gate: a lip farther than deg_lip_scale is sub-pixel
                        lip2 = deg_lip_scale == 0 or sc2m >= deg_lip_scale
                        if um_ and (um_ == 1 or lip2) \
                                and len(ups[x]) < n_stack and (not ups[x] or stk2):
                            if DEG_DDA_FACES:
                                t0 = _signed(_fr[0], 32) >> 16
                                ub = _signed(_fr[1], 32) >> 16 if um_ == 1 else 0
                            else:
                                t0, _b = self.wall_screen_span(fsec.ceil_h, fsec.ceil_h,
                                                               viewz, sc2m)
                                _t, ub = (self.wall_screen_span(fsec.ceil_h, bsec.ceil_h,
                                                                viewz, sc2m)
                                          if um_ == 1 else (0, 0))
                            # V5-DROP: a LIP piece is the near ceiling's edge row alone -- the
                            # region-behind then paints the far ceiling below it
                            a, b = (t0, ub - 1) if um_ == 1 else (t0, t0)
                            if ups[x]:
                                # a farther boundary's face clips BELOW the nearer one's stored
                                # end (DOOM's descending ceilingclip -> the splice stays monotone)
                                a = max(a, ups[x][-1][1] + 1)
                            if a <= b:
                                st_ = ((1, 0) if b < 0 else (255, 254) if a > Hs
                                       else (max(a, 0), min(b, Hs)))
                                ups[x].append((st_[0], st_[1], fsec,
                                               fsec.ceil_h - bsec.ceil_h, bsec))
                        if lm_ and (lm_ == 1 or lip2) \
                                and len(los[x]) < n_stack and (not los[x] or stk2):
                            if DEG_DDA_FACES:
                                lt = _signed(_fr[2], 32) >> 16 if lm_ == 1 else 0
                                b0 = _signed(_fr[3], 32) >> 16
                            else:
                                lt, _b2 = (self.wall_screen_span(bsec.floor_h, fsec.floor_h,
                                                                 viewz, sc2m)
                                           if lm_ == 1 else (0, 0))
                                _t2, b0 = self.wall_screen_span(fsec.floor_h, fsec.floor_h,
                                                                viewz, sc2m)
                            # V5-DROP: a LIP piece is the near floor's edge row alone (the
                            # tread-lip line); the region-behind paints the far floor above it
                            a, b = (lt, b0) if lm_ == 1 else (b0, b0)
                            if los[x]:
                                # ... and ABOVE the nearer one's stored start (ascending floorclip)
                                b = min(b, los[x][-1][0] - 1)
                            if a <= b:
                                st_ = ((1, 0) if b < 0 else (255, 254) if a > Hs
                                       else (max(a, 0), min(b, Hs)))
                                los[x].append((st_[0], st_[1], fsec,
                                               bsec.floor_h - fsec.floor_h, bsec))
                    if not pclaim[x]:
                        col_ch[x], col_fh[x], col_lt[x] = fsec.ceil_h, fsec.floor_h, fsec.light
                        col_cf[x], col_ff[x] = fsec.ceil_tex, fsec.floor_tex
                        pclaim[x] = 1
                        n_claimed += 1
                    if face_seg:
                        sc2 = (sc2 + st2) & ANGLE_MASK     # the DDA advances on EVERY column
                        if DEG_DDA_FACES:                  # OPTION A: the fracs advance with it
                            _fr = [(f - d) & 0xFFFFFFFF for f, d in zip(_fr, _fst)]
                continue
            rng = self.wall_x_range(viewx, viewy, viewangle, seg, verts)
            if rng is None:
                continue
            x1, x2, rw_angle1 = rng
            rw_normalangle, rw_distance = self.wall_setup(viewx, viewy, seg, verts)
            scale = self.scale_from_global_angle((viewangle + self.xtoviewangle[x1]) & ANGLE_MASK,
                                                 viewangle, rw_normalangle, rw_distance)
            if x2 > x1:
                scale2 = self.scale_from_global_angle((viewangle + self.xtoviewangle[x2]) & ANGLE_MASK,
                                                      viewangle, rw_normalangle, rw_distance)
                diff, span = scale2 - scale, x2 - x1
                scalestep = -(abs(diff) // span) if diff < 0 else diff // span   # trunc toward zero
            else:
                scalestep = 0
            sec = self._seg_sector(lds, sds, secs, seg)
            light_row = max(0, min(COLORMAP_LIGHTS - 1, sec.light >> LIGHT_SHIFT))
            sd = sds[ld.front if seg.side == 0 else ld.back]
            rw_offset, rw_centerangle = self._wall_offset(viewx, viewy, viewangle, seg, verts,
                                                          rw_normalangle, rw_angle1, sd)
            tex = self._wall_texture(scene.asset_wad, sd.middle, texcache, wall_mode=wall_mode)
            # M13-WPXLIGHT: DOOM's per-seg fake contrast (orientation only -> a baked constant)
            wall_contrast = self.wall_fake_contrast(verts[seg.v1], verts[seg.v2])
            worldtop = sec.ceil_h - viewz_world              # world units the ceiling is above the eye
            flat_fill = colormap[light_row][WALL_BG]
            for x in range(x1, x2):
                if not drawn[x]:
                    top, bottom = self.wall_screen_span(sec.ceil_h, sec.floor_h, viewz, scale & ANGLE_MASK)
                    top = max(0, top)
                    bottom = min(cfg.VIEW_H - 1, bottom)
                    if top <= bottom and wall_mode == "WPX":
                        # M13-WPX: the 1×1 run-list baked for this column's EXACT height -- one
                        # texture texel per screen pixel, run-merged, last run ending at `bottom`.
                        # M13-WPXLIGHT: the colormap row is DOOM's scalelight (near = bright) plus
                        # fake contrast, both derived from h + per-seg constants, so both are free.
                        texels_p, th_p, tw_p = tex if tex is not None else (None, 0, 0)
                        wrow = self.wall_light_row(self.wall_lightnum(sec.light, wall_contrast),
                                                   bottom - top + 1, sec.ceil_h - sec.floor_h)
                        ya = top
                        for ri, (rel, c) in enumerate(self.wpx_strip(texels_p, th_p, tw_p, colormap,
                                                                     wrow, bottom - top + 1)):
                            # V1: the pseudo-random grain -- one colormap step-down per RUN, keyed on
                            # the screen column, so the fj emit loop needs exactly one cm.apply per
                            # pair it was already emitting (no run splitting, no extra bank).
                            cc = colormap[self.wall_noise(x, ri)][c] if wall_noise else c
                            for y in range(ya, top + rel):
                                fb[y * cfg.VIEW_W + x] = cc
                            ya = top + rel
                    elif top <= bottom and wall_mode == "W2S":
                        # M13-W2S: band j of the strip covers rows [top + (j*h>>4), top + ((j+1)*h>>4))
                        # with h = bottom-top+1 -- an exact integer split, no v-DDA, no divide, and a
                        # function of (seg, top, bottom) ALONE so the ditto structure survives.
                        texels_s, th_s, tw_s = tex if tex is not None else ([WALL_BG], 1, 1)
                        hh = bottom - top + 1
                        for j in range(th_s):
                            ya = top + ((j * hh) >> 4 if th_s == 16 else (j * hh) // th_s)
                            yb = top + (((j + 1) * hh) >> 4 if th_s == 16 else ((j + 1) * hh) // th_s)
                            c = colormap[light_row][texels_s[j]]
                            for y in range(ya, min(yb, bottom + 1)):
                                fb[y * cfg.VIEW_W + x] = c
                    elif top <= bottom and wall_mode == "W1R":
                        # M13-W1R: W1's one lit byte, split into pseudo-random vertical runs
                        # re-shaded through the colormap. Keyed on the V1 column-group hash
                        # (already in the fj ditto signature -- zero extra ditto breaks) and a
                        # height tier (short = far = darker). The base is baked BRIGHTER than
                        # W1's so the pattern spans both sides of the W1 tone. See `w1r_runs`.
                        # W1R-2C: `alt` runs draw over the texture's SECOND texel (a different
                        # material embedded in the wall, still from the same texture).
                        # W1R-FLAT (owner): walls that are FLAT in the best scenario stay flat
                        # -- no texture at all. They render one UNbrightened W1 tone (fj: the
                        # seg's baked seg_w1rf flag). SKY-textured walls USED to stay flat too
                        # (pre-anchor flicker fix) -- owner 2026-08-09: they read as blank white
                        # slabs, so they now take the standard masonry pattern (white bricks
                        # from SKY1's own two dominant texels).
                        # 25M-CAP SLIVER FLAT: a wall whose whole projected span is <= deg_sliver
                        # columns renders the flat tone -- a 1-2 column sliver at the horizon
                        # carries no readable texture anyway, and the heavy frames have dozens.
                        if (tex is None
                                or (deg_sliver and x2 - x1 <= deg_sliver)):
                            cc = (flat_fill if tex is None
                                  else colormap[light_row][tex[0][0]])
                            for y in range(top, bottom + 1):
                                fb[y * cfg.VIEW_W + x] = cc
                        else:
                            blr = max(0, light_row - self.W1R_BASE_BRIGHTEN)
                            base = colormap[blr][tex[0][0]]
                            base2 = colormap[blr][tex[0][1]]
                            ya = top
                            for rel, row, alt in self.w1r_runs(bottom + 1 - top, x + w1r_xoff):
                                cc = colormap[row][base2 if alt else base]
                                for y in range(ya, top + rel):
                                    fb[y * cfg.VIEW_W + x] = cc
                                ya = top + rel
                    elif top <= bottom:
                        if tex is None:
                            for y in range(top, bottom + 1):
                                fb[y * cfg.VIEW_W + x] = flat_fill
                        else:
                            texels, th, tw = tex
                            ang = (rw_centerangle + self.xtoviewangle[x]) & ANGLE_MASK
                            ft = self.finetangent[(ang >> self.angle_shift) & (cfg.TRIG_N - 1)]
                            texcol = (_signed((rw_offset - fixed_mul(ft, rw_distance, 8, 4)) & ANGLE_MASK,
                                              32) >> 16) % tw
                            iscale = self._recip_div32(scale & ANGLE_MASK) // ds   # perf #11: texels/pixel 16.16
                            texturemid = (worldtop << 16) // ds                           # texels at horizon
                            frac = texturemid + (top - centery) * iscale                  # 16.16 texel-v
                            col = self.render_textured_column(
                                texels, th, texcol, colormap, light_row,
                                count=bottom - top + 1, frac0=(frac >> 8) & 0xFFFF,
                                step=(iscale >> 8) & 0xFFFF)
                            for k, y in enumerate(range(top, bottom + 1)):
                                fb[y * cfg.VIEW_W + x] = col[k]
                    # record the M13 visplane regions for this column (ceiling above, floor below the wall)
                    ceil_hi[x] = min(top, cfg.VIEW_H) - 1
                    floor_lo[x] = max(bottom + 1, 0)
                    # M13-2S rung 3a: the region EXTENTS (ceil_hi/floor_lo) still come from this
                    # one-sided wall, only the surface ATTRIBUTION moves to the nearest marking seg.
                    if not pclaim[x]:
                        col_ch[x], col_fh[x], col_lt[x] = sec.ceil_h, sec.floor_h, sec.light
                        col_cf[x], col_ff[x] = sec.ceil_tex, sec.floor_tex
                        pclaim[x] = 1
                        n_claimed += 1
                    drawn[x] = 1
                    n_wdrawn += 1                # fj's n_drawn/full mirror (M13opt-P1 counter)
                scale = (scale + scalestep) & ANGLE_MASK     # DOOM accumulates rw_scale as a 32-bit Fixed

        planes = (ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff)
        if planes_out is not None:
            planes_out.append(planes)                        # the per-column records, for the gates
        if steps_out is not None:
            steps_out.append((ups, los))                     # V5: the per-column piece lists
        if floor_mode_ft1:
            self._render_planes_flat(fb, colormap, scene.asset_wad, flatcache, viewz, *planes,
                                     ft1=True, sky=sky, viewangle=viewangle, texcache=texcache)
            if near_steps:
                # V3 - splice the STEP FACES into the plane regions. Flat-shaded: one distance-lit
                # colour per run rather than a 1x1 texture strip, which is the accuracy this rung
                # trades away. Each run is clipped to the region the claiming wall actually left
                # open (ceiling above ceil_hi, floor below floor_lo) so the emitted column stays
                # MONOTONE top-down -- the 0x0B device only moves its cursor forward and silently
                # drops a non-monotone pair.
                c_hi, f_lo = planes[0], planes[1]

                def _face_paint(x, y1, y2, fsc, units):
                    """One clipped face column [y1, y2]. Flat-shaded in every tier except W1R,
                    which splits it into the SAME randomized runs as its walls (`w1r_runs`,
                    anchored at the clipped top, keyed on the V1 group -- all of it already in
                    the fj ditto signature). The base is pre-brightened like `seg_lit` so the
                    rows have colormap headroom (R44)."""
                    h = y2 - y1 + 1
                    lr = self.wall_light_row(self.wall_lightnum(fsc.light, 0), h, max(1, units))
                    if wall_mode == "W1R":
                        # (faces have no second texel -- the alt bit is ignored here)
                        base = colormap[max(0, lr - self.W1R_BASE_BRIGHTEN)][STEP_FACE_BASE]
                        ya = y1
                        for rel, row, _alt in self.w1r_runs(h, x + w1r_xoff):
                            cc = colormap[row][base]
                            for y in range(ya, y1 + rel):
                                fb[y * cfg.VIEW_W + x] = cc
                            ya = y1 + rel
                    else:
                        for y in range(y1, y2 + 1):
                            fb[y * cfg.VIEW_W + x] = colormap[lr][STEP_FACE_BASE]

                v5_cache: dict = {}

                def _region_paint(x, ra, rb, bsec, ceiling):
                    """V5: the plane region BEHIND a boundary piece -- the back sector's own
                    ceiling/floor, shaded through the SAME shared per-visplane recipe the base
                    planes use (`_flat_row_colours`), so a stacked region's rows match any other
                    window of that visplane. A sky back-ceiling paints SKY (the V2 rule)."""
                    if rb < ra:
                        return
                    if ceiling:
                        hgt, flat, lgt = bsec.ceil_h, bsec.ceil_tex, bsec.light
                    else:
                        hgt, flat, lgt = bsec.floor_h, bsec.floor_tex, bsec.light
                    if ceiling and sky and (flat or "").upper() == "F_SKY1":
                        for y in range(ra, rb + 1):
                            fb[y * cfg.VIEW_W + x] = self.sky_texel(scene.asset_wad, texcache,
                                                                    viewangle, x, y)
                        return
                    rows = self._flat_row_colours(colormap, scene.asset_wad, flatcache, viewz,
                                                  abs((hgt << 16) - viewz), lgt, flat,
                                                  ft1=True, walk_cache=v5_cache)
                    for y in range(ra, rb + 1):
                        fb[y * cfg.VIEW_W + x] = rows[y]

                for x in range(cfg.VIEW_W):
                    if sfrag[x] is not None and not stack_steps:
                        # V4: ONE overlay per column, and the sprite wins (the legacy tier's
                        # trade). V5-SPR paints the pieces UNDER the sprite instead -- the fj
                        # emit_region routes its region windows through the stacked splices, so
                        # walls and ledges no longer look cut where a sprite overlaps them.
                        continue
                    ceil_end = min(c_hi[x], cfg.VIEW_H - 1)
                    for k, (y1, y2, fsc, units, bsec) in enumerate(ups[x]):
                        y1c, y2c = max(y1, 0), min(y2, ceil_end)
                        if y1c <= y2c:
                            _face_paint(x, y1c, y2c, fsc, units)
                        if stack_steps:
                            # the CEILING region behind this boundary: below its face, above the
                            # next piece (or the claiming wall's ceiling extent)
                            nxt = ups[x][k + 1][0] - 1 if k + 1 < len(ups[x]) else ceil_end
                            _region_paint(x, max(y2 + 1, 0), min(nxt, ceil_end), bsec, True)
                    for k, (y1, y2, fsc, units, bsec) in enumerate(los[x]):
                        y1c, y2c = max(y1, f_lo[x]), min(y2, cfg.VIEW_H - 1)
                        if y1c <= y2c:
                            _face_paint(x, y1c, y2c, fsc, units)
                        if stack_steps:
                            # the FLOOR region behind this boundary: above its face, below the
                            # next piece (or the claiming wall's floor extent)
                            nxt = los[x][k + 1][1] + 1 if k + 1 < len(los[x]) else f_lo[x]
                            _region_paint(x, max(nxt, f_lo[x], 0),
                                          min(y1 - 1, cfg.VIEW_H - 1), bsec, False)
            if things_out is not None:
                things_out.append(sfrag)                 # the per-column fragments, for the gates
                things_out.append(n_thing)               # ... and how many things the budget let in
            if things:
                # V4 - splice the sprite fragments. Each is ONE contiguous block of runs at
                # `[y0 + rel]`, clipped to the screen exactly the way the fj emit clips it: runs
                # ending at or above row 0 are skipped outright (a near sprite whose top is off the
                # top of the view) and the last one is clamped at VIEW_H.
                for x in range(cfg.VIEW_W):
                    # V4b: far fragment first, near painted OVER it -- the fj emit produces the
                    # same pixels by windowing the far fragment to the rows the near one leaves.
                    for frag in (sfrag2[x], sfrag[x]):
                        if frag is None:
                            continue
                        y0, runs, lr = frag
                        prev = 0
                        for (rel, texel) in runs:
                            for y in range(max(0, y0 + prev), min(cfg.VIEW_H, y0 + rel)):
                                fb[y * cfg.VIEW_W + x] = colormap[lr][texel]
                            prev = rel
        elif floor_texturing:
            self._render_planes_textured(fb, colormap, scene.asset_wad, flatcache,
                                         viewx, viewy, viewangle, viewz, *planes)
        else:
            self._render_planes_flat(fb, colormap, scene.asset_wad, flatcache, viewz, *planes)
        return bytes(fb)

    def render_frame_2s(self, state: SimState, scene: Scene, *, ft1: bool = True) -> bytes:
        """M13-2S — the TWO-SIDED renderer: DOOM's R_RenderSegLoop window model.

        `render_wall_frame` draws only ONE-SIDED linedefs, which on E1M1 is 575 of 2057 segs: every
        step face, ledge front, door frame and window sill was missing (at spawn the absent wall area
        exceeded the drawn area), and because a column's plane record came from whichever wall claimed
        it, one continuous floor got painted in several different shades. This method fixes both.

        Per column it keeps DOOM's `ceilingclip` (highest row still unpainted from the top) and
        `floorclip` (lowest still unpainted from the bottom), and for each seg front-to-back paints
            front-sector CEILING region | upper wall | (opening) | lower wall | front FLOOR region
        narrowing the window from both ends. A one-sided seg fills what is left and closes the column.
        Each plane region carries the bounding seg's OWN front sector, so equal-distance floor pixels
        finally get equal shades (see `_render_plane_regions_flat`).

        A two-sided seg whose two sectors share BOTH ceiling and floor can never draw anything — 773
        of E1M1's 1482 two-sided segs — and is skipped up front; in fj that becomes a baked flag, so
        it costs nothing at runtime. Walls use the shipped WPX 1x1 tier (`wpx_strip` +
        `wall_light_row`), upper/lower portions sampling the sidedef's upper/lower texture.

        Anything still open when the walk ends stays as the zero fill (sky / an unclosed window);
        real sky rendering is later work."""
        cfg = self.cfg
        W, H = cfg.VIEW_W, cfg.VIEW_H
        fb = bytearray(cfg.FB_SIZE)
        colormap = scene.asset_wad.colormap()
        lds = scene.map_wad.linedefs(scene.mapname)
        sds = scene.map_wad.sidedefs(scene.mapname)
        secs = scene_sectors(scene)
        verts = scene.cmap.vertexes
        texcache, flatcache = {}, {}
        viewx, viewy, viewangle = state.x, state.y, state.angle
        px, py = _signed(state.x, 32) >> 16, _signed(state.y, 32) >> 16
        pss = scene.cmap.subsectors[self.point_in_subsector(scene.cmap, px, py)]
        viewz = self.view_z(self._seg_sector(lds, sds, secs, scene.cmap.segs[pss.firstseg]).floor_h)

        ceilclip = [-1] * W
        floorclip = [H] * W
        regions: list = []                       # (x, y1, y2, plane_h, light, flat)

        def wallrun(x, y1, y2, texname, sec, wall_units, contrast):
            """one WPX 1x1-textured, scalelight-shaded wall run over rows [y1, y2].

            `contrast` is DOOM's per-seg fake contrast (orientation only, so a baked constant): the
            shipped WPX tier applies it and the owner signed off on that look, so the two-sided model
            has to apply it too or switching the fj over would silently drop it."""
            y1, y2 = max(0, y1), min(H - 1, y2)
            if y1 > y2:
                return
            h = y2 - y1 + 1
            tex = self._wall_texture(scene.asset_wad, texname, texcache, wall_mode="WPX")
            texels, th, tw = tex if tex is not None else (None, 0, 0)
            lr = self.wall_light_row(self.wall_lightnum(sec.light, contrast), h, max(1, wall_units))
            ya = y1
            for rel, c in self.wpx_strip(texels, th, tw, colormap, lr, h):
                for y in range(ya, min(y1 + rel, y2 + 1)):
                    fb[y * W + x] = c
                ya = y1 + rel

        for seg_i in self.visible_segs(scene.cmap, px, py):
            seg = scene.cmap.segs[seg_i]
            ld = lds[seg.linedef]
            two = ld.back != -1
            sd = sds[ld.front if seg.side == 0 else ld.back]
            fsec = secs[sd.sector]
            bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector] if two else None
            # M13-2S rung 3b: the cull is DOOM's R_AddLine reject, i.e. the MARKING test -- the two
            # sides differ in a plane key (height, light, flat). "Can never draw a WALL"
            # (fsec.ceil > bsec.ceil or bsec.floor > fsec.floor) is a SUBSET of it: differing heights
            # differ in the key. Using the wall test alone would throw away rung 3a's attribution fix,
            # because two sectors of EQUAL heights but different flats/lights still bound the near
            # floor -- measured at E1M1 spawn, that is the difference between 1 surface and 4.
            if two and ((fsec.ceil_h, fsec.light, fsec.ceil_tex)
                        == (bsec.ceil_h, bsec.light, bsec.ceil_tex)
                        and (fsec.floor_h, fsec.light, fsec.floor_tex)
                        == (bsec.floor_h, bsec.light, bsec.floor_tex)):
                continue
            rng = self.wall_x_range(viewx, viewy, viewangle, seg, verts)
            if rng is None:
                continue
            x1, x2, _rw_angle1 = rng
            contrast = self.wall_fake_contrast(verts[seg.v1], verts[seg.v2])
            rw_normalangle, rw_distance = self.wall_setup(viewx, viewy, seg, verts)
            scale = self.scale_from_global_angle((viewangle + self.xtoviewangle[x1]) & ANGLE_MASK,
                                                viewangle, rw_normalangle, rw_distance)
            if x2 > x1:
                scale2 = self.scale_from_global_angle(
                    (viewangle + self.xtoviewangle[x2]) & ANGLE_MASK, viewangle,
                    rw_normalangle, rw_distance)
                diff, span = scale2 - scale, x2 - x1
                scalestep = -(abs(diff) // span) if diff < 0 else diff // span
            else:
                scalestep = 0
            for x in range(x1, x2):
                if 0 <= x < W and ceilclip[x] + 1 <= floorclip[x] - 1:
                    sc = scale & ANGLE_MASK
                    top, bot = self.wall_screen_span(fsec.ceil_h, fsec.floor_h, viewz, sc)
                    c_hi, c_lo = ceilclip[x] + 1, min(top - 1, floorclip[x] - 1)
                    if c_hi <= c_lo:
                        regions.append((x, c_hi, c_lo, fsec.ceil_h, fsec.light, fsec.ceil_tex))
                        ceilclip[x] = c_lo
                    f_lo, f_hi = floorclip[x] - 1, max(bot + 1, ceilclip[x] + 1)
                    if f_hi <= f_lo:
                        regions.append((x, f_hi, f_lo, fsec.floor_h, fsec.light, fsec.floor_tex))
                        floorclip[x] = f_hi
                    win_hi, win_lo = ceilclip[x] + 1, floorclip[x] - 1
                    if win_hi <= win_lo:
                        if not two:
                            wallrun(x, max(top, win_hi), min(bot, win_lo), sd.middle, fsec,
                                    fsec.ceil_h - fsec.floor_h, contrast)
                            ceilclip[x], floorclip[x] = H, -1        # column finished
                        else:
                            if fsec.ceil_h > bsec.ceil_h:            # upper: lintel / step-down
                                _t, ub = self.wall_screen_span(fsec.ceil_h, bsec.ceil_h, viewz, sc)
                                lo = min(ub - 1, win_lo)
                                if win_hi <= lo:
                                    wallrun(x, win_hi, lo, sd.upper, fsec,
                                            fsec.ceil_h - bsec.ceil_h, contrast)
                                    ceilclip[x] = lo
                                    win_hi = lo + 1
                            if bsec.floor_h > fsec.floor_h:          # lower: step / ledge face
                                lt, _b = self.wall_screen_span(bsec.floor_h, fsec.floor_h, viewz, sc)
                                hi = max(lt, win_hi)
                                if hi <= win_lo:
                                    wallrun(x, hi, win_lo, sd.lower, fsec,
                                            bsec.floor_h - fsec.floor_h, contrast)
                                    floorclip[x] = hi
                scale = (scale + scalestep) & ANGLE_MASK
        self._render_plane_regions_flat(fb, colormap, scene.asset_wad, flatcache, viewz, regions,
                                       ft1=ft1)
        return bytes(fb)

    def _render_plane_regions_flat(self, fb, colormap, asset_wad, flatcache, viewz, regions,
                                   *, ft1: bool = False):
        """M13-2S: rasterize an explicit LIST of plane regions instead of one ceiling + one floor
        region per column.

        Why this exists: the per-column model took each column's plane height/light from whichever
        WALL claimed the column, which is wrong as soon as the claiming wall lives in a different
        sector from the surface you are actually looking at. Measured at E1M1 spawn row 80, every
        column had the same planeheight 41 (the floor underfoot) yet came out in zlight rows
        19/7/15/12, because the claiming sectors' light levels were 150/192/160 — one continuous
        floor painted in three shades. DOOM cannot do that: a visplane belongs to a SECTOR SURFACE
        and carries that surface's light, not to a column claim. Here each region carries its own
        (planeheight, light, flat) from the seg that bounded it, so equal-distance floor pixels get
        equal shades again.

        `regions` = [(x, y1, y2, plane_h_mapunits, light, flat_name)]. The per-row band arithmetic is
        the SAME shared full-range `_zidx_band_walk` + `band_colour` the per-column tier uses (R6), so
        a region is bit-identical to the corresponding slice of the old whole-column fill."""
        cfg = self.cfg
        W, H, CY_ = cfg.VIEW_W, cfg.VIEW_H, cfg.CENTERY
        walk_cache: dict = {}

        def band_colour(name, base, zrows, k):
            if not ft1:
                return colormap[zrows[k]][base]
            tx = self._flat_texels(asset_wad, name, flatcache)
            ordinal = sum(1 for i in range(1, k + 1) if zrows[i] != zrows[i - 1])
            return colormap[zrows[k]][tx[((ordinal & 63) * 64 + (ordinal & 63)) % len(tx)]]

        def full_walk(ph):
            if ph not in walk_cache:
                walk_cache[ph] = self._zidx_band_walk(ph, list(range(H)))
            return walk_cache[ph]

        for x, y1, y2, plane_h, light, flat in regions:
            ph = abs((plane_h << 16) - viewz)
            base = self._flat_base(asset_wad, flat, flatcache)
            lvl = min(LIGHTLEVELS - 1, light >> LIGHTSEGSHIFT)
            zr_all = [self.zlight[lvl][z] for z in full_walk(ph)]
            for y in range(max(0, y1), min(H, y2 + 1)):
                k0 = y if y < CY_ else y - CY_
                seq = zr_all[:CY_] if y < CY_ else zr_all[CY_:]
                fb[y * W + x] = band_colour(flat, base, seq, k0)

    # ── M13 floor/ceiling visplane rasterizers (consume the per-column region records above) ──
    def sky_texel(self, asset_wad, texcache, viewangle: int, x: int, y: int) -> int:
        """V2 — one sky pixel. DOOM's sky is the only surface with NO perspective: its texture column
        comes from the absolute view angle and its row is the screen row, so it neither scales with
        distance nor takes a colormap step. That is exactly why it is cheap here — with no
        perspective the whole column is a function of `u` alone, so the fj bakes ONE run-list per sky
        texture column (128 of them, ~9 runs each) and the runtime cost per sky column is an add, a
        shift, a mask and one dispatch.

        `SKY_TURN` sky widths per full turn is the look knob (DOOM uses 1 across its 90° FOV, i.e. 4
        per turn); it is not a correctness constant.

        The column is SPLIT into a per-frame base plus a per-column offset —
            u = (sky_base(viewangle) + sky_col_off(x)) & (tw-1)
        — rather than shifting the runtime sum `viewangle + xtoviewangle[x]`. Both halves are then
        cheap in fj: the base is one shift-and-mask per FRAME, and the offset is a compile-time
        constant per column (xtoviewangle is compile-time), so the per-column cost is an add and a
        mask. Dropping the carry between the two halves can move `u` by one texel versus the exact
        sum; on a 128-wide cloud texture that is invisible, and the oracle takes the SAME
        decomposition so fj still has to match it bit for bit (R6)."""
        tex = self._wall_texture(asset_wad, "SKY1", texcache if texcache is not None else {},
                                 wall_mode="textured")
        if tex is None:
            return CEIL_BG
        texels, th, tw = tex
        u = (self.sky_base(viewangle, tw) + self.sky_col_off(x, tw)) & (tw - 1)
        return texels[u * th + min(th - 1, y * th // max(1, self.cfg.VIEW_H))]

    @staticmethod
    def sky_base(viewangle: int, tw: int) -> int:
        """The frame's sky scroll: which texture column screen column 0's view ray starts from.
        One shift and mask, once per frame."""
        return (viewangle >> _sky_shift(tw)) & (tw - 1)

    def sky_col_off(self, x: int, tw: int) -> int:
        """The per-column sky offset — a COMPILE-TIME constant, since xtoviewangle is."""
        return (self.xtoviewangle[x] >> _sky_shift(tw)) & (tw - 1)

    def sky_texel_u(self, asset_wad, texcache, u: int, y: int) -> int:
        """One sky pixel addressed by TEXTURE COLUMN rather than screen column — what the fj bank
        bakes, one list per `u`. `sky_texel` is this composed with the u computation."""
        tex = self._wall_texture(asset_wad, "SKY1", texcache if texcache is not None else {},
                                 wall_mode="textured")
        if tex is None:
            return CEIL_BG
        texels, th, tw = tex
        return texels[(u % tw) * th + min(th - 1, y * th // max(1, self.cfg.VIEW_H))]

    def _flat_row_colours(self, colormap, asset_wad, flatcache, viewz,
                          plane_h: int, light: int, flat_name, *, ft1: bool,
                          walk_cache: dict):
        """The FT1 flat tier's colour for EVERY screen row of one visplane (height, light, flat)
        — the shared recipe `_render_planes_flat` slices per column and V5's stacked regions
        window per piece: one full-range `_zidx_band_walk` (split at CENTERY inside), zlight
        rows, and the FT1 band-ordinal diagonal texel, ordinals restarting per half. The fj side
        windows its shared per-visplane band list exactly the same way, which is why a stacked
        region's rows match any other window of the same visplane (R6)."""
        cfg = self.cfg
        H, CY_ = cfg.VIEW_H, cfg.CENTERY
        key = (plane_h, light, flat_name, ft1)
        if key in walk_cache:
            return walk_cache[key]
        wk = f"__walk_{plane_h}"
        if wk not in walk_cache:
            walk_cache[wk] = self._zidx_band_walk(plane_h, list(range(H)))
        lvl = min(LIGHTLEVELS - 1, light >> LIGHTSEGSHIFT)
        zr_all = [self.zlight[lvl][z] for z in walk_cache[wk]]
        base = self._flat_base(asset_wad, flat_name, flatcache)
        tx = self._flat_texels(asset_wad, flat_name, flatcache) if ft1 else None
        out = [0] * H
        for half, (lo, hi) in enumerate(((0, CY_), (CY_, H))):
            seq = zr_all[lo:hi]
            for k, y in enumerate(range(lo, hi)):
                if not ft1:
                    out[y] = colormap[seq[k]][base]
                else:
                    ordinal = sum(1 for i in range(1, k + 1) if seq[i] != seq[i - 1])
                    out[y] = colormap[seq[k]][tx[((ordinal & 63) * 64 + (ordinal & 63)) % len(tx)]]
        walk_cache[key] = out
        return out

    def _render_planes_flat(self, fb, colormap, asset_wad, flatcache, viewz,
                            ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff,
                            *, ft1: bool = False, sky: bool = False, viewangle: int = 0,
                            texcache: dict | None = None):
        """M13a flat-colored tier (the cheaper §1 floor mode): each claimed column's ceiling rows
        [0, ceil_hi] and floor rows [floor_lo, H-1] are filled with the flat's base index, distance-lit
        per row. No horizontal DDA — each pixel is independent.
        M13pS2 (the F4 [re-bless], applied WITH the fj column-stream consumer): the per-row zidx comes
        from `_zidx_band_walk` — the SAME seed-then-threshold-walk arithmetic the fj
        `plane.build_bands` kernel mirrors bit-for-bit — instead of the per-row always-exact
        `_plane_pixel` FixedMul. Measured vs exact at pS2a: 79/16,000 E1M1 spawn flat pixels shift
        (each ≤1 row, an adjacent-colormap-row shade); the square-room frames are unchanged.
        ⚠ This intentionally diverges from the LEGACY framebuffer-mode fj flat kernel
        (`draw_span_flat`, still exact per span-row) — that path's E1M1 flat gate is superseded by
        the stream capstone (see tests/fj/test_floor_planes_fj.py)."""
        cfg = self.cfg
        W, H, CY_ = cfg.VIEW_W, cfg.VIEW_H, cfg.CENTERY
        # M13pS2-crush2b (per-VISPLANE sharing): every column slices ONE shared full-range walk
        # (rows [0,H), split at CENTERY inside _zidx_band_walk) instead of walking its own window --
        # the fj side builds each visplane's full-range band list once per frame and clips it per
        # column at emit time (ceiling = a PREFIX of the list, floor = a SUFFIX). Ceiling prefixes
        # are bit-identical to per-window walks (same row-0 seed, deterministic march); floor
        # suffixes take their zidx from the shared CENTERY-seeded half instead of a per-window
        # fstart seed -- an F4-class <=1-row band-edge shift, re-blessed with the fj consumer.
        walk_cache: dict = {}
        for x in range(W):
            # V2: F_SKY1 is not a flat at all -- it is DOOM's signal to paint the SKY, whose texture
            # column is chosen by the VIEW ANGLE and which takes NO distance lighting. That
            # combination is what makes it read as "outdoors": the sky slides as you turn but never
            # gets nearer and never darkens with depth. 19 of E1M1's sectors use it.
            is_sky = sky and ceil_hi[x] >= 0 and (col_cf[x] or "").upper() == "F_SKY1"
            if is_sky:
                for y in range(min(ceil_hi[x] + 1, H)):
                    fb[y * W + x] = self.sky_texel(asset_wad, texcache, viewangle, x, y)
            if ceil_hi[x] >= 0 and not is_sky:
                rows = self._flat_row_colours(colormap, asset_wad, flatcache, viewz,
                                              abs((col_ch[x] << 16) - viewz), col_lt[x],
                                              col_cf[x], ft1=ft1, walk_cache=walk_cache)
                for y in range(min(ceil_hi[x] + 1, H)):
                    fb[y * W + x] = rows[y]
            if floor_lo[x] < H:
                rows = self._flat_row_colours(colormap, asset_wad, flatcache, viewz,
                                              abs((col_fh[x] << 16) - viewz), col_lt[x],
                                              col_ff[x], ft1=ft1, walk_cache=walk_cache)
                for y in range(floor_lo[x], H):
                    fb[y * W + x] = rows[y]

    @staticmethod
    def _plane_region_at(x, y, ceil_hi, floor_lo):
        """Which visplane (if any) column x belongs to at screen row y: 'c' (ceiling, y above the wall),
        'f' (floor, y below the wall), or None (the wall band / an unclaimed column)."""
        if y <= ceil_hi[x]:
            return 'c'
        if y >= floor_lo[x]:
            return 'f'
        return None

    def _render_planes_textured(self, fb, colormap, asset_wad, flatcache,
                                viewx, viewy, viewangle, viewz,
                                ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff):
        """M13b full-res textured tier (the chosen §1 default): DOOM's R_DrawPlanes. For each screen row,
        group consecutive columns sharing the same visplane (region + flat + plane-height + light) into a
        horizontal span and rasterize it with the perspective u,v DDA (R_MapPlane/R_DrawSpan). `basexscale`/
        `baseyscale` are the per-frame R_ClearPlanes seeds; the span start's `length`/angle seed `xfrac`/
        `yfrac`, then `+= xstep/ystep` per pixel; the flat is sampled `&63` and distance-lit (zlight)."""
        cfg = self.cfg
        W, H = cfg.VIEW_W, cfg.VIEW_H
        cxfrac = cfg.CENTERX << 16                           # centerxfrac (R_ClearPlanes)
        ang_b = ((viewangle - ANG90) & ANGLE_MASK) >> self.angle_shift
        basexscale = fixed_div(self._finecos_idx(ang_b), cxfrac, 8, 4)
        baseyscale = (-fixed_div(self._finesin_idx(ang_b), cxfrac, 8, 4)) & ANGLE_MASK
        viewx32, viewy32 = viewx & 0xFFFFFFFF, viewy & 0xFFFFFFFF
        for y in range(H):
            x = 0
            while x < W:
                region = self._plane_region_at(x, y, ceil_hi, floor_lo)
                if region is None:
                    x += 1
                    continue
                ch, cf = (col_ch, col_cf) if region == 'c' else (col_fh, col_ff)
                height, flat, light = ch[x], cf[x], col_lt[x]
                x2 = x                                       # extend the span over same-visplane columns
                while x2 + 1 < W and self._plane_region_at(x2 + 1, y, ceil_hi, floor_lo) == region \
                        and ch[x2 + 1] == height and cf[x2 + 1] == flat and col_lt[x2 + 1] == light:
                    x2 += 1
                self._draw_span(fb, colormap, self._flat_texels(asset_wad, flat, flatcache),
                                height, light, viewx32, viewy32, viewangle, viewz,
                                basexscale, baseyscale, y, x, x2)
                x = x2 + 1

    def _draw_span(self, fb, colormap, texels, height, light, viewx32, viewy32, viewangle, viewz,
                   basexscale, baseyscale, y, x1, x2):
        """R_MapPlane + R_DrawSpan for one horizontal span [x1,x2] at row y: distance = FixedMul(planeheight,
        yslope[y]); the per-pixel step xstep/ystep = FixedMul(distance, base?scale); the span-left seed
        xfrac/yfrac from the slant length (FixedMul(distance, distscale[x1])) + the column's view angle;
        then per pixel sample `flat[(yfrac>>10 & 63*64) + (xfrac>>16 & 63)]`, distance-lit, and step the
        DDA. All coords are unsigned 32-bit modular (what the fj computes)."""
        W = self.cfg.VIEW_W
        planeheight = abs((height << 16) - viewz)
        distance = fixed_mul(planeheight, self.yslope[y], 8, 4)
        xstep = fixed_mul(distance, basexscale, 8, 4)
        ystep = fixed_mul(distance, baseyscale, 8, 4)
        length = fixed_mul(distance, self.distscale[x1], 8, 4)
        idx = ((viewangle + self.xtoviewangle[x1]) & ANGLE_MASK) >> self.angle_shift
        xfrac = (viewx32 + fixed_mul(self._finecos_idx(idx), length, 8, 4)) & 0xFFFFFFFF
        yfrac = (-viewy32 - fixed_mul(self._finesin_idx(idx), length, 8, 4)) & 0xFFFFFFFF
        row = colormap[self.plane_light_row(light, distance)]
        for x in range(x1, x2 + 1):
            spot = ((yfrac >> 10) & 4032) + ((xfrac >> 16) & 63)   # DOOM R_DrawSpan: v*64 + u, flats are 64x64
            fb[y * W + x] = row[texels[spot]]
            xfrac = (xfrac + xstep) & 0xFFFFFFFF
            yfrac = (yfrac + ystep) & 0xFFFFFFFF
