"""The HEAT LIST for pin protection (M7 P1.1, docs/gp-pin-protection.md): each hot group's hot table
sites, hottest first, for `build_blocked.py --pin-heat`.

    python scratchpad/12m/heatsites.py <profx prefix> --sites <sites.json.gz> [--top 20]
        [--out scratchpad/12m/heat_blocked27.json] [--counts-cache scratchpad/12m/_counts_game.json.gz]
        [--fjm build/doom_e1m1_blocked27.fjm] [--labels scratchpad/12m/atlas/blocked27.labels.tsv.gz]

WHAT IT JOINS.
  * the profile (`profx drive.py games`): self counts of every pool word the ten games executed;
  * the layout: the build's blocks, re-derived from its counts cache (`profx/pool.reconstruct`) and
    checked against the image -- every placed group's source word must rest at its base;
  * the SITES: `build_blocked.py --record-sites` records every table the counting pass reached --
    its group, its macro-expansion path, its size -- in the order the program reaches them.
A table's address says which slot it took, not which code emitted it, so the sites are REPLAYED
through a fresh placing pool with the build's knobs -- flipjump's own `reserve()`, not a copy of its
index rule -- and every address it hands out is mapped back to its site. The profile's tables are
then named by site, ranked by the ops they executed, and written as
{heat_key(group): [[heat_key(site), occurrence, slot_ops], ...]} for the top groups by table ops.

CONTROLS. The replay must reproduce the counts cache's per-width table counts for every hot group
(else the sites are another program's), and every executed pool word inside a hot block must map
to a replayed table (reported, not silently dropped). The per-group arm/disarm estimate it prints
(2 x popcount of the offset, as `profx/heatindex.py`) is arithmetic, not a measurement.
"""
import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for q in (HERE / "profx", ROOT / "src"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))
from flipjump.assembler.inner_classes.expr import Expr                     # noqa: E402
from flipjump.assembler.preprocessor import heat_key                       # noqa: E402
from common import W, default_fjm, default_labels, label_dict, load_sparse, work_dir  # noqa: E402
from fjmimage import FjmImage                                               # noqa: E402
from pool import KNOBS, eval_key, reconstruct                               # noqa: E402

OP_BITS = 2 * W


def game_frames(prefix):
    runs = json.load(open(prefix + ".runs.json"))["runs"]
    return sum(max(0, r["frames"] - 2) for r in runs if r["name"] != "calibration")


