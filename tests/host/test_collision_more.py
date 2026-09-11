"""M14-d/M14-e — the parts of `doomfj/collision.py` that only a 45-minute assemble checks today.

`tests/host/test_collision.py` proves the ORACLE's geometry and that the table walk agrees with it
INSIDE the map; `tests/fj/test_collision_fj.py` proves the emitted fj computes the right answer, but
it builds a program. Between them sits the Python that WRITES the fj, and almost none of it is
checked without a build. This file closes that gap. Every test here is host-only and touches no
emitter output beyond the text it is handed.

What it pins, and what breaks in the shipped program if it stops holding:

* **`generate_point_location_fj`'s compile-time specialisation.** A node's descent is emitted as one
  `hex.scmp` instead of the cross product, and the three targets have to be what
  `mapcompiler._point_side` says at the three probes. A flipped `n.dy > 0`, a swapped `lo, hi`, or a
  swapped `n.left`/`n.right` sends the descent into the wrong subsector: things bind to the wrong
  leaf and `check_position`'s seed sector is wrong. Today that surfaces as a wrong picture after a
  full build. The diagonal branch's four baked constants are pinned in the same way.
* **Its label closure.** An `NF_SUBSECTOR` masking slip emits a jump to a label nothing defines —
  an assembler failure ~40 minutes into a heavy build; here it is milliseconds.
* **`move_with_collision_lines`' shape.** `cprad` once, with the RADIUS, before the first
  `sim.check_position` (the failure its own warning comment documents: an unwritten `cprad` is zero,
  the box collapses to a point and the player walks through walls); the three candidates in the
  oracle's order (a reorder changes which wall the player slides along, and only the cumulative
  `m5_gate` would see it); the blockmap arguments matching a `blockmap_grid` recomputed here; and
  every label defined once with every jump resolving.
* **The row layout.** `collision_tables_fj`'s local `pack` masks and cannot complain, so a field too
  wide for `LINE_ROW_BYTES` silently packs a WRAPPED value and the wall's bbox lands elsewhere. This
  is the guard M4's nine levels need — E1M1 has enormous headroom, an E2/E3 map need not.
  `line_box`/`line_rest` are pinned against distinct sentinels because the module's own
  `assert LINE_REST_BYTES[FLAGS_REST_INDEX] == 1` cannot tell `flags` from `slope`.
* **The LUT header counts**, which say `bkoff` is sized from the DENSE rectangle and not from the
  occupied set — sizing it from `len(grid)` makes every block past the first gap read another
  block's row.
* **`check_position_table` OUTSIDE the blockmap rectangle**, a branch every existing test misses:
  the `0 <= bx - bx0 < nbx` guard is computed after `bi`, so without it a negative index wraps into
  another block and a too-large one raises. It is also the Python mirror of `sim.check_block`'s
  `xok`/`yok`/`skip`.
* **The runtime door in both mirrors at once**: `line_rows(door_line_ids=D)` marks rows BLOCKING
  while the oracle consults `scene.blocked_lines`, and nothing compared the two answers before.
* **Two oracle contracts that are deliberate and undocumented by any test**: collision is UNSWEPT
  (a verdict depends on the destination box and on the origin only through its floor), and the
  refused band across a wall is exactly the 2*PLAYER_RADIUS - 1 units the box implies.
* **The fan-out rule 5 edges into fj**: every cell `sim.check_position`/`check_block`/`check_line`/
  `try_move` captures must be declared by `COLLISION_STATE_DECLS`, and `BLOCK_SHIFT` must be the
  block size `sim.check_block`'s three baked constants and `check_position_table`'s shift describe.
"""
import collections
import inspect
import re
from pathlib import Path

import pytest

