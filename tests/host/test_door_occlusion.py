"""M2 — A SHUT DOOR MUST OCCLUDE THE ROOM BEHIND IT.

M2 shipped marked DONE on a gate that could not have caught this. The gate proved the fj program
and the oracle agree byte for byte, which they did — while BOTH drew a door you could see straight
through. Agreement is not correctness, and the shut-door property had no test of its own until the
owner played the game and said "with a closed door I can see through it".

THE MEASUREMENT. Perturb ONLY the room on the far side of a shut door. If the door occludes, the
frame is bit-identical: nothing beyond it can reach the screen. Every differing pixel is a pixel
that leaked through a closed door. This cannot be satisfied by painting a slab over the doorway —
the earlier attempt that did exactly that still leaked the far room's floor underneath it.

⚠ TWO WAYS TO MAKE THIS TEST LIE, both of which have happened here:
  * PERTURB THE WRONG SECTOR. A door's linedefs both carry the DOOR on their back side, so
    `sds[ld.back].sector` is the door, not the room beyond. Perturbing it moves the shut door's
    own ceiling from one shut position to another, and the test passes on a glass door.
    `doorcode.door_rooms` is the SSOT for which sector is actually behind a door.
  * PERTURB SOMETHING INVISIBLE. A probe nothing can see reports zero leak for a glass door too,
    so the same perturbation is also measured with the door OPEN and REQUIRED to be large. That
    open-door number is the test's own control: it is what a non-occluding door would score.

`scratchpad/12m/leakcheck.py` runs this over every door and viewpoint; this pins the property in
the suite, on one door, at a cost the default test run can afford.
"""
import math

import pytest

from doomfj.config import Config
from doomfj.doorcode import door_line_ids, door_rooms
from doomfj.doors import door_states
from doomfj.mapcompiler import _point_side, bake_bsp
from doomfj.reference_model import ReferenceModel, Scene, SimState
from doomfj.wad import WadFile

E1M1 = "tests/fixtures/freedoom_e1m1.wad"
STANDOFF = 128          # map units back from the door line
RENDER = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
              near_steps=True, stack_steps=True, degrade=True)


@pytest.fixture(scope="module")
def level():
    mw = WadFile.from_path(E1M1)
    cmap = bake_bsp(mw, "E1M1")
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    tbl = door_states(secs, lds, sds)
    topo = door_rooms(lds, sds, tbl, door_line_ids(secs, lds, sds, tbl))
    return mw, cmap, secs, lds, sds, tbl, topo


def _sector_of_point(rm, cmap, lds, sds, x, y):
    """The sector index map point (x, y) stands in: BSP leaf -> first seg -> that seg's front
    sector. Same rule as `mapcompiler.seg_sector`, applied to an index rather than an object."""
    ss = cmap.subsectors[rm.point_in_subsector(cmap, x, y)]
    if ss.numsegs <= 0:
        return None
    ld = lds[cmap.segs[ss.firstseg].linedef]
    side = ld.front if cmap.segs[ss.firstseg].side == 0 else ld.back
    return None if side == -1 else sds[side].sector


