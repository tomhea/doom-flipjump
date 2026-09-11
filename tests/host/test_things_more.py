"""`doomfj.things` — the LAYOUT CONTRACTS around the runtime thing table.

`tests/host/test_thing_table.py` proves the one thing the module was written for: `sp_z` and
`sp_lt` derive at runtime to exactly what the emitter bakes. It does that by RE-IMPLEMENTING the
derivation inline, and it touches almost nothing else in the module. This file pins the rest --
the index spaces and the row layout that every one of those numbers is addressed through:

* **The row split is a PARTITION.** `_HOT_FIELDS`/`_COLD_FIELDS` carve `THING_ROW_BYTES` in two.
  The module-level assert only checks the two WIDTHS add up, so it still passes for an edit that
  duplicates one 2-byte field into both halves and drops another. That ships a `throw` table where
  every drawn sprite reads a bogus z-offset, visible only as pixels 40 minutes into a build.

* **The fj mirror reads the same offsets.** `sim.thing_load` and `frame.thing_load_cold` address
  the row with BAKED constants (`row + 16*dw`, `hex.read_table_packed 17`). Widen or reorder a
  Python-side field and fj keeps reading the old ones, with no Python-side symptom at all. This is
  the same two-mirror class `test_the_runtime_pass_clears_every_register_the_baked_block_xors`
  guards for the xor_by/zero pair; nothing guarded the row.

* **Slot and index spaces.** `vanishable_slots` numbers a compile-time address (`thvis + slot*2*dw`)
  AND a byte position in `wireformat.encode_visibility`; `thing_rows(keep=...)` is keyed by WAD
  index while everything around it is keyed by DRAWABLE index. Renumber either and the host hides
  or draws the wrong thing -- with every width still looking right.

* **M4 (nine levels) blockers, priced in 0.1 s instead of 40 minutes.** The leaf-homogeneity rule
  `baked_thing_mask` implements, and the `nt < 0xFF` ceiling `_moving_thing_tables` asserts. The
  second one is VIOLATED TODAY on two E1 maps, which is why that test is parametrised and xfailed
  rather than written as a passing assertion -- see its docstring for the measured counts.

* **`sprite_light_table`'s flat layout**, whose index formula is duplicated in three places (here,
  `check_row_equivalence`, and fj's `thing_load_cold` via `ss_ltb + sp_ti`). A transpose gives every
  sprite another thing's light class and stays in bounds, so nothing raises.

* **`check_row_equivalence` itself**, called for real. It is the function that gates the migration
  and no test called it; the proof lived in a test-local copy of the derivation, so the two could
  drift apart while agreeing with each other.

Nothing here builds or assembles anything: the heaviest input is `assets/freedoom1.wad` read as
data, and the whole file runs in about a second.
"""
from __future__ import annotations

import itertools
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from doomfj.config import Config
from doomfj.mapcompiler import bake_bsp, seg_sector
from doomfj.reference_model import (DEG_MINH2_MON, DEG_MINH2_SCENERY, MIN_SPRITE_H,
                                    MIN_SPRITE_H_MONSTER, MONSTER_TYPES, VANISHABLE_TYPES,
                                    ReferenceModel)
from doomfj.things import (THING_ROW_BYTES, THING_ROW_COLD_BYTES, THING_ROW_COLD_LEN,
                           THING_ROW_HOT_BYTES, THING_ROW_HOT_LEN, THING_ROW_LEN,
                           baked_thing_mask, check_row_equivalence, cold_row, drawable_things,
                           hot_row, reachable_lightnums, sprite_light_table, subsector_tables,
                           thing_rows, vanishable_slots)
from doomfj.wad import WadFile
from doomfj.wall_renderer import _lines_sprite_light, _thing_sector

ROOT = Path(__file__).resolve().parents[2]
LITE = ROOT / "tests/fixtures/e1m1_lite.wad"
EPISODE = ROOT / "assets/freedoom1.wad"          # the only wad here that carries E1M2..E1M9
E1_MAPS = [f"E1M{i}" for i in range(1, 10)]

# 0xFF is the empty/end sentinel of `thnext`/`sshead`, so the highest usable runtime index is 254.
# `wall_renderer._moving_thing_tables` asserts `nt < 0xFF` on len(rows) with `keep` applied.
RUNTIME_THING_CAP = 0xFF


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def art():
    return WadFile.from_path(EPISODE)


@pytest.fixture(scope="module")
def lite(art):
    """e1m1_lite: small, and it carries sectors with NEGATIVE floor heights (-168/-160/-152), which
    is the case the 16-bit two's-complement storage exists for."""
    rm = ReferenceModel(Config())
    mw = WadFile.from_path(LITE)
    cmap = bake_bsp(mw, "E1M1")
    return SimpleNamespace(
        cfg=Config(), rm=rm, mw=mw, art=art, cmap=cmap,
        lds=mw.linedefs("E1M1"), sds=mw.sidedefs("E1M1"), secs=mw.sectors("E1M1"),
        things=mw.things("E1M1"))


