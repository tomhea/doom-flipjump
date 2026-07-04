"""M13pS2a (LS2) -- `ReferenceModel._zidx_band_walk`: the per-row distance-bucket (zidx) walk that
replaces a per-pixel FixedMul with ONE exact seed + a cheap threshold walk (the reciprocal(planeheight)
step). This is the arithmetic the future fj column-stream band-list emitter (pS2c) will mirror -- these
tests pin its correctness and its accepted approximation bound (<=1 row shift vs the always-exact
per-pixel formula) BEFORE it is wired into any renderer or oracle output.

Not yet consumed by `_render_planes_flat` (still exact, byte-identical to the shipped flat goldens and
the current row-major fj kernel) -- see the docstring on `_render_planes_flat` for why the wiring waits
for the fj-side replacement to land in the same rung.
"""
from doomfj.config import Config
from doomfj.fixedpoint import _signed, fixed_mul
from doomfj.reference_model import ReferenceModel, build_scene, spawn_state
from doomfj.wad import WadFile

E1M1 = "tests/fixtures/freedoom_e1m1.wad"


def _exact_zidx(rm, ph, y):
    dist = fixed_mul(ph, rm.yslope[y], 8, 4)
    return min(127, dist >> 20)


def _real_e1m1_planeheights(rm):
    """Every |ceil_h<<16 - viewz| / |floor_h<<16 - viewz| the E1M1 spawn frame's real render loop
    actually computes (every claimed seg's sector) -- not an arbitrary cross product, which hits
    32-bit FixedMul wraparound at planeheight/viewz combinations no real frame ever produces."""
    mw = WadFile.from_path(E1M1)
    scene = build_scene(mw, mw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
    verts = scene.cmap.vertexes
    px, py = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    pss = scene.cmap.subsectors[rm.point_in_subsector(scene.cmap, px, py)]
    viewz = rm.view_z(rm._seg_sector(lds, sds, secs, scene.cmap.segs[pss.firstseg]).floor_h)
    phs = set()
    for seg_i in rm.visible_segs(scene.cmap, px, py):
        seg = scene.cmap.segs[seg_i]
        ld = lds[seg.linedef]
        if ld.back != -1:
            continue
        rng = rm.wall_x_range(sp.x, sp.y, sp.angle, seg, verts)
        if rng is None:
            continue
        sec = rm._seg_sector(lds, sds, secs, seg)
        phs.add(abs((sec.ceil_h << 16) - viewz))
        phs.add(abs((sec.floor_h << 16) - viewz))
    return sorted(x for x in phs if x > 0)


def test_single_row_window_is_byte_identical_to_the_exact_formula():
    """A 1-row window has no room to walk -- it must be the SAME exact seed every time (the fj span
    kernel, which only ever asks for ONE row per call, would see zero drift if it called this)."""
    rm = ReferenceModel()
    for ph in (1, 100 << 16, 6553600, 32440320):
        for y in (0, 25, 49, 50, 75, 99):
            assert rm._zidx_band_walk(ph, [y]) == [_exact_zidx(rm, ph, y)]


def test_zero_planeheight_is_a_single_flat_band():
    rm = ReferenceModel()
    assert rm._zidx_band_walk(0, [0, 1, 2, 3]) == [0, 0, 0, 0]


def test_empty_window_returns_empty():
    rm = ReferenceModel()
    assert rm._zidx_band_walk(12345, []) == []


def test_ceiling_and_floor_windows_walk_the_correct_monotonic_direction():
    """Ceiling (y ascending toward the horizon) -> zidx non-decreasing. Floor (y ascending AWAY from
    the horizon) -> zidx non-increasing. Mirrors yslope's own peak-at-horizon shape."""
    rm = ReferenceModel()
    ph = 6553600  # 100 world units, comfortably inside E1M1's real range
    ceil_rows = list(range(0, Config().CENTERY))
    floor_rows = list(range(Config().CENTERY, Config().VIEW_H))
    ceil_z = rm._zidx_band_walk(ph, ceil_rows)
    floor_z = rm._zidx_band_walk(ph, floor_rows)
    assert all(b >= a for a, b in zip(ceil_z, ceil_z[1:]))
    assert all(b <= a for a, b in zip(floor_z, floor_z[1:]))


def test_matches_exact_within_one_row_across_every_real_e1m1_planeheight():
    """The ledger's F4 acceptance bound, MEASURED (not assumed): across every planeheight the real
    E1M1 spawn frame actually computes, the band-walk's per-row zidx differs from the always-exact
    per-pixel formula by at most 1 bucket, and only for a small minority of rows."""
    rm = ReferenceModel()
    ceil_rows = list(range(0, Config().CENTERY))
    floor_rows = list(range(Config().CENTERY, Config().VIEW_H))
    phs = _real_e1m1_planeheights(rm)
    assert len(phs) >= 20   # sanity: this is exercising real per-seg data, not an empty list
    max_shift = 0
    shifted, total = 0, 0
    for ph in phs:
        for rows in (ceil_rows, floor_rows):
            approx = rm._zidx_band_walk(ph, rows)
            exact = [_exact_zidx(rm, ph, y) for y in rows]
            for a, e in zip(approx, exact):
                d = abs(a - e)
                max_shift = max(max_shift, d)
                total += 1
                shifted += d != 0
    assert max_shift <= 1, f"F4 bound violated: max shift {max_shift} > 1 row"
    assert shifted / total < 0.10, f"too many rows drifted: {shifted}/{total}"
