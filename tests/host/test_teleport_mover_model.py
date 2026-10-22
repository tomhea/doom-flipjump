"""M8 C5b -- a teleport whose DESTINATION sector moves (E1M7: 516 -> sector 89, lowered by W1 36 line 4272, tag 60;
521 -> sector 88). DOOM's P_TeleportMove: floorz = the destination subsector's sector floor NOW, z = floorz. The model
(world._teleport_monster) reads `secs_c`, the movers where they stand; the survey's row
(`level_survey.teleport_mover_destinations`) lists such lines on every map. tests/fj/test_teleport_mover_fj RUNS the fj.

Controls: the stored floor (`Teleporter.dest_floor`) is what the pre-C5b rule took -- it parts once the mover left; a
door destination is still refused (and listed as REFUSED by the survey).
"""
import dataclasses
import importlib.util
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj.wad import WadFile
from doomfj.world import World
from tests.fixtures.map_variants import episode_wad

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")
DEST = {516: 89, 521: 88}


@pytest.fixture(scope="module")
def art():
    return WadFile.from_path(str(ART))


@pytest.fixture(scope="module")
def ls():
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts" / "level_survey.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def w(art):
    w = World(episode_wad(art, "E1M7"), "E1M7", skill=gd.SK_HARD, player="final", monsters="final")
    ws = w.ws
    for k in range(w.layout.nmon):
        if ws.mon_active[k]:
            w._list_remove(k, ws.mon_leaf[k])
        ws.mon_active[k] = ws.mon_shootable[k] = ws.mon_solid[k] = 0
    ws.px, ws.py = 30000 << 16, 30000 << 16
    return w


def _cross(w, line):
    tel = [t for t in w.teleports if t.line == line][0]
    m = [k for k in range(w.layout.nmon) if w.mon_radius[k] == 20][0]
    ws, mid = w.ws, (tel.lo + tel.hi) // 2
    a, b = (tel.coord - 4, tel.coord + 4) if tel.front_le else (tel.coord + 4, tel.coord - 4)
    (ox, oy), (nx, ny) = ((a, mid), (b, mid)) if tel.axis == "x" else ((mid, a), (mid, b))
    ws.mon_x[m], ws.mon_y[m] = nx, ny
    ws.mon_active[m] = ws.mon_shootable[m] = 1
    w._teleported = False
    assert w._teleport_monster(m, ox, oy, nx, ny) == tel.dest and w._teleported
    ws.mon_active[m] = ws.mon_shootable[m] = 0
    return tel, ws.mon_floorz[m]


def _set_group(w, sector, state):
    g = [k for k, grp in enumerate(w.floor_groups) if sector in grp.sectors][0]
    w.ws.f_switch[g], w.ws.f_sub[g] = state, 0
    w._door_phase_scene()
    return w.floor_groups[g].n


def test_the_world_builds_e1m7_and_marks_both_mover_destinations(w):
    assert sorted(t.line for t in w.teleports if t.dest_moves) == sorted(DEST)
    for t in w.teleports:
        assert t.dest_moves == (t.dest_sector in w.mover_order)


@pytest.mark.parametrize("line", sorted(DEST))
def test_a_teleport_lands_on_the_movers_floor_now(w, line):
    sector = DEST[line]
    n = _set_group(w, sector, 0)
    tel, z0 = _cross(w, line)
    assert z0 == tel.dest_floor                                  # at the level start: the stored floor
    moved = 0
    for s in range(1, n):
        _set_group(w, sector, s)
        _tel, z = _cross(w, line)
        assert z == w.secs_c[sector].floor_h
        moved += z != tel.dest_floor                             # control: the stored floor parts here
    _set_group(w, sector, 0)
    assert moved, "the mover never left the stored floor: the test proves nothing"


def test_control_a_door_destination_is_still_refused(art, w, monkeypatch):
    import doomfj.teleport as TP
    door, real = w.door_order[0], TP.teleporters
    monkeypatch.setattr(TP, "teleporters",
                        lambda *a, **k: [dataclasses.replace(t, dest_sector=door) for t in real(*a, **k)])
    with pytest.raises(AssertionError, match="is a door"):
        World(episode_wad(art, "E1M7"), "E1M7", player="final", monsters="final")


def test_the_survey_lists_mover_and_door_destinations(ls, art, w):
    rows = ls.teleport_mover_destinations(w.secs, w.lds, w.sds, w.teleports)
    assert sorted(rows["mover"]) == sorted(DEST.items()) and rows["door"] == []
    # control: a destination moved onto a door is listed as one, and a still sector as neither
    door = w.door_order[0]
    fake = [dataclasses.replace(t, dest_sector=door) for t in w.teleports[:1]]
    still = [t for t in w.teleports if not t.dest_moves][:1]
    assert ls.teleport_mover_destinations(w.secs, w.lds, w.sds, fake)["door"] == [(fake[0].line, door)]
    assert ls.teleport_mover_destinations(w.secs, w.lds, w.sds, still) == {"mover": [], "door": []}
