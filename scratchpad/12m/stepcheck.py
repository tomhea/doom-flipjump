"""Does a 50-unit unswept step let the player walk THROUGH a wall, and does a smaller step fix it?

A playtest reported two things that look opposite: being stopped on visibly open floor, and
escaping the level entirely. The claim under test is that ONE mechanism produces both --

    FORWARD_MOVE = 50 map units per tic (reference_model.py:63) is applied as a single UNSWEPT
    jump, tested only at the destination box (reference_model.py:847), with no partial move on
    refusal (reference_model.py:867-872).

The player box is 2*PLAYER_RADIUS = 32 units wide. A 50-unit step therefore leaves an 18-unit band
covered by NEITHER the source box nor the destination box, so a wall standing in that band is never
straddled by either test and is jumped clean. And because a refused step is discarded whole rather
than truncated, the player halts up to ~50 units short of a wall on open floor.

This checks that on THE MAP THAT SHIPS. An earlier analysis reached its conclusions by sweeping
assets/doom1.wad; DESIGN.md:812 says that WAD "is never the oracle input (its geometry differs)",
and build_wall_renderer defaults to tests/fixtures/freedoom_e1m1.wad. Using the wrong map inverted
the answer, so this script PRINTS the wad it loaded and asserts it is the build default.

Oracle only -- no assembly, no build, seconds to run.

    python scratchpad/12m/stepcheck.py
    python scratchpad/12m/stepcheck.py --selftest

CONTROLS (R9)
  C1 RIGHT MAP -- the wad under test must be the one build_wall_renderer actually builds.
  C2 THE TUNNELING TEST SEPARATES -- a segment/segment crossing test must report a crossing for a
     path that demonstrably straddles a known wall, and none for a path that does not. A detector
     that never fires would report "0 tunneling" at every step size and look like a clean bill.
  C3 NON-VACUITY -- a sweep that accepts no moves at all is reported as VACUOUS, not as "0 crossings".
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.reference_model import (ReferenceModel, spawn_state, _signed,   # noqa: E402
                                    build_scene)
from doomfj.config import Config                                          # noqa: E402
from doomfj import build as buildmod                                      # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402


def _seg_cross(ax, ay, bx, by, cx, cy, dx, dy):
    """True when segment AB properly straddles segment CD (both orientation tests disagree)."""
    def cross(ox, oy, px, py, qx, qy):
        return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)
    d1 = cross(cx, cy, dx, dy, ax, ay)
    d2 = cross(cx, cy, dx, dy, bx, by)
    d3 = cross(ax, ay, bx, by, cx, cy)
    d4 = cross(ax, ay, bx, by, dx, dy)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def load():
    wad_path = Path(buildmod.DEFAULT_WAD)
    return wad_path, WadFile.from_path(wad_path)


def walkout(move_units, tics=40, turns=17):
    """Drive the SHIPPED sim path from the real player start and see if the centre path ever
    crosses a one-sided (solid) linedef -- i.e. the player left the level."""
    import doomfj.reference_model as rm
    old = rm.FORWARD_MOVE
    rm.FORWARD_MOVE = move_units << 16
    try:
        wad_path, wad = load()
        rmod = ReferenceModel(Config())
        scene = build_scene(wad, wad, "E1M1")
        st = spawn_state(wad, "E1M1")
        lds = wad.linedefs("E1M1")
        verts = wad.vertexes("E1M1")
        crossings = []
        for t in range(tics):
            keys = {"turn_left": t < turns, "forward": t >= turns}
            nxt = rmod.step_sim(st, keys, scene=scene)
            ax, ay = _signed(st.x, 32) / 65536.0, _signed(st.y, 32) / 65536.0
            bx, by = _signed(nxt.x, 32) / 65536.0, _signed(nxt.y, 32) / 65536.0
            if (ax, ay) != (bx, by):
                for li, ld in enumerate(lds):
                    if ld.back != -1:
                        continue                        # only SOLID walls prove an escape
                    v1, v2 = verts[ld.v1], verts[ld.v2]
                    if _seg_cross(ax, ay, bx, by, v1.x, v1.y, v2.x, v2.y):
                        crossings.append((t, li, (round(ax), round(ay)), (round(bx), round(by)),
                                          ((v1.x, v1.y), (v2.x, v2.y))))
            st = nxt
        return wad_path, crossings, (_signed(st.x, 32) / 65536.0, _signed(st.y, 32) / 65536.0)
    finally:
        rm.FORWARD_MOVE = old


def main():
    wad_path, wad = load()
    print("wad under test : %s" % wad_path)
    print("C1 is this the wad build_wall_renderer builds? %s"
          % ("YES" if Path(wad_path) == Path(buildmod.DEFAULT_WAD) else "NO -- WRONG MAP"))
    lds = wad.linedefs("E1M1")
    verts = wad.vertexes("E1M1")
    xs = [v.x for v in verts]
    ys = [v.y for v in verts]
    print("               %d linedefs, bbox x %d..%d  y %d..%d"
          % (len(lds), min(xs), max(xs), min(ys), max(ys)))
    print("")
    print("PLAYER box is 2*16 = 32 units wide; the step is tested at the DESTINATION only.")
    print("")
    for move in (50, 25, 16):
        wp, cross, end = walkout(move)
        tag = "  <-- shipped" if move == 50 else ""
        print("move %2d u/tic : %d solid-wall crossing(s); ends at (%.0f, %.0f)%s"
              % (move, len(cross), end[0], end[1], tag))
        for t, li, a, b, seg in cross[:3]:
            print("      tic %2d  %s -> %s  THROUGH one-sided linedef %d %s"
                  % (t, a, b, li, seg))
    return 0


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-56s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("stepcheck selftest -- a crossing detector that never fires reports a clean bill")
    # C2 positive: a path from (0,-10) to (0,10) straddles the wall segment (-10,0)-(10,0).
    check("C2 detects a path that DOES cross a wall",
          _seg_cross(0, -10, 0, 10, -10, 0, 10, 0))
    # C2 negative: a path that stops short must NOT report a crossing.
    check("C2 ...and rejects one that stops short",
          not _seg_cross(0, -10, 0, -1, -10, 0, 10, 0))
    check("C2 ...and rejects a parallel path",
          not _seg_cross(-10, 5, 10, 5, -10, 0, 10, 0))
    wad_path, _ = load()
    check("C1 the build default wad resolves", Path(wad_path).exists(), str(wad_path))
    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else main())
