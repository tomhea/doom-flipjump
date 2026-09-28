"""M7 P1.2 -- the player's collision CELLS (docs/gp-collision-cells.md), host side.

The emitted program no longer walks the blockmap: a jump tree on the 16.16 centre reaches its 32-unit
cell, the cell's stub calls one stub per listed line, and each line stub xors its constants into
argument cells around ONE shared `sim.line_test`. Three claims make that exact, and each carries its
own negative control (R9):

1. COVERAGE -- a line missing from a cell's list is bbox-rejected at all four corners of the cell,
   which for a box at least a cell wide means everywhere in it (`cell_lists`' docstring). Control:
   drop one needed line from one list and the check must name exactly that pair.
2. MODEL = ORACLE -- `check_position_cells` gives `ReferenceModel.check_position`'s answer on a
   sample holding refusals, openings, 16.16 cell edges, fractional centres, positions off the map
   and every door both shut and open. Control: the sample must contain refusals and door lines whose
   verdict moves with the door.
3. THE EMITTED TEXT IS THE MODEL -- the tree, walked here by an interpreter of its own text, routes
   every cell's centre to the stub of that cell's list; every line stub xors each constant in and
   out (so the argument cells are zero between lines); a door line's stub reads its own door's
   `dstate` against the pass state. Controls: a tree with one target swapped, and a stub with one
   xor dropped, are both rejected.

`tests/fj/test_collision_fj.py` runs the emitted routine itself; this file is the part that needs
no assembler.
"""
import random
import re
from pathlib import Path

import pytest

from doomfj.collision import (CELL_DECLS, CELL_SHIFT, COLLISION_STATE_DECLS, FLAG_BLOCKING,
                              ST_HORIZONTAL, ST_NEGATIVE, ST_POSITIVE, ST_VERTICAL, cell_lists,
                              cell_of, check_position_cells, collision_cells_fj, line_constants,
                              line_rows)
from doomfj.config import Config
from doomfj.doorcode import door_line_ids
from doomfj.doors import door_states, pass_state
from doomfj.mapcompiler import bake_bsp, seg_sector
from doomfj.reference_model import (ML_BLOCKING, PLAYER_RADIUS, ReferenceModel,
                                    apply_sector_heights, build_scene, scene_sectors)
from doomfj.wad import WadFile

REPO = Path(__file__).resolve().parents[2]
E1M1 = REPO / "tests" / "fixtures" / "freedoom_e1m1.wad"
M32 = 0xFFFFFFFF
S = 1 << CELL_SHIFT                              # a cell, in 16.16


class Level:
    """E1M1 with its doors, as the game tier builds it: door lines take the OPEN opening."""

    def __init__(self):
        self.wad = WadFile.from_path(str(E1M1))
        self.lds = self.wad.linedefs("E1M1")
        self.sds = self.wad.sidedefs("E1M1")
        self.secs = self.wad.sectors("E1M1")
        self.cmap = bake_bsp(self.wad, "E1M1")
        self.rm = ReferenceModel(Config())
        tbl = door_states(self.secs, self.lds, self.sds)
        self.order = sorted(tbl)
        self.lines_of = door_line_ids(self.secs, self.lds, self.sds, tbl)
        self.door_lines = frozenset(li for v in self.lines_of.values() for li in v)
        self.open_h = {si: (self.secs[si].floor_h, tbl[si][-1]) for si in self.order}
        self.nstates = {si: len(tbl[si]) for si in self.order}
        self.passes = {si: pass_state(self.secs, self.lds, self.sds, si) for si in self.order}
        self.rows = line_rows(self.lds, self.cmap.vertexes, self.secs, self.sds, ML_BLOCKING,
                              secs_open=apply_sector_heights(self.secs, self.open_h),
                              door_line_ids=self.door_lines)
        self.lists = cell_lists(self.rows, PLAYER_RADIUS)
        self.doors = {}
        for d, si in enumerate(self.order):
            for li in self.lines_of.get(si, ()):
                self.doors.setdefault(li, []).append((d, self.passes[si]))
        self._scenes = {}

    def scene(self, shut):
        if shut not in self._scenes:
            self._scenes[shut] = build_scene(self.wad, self.wad, "E1M1", self.open_h, shut)
        return self._scenes[shut]

    def both(self, x16, y16, shut=frozenset()):
        """(the cell model's answer, the oracle's) for one centre and one set of shut door lines"""
        scene = self.scene(shut)
        ss = self.cmap.subsectors[self.rm.point_in_subsector(self.cmap, x16 >> 16, y16 >> 16)]
        sec = seg_sector(self.lds, self.sds, scene_sectors(scene), self.cmap.segs[ss.firstseg])
        got = check_position_cells(self.rows, self.lists, x16, y16, PLAYER_RADIUS,
                                   sec.floor_h, sec.ceil_h, shut)
        return got, self.rm.check_position(scene, x16, y16)

    def extent(self):
        xs = [v[0] for v in self.cmap.vertexes]
        ys = [v[1] for v in self.cmap.vertexes]
        return min(xs), max(xs), min(ys), max(ys)


