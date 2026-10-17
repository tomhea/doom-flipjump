"""M8 L1 -- the PAIR state switch, assembled and dispatched into.

A seg between two movers on DIFFERENT state cells (two lifts) has its constant block baked once per PAIR of states,
picked by `generate_pair_state_switch_fj`: the one-cell door switch on the first mover's cell, whose landings
`sim.jump16` on the second's. The emitter calls this exact generator (`wall_renderer._door_blocks`). No current map
reaches it -- E1M2's linedef 1460, which found the need, lies between two floor-switch sectors that move by ONE cell and
collapse to one mover (`_seg_movers`) -- so this harness is its only proof until a map with two adjacent lifts.

WHAT THE TESTS CHECK, and why each exists:

  * **every pair, twice.** A nested dispatch fails by ALIASING -- (2, 1) quietly running (1, 2)'s block paints a
    plausible wall at the wrong height -- and a dispatch whose clean is wrong looks perfect on the first call only. So
    every (i, j) is dispatched twice in a row: the first SETs its own value, the second CLEARs it back to 0.
  * **both cells survive.** `sim.jump16` xors the second cell's jump field and must xor it back; the outer switch
    xors the first cell into its dispatch op. Both cells are printed after every dispatch.
  * **the padding of the second cell is the last block** (as `_mover_dispatch`'s), not a jump into the table's tail.
  * **CONTROL:** the same program with the landings dispatching on the FIRST cell instead of the second must produce
    a different stream -- or the assertions above are not looking at the second cell at all.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_pair_state_switch_fj

FIXP = Path("src/fj/fixed_point.fj")
SIM = Path("src/fj/sim.fj")
NA, NB = 3, 5
# distinct per pair and not a simple function of (i, j): an off-by-one dispatch must not still look ordered
VALS = [[0xA7, 0x31, 0xFE, 0x05, 0x6C], [0xB9, 0x42, 0xDD, 0x18, 0x9E], [0x2B, 0xC4, 0x73, 0x5A, 0xE1]]


def _show():
    return ["    hex.print_uint 2, dreg, 0, 0", "    stl.output_char 0x20",
            "    hex.print_uint 1, ca, 0, 0", "    stl.output_char 0x20",
            "    hex.print_uint 1, cb, 0, 0", "    stl.output_char 0x20"]


def _program(order, *, wrong_cell=False):
    body = []
    for i, j in order:
        body += [f"    hex.set 1, ca, {i}", f"    hex.set 1, cb, {j}",
                 "    dsw_go ca", *_show(), "    dsw_go ca", *_show()]
    blocks = []
    for i in range(NA):
        for j in range(NB):
            blocks += [f"dsw_st{i}_{j}:", f"    hex.xor_by 2, dreg, {VALS[i][j]}", "    stl.fret dsw_x"]
    switch = generate_pair_state_switch_fj("dsw", "ca" if wrong_cell else "cb",
                                           [[f"dsw_st{i}_{j}" for j in range(NB)] for i in range(NA)])
    return "\n".join(["stl.startup_and_init_all", *body, "    stl.loop",
                      "dreg: hex.vec 2, 0", "ca: hex.vec 1, 0", "cb: hex.vec 1, 0", *blocks, switch]) + "\n"


def _run(tmp, tag, text):
    src = tmp / f"{tag}.fj"
    src.write_text(text, encoding="utf-8")
    out = tmp / f"{tag}.fjm"
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")        # sim.fj's pad constants
    fj.assemble([consts.resolve(), FIXP.resolve(), SIM.resolve(), src.resolve()], out,
                memory_width=W, print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode("ascii").split()


def _want(order, val):
    out = []
    for i, j in order:
        out += ["%x" % val(i, j), "%x" % i, "%x" % j, "0", "%x" % i, "%x" % j]
    return out


@pytest.fixture(scope="module")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("pairsw")


ALL = [(i, j) for i in range(NA) for j in range(NB)]


def test_every_pair_dispatches_to_its_own_block_twice_and_both_cells_survive(tmp):
    assert _run(tmp, "all", _program(ALL)) == _want(ALL, lambda i, j: VALS[i][j])


def test_the_second_cell_past_its_states_reuses_the_last_block(tmp):
    order = [(0, 9), (2, 15), (1, NB)]
    assert _run(tmp, "pad", _program(order)) == _want(order, lambda i, j: VALS[i][NB - 1])


def test_control_landings_on_the_wrong_cell_are_caught(tmp):
    """the landings dispatch on the first cell: (i, j) runs (i, i)'s block -- a different stream on this order"""
    got = _run(tmp, "ctl", _program(ALL, wrong_cell=True))
    assert got == _want(ALL, lambda i, j: VALS[i][i])
    assert got != _want(ALL, lambda i, j: VALS[i][j])


def test_the_generator_refuses_an_empty_or_wide_row():
    with pytest.raises(AssertionError):
        generate_pair_state_switch_fj("x", "c", [])
    with pytest.raises(AssertionError):
        generate_pair_state_switch_fj("x", "c", [[f"t{k}" for k in range(17)]])
