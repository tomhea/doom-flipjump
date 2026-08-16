"""M14-e — the runtime thing table's DATA, proved equivalent to the constants baked today.

`wall_renderer.subsector_action` bakes one block per (subsector, thing). M14-e replaces those with
per-INDEX tables plus two per-subsector tables, because two of the baked fields -- `sp_z` and
`sp_lt` -- are properties of where the thing IS, and change when it crosses a sector.

⚠ This test is the reason `doomfj.things` exists: it derives `sp_z` and `sp_lt` the runtime way, for
every thing at its spawn position, and requires them to equal the emitter's baked values. If that
holds, swapping baked blocks for table reads cannot move a pixel for a static thing -- which is what
lets the M14-e gate blame any divergence on the moving half rather than on the migration.
"""
from pathlib import Path

import pytest

from doomfj.config import Config
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import COLORMAP_LIGHTS, MONSTER_TYPES, ReferenceModel
from doomfj.things import (reachable_lightnums, subsector_tables, thing_rows,
                           THING_ROW_BYTES, THING_ROW_LEN)
from doomfj.wad import WadFile
from doomfj.wall_renderer import _lines_sprite_bank, _lines_sprite_light, _thing_sector

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
ART = Path("assets/freedoom1.wad")


@pytest.fixture(scope="module")
def level():
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1)
    art = WadFile.from_path(ART)
    cmap = bake_bsp(mw, "E1M1")
    lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
    _bank, spr_base, spr_dw, spr_ldbase = _lines_sprite_bank(rm, art, cfg, mw, "E1M1")
    _lt, spr_cls = _lines_sprite_light(rm, cfg, art, mw, "E1M1", cmap, lds, sds, secs)
    return cfg, rm, mw, art, cmap, lds, sds, secs, spr_base, spr_dw, spr_ldbase, spr_cls


def _build(level, deg=True, spr_near=True):
    from doomfj.reference_model import (DEG_MINH2_MON, DEG_MINH2_SCENERY, MIN_SPRITE_H,
                                        MIN_SPRITE_H_MONSTER)
    cfg, rm, mw, art, cmap, lds, sds, secs, spr_base, spr_dw, spr_ldbase, spr_cls = level
    things = mw.things("E1M1")
    rows, idx = thing_rows(rm, things, art, spr_base, spr_ldbase, spr_dw, MONSTER_TYPES,
                           MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON,
                           deg=deg, spr_near=spr_near)
    ssfloor, sslight = subsector_tables(rm, cmap, lds, sds, secs)
    return things, rows, idx, ssfloor, sslight


def _interior_point(cmap, ss):
    """A point inside subsector `ss`, or None if the centroid escapes it (convex leaves are the
    normal case, but E1M1 has degenerate ones). Used to MOVE a thing somewhere for real, so the
    control below runs the production descent instead of a test-local restatement of it."""
    ssd = cmap.subsectors[ss]
    if not ssd.numsegs:
        return None
    pts = []
    for si in range(ssd.firstseg, ssd.firstseg + ssd.numsegs):
        sg = cmap.segs[si]
        pts.append(cmap.vertexes[sg.v1])
        pts.append(cmap.vertexes[sg.v2])
    return (round(sum(p[0] for p in pts) / len(pts)), round(sum(p[1] for p in pts) / len(pts)))


def test_the_rows_cover_exactly_the_drawable_things(level):
    """The row set must be the SAME set the emitter bakes -- `sprite_art`-resolvable things -- or
    the migration would silently add or drop sprites."""
    cfg, rm, mw, art, *_ = level
    things = mw.things("E1M1")
    _t, rows, idx, *_ = _build(level)
    cache = {}
    want = [i for i, t in enumerate(things) if rm.sprite_art(art, t.type, cache) is not None]
    assert idx == want
    # ⚠ THE INVARIANT IS `idx == want`, not the magnitude. The absolute count follows
    # reference_model.DROPPED_SPRITE_TYPES (the 25M sprite package): E1M1 has 251 drawable things
    # with every class enabled and 53 with monsters only. The bound below exists solely to catch
    # the fixture silently emptying, so it tracks the smaller configuration.
    assert len(rows) == len(want) > 40
    for r in rows:
        assert len(r) == len(THING_ROW_BYTES)
        for v, nb in zip(r, THING_ROW_BYTES):
            assert 0 <= (v & ((1 << (8 * nb)) - 1)) < (1 << (8 * nb))
    assert THING_ROW_LEN == 22