@pytest.fixture(scope="module")
def lvl():
    return Level()


# ── 1. coverage ────────────────────────────────────────────────────────────────────────────────

def _rejected(row, x16, y16):
    """check_position's bbox reject, written from the oracle's expression rather than the lists'"""
    minx, maxx, miny, maxy = (v << 16 for v in row[4:8])
    r = PLAYER_RADIUS
    return x16 + r <= minx or x16 - r >= maxx or y16 + r <= miny or y16 - r >= maxy


def _uncovered(rows, lists):
    """Every (cell, line) where the line is NOT listed yet some corner of the cell escapes its bbox
    reject. Scans every line's neighbourhood two cells beyond anything the lists could claim."""
    out = []
    for li, row in enumerate(rows):
        minx, maxx, miny, maxy = (v << 16 for v in row[4:8])
        for cx in range((minx - PLAYER_RADIUS) // S - 2, (maxx + PLAYER_RADIUS) // S + 3):
            for cy in range((miny - PLAYER_RADIUS) // S - 2, (maxy + PLAYER_RADIUS) // S + 3):
                if li in lists.get((cx, cy), ()):
                    continue
                corners = [(x, y) for x in (cx * S, cx * S + S - 1) for y in (cy * S, cy * S + S - 1)]
                if not all(_rejected(row, x, y) for x, y in corners):
                    out.append(((cx, cy), li))
    return out


def test_every_line_a_box_in_the_cell_can_touch_is_listed(lvl):
    assert not _uncovered(lvl.rows, lvl.lists), _uncovered(lvl.rows, lvl.lists)[:5]
    # ... and nothing is listed that no box in the cell can touch (the lists are exact, not padded)
    for (cx, cy), lis in lvl.lists.items():
        assert list(lis) == sorted(set(lis)), f"cell {(cx, cy)}: not ascending and unique"
        for li in lis:
            xs = (cx * S, cx * S + S - 1)
            ys = (cy * S, cy * S + S - 1)
            assert not all(_rejected(lvl.rows[li], x, y) for x in xs for y in ys), \
                f"cell {(cx, cy)} lists line {li}, which every box in it rejects"
    assert len(lvl.lists) > 1000 and max(len(v) for v in lvl.lists.values()) > 5


def test_the_coverage_check_names_a_dropped_line(lvl):
    """R9: the check above must SAY NO. Drop one needed line from one list; exactly that pair."""
    cell = next(c for c, lis in sorted(lvl.lists.items()) if len(lis) >= 3)
    li = lvl.lists[cell][1]
    mutated = dict(lvl.lists)
    mutated[cell] = tuple(x for x in lvl.lists[cell] if x != li)
    assert _uncovered(lvl.rows, mutated) == [(cell, li)]


def test_a_corner_escape_is_the_whole_story_only_for_a_box_a_cell_wide():
    """The corner argument is `cell_lists`' own precondition; a narrower box must be refused."""
    rows = [(0, 0, 10, 0, 0, 10, 0, 0, ST_HORIZONTAL, 1, 0, 0)]
    with pytest.raises(AssertionError):
        cell_lists(rows, (S // 2) - 1)
    assert cell_lists(rows, S // 2)


def test_cell_of_is_the_trees_signed_arithmetic_shift():
    for c16 in (0, 1, S - 1, S, -1, -S, -S - 1, 0x7FFFFFFF, -0x80000000, 1234 << 16, -1234 << 16):
        assert cell_of(c16) == c16 >> CELL_SHIFT
        assert cell_of(c16 & M32) == c16 >> CELL_SHIFT, "the unsigned word reads the same"


# ── 2. the model against the oracle ────────────────────────────────────────────────────────────

def test_the_cell_model_is_the_oracle(lvl):
    """Random centres (integer and fractional), every cell's four 16.16 corners for a sample of
    lined cells, and centres beyond the map's extent; doors all shut and all open."""
    rng = random.Random(1)
    x0, x1, y0, y1 = lvl.extent()
    pts = [((rng.randint(x0 - 64, x1 + 64) << 16) + rng.choice((0, 0x8000, 0x0001, 0xFFFF)),
            (rng.randint(y0 - 64, y1 + 64) << 16) + rng.choice((0, 0x8000, 0x7FFF)))
           for _ in range(800)]
    for cx, cy in rng.sample(sorted(lvl.lists), 150):
        pts += [(x, y) for x in (cx * S, cx * S + S - 1) for y in (cy * S, cy * S + S - 1)]
    pts += [(x << 16, y << 16) for x in (x0 - 3000, x1 + 3000) for y in (y0 - 3000, y1 + 3000)]
    refused = 0
    for shut in (lvl.door_lines, frozenset()):
        for x16, y16 in pts:
            got, want = lvl.both(x16, y16, shut)
            assert got == want, f"({x16 / 65536:.4f}, {y16 / 65536:.4f}) shut={bool(shut)}"
            refused += not want[0]
    assert refused > 300, f"only {refused} refusals -- the sample proves little about walls"


def test_a_door_line_follows_its_doors_state(lvl):
    """A centre ON each door line: shut refuses, open narrows -- in both mirrors, for every door
    state, with every OTHER door in a random state. Control: most door lines must move."""
    rng = random.Random(2)
    moved = 0
    for d, si in enumerate(lvl.order):
        for li in lvl.lines_of[si]:
            (x1, y1), (x2, y2) = lvl.cmap.vertexes[lvl.lds[li].v1], lvl.cmap.vertexes[lvl.lds[li].v2]
            x16, y16 = ((x1 + x2) // 2) << 16, ((y1 + y2) // 2) << 16
            seen = set()
            for k in range(lvl.nstates[si]):
                others = {o: rng.randrange(lvl.nstates[o]) for o in lvl.order if o != si}
                others[si] = k
                shut = frozenset(x for o, st in others.items() if st < lvl.passes[o]
                                 for x in lvl.lines_of.get(o, ()))
                got, want = lvl.both(x16, y16, shut)
                assert got == want, f"door {d} line {li} state {k}: cells {got} oracle {want}"
                seen.add(want[0])
            moved += seen == {False, True}
    assert moved >= len(lvl.door_lines) - 2, f"only {moved} door lines change with their door"


# ── 3. the emitted text ────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def emitted(lvl):
    return collision_cells_fj("e1m1", lvl.rows, lvl.lists, doors=lvl.doors)


def _parse(text):
    """(nodes {label: (register, nibble, [16 targets])}, stubs {label: [line labels]},
    lines {label: [op, ...]})"""
    nodes, stubs, lines, cur, body = {}, {}, {}, None, None
    for raw in text.splitlines():
        s = raw.split("//")[0].strip()
        if not s:
            continue
        m = re.fullmatch(r"([A-Za-z_]\w*):", s)
        if m:
            cur = m.group(1)
            if re.fullmatch(r"e1m1_cc_s\d+", cur):
                body = stubs.setdefault(cur, [])
            elif re.fullmatch(r"e1m1_cc_l\d+", cur):
                body = lines.setdefault(cur, [])
            elif not re.fullmatch(r"e1m1_cc_l\d+_(shut|go|out|d\d+)", cur):
                body = None
            continue
        mj = re.fullmatch(r"sim\.jump16 (cp[xy]) \+ (\d)\*dw, (.*)", s)
        if mj:
            nodes[cur] = (mj.group(1), int(mj.group(2)), [t.strip() for t in mj.group(3).split(",")])
            continue
        if body is not None:
            if cur in stubs:
                mc = re.fullmatch(r"stl\.fcall (e1m1_cc_l\d+), cc_lret", s)
                if mc:
                    body.append(mc.group(1))
            else:
                body.append(s)
    return nodes, stubs, lines


def _walk(nodes, root, x16, y16):
    """Follow the tree's own text for one centre: returns the leaf label it lands on."""
    lab = root
    while lab in nodes:
        reg, nib, targets = nodes[lab]
        v = (x16 if reg == "cpx" else y16) & M32
        lab = targets[(v >> 4 * nib) & 0xF]
    return lab


def test_the_tree_routes_every_cell_to_its_lists_stub(lvl, emitted):
    text, root = emitted
    nodes, stubs, _lines = _parse(text)
    # both 16-unit halves of every cell, each at its first and last 16.16 value
    probes = [((cx, cy), x16, y16) for (cx, cy) in sorted(lvl.lists)
              for x16 in (cx * S, cx * S + (S >> 1) - 1, cx * S + (S >> 1), cx * S + S - 1)
              for y16 in (cy * S, cy * S + (S >> 1) - 1, cy * S + (S >> 1), cy * S + S - 1)]
    for cell, x16, y16 in probes:
        leaf = _walk(nodes, root, x16, y16)
        got = tuple(int(lab.rsplit("_l", 1)[1]) for lab in stubs[leaf])
        assert got == lvl.lists[cell], f"cell {cell} reaches {leaf} listing {got}"
    # a cell no line can touch lands on the empty stub
    x0, x1, y0, y1 = lvl.extent()
    for x, y in ((x0 - 2000, y0 - 2000), (x1 + 2000, y1 + 2000), (-32000, 31000)):
        assert _walk(nodes, root, x << 16, y << 16) == "e1m1_cc_none"
    assert len(probes) > 90000
    # R9: swap two DIFFERENT targets of one node and the same probes must see it
    lab, (reg, nib, targets) = next((k, v) for k, v in nodes.items()
                                    if len({t for t in v[2] if t != "e1m1_cc_none"}) >= 2)
    i = next(k for k, t in enumerate(targets) if t != "e1m1_cc_none")
    j = next(k for k, t in enumerate(targets) if t not in ("e1m1_cc_none", targets[i]))
    bad = dict(nodes)
    t2 = list(targets)
    t2[i], t2[j] = t2[j], t2[i]
    bad[lab] = (reg, nib, t2)
    assert any(_walk(bad, root, x16, y16) != _walk(nodes, root, x16, y16)
               for _c, x16, y16 in probes), "the routing check cannot see a swapped target"


def test_every_line_stub_xors_its_constants_in_and_out(lvl, emitted):
    """Each argument cell must be zero again when the stub returns: the same xor lines before the
    call and after it. Control: a stub with one xor dropped is caught."""
    text, _root = emitted
    _nodes, _stubs, lines = _parse(text)
    assert len(lines) == len({li for lis in lvl.lists.values() for li in lis})

    door_bit = "hex.xor_by ca_flags, %d" % FLAG_BLOCKING    # a shut door's own pair, checked below

    def balanced(ops):
        calls = [k for k, o in enumerate(ops) if o.startswith("stl.fcall e1m1_cc_test")]
        assert calls, ops[:3]
        before = [o for o in ops[:calls[0]] if o.startswith("hex.xor_by ca_") and o != door_bit]
        after = [o for o in ops[calls[-1] + 1:] if o.startswith("hex.xor_by ca_") and o != door_bit]
        return before == after and before

    for lab, ops in lines.items():
        assert balanced(ops), f"{lab}: the xors in and out differ"
    lab, ops = next(iter(lines.items()))
    k = max(i for i, o in enumerate(ops) if o.startswith("hex.xor_by ca_"))
    assert not balanced(ops[:k] + ops[k + 1:]), "the balance check cannot see a dropped xor"


def test_a_stub_xors_exactly_its_rows_constants(lvl, emitted):
    """The xors spell `line_constants(row)` nibble by nibble -- the ONE place the row becomes fj."""
    text, _root = emitted
    _nodes, _stubs, lines = _parse(text)
    for lab, ops in lines.items():
        li = int(lab.rsplit("_l", 1)[1])
        want = {}
        for cell, v in line_constants(lvl.rows[li]):
            want[cell] = v
        got = {}
        call = next(k for k, o in enumerate(ops) if o.startswith(("stl.fcall", "hex.if_flags")))
        for o in ops[:call]:
            m = re.fullmatch(r"hex\.xor_by (ca_\w+)(?: \+ (\d)\*dw)?, (\d+)", o)
            assert m, o
            got[m.group(1)] = got.get(m.group(1), 0) | int(m.group(3)) << 4 * int(m.group(2) or 0)
        assert got == want, f"{lab}: xors {got}, the row says {want}"


def test_line_constants_follow_the_slope_and_the_flags():
    """Sentinel rows: which cells each kind of line needs, and nothing else (an unread cell stays
    zero, so the shared test never sees another line's leftovers)."""
    def row(slope, flags):
        return (3, 5, 7, 11, 13, 17, 19, 23, slope, flags, 29, 31)

    def cells(r):
        return {c for c, _v in line_constants(r)}
    box = {"ca_minx", "ca_maxx", "ca_miny", "ca_maxy"}
    assert cells(row(ST_HORIZONTAL, 1)) == box | {"ca_v1y", "ca_flags"}          # slope 0: no xor
    assert cells(row(ST_VERTICAL, 2)) == box | {"ca_v1x", "ca_slope", "ca_flags"}
    assert cells(row(ST_POSITIVE, 0)) == box | {"ca_v1x", "ca_v1y", "ca_dx", "ca_dy", "ca_slope",
                                                "ca_ob", "ca_ot"}
    assert cells(row(ST_NEGATIVE, 0)) == cells(row(ST_POSITIVE, 0))
    vals = dict(line_constants(row(ST_POSITIVE, 0)))
    assert (vals["ca_minx"], vals["ca_maxy"], vals["ca_v1x"]) == (13 << 16, 23 << 16, 3 << 16)
    assert (vals["ca_dx"], vals["ca_dy"], vals["ca_ob"], vals["ca_ot"]) == (7, 11, 31, 29)
    neg = dict(line_constants((-3, 0, -7, 11, -13, 17, 0, 23, ST_NEGATIVE, 0, -29, -31)))
    assert neg["ca_v1x"] == (-3 << 16) & M32 and neg["ca_dx"] == -7 & M32   # sign-extended
    assert neg["ca_ot"] == -29 & M32 and "ca_miny" not in neg                  # a zero: no xor


def test_a_door_lines_stub_reads_its_own_doors_state(lvl, emitted):
    """`hex.if_flags dstate + slot*dw, <states below the pass state>, go, shut`, and the shut path
    alone xors FLAG_BLOCKING in and out. A wrong slot opens one door by pressing another."""
    text, _root = emitted
    _nodes, _stubs, lines = _parse(text)
    for li, ((slot, pw),) in lvl.doors.items():                  # E1M1: every line on ONE door
        ops = lines[f"e1m1_cc_l{li}"]
        tests = [o for o in ops if o.startswith("hex.if_flags")]
        assert tests == [f"hex.if_flags dstate + {slot}*dw, {(1 << pw) - 1:#06x}, "
                         f"e1m1_cc_l{li}_go, e1m1_cc_l{li}_shut"], (li, tests)
        # the shut path, and only it, brackets its call with the FLAG_BLOCKING xor
        shut = ops[ops.index("hex.xor_by ca_flags, %d" % FLAG_BLOCKING):]
        assert shut[:3] == [f"hex.xor_by ca_flags, {FLAG_BLOCKING}", "stl.fcall e1m1_cc_test, cc_tret",
                            f"hex.xor_by ca_flags, {FLAG_BLOCKING}"], (li, shut[:4])
        assert ops.count(f"hex.xor_by ca_flags, {FLAG_BLOCKING}") == 2
    other = [lab for lab, ops in lines.items() if int(lab.rsplit("_l", 1)[1]) not in lvl.doors
             and any("dstate" in o for o in ops)]
    assert not other, f"stubs that are not door lines read dstate: {other[:3]}"
    # 15 doors (M7 P2a.1: the walk-over doors' lines are gated too): 29 lines
    assert len(lvl.doors) == 29 and len({s for ((s, _p),) in lvl.doors.values()}) == 15


def test_a_line_on_two_doors_refuses_while_either_is_shut(lvl):
    """No E1M1 line sits between two door sectors, but `door_line_ids` lists such a line under both,
    and the oracle's `blocked_lines` is the UNION of the shut doors' lines. So the stub chains one
    test per door, each shut state jumping to the same shut path: shut if ANY door is shut."""
    li = min(lvl.doors)
    (slot, pw), = lvl.doors[li]
    other = (slot + 1) % 13
    text, _root = collision_cells_fj("e1m1", lvl.rows, lvl.lists,
                                     doors={li: [(slot, pw), (other, pw + 1)]})
    ops = _parse(text)[2][f"e1m1_cc_l{li}"]
    tests = [o for o in ops if o.startswith("hex.if_flags")]
    assert tests == [f"hex.if_flags dstate + {slot}*dw, {(1 << pw) - 1:#06x}, "
                     f"e1m1_cc_l{li}_d1, e1m1_cc_l{li}_shut",
                     f"hex.if_flags dstate + {other}*dw, {(1 << (pw + 1)) - 1:#06x}, "
                     f"e1m1_cc_l{li}_go, e1m1_cc_l{li}_shut"], tests
    assert f"e1m1_cc_l{li}_d1:" in text


def test_the_cell_declarations_are_in_the_state(lvl):
    names = [d.split(":")[0] for d in COLLISION_STATE_DECLS]
    assert names[-len(CELL_DECLS):] == [d.split(":")[0] for d in CELL_DECLS], \
        "CELL_DECLS must come LAST: the restore sets fingerprint the spans of the names before them"
    assert len(set(names)) == len(names)