@pytest.fixture(scope="module")
def spr_tables(lite):
    """SYNTHETIC `spr_base`/`spr_ldbase`/`spr_dw`, deliberately not the emitter's.

    The real ones come out of `_lines_sprite_bank`, which emits ~100M characters and takes minutes.
    Every property in this file is about WHICH value lands in WHICH field, so distinct synthetic
    values per type are strictly better evidence than the real ones: they make a swapped field
    visible. Widths follow THING_ROW_BYTES (base/base2 uint16, dw uint8)."""
    types = sorted({t.type for t in lite.things})
    return (
        {ty: 1000 + 7 * i for i, ty in enumerate(types)},        # spr_base   (2 bytes)
        {ty: 2000 + 5 * i for i, ty in enumerate(types)},        # spr_ldbase (2 bytes)
        {ty: 1 + (i % 4) for i, ty in enumerate(types)},         # spr_dw     (1 byte)
    )


def _rows(lite, spr_tables, *, deg=True, spr_near=True, keep=None, cache=None):
    spr_base, spr_ldbase, spr_dw = spr_tables
    return thing_rows(lite.rm, lite.things, lite.art, spr_base, spr_ldbase, spr_dw, MONSTER_TYPES,
                      MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON,
                      deg=deg, spr_near=spr_near, keep=keep, cache=cache)


@pytest.fixture(scope="module")
def rows_idx(lite, spr_tables):
    return _rows(lite, spr_tables)


@pytest.fixture(scope="module")
def episode(art):
    """Every E1 map's drawable/baked split, computed once. MEASURED: 0.1 s for all nine, which is
    what makes the two M4 invariants below a one-second gate instead of a build-time AssertionError.

    ⚠ ONE `spr_cache` across all nine maps, exactly as `build_wall_renderer` does it."""
    rm = ReferenceModel(Config())
    cache: dict = {}
    out = {}
    for mn in E1_MAPS:
        cmap = bake_bsp(art, mn)
        things = art.things(mn)
        drawable, widx = drawable_things(rm, things, art, cache)
        baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
        leaves = [rm.point_in_subsector(cmap, t.x, t.y) for t in drawable]
        out[mn] = SimpleNamespace(cmap=cmap, things=things, drawable=drawable, widx=widx,
                                  baked=baked, leaves=leaves)
    return out


# ── the row split is a partition, and fj reads it at the same offsets ───────────────────────────
def test_hot_and_cold_fields_partition_the_thing_row(lite, rows_idx):
    """`hot_row(r) + cold_row(r)` must be a PERMUTATION of `r` -- every field carried exactly once.

    The module-level `assert THING_ROW_HOT_LEN + THING_ROW_COLD_LEN == THING_ROW_LEN` checks only
    the widths, so it survives an edit that duplicates a 2-byte field into both halves while
    dropping another 2-byte one (e.g. `_HOT_FIELDS=(0,1,2,0,4,5,8)`): same total width, and every
    drawn sprite then reads a bogus z-offset out of `throw`.

    Run on a REAL row, not a synthetic tuple, so the declared widths are checked against values the
    emitter would actually pack."""
    rows, _idx = rows_idx
    assert rows, "no rows -- the fixture wad has gone empty and this proves nothing"
    for r in rows[:1] + rows[-1:]:
        h, c = hot_row(r), cold_row(r)
        assert len(h) == len(THING_ROW_HOT_BYTES) and len(c) == len(THING_ROW_COLD_BYTES)
        # a permutation: same multiset, and every source position accounted for exactly once
        assert sorted(h + c) == sorted(r), "hot+cold is not a permutation of the row"
        assert len(h) + len(c) == len(THING_ROW_BYTES) == len(r)
    # ... and the partition is of POSITIONS, which a multiset check alone cannot see when two
    # fields happen to hold equal values. Probe with a row whose every field is distinct.
    probe = tuple(range(len(THING_ROW_BYTES)))
    assert sorted(hot_row(probe) + cold_row(probe)) == list(probe), \
        "a field is duplicated or dropped between the hot and cold halves"
    # each value must be declared at the width its own half claims for that position
    for value, nb in zip(hot_row(probe), THING_ROW_HOT_BYTES):
        assert THING_ROW_BYTES[value] == nb, "THING_ROW_HOT_BYTES disagrees with _HOT_FIELDS"
    for value, nb in zip(cold_row(probe), THING_ROW_COLD_BYTES):
        assert THING_ROW_BYTES[value] == nb, "THING_ROW_COLD_BYTES disagrees with _COLD_FIELDS"
    assert THING_ROW_HOT_LEN + THING_ROW_COLD_LEN == THING_ROW_LEN == sum(THING_ROW_BYTES)


def _macro_body(relpath: str, name: str) -> str:
    """One fj macro's body, comments stripped (the word `row` occurs in them)."""
    src = (ROOT / relpath).read_text(encoding="utf-8")
    body = src[src.index(f"def {name} "):]
    return re.sub(r"//.*", "", body[:body.index("\n    }")])


