"""dead_eye_census.py -- M7 P8a (package A): the ORACLE at every eye height the dying view reaches.

    python scratchpad/gp/dead_eye_census.py [--drops 1,17,34,35] [--angles 8] [--per-class 2] [--selftest]

The renderer was only ever asked for eyes at floor + 41. The dying view (docs/gp-final-plan.md 1.1, S0) sinks the
geometry to floor + 6 while the planes keep the standing eye's band lists. Before any fj is trusted with that, the
SPEC must be shown to stand there: for EVERY eye class of E1M1 (a leaf's view_z, the class the fj's landing selects
-- the static floors and each lift at each of its stops, `movers.lift_states`), `--per-class` leaves of that class
(a point inside each: its segs' vertex centroid, kept only if point_in_subsector returns the leaf), at each drop d and
`--angles` view angles, the game tier's oracle call (GAME_RENDER_KW, its sprites and the boot skill's hidden set)
with `view_drop=d` must
  (1) return a frame -- no assertion, no exception anywhere in render_wall_frame;
  (2) shade every plane with ph != 0 (ph = |plane_h - viewz| as `_flat_row_colours` receives it: under S0 the
      STANDING eye's, so a 0 would be a plane exactly at a standing eye -- the band walk's degenerate case);
  (3) MOVE the picture against view_drop 0 on some angle of every class (else the class never sank: vacuous).
PASS = (1) and (2) everywhere and (3) for every class.

--selftest (R9, docs/cr-rules.md): the census must REJECT two broken oracles --
  * "bands from the sunk eye" (the S0 split removed for the planes: `_render_planes_flat` handed viewz - (d << 16)):
    some plane then sits exactly at a sunk eye (a 24-unit step at d = 17), so (2) must fire;
  * "an assert below the eye": `wall_screen_span` raising when its eye is below floor + 41 -- (1) must fire.
Each must make the census FAIL; the selftest passes only if both do.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

from doomfj.reference_model import GAME_RENDER_KW, VIEW_DROP_MAX, SimState   # noqa: E402

DEFAULT_DROPS = (1, 17, 34, VIEW_DROP_MAX)


def eye_points(orc, per_class: int):
    """[(class viewz, leaf, x, y, movers)] -- `per_class` leaves of every eye class, static and lift-stop classes"""
    from doomfj.movers import lift_states
    rm, mw, name = orc.rm, orc.mw, orc.mapname
    sc = orc.scene_for()
    cmap = sc.cmap
    lds, sds = orc.lds, orc.sds
    verts = cmap.vertexes
    lifts = lift_states(orc.secs, lds, sds)

    def leaf_sector(s):
        """the leaf's sector INDEX: seg -> linedef -> its side's sidedef -> sector (World.leaf_sector's rule)"""
        sg = cmap.segs[cmap.subsectors[s].firstseg]
        ld = lds[sg.linedef]
        return sds[ld.front if sg.side == 0 else ld.back].sector

    def inside(s):
        ss = cmap.subsectors[s]
        pts = [verts[cmap.segs[ss.firstseg + k].v1] for k in range(ss.numsegs)]
        if len(pts) < 3:
            return None
        x = round(sum(p[0] for p in pts) / len(pts))
        y = round(sum(p[1] for p in pts) / len(pts))
        return (x, y) if rm.point_in_subsector(cmap, x, y) == s else None

    by_class = defaultdict(list)
    for s in range(len(cmap.subsectors)):
        p = inside(s)
        if p is None:
            continue
        si = leaf_sector(s)
        if si in lifts:
            for fl in lifts[si]:
                by_class[("lift", rm.view_z(fl))].append((s, p, {si: (fl, orc.secs[si].ceil_h)}))
        else:
            by_class[("floor", rm.view_z(orc.secs[si].floor_h))].append((s, p, None))
    out = []
    for cls in sorted(by_class, key=lambda c: (c[0], c[1])):
        leaves = by_class[cls]
        step = max(1, len(leaves) // per_class)
        for s, (x, y), movers in leaves[::step][:per_class]:
            out.append((cls, s, x, y, movers))
    return out


def census(drops=DEFAULT_DROPS, angles=8, per_class=2, mutate=None, quiet=False) -> bool:
    import probe as P
    orc = P.Oracle()
    rm = orc.rm
    pts = eye_points(orc, per_class)
    classes = sorted({c for c, *_ in pts})
    ph_zero, errors = [], []
    moved = defaultdict(int)
    o_rows = rm._flat_row_colours
    cur = {}

    def rows(cm, aw, fc, vz, plane_h, *a, **k):
        if plane_h == 0:
            ph_zero.append((cur["cls"], cur["leaf"], cur["d"], cur["ang"]))
        return o_rows(cm, aw, fc, vz, plane_h, *a, **k)
    rm._flat_row_colours = rows
    restore = []
    if mutate == "bands_sunk":
        o_planes = rm._render_planes_flat

        def planes(fb, cm, aw, fc, vz, *a, **k):
            return o_planes(fb, cm, aw, fc, vz - (cur["d"] << 16), *a, **k)
        rm._render_planes_flat = planes
        restore.append("_render_planes_flat")
    elif mutate == "assert_below":
        o_span = rm.wall_screen_span

        def span(c, f, vz, s):
            assert vz >= cur["standing"], "an eye below the standing eye"
            return o_span(c, f, vz, s)
        rm.wall_screen_span = span
        restore.append("wall_screen_span")
    t0 = time.time()
    nframes = 0
    try:
        for cls, s, x, y, movers in pts:
            sc = orc.scene_for((), movers)
            cur.update(cls=cls, leaf=s, standing=cls[1])
            for j in range(angles):
                ang = (j * (1 << 32) // angles + 0x0123456) & 0xFFFFFFFF
                st = SimState(x << 16, y << 16, ang, orc.mapname)
                kw = dict(sprite_wad=orc.art, thing_hidden=set(orc.hidden), **GAME_RENDER_KW)
                cur.update(d=0, ang=ang)
                base = bytes(rm.render_wall_frame(st, sc, **kw))
                for d in drops:
                    cur["d"] = d
                    nframes += 1
                    try:
                        fb = bytes(rm.render_wall_frame(st, sc, view_drop=d, **kw))
                    except Exception as e:                       # noqa: BLE001 -- (1): ANY failure is the finding
                        errors.append((cls, s, d, ang, "%s: %s" % (type(e).__name__, e)))
                        continue
                    moved[cls] += fb != base
    finally:
        del rm._flat_row_colours
        for name in restore:
            delattr(rm, name)
    unmoved = [c for c in classes if not moved[c]]
    ok = not errors and not ph_zero and not unmoved
    if not quiet or not ok:
        for e in errors[:10]:
            print("  ERROR class %s leaf %d d %d angle %#010x: %s" % e)
        for z in ph_zero[:10]:
            print("  ph == 0: class %s leaf %d d %d angle %#010x" % z)
        for c in unmoved[:10]:
            print("  NEVER SANK: class %s" % (c,))
    print("DEAD-EYE CENSUS%s: %d eye classes (%d static, %d lift stops), %d leaves, drops %s x %d angles = %d sunk "
          "frames: %d errors, %d planes at ph 0, %d classes never moved -- %s (%.0f s)"
          % (" [mutant %s]" % mutate if mutate else "", len(classes), sum(1 for c in classes if c[0] == "floor"),
             sum(1 for c in classes if c[0] == "lift"), len(pts), list(drops), angles, nframes, len(errors),
             len(ph_zero), len(unmoved), "PASS" if ok else "FAIL", time.time() - t0))
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--drops", default=",".join(map(str, DEFAULT_DROPS)))
    ap.add_argument("--angles", type=int, default=8)
    ap.add_argument("--per-class", type=int, default=2)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    drops = tuple(int(v) for v in a.drops.split(","))
    if a.selftest:
        caught = {m: not census(drops, a.angles, a.per_class, mutate=m, quiet=True)
                  for m in ("bands_sunk", "assert_below")}
        print("SELFTEST: %s -- %s" % (", ".join("%s %s" % (m, "CAUGHT" if c else "MISSED") for m, c in caught.items()),
                                       "PASS" if all(caught.values()) else "FAIL"))
        return 0 if all(caught.values()) else 1
    return 0 if census(drops, a.angles, a.per_class) else 1


if __name__ == "__main__":
    sys.exit(main())
