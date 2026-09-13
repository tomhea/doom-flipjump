"""1a. The instruction stream versus the flip targets: which one is the chain paying for?

Reads the two cache-line histograms `mkprof2.py` dumps (FJPROF_DUMP = ip-stream, FJPROF_DUMP_FLIP
= flip targets) and answers: how big is each stream's footprint, how concentrated is each, and
how much do they overlap. The dependent chain -- the thing that sets ops/s -- lives ONLY in the
ip-stream. If that stream is small, making IT resident is the lever and the flip targets can
stay scattered; if it is the bulk, the whole-program footprint is the problem after all.

    python scratchpad/12m/splitanalyze.py <ip.bin> <flip.bin>
"""
import struct
import sys
from pathlib import Path

LINE = 64


def load(path):
    raw = Path(path).read_bytes()
    unit, n = struct.unpack_from("<QQ", raw, 0)
    assert unit == 8, "expected cache-line granularity, got %d words/unit" % unit
    return memoryview(raw)[16:].cast("I"), n


def curve(counts, n, label):
    tot = 0
    touched = []
    for i in range(n):
        c = counts[i]
        if c:
            tot += c
            touched.append(c)
    touched.sort(reverse=True)
    print("%-14s touches %14s   distinct lines %9s = %7.2f MB"
          % (label, format(tot, ","), format(len(touched), ","), len(touched) * LINE / 2**20))
    acc = 0
    marks = [0.5, 0.8, 0.9, 0.95, 0.99, 1.0]
    mi = 0
    for k, c in enumerate(touched, 1):
        acc += c
        while mi < len(marks) and acc >= marks[mi] * tot:
            print("    %4.0f%% of its touches in %9s lines = %7.2f MB"
                  % (marks[mi] * 100, format(k, ","), k * LINE / 2**20))
            mi += 1
    return tot, len(touched)


def main():
    ip, n = load(sys.argv[1])
    fl, n2 = load(sys.argv[2])
    assert n == n2
    print("array: %s lines" % format(n, ","))
    print("")
    tip, lip = curve(ip, n, "IP-STREAM")
    print("")
    tfl, lfl = curve(fl, n, "FLIP-TARGETS")
    print("")
    both = sum(1 for i in range(n) if ip[i] and fl[i])
    only_ip = lip - both
    only_fl = lfl - both
    print("OVERLAP: %s lines touched by both streams; %s ip-only; %s flip-only"
          % (format(both, ","), format(only_ip, ","), format(only_fl, ",")))
    print("union footprint: %s lines = %.2f MB" % (format(lip + lfl - both, ","),
                                                   (lip + lfl - both) * LINE / 2**20))
    print("")
    print("READ THIS AS: the chain is the IP-STREAM curve. If its 90%% line count is a few thousand")
    print("(< ~1 MB), the dependent load is L2-servable once that stream is packed, regardless of")
    print("how the flip targets are laid out. If it is tens of thousands, the instruction stream")
    print("itself is the problem and packing it is the whole game.")


if __name__ == "__main__":
    raise SystemExit(main())