def test_runtime_sp_z_and_sp_lt_equal_the_baked_constants(level):
    """⚠ THE EQUIVALENCE PROOF. `sp_z` and `sp_lt` are the two fields that stop being constant once
    a thing moves. Derived from the bound subsector at spawn, they must reproduce exactly what the
    emitter bakes today -- for every drawable thing, not a sample."""
    cfg, rm, mw, art, cmap, lds, sds, secs, *_rest = level
    things, rows, idx, ssfloor, sslight = _build(level)
    spr_cls = level[-1]
    cache = {}
    baked = {}
    for t_i in idx:
        t = things[t_i]
        a = rm.sprite_art(art, t.type, cache)
        tsec = _thing_sector(rm, cmap, lds, sds, secs, t)
        baked[t_i] = (tsec.floor_h + a[6],
                      spr_cls[(rm.wall_lightnum(tsec.light, 0), max(1, a[4]))])
    # the flat `sprlt` array cannot be built until the shade-row bank is widened (see the last
    # test), so the DERIVATION is proved through the dict the array will hold: sp_lt is a function
    # of the BOUND subsector's light and the thing's height, and nothing else.
    def lt_of(ss, row_i):
        return spr_cls[(sslight[ss], max(1, rows[row_i][2]))]

    bad = []
    for row_i, t_i in enumerate(idx):
        ss = rm.point_in_subsector(cmap, things[t_i].x, things[t_i].y)
        fl = ssfloor[ss] if ssfloor[ss] < 0x8000 else ssfloor[ss] - 0x10000
        got = (fl + rows[row_i][3], lt_of(ss, row_i))
        if got != baked[t_i]:
            bad.append((t_i, got, baked[t_i]))
    assert not bad, f"{len(bad)} things derive differently at rest: {bad[:5]}"


def test_a_thing_moved_into_another_sector_takes_that_sector_s_floor_and_light(level):
    """⚠ THE CONTROL. The test above passes even if the derivation ignored the subsector entirely
    and returned the baked value -- every thing is at its spawn position there. This one MOVES a
    thing into a different sector and requires sp_z / sp_lt to follow it, which is the entire point
    of the rung: the two fields must be functions of where the thing IS.

    ⚠ CR-2026-08 (TS-2): the previous version of this control could not fail. It compared
    `(z_away + off, lt_away)` against `(z_home + off, lt_home)` where all four values were computed
    IN THE TEST from `ssfloor`/`sslight`/`spr_cls`, under a guard that had already skipped the
    equal case -- so it asserted `spr_cls` is injective and never called the derivation at all.
    This version moves the thing and runs BOTH production paths on the moved thing: the emitter's
    `_thing_sector` (which bakes the constant) and `things.subsector_tables` (which the runtime
    table reads). They must agree with each other AND differ from the home answer -- so a
    `_thing_sector` that ignored position fails the first clause, and a fixture that never really
    moved anything fails the second."""
    from dataclasses import replace
    cfg, rm, mw, art, cmap, lds, sds, secs, *_rest = level
    things, rows, idx, ssfloor, sslight = _build(level)
    spr_cls = level[-1]

    def derive(t, ss, row_i):
        """(sp_z, sp_lt) both ways for thing `t` standing in subsector `ss`."""
        fl = ssfloor[ss] if ssfloor[ss] < 0x8000 else ssfloor[ss] - 0x10000
        table = (fl + rows[row_i][3], spr_cls[(sslight[ss], max(1, rows[row_i][2]))])
        sec = _thing_sector(rm, cmap, lds, sds, secs, t)         # the emitter's baked half
        baked = (sec.floor_h + rows[row_i][3],
                 spr_cls[(rm.wall_lightnum(sec.light, 0), max(1, rows[row_i][2]))])
        return table, baked

    moved = 0
    for row_i, t_i in enumerate(idx):
        t = things[t_i]
        home = rm.point_in_subsector(cmap, t.x, t.y)
        home_table, home_baked = derive(t, home, row_i)
        assert home_table == home_baked, f"thing {t_i} disagrees at home"
        for ss, ssd in enumerate(cmap.subsectors):
            if not ssd.numsegs or ss == home:
                continue
            if (ssfloor[ss], sslight[ss]) == (ssfloor[home], sslight[home]):
                continue                       # same floor AND light: nothing would change
            h = max(1, rows[row_i][2])
            if (sslight[ss], h) not in spr_cls or (sslight[home], h) not in spr_cls:
                continue                       # a pair the bank does not carry yet
            # a point INSIDE ss, so `_thing_sector`'s own descent lands there: the seg midpoint
            # nudged towards the leaf's interior along the seg normal.
            pt = _interior_point(cmap, ss)
            if pt is None or rm.point_in_subsector(cmap, *pt) != ss:
                continue
            away_table, away_baked = derive(replace(t, x=pt[0], y=pt[1]), ss, row_i)
            assert away_table == away_baked, (
                f"thing {t_i} moved to ss{ss}: the runtime table derives {away_table} but the "
                f"emitter bakes {away_baked} -- the two halves disagree once it moves")
            assert away_baked != home_baked, (
                f"thing {t_i} derives identically in ss{home} and ss{ss} -- _thing_sector is not "
                f"position-driven")
            moved += 1
            break
        if moved >= 20:
            break
    assert moved >= 20, f"only {moved} things could be moved to a differing sector"


