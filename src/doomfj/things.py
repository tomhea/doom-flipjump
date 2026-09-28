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

# ── M14-perf: the row is READ IN TWO HALVES, because 94.1% of loads are thrown away ────────────
#
# MEASURED (scratchpad/m14_m5_counts.py, 260 frames): of 22,146 things `sim.thing_load` loads,
# 20,832 are rejected by `proj.project_thing` and only 1,314 (5.9%) ever draw. `read_table_packed`
# costs `rep(nb) read_byte_and_inc`, i.e. LINEAR in the row width, so every rejected thing was
# paying for bytes it never read.
#
# The split point is the reject ladder, not convenience. `project_thing`'s three cheap rejects --
# tz < minz, tz > sp_tzmax/sp_tzmax2, |tx| > tz<<2 -- read only the position and the two depth
# bounds, and `thing_record_body`'s budget test reads only `mon`. `sp_base`/`sp_base2`/`sp_dw`
# (and the separate `sprlt` lookup) are first touched AFTER `hex.if0 1, vis, ret`. So HOT is
# everything any reject can reach and COLD is what only a drawn sprite needs.
#
# ⚠ TWO TABLES, NOT AN OFFSET READ. `hex.read_table_packed nb, ...` derives its STRIDE from `nb`
# (`mul_const w/4, ptr, ptr, nb*dw`), so it can only read a whole row of exactly `nb` bytes -- a
# prefix of a wider row would index at the wrong stride. Splitting the table is the only form this
# accessor supports.
#
# ⚠ VALUES AND ORDER ARE UNCHANGED, so no pixel can move: the same fields carry the same bytes and
# every reject and budget spend still happens in the same sequence.
_HOT_FIELDS = (0, 1, 2, 3, 4, 5, 8)     # left, w, hh, zoff, tzmax, tzmax2, mon
_COLD_FIELDS = (6, 7, 9)                # base, base2, dw
THING_ROW_HOT_BYTES = tuple(THING_ROW_BYTES[i] for i in _HOT_FIELDS)
THING_ROW_COLD_BYTES = tuple(THING_ROW_BYTES[i] for i in _COLD_FIELDS)
THING_ROW_HOT_LEN = sum(THING_ROW_HOT_BYTES)      # 17
THING_ROW_COLD_LEN = sum(THING_ROW_COLD_BYTES)    # 5
assert THING_ROW_HOT_LEN + THING_ROW_COLD_LEN == THING_ROW_LEN


def hot_row(row):
    """The fields any reject can reach, in `THING_ROW_HOT_BYTES` order."""
    return tuple(row[i] for i in _HOT_FIELDS)


def cold_row(row):
    """The fields only a DRAWN sprite needs, in `THING_ROW_COLD_BYTES` order."""
    return tuple(row[i] for i in _COLD_FIELDS)


def single_player(t):
    """M7 P1.5 (D7): does the thing exist on SOME single-player skill? DOOM's P_SpawnMapThing drops a
    multiplayer-only thing (`options & MTF_NOTSINGLE` outside a netgame) and one with no skill bit.
    ONE predicate for the thing universe: `drawable_things` below (the renderer, the oracle, every
    gate) and the gameplay model (`world.World`) both take it. E1M1: 26 of the 251 things with art
    are multiplayer-only (all pickups: 7 weapons, 18 ammo, a soulsphere --
    docs/ship-evidence/p15_skill_census.log); the image holds the other 225, the union of the three
    skills, and which of those a game has is the skill's level-start state."""
    from doomfj import gamedata as gd          # lazy: gamedata reads the oracle's constants at import
    return (not t.flags & gd.MTF_NOTSINGLE
            and bool(t.flags & (gd.MTF_EASY | gd.MTF_NORMAL | gd.MTF_HARD)))


def skill_absent(drawable, skill):
    """M7 P1.5: the DRAWABLE indices `skill` does not spawn -- DOOM's P_SpawnMapThing skips a thing
    whose options lack the skill's bit. ONE answer for both mirrors: the emitter bakes each skill's
    leaf lists and `thvis` flags from it, and the gates hand it to the oracle as `thing_hidden`. The
    boot state is hard's (docs/gp-skill-menu.md)."""
    from doomfj import gamedata as gd          # lazy, as single_player
    bit = gd.skill_bit(skill)
    return frozenset(i for i, t in enumerate(drawable) if not t.flags & bit)


def skill_hidden(rm, things, sprite_wad, skill):
    """M7 P1.5: `skill_absent` over the drawable list the ORACLE builds from `things` -- the
    `thing_hidden` a gate hands `render_wall_frame` for a game at `skill`. The game tier boots at
    wall_renderer.BOOT_SKILL, so every gate that runs it asks for that skill's set."""
    return skill_absent(drawable_things(rm, things, sprite_wad)[0], skill)


