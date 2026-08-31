"""M4-R0 -- THE decisive measurement, and it needs no build.

GAP 1 says the milestone turns on `P`, the map-specific fraction of the span, break-even 21.7%.
The banks part is 89.8% of the emitted text and `vpb_*` (bands-as-code) is 86% of BANKS -- so
`P` is essentially "how much of vpb is per-map". This answers it exactly, from the emitter's own
inputs, by intercepting `generate_bands_walk_fj` and reading the frame it was called from.

WHY IT MATTERS MORE THAN 14.8x: the half-list count is a PRODUCT,
    n = 2 * len(vz_classes) * len(bank_keys)
(`_band_pair_lists` is class-major over keys), and BOTH factors are per-map. A naive union that
crosses every map's view-z classes with every map's bank keys is QUADRATIC in map count; the
per-map block layout (map m's ids based at its own offset) is linear. This prints both, plus the
cross-map dedup rate that decides whether the index has to widen past 4 nibbles at all.

    python scratchpad/m4_bands.py [--maps E1M1,E1M8,E1M7] [--wad assets/freedoom1.wad]
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import wall_renderer as WR                                    # noqa: E402
from doomfj.build import _resolve_sprite_wad, DEFAULT_SPRITE_WAD          # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402


class Captured(Exception):
    def __init__(self, lists):
        self.lists = lists


def capture(wad, mapname, cfg, spr, tier):
    """Run the emitter until the bands walk and steal its inputs, then abort."""
    real = WR.generate_bands_walk_fj
    grabbed = {}

    def spy(lists, **kw):
        f = sys._getframe(1)                       # the emit_wall_renderer frame
        loc = f.f_locals
        grabbed["lists"] = list(lists)
        for k in ("lines_vz_classes", "lines_bank_keys", "lines_pid", "_has_sky",
                  "sky_base_id", "_main_lists", "_sky_lists"):
            if k in loc:
                grabbed[k] = loc[k]
        raise Captured(lists)

    WR.generate_bands_walk_fj = spy
    try:
        WR.emit_wall_renderer(wad, mapname, cfg, sprite_wad=spr, tier=tier, return_parts=True)
    except Captured:
        pass
    finally:
        WR.generate_bands_walk_fj = real
    return grabbed


def key(pairs):
    return tuple(map(tuple, pairs))


CACHE = ROOT / "scratchpad" / "_m4_bands"


def digests(lists):
    """One sha256 per DISTINCT half-list. The union of these across maps is the cross-map dedup
    rate -- the number that decides whether the band index has to widen past 4 nibbles."""
    out = set()
    for pairs in lists:
        h = hashlib.sha256()
        for y2, c in pairs:
            h.update(b"%d,%d;" % (y2, c))
        out.add(h.hexdigest()[:16])
    return out


def measure(wad, m, cfg, spr, tier):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / ("%s_%s.json" % (m, tier))
    if f.exists():
        return json.loads(f.read_text()), 0.0
    t0 = time.perf_counter()
    try:
        g = capture(wad, m, cfg, spr, tier)
    except Exception as e:
        # A CAP that is really an E1M1 fact. This is the survey's second product: every one
        # of these would otherwise surface as a dead build hours in. Record and carry on.
        rec = dict(map=m, tier=tier, failed='%s: %s' % (type(e).__name__, e))
        f.write_text(json.dumps(rec))
        return rec, time.perf_counter() - t0
    dt = time.perf_counter() - t0
    lists = g["lists"]
    rec = dict(map=m, tier=tier,
               nvz=len(g.get("lines_vz_classes", {})),
               npid=len(g.get("lines_pid", {})),
               nkeys=len(g.get("lines_bank_keys", [])),
               n=len(lists), sky=len(g.get("_sky_lists", [])),
               secs=round(dt, 1), dig=sorted(digests(lists)))
    f.write_text(json.dumps(rec))
    return rec, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="assets/freedoom1.wad")
    ap.add_argument("--maps", default=",".join("E1M%d" % i for i in range(1, 10)))
    ap.add_argument("--tier", default="game")
    ap.add_argument("--report", action="store_true", help="union only what is already cached")
    args = ap.parse_args()

    maps = args.maps.split(",")
    recs = []
    if not args.report:
        wad = WadFile.from_path(str(ROOT / args.wad))
        cfg = Config()
        spr = _resolve_sprite_wad(wad, DEFAULT_SPRITE_WAD)
        print("%-6s %5s %6s %6s %9s %9s %7s %8s" %
              ("map", "nvz", "pids", "keys", "lists", "uniq", "sky", "sec"))
        for m in maps:
            r, dt = measure(wad, m, cfg, spr, args.tier)
            if "failed" in r:
                print("%-6s  !! %s" % (m, r["failed"][:150]))
                sys.stdout.flush()
                continue
            recs.append(r)
            print("%-6s %5d %6d %6d %9d %9d %7d %8.1f%s" %
                  (m, r["nvz"], r["npid"], r["nkeys"], r["n"], len(r["dig"]), r["sky"],
                   r["secs"], "" if dt else "  (cached)"))
            sys.stdout.flush()
    else:
        for m in maps:
            f = CACHE / ("%s_%s.json" % (m, args.tier))
            if f.exists():
                r = json.loads(f.read_text())
                if "failed" in r:
                    print("%-6s  !! %s" % (m, r["failed"][:150]))
                else:
                    recs.append(r)
        print("%-6s %5s %6s %6s %9s %9s %7s" % ("map", "nvz", "pids", "keys", "lists", "uniq", "sky"))
        for r in recs:
            print("%-6s %5d %6d %6d %9d %9d %7d" %
                  (r["map"], r["nvz"], r["npid"], r["nkeys"], r["n"], len(r["dig"]), r["sky"]))

    if len(recs) < 2:
        return
    base = recs[0]
    sum_n = sum(r["n"] for r in recs)
    sum_u = sum(len(r["dig"]) for r in recs)
    union = set()
    for r in recs:
        union |= set(r["dig"])
    print()
    print("PER-MAP BLOCK LAYOUT -- map m's ids based at its own offset. THE LINEAR union.")
    print("  sum of per-map list counts     %10d   (%.2fx %s)" % (sum_n, sum_n / base["n"], base["map"]))
    print("  sum of per-map unique bodies   %10d" % sum_u)
    print("  UNION unique bodies            %10d   cross-map dedup saves %.1f%% of the bodies"
          % (len(union), 100 * (1 - len(union) / sum_u)))
    pad = 1 << max(1, (sum_n - 1).bit_length())
    nib = max(1, (max(1, (pad - 1).bit_length()) + 3) // 4)
    print("  the vpb_switch__ pad for %d ids is %d -> %d index nibbles (today: 65536 / 4)"
          % (sum_n, pad, nib))
    print("  switch table growth            %10.2fx   (%d -> %d entries)"
          % (pad / 65536, 65536, pad))
    print("  BODY growth vs %s            %10.2fx   (%d -> %d unique)"
          % (base["map"], len(union) / len(base["dig"]), len(base["dig"]), len(union)))

    print()
    print("NAIVE GLOBAL GRID (one vz-class set x one key set for every map) -- QUADRATIC.")
    tvz = sum(r["nvz"] for r in recs)
    tk = sum(r["nkeys"] for r in recs)
    print("  2 * %d vz-classes * %d keys = %d lists  (%.1fx the per-map layout)"
          % (tvz, tk, 2 * tvz * tk, (2 * tvz * tk) / max(1, sum_n)))

    print()
    print("PID BYTE -- the emitter asserts len(lines_pid) <= 255")
    print("  per-map max %d; a GLOBAL pid space would be %d and OVERFLOWS the byte."
          % (max(r["npid"] for r in recs), sum(r["npid"] for r in recs)))


if __name__ == "__main__":
    main()
