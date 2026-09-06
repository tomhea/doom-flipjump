"""Rank every paddable label by SPEED GAINED PER BYTE SPENT.

The two numbers a pad trades, and the campaign has now been burned by confusing them twice:

  SPEED  = sum over HOT wflip sites of visits * (popcount now - popcount aligned).
           Comes from the census+profile join. Sees only the ~34k values a frame actually walks.
  BYTES  = TOTAL expansions of the macro that defines the label, times the average slack the
           wider pad inserts, times 8 (one op is 2w = 8 bytes at w=32).
           Comes from the LABEL TABLE, which sees all of them. FINDINGS Y: these differ by 1800x
           for bit.exact_xor, which is why pricing that pad from the census alone overflowed the
           address space.

So the ratio this file ranks on is ops-per-frame saved per byte of image, and a family is only a
good pad when it is hot AND rare. That is a different order from either column alone.

TWO CORRECTIONS BAKED IN:
  * `expansions` is counted as LINES OF THE LABEL TABLE carrying that family, not mentions/2 --
    the label table has exactly one row per expansion per label, so no divisor is guessed.
  * current alignment Q is MEASURED (the largest power of two dividing every observed op index of
    the family), so the slack a wider pad adds is (P-Q)/2, not P/2. Pricing a 64 over an existing
    32 as if it were over nothing doubles the quoted cost.

⚠ KNOWN OVERSTATEMENT -- CONSECUTIVE LABELS. Each family is scored as if it could be aligned on
its own. When a macro defines several labels ONE OP APART -- `xor_hex_to_flip_ptr`'s
after_flip_bit0..3, which sit at base+0..+3 behind a single `pad 4` -- only the FIRST can be
aligned, and the others inherit base+1, +2, +3. The tool then reports each of them saving its own
low bits, and the sum is unreachable by any single pad. Read multi-row families as ONE row (the
lowest-addressed label) plus a bonus that is not guaranteed. Rows whose macro appears more than
once in the table are exactly the ones to check.

NEGATIVE CONTROLS (R9), all run by --selftest:
  1. vacuity   -- pad P == measured alignment Q must score exactly 0 saving.
  2. bit mask  -- a synthetic family at a known address must lose exactly the bits `pad P` clears.
  3. rarity    -- two families with identical speed must rank by expansions, the common one LAST.

    python scratchpad/12m/padrank.py --census atlas/P7B.census.json.gz \
        --hist atlas/P7B.h57_1.json --labels atlas/P7B.labels.tsv.gz --top 50
"""
import argparse
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

OPBITS = 6                      # one op is 2w = 64 bits at w=32, so op_index = bit_addr >> 6
BYTES_PER_OP = 8
IMAGE_BYTES = 15168954          # the P7-11 certified .fjm, for the "+% of image" column
SWEEP_MEDIAN = 16038392         # P7-11's 260-frame ca2_sweep median -- THE SHIP CRITERION

# ⚠ THE FRAME THIS TOOL PREDICTS ON IS NOT THE ONE THE CAMPAIGN SHIPS ON.
# Every visit count comes from ONE profiled viewpoint's IP histogram (h57_1 = the 6th of 8), and
# that viewpoint is deliberately heavy: 17,130,098 ops against a 16,038,392 sweep median on
# P7-11, and 20,204,970 against 18,982,338 on BASE -- +6.8% and +6.4%. Savings scale roughly with
# visits, so a figure here is ~6% ABOVE the median delta a gate will report. Quote both.

# Gate verdicts already on the record (LEDGER.md / FINDINGS Z). The census cannot see the
# whole-image re-roll a propagating pad causes, so for these rows the PREDICTION IS KNOWN WRONG
# and the measured sign is what counts. Printed so nobody re-proposes a pad the sweep refuted.
KNOWN = {
    "hex.exact_xor :: switch": "GATED 256 optimal; 512 measured +316,510 WORSE",
    "hex.cmp :: ret": "GATED 64 optimal; 128 measured worse (P7-12)",
    "hex.add_mul :: ret": "GATED 64 optimal; 128 measured worse (P7-12)",
    "hex.triple_exact_xor :: first_flip": "GATED 128 optimal; 256 measured worse (P7-12)",
    "hex.double_exact_xor :: first_flip": "GATED 64 optimal; 128 measured worse (P7-12)",
    "hex.if_flags :: switch": "GATED 64 optimal; 128 measured worse (P7-12)",
    "hex.add.clear_carry :: ret": "GATED 64 optimal; 128 measured worse",
    "hex.sub.clear_carry :: ret": "GATED 64 optimal; 128 measured worse",
    "hex.tables.jump_to_table_entry :: return": "GATED 64 optimal; 128 measured worse",
    "bit.exact_xor :: base_jump_label": "DO NOT PAD -- 600k expansions overflowed the assembler",
}

