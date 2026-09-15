"""Build a tier with the assembler's table-placement pass ON, driven by a PROFILE.

Relocating every table is worthless and this script exists to avoid doing it. There are 374,655
single-destination `hex.exact_xor` tables in the shipped program and only 9,109 pad-16-aligned
addresses below 2^32 with popcount <= 4; handing the cheap ones out in source order gives them to
cold tables and the mean popcount lands back where it started. So the pool is told exactly which
CALL SITES to move, from the same labels/histogram join `xorcost.py` prices.

    python scratchpad/12m/build_placed.py game --out build/doom_e1m1_placed.fjm --top 8192
    python scratchpad/12m/build_placed.py render --out build/doom_e1m1_placed_render.fjm --top 4096

THE JOIN KEY. A relocatable table's label is `<labels_prefix>---switch`, and `labels_prefix` is
exactly what `TablePool.wants` is handed -- the full macro-expansion path, i.e. the call site. So
the hot set is a set of label stems, and membership is the whole decision.

⚠ THE PROFILE IS FROM AN OLDER BUILD. Label paths shift when the fj sources change, and a stale
path simply fails to match -- silently relocating nothing. The run PRINTS how many tables were
relocated and how many were declined; a `relocated: 0` line means the hot set missed, not that
placement did not help.
"""
import argparse
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                   # noqa: E402
from flipjump.assembler.preprocessor import TablePool                   # noqa: E402
from doomfj.build import build_wall_renderer                            # noqa: E402
from doomfj.config import Config                                        # noqa: E402
from doomfj.harness import W                                            # noqa: E402
from doomfj.wall_renderer import TIERS                                  # noqa: E402

TABLE_LOCALS = ("switch", "first_flip")


def hot_sites(labels_path, hist_path, top):
    """the `top` hottest call sites, as labels_prefix strings"""
    labels = {}
    with gzip.open(labels_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            name, addr = line.rstrip("\n").split("\t")
            labels[name] = int(addr)
    with gzip.open(hist_path, "rt", encoding="utf-8") as fh:
        hist = {int(k): v for k, v in json.load(fh)["hist"].items()}
    ranked = []
    for name in labels:
        for local in TABLE_LOCALS:
            if name.endswith("---" + local):
                stem = name[: -len("---" + local)]
                end = labels.get(stem + "---end")
                if end is not None and hist.get(end, 0):
                    ranked.append((hist[end], stem))
                break
    ranked.sort(reverse=True)
    return {stem for _, stem in ranked[:top]}, len(ranked)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", choices=sorted(TIERS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--labels", default="scratchpad/12m/_full_labels.tsv.gz")
    ap.add_argument("--hist", default="scratchpad/12m/_s2_hist.json.gz")
    ap.add_argument("--top", type=int, default=8192)
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=1 << 31)
    ap.add_argument("--run-ops", type=int, default=16)
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=1 << 27,
                    help="how far above --pool-base the pool may reach. An UNBOUNDED pool scatters "
                         "to the top of the address space (span 96.9%% of 2^27 on the first render "
                         "build) for ~0.6 popcount; bounding it buys the ceiling back.")
    ap.add_argument("--owners", nargs="*", default=None,
                    help="relocate tables under these macro names (stable across edits) instead "
                         "of the profile's exact label paths; --top then caps the count")
    a = ap.parse_args()

    # ONE POOL PER ASSEMBLY. The game tier assembles TWICE -- pass 1 resolves labels, pass 2 bakes
    # them into the M1 self-reset -- and a TablePool is stateful, so sharing one across the passes
    # makes pass 2 continue from pass 1's cursor and give every table a different address. That is
    # not a subtle failure: the reset's own check refused the build with "434 baked addresses moved
    # between passes". `make_pool` is called per assemble() so both passes allocate identically.
    def make_pool():
        if a.owners:
            names = tuple(a.owners)
            return TablePool(W, a.pool_base, run_ops=a.run_ops, capacity=a.top,
                             span_bits=a.span_bits,
                             wants=lambda macro_name, prefix: any(o in prefix for o in names))
        return TablePool(W, a.pool_base, run_ops=a.run_ops, span_bits=a.span_bits,
                         wants=lambda macro_name, prefix: prefix in hot)

    hot = None
    if a.owners:
        # STABLE KEY. An exact label path embeds src/fj line numbers, so any edit to those files
        # shifts it and the hot set silently matches nothing. Macro NAMES do not move, and the
        # profile showed 11 owner macros hold 86.4% of all exact_xor calls, so matching the owner
        # and capping the count gets the cheap addresses to hot code without depending on a
        # profile taken at the same revision.
        owners = tuple(a.owners)
        print("owner mode: relocating tables under %s, capped at %s"
              % (", ".join(owners), format(a.top, ",")), flush=True)
    else:
        hot, live = hot_sites(ROOT / a.labels, ROOT / a.hist, a.top)
        print("profile: %s live tables, relocating the hottest %s"
              % (format(live, ","), format(len(hot), ",")), flush=True)
    print("pool: base %s, span %s, run_ops %d"
          % (hex(a.pool_base), hex(a.span_bits), a.run_ops), flush=True)

    real_assemble = fj.assemble
    pools = []

    def assemble_with_pool(*args, **kwargs):
        pool = make_pool()
        pools.append(pool)
        kwargs["table_pool"] = pool
        return real_assemble(*args, **kwargs)

    fj.assemble = assemble_with_pool
    # build.py imported `assemble` through the `fj` module object, so patching the attribute is
    # enough -- but assert it rather than trusting it, because a silent miss looks like "placement
    # did not help".
    import doomfj.build as build_module
    assert build_module.fj.assemble is assemble_with_pool, "build.py does not call fj.assemble"

    t0 = time.time()
    try:
        info = build_wall_renderer(ROOT / a.out, wad_path=str(ROOT / a.wad), mapname=a.map,
                                   cfg=Config(), tier=a.tier)
    finally:
        fj.assemble = real_assemble

    print(json.dumps(info, indent=2, default=str), flush=True)
    print("", flush=True)
    print("assemblies: %d; relocated per assembly: %s"
          % (len(pools), ", ".join(format(q.allocated, ",") for q in pools)), flush=True)
    if len({q.allocated for q in pools}) > 1:
        print("*** THE PASSES RELOCATED DIFFERENT COUNTS -- their addresses cannot agree", flush=True)
    pool = pools[-1] if pools else make_pool()
    print("relocated: %s tables into %s runs; declined %s"
          % (format(pool.allocated, ","), format(len(pool.run_starts), ","),
             format(pool.declined, ",")), flush=True)
    if pool.allocated == 0:
        print("*** NOTHING WAS RELOCATED -- the hot set matched no call site. The profile is "
              "probably from a different revision of src/fj.", flush=True)
    print("total %ds" % int(time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
