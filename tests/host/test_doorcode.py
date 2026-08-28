"""M2-R4 -- the door's fj half, and the ONE BIT it shares with the collision table.

`tests/host/test_doors.py` covers the geometry and `test_doors_runtime.py` the state model. Neither
touches `doomfj/doorcode.py`, which is the transliteration that turns that model into fj text, or
the branch M2-R4 added to `collision.line_rows`. Those two are a matched pair: `line_rows` bakes a
door's opening at the OPEN height and marks the line BLOCKING, and `doorcode._unblock_lines` emits
the single `wflip` that clears the bit. The whole "a runtime door costs nothing on the hot path"
claim is that pairing, and it is exactly the shape that drifts silently -- the address is computed
in one module out of constants that live in the other.

So the tests that matter here are the CROSS-MODULE ones: the flipped byte must be the byte the
walk reads, and the cells the emitter declares must be the cells the reset carries.
"""
import re

import pytest

from doomfj import doorcode
from doomfj.build import DOOR_PERSIST
from doomfj.collision import (FLAG_BLOCKING, FLAG_ONE_SIDED, FLAGS_REST_BYTE, FLAGS_REST_INDEX,
                              LINE_REST_BYTES, LINE_REST_LEN, line_rows)
from doomfj.doors import door_states, heights_for_states
from doomfj.reference_model import apply_sector_heights
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile
from doomfj.wireformat import KEY_NAMES, KEY_USE, KEY_USE_MASK, keys_dict

E1M1 = "tests/fixtures/freedoom_e1m1.wad"
ML_BLOCKING = 1


@pytest.fixture(scope="module")
def level():
    w = WadFile.from_path(E1M1)
    return (w.sectors("E1M1"), w.linedefs("E1M1"), w.sidedefs("E1M1"),
            bake_bsp(w, "E1M1").vertexes)


@pytest.fixture(scope="module")
def doors(level):
    secs, lds, sds, _v = level
    return door_states(secs, lds, sds)


# -- the one bit: what `line_rows` bakes and what `_unblock_lines` flips ------------------------

def _fully_open(level, doors):
    """The sector list with EVERY door at its last state -- what the emitter calls `_dsecs_open`,
    rebuilt here from the same two helpers rather than imported, so a change to either is a
    failure here and not a silently different table."""
    secs, lds, sds, _v = level
    return apply_sector_heights(
        secs, heights_for_states(secs, lds, sds, {si: len(st) - 1 for si, st in doors.items()}))


def test_the_wflip_targets_the_flags_byte_the_walk_reads(level, doors):
    """THE cross-module invariant. `_unblock_lines` writes an address out of `collision`'s row
    layout; if either side's stride moved, the flip would land on a neighbouring field -- `opentop`
    is the very next one -- and a door would open by corrupting its own height instead of by
    clearing a flag. Recompute the address here from the layout, independently of the f-string."""
    secs, lds, sds, _v = level
    dli = doorcode.door_line_ids(secs, lds, sds, doors)
    lis = sorted(dli[sorted(dli)[0]])
    out = doorcode._unblock_lines(lis)
    assert len(out) == len(lis)
    for line, li in zip(out, lis):
        m = re.fullmatch(r"\s*wflip lnrow \+ (\d+)\*dw \+ w, (0x[0-9a-fA-F]+)\*dw", line)
        assert m, line
        assert int(m.group(1)) == li * LINE_REST_LEN + FLAGS_REST_BYTE
        assert int(m.group(2), 16) == FLAG_BLOCKING
    # ... and the byte it lands on really is one byte wide, with a whole field after it to hit.
    assert LINE_REST_BYTES[FLAGS_REST_INDEX] == 1
    assert FLAGS_REST_BYTE + 1 < LINE_REST_LEN


def test_the_flip_is_dispatch_free(level, doors):
    """R42: a switch target may only `wflip`/`hex.xor_by` -- anything that dispatches cannot sit
    there. The unblock is emitted where a per-state form could need to, so it stays clean."""
    secs, lds, sds, _v = level
    dli = doorcode.door_line_ids(secs, lds, sds, doors)
    for line in doorcode._unblock_lines(sorted(dli[sorted(dli)[0]])):
        assert line.strip().startswith("wflip ")
        assert "hex.set" not in line and ";" not in line


def test_toggling_that_bit_is_what_turns_a_door_from_wall_into_doorway(level, doors):
    """The bit's MEANING, not just its address: with it set the row reads as blocking, and one XOR
    of `FLAG_BLOCKING` at that byte is the whole difference. `check_position`'s wall test is
    `flags & (FLAG_ONE_SIDED | FLAG_BLOCKING)`, so this is the value that test reads."""
    secs, lds, sds, verts = level
    secs_open = _fully_open(level, doors)
    dli = doorcode.door_line_ids(secs, lds, sds, doors)
    door_lis = {li for lis in dli.values() for li in lis}
    rows = line_rows(lds, verts, secs, sds, ML_BLOCKING,
                     secs_open=secs_open, door_line_ids=door_lis)
    for li in sorted(door_lis):
        flags = rows[li][9]
        assert flags & FLAG_BLOCKING, f"line {li} bakes shut-as-a-wall"
        assert not flags & FLAG_ONE_SIDED, f"line {li} has no opening to clear into"
        assert not (flags ^ FLAG_BLOCKING) & (FLAG_ONE_SIDED | FLAG_BLOCKING), (
            f"line {li} would still refuse after the wflip -- the one bit is not enough")