def _row_reads(relpath: str, name: str):
    """`(nb, vec_nibbles, {nibble offset})` for the packed row `name` reads.

    Derived from the source, with no name list to go stale: find the `hex.read_table_packed nb,
    REG, ...` that fills the row, its `REG: hex.vec n` declaration, then every OTHER mention of
    `REG` -- which is a field read, at `REG` (offset 0) or `REG + k*dw`."""
    body = _macro_body(relpath, name)
    m = re.search(r"hex\.read_table_packed\s+(\d+),\s*(\w+),", body)
    assert m, f"{name} no longer fills its row with hex.read_table_packed"
    nb, reg = int(m.group(1)), m.group(2)
    vec = re.search(rf"^\s*{reg}:\s*hex\.vec\s+(\d+)", body, re.M)
    assert vec, f"{name} has no `{reg}: hex.vec` declaration"
    rest = "\n".join(ln for ln in body.splitlines()
                     if "read_table_packed" not in ln and not ln.strip().startswith(reg + ":"))
    offs = {int(mm.group(1) or 0)
            for mm in re.finditer(rf"\b{reg}\b(?:\s*\+\s*(\d+)\s*\*\s*dw)?", rest)}
    return nb, int(vec.group(1)), offs


def _field_starts(widths):
    """Nibble offset of each field start: byte k lives at nibble 2k."""
    return {2 * b for b in itertools.accumulate((0,) + tuple(widths[:-1]))}


@pytest.mark.parametrize("relpath,macro,widths,nbytes", [
    ("src/fj/sim.fj", "thing_load", THING_ROW_HOT_BYTES, THING_ROW_HOT_LEN),
    ("src/fj/frame_render.fj", "thing_load_cold", THING_ROW_COLD_BYTES, THING_ROW_COLD_LEN),
])
def test_the_fj_mirror_reads_the_row_at_the_python_field_offsets(relpath, macro, widths, nbytes):
    """⚠ THE TWO-MIRROR CHECK for the row LAYOUT, which nothing else guards.

    `hex.read_table_packed nb, ...` derives its stride from `nb`, and every field read is a baked
    `row + k*dw` constant. So widening or reordering a Python-side field shifts every later byte
    while fj keeps the old constants -- sprite left/width/half-height/depth-bounds come out garbage
    and no Python-side test notices. The fj side is read from source (no assembling), and the
    expected set is DERIVED from THING_ROW_*_BYTES, so there is no name list to go stale.

    MEASURED: hot offsets {0,4,8,12,16,24,32}, cold {0,4,8}; nb 17/5; hex.vec 34/10."""
    nb, vec, offs = _row_reads(relpath, macro)
    assert nb == nbytes, f"{macro} reads {nb} bytes per row; Python packs {nbytes}"
    assert vec == 2 * nbytes, f"{macro}'s row vec is {vec} nibbles; {nbytes} bytes need {2 * nbytes}"
    want = _field_starts(widths)
    assert offs == want, f"{macro} reads nibble offsets {sorted(offs)}, fields start at {sorted(want)}"
    assert len(offs) == len(widths), f"{macro} reads {len(offs)} fields, the row has {len(widths)}"


# ── vanishable_slots: a dense, order-preserving numbering ───────────────────────────────────────
def test_vanishable_slots_is_a_dense_order_preserving_bijection(lite):
    """The slot is a COMPILE-TIME ADDRESS (`hex.if0 1, thvis + slot*2*dw`) and simultaneously a byte
    position in `wireformat.encode_visibility`'s block. So the numbering must be dense, ascending in
    drawable order, and exactly the baked vanishable things -- a rewrite that sorted by type would
    renumber every slot while every width still looked right, and the host would hide the wrong
    thing. MEASURED on e1m1_lite: 80 slots from 110 baked of 197 drawable."""
    drawable, _ = drawable_things(lite.rm, lite.things, lite.art, {})
    baked = baked_thing_mask(lite.rm, lite.cmap, drawable, MONSTER_TYPES)
    slots = vanishable_slots(drawable, baked, VANISHABLE_TYPES)
    assert slots, "no vanishable baked things -- this fixture proves nothing"
    keys = list(slots)
    assert keys == sorted(keys), "slots are not in ascending drawable order"
    assert list(slots.values()) == list(range(len(slots))), "the slot numbering is not dense"
    want = [i for i, (t, b) in enumerate(zip(drawable, baked))
            if b and t.type in VANISHABLE_TYPES]
    assert keys == want, "membership is not exactly (baked AND vanishable type)"
    assert vanishable_slots(drawable, baked, VANISHABLE_TYPES) == slots, "not deterministic"
    # a runtime thing must never get a slot: it carries a position the host can move instead
    assert not any(slots.get(i) is not None for i, b in enumerate(baked) if not b)


def test_vanishable_slots_numbers_by_drawable_order_not_by_type():
    """⚠ THE CONTROL for the test above, which cannot distinguish orderings on a wad where the
    vanishable things happen to be type-sorted already. Two things of DECREASING type: slot 0 must
    go to the earlier drawable index regardless."""
    drawable = [SimpleNamespace(type=9, x=0, y=0), SimpleNamespace(type=2, x=0, y=0)]
    slots = vanishable_slots(drawable, (True, True), {2, 9})
    assert slots == {0: 0, 1: 1}, "slots follow type order, not drawable order"


