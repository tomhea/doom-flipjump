"""Unit tests for `doomfj.mapsimplify.simplify`'s pure logic, on tiny synthetic maps built
from the real wad dataclasses (Linedef/Sidedef/Sector/Thing) — the exact record types the
module consumes. Covers the union-find tolerance grouping (including the documented
group-range CAP that stops a staircase from transitively collapsing), the untouchable
special/tag rule, and the thing-thinning policy.
"""
from doomfj.mapsimplify import simplify
from doomfj.wad import Linedef, Sector, Sidedef, Thing

_1S, _2S = 1, 4          # linedef flags: impassable / two-sided


def _sd(sector, middle="-"):
    return Sidedef(0, 0, "-", "-", middle, sector)


def _sec(floor_h, *, ceil_h=128, light=160, special=0, tag=0):
    return Sector(floor_h, ceil_h, "FLOOR0_1", "CEIL1_1", light, special, tag)


def _split_room(sec_a, sec_b, *, splitter_special=0, splitter_flags=_2S):
    """Two cells: sector 0 is x in [0,256] (the HEAVIER perimeter -> group representative),
    sector 1 is x in [256,384]; one two-sided splitter at x=256 (front=1, back=0)."""
    verts = [(0, 0), (0, 128), (256, 128), (384, 128), (384, 0), (256, 0)]
    sds = [_sd(0), _sd(0), _sd(1), _sd(1), _sd(1), _sd(0), _sd(1), _sd(0)]
    lds = [
        Linedef(0, 1, _1S, 0, 0, 0, -1),                       # west         (sector 0)
        Linedef(1, 2, _1S, 0, 0, 1, -1),                       # top-left     (sector 0)
        Linedef(2, 3, _1S, 0, 0, 2, -1),                       # top-right    (sector 1)
        Linedef(3, 4, _1S, 0, 0, 3, -1),                       # east         (sector 1)
        Linedef(4, 5, _1S, 0, 0, 4, -1),                       # bottom-right (sector 1)
        Linedef(5, 0, _1S, 0, 0, 5, -1),                       # bottom-left  (sector 0)
        Linedef(5, 2, splitter_flags, splitter_special, 0, 6, 7),   # splitter x=256
    ]
    return verts, lds, sds, [sec_a, sec_b]


def _corridor(floors):
    """len(floors) cells in a row, 128 units wide each, adjacent cells joined by a two-sided
    boundary line. Cell i fronts sector i."""
    n = len(floors)
    verts = [(128 * i, 0) for i in range(n + 1)] + [(128 * i, 128) for i in range(n + 1)]
    top = lambda i: n + 1 + i
    lds, sds = [], []

    def add(v1, v2, front_sec, back_sec=None, flags=_1S):
        front = len(sds)
        sds.append(_sd(front_sec))
        back = -1
        if back_sec is not None:
            back = len(sds)
            sds.append(_sd(back_sec))
            flags = _2S
        lds.append(Linedef(v1, v2, flags, 0, 0, front, back))

    add(0, top(0), 0)                                          # west wall
    for i in range(n):
        add(top(i), top(i + 1), i)                             # top of cell i
        add(i + 1, i, i)                                       # bottom of cell i
    add(top(n), n, n - 1)                                      # east wall
    for i in range(n - 1):
        add(i + 1, top(i + 1), i + 1, i)                       # boundary: front=right cell
    return verts, lds, sds, [_sec(f) for f in floors]


# ── pass 1: tolerance grouping ──

def test_within_tolerance_sectors_merge_and_interior_line_is_deleted():
    verts, lds, sds, secs = _split_room(_sec(0), _sec(8))      # floors differ by 8 <= 24
    _, lds2, sds2, secs2, _, st = simplify(verts, lds, sds, secs, [])
    assert st.sector_groups == 1 and st.sectors_flattened == 1
    assert st.lines_deleted == 1                               # the splitter vanished
    assert len(secs2) == 1
    # the heavier-perimeter sector (0) is the representative: its look wins
    assert secs2[0].floor_h == 0
    assert all(sd.sector == 0 for sd in sds2)
    assert all(ld.back == -1 for ld in lds2)                   # no two-sided line survives


def test_chain_with_total_range_over_cap_does_not_transitively_merge():
    """The module's documented regression: floors 0/16/32/48 differ by 16 pairwise (inside
    floor_tol=24), but the GROUP range cap must stop the staircase collapsing into one
    48-unit cliff — it may merge into sub-groups whose internal range stays <= 24, never
    into fewer than two distinct floor heights."""
    verts, lds, sds, secs = _corridor([0, 16, 32, 48])
    _, _, sds2, secs2, _, st = simplify(verts, lds, sds, secs, [])
    floors = sorted({s.floor_h for s in secs2})
    assert len(floors) >= 2, "staircase transitively collapsed — the range cap regressed"
    # the current greedy order yields exactly {0,16} + {32,48}
    assert floors == [0, 32]
    assert st.sectors_flattened == 2 and st.sector_groups == 2
    assert st.lines_deleted == 2                               # the two intra-group boundaries
    # sector_map: 0/1 land together, 2/3 land together, the two groups stay apart
    m = st.sector_map
    assert m[0] == m[1] and m[2] == m[3] and m[0] != m[2]


