"""M7 P1.5 -- what the shipped build's `--pin-state-cells` must never pin (scratchpad/12m/build_blocked.py).

The blocking pass pins the words table-family macros write, and a pinned word holds base + value.
Hex ops dispatch THROUGH a cell and keep working; a RAW read through a pointer takes the base for
part of the value. NEW GAME's restart writes the runtime things' positions and bindings with
`hex.set` in pass-1 code -- which makes them pin candidates for the first time -- while
`sim.thing_pass` reads the positions through `hex.ptr_index` + `hex.read_hex`. So the veto
(`build_blocked.pin_state_veto`) covers every `selfreset.POINTER_READ_CELLS` label at its whole
extent, besides the byte cells.

R9: the same veto with POINTER_READ_CELLS emptied leaves the positions pinnable, and the check says so.
"""
import importlib.util
from pathlib import Path

from doomfj import selfreset
from doomfj.harness import W

ROOT = Path(__file__).resolve().parents[2]

# A miniature label table (word addresses): the three byte arrays as the real build declares them
# (sshead over-allocated 2x for 3 subsectors; pclm and sfflag for a 2-column view), the three other
# pointer-read labels, and one ordinary register.
FAKE = {"sshead": 200, "pclm": 212, "sfflag": 216, "thss_rt": 220, "thpos_rt": 252,
        "thnext": 284, "viewx": 290, "zzz_end": 306}
LABELS = {k: v * W for k, v in FAKE.items()}


def _veto():
    spec = importlib.util.spec_from_file_location("build_blocked",
                                                  ROOT / "scratchpad/12m/build_blocked.py")
    bb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bb)
    return bb.pin_state_veto(LABELS, view_w=2, subsectors=3)


def _span(name, nxt):
    return set(range(FAKE[name], FAKE[nxt]))


def test_every_pointer_read_label_is_vetoed_at_its_whole_extent():
    veto = _veto()
    for name, nxt in (("thss_rt", "thpos_rt"), ("thpos_rt", "thnext"), ("thnext", "viewx"),
                      ("sshead", "pclm")):
        missing = _span(name, nxt) - veto
        assert not missing, "%s: %d words pinnable, e.g. %s" % (name, len(missing), sorted(missing)[:3])
    assert _span("pclm", "sfflag") | _span("sfflag", "thss_rt") <= veto     # the byte cells, as before
    assert not _span("viewx", "zzz_end") & veto                             # a register stays pinnable


def test_the_list_names_the_cells_the_thing_code_reads_through_pointers():
    """the positions (sim.thing_pass), the bindings (sim.bind_things) and both halves of the lists"""
    assert {"thpos_rt", "thss_rt", "sshead", "thnext"} <= set(selfreset.POINTER_READ_CELLS)


def test_a_veto_without_the_list_leaves_the_positions_pinnable(monkeypatch):
    monkeypatch.setattr(selfreset, "POINTER_READ_CELLS", ())
    veto = _veto()
    assert _span("thpos_rt", "thnext") - veto, "the check cannot tell the list was dropped"
