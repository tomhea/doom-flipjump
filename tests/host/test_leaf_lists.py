"""M7 P1.3 -- the game tier's BAKED leaf lists (`things.spawn_leaf_lists`, `things.byte_array_decl`).

`sim.bind_things` rebuilt every leaf's list every frame from the spawn bindings, in ascending thing
order. The game tier now bakes that result and keeps it (`build.THING_PERSIST`), so two things have
to hold with no build in sight:

* the baked lists ARE bind_things' lists -- checked here against an independent construction (group
  by leaf, sort, chain) on E1M1's own things, not against a copy of the same loop;
* the baked declaration spells them in the byte-array layout `read_byte` reads, at the extent the
  old `hex.vec` had, so no label after it moves and the M1 restore set's span for it holds.

Each has its control (R9): a list built descending, and a declaration one cell short, are refused.
The relink that keeps the lists right when a thing moves is tests/fj/test_leaf_lists_fj.py.
"""
import re
from pathlib import Path

import pytest

from doomfj.config import Config
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ReferenceModel
from doomfj.things import LIST_MAX_THINGS, byte_array_decl, spawn_leaf_lists
from doomfj.wad import WadFile

E1M1 = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "freedoom_e1m1.wad"


@pytest.fixture(scope="module")
def e1m1_binds():
    """every E1M1 thing's spawn leaf -- the shape of the game tier's runtime bindings"""
    w = WadFile.from_path(str(E1M1))
    cmap = bake_bsp(w, "E1M1")
    rm = ReferenceModel(Config())
    things = w.things("E1M1")[:LIST_MAX_THINGS]      # the lists hold t + 1 in a byte
    return [rm.point_in_subsector(cmap, t.x, t.y) for t in things], len(cmap.subsectors)


def _chains(head, nxt):
    """{leaf: [thing, ...]} read back from the lists, the way the renderer walks them"""
    out = {}
    for leaf, cur in enumerate(head):
        seq = []
        while cur:
            seq.append(cur - 1)
            cur = nxt[cur - 1]
            assert len(seq) <= len(nxt), "a cycle"
        if seq:
            out[leaf] = seq
    return out


def _independent(binds):
    by = {}
    for t, leaf in enumerate(binds):
        by.setdefault(leaf, []).append(t)
    return {leaf: sorted(ts) for leaf, ts in by.items()}


def test_the_baked_lists_are_every_leafs_things_ascending(e1m1_binds):
    binds, nleaves = e1m1_binds
    head, nxt = spawn_leaf_lists(binds, nleaves)
    assert len(head) == nleaves and len(nxt) == len(binds)
    assert _chains(head, nxt) == _independent(binds)
    assert len(_independent(binds)) > 50 and max(len(v) for v in _independent(binds).values()) > 2
    # every thing is listed exactly once, and the lists end on 0
    assert sorted(t for seq in _chains(head, nxt).values() for t in seq) == list(range(len(binds)))
    # R9: the same check refuses a DESCENDING build (plain prepending in ascending order)
    bad_head, bad_nxt = [0] * nleaves, [0] * len(binds)
    for t, leaf in enumerate(binds):
        bad_nxt[t], bad_head[leaf] = bad_head[leaf], t + 1
    assert _chains(bad_head, bad_nxt) != _independent(binds)


def test_the_declaration_spells_the_bytes_at_the_old_extent():
    values = [3, 0, 255, 17, 1]
    text = byte_array_decl("sshead", values, 10)
    lines = text.split("\n")
    assert lines[0] == "sshead:"
    assert [int(m.group(1)) for m in (re.fullmatch(r";(\d+) \* dw", l) for l in lines[1:6])] == values
    assert lines[6:] == ["hex.vec 5"], "padded to the old `hex.vec 10` extent, no more, no less"
    # R9: an extent the values do not fit in is refused, not silently truncated
    with pytest.raises(AssertionError):
        byte_array_decl("sshead", values, 5)
    with pytest.raises(AssertionError):
        byte_array_decl("sshead", [256], 4)


def test_too_many_things_for_a_byte_are_refused():
    with pytest.raises(AssertionError):
        spawn_leaf_lists([0] * (LIST_MAX_THINGS + 1), 1)
    assert spawn_leaf_lists([0] * LIST_MAX_THINGS, 1)[0] == [1]


def test_a_map_with_no_runtime_things_bakes_an_empty_array():
    """no entry, no cell -- the game tier emitted on a thing-less map (the one-room fixture) must
    not trip the extent check, while a full array still must"""
    assert byte_array_decl("thnext", [], 0) == "thnext:\nhex.vec 0"
    with pytest.raises(AssertionError):
        byte_array_decl("thnext", [1, 2], 2)            # no zero cell left after the entries

