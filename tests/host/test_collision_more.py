"""M14-d/M14-e/M7 P1.2 — the parts of `doomfj/collision.py` that only a long assemble checks today.

`tests/host/test_collision_cells.py` proves the cell lists and their Python model exact against the
ORACLE; `tests/fj/test_collision_fj.py` proves the emitted fj computes the right answer, but it
builds a program. Between them sits the Python that WRITES the fj, and much of it is checked by
nothing short of a build. This file closes that gap. Every test here is host-only and touches no
emitter output beyond the text it is handed.

What it pins, and what breaks in the shipped program if it stops holding:

* **`generate_point_location_fj`'s compile-time specialisation.** A node's descent is emitted as one
  `hex.scmp` instead of the cross product, and the three targets have to be what
  `mapcompiler._point_side` says at the three probes. A flipped `n.dy > 0`, a swapped `lo, hi`, or a
  swapped `n.left`/`n.right` sends the descent into the wrong subsector: things bind to the wrong
  leaf and the collision seed's sector is wrong. Today that surfaces as a wrong picture after a
  full build. The diagonal branch's four baked constants are pinned in the same way.
* **Its label closure.** An `NF_SUBSECTOR` masking slip emits a jump to a label nothing defines —
  an assembler failure ~40 minutes into a heavy build; here it is milliseconds.
* **`move_with_collision_lines`' shape.** `cprad` once, with the RADIUS, before the first
  `sim.check_cells` (the failure its own warning comment documents: an unwritten `cprad` is zero,
  the box collapses to a point and the player walks through walls); the three candidates in the
  oracle's order (a reorder changes which wall the player slides along, and only the cumulative
  `m5_gate` would see it); all four checks entering the SAME cell routine; and every label defined
  once with every jump resolving.
* **The line constants' widths.** A cell's line stub xors each constant into an 8-nibble argument
  cell, and a map coordinate is 16.16 there: a coordinate outside int16 does not survive `<< 16`, so
  the wall's bbox would land elsewhere and the player walk through it. This is the guard M4's
  levels need -- E1M1 has enormous headroom, an E2/E3 map need not.
* **The runtime door in both mirrors at once**: a door line's stub decides shut-or-open from the
  door's state while the oracle consults `scene.blocked_lines`, and this compares the two answers on
  a second map.
* **Two oracle contracts that are deliberate and undocumented by any test**: collision is UNSWEPT
  (a verdict depends on the destination box and on the origin only through its floor), and the
  refused band across a wall is exactly the 2*PLAYER_RADIUS - 1 units the box implies.
* **The fan-out rule 5 edges into fj**: every cell `sim.check_cells`/`line_test`/`try_move`
  captures must be declared by `COLLISION_STATE_DECLS`, and `CELL_SHIFT` must be the cell the
  emitted tree's nibble split describes.
"""
import collections
import re
from pathlib import Path

import pytest

from doomfj import doorcode
from doomfj.collision import (CELL_DECLS, CELL_SHIFT, CHECK_SCRATCH_DECLS, COLLISION_STATE_DECLS,
                              cell_lists, cell_of, check_position_cells, collision_cells_fj,
                              generate_point_location_fj, line_rows, move_with_collision_lines)
from doomfj.config import Config
from doomfj.doors import door_states, heights_for_states
from doomfj.fixedpoint import _signed
from doomfj.mapcompiler import NF_SUBSECTOR, _point_side, bake_bsp, seg_sector
from doomfj.reference_model import (ML_BLOCKING, PLAYER_RADIUS, ReferenceModel,
                                    apply_sector_heights, build_scene)
from doomfj.wad import WadFile

REPO = Path(__file__).resolve().parents[2]
LITE = REPO / "tests/fixtures/e1m1_lite.wad"
FREEDOOM = REPO / "tests/fixtures/freedoom_e1m1.wad"
SIM_FJ = REPO / "src/fj/sim.fj"

R_UNITS = PLAYER_RADIUS >> 16                     # the collision box's half-width, in map units