# `s3:l8:hex.pointers.ptr_init(2)` -> `hex.pointers.ptr_init`
SEG = re.compile(r"^[sf]\d+:l\d+:(.*?)(?:\(\d+\))?$")
# `rep4:hex.triple_exact_xor` is ONE macro unrolled, not seven macros. The atlas was wrong
# about this once and hid 1.8M ops; here it would split both columns and understate bytes.
REP = re.compile(r"^(?:rep\d+:)+")


def family_of(name):
    """(macro, local) for a label row. Top-level labels report macro ''."""
    parts = name.split("---")
    local = parts[-1]
    if len(parts) == 1:
        return "", local
    m = SEG.match(parts[-2])
    return REP.sub("", m.group(1) if m else parts[-2]), local


def align_of(op_indices):
    """the largest power of two dividing every one of them -- the pad already in force."""
    acc = 0
    for v in op_indices:
        acc |= v
        if acc & 1:
            return 1
    return (acc & -acc) if acc else 1 << 30


def score(addr_visits, pad, q):
    """ops/frame saved if this family were aligned to `pad` ops instead of `q`."""
    if pad <= q:
        return 0
    mask = ~((pad - 1) << OPBITS)
    out = 0
    for addr, visits in addr_visits:
        out += visits * (max(1, bin(addr).count("1")) - max(1, bin(addr & mask).count("1")))
    return out


def rank(fams, pads):
    """fams: key -> dict(addr_visits, expansions, visits). Returns the best pad per family."""
    rows = []
    for key, f in fams.items():
        q = align_of([a >> OPBITS for a, _ in f["addr_visits"]])
        best = None
        for p in pads:
            if p <= q:
                continue
            sv = score(f["addr_visits"], p, q)
            if sv <= 0:
                continue
            ops = f["expansions"] * (p - q) // 2
            by = ops * BYTES_PER_OP
            r = sv / by if by else 0.0
            if best is None or r > best[0]:
                best = (r, p, sv, ops, by)
        if best:
            rows.append((best[0], key, q, best[1], best[2], best[3], best[4], f["visits"]))
    rows.sort(reverse=True)
    return rows


# ------------------------------------------------------------------------------- selftest

def selftest():
    ok = True
    A = 1000 << OPBITS                                   # op index 1000 = 0b1111101000
    fam = {"addr_visits": [(A, 100)], "expansions": 10, "visits": 100}

    q = align_of([1000])
    ok &= (q == 8)
    print("  measured alignment of op 1000 : %d   %s" % (q, "ok" if q == 8 else "!! want 8"))

    v = score(fam["addr_visits"], 8, 8)
    ok &= (v == 0)
    print("  CONTROL 1 vacuity  pad==align  : %d   %s" % (v, "ok" if v == 0 else "!! want 0"))

    # pad 64 clears op bits 0..5 of 1000 = 0b101000 -> two set bits, x100 visits
    v = score(fam["addr_visits"], 64, 8)
    ok &= (v == 200)
    print("  CONTROL 2 bit mask pad 64      : %d   %s" % (v, "ok" if v == 200 else "!! want 200"))

    hot = {"addr_visits": [(A, 100)], "expansions": 10000, "visits": 100}
    rows = rank({"rare": fam, "common": hot}, [64])
    order = [r[1] for r in rows]
    ok &= (order == ["rare", "common"])
    print("  CONTROL 3 rarity ranks first   : %s   %s"
          % (order, "ok" if order == ["rare", "common"] else "!! wrong order"))
    print("")
    print("SELFTEST %s" % ("PASS" if ok else "!! FAIL"))
    raise SystemExit(0 if ok else 1)


