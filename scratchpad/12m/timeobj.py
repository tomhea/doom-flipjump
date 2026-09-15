"""1d. TIME by object -- the ranking in the currency (ms/frame), not touches or footprint.

Reads the (word address, rdtsc) samples the `mkprof3.py T` engine records every 64 ops and
credits each sample's tick delta to the top-level object its address falls in. Two numbers per
object: its share of the run's time, and its ns/op -- which is the cache level its dependent
loads are served from (L1 ~1.1 ns, L2 ~3.5 ns, L3 ~14 ns at 4.6 GHz).

Windows containing an IO callback, an interrupt or a context switch carry a huge delta; they are
trimmed at `--trim` times the median (reported), and the trimmed total is checked against the
engine's own net compute time.

    python scratchpad/12m/timeobj.py <time.bin> <labels.tsv.gz> [--top N] [--ghz F] [--net-secs S]
"""
import argparse
import bisect
import gzip
import struct
from pathlib import Path


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("time_bin")
    ap.add_argument("labels")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--ghz", type=float, default=0.0, help="core clock during the run, for cycles/op")
    ap.add_argument("--net-secs", type=float, default=0.0, help="engine net compute seconds, for the check")
    ap.add_argument("--trim", type=float, default=50.0, help="drop deltas above this multiple of the median")
    a = ap.parse_args()

    raw = Path(a.time_bin).read_bytes()
    n, every, tsc_hz = struct.unpack_from("<QQQ", raw, 0)
    off = 24
    ip = memoryview(raw)[off:off + 4 * n].cast("I")
    tsc = memoryview(raw)[off + 4 * n:off + 4 * n + 8 * n].cast("Q")
    print("samples %s every %d ops; tsc %.3f GHz" % (format(n, ","), every, tsc_hz / 1e9))

    taddr, tname = load_labels(a.labels)
    print("labels: %s top-level objects" % format(len(taddr), ","))

    deltas = [tsc[i] - tsc[i - 1] for i in range(1, n)]
    srt = sorted(deltas)
    med = srt[len(srt) // 2]
    cut = med * a.trim
    ticks_all = sum(deltas)
    ticks = {}
    cnt = {}
    dropped_t = 0
    dropped_n = 0
    for i in range(1, n):
        d = deltas[i - 1]
        if d > cut:
            dropped_t += d
            dropped_n += 1
            continue
        wa = ip[i]
        k = bisect.bisect_right(taddr, wa) - 1
        obj = tname[k] if k >= 0 else "(before first label)"
        ticks[obj] = ticks.get(obj, 0) + d
        cnt[obj] = cnt.get(obj, 0) + 1
    tot = sum(ticks.values())
    ops = sum(cnt.values()) * every
    print("median window %d ticks (%.2f ns/op); trimmed %s windows = %.1f%% of ticks (IO, interrupts)"
          % (med, med / tsc_hz * 1e9 / every, format(dropped_n, ","), 100.0 * dropped_t / ticks_all))
    print("kept: %s ops in %.3f s  ->  %.2f ns/op  = %.1f M ops/s%s"
          % (format(ops, ","), tot / tsc_hz, tot / tsc_hz / ops * 1e9, ops / (tot / tsc_hz) / 1e6,
             ("  = %.1f cycles/op at %.2f GHz" % (tot / ops * a.ghz * 1e9 / tsc_hz, a.ghz)) if a.ghz else ""))
    if a.net_secs:
        print("check: engine net compute %.3f s vs kept ticks %.3f s (%.1f%%)"
              % (a.net_secs, tot / tsc_hz, 100.0 * (tot / tsc_hz) / a.net_secs))
    print("")
    print("BY TIME (share of the kept ticks; ns/op = the level the object's chain loads come from)")
    print("%5s %8s %9s %10s %9s  %s" % ("rank", "time%", "ops%", "ns/op", "cyc/op" if a.ghz else "", "object"))
    cum = 0.0
    for k, o in enumerate(sorted(ticks, key=lambda o: ticks[o], reverse=True)[:a.top]):
        t = ticks[o]
        oo = cnt[o] * every
        ns = t / tsc_hz / oo * 1e9
        cum += 100.0 * t / tot
        print("%5d %7.2f%% %8.2f%% %10.2f %9s  %s"
              % (k, 100.0 * t / tot, 100.0 * oo / ops, ns, ("%.1f" % (ns * a.ghz)) if a.ghz else "", o[:58]))
    print("      top %d objects = %.1f%% of the time" % (a.top, cum))
    print("")
    print("SLOWEST (ns/op) among objects with >= 1%% of the ops")
    big = [o for o in ticks if cnt[o] * every >= 0.01 * ops]
    for k, o in enumerate(sorted(big, key=lambda o: ticks[o] / cnt[o], reverse=True)[:12]):
        t = ticks[o]
        oo = cnt[o] * every
        print("%5d %7.2f%% %8.2f%% %10.2f  %s" % (k, 100.0 * t / tot, 100.0 * oo / ops, t / tsc_hz / oo * 1e9, o[:58]))
    print("")
    print("READ THIS AS: time% is what a lever on that object can win at most; ns/op says WHY it")
    print("costs -- ~1 ns is L1-resident (only fewer ops help), ~3-4 ns is L2, >10 ns is L3-bound")
    print("(footprint/locality is the lever). A big object at ~1 ns/op is NOT a cache problem.")


if __name__ == "__main__":
    raise SystemExit(main())