class Level:
    """Everything both mirrors need for one map, built once."""

    def __init__(self, path):
        self.wad = WadFile.from_path(str(path))
        self.mapname = "E1M1"
        self.lds = self.wad.linedefs(self.mapname)
        self.secs = self.wad.sectors(self.mapname)
        self.sds = self.wad.sidedefs(self.mapname)
        self.cmap = bake_bsp(self.wad, self.mapname)
        self.scene = build_scene(self.wad, self.wad, self.mapname)
        self.rm = ReferenceModel(Config())

    def rows(self, **kw):
        return line_rows(self.lds, self.cmap.vertexes, self.secs, self.sds, ML_BLOCKING, **kw)

    def seed(self, x: int, y: int, secs=None):
        """`check_position`'s subsector seed, the way the oracle computes it -- the caller's job on
        both sides, so the cell model has to be handed it."""
        ss = self.cmap.subsectors[self.rm.point_in_subsector(self.cmap, x, y)]
        sec = seg_sector(self.lds, self.sds, secs or self.secs, self.cmap.segs[ss.firstseg])
        return sec.floor_h, sec.ceil_h

    def extent(self):
        xs = [v[0] for v in self.cmap.vertexes]
        ys = [v[1] for v in self.cmap.vertexes]
        return min(xs), max(xs), min(ys), max(ys)


@pytest.fixture(scope="module")
def lite():
    return Level(LITE)


@pytest.fixture(scope="module")
def ptloc(lite):
    return generate_point_location_fj(lite.cmap)

# ── generate_point_location_fj: the specialisation, against the generic formula ────────────────

def _defined_labels(text: str) -> collections.Counter:
    """Every `name:` the text defines, counted -- fj top-level labels are global, so twice is a
    redefinition and not a scope."""
    return collections.Counter(m.group(1) for m in
                               re.finditer(r"^\s*([A-Za-z_]\w*):\s*(?://.*)?$", text, re.M))


def _ptloc_node_ops(text: str, label="ptloc") -> dict:
    """`{node index: [op, ...]}` -- one node's whole descent test.

    A node's block runs from `{label}_n{i}:` to the next node or leaf label; the diagonal branch's
    own `{label}_g{i}:` continuation sits INSIDE it and does not end it."""
    out, cur = {}, None
    for raw in text.splitlines():
        s = raw.split("//")[0].strip()
        if not s:
            continue
        m = re.fullmatch(r"([A-Za-z_]\w*):", s)
        if m:
            if re.fullmatch(rf"{label}_g\d+", m.group(1)):
                continue                                  # the diagonal's own continuation
            n = re.fullmatch(rf"{label}_n(\d+)", m.group(1))
            cur = int(n.group(1)) if n else None
            if cur is not None:
                out[cur] = []
            continue
        if cur is not None:
            out[cur].append(s)
    return out


def _target(child: int, label="ptloc") -> str:
    """The emitter's own `target()`, restated here so a masking slip is a disagreement and not a
    shared mistake."""
    return (f"{label}_l{child & (NF_SUBSECTOR - 1)}" if child & NF_SUBSECTOR
            else f"{label}_n{child}")


def _want_child(node, px: int, py: int) -> str:
    """Which child `mapcompiler._point_side` sends (px, py) to: side > 0 is the BACK (left) child,
    which is the convention `generate_point_location_fj`'s docstring claims to mirror."""
    side = _point_side(node.x, node.y, node.dx, node.dy, px, py)
    return _target(node.left if side > 0 else node.right)


def test_the_axis_shortcuts_pick_the_same_child_as_the_generic_side_formula(lite, ptloc):
    """A `dx == 0` node emits ONE `hex.scmp 10, ptx, k, lt, eq, gt` in place of the cross product,
    and a `dy == 0` node the same in y. The shortcut is only sound if its three targets are what
    `_point_side` answers at (px-1, px, px+1). A flipped `n.dy > 0`, a swapped `lo, hi` or a swapped
    `n.left`/`n.right` is invisible to every other host test and costs a full build to see: the
    descent lands in the wrong subsector, so a thing binds to the wrong leaf and `check_position`'s
    seed sector is wrong.

    R9: this has bite. Swapping `lo, hi` in the dx == 0 branch of a patched copy of the emitter
    turns all 150 vertical nodes into failures."""
    ops = _ptloc_node_ops(ptloc)
    seen = {"x": 0, "y": 0}
    for i, n in enumerate(lite.cmap.nodes):
        if n.dx != 0 and n.dy != 0:
            continue
        axis, reg = ("x", "ptx") if n.dx == 0 else ("y", "pty")
        body = ops[i]
        assert len(body) == 2, f"node {i} ({axis}-axis) is not the two-op shortcut: {body}"
        k = re.fullmatch(r"hex\.set 10, ptlock, (-?\d+)", body[0])
        assert k, body[0]
        cmp_ = re.fullmatch(rf"hex\.scmp 10, {reg}, ptlock, (\S+), (\S+), (\S+)", body[1])
        assert cmp_, body[1]
        # the constant is the partition's own coordinate on that axis, masked to 10 nibbles
        want_k = (n.x if axis == "x" else n.y) & ((1 << 40) - 1)
        assert int(k.group(1)) == want_k, f"node {i}: compares against the wrong coordinate"
        probes = (((n.x - 1, n.y), (n.x, n.y), (n.x + 1, n.y)) if axis == "x"
                  else ((n.x, n.y - 1), (n.x, n.y), (n.x, n.y + 1)))
        got = cmp_.groups()                       # scmp n, a, b, lt, eq, gt
        for which, (px, py), tgt in zip(("lt", "eq", "gt"), probes, got):
            assert tgt == _want_child(n, px, py), (
                f"node {i} ({axis}-axis, dx={n.dx} dy={n.dy}): the {which} branch jumps to {tgt}, "
                f"but _point_side at ({px},{py}) says {_want_child(n, px, py)}")
        seen[axis] += 1
    assert seen["x"] > 50 and seen["y"] > 50, \
        f"only {seen} nodes took the shortcut -- this fixture proves nothing"