# ── baked_thing_mask: THE RULE, and M4's homogeneity invariant ──────────────────────────────────
class _StubRM:
    """Just enough ReferenceModel for `baked_thing_mask`/`check_row_equivalence`: point location,
    driven by a dict so a synthetic leaf layout needs no wad."""

    def __init__(self, leaf_of):
        self.leaf_of = leaf_of

    def point_in_subsector(self, cmap, x, y):
        return self.leaf_of[(x, y)]


def test_baked_thing_mask_is_not_a_monster_and_no_monster_in_the_leaf():
    """THE RULE (handoff-m14_5 section 4b), on a synthetic leaf layout so every case is present.

    `test_thing_table` only asserts `not all(baked) and any(baked)` on the real map, which passes
    for almost any wrong rule -- an `or` for the `and`, or dropping the `mon_leaves` term. Both
    mistakes make a leaf MIXED at spawn, and a mixed leaf is visited "all baked then all runtime"
    in the fj mirror only, which reorders sprite-slot claims and the acceptance counters."""
    mons = {64}
    # leaf 0: a monster and a barrel. leaf 1: a lone barrel. leaf 2: a lone monster.
    pos = {"mon_a": (0, 0), "dec_a": (1, 0), "dec_b": (0, 1), "mon_b": (0, 2)}
    rm = _StubRM({pos["mon_a"]: 0, pos["dec_a"]: 0, pos["dec_b"]: 1, pos["mon_b"]: 2})
    drawable = [SimpleNamespace(type=64, x=0, y=0), SimpleNamespace(type=2, x=1, y=0),
                SimpleNamespace(type=2, x=0, y=1), SimpleNamespace(type=64, x=0, y=2)]
    assert baked_thing_mask(rm, None, drawable, mons) == (False, False, True, False), \
        "the rule is not (not a monster) AND (no monster shares the leaf)"


def test_baked_thing_mask_is_driven_by_the_positions_it_is_given():
    """The mask is a property of the THING computed from SPAWN positions -- so moving the decoration
    out of the monster's leaf must flip it to baked. Without this, the test above passes for a rule
    that ignores `mon_leaves` and simply returns `type not in monster_types` for leaf 1."""
    mons = {64}
    rm = _StubRM({(0, 0): 0, (1, 0): 0, (9, 9): 7})
    with_mon = [SimpleNamespace(type=64, x=0, y=0), SimpleNamespace(type=2, x=1, y=0)]
    away = [SimpleNamespace(type=64, x=0, y=0), SimpleNamespace(type=2, x=9, y=9)]
    assert baked_thing_mask(rm, None, with_mon, mons) == (False, False), \
        "a decoration sharing a monster's leaf baked anyway -- the leaf is MIXED at spawn"
    assert baked_thing_mask(rm, None, away, mons) == (False, True), \
        "a decoration in its own leaf did not bake -- the mask ignores position"


def test_no_e1_map_has_a_mixed_leaf_at_spawn(episode):
    """M4's HOMOGENEITY INVARIANT, for all nine levels, in 0.1 s.

    `baked_thing_mask` exists to keep every leaf all-baked or all-runtime at spawn, so per-leaf
    visit order stays wad order in both mirrors. The emitter asserts this -- but only 20-40 minutes
    into a nine-level build. MEASURED here: mixed == 0 on E1M1..E1M9."""
    for mn, lv in episode.items():
        per: dict = {}
        for ss, b in zip(lv.leaves, lv.baked):
            per.setdefault(ss, set()).add(b)
        mixed = sorted(ss for ss, kinds in per.items() if len(kinds) > 1)
        assert not mixed, f"{mn}: subsectors {mixed[:5]} hold both a baked and a runtime thing"
        assert lv.drawable, f"{mn}: no drawable things at all"


@pytest.mark.parametrize("mapname", [
    pytest.param(mn, marks=pytest.mark.xfail(
        strict=True,
        reason="MEASURED M4 BLOCKER: E1M6 has 344 and E1M7 330 runtime things, over the 254 the "
               "thnext/sshead byte sentinel allows. Not a regression -- a nine-level build would "
               "die on wall_renderer._moving_thing_tables' `assert nt < 0xFF`. strict=True, so "
               "this flips to a FAILURE the moment either map fits (a widened index, or a bigger "
               "baked share) and the numbers here need updating."))
    if mn in ("E1M6", "E1M7") else mn
    for mn in E1_MAPS])
def test_the_runtime_thing_count_fits_the_byte_linked_list(episode, mapname):
    """M4's OTHER blocker: `thnext`/`sshead` are byte arrays with 0xFF as the empty sentinel, so the
    RUNTIME thing count (drawable minus baked) must stay under 255.

    MEASURED this session, runtime counts E1M1..E1M9: 75, 170, 248, 219, 250, 344, 330, 0, 181.
    E1M6 and E1M7 are over; E1M3 (248) and E1M5 (250) are within six. This is the cheapest M4
    blocker there is -- 0.1 s instead of a 40-minute emit that ends in an AssertionError."""
    lv = episode[mapname]
    runtime = len(lv.drawable) - sum(lv.baked)
    assert runtime < RUNTIME_THING_CAP, (
        f"{mapname}: {runtime} runtime things; the byte linked list tops out at "
        f"{RUNTIME_THING_CAP - 1}")