def _viewpoint(rm, cmap, lds, sds, li, door_sec, far):
    """Stand `STANDOFF` units off the door line, on the side its FRONT sidedef faces, looking at it.

    The side comes from `mapcompiler._point_side` (DOOM's right = front) rather than from a winding
    rule restated here, and BSP point location then rejects a spot that has wandered into the door
    sector or into the very room the test perturbs. Returns None when neither side qualifies."""
    ld = lds[li]
    v1, v2 = cmap.vertexes[ld.v1], cmap.vertexes[ld.v2]
    dx, dy = v2[0] - v1[0], v2[1] - v1[1]
    mx, my = (v1[0] + v2[0]) / 2.0, (v1[1] + v2[1]) / 2.0
    nl = (dx * dx + dy * dy) ** 0.5 or 1.0
    nx, ny = -dy / nl, dx / nl
    for sgn in (1.0, -1.0):
        px, py = int(mx + sgn * nx * STANDOFF), int(my + sgn * ny * STANDOFF)
        if _point_side(v1[0], v1[1], dx, dy, px, py) >= 0:
            continue
        if _sector_of_point(rm, cmap, lds, sds, px, py) in set(far) | {door_sec}:
            continue
        ang = int(math.atan2(my - py, mx - px) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
        return px, py, ang
    return None


def _perturb(secs, base, far):
    """Move the far rooms' floor and ceiling while keeping each room OPEN — a perturbation that
    shuts the far room would hide itself and read as 'no leak'."""
    out = dict(base)
    for fs in far:
        fh, ch = out.get(fs, (secs[fs].floor_h, secs[fs].ceil_h))
        room = ch - fh
        out[fs] = (fh + min(8, max(0, room // 4)), ch - min(40, max(0, room // 2)))
    return out


def _leak_and_probe(level, door):
    """(pixels that leak through the SHUT door, pixels the same perturbation moves when OPEN)."""
    mw, cmap, secs, lds, sds, tbl, topo = level
    rm = ReferenceModel(Config())
    shut = {si: (secs[si].floor_h, tbl[si][0]) for si in tbl}
    opn = dict(shut)
    opn[door] = (secs[door].floor_h, tbl[door][-1])

    def frame(st, heights):
        return rm.render_wall_frame(
            st, Scene(mw, mw, "E1M1", cmap, heights, frozenset()), **RENDER)

    leak = probe = views = 0
    for li, _near, far in topo[door]:
        if not far:
            continue
        vp = _viewpoint(rm, cmap, lds, sds, li, door, far)
        if vp is None:
            continue
        px, py, ang = vp
        st = SimState(x=px << 16, y=py << 16, angle=ang, level="E1M1")
        views += 1
        leak += sum(1 for a, b in zip(frame(st, shut), frame(st, _perturb(secs, shut, far)))
                    if a != b)
        probe += sum(1 for a, b in zip(frame(st, opn), frame(st, _perturb(secs, opn, far)))
                     if a != b)
    return leak, probe, views


def _first_measurable_door(level):
    _mw, _cmap, _secs, _lds, _sds, _tbl, topo = level
    for si in sorted(topo):
        if any(far for _li, _near, far in topo[si]):
            return si
    pytest.fail("no door on this map has a room behind it to perturb")


# ── the topology this rests on ──────────────────────────────────────────────────────────────

def test_a_doors_back_sidedef_is_the_door_itself_not_the_room_behind(level):
    """The mistake the occlusion test must not repeat. If this ever fails, `door_rooms` is
    describing a different kind of map and the perturbation target has to be rethought."""
    _mw, _cmap, _secs, lds, sds, tbl, topo = level
    backs = {sds[lds[li].back].sector for si in topo for li, _n, _f in topo[si]}
    assert backs and backs <= set(tbl), sorted(backs - set(tbl))


def test_the_room_behind_a_door_is_never_the_door(level):
    _mw, _cmap, _secs, _lds, _sds, _tbl, topo = level
    for si in topo:
        for _li, _near, far in topo[si]:
            assert si not in far, (si, far)


# ── the property ────────────────────────────────────────────────────────────────────────────

def test_a_shut_door_occludes_the_room_behind_it(level):
    """Nothing beyond a shut door may reach the screen — not the far floor, not the far ceiling,
    not one pixel. `probe` is the control: it is the score a door you can see through would get."""
    door = _first_measurable_door(level)
    leak, probe, views = _leak_and_probe(level, door)
    assert views > 0, "no usable viewpoint -- the assertions below would pass vacuously"
    assert probe > 200, (
        "the perturbation is invisible even with the door OPEN (%d px), so a leak of 0 would "
        "prove nothing about occlusion" % probe)
    assert leak == 0, (
        "%d px leaked through shut door %d across %d viewpoint(s); the same perturbation moves "
        "%d px with the door open" % (leak, door, views, probe))
