"""M7 P1.5 -- what the shipped (blocked) build must never pin: flipjump BlockPool's `pin_all_but`, as the build names
it (selfreset.pin_all_but_cells, build.build_wall_renderer's `Assembly.pool`; scratchpad/12m/build_blocked.py).

The blocking pass pins the words table-family macros write, and a pinned word holds base + value.
Hex ops dispatch THROUGH a cell and keep working; a RAW read through a pointer takes the base for
part of the value. NEW GAME's restart writes the runtime things' positions and bindings with
`hex.set` in pass-1 code -- which makes them pin candidates for the first time -- while
`sim.thing_pass` reads the positions through `hex.ptr_index` + `hex.read_hex`. So the list names every
`selfreset.POINTER_READ_CELLS` label (flipjump's label-alone form: the cell runs to the next label), besides the
byte cells over their reachable extent.

The words are resolved by flipjump's OWN BlockPool.unpinned_words, so this holds the list to what the assembler
leaves unpinned, not to a model of it. R9: the same list with POINTER_READ_CELLS emptied leaves the positions
pinnable, and the check says so; a pointer label the program lacks is never named.
"""
import pytest
from flipjump.assembler.inner_classes.table_pool import BlockPool

from doomfj import selfreset
from doomfj.harness import W

# A miniature label table (word addresses): the three byte arrays as the real build declares them
# (sshead over-allocated 2x for 3 subsectors; pclm and sfflag for a 2-column view), the three other
# pointer-read labels, and one ordinary register.
FAKE = {"sshead": 200, "pclm": 212, "sfflag": 216, "thss_rt": 220, "thpos_rt": 252,
        "thnext": 284, "viewx": 290, "zzz_end": 306}
LABELS = {k: v * W for k, v in FAKE.items()}


def _cells():
    return selfreset.pin_all_but_cells(set(FAKE), view_w=2, nss=3)


def _unpinned(cells):
    """the WORD addresses flipjump's pool leaves unpinned for `cells`"""
    pool = BlockPool(W, 1 << 26, pin_all_but=cells)
    words = pool.unpinned_words(LABELS)
    assert not pool.pin_all_but_missing, pool.pin_all_but_missing
    return {b // W for b in words}


def _span(name, nxt):
    return set(range(FAKE[name], FAKE[nxt]))


def test_every_pointer_read_label_is_left_unpinned_at_its_whole_extent():
    veto = _unpinned(_cells())
    for name, nxt in (("thss_rt", "thpos_rt"), ("thpos_rt", "thnext"), ("thnext", "viewx"),
                      ("sshead", "pclm")):
        missing = _span(name, nxt) - veto
        assert not missing, "%s: %d words pinnable, e.g. %s" % (name, len(missing), sorted(missing)[:3])
    assert _span("pclm", "sfflag") | _span("sfflag", "thss_rt") <= veto     # the byte cells, as before
    assert not _span("viewx", "zzz_end") & veto                             # a register stays pinnable


def test_the_byte_cells_are_their_reachable_cells_only():
    """sshead declares 2 cells a leaf and a 1-cell stride reaches nss of them: (name, n) is n ops = 2n words"""
    cells = selfreset.pin_all_but_cells(set(FAKE), view_w=2, nss=3, pointer_cells=False)
    assert cells == [("sshead", 3), ("pclm", 2), ("sfflag", 2)]
    assert _unpinned(cells) == set(range(200, 206)) | _span("pclm", "sfflag") | _span("sfflag", "thss_rt")
    selfreset.check_pin_all_but(cells, LABELS, 2, 3)                        # the geometry agrees with the labels
    with pytest.raises(AssertionError):
        selfreset.check_pin_all_but([("sshead", 4), ("pclm", 2), ("sfflag", 2)], LABELS, 2, 4)


def test_the_list_names_the_cells_the_thing_code_reads_through_pointers():
    """the positions (sim.thing_pass), the bindings (sim.bind_things) and both halves of the lists"""
    assert {"thpos_rt", "thss_rt", "sshead", "thnext"} <= set(selfreset.POINTER_READ_CELLS)


def test_a_pointer_label_the_program_lacks_is_never_named():
    """flipjump refuses a pin_all_but label the program does not define, so only DECLARED ones are passed -- and
    the post-assembly check refuses a list that missed one the program has"""
    cells = _cells()
    assert "thseen" not in cells and "thpos_rt" in cells
    selfreset.check_pin_all_but(cells, LABELS, 2, 3)
    with pytest.raises(AssertionError):
        selfreset.check_pin_all_but([c for c in cells if c != "thpos_rt"], LABELS, 2, 3)


def test_the_declarations_are_read_off_the_program(tmp_path):
    part = tmp_path / "e1m1_05_state.fj"
    part.write_text("thpos_rt:\n    hex.vec 4, 0\n  thss_rt: hex.vec 16\n// thnext: a comment\nthseenx: hex.vec 1\n",
                    encoding="utf-8")
    assert selfreset.declared_names([part], selfreset.POINTER_READ_CELLS) == {"thpos_rt", "thss_rt"}


def test_a_list_without_the_pointer_cells_leaves_the_positions_pinnable(monkeypatch):
    monkeypatch.setattr(selfreset, "POINTER_READ_CELLS", ())
    veto = _unpinned(_cells())
    assert _span("thpos_rt", "thnext") - veto, "the check cannot tell the list was dropped"