def drawable_things(rm, things, sprite_wad, cache=None):
    """`(drawable, wad_indices)` -- the single-player things that have art, in wad order.

    ONE definition of "drawable", so the emitter, the oracle and every gate index the same list."""
    cache = {} if cache is None else cache
    out, idx = [], []
    for i, t in enumerate(things):
        if single_player(t) and rm.sprite_art(sprite_wad, t.type, cache) is not None:
            out.append(t)
            idx.append(i)
    return out, idx


def baked_thing_mask(rm, cmap, drawable, monster_types):
    """M14.5 SSOT — which drawable things BAKE into their leaf, and which take the runtime path.

    Returns a tuple parallel to `drawable` (True = baked). ⚠ It is computed from SPAWN positions
    and is a property of the THING, not of where it currently stands: a runtime thing that walks
    into a baked thing's leaf stays runtime.

    THE RULE (docs/handoff-m14_5.md §4b): a thing bakes iff it is not a monster AND no monster
    shares its leaf. That keeps every leaf HOMOGENEOUS at spawn -- all-baked or all-runtime -- so
    the per-leaf visit order stays wad order in both mirrors and the frame is byte-identical to the
    all-runtime build. A mixed leaf could only be visited "all baked, then all runtime" (baked
    things are CODE at the call site, runtime things are a list), which reorders sprite slot claims
    and the graduated-acceptance counters.

    ⚠ Both mirrors order a leaf BAKED-FIRST-THEN-RUNTIME (not static-first-then-dynamic). Those
    coincide at spawn because of the rule above; they stop coinciding the moment a runtime thing
    moves into a baked leaf, and only the baked-ness key is order-preserving by construction."""
    leaves = [rm.point_in_subsector(cmap, t.x, t.y) for t in drawable]
    mon_leaves = {ss for ss, t in zip(leaves, drawable) if t.type in monster_types}
    return tuple(t.type not in monster_types and ss not in mon_leaves
                 for t, ss in zip(drawable, leaves))


def vanishable_slots(drawable, baked, vanishable_types):
    """M14.5 §3.3 — `{drawable index: slot}` for the baked things that can VANISH.

    A baked thing is code inside its leaf, so a runtime flag is the ONLY way it can stop being
    drawn -- and it is the cheapest read the program has: the index is a compile-time constant at
    the call site, so the test is `hex.if0 1, thvis + slot*2*dw` at a FIXED ADDRESS, no pointer
    built, no table strided. One test per thing per leaf visit, the same shape as the `tstop` guard
    already emitted there; a hidden thing then skips its whole projection.

    ⚠ Only BAKED things get a slot. A runtime thing already carries a position that the host can
    move, and giving it a flag would mean an INDEXED read -- the pattern this milestone exists to
    remove. ⚠ And only VANISHABLE types: a guard on a tree is a test that can never fire."""
    return {i: k for k, i in enumerate(
        i for i, (t, b) in enumerate(zip(drawable, baked))
        if b and t.type in vanishable_types)}


def thing_rows(rm, things, sprite_wad, spr_base, spr_ldbase, spr_dw, monster_types,
               min_h, min_h_monster, deg_min_h, deg_min_h_monster, *, deg: bool,
               spr_near: bool, cache=None, keep=None):
    """One packed row per DRAWABLE thing, in `THING_ROW_BYTES` order, plus the index list.

    Returns `(rows, indices)` where `indices[i]` is the position of row `i` in the wad's THINGS
    lump -- the wire's position table is indexed the same way, so a row and a position share an
    index and neither needs a pointer to the other.

    `keep`, when given, is the set of wad indices that take the RUNTIME path (M14.5): everything
    else bakes into its leaf and must NOT appear here, or it would be drawn twice."""
    cache = {} if cache is None else cache
    rows, idx = [], []
    for i, t in enumerate(things):
        if not single_player(t):
            continue                                    # M7 P1.5: on no single-player skill
        art = rm.sprite_art(sprite_wad, t.type, cache)
        if art is None:
            continue                                    # a start / teleport spot / unknown
        if keep is not None and i not in keep:
            continue                                    # M14.5: baked into its leaf instead
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


# The per-leaf thing lists (`sshead` / `thnext`) store a thing's index + 1 in ONE BYTE, 0 ending a
# list: the most things they hold. ONE bound for the three layers that rely on it -- these baked
# lists, the emitter's runtime-thing tables (wall_renderer) and the gameplay model's mobiles (world).
LIST_MAX_THINGS = 254