from doomfj import doorcode
from doomfj.collision import (CHECK_SCRATCH_DECLS, COLLISION_STATE_DECLS, FLAGS_REST_INDEX,
                              LINE_BOX_BYTES, LINE_BOX_LEN, LINE_REST_BYTES, LINE_REST_LEN,
                              LINE_ROW_BYTES, block_tables, blockmap_grid, check_position_table,
                              collision_tables_fj, generate_point_location_fj, line_box, line_rest,
                              line_rows, move_with_collision_lines)
from doomfj.config import Config
from doomfj.doors import door_states, heights_for_states
from doomfj.fixedpoint import _signed
from doomfj.mapcompiler import (BLOCK_SHIFT, NF_SUBSECTOR, _point_side, bake_bsp, build_blockmap,
                                seg_sector)
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
        self.grid = build_blockmap(self.cmap, self.lds)
        self.scene = build_scene(self.wad, self.wad, self.mapname)
        self.rm = ReferenceModel(Config())

    def rows(self, **kw):
        return line_rows(self.lds, self.cmap.vertexes, self.secs, self.sds, ML_BLOCKING, **kw)

    def seed(self, x: int, y: int):
        """`check_position`'s subsector seed, the way the oracle computes it -- the caller's job on
        both sides, so the table walk has to be handed it."""
        ss = self.cmap.subsectors[self.rm.point_in_subsector(self.cmap, x, y)]
        sec = seg_sector(self.lds, self.sds, self.secs, self.cmap.segs[ss.firstseg])
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

MOVE_KW = dict(radius=PLAYER_RADIUS, height=56, maxstep=24, n_bk=4, n_bl=4, n_ln=4)


@pytest.fixture(scope="module")
def move_ops(lite):
    return move_with_collision_lines(lite.grid, "e1m1", **MOVE_KW)


def test_cprad_is_written_once_with_the_radius_before_the_first_position_test(move_ops):
    """⚠ The bug the function's own warning comment documents. `sim.check_position` READS `cprad`
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
                     if "sim.check_position" in ln or "sim.try_move" in ln)
    assert writes[0] < first_test, "cprad is written AFTER the first position test reads it"


def test_the_three_candidates_are_the_oracles_three_in_the_oracles_order(move_ops):
    """`ReferenceModel.move_with_collision` tries (x+dx, y+dy), (x+dx, y), (x, y+dy) in that order,
    and the emitted block must try the same three in the same order: the axis retry decides which
    wall the player slides along when a diagonal move is refused, and a reorder is a silent
    divergence the cumulative `m5_gate` would only show as a parted trajectory from frame 0."""
    # each candidate is the run of cpx/cpy construction between the previous try_move and this one
    tries = [i for i, ln in enumerate(move_ops) if "sim.try_move" in ln]
    assert len(tries) == 3, f"{len(tries)} candidates emitted, the policy has exactly three"
    start = min(i for i, ln in enumerate(move_ops) if "sim.check_position" in ln)
    want = [["hex.mov 8, cpx, viewx", "hex.add 8, cpx, cm_dx",
             "hex.mov 8, cpy, viewy", "hex.add 8, cpy, cm_dy"],
            ["hex.mov 8, cpx, viewx", "hex.add 8, cpx, cm_dx", "hex.mov 8, cpy, viewy"],
            ["hex.mov 8, cpx, viewx", "hex.mov 8, cpy, viewy", "hex.add 8, cpy, cm_dy"]]
    for k, (end, expect) in enumerate(zip(tries, want)):
        window = [ln.strip() for ln in move_ops[start + 1:end]]
        got = [ln for ln in window if re.match(r"hex\.(mov|add) 8, cp[xy],", ln)]
        assert got == expect, f"candidate {k}: built ({got}), the oracle builds ({expect})"
        start = end


def test_check_position_and_try_move_get_the_same_blockmap_arguments(lite, move_ops):
    """`bmi = (by - by0)*nbx + (bx - bx0)` is assembled from these five numbers; bx0/by0 swapped or
    nbx/nby transposed names a DIFFERENT block at runtime, so every candidate tests the wrong
    lines -- the failure `sim.check_block`'s xok/yok/skip branches exist to contain. The grid is
    recomputed here from the blockmap's own keys rather than by calling `blockmap_grid`."""
    cps = [ln for ln in move_ops if "sim.check_position" in ln]
    tms = [ln for ln in move_ops if "sim.try_move" in ln]
    assert len(cps) == 1 and len(tms) == 3
    cp_args = [a.strip() for a in cps[0].split("sim.check_position", 1)[1].split(",")]
    for tm in tms:
        tm_args = [a.strip() for a in tm.split("sim.try_move", 1)[1].split(",")]
        assert tm_args[:len(cp_args)] == cp_args, "try_move reads a different blockmap"
        assert tm_args[len(cp_args):] == [str(MOVE_KW["height"]), str(MOVE_KW["maxstep"]), "cm_hf"]
    bxs = [c[0] for c in lite.grid]
    bys = [c[1] for c in lite.grid]
    bx0, by0 = min(bxs), min(bys)
    want = [max(bxs) - bx0 + 1, max(bys) - by0 + 1, bx0, by0]     # nbx, nby, bx0, by0
    assert [int(a) for a in cp_args[-4:]] == want, \
        f"the emitted grid {cp_args[-4:]} is not (nbx, nby, bx0, by0) = {want}"
    assert blockmap_grid(lite.grid) == (bx0, by0, want[0], want[1])


