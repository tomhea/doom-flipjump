"""M8 size: the SHARED point location (config PTLOC_SHARED, `collision._shared_point_location_fj`), RUN in fj.

The inline walk emits a whole 10-nibble multiply pair (or a 10-nibble compare) per BSP node; the shared one keeps a
node's four constants in the node, XORs them into zero-at-rest registers and calls one subroutine per node kind. The
two must name the SAME leaf for every point -- the oracle's `point_in_subsector` -- and the registers must be zero
again after every call (the next node's XOR needs it), so every point here is located in ONE run, one after another.

The points: every vertex (they sit exactly ON partition lines -- the "on the line is front" convention), points ON
diagonal partitions (the cross product's zero), points one unit off them both ways, and random points; on E1M1 and on
E1M2 (388 diagonal nodes).

R9: two mutants of the shipped generator text must FAIL -- a register left non-zero after the diagonal subroutine
(the invariant), and the compare's "greater" answer folded into "equal" (the axis branch).
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.collision import generate_point_location_fj, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile

FIXP = Path("src/fj/fixed_point.fj")
WADS = {"E1M1": Path("tests/fixtures/freedoom_e1m1.wad"), "E1M2": Path("tests/fixtures/freedoom_e1m2.wad")}


def _program(cmap, walk_text, shared):
    return "\n".join([
        "stl.startup_and_init_all",
        "loop:",
        "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
        "hex.input 2, inx", "hex.input 2, iny",
        "hex.zero 10, ptx", "hex.mov 4, ptx, inx", "hex.sign 4, inx, xn, xp",
        "xn:", "hex.set 6, ptx + 4*dw, 0xFFFFFF", "xp:",
        "hex.zero 10, pty", "hex.mov 4, pty, iny", "hex.sign 4, iny, yn, yp",
        "yn:", "hex.set 6, pty + 4*dw, 0xFFFFFF", "yp:",
        "stl.fcall ptloc_walk, ptloc_ret",
        "hex.print_as_digit 4, ptss, 0", "stl.output 10",
        ";loop",
        "done:", "stl.loop",
        "wmagic: hex.vec 2", "inx: hex.vec 4", "iny: hex.vec 4",
        *point_location_decls(shared=shared),
        walk_text,
    ]) + "\n"


def _points(cmap, seed):
    rng = random.Random(seed)
    xs = [v[0] for v in cmap.vertexes]
    ys = [v[1] for v in cmap.vertexes]
    pts = [(v[0], v[1]) for v in cmap.vertexes]
    for n in cmap.nodes:
        if n.dx and n.dy:
            for k in (1, 2, -1):          # ON the partition line (when the step lands on integers)
                pts.append((n.x + k * n.dx, n.y + k * n.dy))
            pts += [(n.x + 1, n.y), (n.x - 1, n.y), (n.x, n.y + 1), (n.x, n.y - 1)]
        else:
            pts += [(n.x, n.y), (n.x + 1, n.y + 1), (n.x - 1, n.y - 1)]
    pts += [(rng.randint(min(xs), max(xs)), rng.randint(min(ys), max(ys))) for _ in range(300)]
    return [(x, y) for x, y in pts if -32768 <= x < 32768 and -32768 <= y < 32768]


def _run(tmp, name, text, pts):
    src = tmp / f"{name}.fj"
    src.write_text(text, encoding="utf-8")
    out = tmp / f"{name}.fjm"
    fj.assemble([FIXP.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(b"".join(bytes([0xD0]) + struct.pack("<hh", x, y) for x, y in pts) + b"\x00")
    stats = fj.run(out, io_device=io, print_time=False, print_termination=False)
    lines = io.get_output(allow_incomplete_output=True).decode().split("\n")
    return [int(v, 16) for v in lines[:len(pts)]], stats.op_counter


@pytest.fixture(scope="module", params=["E1M1", "E1M2"])
def level(request):
    wad = WadFile.from_path(WADS[request.param])
    cmap = bake_bsp(wad, request.param)
    rm = ReferenceModel(Config())
    pts = _points(cmap, 19)
    want = [rm.point_in_subsector(cmap, x, y) for x, y in pts]
    return request.param, cmap, pts, want


def test_shared_walk_names_the_oracles_leaf(level, tmp_path):
    name, cmap, pts, want = level
    got, ops = _run(tmp_path, "shared", _program(cmap, generate_point_location_fj(cmap, shared=True), True), pts)
    bad = [(p, g, w) for p, g, w in zip(pts, got, want) if g != w]
    assert not bad, f"{name}: {len(bad)} of {len(pts)} points located wrong, e.g. {bad[:4]}"
    print(f"{name}: {len(pts)} points, shared walk {ops:,} ops")


@pytest.mark.slow                   # the inline E1M1 walk takes ~170 s to assemble
def test_shared_walk_costs_little_more_than_inline(level, tmp_path):
    """the runtime price, measured: ops per located point, shared vs inline, over the same points (E1M1: the
    inline E1M2 walk alone is 23M words to assemble)"""
    name, cmap, pts, want = level
    if name != "E1M1":
        pytest.skip("priced on E1M1 (measured on E1M2 once: inline 71,469, shared 54,211 ops a point, -24.1%)")
    gs, ops_s = _run(tmp_path, "shared", _program(cmap, generate_point_location_fj(cmap, shared=True), True), pts)
    gi, ops_i = _run(tmp_path, "inline", _program(cmap, generate_point_location_fj(cmap), False), pts)
    assert gs == gi == want
    per_s, per_i = ops_s / len(pts), ops_i / len(pts)
    print(f"{name}: inline {per_i:,.0f} ops/point, shared {per_s:,.0f} ops/point ({100 * (per_s / per_i - 1):+.1f}%)")
    assert per_s < 1.25 * per_i, (per_s, per_i)


@pytest.mark.parametrize("mutant", ["register_left_set", "gt_folded_into_eq"])
def test_negative_control_mutants_fail(level, tmp_path, mutant):
    """R9: the harness must reject a broken shared walk (the shipped generator's text, mutated)"""
    name, cmap, pts, want = level
    if name != "E1M1":
        pytest.skip("the controls run on E1M1")
    text = generate_point_location_fj(cmap, shared=True)
    if mutant == "register_left_set":
        bad = text.replace("    hex.zero 10, ptlockdy\n", "", 1)
    else:
        bad = text.replace("    hex.xor_by ptlocr, 2\n    ;ptloc_sxq\n", "    hex.xor_by ptlocr, 1\n    ;ptloc_sxq\n", 1)
    assert bad != text, "the mutation did not apply: the generator text changed"
    got, _ops = _run(tmp_path, mutant, _program(cmap, bad, True), pts)
    assert got != want, f"{name}: the harness passed a mutant ({mutant})"


def test_inline_walk_text_unchanged_by_default():
    """PTLOC_SHARED off (E1M1, E1M2): the inline walk and its decls, exactly as before"""
    wad = WadFile.from_path(WADS["E1M1"])
    cmap = bake_bsp(wad, "E1M1")
    text = generate_point_location_fj(cmap)
    assert "ptloc_sd" not in text and "hex.mul_lo 10, ptlocp, ptlocdy, ptlock" in text
    assert point_location_decls() == point_location_decls(shared=False)
    assert not any("ptlockx" in d for d in point_location_decls())
    from doomfj.config import map_cfg
    assert not map_cfg(Config(), "E1M1").PTLOC_SHARED and not map_cfg(Config(), "E1M2").PTLOC_SHARED
    assert map_cfg(Config(), "E1M7").PTLOC_SHARED == 1