# ── thing_rows: the keep filter and the two feature gates ───────────────────────────────────────
def test_keep_selects_by_wad_index_not_by_drawable_index(lite, spr_tables, rows_idx):
    """`keep` is the set of WAD indices that take the runtime path (M14.5). Everything around it --
    `thing_positions`, `thvis` slots, `baked_thing_mask` -- is keyed by DRAWABLE index, so reading
    `keep` in the wrong space is a live hazard: the runtime table would carry a different set than
    `_mt_keep` intends and a thing gets drawn twice (leaf AND table) or not at all.

    The `keep` set is drawn from PAST the first divergence of the two index spaces (drawable
    position 52 on e1m1_lite), and the test asserts the drawable-index reading would give a
    genuinely different answer -- otherwise it would pass in both spaces."""
    rows, idx = rows_idx
    diverge = next(k for k, w in enumerate(idx) if k != w)
    assert diverge < len(idx) - 8, "the fixture no longer diverges early enough to distinguish"
    keep = set(idx[diverge:diverge + 8])
    krows, kidx = _rows(lite, spr_tables, keep=keep)

    assert kidx == sorted(keep), "keep did not select exactly its wad indices, in wad order"
    assert krows == [rows[idx.index(w)] for w in kidx], \
        "a filtered row differs from the row the unfiltered call built for the same wad index"
    # ⚠ the control: had `keep` been read as a set of DRAWABLE indices, the answer would differ
    naive = [idx[k] for k in sorted(keep) if k < len(idx)]
    assert naive != kidx, "the two index spaces coincide here -- this test cannot distinguish them"


def test_keep_and_the_baked_mask_partition_the_drawable_set(lite, spr_tables, rows_idx):
    """The emitter's split control, without building: rows(keep=runtime) and the baked things must
    together be exactly the drawable set, with no overlap. An off-by-one in either half is M14-a's
    silent failure mode -- a thing drawn twice, or vanished."""
    _rows_all, idx = rows_idx
    drawable, widx = drawable_things(lite.rm, lite.things, lite.art, {})
    baked = baked_thing_mask(lite.rm, lite.cmap, drawable, MONSTER_TYPES)
    runtime = {w for w, b in zip(widx, baked) if not b}
    baked_w = {w for w, b in zip(widx, baked) if b}
    _r, kidx = _rows(lite, spr_tables, keep=runtime)
    assert set(kidx).isdisjoint(baked_w), "a baked thing is also in the runtime table"
    assert set(kidx) | baked_w == set(idx) == set(widx), "the split loses or invents a thing"
    assert len(kidx) + len(baked_w) == len(idx)


def test_deg_and_spr_near_gate_their_own_fields(lite, spr_tables, rows_idx):
    """The two ternaries in `thing_rows` are only ever exercised True: no test passes deg=False or
    spr_near=False. `sim.thing_load` reads `sp_tzmax2` unconditionally, so a leaked non-zero in a
    deg=False build is a depth bound that rejects sprites which should draw, and a leaked `base2`
    indexes the wrong sprite bank. Both directions asserted, so neither control is vacuous."""
    rows, _ = rows_idx
    off_deg, _ = _rows(lite, spr_tables, deg=False)
    off_near, _ = _rows(lite, spr_tables, spr_near=False)
    assert all(r[5] == 0 for r in off_deg), "deg=False still baked a tzmax2 depth bound"
    assert all(r[7] == 0 for r in off_near), "spr_near=False still baked a base2 bank index"
    assert any(r[5] for r in rows), "deg=True bakes no tzmax2 -- the off-test proves nothing"
    assert any(r[7] for r in rows), "spr_near=True bakes no base2 -- the off-test proves nothing"
    # ... and nothing ELSE moved: each gate touches exactly one field, so every other field must be
    # bit-identical. (tzmax2 is hot index 5, base2 is cold index 1.)
    assert len(rows) == len(off_deg) == len(off_near)
    for r, d, n in zip(rows, off_deg, off_near):
        assert hot_row(r)[:5] + hot_row(r)[6:] == hot_row(d)[:5] + hot_row(d)[6:], \
            "deg=False changed a field other than tzmax2"
        assert cold_row(r) == cold_row(d), "deg=False reached into the cold half"
        assert hot_row(r) == hot_row(n), "spr_near=False reached into the hot half"
        assert cold_row(r)[0::2] == cold_row(n)[0::2], \
            "spr_near=False changed a field other than base2"


