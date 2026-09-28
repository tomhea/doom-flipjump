"""M7 P1.5 review -- the probe tools still read binaries built BEFORE the rung (scratchpad/gp/probe.py).

P1.5 gave the game tier two persisted cells, `menu_scr` and `menu_sel`, and `probe.game_cells` and
`Oracle.known_pristine` list them -- so every probe-based tool (b0, b0_scenarios, gamespeed_trail,
the probe's own selftest and demo) raised KeyError on the label table of a binary built before it,
the shipped blocked27's included (probe.DEFAULT_FJM). They are OPTIONAL now: a table may lack both
(never just one), a Probe drops the cells it has no label for, and the known-value check skips their
values. Every other label is still required -- the R9 half.

No binary: a synthetic label table (the build's gz TSV, `name<TAB>bit address`) and the probe's own
fake device memory.
"""
import gzip
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
ND = 3                                             # doors in the synthetic table
CELL_BITS = 64                                     # dw at w = 32


def _load_probe():
    spec = importlib.util.spec_from_file_location("gp_probe", ROOT / "scratchpad/gp/probe.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # @dataclass resolves the module's annotations through it
    spec.loader.exec_module(mod)
    return mod


P = _load_probe()


def _table(tmp_path, drop=()):
    """every game cell's label, 64 cells apart (wider than any cell spec), less the ones in `drop`"""
    lines, at = [], 1 << 20
    for c in P.game_cells(ND, 2).values():
        if c.label not in drop:
            lines.append("%s\t%d" % (c.label, at))
        at += 64 * CELL_BITS
    lines.append("zz_end\t%d" % at)
    path = tmp_path / ("labels-%s.tsv.gz" % ("-".join(drop) or "all"))
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return P.LabelTable.load(path, {c.label for c in P.game_cells(ND, 2).values()})


def _known():
    """Oracle.known_pristine without the WADs: it reads only the door count and the spawn"""
    stub = SimpleNamespace(ndoors=ND, nwalk=2, spawn=SimpleNamespace(x=-(5 << 16), y=7 << 16, angle=1 << 30))
    return P.Oracle.known_pristine(stub)


def _probe_holding(table, values):
    p = P.Probe(P.game_cells(ND, 2), table)
    p.attach(P._FakeMemory())
    p.write_cells({k: v for k, v in values.items() if k in p.cells})
    return p


def test_a_table_before_the_skill_menu_loads_and_its_menu_cells_are_dropped(tmp_path):
    table = _table(tmp_path, drop=("menu_scr", "menu_sel"))
    assert table.absent == {"menu_scr", "menu_sel"}
    known = _known()
    assert {"menu_scr", "menu_sel"} <= set(known), "known_pristine lost the menu cells"
    p = _probe_holding(table, known)
    assert p.absent == {"menu_scr", "menu_sel"} and not p.absent & set(p.cells)
    assert p.check_known(known) == []                      # every other known value is checked...
    assert "menu_scr" not in p.read_cells()
    wrong = dict(known, viewx=known["viewx"] + 1)
    assert [b[0] for b in p.check_known(wrong)] == ["viewx"]   # ...and still read


def test_a_table_with_the_skill_menu_probes_its_cells(tmp_path):
    table = _table(tmp_path)
    assert table.absent == frozenset()
    known = _known()
    p = _probe_holding(table, known)
    assert {"menu_scr", "menu_sel"} <= set(p.cells) and p.absent == frozenset()
    assert p.check_known(known) == []
    assert [b[0] for b in p.check_known(dict(known, menu_sel=known["menu_sel"] - 1))] == ["menu_sel"]


def test_only_the_skill_menu_is_optional(tmp_path):
    """R9: the optionality is exactly those two labels, and together -- a table without a REQUIRED
    label, or with one menu label and not the other, is still refused"""
    with pytest.raises(KeyError, match="has no"):
        _table(tmp_path, drop=("viewx",))
    with pytest.raises(KeyError, match="come together"):
        _table(tmp_path, drop=("menu_sel",))
    for one in ("dreq", "pcard", "wfired"):
        with pytest.raises(KeyError, match="come together"):
            _table(tmp_path, drop=(one,))
    assert P.OPTIONAL_LABELS == {"menu_scr", "menu_sel", "dreq", "pcard", "wfired"}


def test_a_table_before_p2a1_loads_and_its_door_cells_are_dropped(tmp_path):
    """M7 P2a.1: a binary before the rung (blocked33 and every baseline) has no dreq / pcard /
    wfired; the probe drops them, a pose that names them writes the rest"""
    table = _table(tmp_path, drop=("dreq", "pcard", "wfired"))
    assert table.absent == {"dreq", "pcard", "wfired"}
    known = _known()
    assert {"dreq", "pcard", "wfired"} <= set(known)
    p = _probe_holding(table, known)
    assert p.absent == {"dreq", "pcard", "wfired"} and p.check_known(known) == []
    p.write_cells(known)                                     # absent cells: nothing written
    assert [b[0] for b in p.check_known(dict(known, viewy=known["viewy"] + 1))] == ["viewy"]


def test_a_table_with_the_door_cells_probes_them(tmp_path):
    p = _probe_holding(_table(tmp_path), _known())
    assert p.check_known(_known()) == []
    assert [b[0] for b in p.check_known(dict(_known(), pcard=1))] == ["pcard"]
    assert [b[0] for b in p.check_known(dict(_known(), dreq=(0, 1, 0)))] == ["dreq"]
