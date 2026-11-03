"""M8 C2 (docs/c2-slot-ids.md): the slot-id width -- derived from the counts, named by the map's Config, refused at
emission on a mismatch; the narrow maps' schema and dispatch text exactly the old ones. Each with its control (R9)."""
from types import SimpleNamespace

import pytest

from doomfj import config as C
from doomfj.monstercode import id_jump_lines
from doomfj.wall_renderer import check_slot_bits
from doomfj.world import SLOT_IDS_NARROW, World, _code_bits, _index_bits, aim_bits, slot_nibbles
from tests.fj.wide_maps import ASSET, map_world


def _lay(nmon, nbar, nshot=0):
    return SimpleNamespace(nmon=nmon, nbarrel=nbar, nshot=nshot)


def test_the_width_is_derived_from_the_counts():
    assert slot_nibbles(_lay(SLOT_IDS_NARROW - 7, 7)) == 2
    assert slot_nibbles(_lay(SLOT_IDS_NARROW - 6, 7)) == 3          # control: one slot more is three nibbles
    assert slot_nibbles(_lay(294, 7)) == 3 and aim_bits(_lay(294, 7)) == 12
    with pytest.raises(AssertionError):                            # a GR shot line's id would meet a monster's
        aim_bits(_lay(294, 7, nshot=1))


def _old_tree(reg, n, target, none, lab):
    """the two-level text every dispatch had before C2 (ids 0 .. n-1)"""
    nh = (n + 15) // 16
    out = ["    hex.switch %s + 1*dw, " % reg + ", ".join(lab % h if h < nh else none for h in range(16))]
    for h in range(nh):
        out += ["  %s:" % (lab % h), "    hex.switch %s, " % reg + ", ".join(
            target(16 * h + k) if 16 * h + k < n else none for k in range(16))]
    return out


@pytest.mark.parametrize("n", (1, 16, 17, 76, 139, 255, 256))
def test_the_narrow_tree_is_the_old_text(n):
    t = lambda i: "s%d" % i                                         # noqa: E731
    assert id_jump_lines("r", 2, n, t, "x", "h%d", "g%d") == _old_tree("r", n, t, "x", "h%d")
    wide = id_jump_lines("r", 3, n, t, "x", "h%d", "g%d")
    assert wide != _old_tree("r", n, t, "x", "h%d")                 # control: the wide tree is another text
    assert wide[0] == "    hex.switch r + 2*dw, g0, " + ", ".join(["x"] * 15)


def test_the_narrow_schema_keeps_the_old_widths():
    """E1M1's slot fields at the formulas every frozen digest was recorded with; CONTROL: E1M6's are 12 bits"""
    w = World(monsters="final", player="final")
    lay, f = w.layout, {x.name: x.bits for x in w.schema}
    mb = _index_bits(lay.nmon)
    assert slot_nibbles(lay) == 2
    assert f["sched_cursor"] == max(5, mb) and f["proj_src"] == mb and f["p_attacker"] == _index_bits(lay.nmon + 1)
    assert f["mon_target"] == _code_bits(lay.nmon) and f["bar_src"] == _code_bits(lay.nmon)
    assert f["aim_sid"] == max(7, (lay.nmon + lay.nbarrel).bit_length()) and f["p_killcount"] == 8
    if not ASSET.exists():
        pytest.skip("the wide control needs assets/freedoom1.wad")
    w6 = map_world("E1M6", monsters="final", player="final")
    f6 = {x.name: x.bits for x in w6.schema}
    assert all(f6[k] == 12 for k in ("sched_cursor", "proj_src", "p_attacker", "mon_target", "bar_src", "aim_sid",
                                     "p_killcount", "p_itemcount")), {k: f6[k] for k in f6 if k in (
        "sched_cursor", "proj_src", "p_attacker", "mon_target", "bar_src", "aim_sid", "p_killcount")}


def test_the_emitter_refuses_a_map_without_its_width(monkeypatch):
    """E1M6's counts with its MAP_CONFIG entry: 3 nibbles; CONTROL: the entry's SLOT_ID_BITS removed -- refused, and a
    narrow map whose entry claimed 12 bits refused too"""
    assert check_slot_bits(C.Config(), "E1M6", _lay(294, 7)) == 3
    assert check_slot_bits(C.Config(), "E1M1", _lay(53, 22)) == 2
    monkeypatch.setitem(C.MAP_CONFIG, "E1M6", {k: v for k, v in C.MAP_CONFIG["E1M6"].items() if k != "SLOT_ID_BITS"})
    with pytest.raises(AssertionError, match="SLOT_ID_BITS"):
        check_slot_bits(C.Config(), "E1M6", _lay(294, 7))
    monkeypatch.setitem(C.MAP_CONFIG, "E1M1", dict(C.MAP_CONFIG["E1M1"], SLOT_ID_BITS=12))
    with pytest.raises(AssertionError, match="SLOT_ID_BITS"):
        check_slot_bits(C.Config(), "E1M1", _lay(53, 22))