def test_out_of_tolerance_sectors_do_not_merge():
    verts, lds, sds, secs = _split_room(_sec(0), _sec(64))     # 64 > floor_tol 24
    _, _, _, secs2, _, st = simplify(verts, lds, sds, secs, [])
    assert st.sectors_flattened == 0 and st.lines_deleted == 0
    assert sorted(s.floor_h for s in secs2) == [0, 64]


def test_light_tolerance_gates_merging_too():
    verts, lds, sds, secs = _split_room(_sec(0), _sec(0, light=255))   # 95 > light_tol 32
    _, _, _, secs2, _, st = simplify(verts, lds, sds, secs, [])
    assert st.sectors_flattened == 0
    assert len(secs2) == 2


# ── the untouchable rule ──

def test_special_sector_never_merges():
    verts, lds, sds, secs = _split_room(_sec(0), _sec(8, special=9))   # secret sector
    _, _, _, secs2, _, st = simplify(verts, lds, sds, secs, [])
    assert st.sectors_flattened == 0 and st.lines_deleted == 0
    assert len(secs2) == 2


def test_tagged_sector_never_merges():
    verts, lds, sds, secs = _split_room(_sec(0), _sec(8, tag=7))       # lift/door target
    _, _, _, secs2, _, st = simplify(verts, lds, sds, secs, [])
    assert st.sectors_flattened == 0
    assert len(secs2) == 2


def test_special_boundary_line_blocks_merge_and_protects_the_door_sector():
    # a DR-style door line (special, back sector, no tag) protects its back sector
    verts, lds, sds, secs = _split_room(_sec(0), _sec(8), splitter_special=1)
    _, _, _, secs2, _, st = simplify(verts, lds, sds, secs, [])
    assert st.sectors_flattened == 0 and st.lines_deleted == 0
    assert len(secs2) == 2


def test_impassable_boundary_line_blocks_merge():
    verts, lds, sds, secs = _split_room(_sec(0), _sec(8), splitter_flags=_2S | 1)
    _, _, _, secs2, _, st = simplify(verts, lds, sds, secs, [])
    assert st.sectors_flattened == 0
    assert len(secs2) == 2


# ── pass 5: thing thinning ──

def _things_fixture():
    return [
        Thing(10, 10, 0, 3004, 7),     # imp            -> KEEP (monster)
        Thing(20, 20, 0, 1, 0),        # player 1 start -> KEEP
        Thing(30, 30, 0, 2001, 0),     # shotgun        -> KEEP (weapon)
        Thing(40, 40, 0, 5, 0),        # blue keycard   -> KEEP (key)
        Thing(50, 50, 0, 31, 0),       # small decor    -> DROP
        Thing(60, 60, 0, 10, 0),       # gore/corpse    -> DROP
        Thing(0, 200, 0, 2014, 0),     # health bonus   -> KEEP (first of its cluster)
        Thing(32, 200, 0, 2014, 0),    # health bonus 32u away -> DROP (inside 96u spacing)
        Thing(300, 200, 0, 2014, 0),   # isolated bonus -> KEEP (outside the radius)
        Thing(70, 70, 0, 9999, 0),     # unknown type   -> KEEP (safe default)
    ]


def test_thing_thinning_policy():
    verts, lds, sds, secs = _split_room(_sec(0), _sec(64))     # geometry irrelevant here
    things = _things_fixture()
    _, _, _, _, things2, st = simplify(verts, lds, sds, secs, things)
    kept = [(t.type, t.x, t.y) for t in things2]
    # every monster/start/weapon/key survives
    for tt in (3004, 1, 2001, 5):
        assert any(k[0] == tt for k in kept), f"type {tt} must always be kept"
    # small decor and gore are gone
    assert all(k[0] not in (31, 10) for k in kept)
    # the bonus string thinned spatially: the 32u neighbour dropped, the isolated one kept
    bonuses = sorted((x, y) for tt, x, y in kept if tt == 2014)
    assert bonuses == [(0, 200), (300, 200)]
    # unknown types default to kept
    assert any(k[0] == 9999 for k in kept)
    assert st.things_dropped == 3


def test_thin_things_false_keeps_everything():
    verts, lds, sds, secs = _split_room(_sec(0), _sec(64))
    things = _things_fixture()
    _, _, _, _, things2, st = simplify(verts, lds, sds, secs, things, thin_things=False)
    assert things2 == things
    assert st.things_dropped == 0
