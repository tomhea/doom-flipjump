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
from doomfj.things import drawable_things                                 # noqa: E402
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
        draw, _ = drawable_things(rm, things, spr, cache)
        st = door_states(secs, lds, sds)
        # A LOWER BOUND on `lines_pid`, and it needs no BSP walk: a pid is a distinct
        # (ceiling key, floor key) pair, and every sector contributes its own. The emitter's real
        # count is HIGHER -- it adds one variant per door STATE and the back sectors of stacked
        # two-sided segs (E1M1: 152 distinct pairs -> 222 pids). So "over 255 here" is proof the cap
        # binds; "under" is not proof it does not. m4_bands.py measures the real number.
        pid_lo = len({(WR._pid_ceil_key(s2), WR._pid_floor_key(s2)) for s2 in secs}) if hasattr(
            WR, "_pid_ceil_key") else len({((s2.ceil_h, s2.light & 0xFF, s2.ceil_tex.upper()),
                                            (s2.floor_h, s2.light & 0xFF, s2.floor_tex.upper()))
                                           for s2 in secs})
        rows.append(dict(map=m, segs=len(segs), ssecs=len(wad.subsectors(m)),
                         nodes=len(wad.nodes(m)), draw=len(draw), pid_lo=pid_lo,
                         doors=len(st), maxstate=max((len(v) for v in st.values()), default=0),
                         sky=WR.map_has_sky(secs)))

    caps = [
        ("segs < DEG_PNEAR", "segs", WR.DEG_PNEAR,
         "the deg attribution budget must provably never bind (_assert_pnear_unbound); the fj "
         "counter n_tsv is 3 nibbles, so the cap cannot simply be raised"),
        ("drawable things < 0xFF", "draw", 0xFF,
         "0xFF is the empty/end sentinel of BOTH thing linked-list arrays (wall_renderer:470)"),
        ("door states <= MAX_STATES", "maxstate", 16,
         "the fj door switch index is one nibble (doors.MAX_STATES)"),
        ("lines_pid <= 255 (LOWER BOUND)", "pid_lo", 256,
         "the per-column plane-pair id is ONE BYTE (wall_renderer:1195). This column counts "
         "distinct sector (ceil,floor) key pairs, which the emitter only ever ADDS to -- E1M1 "
         "reads 152 here and the emitter bakes 222 -- so an OVER is proof and an ok is not"),
    ]

    print("%-6s %7s %7s %7s %7s %8s %7s %9s %5s" %
          ("map", "segs", "ssecs", "nodes", "draw", "pid>=", "doors", "maxstate", "sky"))
    for r in rows:
        print("%-6s %7d %7d %7d %7d %8d %7d %9d %5s" %
              (r["map"], r["segs"], r["ssecs"], r["nodes"], r["draw"], r["pid_lo"], r["doors"],
               r["maxstate"], "yes" if r["sky"] else "NO"))

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
    print("Caps that need a live emission (measured by scratchpad/m4_bands.py instead):")
    print("  step classes * 256 <= 65536 the 4-nibble stepcol index (:2722)")
    print("  sprite blocks < 0x10000     sp_base is 4 nibbles (:2817)")
    print("  sky half <= LINES_HALF_SLOTS (:2953)")


if __name__ == "__main__":
    main()