def test_a_diagonal_node_bakes_x_y_dx_dy_in_that_order(lite, ptloc):
    """The general branch's four `hex.set 10, ptlock, k` constants ARE the node, sign-extended out
    of the 40-bit mask -- x, y, dx, dy, in the order the cross product consumes them. A transposed
    pair (dx/dy is the easy one, since both are small deltas) silently rotates the partition."""
    ops = _ptloc_node_ops(ptloc)
    checked = 0
    for i, n in enumerate(lite.cmap.nodes):
        if n.dx == 0 or n.dy == 0:
            continue
        ks = [int(m.group(1)) for m in
              (re.fullmatch(r"hex\.set 10, ptlock, (-?\d+)", op) for op in ops[i]) if m]
        assert len(ks) == 4, f"node {i}: {len(ks)} baked constants, expected 4"
        assert [_signed(k, 40) for k in ks] == [n.x, n.y, n.dx, n.dy], \
            f"node {i}: baked {[_signed(k, 40) for k in ks]} != (x, y, dx, dy) {(n.x, n.y, n.dx, n.dy)}"
        # and the two children are the two labels the branch can reach, front-on-zero
        assert ops[i][-1] == f";{_target(n.left)}", f"node {i}: the fallthrough is not the back child"
        assert f"hex.if0 10, ptlocp, {_target(n.right)}" in ops[i], \
            f"node {i}: a point ON the partition must go to the FRONT child"
        checked += 1
    assert checked > 50, f"only {checked} diagonal nodes -- this fixture proves nothing"


def test_every_point_location_jump_lands_on_a_label_the_same_text_defines(lite, ptloc):
    """The `NF_SUBSECTOR` masking in the emitter's local `target()` has to agree with the leaves it
    actually emits. A masking slip, or a leaf loop that stops one short, emits a jump to a label
    nothing defines -- which today is an assembler failure ~40 minutes into a heavy build."""
    defined = _defined_labels(ptloc)
    assert not [k for k, v in defined.items() if v > 1], \
        f"redefined labels: {[k for k, v in defined.items() if v > 1]}"
    # every child ref of every node, plus the root, resolves
    refs = [_target(lite.cmap.root)]
    for n in lite.cmap.nodes:
        refs += [_target(n.left), _target(n.right)]
    missing = sorted({r for r in refs if r not in defined})
    assert not missing, f"child refs with no leaf/node: {missing[:8]}"
    # ... and exactly one leaf per subsector, no more and no fewer
    leaves = {k for k in defined if re.fullmatch(r"ptloc_l\d+", k)}
    assert leaves == {f"ptloc_l{s}" for s in range(len(lite.cmap.subsectors))}
    # the `_g{i}` continuations and the `;` fallthroughs must resolve too
    for m in re.finditer(r";([A-Za-z_]\w*)\s*$", ptloc, re.M):
        assert m.group(1) in defined, f"fallthrough to undefined {m.group(1)}"
    lbl = r"([A-Za-z_]\w*)"
    branches = 0
    for pat in (rf"hex\.(?:scmp|cmp) 10, \w+, \w+, {lbl}, {lbl}, {lbl}",
                rf"hex\.sign 10, \w+, {lbl}, {lbl}",
                rf"hex\.if0 10, \w+, {lbl}"):
        for m in re.finditer(pat, ptloc):
            for t in m.groups():
                assert t in defined, f"branch target {t} is undefined"
            branches += 1
    assert branches >= len(lite.cmap.nodes), \
        f"only {branches} branches parsed for {len(lite.cmap.nodes)} nodes -- the census is blind"




# ── move_with_collision_lines: the emitted move block ──────────────────────────────────────────

MOVE_KW = dict(radius=PLAYER_RADIUS, height=56, maxstep=24)
ROOT = "e1m1_cc_n0"                               # the cell routine's entry, as collision_cells_fj names it


