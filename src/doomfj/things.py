"""M14-e — the RUNTIME thing table: the data half.

Today every thing is baked as one xor-involution block INSIDE its subsector's code
(`wall_renderer.subsector_action`), holding position, art metrics, bases, the monster flag, the
min-size depth bounds and the light class. That works only because a static thing's leaf is known at
emit time. Once things move it is wrong twice over: the leaf owns call sites for things that are no
longer in it, and two of the baked fields are properties of WHERE THE THING IS, not of the thing.

This module splits the block three ways, which is the whole design:

  * POSITION (`sp_x`, `sp_y`) -- runtime, off the wire.
  * PER THING INDEX (`sp_left`, `sp_w`, `sp_hh`, `sp_tzmax(2)`, `sp_mon`, `sp_base(2)`, `sp_dw`,
    and the art's z-offset) -- STATIC, because the set of things is fixed at level load. M14 does
    not spawn or destroy anything, so these bake by index and never move.
  * PER BOUND SUBSECTOR -- `sp_z` is `ssfloor[ss] + zoff[t]` and `sp_lt` is
    `sprlt[sslight[ss]][t]`. THESE ARE THE ONES THAT CHANGE WHEN A THING CROSSES A SECTOR, which is
    exactly what M14-e is for, and they are two small baked tables plus an add.

`check_row_equivalence` is the point of the module: it proves, for every thing at its spawn
position, that the runtime derivation reproduces the emitter's currently-baked constants EXACTLY.
If that holds, swapping the baked blocks for table reads cannot move a pixel for a static thing --
which is what makes the M14-e gate's still frames byte-exact and isolates any divergence to the
moving half.
"""
from __future__ import annotations

# per-thing row: left, w, hh, zoff (int16 each), tzmax, tzmax2 (uint32), base, base2 (uint16),
# mon, dw (uint8)
THING_ROW_BYTES = (2, 2, 2, 2, 4, 4, 2, 2, 1, 1)
THING_ROW_LEN = sum(THING_ROW_BYTES)


def thing_rows(rm, things, sprite_wad, spr_base, spr_ldbase, spr_dw, monster_types,
               min_h, min_h_monster, deg_min_h, deg_min_h_monster, *, deg: bool,
               spr_near: bool, cache=None):
    """One packed row per DRAWABLE thing, in `THING_ROW_BYTES` order, plus the index list.

    Returns `(rows, indices)` where `indices[i]` is the position of row `i` in the wad's THINGS
    lump -- the wire's position table is indexed the same way, so a row and a position share an
    index and neither needs a pointer to the other."""
    cache = {} if cache is None else cache
    rows, idx = [], []
    for i, t in enumerate(things):
        art = rm.sprite_art(sprite_wad, t.type, cache)
        if art is None:
            continue                                    # a start / teleport spot / unknown
        mon = t.type in monster_types
        rows.append((art[5], art[3], art[4], art[6],
                     rm.sprite_tz_min_size(art[4], min_h_monster if mon else min_h) & 0xFFFFFFFF,
                     (rm.sprite_tz_min_size(art[4], deg_min_h_monster if mon else deg_min_h)
                      & 0xFFFFFFFF) if deg else 0,
                     spr_base[t.type],
                     spr_ldbase[t.type] if spr_near else 0,
                     1 if mon else 0,
                     spr_dw[t.type]))
        idx.append(i)
    return rows, idx


def subsector_tables(rm, cmap, lds, sds, secs):
    """`(ssfloor, sslight)` per subsector -- the two things a bound leaf has to tell a sprite.

    A seg-less leaf has no sector to read; it gets zeros and is unreachable anyway (nothing binds
    to it, since `point_in_subsector` only ever returns a leaf with geometry)."""
    from doomfj.mapcompiler import seg_sector
    floor, light = [], []
    for ss in cmap.subsectors:
        if not ss.numsegs:
            floor.append(0)
            light.append(0)
            continue
        sec = seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
        floor.append(sec.floor_h & 0xFFFF)
        light.append(rm.wall_lightnum(sec.light, 0))
    return floor, light


def sprite_light_table(spr_cls, rows, lightnums):
    """`sprlt[k * nthings + t]` for `k` indexing `lightnums` -- the light CLASS a thing takes in a
    sector of that light. Flat and two-dimensional, because the class is a function of (sector
    light, sprite world height) and the height is per thing: this turns `sp_lt` into one indexed
    read once the bound leaf's light is known, where the static path could afford an emit-time
    lookup.

    ⚠ THE SHADE-ROW BANK HAS TO BE WIDENED FIRST, and this raises rather than guessing when it has
    not been. `_lines_sprite_light` bakes only the (lightnum, height) pairs that OCCUR AT SPAWN --
    75 of them on E1M1 -- because a static thing never sees any other. A thing that walks into a
    differently-lit sector needs a pair that was never baked.

    Sizing, measured on E1M1: 21 distinct sprite heights. Against all 32 COLORMAP_LIGHTS that is
    672 pairs, 9x today, and the bank text goes 193k -> ~1.73M chars. But a thing can only ever
    stand in a REAL SECTOR, and only 10 lightnums occur among E1M1's sectors -- so the honest
    requirement is 10 x 21 = 210 pairs, **2.8x today** (~540k chars). Pass those 10, not range(32).
    """
    out = []
    missing = set()
    for ln in lightnums:
        for r in rows:
            key = (ln, max(1, r[2]))                    # r[2] = the art's half-height (sp_hh)
            if key not in spr_cls:
                missing.add(key)
            out.append(spr_cls.get(key))
    if missing:
        raise KeyError(
            f"the sprite shade-row bank is missing {len(missing)} (lightnum, height) pairs that a "
            f"MOVING thing can reach, e.g. {sorted(missing)[:4]}. _lines_sprite_light bakes only "
            f"the pairs that occur at spawn; M14-e needs it widened to the cross product of the "
            f"map's REACHABLE sector lightnums with the sprite heights -- 2.8x on E1M1, not the 9x "
            f"a naive all-32-lightnums widening would cost.")
    return out


def reachable_lightnums(rm, secs):
    """The lightnums a thing can actually stand in -- one per distinct sector light. This is what
    keeps the widened shade-row bank at 2.8x instead of 9x: nothing can reach a lightnum no sector
    has."""
    return sorted({rm.wall_lightnum(s.light, 0) for s in secs})


def check_row_equivalence(rm, cmap, lds, sds, secs, things, indices, rows, ssfloor, sslight,
                          sprlt, nthings, baked):
    """⚠ THE PROOF THIS MODULE EXISTS FOR. For every thing at its SPAWN position, derive `sp_z` and
    `sp_lt` the runtime way -- from the subsector it binds to -- and require them to equal what the
    emitter bakes today. `baked` maps a THINGS-lump index to `(sp_z, sp_lt)`.

    Returns the list of disagreements; empty means the table swap is pixel-neutral for static
    things, and therefore that any divergence the M14-e gate finds belongs to the moving half."""
    bad = []
    for row_i, t_i in enumerate(indices):
        t = things[t_i]
        ss = rm.point_in_subsector(cmap, t.x, t.y)
        z = ((ssfloor[ss] if ssfloor[ss] < 0x8000 else ssfloor[ss] - 0x10000)
             + rows[row_i][3]) & 0xFFFF
        lt = sprlt[sslight[ss] * nthings + row_i]
        want_z, want_lt = baked[t_i]
        if (z, lt) != (want_z & 0xFFFF, want_lt):
            bad.append((t_i, (z, lt), (want_z & 0xFFFF, want_lt)))
    return bad