# every op form the move block emits, and where (if anywhere) it names a label. A form missing from
# this table means the census below is incomplete, so an unknown op is a failure and not a skip.
_LABEL_ARGS = {
    "hex.set": (), "hex.mov": (), "hex.add": (), "hex.sub": (), "hex.zero": (),
    "sim.check_position": (), "sim.try_move": (),
    "hex.sign": (-2, -1), "hex.if0": (-1,),
    "stl.fcall": (0,),                      # (walk target, return CELL) -- only the first is a label
}


def test_every_label_is_defined_once_and_every_jump_resolves(move_ops):
    """fj top-level labels are GLOBAL, so a copy-pasted `candidate()` call that reuses a tag
    (cma_/cmb_/cmc_) redefines `cma_vxs` and friends rather than shadowing them. The only label
    this block may leave dangling is the ONE external fcall target, the map-prefixed seed
    descent."""
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
    assert external == {"e1m1_dsccs_walk"}, \
        f"unresolved jumps beyond the seed descent: {sorted(external)}"


def test_only_the_seed_descent_is_map_prefixed(lite):
    """⚠ THE M4 HAZARD, stated rather than discovered at minute 40 of a nine-level build. The
    descent target carries the map prefix, but `cmv_done`/`cmv_b`/`cmh_*`/`cma_*` are UNPREFIXED fj
    globals -- so two maps each emitting this block would redefine them, the same class of collision
    the M4-R1 label gate found. Emitting for two prefixes must differ in the fcall target and in
    NOTHING else; when M4 prefixes these labels, this test fails and the change is deliberate."""
    a = move_with_collision_lines(lite.grid, "e1m1", **MOVE_KW)
    b = move_with_collision_lines(lite.grid, "e2m3", **MOVE_KW)
    assert _defined_labels("\n".join(a)) == _defined_labels("\n".join(b))
    differ = [(x, y) for x, y in zip(a, b) if x != y]
    assert differ and all("dsccs_walk" in x for x, _ in differ), \
        f"the two maps differ somewhere other than the descent call: {differ[:3]}"


def test_move_with_collision_lines_is_deterministic(lite):
    """Called twice with the same grid it must emit the same text -- the emitter walks a dict, and
    an iteration-order dependence would make two builds of one tier differ."""
    assert move_with_collision_lines(lite.grid, "e1m1", **MOVE_KW) == \
        move_with_collision_lines(lite.grid, "e1m1", **MOVE_KW)


# ── the packed row layout ──────────────────────────────────────────────────────────────────────

