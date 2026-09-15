"""1e. The cache model of the instruction stream, per object and as a what-if curve.

Reads what the `mkprof3.py S` engine printed (the FJPROF3S lines in its log: per-stream
L1/L2/L3/DRAM split from a simulated i7-12700H P-core hierarchy, and the LRU stack-distance
histogram) plus its two per-line dumps (ip-stream accesses NOT served by L1; NOT served by L1 or
L2), joined to the object table and to the ip-stream touch histogram of the same run.

Three outputs:
  1. the level mix of the dependent chain, and the cycles/op it PREDICTS (5/16/65/300 cycles)
     -- to be checked against the measured cycles/op from `timeobj.py`. If they agree the model
     is trusted to price a lever before it is built; if not, something else is on the chain.
  2. per object: touches, L1 misses, L2 misses, and the chain cycles they imply -- the model's
     cost ranking, to be compared with the measured time ranking.
  3. the what-if curve: the fraction of instruction fetches an LRU cache of 2^k lines serves --
     what shrinking the working set by X buys, before anyone builds it.

    python scratchpad/12m/cachemodel.py <prof3S.log> <l1miss.bin> <l2miss.bin> <ip_touches.bin> <labels.tsv.gz> [--top N]
"""
import argparse
import bisect
import gzip
import re
import struct
from pathlib import Path

LAT = (5.0, 16.0, 65.0, 300.0)   # Golden Cove load-to-use, cycles: L1, L2, L3 (~), DRAM (~) -- the
                                 # textbook guess; override with --lat from tlbcost.c's packed column


def is_top(name):
    return not (name.startswith("f") and ":l" in name[:24])