def test_the_shade_row_bank_must_be_widened_and_by_how_much(level):
    """⚠ THE BLOCKER M14-e HITS, measured rather than discovered as a KeyError mid-build.

    `_lines_sprite_light` bakes only the (lightnum, height) pairs that OCCUR AT SPAWN, because a
    static thing never sees another. A thing that walks into a differently-lit sector needs a pair
    that was never baked, so the bank has to be widened first.

    The size of that widening is the point: naively it is every COLORMAP_LIGHTS, but a thing can
    only ever stand in a REAL SECTOR, and far fewer lightnums occur among them. This asserts the
    cheap bound holds, so the next session budgets 2.8x and not 9x."""
    cfg, rm, mw, art, cmap, lds, sds, secs, *_rest = level
    spr_cls = level[-1]
    things, rows, idx, *_ = _build(level)
    heights = {max(1, r[2]) for r in rows}
    reach = reachable_lightnums(rm, secs)
    naive = COLORMAP_LIGHTS * len(heights)
    needed = len(reach) * len(heights)
    assert len(spr_cls) < needed, "the bank already covers every reachable pair -- no widening left"
    assert needed < naive, "the reachable restriction must actually save something"
    assert needed / len(spr_cls) < 4, (
        f"widening is {needed / len(spr_cls):.1f}x today ({len(spr_cls)} -> {needed} pairs); "
        "over 4x would want re-thinking before it ships")
    # and the missing pairs must be exactly the reachable ones nobody stands in today
    missing = {(ln, h) for ln in reach for h in heights if (ln, h) not in spr_cls}
    assert missing, "nothing missing means moving things need no widening, which contradicts above"


def test_the_widened_shade_row_bank_is_additive_and_covers_every_reachable_pair(level):
    """M14-e's bank widening, and the property that makes it safe to ship.

    `_lines_sprite_light(moving_things=True)` APPENDS the reachable pairs after the spawn ones, so
    every class a static thing already bakes keeps its index. That is what makes the widening
    pixel-neutral on its own: a static thing's `sp_lt` is bit-identical before and after, and any
    divergence the M14-e gate then finds belongs to the moving half, not to the bank."""
    cfg, rm, mw, art, cmap, lds, sds, secs, *_rest = level
    static_txt, static_cls = _lines_sprite_light(rm, cfg, art, mw, "E1M1", cmap, lds, sds, secs)
    wide_txt, wide_cls = _lines_sprite_light(rm, cfg, art, mw, "E1M1", cmap, lds, sds, secs,
                                             moving_things=True)
    # ⚠ the property that matters: indices are preserved, not merely present
    for pair, idx in static_cls.items():
        assert wide_cls[pair] == idx, f"{pair} moved from class {idx} to {wide_cls[pair]}"
    heights = {h for (_ln, h) in static_cls}
    for ln in reachable_lightnums(rm, secs):
        for h in heights:
            assert (ln, h) in wide_cls, f"a thing standing in light {ln} at height {h} has no class"
    ratio = len(wide_cls) / len(static_cls)
    assert 1 < ratio < 4, f"widening is {ratio:.1f}x ({len(static_cls)} -> {len(wide_cls)})"
    assert len(wide_txt) > len(static_txt)