@pytest.fixture(scope="module")
def move_ops(lite):
    return move_with_collision_lines(ROOT, "e1m1", **MOVE_KW)


def test_cprad_is_written_once_with_the_radius_before_the_first_position_test(move_ops):
    """⚠ The bug the function's own warning comment documents. `sim.check_cells` READS `cprad`
    and never sets it, and a declared-but-unwritten `hex.vec` is ZERO -- with `cprad = 0` the
    collision box collapses to a POINT and the player walks through every wall the real 32-unit box
    would straddle. This also catches the DIAMETER being wired where the radius belongs, which
    would double the box instead of collapsing it."""
    writes = [i for i, ln in enumerate(move_ops) if re.match(r"\s*hex\.set \d+, cprad,", ln)]
    assert len(writes) == 1, f"cprad is written {len(writes)} times, expected exactly once"
    val = int(re.fullmatch(r"\s*hex\.set \d+, cprad, (\d+)", move_ops[writes[0]]).group(1))
    assert val == PLAYER_RADIUS, f"cprad = {val}, expected PLAYER_RADIUS {PLAYER_RADIUS}"
    assert val * 2 != PLAYER_RADIUS and val != PLAYER_RADIUS * 2, "the radius, not the diameter"
    first_test = min(i for i, ln in enumerate(move_ops)
                     if "sim.check_cells" in ln or "sim.try_move" in ln)
    assert writes[0] < first_test, "cprad is written AFTER the first position test reads it"


def test_the_three_candidates_are_the_oracles_three_in_the_oracles_order(move_ops):
    """`ReferenceModel.move_with_collision` tries (x+dx, y+dy), (x+dx, y), (x, y+dy) in that order,
    and the emitted block must try the same three in the same order: the axis retry decides which
    wall the player slides along when a diagonal move is refused, and a reorder is a silent
    divergence the cumulative `m5_gate` would only show as a parted trajectory from frame 0."""
    # each candidate is the run of cpx/cpy construction between the previous try_move and this one
    tries = [i for i, ln in enumerate(move_ops) if "sim.try_move" in ln]
    assert len(tries) == 3, f"{len(tries)} candidates emitted, the policy has exactly three"
    start = min(i for i, ln in enumerate(move_ops) if "sim.check_cells" in ln)
    want = [["hex.mov 8, cpx, viewx", "hex.add 8, cpx, cm_dx",
             "hex.mov 8, cpy, viewy", "hex.add 8, cpy, cm_dy"],
            ["hex.mov 8, cpx, viewx", "hex.add 8, cpx, cm_dx", "hex.mov 8, cpy, viewy"],
            ["hex.mov 8, cpx, viewx", "hex.mov 8, cpy, viewy", "hex.add 8, cpy, cm_dy"]]
    for k, (end, expect) in enumerate(zip(tries, want)):
        window = [ln.strip() for ln in move_ops[start + 1:end]]
        got = [ln for ln in window if re.match(r"hex\.(mov|add) 8, cp[xy],", ln)]
        assert got == expect, f"candidate {k}: built ({got}), the oracle builds ({expect})"
        start = end


def test_all_four_checks_enter_the_same_cell_routine(move_ops):
    """The standing position and the three candidates are four checks of ONE routine: a second
    root would be a second tree -- and on a copy-paste slip, a different map's cells."""
    cps = [ln for ln in move_ops if "sim.check_cells" in ln]
    tms = [ln for ln in move_ops if "sim.try_move" in ln]
    assert len(cps) == 1 and len(tms) == 3
    assert cps[0].split("sim.check_cells", 1)[1].strip() == ROOT
    for tm in tms:
        tm_args = [a.strip() for a in tm.split("sim.try_move", 1)[1].split(",")]
        assert tm_args == [ROOT, str(MOVE_KW["height"]), str(MOVE_KW["maxstep"]), "cm_hf"], tm_args


# every op form the move block emits, and where (if anywhere) it names a label. A form missing from
# this table means the census below is incomplete, so an unknown op is a failure and not a skip.
_LABEL_ARGS = {
    "hex.set": (), "hex.mov": (), "hex.add": (), "hex.sub": (), "hex.zero": (),
    "sim.check_cells": (0,), "sim.try_move": (0,),
    "hex.sign": (-2, -1), "hex.if0": (-1,),
    "stl.fcall": (0,),                      # (walk target, return CELL) -- only the first is a label
}