def slot_ops_of(width, max_slot_ops):
    return 1 << max(0, (min(max(width, 1), max_slot_ops) - 1).bit_length())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("prefix")
    ap.add_argument("--sites", required=True)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out", default=str(HERE / "heat_blocked27.json"))
    ap.add_argument("--counts-cache", default=str(HERE / "_counts_game.json.gz"))
    ap.add_argument("--fjm", default=None)
    ap.add_argument("--labels", default=None)
    a = ap.parse_args()
    p = Path(a.prefix)
    prefix = str(p if p.is_absolute() else work_dir() / p)
    fjm = Path(a.fjm) if a.fjm else default_fjm()
    lab = label_dict(Path(a.labels) if a.labels else default_labels())
    F = game_frames(prefix)

    # the layout, checked against the image (as hotwords.py)
    pool, fr = reconstruct(a.counts_cache)
    img = FjmImage(fjm)
    agree = n = 0
    for g, (base, _e) in pool.groups.items():
        addr = eval_key(g, lab)
        if addr is None:
            continue
        v = img.word(addr // W)
        n += 1
        agree += v is not None and (v & ~(pool._block_bits(g) - 1)) == base
    print("fjm %s (sha256 %s...), %d game frames; CONTROL layout vs image: %d/%d source words at their base"
          % (fjm.name, hashlib.sha256(fjm.read_bytes()).hexdigest()[:16], F, agree, n), flush=True)
    if agree < 0.99 * n:
        raise SystemExit("the counts cache does not describe this binary -- not written")

    # ops per executed table, per group (self counts of pool words inside each block)
    placed = sorted((base, pool._block_bits(g), g) for g, (base, _e) in pool.groups.items())
    bases_w = np.array([b // W for b, _bits, _g in placed], dtype=np.int64)
    ws, cs = load_sparse(prefix + ".self.bin")
    m = ws >= KNOBS["pool_base"] // W
    idx = np.searchsorted(bases_w, ws[m], side="right") - 1
    per_group = {}
    for i, c, wv in zip(idx.tolist(), cs[m].tolist(), ws[m].tolist()):
        if i < 0:
            continue
        b, bits, g = placed[i]
        if wv < (b + bits) // W:
            per_group.setdefault(g, {})[wv] = c
    ranked = sorted(per_group, key=lambda g: -sum(per_group[g].values()))[:a.top]

    # the sites, replayed through flipjump's own reserve()
    with gzip.open(a.sites, "rt", encoding="utf-8") as fh:
        sites = json.load(fh)
    print("sites %s (sha256 %s...): %d groups, %d tables, program %s"
          % (Path(a.sites).name, hashlib.sha256(Path(a.sites).read_bytes()).hexdigest()[:16],
             len(sites["groups"]), sum(len(v) for v in sites["groups"].values()), sites.get("program")),
          flush=True)
    replay, _ = reconstruct(a.counts_cache)
    heat, report, bad = {}, [], []
    for g in ranked:
        recorded = sites["groups"].get(g)
        if recorded is None:
            bad.append("%s: no recorded sites" % g)
            continue
        widths = {}
        for _prefix, ops, align in recorded:
            s = slot_ops_of(max(ops, align), KNOBS["max_slot_ops"])
            widths[s] = widths.get(s, 0) + 1
        want = {}
        for w, c in fr["width_hist"].get(g, {}).items():
            s = slot_ops_of(w, KNOBS["max_slot_ops"])
            want[s] = want.get(s, 0) + c
        if widths != want:
            bad.append("%s: recorded widths %s != the counts cache's %s" % (g, widths, want))
            continue
        at = {}
        seen = {}
        for path, ops, align in recorded:
            key = heat_key(path)
            occurrence = seen.get(key, 0)
            seen[key] = occurrence + 1
            got = replay.reserve(align, ops, group=g, group_expr=Expr(g), labels_prefix=path)
            if got is not None:
                at[got[0]] = (key, occurrence, slot_ops_of(max(ops, align), KNOBS["max_slot_ops"]))
        base, bits = pool.groups[g][0], pool._block_bits(g)
        layout, _ = pool._bucket_layout(g)
        tables = {}
        unmapped = 0
        for wv, c in per_group[g].items():
            off = wv * W - base
            for s, (boff, slots, _count) in layout.items():
                sb = s * OP_BITS
                if boff <= off < boff + slots * sb:
                    start = base + boff + ((off - boff) // sb) * sb
                    site = at.get(start)
                    if site is None:
                        unmapped += c
                    else:
                        tables[site] = tables.get(site, 0) + c
                    break
        order = sorted(tables, key=lambda t: (-tables[t], t))
        heat[heat_key(g)] = [list(t) for t in order]
        # the estimate: arm/disarm = 2 x popcount(offset) per dispatch-weighted table op
        now = sum(c * 2 * bin(wv * W - base).count("1") for wv, c in per_group[g].items())
        report.append((g, sum(per_group[g].values()), len(order), unmapped, now))
    if bad:
        for b in bad:
            print("  *** %s" % b)
        raise SystemExit("the sites do not describe this program -- not written")
    print("")
    print("%-58s %12s %8s %10s" % ("hot group", "table ops/fr", "tables", "unmapped/fr"))
    for g, ops, nt, unmapped, _now in report:
        print("%-58s %12s %8s %10s" % (g[:58], format(ops // F, ","), format(nt, ","), format(unmapped // F, ",")))
    blob = {"what": "hot groups and their hot table sites, hottest first (scratchpad/12m/heatsites.py)",
            "fjm": fjm.name, "fjm_sha256": hashlib.sha256(fjm.read_bytes()).hexdigest(),
            "profile": Path(prefix).name, "game_frames": F, "counts_cache": Path(a.counts_cache).name,
            "sites_sha256": hashlib.sha256(Path(a.sites).read_bytes()).hexdigest(),
            "knobs": KNOBS, "top": a.top, "groups": heat}
    Path(a.out).write_text(json.dumps(blob, indent=1), encoding="utf-8", newline="\n")
    print("\nwrote %s: %d hot groups, %d hot sites (sha256 %s...)"
          % (a.out, len(heat), sum(len(v) for v in heat.values()),
             hashlib.sha256(Path(a.out).read_bytes()).hexdigest()[:16]))
    total_unmapped = sum(r[3] for r in report)
    print("CONTROL every executed hot table mapped to a replayed site: %s (%s ops unmapped)"
          % ("PASS" if total_unmapped == 0 else "FAIL", format(total_unmapped, ",")))
    return 0 if total_unmapped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