SIGNED_ROW_FIELDS = (0, 1, 2, 3, 4, 5, 6, 7, 10, 11)   # v1x v1y dx dy + bbox + opentop openbottom
UNSIGNED_ROW_FIELDS = (8, 9)                            # slope, flags


def _fits_signed(v: int, nb: int) -> bool:
    return _signed(v & ((1 << 8 * nb) - 1), 8 * nb) == v


@pytest.mark.parametrize("path", [LITE, FREEDOOM], ids=["e1m1_lite", "freedoom_e1m1"])
def test_every_line_row_field_fits_the_width_it_is_packed_at(path):
    """`collision_tables_fj`'s local `pack` does `x & ((1 << 8*nb) - 1)` and CANNOT complain, so a
    linedef delta or a sector height too wide for its two bytes packs a WRAPPED value: the wall's
    bbox lands somewhere else on the map and the player walks through it.

    E1M1's widest `dx` is 1216 and its deepest floor -168, so today's headroom is enormous -- this
    is the guard M4's nine levels need, because an E2/E3 map with a wider extent is exactly what
    would trip it. The R9 control at the end proves the check can say no."""
    lvl = Level(path)
    rows = lvl.rows()
    assert len(rows) == len(lvl.lds)
    for li, row in enumerate(rows):
        assert len(row) == len(LINE_ROW_BYTES)
        for f in SIGNED_ROW_FIELDS:
            assert _fits_signed(row[f], LINE_ROW_BYTES[f]), \
                f"line {li} field {f} = {row[f]} wraps in {LINE_ROW_BYTES[f]} byte(s)"
        for f in UNSIGNED_ROW_FIELDS:
            assert 0 <= row[f] < 1 << 8 * LINE_ROW_BYTES[f], \
                f"line {li} field {f} = {row[f]} is not an unsigned {LINE_ROW_BYTES[f]}-byte value"
    # R9: the same predicate must REFUSE a value one bit too wide, or it proves nothing
    assert not _fits_signed(1 << 15, 2) and not _fits_signed(-(1 << 15) - 1, 2)
    assert _fits_signed(-(1 << 15), 2) and _fits_signed((1 << 15) - 1, 2)


def test_line_box_and_line_rest_pick_the_fields_their_names_claim():
    """Needs no fixture: twelve distinct sentinels say which indices each half takes. The module's
    own `assert LINE_REST_BYTES[FLAGS_REST_INDEX] == 1` cannot tell `flags` from `slope` -- both are
    one byte -- so a reorder of `LINE_ROW_BYTES`, or of `line_rest`'s `row[:4] + row[8:]`, that
    keeps the widths passes that assert and silently moves `doorcode._unblock_lines`' single wflip
    onto the SLOPE nibble. A door would then open by corrupting its own slope type."""
    row = tuple(range(100, 100 + len(LINE_ROW_BYTES)))        # distinct, positional sentinels
    assert line_box(row) == row[4:8], "line_box is not the four bbox fields"
    assert line_rest(row) == row[:4] + row[8:], "line_rest is not 'everything else, in order'"
    assert line_rest(row)[FLAGS_REST_INDEX] == row[9], \
        "FLAGS_REST_INDEX does not point at the flags field -- the door wflip would miss it"
    assert row[9] != row[8], "the sentinels must distinguish flags from slope"
    # the two halves partition the row exactly: no field lost, none counted twice
    assert sorted(line_box(row) + line_rest(row)) == sorted(row)
    assert (len(LINE_BOX_BYTES), LINE_BOX_LEN + LINE_REST_LEN) == (4, sum(LINE_ROW_BYTES))
    assert len(LINE_REST_BYTES) == len(LINE_ROW_BYTES) - 4


# ── the emitted tables ─────────────────────────────────────────────────────────────────────────

