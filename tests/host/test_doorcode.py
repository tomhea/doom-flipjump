"""M2-R4 -- the door's fj half, and what it shares with the collision cells.

`tests/host/test_doors.py` covers the geometry and `test_doors_runtime.py` the state model. Neither
touches `doomfj/doorcode.py`, which is the transliteration that turns that model into fj text, or
the branch M2-R4 added to `collision.line_rows`. Since M7 P1.2 those two meet in ONE place: a door
line's row carries the OPEN opening and no door bit, and the collision cells' stub for that line
reads the door's `dstate` against its pass state when it is tested. The door tic itself writes only
the door's own cells.

So the tests that matter here are the CROSS-MODULE ones: a door line's row must leave the door bit
to runtime, the door tic must touch nothing but its own state, and the cells the emitter declares
must be the cells the reset carries. (The stub's own reading of `dstate` is pinned in
`tests/host/test_collision_cells.py`.)
"""
import inspect
import re

import pytest

from doomfj import doorcode
from doomfj.build import DOOR_PERSIST
from doomfj.collision import FLAG_BLOCKING, FLAG_ONE_SIDED, line_rows
from doomfj.doors import door_states, heights_for_states, use_boxes_xy
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


# -- the door's lines: the row leaves the door to runtime ---------------------------------------

def _fully_open(level, doors):
    """The sector list with EVERY door at its last state -- what the emitter calls `_dsecs_open`,
    rebuilt here from the same two helpers rather than imported, so a change to either is a
    failure here and not a silently different table."""
    secs, lds, sds, _v = level
    return apply_sector_heights(
        secs, heights_for_states(secs, lds, sds, {si: len(st) - 1 for si, st in doors.items()}))


def test_a_door_lines_row_carries_no_static_block(level, doors):
    """The collision cells' door stub xors FLAG_BLOCKING into the line's flags while the door is
    shut, so the row's own flags must be ZERO: a baked bit would be CLEARED by that xor (a shut door
    you walk through), and a baked one-sided flag would make the door a wall at every state. The
    emitter refuses both (`collision_cells_fj`); this pins the row that makes it unnecessary."""
    secs, lds, sds, verts = level
    dli = doorcode.door_line_ids(secs, lds, sds, doors)
    door_lis = {li for lis in dli.values() for li in lis}
    assert len(door_lis) >= 20
    rows = line_rows(lds, verts, secs, sds, ML_BLOCKING,
                     secs_open=_fully_open(level, doors), door_line_ids=door_lis)
    for li in sorted(door_lis):
        assert rows[li][9] == 0, f"line {li} bakes flags {rows[li][9]}"
    # R9: the same rows DO carry the static flags where they belong
    walls = [li for li, ld in enumerate(lds) if ld.back == -1]
    assert walls and all(rows[li][9] & FLAG_ONE_SIDED for li in walls)
    blocking = [li for li, ld in enumerate(lds) if ld.back != -1 and ld.flags & ML_BLOCKING]
    assert all(rows[li][9] & FLAG_BLOCKING for li in blocking)


def test_the_door_tic_touches_only_the_doors_own_cells(level, doors):
    """Before P1.2 the tic flipped each door line's blocking bit in the collision table on the two
    steps that cross the pass state -- a second copy of the door's state. Now nothing in the tic
    may write outside `dstate`/`ddir`/`dsub`/`dwait`/`duse`/`dbox`; every other cell it names is
    only READ (the player's position for the use box, the key byte). And it cannot be HANDED the
    collision any more: before P1.2 a caller that passed the pass states and door lines got the
    patch, one that did not got a door that never stopped being a wall."""
    assert list(inspect.signature(doorcode.door_tic_lines).parameters) == \
        ["slots", "nstates", "boxes", "kinds"], "door_tic_lines takes collision inputs again"
    secs, lds, sds, verts = level
    slots = sorted(doors)
    text = "\n".join(doorcode.door_tic_lines(slots, {si: len(doors[si]) for si in slots},
                                             use_boxes_xy(secs, lds, sds, verts)))
    assert "wflip" not in text and "lnrow" not in text and "ca_" not in text
    written = set()
    for m in re.finditer(r"hex\.(?:set|zero|inc|dec|xor_by|mov) (?:\d+, )?([A-Za-z_]\w*)", text):
        written.add(m.group(1))
    assert written <= {"dstate", "ddir", "dsub", "dwait", "duse", "dbox", "dreq"}, sorted(written)
    assert {"dstate", "ddir", "dsub", "dwait"} <= written, "the census is not seeing the writes"


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
    """A door's one-sided TRACK walls have no opening at any state; listing one would give a solid
    wall a door stub -- which `collision_cells_fj` refuses, since its row's flags are not zero."""
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