# ── subsector_tables ────────────────────────────────────────────────────────────────────────────
def test_subsector_tables_stay_parallel_to_the_subsector_list(lite):
    """Every consumer indexes these BY SUBSECTOR (`ssflr[ss]`, `sslgt[ss]`, `nss =
    len(cmap.subsectors)`), so a seg-less leaf has to occupy its own zero-filled slot -- dropping it
    would shift the floor height and light class of every later leaf.

    ⚠ Reached with a SPLICED STUB cmap on purpose: MEASURED, no fixture or shipped map has a
    seg-less subsector (e1m1_lite 0/471, freedoom_e1m1 0/682), so the branch is honestly dead on
    today's data and only M4's new maps could wake it. The invariant that matters -- index
    parallelism -- is testable without inventing a wad."""
    f, l = subsector_tables(lite.rm, lite.cmap, lite.lds, lite.sds, lite.secs)
    assert len(f) == len(l) == len(lite.cmap.subsectors)
    assert all(ss.numsegs for ss in lite.cmap.subsectors), \
        "the fixture grew a seg-less leaf; the splice below no longer isolates the branch"

    at = 5
    spliced = SimpleNamespace(
        subsectors=(list(lite.cmap.subsectors[:at]) + [SimpleNamespace(numsegs=0, firstseg=0)]
                    + list(lite.cmap.subsectors[at:])),
        segs=lite.cmap.segs)
    sf, sl = subsector_tables(lite.rm, spliced, lite.lds, lite.sds, lite.secs)
    assert len(sf) == len(f) + 1, "the seg-less leaf did not take a slot of its own"
    assert (sf[at], sl[at]) == (0, 0), "a seg-less leaf must hold (0, 0)"
    assert sf[:at] == f[:at] and sl[:at] == l[:at], "leaves before the empty one moved"
    assert sf[at + 1:] == f[at:] and sl[at + 1:] == l[at:], \
        "leaves after the empty one are shifted -- every later sprite takes the wrong floor/light"


def test_subsector_tables_store_floors_as_16_bit_twos_complement(lite):
    """The fj side receives an UNSIGNED 16-bit floor and adds mod 2^16, so a negative floor must be
    stored as its two's complement and round-trip back to the real sector height. Forget the
    `& 0xFFFF` (or store signed) and every sprite in a below-zero sector floats or sinks by 65536.
    e1m1_lite has sectors at -168/-160/-152, so the negative path is really exercised."""
    f, l = subsector_tables(lite.rm, lite.cmap, lite.lds, lite.sds, lite.secs)
    negatives = 0
    for ss, ssd in enumerate(lite.cmap.subsectors):
        sec = seg_sector(lite.lds, lite.sds, lite.secs, lite.cmap.segs[ssd.firstseg])
        assert 0 <= f[ss] <= 0xFFFF, "a floor escaped the 16-bit window fj reads it through"
        signed = f[ss] if f[ss] < 0x8000 else f[ss] - 0x10000
        assert signed == sec.floor_h, f"ss{ss} stores {f[ss]} for floor {sec.floor_h}"
        assert l[ss] == lite.rm.wall_lightnum(sec.light, 0)
        negatives += sec.floor_h < 0
    assert negatives, "no negative floor on this map -- the two's-complement path is not exercised"
    assert (f, l) == subsector_tables(lite.rm, lite.cmap, lite.lds, lite.sds, lite.secs), \
        "subsector_tables is not deterministic"


# ── sprite_light_table ──────────────────────────────────────────────────────────────────────────
def _row_with_height(h):
    """A THING_ROW_BYTES-shaped row whose only field that matters here is sp_hh (index 2)."""
    return (0, 0, h, 0, 0, 0, 0, 0, 0, 0)


def test_sprite_light_table_is_row_major_over_lightnums():
    """THE FLAT LAYOUT: `out[k * nthings + t]`. The same index formula lives in three places --
    here, `check_row_equivalence`, and fj's `thing_load_cold` as `ss_ltb + sp_ti` -- and a
    row/column transpose would still be IN BOUNDS, so nothing raises: every sprite would silently
    take another thing's light class. Synthetic classes, deliberately distinct per cell, so a
    transpose is visible."""
    cls = {(5, 3): 11, (5, 7): 12, (9, 3): 21, (9, 7): 22}
    rows = [_row_with_height(3), _row_with_height(7)]
    out = sprite_light_table(cls, rows, [5, 9])
    assert out == [11, 12, 21, 22], "the table is not row-major over lightnums"
    assert len(out) == len(rows) * 2
    for k, ln in enumerate([5, 9]):
        for t, r in enumerate(rows):
            assert out[k * len(rows) + t] == cls[(ln, r[2])]


def test_sprite_light_table_clamps_a_zero_height_to_one(lite, rows_idx):
    """The key height is `max(1, sp_hh)`, and `_lines_sprite_light` bakes the bank on `max(1,
    art[4])` -- the same bare constant in two modules with no SSOT. Drop it on either side and a
    zero-height sprite either raises mid-build or, worse, silently takes class (ln, 0) while the
    bank baked (ln, 1)."""
    assert sprite_light_table({(4, 1): 99}, [_row_with_height(0)], [4]) == [99], \
        "a zero-height sprite did not clamp to height 1"
    # ... and a bank holding only the UNCLAMPED key must be reported missing, not used
    with pytest.raises(KeyError, match="height"):
        sprite_light_table({(4, 0): 99}, [_row_with_height(0)], [4])

    # cross-check on the real map: every key the table looks up is in the widened bank, so the two
    # modules agree about which pairs exist. No sprite bank is built -- _lines_sprite_light alone.
    rows, _ = rows_idx
    lns = reachable_lightnums(lite.rm, lite.secs)
    _txt, wide = _lines_sprite_light(lite.rm, lite.cfg, lite.art, lite.mw, "E1M1", lite.cmap,
                                     lite.lds, lite.sds, lite.secs, moving_things=True)
    flat = sprite_light_table(wide, rows, lns)
    assert len(flat) == len(rows) * len(lns) and all(v is not None for v in flat)