def load_labels(path, w=32):
    names, addrs = [], []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if addr and is_top(name):
                try:
                    addrs.append(int(addr) // w)
                    names.append(name)
                except ValueError:
                    pass
    order = sorted(range(len(addrs)), key=lambda i: addrs[i])
    return [addrs[i] for i in order], [names[i] for i in order]


def load_u32(path):
    raw = Path(path).read_bytes()
    unit, n = struct.unpack_from("<QQ", raw, 0)
    return unit, n, memoryview(raw)[16:16 + 4 * n].cast("I")


def parse_log(path):
    txt = Path(path).read_text(encoding="utf-8", errors="replace")
    out = {"cache": {}, "thr": {}, "hist": {}}
    for m in re.finditer(r"FJPROF3S CACHE (\w+)\s+total=(\d+) L1=(\d+) .*? L2=(\d+) .*? L3=(\d+) .*? DRAM=(\d+)", txt):
        out["cache"][m.group(1)] = tuple(int(m.group(i)) for i in range(2, 7))
    for m in re.finditer(r"FJPROF3S STACKTHR (\w+)\s+lt768=(\d+) lt20480=(\d+) lt393216=(\d+) ge=(\d+)", txt):
        out["thr"][m.group(1)] = tuple(int(m.group(i)) for i in range(2, 6))
    for m in re.finditer(r"FJPROF3S STACKHIST (\w+)\s+([\d ]+)", txt):
        out["hist"][m.group(1)] = [int(x) for x in m.group(2).split()]
    out["tlb"] = {}
    for m in re.finditer(r"FJPROF3S TLB (\w+)\s+total=(\d+) DTLB=(\d+) .*? STLB=(\d+) .*? WALK=(\d+)", txt):
        out["tlb"][m.group(1)] = tuple(int(m.group(i)) for i in range(2, 6))
    m = re.search(r"FJPROF3S accesses=(\d+) distinct_lines=(\d+) fen_overflow=(\d)", txt)
    out["acc"] = tuple(int(m.group(i)) for i in range(1, 4)) if m else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("l1miss")
    ap.add_argument("l2miss")
    ap.add_argument("ip_touches")
    ap.add_argument("labels")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--dtlb", default="", help="per-line ip-stream L1-DTLB-miss dump (mkprof3 S with the TLB model)")
    ap.add_argument("--stlb", default="", help="per-line ip-stream STLB-miss (page walk) dump")
    ap.add_argument("--tlb-cost", default="7,30", help="cycles per DTLB miss (STLB hit), per page walk -- from tlbcost.c")
    ap.add_argument("--floor", type=float, default=6.0, help="cycles per op with everything L1/TLB-resident (the engine floor)")
    ap.add_argument("--lat", default="", help="measured L1,L2,L3,DRAM cycles per dependent load (tlbcost.c packed column x GHz)")
    ap.add_argument("--pages", type=int, default=0, help="words per page (1024 at 4-byte cells) to print the page concentration of the ip stream")
    a = ap.parse_args()
    tlb_cost = tuple(float(x) for x in a.tlb_cost.split(","))
    global LAT
    if a.lat:
        LAT = tuple(float(x) for x in a.lat.split(","))

    lg = parse_log(a.log)
    if lg["acc"]:
        print("accesses %s, distinct lines %s, fenwick overflow %d"
              % (format(lg["acc"][0], ","), format(lg["acc"][1], ","), lg["acc"][2]))
    print("")
    print("1. LEVEL MIX (simulated L1D 48K/12, L2 1.25M/10, L3 24M/12 exclusive) and predicted chain cost")
    for st in ("IP", "FLIP"):
        if st not in lg["cache"]:
            continue
        tot, l1, l2, l3, dr = lg["cache"][st]
        p = [l1 / tot, l2 / tot, l3 / tot, dr / tot]
        cyc = sum(pi * li for pi, li in zip(p, LAT))
        print("   %-4s  L1 %6.2f%%  L2 %6.2f%%  L3 %6.2f%%  DRAM %6.3f%%   ->  %.1f cycles/access at (%s)"
              % (st, 100 * p[0], 100 * p[1], 100 * p[2], 100 * p[3], cyc, "/".join("%d" % x for x in LAT)))
        if st == "IP":
            print("         the chain: predicted %.1f cycles/op from loads alone; add ~2 for the address arithmetic."
                  % cyc)
            print("         if every L3 hit became an L2 hit: %.1f cycles/op  (x%.2f)"
                  % (p[0] * LAT[0] + (p[1] + p[2]) * LAT[1] + p[3] * LAT[3],
                     cyc / (p[0] * LAT[0] + (p[1] + p[2]) * LAT[1] + p[3] * LAT[3])))
    ip_mem = None
    if "IP" in lg["cache"]:
        tot, l1, l2, l3, dr = lg["cache"]["IP"]
        ip_mem = (l1 * LAT[0] + l2 * LAT[1] + l3 * LAT[2] + dr * LAT[3]) / tot - LAT[0]
    for st in ("IP", "FLIP"):
        if st in lg["tlb"]:
            tt, d, s_, w = lg["tlb"][st]
            pen = (s_ * tlb_cost[0] + w * tlb_cost[1]) / tt
            print("   %-4s  TLB: L1 DTLB hit %6.2f%%  STLB hit %6.2f%%  page walk %6.3f%%   ->  +%.1f cycles/access at (%g/%g)"
                  % (st, 100.0 * d / tt, 100.0 * s_ / tt, 100.0 * w / tt, pen, tlb_cost[0], tlb_cost[1]))
            if st == "IP" and ip_mem is not None:
                print("         PREDICTED chain cycles/op = floor %.1f + cache misses %.1f + TLB %.1f = %.1f"
                      % (a.floor, ip_mem, pen, a.floor + ip_mem + pen))
    for st in ("IP", "FLIP"):
        if st in lg["thr"]:
            t = lg["thr"][st]
            s = float(sum(t))
            print("   %-4s  LRU stack-distance thresholds: <768 lines %.2f%%  <20480 %.2f%%  <393216 %.2f%%  beyond/cold %.3f%%"
                  % (st, 100 * t[0] / s, 100 * t[1] / s, 100 * t[2] / s, 100 * t[3] / s))
    print("   (set-associative minus fully-associative LRU = conflict misses; the L3 is exclusive so its")
    print("    effective size is L2+L3)")
    print("")

    # per-object join
    u1, n1, l1m = load_u32(a.l1miss)
    u2, n2, l2m = load_u32(a.l2miss)
    ut, nt, tch = load_u32(a.ip_touches)
    assert u1 == u2
    dt_m = load_u32(a.dtlb)[2] if a.dtlb else None
    st_m = load_u32(a.stlb)[2] if a.stlb else None
    taddr, tname = load_labels(a.labels)
    T, M1, M2, D1, W1 = {}, {}, {}, {}, {}
    for i in range(n1):
        c1 = l1m[i]
        c2 = l2m[i]
        cd = dt_m[i] if dt_m is not None else 0
        cw = st_m[i] if st_m is not None else 0
        # touches come from the mkprof2 histogram at `ut` words/unit; sum the units of this line
        wa = i * u1
        t = 0
        for k in range(u1 // ut):
            idx = (wa // ut) + k
            if idx < nt:
                t += tch[idx]
        if not (t or c1 or c2 or cd or cw):
            continue
        j = bisect.bisect_right(taddr, wa) - 1
        obj = tname[j] if j >= 0 else "(before first label)"
        T[obj] = T.get(obj, 0) + t
        M1[obj] = M1.get(obj, 0) + c1
        M2[obj] = M2.get(obj, 0) + c2
        D1[obj] = D1.get(obj, 0) + cd
        W1[obj] = W1.get(obj, 0) + cw
    tot_t = float(sum(T.values()))
    tot_m1 = float(sum(M1.values())) or 1.0
    tot_m2 = float(sum(M2.values())) or 1.0
    tot_d1 = float(sum(D1.values())) or 1.0

    def cost(o):
        t, m1, m2, d1, w1 = T.get(o, 0), M1.get(o, 0), M2.get(o, 0), D1.get(o, 0), W1.get(o, 0)
        return (t * a.floor + m1 * (LAT[1] - LAT[0]) + m2 * (LAT[2] - LAT[1])
                + d1 * tlb_cost[0] + w1 * tlb_cost[1])

    tot_cost = sum(cost(o) for o in T) or 1.0
    print("2. PER OBJECT: the model's cost ranking of the instruction stream (compare with timeobj.py)")
    print("%5s %8s %9s %8s %8s %8s %8s %9s  %s" % ("rank", "cost%", "touches%", "L1hit", "L2miss%", "DTLBhit", "DTLBms%", "cyc/touch", "object"))
    cum = 0.0
    for k, o in enumerate(sorted(T, key=cost, reverse=True)[:a.top]):
        t, m1, m2, d1 = T.get(o, 0), M1.get(o, 0), M2.get(o, 0), D1.get(o, 0)
        c = cost(o)
        cum += 100.0 * c / tot_cost
        print("%5d %7.2f%% %8.2f%% %7.1f%% %7.2f%% %7.1f%% %7.2f%% %9.1f  %s"
              % (k, 100.0 * c / tot_cost, 100.0 * t / tot_t, 100.0 * (1 - m1 / t) if t else 0.0,
                 100.0 * m2 / tot_m2, 100.0 * (1 - d1 / t) if t else 0.0, 100.0 * d1 / tot_d1,
                 c / t if t else 0.0, o[:48]))
    print("      top %d objects = %.1f%% of the modelled chain cost" % (a.top, cum))
    print("")

    if a.pages:
        per_page = {}
        for i in range(nt):
            c = tch[i]
            if c:
                pg = (i * ut) // a.pages
                per_page[pg] = per_page.get(pg, 0) + c
        vals = sorted(per_page.values(), reverse=True)
        tot = float(sum(vals))
        print("2b. PAGE CONCENTRATION of the instruction stream (%s words/page): %s pages touched"
              % (format(a.pages, ","), format(len(vals), ",")))
        acc = 0.0
        marks = [0.5, 0.8, 0.9, 0.95, 0.99]
        mi = 0
        for k, v in enumerate(vals, 1):
            acc += v
            while mi < len(marks) and acc >= marks[mi] * tot:
                print("    %4.0f%% of fetches in %7s pages%s" % (marks[mi] * 100, format(k, ","),
                      "   <- L1 DTLB is 96" if k <= 96 else "   <- STLB is 2,048" if k <= 2048 else "   <- beyond the STLB"))
                mi += 1
        print("    (a layout that put the 90%% set in <= 2,048 pages would make every fetch an STLB hit at worst)")
        print("")
    print("3. WHAT-IF: fraction of instruction fetches an LRU cache of 2^k lines would serve")
    if "IP" in lg["hist"]:
        h = lg["hist"]["IP"]
        s = float(sum(h))
        acc = 0.0
        for k in range(len(h) - 1):
            acc += h[k]
            if 8 <= k <= 22:
                print("   %2d  %9s lines = %8.2f MB   %6.2f%%%s"
                      % (k + 1, format(1 << (k + 1), ","), (1 << (k + 1)) * 64 / 2**20, 100 * acc / s,
                         "   <- L1 (768)" if k + 1 == 10 else "   <- L2 (20,480)" if k + 1 == 15 else
                         "   <- L3 (393,216)" if k + 1 == 19 else ""))
        print("   cold (first touch): %.3f%%" % (100 * h[-1] / s))
    print("")
    print("READ THIS AS: (1) if the predicted cycles/op matches the measured one, the model prices")
    print("levers; (2) is what to shrink; (3) is how much shrinking it pays.")


if __name__ == "__main__":
    raise SystemExit(main())