def test_the_four_lut_headers_count_what_the_walk_indexes(lite):
    """The four LUTs are indexed by three different things, and each header says which. `bkoff` is
    the one that bites: sized from `len(grid)` -- the OCCUPIED set -- every block index past the
    first gap reads another block's (offset, count) row. This also pins that `lnbox` and `lnrow`
    stay the same length, which is why `move_with_collision_lines` passes ONE `n_ln` for both."""
    text = collision_tables_fj(lite.cmap, lite.lds, lite.secs, lite.sds, ML_BLOCKING, lite.grid)
    hdr = {m.group(1): (int(m.group(2)), int(m.group(3))) for m in
           re.finditer(r'packed LUT "(\w+)": (\d+) entries x (\d+) bytes', text)}
    assert set(hdr) == {"lnbox", "lnrow", "bkoff", "bklin"}, f"emitted {sorted(hdr)}"
    _bx0, _by0, nbx, nby = blockmap_grid(lite.grid)
    n_lines = len(lite.lds)
    pairs = sum(len(v) for v in lite.grid.values())
    assert hdr["lnbox"] == (n_lines, LINE_BOX_LEN), "one bbox row per linedef"
    assert hdr["lnrow"] == (n_lines, LINE_REST_LEN), "one rest row per linedef"
    assert hdr["bkoff"] == (nbx * nby, 3), \
        f"bkoff is {hdr['bkoff'][0]} rows; the DENSE rectangle is {nbx * nby} and the occupied " \
        f"set is only {len(lite.grid)}"
    assert hdr["bklin"] == (pairs, 2), "one entry per (block, line) pair"
    assert nbx * nby > len(lite.grid), "this fixture has no unoccupied cell -- it proves nothing"


def test_each_block_row_selects_exactly_its_own_cells_line_list(lite):
    """`block_tables` flattens the grid and hands the loop an (offset, count) per DENSE cell. A
    bx0/by0 swap or an nbx/nby transpose makes the row name a different cell. The count-0 half is
    load-bearing on its own: it is why the fj loop needs no membership test, only a count that can
    be zero."""
    bx0, by0, nbx, nby = blockmap_grid(lite.grid)
    rows, flat = block_tables(lite.grid)
    assert len(rows) == nbx * nby
    assert len(flat) == sum(len(v) for v in lite.grid.values())
    for (bx, by), lines in lite.grid.items():
        off, cnt = rows[(by - by0) * nbx + (bx - bx0)]
        assert list(flat[off:off + cnt]) == list(lines), f"cell ({bx},{by}) selects the wrong lines"
    occupied = {(by - by0) * nbx + (bx - bx0) for bx, by in lite.grid}
    empty = [bi for bi in range(nbx * nby) if bi not in occupied]
    assert empty, "no unoccupied cell -- the count-0 half is untested on this fixture"
    for bi in empty:
        assert rows[bi][1] == 0, f"unoccupied cell {bi} claims {rows[bi][1]} lines"


# ── check_position_table outside the rectangle ─────────────────────────────────────────────────