def test_the_oracle_renders_the_same_frame_from_explicit_spawn_positions(level):
    """M14-e's oracle half, and the reason it is nearly free: `render_wall_frame` already binds
    things by calling `point_in_subsector(t.x, t.y)`, so it is position-driven ALREADY. Handing it
    the spawn positions explicitly must reproduce today's frame bit for bit."""
    from doomfj.reference_model import SimState, THING_SPRITE, build_scene, spawn_state
    cfg, rm, mw, art, cmap, *_rest = level
    scene = build_scene(mw, mw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    kw = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
              near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)
    st = SimState(sp.x, sp.y, sp.angle, "E1M1")
    base = bytes(rm.render_wall_frame(st, scene, **kw))
    pos = [(t.x, t.y) for t in mw.things("E1M1") if THING_SPRITE.get(t.type) is not None]
    same = bytes(rm.render_wall_frame(st, scene, thing_positions=pos, **kw))
    assert same == base, "explicit spawn positions changed the frame"
    # ⚠ THE CONTROL: moving things must CHANGE the frame, or the parameter is being ignored.
    # Move all of them, not thing[0] -- the first drawable thing is nowhere near the spawn view, so
    # moving it changes no pixel and the control passed vacuously on the first attempt.
    # M14.5: ... all of the RUNTIME ones. A baked thing is code inside its leaf and has no position
    # on the wire, so moving one here would compare a world fj cannot render.
    from doomfj.things import baked_thing_mask
    drawable = [t for t in mw.things("E1M1") if THING_SPRITE.get(t.type) is not None]
    baked = baked_thing_mask(rm, scene.cmap, drawable, MONSTER_TYPES)
    assert not all(baked) and any(baked), "the split is degenerate -- this control proves nothing"
    moved = [(x, y) if b else (x + 64, y + 64) for (x, y), b in zip(pos, baked)]
    other = bytes(rm.render_wall_frame(st, scene, thing_positions=moved, **kw))
    assert other != base, "moving every thing changed nothing -- thing_positions is not wired through"
    # ⚠ ... and the other side of it: moving a BAKED thing must be REFUSED, not silently rendered.
    # That is the only thing standing between a host bug and two mirrors drawing different worlds.
    bad = [(x + 64, y + 64) if b else (x, y) for (x, y), b in zip(pos, baked)]
    with pytest.raises(AssertionError, match="BAKED"):
        rm.render_wall_frame(st, scene, thing_positions=bad, **kw)