def test_a_door_line_bakes_its_opening_at_the_OPEN_height(level, doors):
    """Why the one bit is enough: the gap is baked as if the door were fully open, so once the
    flag clears there is nothing else to update. A shut door's own geometry would give a zero-high
    opening, and clearing the flag would then admit the player into a gap they do not fit."""
    secs, lds, sds, verts = level
    secs_open = _fully_open(level, doors)
    dli = doorcode.door_line_ids(secs, lds, sds, doors)
    door_lis = {li for lis in dli.values() for li in lis}
    shut = line_rows(lds, verts, secs, sds, ML_BLOCKING)
    open_ = line_rows(lds, verts, secs, sds, ML_BLOCKING,
                      secs_open=secs_open, door_line_ids=door_lis)
    moved = [li for li in sorted(door_lis) if open_[li][10] != shut[li][10]]
    assert moved, "no door line's opening moved -- secs_open was not consulted"
    for li in moved:
        assert open_[li][10] > shut[li][10], f"line {li}'s ceiling went DOWN when the door opened"
    for li in range(len(lds)):                      # and nothing outside the door set moved at all
        if li not in door_lis:
            assert open_[li] == shut[li], f"line {li} is not a door and changed"


def test_without_the_door_arguments_the_table_is_the_stock_one(level):
    """The default path is the one every non-doors build takes, and it must be untouched by R4."""
    secs, lds, sds, verts = level
    assert line_rows(lds, verts, secs, sds, ML_BLOCKING) == \
        line_rows(lds, verts, secs, sds, ML_BLOCKING, secs_open=None, door_line_ids=frozenset())


def test_door_line_ids_are_two_sided_only(level, doors):
    """A door's one-sided TRACK walls have no opening at any state; listing one would emit a wflip
    that clears the blocking bit on a solid wall, i.e. a hole in the map."""
    secs, lds, sds, _v = level
    dli = doorcode.door_line_ids(secs, lds, sds, doors)
    assert set(dli) <= set(doors)
    for si, lis in dli.items():
        assert lis, f"door sector {si} has no two-sided line"
        for li in lis:
            ld = lds[li]
            assert ld.back not in (-1, 0xFFFF) and ld.back < len(sds)
            assert si in (sds[ld.front].sector, sds[ld.back].sector)


# -- the declarations, and the reset that has to carry them ------------------------------------

def test_the_declared_cells_are_exactly_the_ones_the_reset_persists(doors):
    """The owner's standing rule, as a test: a feature is not complete until the M1 reset loop
    carries its labels. `door_decls` declares the runtime state; `DOOR_PERSIST` is what survives
    the reset. Every cell the tic machine WRITES must be in both, or the doors re-shut every
    frame -- and a new cell added to one side alone fails here rather than in a 4,966-second
    build that nobody re-runs."""
    names = [d.split(":")[0] for d in doorcode.door_decls(len(doors))]
    assert set(DOOR_PERSIST) <= set(names)
    # `duse`/`dbox` are per-frame scratch: written before they are read, every frame, so they need
    # not survive. Everything else is state and must.
    assert set(names) - set(DOOR_PERSIST) == {"duse", "dbox"}


def test_every_declared_cell_is_baked_shut_and_idle(doors):
    """State 0 is the map as stored, so a doors build renders the stock picture until something
    writes a nibble. A non-zero initial value here would move pixels on frame 0."""
    for d in doorcode.door_decls(len(doors)):
        assert d.endswith(", 0"), d


def test_the_wait_counter_is_wide_enough_for_WAIT(doors):
    """`dwait` is WAIT_NIBBLES per door; a WAIT that overflowed it would wrap to an early close."""
    decl = [d for d in doorcode.door_decls(len(doors)) if d.startswith("dwait:")][0]
    assert int(decl.split()[2].rstrip(",")) == doorcode.WAIT_NIBBLES * len(doors)


# -- the use key on the wire -------------------------------------------------------------------

def test_use_is_the_first_bit_of_the_second_nibble():
    """The four movement bits fill the low nibble exactly, so bit 4 is the first bit that costs no
    new dispatch: the fj side reads it at `pkeys + 1*dw` under the SAME mask as bit 0."""
    assert KEY_USE == 1 << 4
    assert KEY_USE_MASK == sum(1 << v for v in range(16) if v & 1)
    assert KEY_USE not in (1, 2, 4, 8)


def test_keys_dict_reports_use_and_leaves_the_movement_bits_alone():
    assert keys_dict(KEY_USE)["use"] is True
    assert not any(v for k, v in keys_dict(KEY_USE).items() if k != "use")
    assert keys_dict(0)["use"] is False
    assert keys_dict(0xFF) == {n: True for n in KEY_NAMES}       # bits 5..7 do not exist
    assert keys_dict(0xE0)["use"] is False