def test_the_table_walk_agrees_with_the_oracle_outside_the_blockmap_rectangle(lite):
    """The branch no existing test reaches. `check_position_table` computes `bi` BEFORE the
    `0 <= bx - bx0 < nbx` guard, so without the guard a negative index wraps via Python's negative
    indexing into another block's row and a too-large one raises IndexError. Every other sample in
    the suite sits inside the vertex bounding box. This is also the Python mirror of
    `sim.check_block`'s xok/yok/skip, whose comment says an out-of-range index must be SKIPPED and
    not clamped.

    The two counters at the end are the R9 control: they say the guard actually had work to do."""
    rows = lite.rows()
    blocks, flat = block_tables(lite.grid)
    bx0, by0, nbx, nby = blockmap_grid(lite.grid)
    pad = 600                                     # far enough out that every corner leaves the grid
    lo_x, hi_x = (bx0 << BLOCK_SHIFT) - pad, ((bx0 + nbx) << BLOCK_SHIFT) + pad
    lo_y, hi_y = (by0 << BLOCK_SHIFT) - pad, ((by0 + nby) << BLOCK_SHIFT) + pad
    would_raise = would_wrap = checked = 0
    pts = [(x, y) for x in range(lo_x, hi_x + 1, 127) for y in range(lo_y, hi_y + 1, 131)]
    pts += [(x, y) for x in (-30000, 0, 30000) for y in (-30000, 0, 30000)]
    for x, y in pts:
        corners = [(bx, by)
                   for bx in {(x - R_UNITS) >> BLOCK_SHIFT, (x + R_UNITS) >> BLOCK_SHIFT}
                   for by in {(y - R_UNITS) >> BLOCK_SHIFT, (y + R_UNITS) >> BLOCK_SHIFT}]
        out = [(bx, by) for bx, by in corners
               if not (0 <= bx - bx0 < nbx and 0 <= by - by0 < nby)]
        if not out:
            continue                              # inside: the existing suite already covers it
        for bx, by in out:
            bi = (by - by0) * nbx + (bx - bx0)
            if bi < 0 or bi >= len(blocks):
                would_raise += 1
            elif blocks[bi][1]:
                would_wrap += 1
        sf, sc = lite.seed(x, y)
        got = check_position_table(rows, blocks, flat, lite.grid, x << 16, y << 16,
                                   PLAYER_RADIUS, sf, sc)
        want = lite.rm.check_position(lite.scene, x << 16, y << 16)
        assert got == want, f"({x},{y}) outside the grid: table {got} != oracle {want}"
        checked += 1
    assert checked > 300, f"only {checked} outside positions sampled"
    assert would_raise > 0 and would_wrap > 0, \
        f"the guard never had to fire (raise {would_raise}, wrap {would_wrap}) -- no bite"


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
    """The two halves of the runtime door have never been compared. `collision.line_rows` marks the
    row FLAG_BLOCKING and bakes its opening OPEN; the oracle consults `scene.blocked_lines` instead.
    `test_doorcode.py` pins the flags BYTE and the baked-open opening, but nothing asks whether a
    door actually REFUSES a position on both sides.

    The second half is the R9 control: without it this passes with the door wiring deleted from
    both mirrors at once."""
    lines, open_secs = door_set
    assert lines, "e1m1_lite has no door -- this test proves nothing"
    rows_d = lite.rows(secs_open=open_secs, door_line_ids=lines)
    rows_0 = lite.rows()
    blocks, flat = block_tables(lite.grid)
    shut = build_scene(lite.wad, lite.wad, lite.mapname, blocked_lines=lines)
    open_ = lite.scene                                     # no blocked_lines: every door is passable

    def both(scene, rows, x, y):
        sf, sc = lite.seed(x, y)
        got = check_position_table(rows, blocks, flat, lite.grid, x << 16, y << 16,
                                   PLAYER_RADIUS, sf, sc)
        want = lite.rm.check_position(scene, x << 16, y << 16)
        assert got == want, f"({x},{y}): table {got} != oracle {want}"
        return want

    minx, maxx, miny, maxy = lite.extent()
    checked = 0
    for x in range(minx, maxx, 151):
        for y in range(miny, maxy, 157):
            both(shut, rows_d, x, y)
            checked += 1
    assert checked > 200, f"only {checked} positions sampled"
    # ... and the door set has to CHANGE the answer somewhere, in both mirrors together
    changed = 0
    for li in sorted(lines):
        ld = lite.lds[li]
        (x1, y1), (x2, y2) = lite.cmap.vertexes[ld.v1], lite.cmap.vertexes[ld.v2]
        x, y = (x1 + x2) // 2, (y1 + y2) // 2              # a box centred ON the line straddles it
        changed += both(shut, rows_d, x, y) != both(open_, rows_0, x, y)
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
    """⚠ EXACTLY the rule-5 fan-out `CHECK_SCRATCH_DECLS`' own warning names: 'anything that
    assembles sim.check_position / check_block / check_line MUST emit these; they were duplicated in
    four places once.' A scratch cell added on the fj side and forgotten in the Python list is an
    undeclared label at minute 40 of an assemble; here it is a grep."""
    src = SIM_FJ.read_text(encoding="utf-8")
    declared = {d.split(":")[0].strip() for d in COLLISION_STATE_DECLS}
    assert {d.split(":")[0].strip() for d in CHECK_SCRATCH_DECLS} <= declared, \
        "COLLISION_STATE_DECLS no longer splices in CHECK_SCRATCH_DECLS"
    total = 0
    for name in ("check_position", "check_block", "check_line", "try_move"):
        caps = _fj_captures(src, name)
        assert caps, f"sim.{name} captures nothing"
        missing = [c for c in caps if c not in declared]
        assert not missing, f"sim.{name} captures {missing}, which COLLISION_STATE_DECLS omits"
        total += len(caps)
    assert total > 30, f"only {total} captured cells parsed -- the parser is not seeing the defs"
    # R9: the same parser must NOTICE a cell that is not declared
    assert "cb_bx" in _fj_captures(src, "check_block")
    assert "no_such_cell_xyz" not in declared


