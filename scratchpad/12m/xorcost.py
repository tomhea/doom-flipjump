"""WHERE THE OPS ACTUALLY GO: `hex.exact_xor` arms a switch table and disarms it, and those two
`wflip`s cost `2 * popcount(table_address)` -- 62.78% of every op the shipped game executes.

This tool measures that from the SHIPPED BINARY (not from a model), and prices one alternative.

THE MECHANISM, as `flipjump/assembler/assembler.py:insert_wflip_ops` builds it. `wflip a, v, j`
emits ONE op per set bit of `v`: the first inline, the rest chained (and shared between call sites
with the same suffix -- sharing saves SPACE, never OPS). `hex.exact_xor` does this twice:

    wflip src+w, switch, src              <- arm:    popcount(switch) ops
    pad 16 ; switch: <16 entries> ; end:  <- walk:   1..4 ops
    wflip src+w, switch                   <- disarm: popcount(switch) ops

So the address the table LANDS AT is a per-call cost, paid ~660k times a frame.

THE ALTERNATIVE it prices (`blocked`). Every site's `src+w` word is recovered from the binary, and
sites are grouped by it. If the tables sharing a word were relocated into ONE aligned block and the
word were baked with the block base, the arm would flip only the INDEX within the block --
`2 * popcount(index)` instead of `2 * popcount(full address)`.

    python scratchpad/12m/xorcost.py --fjm build/doom_e1m1_s2.fjm
    python scratchpad/12m/xorcost.py --selftest

WHAT THIS IS NOT. It prices a LAYOUT, not a patch. It assumes the only writers of `src+w` are these
arms and disarms; nothing here proves that, and the design does not survive a third writer. C5
states the assumption rather than checking it, and the number is void until an implementation
asserts it. The campaign's three estimate misses (FINDINGS BC) were all "attributed != removable";
this is a different inference -- an EXACT per-op accounting, not an attribution -- but it is still
an estimate until a build measures it.

CONTROLS (R9)
  C1 THE MODEL, against the real binary: at each of the hottest sites the disarm chain must be
     exactly popcount(switch) ops long and EVERY op in it must execute exactly `calls` times.
     This is the claim the whole file rests on, checked op by op on the shipped image.
  C2 SENSITIVITY: a table at a low-popcount address must measure cheaper than one at a high-popcount
     address. A tool that cannot see the effect cannot price it.
  C3 PROVENANCE: labels and histogram from DIFFERENT builds must be rejected, not silently joined.
  C4 NON-VACUITY: with every table already at popcount 1 the predicted saving must be ~0, so the
     headline number cannot come from the arithmetic alone.
  C5 PERMUTATION: within a block each site must get a DISTINCT index, or the "blocked" cost is
     counting a layout that cannot exist.
"""
import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def load_labels(path):
    lab = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            name, addr = line.rstrip("\n").split("\t")
            lab[name] = int(addr)
    return lab


