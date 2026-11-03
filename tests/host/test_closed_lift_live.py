"""M8 C11 (E1M7): a lift STORED CLOSED (floor >= ceiling) is inhabitable once it lowers -- `thing_live_subsectors`
must ask the map with it lowered (`wall_renderer.closed_lifts_lowered`), or the walk prune drops its leaves.

E1M7's emission refused: "thing_live_subsectors says subsectors [445] are uninhabitable, yet E1M7 spawns drawable
things in them: [(2047, 1528, 2112)]" -- an energy cell on the secret lift 274 (SR 123, floor = ceiling = 128). The
union asked by the prune took the doors open and the floor groups lowered, never the lifts.

What must not move: E1M1 and E1M2 have no closed lift (the map comes back unchanged: their emission is the same), and
the bbox wedge gate -- computed by the ORACLE from the frame's sectors -- is the same set of boxes with or without the
closed lifts' leaves on E1M1, E1M2 and E1M7 (so the mirrors' gates still agree to the node).

R9: without the lowering, E1M7's leaf 445 is uninhabitable while a thing spawns in it (the emitter's refusal).
"""
from pathlib import Path

import pytest

from doomfj import doors, movers
from doomfj.mapcompiler import bake_bsp, bbox_gate_boxes, thing_live_subsectors
from doomfj.reference_model import apply_sector_heights
from doomfj.wad import WadFile
from doomfj.wall_renderer import closed_lifts_lowered

ROOT = Path(__file__).resolve().parents[2]
FULL = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not FULL.exists(), reason="the full episode wad is not present")


@pytest.fixture(scope="module")
def wad():
    return WadFile.from_path(str(FULL))


def _open(secs, lds, sds):
    """the emitter's union before C11: doors open, floor groups lowered"""
    dst = doors.door_states(secs, lds, sds)
    opened = apply_sector_heights(secs, doors.heights_for_states(secs, lds, sds,
                                                                 {si: len(v) - 1 for si, v in dst.items()}))
    flow = {si: (min(h), secs[si].ceil_h) for g in movers.floor_groups(secs, lds, sds) for si, h in g.heights
            if min(h) < secs[si].floor_h}
    return apply_sector_heights(opened, flow) if flow else opened


@pytest.mark.parametrize("m", ["E1M1", "E1M2"])
def test_no_closed_lift_no_change(wad, m):
    secs, lds, sds = wad.sectors(m), wad.linedefs(m), wad.sidedefs(m)
    so = _open(secs, lds, sds)
    assert closed_lifts_lowered(secs, lds, sds, so) is so


def test_e1m7_lift_274_is_live(wad):
    m = "E1M7"
    secs, lds, sds = wad.sectors(m), wad.linedefs(m), wad.sidedefs(m)
    cm = bake_bsp(wad, m)
    so = _open(secs, lds, sds)
    before = thing_live_subsectors(cm, lds, sds, so)
    after = thing_live_subsectors(cm, lds, sds, closed_lifts_lowered(secs, lds, sds, so))
    assert 445 not in before and 445 in after                       # R9: the refusal's leaf, without and with
    assert before <= after
    assert any((t.x, t.y, t.type) == (1528, 2112, 2047) for t in wad.things(m))


@pytest.mark.parametrize("m", ["E1M1", "E1M2", "E1M7"])
def test_the_bbox_gate_is_unchanged(wad, m):
    secs, lds, sds = wad.sectors(m), wad.linedefs(m), wad.sidedefs(m)
    cm = bake_bsp(wad, m)
    so = _open(secs, lds, sds)
    a = bbox_gate_boxes(cm, thing_subsectors=thing_live_subsectors(cm, lds, sds, so))
    b = bbox_gate_boxes(cm, thing_subsectors=thing_live_subsectors(cm, lds, sds, closed_lifts_lowered(secs, lds, sds, so)))
    assert a == b