def test_sprite_light_table_reports_every_missing_pair_at_once(lite, rows_idx):
    """⚠ R9 NEGATIVE CONTROL, and the module's designed hand-off to the operator: the raise happens
    AFTER the whole scan, so the message names the count of ALL distinct missing (lightnum, height)
    pairs. Move it inside the loop and the count is always 1 -- the next session then sizes the bank
    widening from one pair instead of from the real requirement ("2.8x, not 9x"). Delete it and
    `spr_cls.get(key)` puts None in the table, which `generate_packed_lut_fj` would try to pack.

    The assertion is on the COUNT, so a raise-on-first-miss still fails here."""
    cls = {(5, 3): 11}                                   # three of the four pairs are absent
    rows = [_row_with_height(3), _row_with_height(7)]
    with pytest.raises(KeyError, match=r"missing 3 \(lightnum, height\) pairs"):
        sprite_light_table(cls, rows, [5, 9])

    # and on the real map the unwidened (spawn-only) bank must be short too, with no None leaking
    rows_r, _ = rows_idx
    lns = reachable_lightnums(lite.rm, lite.secs)
    _txt, static = _lines_sprite_light(lite.rm, lite.cfg, lite.art, lite.mw, "E1M1", lite.cmap,
                                       lite.lds, lite.sds, lite.secs)
    with pytest.raises(KeyError, match="shade-row bank is missing"):
        sprite_light_table(static, rows_r, lns)


def test_the_empty_map_path_stays_empty(lite):
    """E1M8 has ZERO runtime things (MEASURED: 98 drawable, 98 baked), so the empty path is on M4's
    shipped road, not hypothetical: a `max()` or a division added for sizing would crash the
    nine-level emit on exactly one map."""
    spr = ({}, {}, {})
    assert thing_rows(lite.rm, [], lite.art, *spr, MONSTER_TYPES, MIN_SPRITE_H,
                      MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON,
                      deg=True, spr_near=True) == ([], [])
    assert drawable_things(lite.rm, [], lite.art, {}) == ([], [])
    assert baked_thing_mask(lite.rm, lite.cmap, [], MONSTER_TYPES) == ()
    assert vanishable_slots([], (), VANISHABLE_TYPES) == {}
    assert sprite_light_table({(5, 3): 1}, [], [5]) == []
    assert sprite_light_table({(5, 3): 1}, [_row_with_height(3)], []) == []
    # E1M8's own shape: an ALL-BAKED map. `keep=set()` is not `keep=None`, so the runtime table must
    # come back empty rather than carrying every thing.
    assert lite.things, "the fixture has no things at all"
    assert thing_rows(lite.rm, lite.things, lite.art, *spr, MONSTER_TYPES, MIN_SPRITE_H,
                      MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON,
                      deg=True, spr_near=True, keep=set()) == ([], [])


# ── check_row_equivalence, called for real ──────────────────────────────────────────────────────
def test_check_row_equivalence_agrees_at_spawn_and_catches_a_one_bit_change(lite, rows_idx):
    """⚠ THE PROOF THE MODULE EXISTS FOR, run through the ACTUAL FUNCTION.

    `test_runtime_sp_z_and_sp_lt_equal_the_baked_constants` re-implements this derivation inline, so
    the emitter and that test can agree while `check_row_equivalence` itself has drifted -- a lost
    sign extension, an off-by-one in the sprlt index. Nobody calls it.

    Inputs are shaped the way `_moving_thing_tables` shapes them, including `sslight` REMAPPED
    through `lnpos` (the raw lightnums would index off the end of `sprlt`). The light classes are
    SYNTHETIC and injective, which keeps this independent of the sprite bank and means a wrong
    sprlt index cannot alias onto the right answer.

    ⚠ R9: the second half perturbs one baked z by a single bit and requires the function to report
    exactly that thing. MEASURED: [(7, (65453, ...), (65452, ...))] -- and 65453 shows the
    negative-floor (two's complement) branch is the one being exercised."""
    rows, idx = rows_idx
    lns = reachable_lightnums(lite.rm, lite.secs)
    heights = sorted({max(1, r[2]) for r in rows})
    synth = {(ln, h): 1 + k * len(heights) + j
             for k, ln in enumerate(lns) for j, h in enumerate(heights)}
    assert len(set(synth.values())) == len(synth), "the synthetic class map is not injective"
    sprlt = sprite_light_table(synth, rows, lns)
    ssfloor, sslight_raw = subsector_tables(lite.rm, lite.cmap, lite.lds, lite.sds, lite.secs)
    lnpos = {ln: k for k, ln in enumerate(lns)}
    sslight = [lnpos.get(ln, 0) for ln in sslight_raw]

    cache: dict = {}
    baked = {}
    for t_i in idx:
        t = lite.things[t_i]
        a = lite.rm.sprite_art(lite.art, t.type, cache)
        sec = _thing_sector(lite.rm, lite.cmap, lite.lds, lite.sds, lite.secs, t)
        baked[t_i] = (sec.floor_h + a[6],
                      synth[(lite.rm.wall_lightnum(sec.light, 0), max(1, a[4]))])

    def run(b):
        return check_row_equivalence(lite.rm, lite.cmap, lite.lds, lite.sds, lite.secs,
                                     lite.things, idx, rows, ssfloor, sslight, sprlt, len(rows), b)

    assert run(baked) == [], "the runtime derivation disagrees with the baked constants at spawn"
    assert any(ssfloor[lite.rm.point_in_subsector(lite.cmap, lite.things[t].x, lite.things[t].y)]
               >= 0x8000 for t in idx), "no thing stands on a negative floor here"

    victim = idx[7]
    bent = dict(baked)
    bent[victim] = (bent[victim][0] ^ 1, bent[victim][1])
    got = run(bent)
    assert [g[0] for g in got] == [victim], f"a one-bit z change was not reported exactly: {got}"
    assert got[0][1] != got[0][2], "reported a disagreement whose two sides are equal"

    bent_lt = dict(baked)
    bent_lt[victim] = (baked[victim][0], baked[victim][1] + 1)
    assert [g[0] for g in run(bent_lt)] == [victim], "a wrong light class was not reported"