# ------------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--census")
    ap.add_argument("--hist")
    ap.add_argument("--labels")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--pads", default="16,32,64,128,256,512,1024")
    ap.add_argument("--min-visits", type=int, default=200)
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    for need in ("census", "hist", "labels"):
        if not getattr(a, need):
            raise SystemExit("--%s is required" % need)
    pads = [int(x) for x in a.pads.split(",")]

    payload = json.load(gzip.open(a.census, "rt", encoding="utf-8"))
    bases, values = payload["sites"], payload["values"]
    hj = json.load(open(a.hist))
    hist = {int(k): v for k, v in hj["hist"].items()}
    shift = hj["bucket_bits"]
    frame = sum(hist.values())

    val_visits = defaultdict(int)
    for (base, _pc), v in zip(bases, values):
        n = hist.get(base >> shift, 0)
        if n:
            val_visits[v] += n
    print("census %s sites, %s hot distinct values, frame %s ops"
          % (format(len(values), ","), format(len(val_visits), ","), format(frame, ",")))

    fams = {}
    expansions = defaultdict(int)
    matched = 0
    with gzip.open(a.labels, "rt", encoding="utf-8") as f:
        for line in f:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            macro, local = family_of(name)
            key = "%s :: %s" % (macro, local) if macro else local
            expansions[key] += 1
            ad = int(addr)
            vis = val_visits.get(ad)
            if vis:
                matched += vis
                d = fams.get(key)
                if d is None:
                    d = fams[key] = {"addr_visits": [], "expansions": 0, "visits": 0}
                d["addr_visits"].append((ad, vis))
                d["visits"] += vis
    for k, d in fams.items():
        d["expansions"] = expansions[k]
    hotvis = sum(val_visits.values())
    print("label table: %s rows, %s families; %s of %s hot visits (%.1f%%) resolve to a label"
          % (format(sum(expansions.values()), ","), format(len(expansions), ","),
             format(matched, ","), format(hotvis, ","), 100.0 * matched / max(1, hotvis)))
    print("")

    fams = {k: d for k, d in fams.items() if d["visits"] >= a.min_visits}
    rows = rank(fams, pads)

    hdr = ("%-4s %-46s %4s %5s %9s %8s %11s %11s %7s"
           % ("#", "macro :: label", "now", "pad", "opssaved", "expans", "bytes", "cum.bytes",
              "ops/KB"))
    lines = [hdr, "-" * len(hdr)]
    tot_s = tot_b = 0
    fresh_s = fresh_b = fresh_n = 0
    notes = []
    for i, (r, key, q, p, sv, ops, by, _vis) in enumerate(rows[:a.top], 1):
        tot_s += sv
        tot_b += by
        why = KNOWN.get(key, "")
        if why:
            notes.append("%2d  %-46s %s" % (i, key[:46], why))
        else:
            fresh_s += sv
            fresh_b += by
            fresh_n += 1
        lines.append("%-4d %-46s %4s %5d %9s %8s %11s %11s %7.1f%s"
                     % (i, key[:46], (q if q < (1 << 20) else "-"), p, format(sv, ","),
                        format(expansions[key], ","), format(by, ","), format(tot_b, ","),
                        r * 1024, "  <-- refuted" if why else ""))
    lines.append("-" * len(hdr))
    lines.append("%-4s %-46s %4s %5s %9s %8s %11s %11s %7.1f"
                 % ("", "TOTAL of the %d" % min(a.top, len(rows)), "", "", format(tot_s, ","),
                    "", format(tot_b, ","), "", (tot_s / tot_b * 1024) if tot_b else 0))
    scale = SWEEP_MEDIAN / frame
    lines.append("")
    lines.append("PREDICTED ON the %s-op profiled viewpoint (%s), NOT on the sweep median."
                 % (format(frame, ","), Path(a.hist).stem))
    lines.append("  the %d together   : %s ops = %.2f%% of that viewpoint"
                 % (min(a.top, len(rows)), format(tot_s, ","), 100.0 * tot_s / frame))
    lines.append("  scaled to the %s-op MEDIAN (x%.4f): ~%s ops = %.2f%%"
                 % (format(SWEEP_MEDIAN, ","), scale, format(int(tot_s * scale), ","),
                    100.0 * tot_s * scale / SWEEP_MEDIAN))
    lines.append("  space             : %s bytes = %+.1f%% of a %s-byte image"
                 % (format(tot_b, ","), 100.0 * tot_b / IMAGE_BYTES, format(IMAGE_BYTES, ",")))
    lines.append("")
    lines.append("EXCLUDING the %d rows a gate has already refuted: %d pads, %s ops on the "
                 "viewpoint (~%s on the median) for %s bytes"
                 % (len(notes), fresh_n, format(fresh_s, ","), format(int(fresh_s * scale), ","),
                    format(fresh_b, ",")))
    lines.append("  = %.2f%% of the median frame for %+.2f%% of the image"
                 % (100.0 * fresh_s * scale / SWEEP_MEDIAN, 100.0 * fresh_b / IMAGE_BYTES))
    if notes:
        lines.append("")
        lines.append("ALREADY RULED ON BY A SWEEP -- the prediction above is known wrong for these:")
        lines += ["  " + n for n in notes]
    out = "\n".join(lines)
    print(out)
    if a.out:
        Path(a.out).write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