def test_every_label_is_defined_once_and_every_jump_resolves(move_ops):
    """fj top-level labels are GLOBAL, so a copy-pasted `candidate()` call that reuses a tag
    (cma_/cmb_/cmc_) redefines `cma_vxs` and friends rather than shadowing them. The only labels
    this block may leave dangling are the TWO external entries: the map-prefixed seed descent and
    the cell routine."""
    text = "\n".join(move_ops)
    defined = _defined_labels(text)
    dupes = sorted(k for k, v in defined.items() if v > 1)
    assert not dupes, f"redefined labels: {dupes}"
    external = set()
    for ln in move_ops:
        s = ln.split("//")[0].strip()
        if not s or s.endswith(":"):
            continue
        if s.startswith(";"):
            tgt = s[1:].strip()
            assert tgt in defined or tgt == ";", f"fallthrough to undefined {tgt}"
            continue
        op, _, rest = s.partition(" ")
        assert op in _LABEL_ARGS, f"unknown op {op!r} -- the label census cannot be trusted"
        args = [a.strip() for a in rest.split(",")]
        for idx in _LABEL_ARGS[op]:
            tgt = args[idx]
            if tgt not in defined:
                external.add(tgt)
    assert external == {"e1m1_dsccs_walk", ROOT}, \
        f"unresolved jumps beyond the seed descent and the cell routine: {sorted(external)}"


def test_only_the_seed_descent_and_the_cell_root_are_map_prefixed(lite):
    """⚠ THE M4 HAZARD, stated rather than discovered at minute 40 of a nine-level build. The
    descent and the cell routine carry the map prefix, but `cmv_done`/`cmv_b`/`cmh_*`/`cma_*` are
    UNPREFIXED fj globals -- so two maps each emitting this block would redefine them, the same class
    of collision the M4-R1 label gate found. Emitting for two prefixes must differ in the two
    external names and in NOTHING else; when M4 prefixes these labels, this test fails and the
    change is deliberate."""
    a = move_with_collision_lines("e1m1_cc_n0", "e1m1", **MOVE_KW)
    b = move_with_collision_lines("e2m3_cc_n0", "e2m3", **MOVE_KW)
    assert _defined_labels("\n".join(a)) == _defined_labels("\n".join(b))
    differ = [(x, y) for x, y in zip(a, b) if x != y]
    assert differ and all("dsccs_walk" in x or "e1m1_cc_n0" in x for x, _ in differ), \
        f"the two maps differ somewhere other than the two external names: {differ[:3]}"


def test_move_with_collision_lines_is_deterministic(lite):
    """Called twice with the same arguments it must emit the same text."""
    assert move_with_collision_lines(ROOT, "e1m1", **MOVE_KW) == \
        move_with_collision_lines(ROOT, "e1m1", **MOVE_KW)


# ── the line constants' widths ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [LITE, FREEDOOM], ids=["e1m1_lite", "freedoom_e1m1"])
def test_every_line_constant_survives_the_argument_cell_it_is_xored_into(path):
    """A line stub xors `v << 16` for a coordinate into an 8-nibble cell, so a coordinate must be an
    int16 for the 16.16 value to be itself; a delta or an opening is sign-extended to 32 bits and
    only needs to fit there; the slope and the flags are ONE nibble each. `line_constants` masks
    with `& M32` and cannot complain -- a coordinate one bit too wide lands the wall's bbox
    elsewhere and the player walks through it.

    E1M1's widest coordinate is ~3,400 units, so today's headroom is enormous -- this is the guard
    M4's levels need. The R9 control at the end proves the predicate can say no."""
    lvl = Level(path)
    rows = lvl.rows()
    assert len(rows) == len(lvl.lds)

    def int16(v):
        return -(1 << 15) <= v < 1 << 15

    for li, (v1x, v1y, dx, dy, minx, maxx, miny, maxy, slope, flags, ot, ob) in enumerate(rows):
        for name, v in (("v1x", v1x), ("v1y", v1y), ("minx", minx), ("maxx", maxx),
                        ("miny", miny), ("maxy", maxy)):
            assert int16(v) and _signed((v << 16) & 0xFFFFFFFF, 32) == v << 16, \
                f"line {li} {name} = {v} does not survive as 16.16"
        for name, v in (("dx", dx), ("dy", dy), ("opentop", ot), ("openbottom", ob)):
            assert _signed(v & 0xFFFFFFFF, 32) == v, f"line {li} {name} = {v} wraps in 32 bits"
        assert 0 <= slope < 4 and 0 <= flags < 4, f"line {li}: slope {slope} flags {flags}"
    # R9: the same predicate must REFUSE a value one bit too wide, or it proves nothing
    assert not int16(1 << 15) and not int16(-(1 << 15) - 1)
    assert int16(-(1 << 15)) and int16((1 << 15) - 1)