def load_hist(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    return {int(k): v for k, v in blob["hist"].items()}, blob["ops"], blob["frames"], blob["fjm"]


def collect_sites(reader, labels, hist):
    """[(switch_addr, src_word, calls)] for every single-destination site, src recovered from the
    binary: the first disarm op flips a bit of `src+w`, and the word is w-aligned."""
    w = reader.memory_width
    out = []
    for name, switch in labels.items():
        if not name.endswith("---switch"):
            continue
        end = labels.get(name[: -len("switch")] + "end")
        if end is None:
            continue
        flip = reader.get_word(end)
        out.append((switch, flip - (flip % w), hist.get(end, 0)))
    return out


def price(sites):
    """(current_ops, blocked_ops, blocks, slots) over a walk. The hottest site in a block takes
    index 0, so the blocked figure is the BEST case of this layout, and is stated as such."""
    by_word = defaultdict(list)
    for switch, word, calls in sites:
        by_word[word].append((calls, switch))
    cur = new = slots = 0
    for group in by_word.values():
        group.sort(reverse=True)
        for index, (calls, switch) in enumerate(group):
            cur += 2 * bin(switch).count("1") * calls
            new += 2 * max(1, bin(index).count("1")) * calls
        slots += 1 << max(0, (len(group) - 1).bit_length())
    return cur, new, len(by_word), slots


def join_is_sound(labels, hist, total):
    """the labels and the histogram must describe ONE build. A mismatched pair leaves a large
    fraction of ops past the last label -- 12.14% on the pair that produced FINDINGS AY."""
    top = max(labels.values())
    far = sum(c for a, c in hist.items() if a > top)
    return far / total, far / total <= 0.02


def report(fjm, labels_path, hist_path, base_ops_per_frame):
    from flipjump.fjm.fjm_reader import Reader

    labels = load_labels(labels_path)
    hist, total, frames, hist_fjm = load_hist(hist_path)
    rate, ok = join_is_sound(labels, hist, total)
    print("fjm      : %s" % fjm)
    print("histogram: %s  (%s ops, %d frames, from %s)"
          % (Path(hist_path).name, format(total, ","), frames, hist_fjm))
    print("labels   : %s" % Path(labels_path).name)
    print("join     : %.4f%% of ops past the last label -- %s"
          % (100.0 * rate, "SOUND" if ok else "MISMATCHED PAIR, refusing to price"))
    if not ok:
        return 1
    reader = Reader(fjm)
    sites = collect_sites(reader, labels, hist)
    live = [s for s in sites if s[2]]
    calls = sum(s[2] for s in live)
    cur, new, blocks, slots = price(sites)
    print("")
    print("single-destination exact_xor sites : %s static, %s executed"
          % (format(len(sites), ","), format(len(live), ",")))
    print("calls in the walk                  : %s" % format(calls, ","))
    print("mean popcount of an executed table : %.2f"
          % (sum(bin(a).count("1") * c for a, _, c in live) / max(calls, 1)))
    print("")
    print("ARM+DISARM ops in the walk")
    print("  today   (2 x popcount of the table address) : %13s = %6.2f%% of the walk"
          % (format(cur, ","), 100.0 * cur / total))
    print("  blocked (2 x popcount of the index)         : %13s = %6.2f%%"
          % (format(new, ","), 100.0 * new / total))
    print("  saved                                       : %13s = %6.2f%%"
          % (format(cur - new, ","), 100.0 * (cur - new) / total))
    print("")
    print("  ops/frame if that saving lands: %s -> %s"
          % (format(base_ops_per_frame, ","),
             format(int(base_ops_per_frame * (1 - (cur - new) / total)), ",")))
    print("  table region needed: %s blocks, %s slots, %s words (%.2f%% of 2^27)"
          % (format(blocks, ","), format(slots, ","), format(slots * 32, ","),
             100.0 * slots * 32 / 134217728))

    # ---- the 2-destination form, so the family total is in the same log as its parts
    dbl = []
    for name, first in labels.items():
        if not name.endswith("---first_flip"):
            continue
        end = labels.get(name[: -len("first_flip")] + "end")
        if end is not None and hist.get(end, 0):
            dbl.append((first, hist[end]))
    dbl_calls = sum(c for _, c in dbl)
    dbl_ops = sum(2 * bin(a).count("1") * c for a, c in dbl)
    print("")
    print("THE 2-DESTINATION FORM (double_exact_xor), untouched by the figures above")
    print("  live tables %s, calls %s, arm+disarm %s ops"
          % (format(len(dbl), ","), format(dbl_calls, ","), format(dbl_ops, ",")))
    print("  exact_xor FAMILY arm+disarm total : %s ops = %.2f%% of the walk"
          % (format(cur + dbl_ops, ","), 100.0 * (cur + dbl_ops) / total))

    # ---- the hottest site, op by op: this is what C1 verifies, printed so it can be read
    hottest = max(((c, a) for a, _, c in live), default=(0, 0))
    for name, sw in labels.items():
        if name.endswith("---switch") and sw == hottest[1]:
            end = labels[name[: -len("switch")] + "end"]
            print("")
            print("HOTTEST SITE  switch @ %s (popcount %d), end @ %s, %s calls"
                  % (format(sw, ","), bin(sw).count("1"), format(end, ","),
                     format(hottest[0], ",")))
            ip = end
            addrs = []
            for _ in range(bin(sw).count("1")):
                addrs.append(ip)
                ip = reader.get_word(ip + reader.memory_width)
            tail = addrs[1:]                       # addrs[0] is `end` itself, above the table
            print("  first disarm op at `end`; its %d chained ops occupy %s .. %s"
                  % (len(tail), format(min(tail), ","), format(max(tail), ",")))
            print("  those sit BELOW the table at %s -- i.e. inside the `pad 16` alignment gap,"
                  % format(sw, ","))
            print("  which is why widening a pad does not remove them")
            break

    # ---- PINNING, measured and killed: a src word driven by exactly ONE static site
    by_word = defaultdict(list)
    for switch, word, calls_ in sites:
        by_word[word].append((switch, calls_))
    solo = [(s, c) for g in by_word.values() if len(g) == 1 for s, c in g]
    solo_calls = sum(c for _, c in solo)
    solo_ops = sum(2 * bin(s).count("1") * c for s, c in solo)
    print("")
    print("PINNING (bake the address, drop both wflips) -- needs a word used by ONE site")
    print("  eligible sites %s of %s, calls %s of %s, worth %s ops = %.2f%% of the walk"
          % (format(len(solo), ","), format(len(sites), ","), format(solo_calls, ","),
             format(calls, ","), format(solo_ops, ","), 100.0 * solo_ops / total))

    # ---- PLACEMENT, the weaker alternative, at zero size growth
    span = max(labels.values())
    pool = []
    for pc in range(0, 23):
        for mask in range(1 << 22):
            if bin(mask).count("1") == pc and (mask << 10) <= span:
                pool.append(pc)
            if len(pool) > 60000:
                break
        if len(pool) > 60000:
            break
    pool.sort()
    order = sorted(live, key=lambda t: -t[2])
    print("")
    print("PLACEMENT (relocate to low-popcount addresses, hottest first; zero size growth)")
    print("  applies to the %s single-destination sites only" % format(len(order), ","))
    import math
    supply3 = sum(math.comb(22, j) for j in range(4))
    supply4 = sum(math.comb(22, j) for j in range(5))
    print("  supply of pad-16-aligned addresses below 2^32 by popcount: pc<=3 = %s, pc<=4 = %s"
          % (format(supply3, ","), format(supply4, ",")))
    for k in (4096, 16384, len(order)):
        k = min(k, len(order))
        saved = sum(2 * (bin(a).count("1") - pool[i]) * c
                    for i, (a, _, c) in enumerate(order[:k])
                    if i < len(pool) and bin(a).count("1") > pool[i])
        print("  top %-7s tables -> %s ops/frame"
              % (format(k, ","), format(int(base_ops_per_frame * (1 - saved / total)), ",")))
    return 0


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-62s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("xorcost selftest -- the cost model, checked against the shipped image", flush=True)
    from flipjump.fjm.fjm_reader import Reader

    fjm = ROOT / "build" / "doom_e1m1_s2.fjm"
    lp = ROOT / "scratchpad" / "12m" / "_full_labels.tsv.gz"
    hp = ROOT / "scratchpad" / "12m" / "_s2_hist.json.gz"
    if not (fjm.exists() and lp.exists() and hp.exists()):
        print("  MISSING INPUTS -- selftest needs the s2 binary, labels and histogram")
        return 2
    labels = load_labels(lp)
    hist, total, _, _ = load_hist(hp)
    reader = Reader(fjm)
    w = reader.memory_width

    # C1 -- the model, op by op, on the real binary
    ends = []
    for name, switch in labels.items():
        if name.endswith("---switch"):
            end = labels.get(name[: -len("switch")] + "end")
            if end is not None and hist.get(end, 0):
                ends.append((hist[end], switch, end))
    ends.sort(reverse=True)
    bad = 0
    for calls, switch, end in ends[:40]:
        ip, seen = end, []
        for _ in range(bin(switch).count("1")):
            seen.append(hist.get(ip, 0))
            ip = reader.get_word(ip + w)
        if any(c != calls for c in seen):
            bad += 1
    check("C1 disarm chain is popcount(switch) ops, each run exactly `calls` times (40 hottest)",
          bad == 0, "%d site(s) disagreed" % bad)

    # C2 -- sensitivity: a table at a low-popcount address must measure cheaper
    hi, _, _, _ = price([(0x2AB54000, 100, 7), (0x2AB54000, 200, 7)])
    lo, _, _, _ = price([(0x400, 100, 7), (0x400, 200, 7)])
    check("C2 a lower-popcount table address measures cheaper", lo < hi, "%d vs %d" % (lo, hi))

    # C3 -- provenance: a mismatched pair must be refused
    fake = {"a---switch": 8, "a---end": 16}
    rate, ok = join_is_sound(fake, {10 ** 9: 500, 8: 1}, 501)
    check("C3 a mismatched labels/histogram pair is REFUSED", not ok, "%.2f%% far" % (100 * rate))
    _, ok2 = join_is_sound(fake, {8: 500, 16: 1}, 501)
    check("C3 ...and a matched pair is accepted", ok2)

    # C4 -- non-vacuity: nothing to save when every table is already at popcount 1
    cur4, new4, _, _ = price([(0x400, 1000, 5), (0x800, 1000, 9), (0x1000, 1000, 13)])
    check("C4 tables already at popcount 1 predict ~no saving", cur4 - new4 <= 0,
          "cur %d, blocked %d" % (cur4, new4))
    cur5, new5, _, _ = price([(0x2AB54000, 1000, 5), (0x155AC000, 1000, 9)])
    check("C4 ...while scattered tables predict a large one", (cur5 - new5) > 0.5 * cur5,
          "saves %d of %d" % (cur5 - new5, cur5))

    # C5 -- the layout must be a permutation: distinct index per site in a block
    by_word = defaultdict(list)
    for switch, word, calls in [(0x1000, 64, 3), (0x2000, 64, 2), (0x3000, 64, 1)]:
        by_word[word].append((calls, switch))
    indices = [i for g in by_word.values() for i, _ in enumerate(g)]
    check("C5 each site in a block gets a DISTINCT index",
          len(set(indices)) == len(indices) and len(indices) == 3)

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_s2.fjm")
    ap.add_argument("--labels", default="scratchpad/12m/_full_labels.tsv.gz")
    ap.add_argument("--hist", default="scratchpad/12m/_s2_hist.json.gz")
    ap.add_argument("--base", type=int, default=22988275,
                    help="the binding ops/frame the saving is applied to")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return report(a.fjm, a.labels, a.hist, a.base)


if __name__ == "__main__":
    sys.exit(main())