def spawn_leaf_lists(binds, nleaves, present=None):
    """`(sshead, thnext)` -- the per-leaf lists of runtime things `sim.bind_things` builds from the
    bindings `binds` (thing index -> leaf): each leaf's things in ASCENDING index order, stored as
    `t + 1` so that 0 is both the empty list and the end of one. bind_things gets the ascending order
    by prepending in DESCENDING index order; this is that loop.

    M7 P1.3: the game tier BAKES these into its image and they persist -- nothing moves a thing
    until P3, and P3 moves one by relinking it (`sim.leaf_unlink` / `sim.leaf_link`), never by
    rebuilding every list.

    M7 P1.5: `present` (a flag per thing, or None for all) links only the things a skill spawns; an
    absent thing is in no list and keeps `thnext = 0` -- the model's `_list_insert` of the active
    monsters only (world.World._reset_state)."""
    assert len(binds) <= LIST_MAX_THINGS, (
        "%d things: the lists store t + 1 in a byte, at most LIST_MAX_THINGS" % len(binds))
    assert present is None or len(present) == len(binds), (len(present), len(binds))
    sshead = [0] * nleaves
    thnext = [0] * len(binds)
    for t in range(len(binds) - 1, -1, -1):
        if present is not None and not present[t]:
            continue
        leaf = binds[t]
        thnext[t] = sshead[leaf]
        sshead[leaf] = t + 1
    return sshead, thnext


def thing_pos_value(t) -> int:
    """M7 P1.5 (R6): the value of a runtime thing's `thpos_rt` cell at its spawn -- its 16.16 x in
    the low 8 nibbles and its 16.16 y in the high 8, each 32-bit two's complement: what
    `sim.thing_pass` reads with `hex.read_hex 16`, and the layout the hosted wire writes into the
    same cells (`wireformat.encode_things`: x, then y, little-endian). The pristine table
    (`wall_renderer._moving_thing_tables`) and NEW GAME's restart block (`restart_lines`) both
    bake it from here, so the two cannot disagree about where a thing starts."""
    return (((t.y << 16) & 0xFFFFFFFF) << 32) | ((t.x << 16) & 0xFFFFFFFF)


def skill_level_start(drawable, rt_draw, rt_binds, nleaves, vis_slots, skill):
    """M7 P1.5: the game tier's thing PRESENCE at `skill`'s level start -- `(sshead, thnext, thvis)`:
    the runtime things' leaf lists linking only the things the skill spawns, and each baked
    vanishable thing's flag (1 = drawn, 0 = not; slot order). `rt_draw[k]` is runtime thing k's
    drawable index, `rt_binds[k]` its spawn leaf, `vis_slots` {drawable index: slot}. The emitter
    bakes HARD's as the boot state and every skill's into its restart block
    (docs/gp-skill-menu.md); the gates ask `skill_absent` for the oracle's half."""
    absent = skill_absent(drawable, skill)
    head, nxt = spawn_leaf_lists(rt_binds, nleaves, present=[di not in absent for di in rt_draw])
    vis = [0 if di in absent else 1 for di in sorted(vis_slots, key=vis_slots.get)]
    return head, nxt, vis


def byte_array_decl(label, values, cells):
    """fj text for a `read_byte`/`write_byte` array baked to `values`: one cell per entry, holding its
    byte in the jump word as `b * dw` (`b << 6`, the layout scratchpad/gp/probe.py and M1a settled),
    padded with zero cells to `cells` in all -- the extent `label: hex.vec cells` had, so no label
    after it moves and the M1 restore set's span for it holds."""
    # (a map with no runtime things has an EMPTY array -- no entry, no cell: `hex.vec 0` is nothing)
    assert (len(values) < cells or not values) and all(0 <= v < 256 for v in values), (
        label, len(values), cells)
    return "\n".join([f"{label}:"] + [f";{v} * dw" for v in values]
                     + [f"hex.vec {cells - len(values)}"])


# M7 P1.3: the named scratch of `sim.leaf_link` / `sim.leaf_unlink` -- globals, not @-locals, so a
# program that emits the relink declares them once (P3; tests/fj/test_leaf_lists_fj.py today).
# `ll_p`/`ll_q`/`ll_base`/`ll_idx` are w/4 wide because hex.ptr_index moves w/4 nibbles out of its
# index and into its destination.
LEAF_LINK_DECLS = ["ll_enc: hex.vec 2", "ll_v: hex.vec 2", "ll_nxt: hex.vec 2",
                   "ll_p: hex.vec w/4", "ll_q: hex.vec w/4", "ll_base: hex.vec w/4",
                   "ll_idx: hex.vec w/4"]


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
