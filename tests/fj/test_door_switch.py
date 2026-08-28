"""M2-R3 — the door STATE SWITCH, assembled and dispatched into.

`generate_state_switch_fj` is the runtime door's only new fj primitive: a 1-nibble switch that
fcalls one of N per-state constant blocks and returns to the caller. Everything else about R3 is
the existing emitter told to bake a block per state, so if this dispatches wrong, every door
renders wrong and nothing else will say why.

WHAT THE TESTS CHECK, and why each exists:

  * **every state, not a sample.** The failure mode of a switch built from a padded table is
    ALIASING, which is silent — state 5 quietly running state 1's block paints a plausible door at
    the wrong height. `m2_widen.py` learned this the expensive way (CR PR#78, R5): a five-id probe
    could not see it. Here N is small enough that "every state" is the whole loop.
  * **twice each.** The dispatch xors the index into its own dispatch op and the entry cleans it
    back out. If that clean is wrong the FIRST call still looks perfect and the second lands
    somewhere else — so every state is dispatched twice in a row and both must be right.
  * **the involution round-trips.** The real blocks are `hex.xor_by` constants, called once to SET
    and once to CLEAR. A block that does not leave the register at zero corrupts every seg after
    it, so each state's SET/CLEAR pair must return the register to 0.
  * **the padding is inert.** Entries past the last real state clean with their own index. A state
    cell holding an unreachable value must corrupt nothing rather than jump into the table's tail.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.harness import W
from doomfj.lut_generator import generate_state_switch_fj

# distinct per state, and deliberately NOT k or 1<<k: a value that is a simple function of the
# index would let an off-by-one dispatch still look ordered.
VALS = [0xA7, 0x31, 0xFE, 0x05, 0x6C, 0xB9, 0x42, 0xDD, 0x18]


def _show():
    """print the register, then a separator -- `hex.print_uint` strips leading zeros and prints no
    delimiter, so without this the whole run arrives as one unsplittable string (`a700031000fe0`)
    and every assertion below would be comparing against a shape the harness invented."""
    return ["    hex.print_uint 2, dreg, 0, 0", "    stl.output_char 0x20"]


def _blocks(name, vals):
    """One `hex.xor_by` constant block per state — the exact shape a seg's per-state block has."""
    out = []
    for k, v in enumerate(vals):
        out += [f"{name}_st{k}:", f"    hex.xor_by 2, dreg, {v}", f"    stl.fret dsw_x"]
    return out


def _program(nstates, *, order, clear=True):
    """`order` is the sequence of states to dispatch. Emits dreg after the SET and again after the
    CLEAR, so the stream carries both halves of every dispatch."""
    vals = VALS[:nstates]
    body = []
    for k in order:
        body += [f"    hex.set 1, dst, {k}",
                 "    dsw_go dst",
                 *_show(),
                 *(["    dsw_go dst", *_show()] if clear else [])]
    return "\n".join([
        "stl.startup_and_init_all",
        *body,
        "    stl.loop",
        "dreg: hex.vec 2, 0",
        "dst: hex.vec 1, 0",
        *_blocks("dsw", vals),
        generate_state_switch_fj("dsw", [f"dsw_st{k}" for k in range(nstates)]),
    ]) + "\n"


def _run(tmp, tag, text):
    src = tmp / f"{tag}.fj"
    src.write_text(text, encoding="utf-8")
    out = tmp / f"{tag}.fjm"
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode("ascii").split()


@pytest.fixture(scope="module")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("dsw")


def test_every_state_dispatches_to_its_own_block_twice(tmp):
    """The whole point, and both halves of it: state k SETs k's value, and dispatching k again
    CLEARs it back to zero — for every k, with no state sampled out."""
    n = len(VALS)
    got = _run(tmp, "all", _program(n, order=list(range(n))))
    want = []
    for k in range(n):
        want += ["%x" % VALS[k], "0"]
    assert got == want


def test_a_state_dispatched_repeatedly_keeps_dispatching_to_the_same_block(tmp):
    """The clean-back-out check. The index is xored INTO the dispatch op; if the entry's clean
    un-xors the wrong index the first call is still perfect and the second goes elsewhere."""
    n = len(VALS)
    got = _run(tmp, "rep", _program(n, order=[3, 3, 3, 7, 7, 0, 0]))
    want = []
    for k in [3, 3, 3, 7, 7, 0, 0]:
        want += ["%x" % VALS[k], "0"]
    assert got == want


def test_the_set_without_its_clear_leaves_the_register_dirty(tmp):
    """THE NEGATIVE CONTROL for the test above. `clear=False` is the bug the involution exists to
    prevent — values accumulate across dispatches — and it must produce a DIFFERENT stream, or the
    round-trip assertions are asserting nothing."""
    got = _run(tmp, "noclr", _program(4, order=[0, 1, 2, 3], clear=False))
    acc, want = 0, []
    for k in range(4):
        acc ^= VALS[k]
        want.append("%x" % acc)
    assert got == want
    assert got != ["%x" % v for v in VALS[:4]], "xor accumulation is what makes this a control"


def test_padding_entries_are_inert(tmp):
    """A state cell holding a value past the last real state must corrupt nothing. The switch pads
    to 16 and the padding cleans with its own index, so the register comes back untouched."""
    n = 3
    got = _run(tmp, "pad", _program(n, order=[0, 13, 1, 15, 2]))
    assert got == ["a7", "0", "0", "0", "31", "0", "0", "0", "fe", "0"]


def test_the_switch_pads_to_sixteen_and_refuses_more(tmp):
    """The index is ONE NIBBLE. 16 targets fit; 17 is a build-time refusal, not a wrong picture."""
    text = generate_state_switch_fj("x", [f"t{k}" for k in range(16)])
    assert text.count(";x_t") == 16 and "pad 16" in text
    assert ";x_clean__" in text
    with pytest.raises(AssertionError, match="does not fit"):
        generate_state_switch_fj("x", [f"t{k}" for k in range(17)])