def test_the_block_size_is_the_same_in_all_three_places_it_is_encoded():
    """The block size lives in THREE independent places: `mapcompiler.BLOCK_SHIFT` (which shapes the
    grid), `check_position_table`'s hard-coded shift, and `sim.check_block`'s three baked constants.
    Change one -- back to DOOM's 128, say -- and the Python grid and the fj index describe different
    blocks, so every position reads some other block's lines. The Python-vs-Python half is caught
    indirectly by the oracle-agreement tests; the fj half is caught by nothing."""
    assert BLOCK_SHIFT % 4 == 0, \
        "the fj index is a WHOLE-NIBBLE shr_hex of a 16.16 position; BLOCK_SHIFT must be a multiple of 4"
    src = SIM_FJ.read_text(encoding="utf-8")
    body = re.search(r"def check_block\b.*?\n(.*?)\n    \}", src, re.S)
    assert body, "src/fj/sim.fj no longer defines check_block"
    body = body.group(1)
    # the bias: 2^15 map units in 16.16, so a signed coordinate shifts logically
    assert f"hex.set 8, cb_const, 0x{(1 << 15) << 16:08X}".lower() in body.lower(), \
        "check_block's 2^15 bias is not the one BLOCK_SHIFT's argument assumes"
    # the shift: (16 + BLOCK_SHIFT) bits, as whole nibbles
    nibbles = (16 + BLOCK_SHIFT) // 4
    shifts = set(int(m.group(1)) for m in re.finditer(r"hex\.shr_hex 8, (\d+), cb_b[xy]", body))
    assert shifts == {nibbles}, f"check_block shifts {shifts} nibbles, BLOCK_SHIFT implies {nibbles}"
    # the de-bias: the same 2^15 units expressed in BLOCKS
    off = 1 << (15 - BLOCK_SHIFT)
    got = set(re.findall(r"hex\.set 4, cb_const, \(ib[xy]0 \+ (\d+)\) & 0xFFFF", body))
    assert got == {str(off)}, f"check_block de-biases by {got}, BLOCK_SHIFT implies {off}"
    # ... and the Python mirror's hard-coded shift is the same number
    py = inspect.getsource(check_position_table)
    walk_shifts = [int(n) for n in re.findall(r">>\s*(\d+)", py) if int(n) != 16]
    assert walk_shifts and set(walk_shifts) == {BLOCK_SHIFT}, \
        f"check_position_table shifts by {sorted(set(walk_shifts))}, BLOCK_SHIFT is {BLOCK_SHIFT}"
    assert len(walk_shifts) >= 4, "expected a shift per box corner coordinate"
