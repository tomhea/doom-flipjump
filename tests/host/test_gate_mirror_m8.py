"""M8 (the gates' mirror on E1M2): the two hooks the gate harnesses read from the WORLD instead of re-deriving --
`monsters.door_keys_kw` (the yellow / red keys World._doors_phase asks for) and `MonsterPhase.walk_segs` (the segments
the world's own `_walkover` tested: a teleport's walk up to its line, nothing from the jump) -- and that on E1M1 both
are absent (the gates' calls are the ones they always were). The whole-mirror proof against World.tic, with its
negative controls, is scratchpad/gp/mirror_world_check.py --selftest."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from doomfj import gamedata as gd
from doomfj.monsters import MonsterPhase, door_keys_kw, walkover_segments
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
E1M1 = ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"
E1M2 = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
needs_e1m2 = pytest.mark.skipif(not E1M2.exists(), reason="needs tests/fixtures/freedoom_e1m2.wad")
M32 = 0xFFFFFFFF


def _phase(path, mapname):
    return MonsterPhase(WadFile.from_path(str(path)), mapname, gd.SK_HARD, mode="final", player="final")


def test_recorded_segments_replace_the_walk_end_ones():
    """a phase with `walk_segs` gives exactly those segments (in its ends' representation), walk_end or not; without
    them the P8a segments are unchanged"""
    old, new = (100 << 16, -416 << 16), (900 << 16, 50 << 16)          # a teleport: new is the destination
    seg = ((100 << 16, -416 << 16), (108 << 16, -416 << 16))
    ph = SimpleNamespace(walk_segs=[seg], walk_end=(new[0] & M32, new[1] & M32))
    assert walkover_segments(ph, old, new) == [seg]
    uold, unew = tuple(v & M32 for v in old), tuple(v & M32 for v in new)
    assert walkover_segments(ph, uold, unew) == [tuple(tuple(v & M32 for v in p) for p in seg)]
    assert walkover_segments(SimpleNamespace(walk_segs=[], walk_end=None), old, old) == []
    # control: without the record, the jump is one walk from the start to the destination (the bug L4 fixed)
    assert walkover_segments(SimpleNamespace(walk_end=None), old, new) == [(old, new)]


def test_e1m1_installs_nothing():
    """E1M1 has no teleport line: no recorder on the world, `walk_segs` None after a move, and no key kwargs"""
    ph = _phase(E1M1, "E1M1")
    assert "_walkover" not in vars(ph.world)
    ws = ph.world.ws
    ph.sync({si: (0, 0, 0, 0) for si in ph.world.door_order}, tuple((0, 0, 0, 0) for _ in ph.world.lift_order), 0)
    ph.move({"forward": True}, ws.px & M32, ws.py & M32, ws.pangle)
    assert ph.walk_segs is None
    ws.p_cards[gd.IT_BLUECARD] = 1
    assert door_keys_kw(ph) == {} and door_keys_kw(None) == {}


@needs_e1m2
def test_door_keys_are_the_worlds():
    """the yellow / red card (or skull) the world holds, and a blue skull; the blue card rides the gate's own state"""
    ph = _phase(E1M2, "E1M2")
    c = ph.world.ws.p_cards
    assert door_keys_kw(ph) == {}
    c[gd.IT_BLUECARD] = 1
    assert door_keys_kw(ph) == {}
    c[gd.IT_YELLOWCARD] = 1
    assert door_keys_kw(ph) == {"has_yellow": True}
    c[gd.IT_REDSKULL] = 1
    assert door_keys_kw(ph) == {"has_yellow": True, "has_red": True}
    c[gd.IT_BLUESKULL] = 1
    assert door_keys_kw(ph)["has_blue"] is True
    walker = MonsterPhase(WadFile.from_path(str(E1M2)), "E1M2", gd.SK_HARD, mode="idle", player="walk")
    walker.world.ws.p_cards[gd.IT_YELLOWCARD] = 1
    assert door_keys_kw(walker) == {}                  # a player who takes nothing: no card is the world's


@needs_e1m2
def test_a_teleport_records_the_walk_up_to_the_line():
    """E1M2's line 126 (x = 2816, front x > 2816): the player in the closet with his box over the pad, its monsters
    cleared, walks west over the line -- the move lands on the destination, and the one segment recorded is the walk
    from the start to the candidate past the line"""
    ph = _phase(E1M2, "E1M2")
    w, ws = ph.world, ph.world.ws
    tel = next(t for t in w.teleports if t.line == 126)
    assert not tel.front_le and tel.axis == "x"
    for m in range(w.layout.nmon):
        if abs(ws.mon_x[m] - 2826) <= 96 and abs(ws.mon_y[m] - 160) <= 96:
            ws.mon_active[m] = 0
    x16, y16, ang = 2826 << 16, 160 << 16, 0x80000000
    ph.sync({si: (0, 0, 0, 0) for si in w.door_order}, tuple((0, 0, 0, 0) for _ in w.lift_order),
            (0,) * (2 * len(w.floor_groups)))                # M8 F1.3: E1M2's fswitch vector, every group still
    nx, ny, na = ph.move({"forward": True}, x16, y16, ang)
    assert (nx, ny) == ((tel.dest[0] << 16) & M32, (tel.dest[1] << 16) & M32) and ws.p_reaction
    assert len(ph.walk_segs) == 1
    (a, b), = ph.walk_segs
    assert a == (x16, y16) and b[1] == y16 and b[0] < tel.coord << 16 < a[0]
    assert walkover_segments(ph, (x16, y16), (nx, ny)) == [(a, b)]


def _movers(path, mapname):
    from doomfj.movers import MoverPhase
    mw = WadFile.from_path(str(path))
    return MoverPhase(mw.sectors(mapname), mw.linedefs(mapname), mw.sidedefs(mapname), mw.vertexes(mapname))


def test_e1m1_keeps_its_one_switch_cell():
    """E1M1: the narrow layout -- the mirror's `switched` is one scalar, the world's f_switch a 1-bit scalar"""
    mp = _movers(E1M1, "E1M1")
    ph = _phase(E1M1, "E1M1")
    assert not mp.wide and not ph.world.floor_wide and mp.initial()[2] == 0 and ph.world.ws.f_switch == 0


@needs_e1m2
def test_the_fswitch_vector_is_the_worlds():
    """M8 F1.3 (E1M2's wide layout): the mirror's `switched` is the fswitch VECTOR -- each floor group's state, then
    its step timer -- and a group fired in the mirror (MoverPhase.use_press / after_move) is the vector the World's own
    `floor_fire` makes; `MonsterPhase.sync` writes it into the world's f_switch / f_sub as it is"""
    mp = _movers(E1M2, "E1M2")
    ph = _phase(E1M2, "E1M2")
    w = ph.world
    ng = len(mp.groups)
    assert mp.wide and w.floor_wide and mp.initial()[2] == (0,) * (2 * ng)
    for g, box in mp.floor_use:
        x16, y16 = ((box[0] + box[2]) // 2) << 16, ((box[1] + box[3]) // 2) << 16
        st = mp.use_press(mp.initial(), x16, y16)
        w.reset(gd.SK_HARD)
        w.floor_fire(g)
        assert st[2] == tuple(w.ws.f_switch) + tuple(w.ws.f_sub), g
        st = mp.tic(st)
        w._movers_phase(None)
        assert st[2] == tuple(w.ws.f_switch) + tuple(w.ws.f_sub), g
        w.reset(gd.SK_HARD)
        ph.sync({si: (0, 0, 0, 0) for si in w.door_order}, st[0], st[2])
        assert tuple(w.ws.f_switch) + tuple(w.ws.f_sub) == st[2]
