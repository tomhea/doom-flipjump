"""How often does check_line's BBOX test actually reject? C5's entire value rides on this.

`hex.read_table_packed nb` pays a fixed per-call staging preamble (zero w/4 + mov + mul_const w/4 +
add w/4) BEFORE any byte is read. Splitting the 22-byte linedef row into an 8-byte bbox half and a
14-byte remainder therefore trades:

    saving = reject_rate x 14 byte-reads
    cost   = (1 - reject_rate) x one extra staging preamble

The survey measured 93% rejection on a FIXTURE wad with uniformly-sampled in-map points and flagged
that it needed re-measuring on real walk positions.

WHAT THIS SAMPLES -- TWO SETS, because they answer different questions (CR-2026-08: the previous
docstring claimed "real walk positions" while the code walked a uniform 512-unit grid over the map
bounding box, including points outside every sector).

  SWEEP set  -- THE SWEEP'S OWN walkable grid, the identical construction `scratchpad/m1_sweep.py`
                uses for its 260 frames: step the vertex bounding box, drop points within 24 units
                of a line, drop points whose `true_sector` is -1. This is what the governing metric
                measures. ⚠ It excludes everything within 24 units of a line, and PLAYER_RADIUS is
                16, so on this set NO candidate linedef can actually touch the player box -- the
                reject rate is near 100% by construction and the soundness control cannot fire.
  CONTACT set -- in a sector but WITHIN 24 units of a line: where a moving player ends up and the
                only place collision does real work. The soundness control runs here.

Reporting only the SWEEP set would overstate C5, since C5 pays on every call and only saves when a
candidate is rejected.

CONTROLS (R9)
  V. VACUITY. The candidate count per position is printed. A blank-box bug (passing the 16.16
     PLAYER_RADIUS where whole map units are wanted) makes EVERY linedef a candidate; that reads as
     "0.0% rejected" and looks like a finding. It is not -- see RADIUS below. The printed
     candidates-per-position is the tell: ~34 is right, ~1,175 means the box spans the map.
  N. NEGATIVE CONTROL (--selftest). Two mutations, each of which MUST move the measured rate:
       (a) the bbox test is forced to always-false -> the rate must read 0.0%;
       (b) the radius is restored to the un-shifted 16.16 value -> the rate must collapse AND the
           candidates-per-position must explode. This is the exact bug that produced the wrong
           number the first time, so the control reproduces it on purpose.
  S. SOUNDNESS, INDEPENDENTLY DERIVED. Every linedef the bbox REJECTS is re-checked by an exact
     SEGMENT-vs-square intersection (Liang-Barsky clip of the real linedef against the player's
     square) -- a different computation from the bbox test, not a restatement of it. A rejection
     the segment test says could collide is an error. The first version of this control re-ran the
     SAME four comparisons inside the `if rejected:` branch and therefore could not fail; that is
     the failure mode CR-2026-08 kept finding, reproduced here by accident and fixed.

    python scratchpad/ca_bbox_rate.py [--points 40] [--selftest]
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from doomfj.mapcompiler import bake_bsp, build_blockmap, blockmap_candidates   # noqa: E402
from doomfj.reference_model import PLAYER_RADIUS                               # noqa: E402
from doomfj.wad import WadFile                                                 # noqa: E402
from nb_validate import true_sector, _near_any_line                            # noqa: E402

# PLAYER_RADIUS is 16.16 FIXED (1,048,576); blockmap_candidates and the bbox test both want
# WHOLE MAP UNITS. Passing the fixed value makes the query box span the whole map -- every
# linedef becomes a candidate (measured: 1,175 per position against a true 34.2) and nothing can
# be rejected, which reads as "0% rejected" and looks like a finding. It is not.
RADIUS = PLAYER_RADIUS >> 16

ap = argparse.ArgumentParser()
ap.add_argument("--points", type=int, default=40)
ap.add_argument("--step", type=int, default=192)
ap.add_argument("--selftest", action="store_true")
args = ap.parse_args()

t0 = time.perf_counter()
w = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
cmap = bake_bsp(w, "E1M1")
lds, sds = w.linedefs("E1M1"), w.sidedefs("E1M1")
verts = cmap.vertexes
print("bake_bsp: %.1fs" % (time.perf_counter() - t0), flush=True)
t0 = time.perf_counter()
grid = build_blockmap(cmap, lds)
print("build_blockmap: %.1fs" % (time.perf_counter() - t0), flush=True)

box = [(min(verts[l.v1][0], verts[l.v2][0]), max(verts[l.v1][0], verts[l.v2][0]),
        min(verts[l.v1][1], verts[l.v2][1]), max(verts[l.v1][1], verts[l.v2][1])) for l in lds]

# ---- THE SWEEP'S OWN walkable grid (identical construction to scratchpad/m1_sweep.py) ---------
vs = [(v.x, v.y) for v in w.vertexes("E1M1")]
xs, ys = [v[0] for v in vs], [v[1] for v in vs]
walk = []
for x in range(min(xs) + 13, max(xs), args.step):
    for y in range(min(ys) + 7, max(ys), args.step):
        if _near_any_line(vs, lds, x, y, 24.0):
            continue
        if true_sector(vs, lds, sds, x, y) == -1:
            continue
        walk.append((x, y))
contact = []
for x in range(min(xs) + 13, max(xs), args.step):
    for y in range(min(ys) + 7, max(ys), args.step):
        if not _near_any_line(vs, lds, x, y, 24.0):
            continue
        if true_sector(vs, lds, sds, x, y) == -1:
            continue
        contact.append((x, y))
print("SWEEP   set: %d points (the sweep's own construction, step=%d)"
      % (len(walk), args.step), flush=True)
print("CONTACT set: %d points (in a sector, within 24 units of a line)"
      % len(contact), flush=True)


def seg_hits_square(x0, y0, x1, y1, cx, cy, r):
    """Exact: does the segment (x0,y0)-(x1,y1) intersect the axis-aligned square of half-width r
    centred at (cx,cy)? Liang-Barsky parametric clip -- an INDEPENDENT computation from the four
    bbox comparisons under test (it uses the real segment, not its bounding box)."""
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pq in ((-dx, x0 - (cx - r)), (dx, (cx + r) - x0),
               (-dy, y0 - (cy - r)), (dy, (cy + r) - y0)):
        pp, qq = pq
        if pp == 0:
            if qq < 0:
                return False           # parallel and outside this slab
            continue
        t = qq / pp
        if pp < 0:
            if t > t1:
                return False
            t0 = max(t0, t)
        else:
            if t < t0:
                return False
            t1 = min(t1, t)
    return t0 <= t1


def measure(pts_in, radius, always_false=False, always_reject=False):
    """Returns (positions, candidates, rejected, unsound). `unsound` counts rejections that the
    INDEPENDENT segment-vs-square test says could actually collide -- the soundness control."""
    pts = tested = rejected = unsound = 0
    for x, y in pts_in:
        if pts >= args.points:
            break
        c = list(blockmap_candidates(grid, x, y, radius))
        if not c:
            continue
        pts += 1
        for li in c:
            minx, maxx, miny, maxy = box[li]
            tested += 1
            rej = always_reject or ((not always_false)
                                    and (x + radius <= minx or x - radius >= maxx
                                         or y + radius <= miny or y - radius >= maxy))
            if rej:
                ld = lds[li]
                v1, v2 = verts[ld.v1], verts[ld.v2]
                if seg_hits_square(v1[0], v1[1], v2[0], v2[1], x, y, radius):
                    unsound += 1
            rejected += rej
    return pts, tested, rejected, unsound


res = {}
for tag, pset in (("SWEEP", walk), ("CONTACT", contact)):
    pts, tested, rejected, unsound = measure(pset, RADIUS)
    r = 100 * rejected / max(1, tested)
    res[tag] = (pts, tested, rejected, unsound, r)
    print("")
    print("%s set" % tag)
    print("  positions sampled    : %d" % pts)
    print("  check_line candidates: %s  (%.1f per position)"
          % (format(tested, ","), tested / max(1, pts)))
    print("  BBOX-rejected        : %s  (%.1f%%)" % (format(rejected, ","), r))
    print("  survivors, paying BOTH staging preambles: %.1f%%" % (100 - r))
    print("  SOUNDNESS            : %d rejections that could have collided  %s"
          % (unsound, "ok" if unsound == 0 else "!! THE REJECT TEST IS WRONG"))
print("")
print("the survey assumed 93%% rejection; measured: SWEEP %.1f%%  CONTACT %.1f%%"
      % (res["SWEEP"][4], res["CONTACT"][4]))
pts, tested, rejected, unsound, r = res["CONTACT"]

ok = res["SWEEP"][3] == 0 and res["CONTACT"][3] == 0
if args.selftest:
    print("")
    print("NEGATIVE CONTROLS -- each mutation MUST move the number")
    _p, _t, rej_a, _u = measure(contact, RADIUS, always_false=True)
    ra = 100 * rej_a / max(1, _t)
    print("  (a) bbox test forced always-false : %.1f%% rejected  %s"
          % (ra, "ok" if ra == 0.0 else "!! ACCEPTED -- the measurement is vacuous"))
    # (c) runs on the CONTACT set: on the SWEEP set no candidate can touch the player box
    # (every point is >24 units from a line and the radius is 16), so the control could never
    # fire there -- which the first version of it duly reported.
    _p, _t, _r, uns_c = measure(contact, RADIUS, always_reject=True)
    print("  (c) reject rule forced always-true: %d unsound rejections (CONTACT set)  %s"
          % (uns_c, "ok" if uns_c > 0 else "!! the SOUNDNESS control cannot fire"))
    p_b, t_b, rej_b, _u = measure(contact, PLAYER_RADIUS)
    rb = 100 * rej_b / max(1, t_b)
    cb = t_b / max(1, p_b)
    print("  (b) radius left 16.16 (the bug)   : %.1f%% rejected, %.1f candidates/position  %s"
          % (rb, cb, "ok" if (rb < r / 2 and cb > 10 * (tested / max(1, pts)))
             else "!! the bug did NOT show up -- the control cannot detect it"))
    ok = (ok and ra == 0.0 and uns_c > 0 and rb < r / 2
          and cb > 10 * (tested / max(1, pts)))
    print("")
    print("ca_bbox_rate SELFTEST: %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