def test_check_row_equivalence_compares_the_16_bit_wrap(lite):
    """`sp_z` is the two int16s added MOD 2^16 -- fj adds them in a 16-bit window, so that is the
    only answer the mirrors can share. Pinned synthetically across the sign boundary (floors at
    0x7FFF / 0x8000 / 0xFFFF, and a negative z-offset).

    ⚠ HONEST NOTE: the `ssfloor[ss] < 0x8000` branch in the function is arithmetically REDUNDANT --
    subtracting 0x10000 before a `& 0xFFFF` changes nothing -- so no `<` vs `<=` mutation of it can
    be detected by any test. What IS load-bearing, and what this pins, is the MASK: drop the
    `& 0xFFFF` (or compare against an unmasked `want_z`) and a below-zero floor reports a
    disagreement for every sprite standing on it."""
    rm = _StubRM({(0, 0): 0})
    things = [SimpleNamespace(x=0, y=0)]
    for floor, zoff in ((0x7FFF, 1), (0x8000, 0), (0x8000, -1), (0xFFFF, 1), (0, -8), (0xFF58, 24)):
        rows = [(0, 0, 1, zoff, 0, 0, 0, 0, 0, 0)]
        want = (floor + zoff) & 0xFFFF

        def run(z):
            return check_row_equivalence(rm, None, None, None, None, things, [0], rows,
                                         [floor], [0], [5], 1, {0: (z, 5)})

        assert run(want) == [], f"floor {floor:#06x} + {zoff} did not derive {want:#06x}"
        # the signed spelling of the same value must agree too -- that is what the emitter hands it
        assert run(want - 0x10000) == [], "the baked value is not compared modulo 2^16"
        reported = run(0xDEAD)
        assert reported and reported[0][1] == (want, 5), \
            f"floor {floor:#06x} + {zoff} derived {reported[0][1][0]:#06x}, not {want:#06x}"


# ── drawable_things: the shared cache ───────────────────────────────────────────────────────────
def test_the_drawable_cache_is_an_optimization_only(lite, episode):
    """`build_wall_renderer` threads ONE `spr_cache` through every call in a build -- and, under M4,
    across nine maps -- while the oracle builds its own. So the cache must never change the answer:
    if `sprite_art` ever cached a miss differently from a hit, the two mirrors would compute
    different DRAWABLE LISTS, which is the RM-1/ST-1 index-space bug in its other half (the two
    mirrors now share a predicate, but not a cache)."""
    fresh = drawable_things(lite.rm, lite.things, lite.art, {})
    again = drawable_things(lite.rm, lite.things, lite.art, {})
    assert [(t.x, t.y, t.type) for t in fresh[0]] == [(t.x, t.y, t.type) for t in again[0]]
    assert fresh[1] == again[1], "two fresh-cache calls disagree -- drawable_things is not pure"

    shared: dict = {}
    first = drawable_things(lite.rm, lite.things, lite.art, shared)
    warmed = len(shared)
    second = drawable_things(lite.rm, lite.things, lite.art, shared)
    assert warmed, "the cache stayed empty -- it is not being written, so this proves nothing"
    assert len(shared) == warmed, "a second pass added entries; the cache does not reach steady state"
    assert second[1] == first[1] == fresh[1], "a warm cache changed the drawable list"
    assert second[1] == drawable_things(lite.rm, lite.things, lite.art, None)[1], \
        "cache=None and a shared cache disagree"

    # ... and a cache pre-warmed by ANOTHER MAP (the M4 shape: one spr_cache across nine levels)
    cross: dict = {}
    drawable_things(lite.rm, episode["E1M9"].things, lite.art, cross)
    assert cross, "warming from another map cached nothing"
    assert drawable_things(lite.rm, lite.things, lite.art, cross)[1] == fresh[1], \
        "a cache warmed by another map changed this map's drawable list"