def test_the_runtime_pass_clears_every_register_the_baked_block_xors(level):
    """M14.5 — THE ZERO INVARIANT, tied down so it cannot drift apart again.

    A hybrid build sources the sprite registers two ways: BAKED things get an `hex.xor_by` block,
    which is self-restoring ONLY because it starts from zero, and RUNTIME things get `thing_load`,
    which writes the same cells with mov/read and leaves them holding the last thing. So
    `sim.thing_pass` clears them before it returns.

    That is a correspondence between a list in `wall_renderer.subsector_action` and a list in
    `src/fj/sim.fj`, in different languages, with no compiler to check it -- and getting it wrong
    costs a 40-minute build and shows up as a handful of sprite-shaped pixels (MEASURED: 25 px at
    (1869,479), 29 px at spawn). So the test reads BOTH and requires every xored register to be
    cleared, at least as wide as it is declared.
    """
    import re
    from doomfj.wall_renderer import _seg_xorby_block
    cfg, rm, mw, art, cmap, *_rest = level
    src = (Path(__file__).resolve().parents[2] / "src/fj/sim.fj").read_text(encoding="utf-8")
    body = src[src.index("def thing_pass"):]
    body = body[:body.index("\n}")]
    cleared = {m.group(2): int(m.group(1))
               for m in re.finditer(r"hex\.zero\s+(\d+),\s*(sp_\w+)", body)}
    assert cleared, "sim.thing_pass clears nothing -- the zero invariant is gone"

    # ⚠ CR-2026-08 (TS-3/ST-7): read the emitter's OWN schema. This list used to be hand-copied
    # here, so a register added to the xor_by block was invisible to the test that exists to catch
    # exactly that -- a control that cannot fail. `emit_wall_renderer` now asserts it builds from
    # THING_XORBY_FIELDS, so the two ends are pinned to one constant.
    from doomfj.wall_renderer import THING_XORBY_FIELDS
    fields = [(n, w, 0) for n, w in THING_XORBY_FIELDS]
    emitted = {line.split(",")[1].strip() for line in _seg_xorby_block("t", fields)
               if line.strip().startswith("hex.xor_by")}
    missing = sorted(emitted - set(cleared))
    assert not missing, (
        f"sim.thing_pass leaves {missing} dirty, and the next leaf's baked xor_by block would "
        f"land on a non-zero register")
    # ... and wide enough: a narrow clear leaves high nibbles set, which is the same bug
    decls = dict(re.findall(r"\"(sp_\w+): hex\.vec (\d+)\"",
                            (Path(__file__).resolve().parents[2]
                             / "src/doomfj/wall_renderer.py").read_text(encoding="utf-8")))
    # ⚠ CR-2026-08 (TS-3): the `r in decls` filter used to make this whole check vanish if the
    # regex stopped matching -- a rename of the decl line, and the width half silently passed on an
    # empty set. Require the declarations to cover every xored register FIRST.
    undeclared = sorted(emitted - set(decls))
    assert not undeclared, (
        f"no `hex.vec` declaration found for {undeclared} -- the decl regex has gone stale and the "
        f"width check below would have passed vacuously")
    narrow = {r: (cleared[r], int(decls[r])) for r in emitted if cleared[r] < int(decls[r])}
    assert not narrow, f"cleared narrower than declared: {narrow}"


def test_both_mirrors_build_the_drawable_list_with_the_same_predicate(level):
    """⚠ CR-2026-08 (RM-1/ST-1) — THE INDEX SPACE, one predicate.

    `thing_positions`, the `thvis` visibility slots and `baked_thing_mask` are all keyed by position
    in "the drawable list", so the emitter and the oracle must build that list the same way. They
    did not: the emitter asked `things.drawable_things` (`sprite_art(...) is not None`, which is also
    None when the type is in the table but THE WAD HAS NO LUMP), while the oracle asked only whether
    the type was in `THING_SPRITE`. On the full Freedoom art wad the two agree -- which is why every
    gate passed -- and on any wad missing a lump every index after the first absent sprite shifts in
    one mirror only, silently.

    So this test pins the two together AND proves the two predicates are genuinely different, using
    an art wad with a sprite lump removed. Without the second half the first is a tautology on the
    only wad we ship.
    """
    from doomfj.reference_model import THING_SPRITE
    from doomfj.things import drawable_things
    cfg, rm, mw, art, *_rest = level
    things = mw.things("E1M1")

    ssot, _idx = drawable_things(rm, things, art, {})
    loose = [t for t in things if THING_SPRITE.get(t.type) is not None]
    assert [(t.x, t.y, t.type) for t in ssot] == [(t.x, t.y, t.type) for t in loose], \
        "the two predicates already disagree on the shipped art wad"

    # ⚠ THE CONTROL: a wad whose sprite lumps are all missing. `drawable_things` must shrink;
    # the loose predicate cannot. If this passed, the test above would prove nothing.
    class _NoArt:
        def get_data(self, name):
            raise KeyError(name)
    empty, _ = drawable_things(rm, things, _NoArt(), {})
    assert not empty and loose, (
        "with no sprite lumps at all `drawable_things` still returned things -- the two predicates "
        "are the same after all, and this test has no teeth")