def test_the_cell_model_agrees_with_the_oracle_off_the_map(lite):
    """Every other sample sits near the vertices. Far outside, no cell lists anything and the
    oracle's opening is the (solid) subsector's own -- the cell model has to reach the same answer
    through `lists.get(..., ())`, the Python mirror of the tree's `_none` stub. The counter is the
    control: those positions must really be in no cell."""
    rows = lite.rows()
    lists = cell_lists(rows, PLAYER_RADIUS)
    x0, x1, y0, y1 = lite.extent()
    unlisted = checked = 0
    for x in (x0 - 5000, x0 - 200, (x0 + x1) // 2, x1 + 200, x1 + 5000):
        for y in (y0 - 5000, y0 - 200, (y0 + y1) // 2, y1 + 200, y1 + 5000):
            sf, sc = lite.seed(x, y)
            got = check_position_cells(rows, lists, x << 16, y << 16, PLAYER_RADIUS, sf, sc)
            want = lite.rm.check_position(lite.scene, x << 16, y << 16)
            assert got == want, f"({x},{y}): cells {got} != oracle {want}"
            unlisted += (cell_of(x << 16), cell_of(y << 16)) not in lists
            checked += 1
    assert checked == 25 and unlisted >= 16, f"only {unlisted} of {checked} positions are off every list"


# ── the runtime door, in both mirrors at once ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def door_set(lite):
    """The door lines and the fully-open sector list, rebuilt from the same two helpers the emitter
    uses rather than imported from it."""
    states = door_states(lite.secs, lite.lds, lite.sds)
    dli = doorcode.door_line_ids(lite.secs, lite.lds, lite.sds, states)
    lines = frozenset(li for lis in dli.values() for li in lis)
    open_secs = apply_sector_heights(
        lite.secs, heights_for_states(lite.secs, lite.lds, lite.sds,
                                      {si: len(st) - 1 for si, st in states.items()}))
    return lines, open_secs


def test_a_shut_door_refuses_the_same_positions_in_both_mirrors(lite, door_set):
    """The two halves of the runtime door: `line_rows(door_line_ids=D)` bakes the door lines'
    opening OPEN, the cell routine adds FLAG_BLOCKING to a shut door's lines (`shut` here, `dstate`
    in fj), and the oracle consults `scene.blocked_lines`. On this second map, every sample must
    agree with every door shut.

    The second half is the R9 control: without it this passes with the door wiring deleted from
    both mirrors at once."""
    lines, open_secs = door_set
    assert lines, "e1m1_lite has no door -- this test proves nothing"
    rows_d = lite.rows(secs_open=open_secs, door_line_ids=lines)
    lists = cell_lists(rows_d, PLAYER_RADIUS)
    shut = build_scene(lite.wad, lite.wad, lite.mapname, blocked_lines=lines)
    open_ = lite.scene                                     # no blocked_lines: every door is passable
    rows_0 = lite.rows()
    lists_0 = cell_lists(rows_0, PLAYER_RADIUS)

    def both(scene, rows, lists, blocked, x, y):
        sf, sc = lite.seed(x, y)
        got = check_position_cells(rows, lists, x << 16, y << 16, PLAYER_RADIUS, sf, sc, blocked)
        want = lite.rm.check_position(scene, x << 16, y << 16)
        assert got == want, f"({x},{y}): cells {got} != oracle {want}"
        return want

    minx, maxx, miny, maxy = lite.extent()
    checked = 0
    for x in range(minx, maxx, 151):
        for y in range(miny, maxy, 157):
            both(shut, rows_d, lists, lines, x, y)
            checked += 1
    assert checked > 200, f"only {checked} positions sampled"
    # ... and the door set has to CHANGE the answer somewhere, in both mirrors together
    changed = 0
    for li in sorted(lines):
        ld = lite.lds[li]
        (x1, y1), (x2, y2) = lite.cmap.vertexes[ld.v1], lite.cmap.vertexes[ld.v2]
        x, y = (x1 + x2) // 2, (y1 + y2) // 2              # a box centred ON the line straddles it
        changed += (both(shut, rows_d, lists, lines, x, y)
                    != both(open_, rows_0, lists_0, frozenset(), x, y))
    assert changed > 5, f"only {changed} of {len(lines)} door lines change the answer when shut"


# ── two oracle contracts the fj loop mirrors ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def floor_groups(lite):
    """Legal sample positions, grouped by the floor height `check_position` reports for them."""
    minx, maxx, miny, maxy = lite.extent()
    groups = collections.defaultdict(list)
    for x in range(minx, maxx, 151):
        for y in range(miny, maxy, 157):
            ok, floorz, _c = lite.rm.check_position(lite.scene, x << 16, y << 16)
            if ok:
                groups[floorz].append((x, y))
    # a dozen origins per floor is enough to show a group agrees, and keeps this file fast
    return {f: pts[:12] for f, pts in groups.items() if len(pts) >= 3}


def test_a_moves_verdict_depends_on_the_origin_only_through_its_floor(lite, floor_groups):
    """⚠ A PIN, not a bug report. Collision here is UNSWEPT: `try_move` tests the DESTINATION box
    and reads the origin only for `check_position(origin).floorz`, so a teleport-length move is
    accepted whenever the destination is legal and the step is within MAX_STEP. That is the
    contract the fj loop mirrors, and it is invisible in every other test.

    If anyone later makes collision swept, this fails loudly and the behaviour change is deliberate
    and visible instead of a silent divergence between the oracle and the emitted program.

    Two controls: the verdict must depend on the origin floor SOMEWHERE (or `try_move` could be
    ignoring the origin entirely), and at least one accepted move's straight path must cross
    positions `check_position` refuses (or nothing here is teleport-shaped)."""
    floors = sorted(floor_groups)
    assert len(floors) > 5, f"only {len(floors)} distinct floors sampled"
    dests = [floor_groups[f][0] for f in floors[::4]]   # a spread of destination floors
    assert len(dests) >= 4
    per_dest = {}
    for dest in dests:
        verdicts = {}
        for f in floors:
            vs = {lite.rm.try_move(lite.scene, x << 16, y << 16, dest[0] << 16, dest[1] << 16)
                  for x, y in floor_groups[f]}
            assert len(vs) == 1, \
                f"origins on floor {f} disagree about ({dest[0]},{dest[1]}): {vs} -- the verdict " \
                "depends on the origin beyond its floor height"
            verdicts[f] = vs.pop()
        per_dest[dest] = verdicts
    assert any(len(set(v.values())) > 1 for v in per_dest.values()), \
        "no destination ever splits the floors -- try_move is ignoring the origin"
    # the teleport control: an accepted move whose straight path crosses refused ground
    crossed = 0
    for dest, verdicts in per_dest.items():
        for f in floors:
            if not verdicts[f]:
                continue
            ox, oy = max(floor_groups[f], key=lambda p: abs(p[0] - dest[0]) + abs(p[1] - dest[1]))
            blocked = sum(not lite.rm.check_position(
                lite.scene, (ox + (dest[0] - ox) * k // 40) << 16,
                (oy + (dest[1] - oy) * k // 40) << 16)[0] for k in range(41))
            if blocked >= 3:
                crossed += 1
        if crossed:
            break
    assert crossed, "no accepted move crosses refused ground -- the unswept contract is untested"


def test_the_refused_band_across_an_isolated_wall_is_the_box_width(lite):
    """The collision box's width, DERIVED and not read off. The half-width is PLAYER_RADIUS and
    DOOM's bbox reject is `box.right <= minx` / `box.left >= maxx`, so an axis-aligned one-sided
    wall is missed at exactly +/- radius: the refused band is 2*(PLAYER_RADIUS >> 16) - 1 = 31
    integer positions wide, centred on the wall.

    A radius wired as the DIAMETER gives 63, a `<` vs `<=` drift gives 33, and a collapsed (zero)
    radius gives 0 -- which is the `cprad = 0` failure mode in its Python mirror.

    Isolation is established GEOMETRICALLY (no other linedef's bbox can reach the scanned strip), so
    the filter is not quietly asserting the property it selects on."""
    want = 2 * R_UNITS - 1
    boxes = []
    for ld in lite.lds:
        (x1, y1), (x2, y2) = lite.cmap.vertexes[ld.v1], lite.cmap.vertexes[ld.v2]
        boxes.append((min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)))
    span = 2 * R_UNITS                                   # scan this far either side of the wall
    checked = {"vertical": 0, "horizontal": 0}
    for li, ld in enumerate(lite.lds):
        if ld.back != -1:
            continue                                      # one-sided only: a hard refusal
        (x1, y1), (x2, y2) = lite.cmap.vertexes[ld.v1], lite.cmap.vertexes[ld.v2]
        vertical = x1 == x2 and abs(y2 - y1) >= 4 * R_UNITS
        horizontal = y1 == y2 and abs(x2 - x1) >= 4 * R_UNITS
        if not (vertical or horizontal):
            continue
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        # a line matters only if its bbox can overlap the box at SOME scanned position
        rx = span + R_UNITS if vertical else R_UNITS
        ry = R_UNITS if vertical else span + R_UNITS
        if any(mnx < cx + rx and mxx > cx - rx and mny < cy + ry and mxy > cy - ry
               for lj, (mnx, mxx, mny, mxy) in enumerate(boxes) if lj != li):
            continue                                      # not isolated: some other line reaches
        axis = "vertical" if vertical else "horizontal"
        if checked[axis] >= 12:
            continue                                      # a dozen each is plenty and keeps this fast
        refused = [d for d in range(-span, span + 1)
                   if not lite.rm.check_position(
                       lite.scene, (cx + d if vertical else cx) << 16,
                       (cy if vertical else cy + d) << 16)[0]]
        assert len(refused) == want, \
            f"line {li} ({axis}) refuses {len(refused)} positions, the {2 * R_UNITS}-unit box " \
            f"implies {want}"
        assert refused == list(range(-(R_UNITS - 1), R_UNITS)), \
            f"line {li} ({axis}): the band {refused[0]}..{refused[-1]} is not centred on the wall"
        checked[axis] += 1
    assert checked["vertical"] >= 5 and checked["horizontal"] >= 1, \
        f"too few isolated one-sided walls found: {checked}"


# ── the fan-out edges into src/fj ──────────────────────────────────────────────────────────────

def _fj_captures(src: str, name: str) -> list:
    """The `< ...` capture list of one `def` in an fj file, with `\\` continuations joined."""
    joined = re.sub(r"\\\s*\n\s*", " ", src)
    m = re.search(r"^\s*def\s+" + name + r"\b([^{]*)\{", joined, re.M)
    assert m, f"src/fj/sim.fj no longer defines {name}"
    head = m.group(1)
    assert "<" in head, f"{name} captures nothing -- has the signature changed?"
    return [c.strip() for c in head.split("<", 1)[1].split(",") if c.strip()]


def test_every_cell_sim_captures_for_collision_is_declared_in_python():
    """⚠ The rule-5 fan-out: a scratch cell added on the fj side and forgotten in the Python list is
    an undeclared label at minute 40 of an assemble; here it is a grep."""
    src = SIM_FJ.read_text(encoding="utf-8")
    declared = {d.split(":")[0].strip() for d in COLLISION_STATE_DECLS}
    assert {d.split(":")[0].strip() for d in CHECK_SCRATCH_DECLS} <= declared, \
        "COLLISION_STATE_DECLS no longer splices in CHECK_SCRATCH_DECLS"
    assert {d.split(":")[0].strip() for d in CELL_DECLS} <= declared, \
        "COLLISION_STATE_DECLS no longer splices in CELL_DECLS"
    total = 0
    for name in ("check_cells", "line_test", "try_move"):
        caps = _fj_captures(src, name)
        assert caps, f"sim.{name} captures nothing"
        missing = [c for c in caps if c not in declared]
        assert not missing, f"sim.{name} captures {missing}, which COLLISION_STATE_DECLS omits"
        total += len(caps)
    assert total > 30, f"only {total} captured cells parsed -- the parser is not seeing the defs"
    # R9: the same parser must see the argument cells, and must NOTICE a cell that is not declared
    assert "ca_minx" in _fj_captures(src, "line_test") and "cc_ret" in _fj_captures(src, "check_cells")
    assert "no_such_cell_xyz" not in declared


def test_the_cell_size_is_the_one_the_trees_nibble_split_describes(lite):
    """The cell lives in two places: `CELL_SHIFT` (the lists, the model, `cell_of`) and the emitted
    tree, which jumps on nibbles 7, 6, 5 -- bit 20 up, 16-unit steps -- and gives both 16-unit
    halves of a cell the same target. Move one without the other and a centre's cell in fj is not
    its cell in Python: every position near a cell edge tests another cell's lines."""
    assert CELL_SHIFT == 21, "32-unit cells: the tree's finest step is bit 20, two steps a cell"
    rows = lite.rows()
    text, _root = collision_cells_fj("e1m1", rows, cell_lists(rows, PLAYER_RADIUS))
    split = collections.Counter((m.group(1), int(m.group(2))) for m in
                                re.finditer(r"sim\.jump16 (cp[xy]) \+ (\d)\*dw", text))
    assert set(split) == {(r, n) for r in ("cpx", "cpy") for n in (7, 6, 5)}, sorted(split)
    # the leaves: in every nibble-5 node, entries 2k and 2k+1 (one cell's two halves) agree
    pairs = 0
    for m in re.finditer(r"sim\.jump16 cp[xy] \+ 5\*dw, (.*)", text):
        t = [x.strip() for x in m.group(1).split(",")]
        assert all(t[2 * k] == t[2 * k + 1] for k in range(8)), t
        pairs += 1
    assert pairs > 100, f"only {pairs} leaf nodes parsed"
