"""The nine-map survey. Ten seconds, no emission, no build -- run this FIRST.

It exists because "nine levels" was assumed to mean 9x and does not: E1M1 is nearly the smallest
map in the episode and nine of them are 14.8x its segs. Every projection in the older handoffs
reasons from 9x and is wrong by ~60%.

It also finds the per-map assumptions that are really E1M1 facts -- `door_states` throws on five of
the nine because it requires a door sector to be STORED SHUT -- which is the `sky` shape from the
flag retirement, arriving before any code is written. Cheap to find here, an assembly error later.

    python scratchpad/m4_survey.py [--wad assets/freedoom1.wad] [--episode 1]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.doors import door_states                                      # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

SPAN_TODAY = 89_494_606          # MEASURED: the shipped one-level binary
BUDGET = 4 * SPAN_TODAY          # the owner's x4, 2026-08-31


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="assets/freedoom1.wad")
    ap.add_argument("--episode", type=int, default=1)
    args = ap.parse_args()

    w = WadFile.from_path(str(ROOT / args.wad))
    maps = ["E%dM%d" % (args.episode, i) for i in range(1, 10)]
    tex_of, flat_of, rows = {}, {}, []
    types = set()
    for m in maps:
        lds, sds, secs = w.linedefs(m), w.sidedefs(m), w.sectors(m)
        segs, ssecs, things = w.segs(m), w.subsectors(m), w.things(m)
        tex = {t.upper() for s in sds for t in (s.middle, s.upper, s.lower) if t and t != "-"}
        fl = {s.floor_tex.upper() for s in secs} | {s.ceil_tex.upper() for s in secs}
        tex_of[m], flat_of[m] = tex, fl
        types |= {t.type for t in things}
        try:
            tbl = door_states(secs, lds, sds)
            doors = str(len(tbl))
        except Exception as e:                       # a per-map fact behind a shared assumption
            doors = "THROWS"
            print("  !! %s door_states: %s" % (m, str(e)[:96]))
        rows.append((m, len(lds), len(secs), len(segs), len(ssecs), len(tex), len(fl),
                     doors, len(things)))

    print("")
    print("%-6s %6s %6s %6s %7s %5s %5s %7s %7s"
          % ("map", "lines", "sects", "segs", "ssecs", "tex", "flat", "doors", "things"))
    for r in rows:
        print("%-6s %6d %6d %6d %7d %5d %5d %7s %7d" % r)

    segs_sum = sum(r[3] for r in rows)
    mult = segs_sum / rows[0][3]
    u_t, u_f = set().union(*tex_of.values()), set().union(*flat_of.values())
    naive = sum(len(v) for v in tex_of.values())
    print("")
    print("  segs 9-map / E1M1        %.2fx     <- NOT 9x. E1M1 is nearly the smallest map." % mult)
    print("  texture union %d vs E1M1 %d = %.1fx, overlap saves %.0f%% against the naive sum"
          % (len(u_t), len(tex_of[maps[0]]), len(u_t) / len(tex_of[maps[0]]), 100 * (1 - len(u_t) / naive)))
    print("  flat union    %d vs E1M1 %d = %.1fx" % (len(u_f), len(flat_of[maps[0]]),
                                                     len(u_f) / len(flat_of[maps[0]])))
    print("  thing TYPES   %d vs E1M1 %d = %.2fx   <- the sprite bank scales with TYPES, not maps"
          % (len(types), len({t.type for t in w.things(maps[0])}),
             len(types) / len({t.type for t in w.things(maps[0])})))
    print("")
    print("  THE GATE FOR THE MILESTONE. If P is the map-specific fraction of the span,")
    print("  nine levels cost span * ((1-P) + %.2fP):" % mult)
    print("    %-8s %-16s %s" % ("P", "projected span", "vs x4 = %s" % format(BUDGET, ",")))
    for p in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        proj = SPAN_TODAY * ((1 - p) + mult * p)
        print("    %-8s %-16s %s" % ("%.0f%%" % (p * 100), format(int(proj), ","),
                                     "fits" if proj <= BUDGET else "OVER by %.2fx" % (proj / BUDGET)))
    print("    break-even P = %.1f%%  -- above this, nine levels do not fit and the fallback starts"
          % (100 * 3.0 / (mult - 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
