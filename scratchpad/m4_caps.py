"""M4 -- THE CAPACITY SURVEY: every baked cap in the emitter, evaluated against all nine maps.

`door_states` throwing on five of nine was found by the ten-second survey and cost nothing to fix.
This is the same idea applied to every OTHER cap: the emitter asserts ~15 capacity limits, and each
one was sized when E1M1 was the only map. A cap that binds is not a wrong picture -- it is a dead
build, hours in -- so they get checked here, statically, before anything is emitted.

⚠ WHAT THIS DOES NOT COVER, and it says so in the output: caps whose input only exists partway
through an emission (`lines_pid`, the step/sprite light classes, the sky half slots). Those are
measured by `scratchpad/m4_bands.py`, which runs the real emitter and records what each map does.

    python scratchpad/m4_caps.py [--wad assets/freedoom1.wad]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import wall_renderer as WR                                    # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.doors import door_states                                      # noqa: E402
from doomfj.reference_model import ReferenceModel                         # noqa: E402
from doomfj.mapcompiler import bake_bsp                                    # noqa: E402
from doomfj.things import baked_thing_mask, drawable_things                # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="assets/freedoom1.wad")
    ap.add_argument("--sprite-wad", default="assets/freedoom1.wad")
    args = ap.parse_args()

    wad = WadFile.from_path(str(ROOT / args.wad))
    spr = WadFile.from_path(str(ROOT / args.sprite_wad))
    cfg = Config()
    rm = ReferenceModel(cfg)
    cache = {}
    maps = ["E1M%d" % i for i in range(1, 10)]

    rows = []
    for m in maps:
        segs = wad.segs(m)
        secs, lds, sds = wad.sectors(m), wad.linedefs(m), wad.sidedefs(m)
        things = wad.things(m)
        draw, draw_idx = drawable_things(rm, things, spr, cache)
        # THE EXACT `nt`, not the drawable count. wall_renderer:470 asserts on `len(_mt_keep)` --
        # the M14.5 RUNTIME subset -- and `thing_rows` drops everything else, so counting drawables
        # overstates it badly. MEASURED: this column read 463 for E1M6 while the emitter reported
        # 344, and it claimed seven of nine maps overflow when only E1M6 actually does. Getting it
        # right costs one bake_bsp and one point_in_subsector per thing, about a second a map.
        cmap = bake_bsp(wad, m)
        baked = baked_thing_mask(rm, cmap, draw, WR.MONSTER_TYPES)
        nt = len({i for i, b in zip(draw_idx, baked) if not b})
        st = door_states(secs, lds, sds)
        # An ESTIMATE of `lines_pid` with NO GUARANTEED DIRECTION -- do not read it as a bound.
        # A pid is a distinct (ceiling key, floor key) pair. This counts one per SECTOR, and the
        # emitter both ADDS to that (a variant per door STATE, plus the back sectors of stacked
        # two-sided segs) and SUBTRACTS from it (only sectors a WALK seg reaches are registered).
        # MEASURED 2026-08-31 against m4_bands.py, which runs the real emitter:
        #   E1M1 152->222   E1M2 329->376   E1M3 249->337   E1M4 237->276
        #   E1M5 122->147   E1M8  90-> 90   E1M9 264->340   ... but E1M6 328->UNDER 255.
        # Seven of eight read low and E1M6 reads high, so neither an OVER nor an ok here proves
        # anything. It is a sighting shot; m4_bands.py is the measurement.
        pid_lo = len({(WR._pid_ceil_key(s2), WR._pid_floor_key(s2)) for s2 in secs}) if hasattr(
            WR, "_pid_ceil_key") else len({((s2.ceil_h, s2.light & 0xFF, s2.ceil_tex.upper()),
                                            (s2.floor_h, s2.light & 0xFF, s2.floor_tex.upper()))
                                           for s2 in secs})
        rows.append(dict(map=m, segs=len(segs), ssecs=len(wad.subsectors(m)),
                         nodes=len(wad.nodes(m)), draw=len(draw), nt=nt, pid_lo=pid_lo,
                         doors=len(st), maxstate=max((len(v) for v in st.values()), default=0),
                         sky=WR.map_has_sky(secs)))

    caps = [
        ("segs < DEG_PNEAR", "segs", WR.DEG_PNEAR,
         "the deg attribution budget must provably never bind (_assert_pnear_unbound); the fj "
         "counter n_tsv is 3 nibbles, so the cap cannot simply be raised"),
        ("runtime things < 0xFF", "nt", 0xFF,
         "0xFF is the empty/end sentinel of BOTH thing linked-list arrays (wall_renderer:470). "
         "This is the M14.5 RUNTIME subset the assert actually counts, not the drawable count"),
        ("door states <= MAX_STATES", "maxstate", 16,
         "the fj door switch index is one nibble (doors.MAX_STATES)"),
    ]

    print("%-6s %7s %7s %7s %7s %6s %7s %7s %9s %5s" %
          ("map", "segs", "ssecs", "nodes", "draw", "nt", "pid~", "doors", "maxstate", "sky"))
    for r in rows:
        print("%-6s %7d %7d %7d %7d %6d %7d %7d %9d %5s" %
              (r["map"], r["segs"], r["ssecs"], r["nodes"], r["draw"], r["nt"], r["pid_lo"],
               r["doors"], r["maxstate"], "yes" if r["sky"] else "NO"))

    print()
    bad = 0
    for name, field, cap, why in caps:
        over = [(r["map"], r[field]) for r in rows if r[field] >= cap]
        mx = max(r[field] for r in rows)
        tag = "OVER" if over else "ok  "
        print("[%s] %-26s cap %6d   worst map %6d" % (tag, name, cap, mx))
        print("       %s" % why)
        if over:
            bad += 1
            print("       BINDS ON: %s" % ", ".join("%s(%d)" % o for o in over))
    print()
    print("%d of %d statically-checkable caps BIND on at least one E1 map." % (bad, len(caps)))
    print()
    print("lines_pid <= 255 -- the per-column plane-pair id is ONE BYTE (wall_renderer:1195).")
    print("  NOT statically checkable, so it is NOT counted above. The `pid>=` column is a sighting")
    print("  shot in neither direction. MEASURED by scratchpad/m4_bands.py, which runs the emitter:")
    print("    E1M1  222        E1M2  376 OVER   E1M3  337 OVER   E1M4  276 OVER")
    print("    E1M5  147        E1M8   90        E1M9  340 OVER")
    print("    E1M6  UNMEASURED -- it dies on the thing cap at :970, before the pid assert at :1195")
    print("    E1M7  UNMEASURED -- same")
    print("  Four of SEVEN maps that reach the assert overflow the byte. Widening the pid alone")
    print("  would build E1M1/2/3/4/5/8/9; E1M6 and E1M7 need the thing and seg caps as well.")
    print()
    print("Other caps that need a live emission (measure them the same way):")
    print("  step classes * 256 <= 65536 the 4-nibble stepcol index (:2722)")
    print("  sprite blocks < 0x10000     sp_base is 4 nibbles (:2817)")
    print("  sky half <= LINES_HALF_SLOTS (:2953)")


if __name__ == "__main__":
    main()
