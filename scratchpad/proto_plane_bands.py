"""M13pS2a prototype (host-only, no fj) -- validate the LS2 band-list algorithm: for a given
planeheight `ph`, build the per-window zidx BAND LIST via ONE reciprocal(ph) + a per-row THRESHOLD
WALK (additions + compares only, no per-row wide multiply), and compare its expanded per-row zidx
sequence against the EXACT `_plane_pixel` formula (ph*yslope[y] >> 36, clamped 127) across every real
E1M1 planeheight value. Reports the max row-shift so we know, before touching any oracle/fj code,
whether the plan's "<=1 row" F4 acceptance bound actually holds.

Run: python scratchpad/proto_plane_bands.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doomfj.config import Config
from doomfj.fixedpoint import fixed_mul
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
YSLOPE = rm.yslope   # 100-entry 16.16 table, view_h rows


def exact_zidx(ph, y):
    dist = fixed_mul(ph, YSLOPE[y], 8, 4)
    return min(127, dist >> 20)


def approx_band_list(ph, rows):
    """rows: an iterable of row indices in EMISSION order (increasing y). Returns [(run, zidx), ...].
    Handles BOTH monotonic directions (ceiling: yslope increasing; floor: yslope decreasing). The
    FIRST row's zidx is seeded EXACTLY (one real fixed_mul, matching _plane_pixel bit-for-bit -- paid
    ONCE per window, not per row); every SUBSEQUENT row advances via the recip-based STEP (add/compare
    only, no per-row multiply)."""
    rows = list(rows)
    if not rows:
        return []
    if ph == 0:
        return [(len(rows), 0)]
    recip = ReferenceModel._recip_div32(ph)     # (1<<32)//ph, block-FP (shared perf #11 table)
    step = 16 * recip                            # yslope delta per zidx bucket: (1<<36)/ph
    y0 = rows[0]
    ys0 = YSLOPE[y0]
    zidx = exact_zidx(ph, y0)                     # ONE exact eval to seed the first row's bucket
    # direction: does ys increase or decrease as rows advances? (ceiling vs floor window)
    ascending = len(rows) < 2 or YSLOPE[rows[1]] >= ys0
    threshold_hi = step * (zidx + 1)              # crossing this (from below) -> zidx+1
    threshold_lo = step * zidx                    # crossing this (from above) -> zidx-1
    bands = []
    for y in rows:
        ys = YSLOPE[y]
        if ascending:
            while zidx < 127 and ys >= threshold_hi:
                zidx += 1
                threshold_hi += step
        else:
            while zidx > 0 and ys < threshold_lo:
                zidx -= 1
                threshold_lo -= step
        if bands and bands[-1][1] == zidx:
            bands[-1][0] += 1
        else:
            bands.append([1, zidx])
    return [(c, z) for c, z in bands]


def expand(bands):
    out = []
    for count, zidx in bands:
        out += [zidx] * count
    return out


def worst_shift(ph, rows):
    """max |approx_zidx(y) - exact_zidx(y)| over rows, plus how many rows differ at all."""
    approx = expand(approx_band_list(ph, rows))
    exact = [exact_zidx(ph, y) for y in rows]
    diffs = [a - e for a, e in zip(approx, exact)]
    return max(abs(d) for d in diffs), sum(1 for d in diffs if d != 0), len(rows)


def real_e1m1_planeheights():
    """The ACTUAL |ceil_h<<16 - viewz| / |floor_h<<16 - viewz| values the E1M1 spawn frame's real
    render_wall_frame loop computes (every claimed seg's sector, at the real spawn viewz) -- not an
    arbitrary cross-product (an earlier version of this prototype used a synthetic
    sector-x-sector cross product and hit spurious 32-bit FixedMul WRAPAROUND at implausible
    planeheight/viewz combinations that never occur in a real frame; extracting the real per-frame
    values avoids chasing a non-issue)."""
    from doomfj.wad import WadFile as WF
    from doomfj.reference_model import spawn_state, build_scene
    mw = WF.from_path("tests/fixtures/freedoom_e1m1.wad")
    aw = WF.from_path("tests/fixtures/freedoom_assets.wad")
    scene = build_scene(mw, aw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    from doomfj.fixedpoint import _signed
    lds = mw.linedefs("E1M1")
    sds = mw.sidedefs("E1M1")
    secs = mw.sectors("E1M1")
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


def main():
    ceil_rows = range(0, cfg.CENTERY)               # ascending, yslope increasing
    floor_rows = range(cfg.CENTERY, cfg.VIEW_H)      # ascending y, yslope DEcreasing

    phs = real_e1m1_planeheights()
    print(f"testing {len(phs)} real E1M1-derived planeheights x 2 windows")
    worst = (0, 0, "")
    total_shifted_rows = 0
    total_rows = 0
    for ph in phs:
        for name, rows in (("ceil", ceil_rows), ("floor", floor_rows)):
            shift, nshifted, n = worst_shift(ph, rows)
            total_shifted_rows += nshifted
            total_rows += n
            if shift > worst[0]:
                worst = (shift, ph, name)
    print(f"max |approx-exact| zidx shift across all samples: {worst[0]} (ph={worst[1]}, window={worst[2]})")
    print(f"rows differing from exact: {total_shifted_rows}/{total_rows} "
          f"({100*total_shifted_rows/total_rows:.2f}%)")

    # also a synthetic sweep over REALISTIC world heights (DOOM sector heights rarely exceed a few
    # thousand map units -- E1M1 itself maxes at 495; a wider sweep hits 32-bit FixedMul WRAPAROUND
    # at implausible ph values, which is a pre-existing property of the EXACT renderer too, not
    # something this rung needs to solve)
    synth = [h << 16 for h in range(1, 4096, 37)]
    worst2 = (0, 0, "")
    for ph in synth:
        for name, rows in (("ceil", ceil_rows), ("floor", floor_rows)):
            shift, _, _ = worst_shift(ph, rows)
            if shift > worst2[0]:
                worst2 = (shift, ph, name)
    print(f"max shift over synthetic sweep ({len(synth)} values): {worst2[0]} (ph={worst2[1]}, window={worst2[2]})")


if __name__ == "__main__":
    main()
