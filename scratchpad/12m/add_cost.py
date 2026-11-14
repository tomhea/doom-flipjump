"""What one 32-bit addition costs in flip-jumps on the installed flipjump (README / docs/story.md quote it).

usage (repo root, the pinned flipjump on PYTHONPATH): python scratchpad/12m/add_cost.py [--k 200] [--seeds 1 2 3]

Assembles at w=32 (the game's width) a program of K `hex.add 8, a_i, b_i` on random operands and the same program with
none, and prints (ops(K) - ops(0)) / K, once with the stl tables where the assembler puts them and once with
--pool-tables (the tables in blocks right above the program, where they are cheap to arm -- the game's blocking pass
places its tables the same cheap way). The control: two known sums are printed by the fj program and checked here
(a wrong sum fails the run), so the count is of additions that add.
"""
from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CHECK = ((0x89ABCDEF, 0x12345678), (0xFFFFFFFF, 0x00000001))


def fj(path: Path, *extra: str) -> tuple[int, str]:
    code = ("import sys; sys.argv=['fj','-w','32']+sys.argv[1:]; "
            "from flipjump.flipjump_cli import main; main()")
    out = subprocess.run([sys.executable, "-c", code, str(path), *extra], capture_output=True, text=True,
                         check=True).stdout
    m = re.search(r"\(([\d,]+) ops executed\)", out)
    if not m:
        raise SystemExit("no op count in fj's output:\n" + out)
    return int(m.group(1).replace(",", "")), out


def program(pairs, prints: bool) -> str:
    body = ["stl.startup"]
    for i in range(len(pairs)):
        body.append("hex.add 8, a%d, b%d" % (i, i))
        if prints:
            body.append("hex.print_as_digit 8, a%d, 0" % i)
    body += ["stl.loop", "hex.init"]
    for i, (a, b) in enumerate(pairs):
        body += ["a%d: hex.vec 8, 0x%08x" % (i, a), "b%d: hex.vec 8, 0x%08x" % (i, b)]
    return "\n".join(body) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--k", type=int, default=200)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    a = ap.parse_args()
    import flipjump
    print("flipjump", flipjump.__version__, flipjump.__file__)
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for mode, extra in (("tables as assembled", ()), ("--pool-tables", ("--pool-tables",))):
            chk = d / "check.fj"
            chk.write_text(program(CHECK, True), newline="\n")
            _n, out = fj(chk, *extra)
            want = "".join("%08x" % ((x + y) & 0xFFFFFFFF) for x, y in CHECK)
            if want not in out:
                print("CONTROL FAIL (%s): expected %s in fj's output:\n%s" % (mode, want, out))
                return 1
            empty = d / "add_0.fj"
            empty.write_text(program([], False), newline="\n")
            base, _ = fj(empty, *extra)
            per = []
            for s in a.seeds:
                r = random.Random(s)
                f = d / ("add_%d.fj" % s)
                f.write_text(program([(r.getrandbits(32), r.getrandbits(32)) for _ in range(a.k)], False),
                             newline="\n")
                n, _ = fj(f, *extra)
                per.append((n - base) / a.k)
            print("%-20s control PASS (%s); %d additions x %d seeds: %s flip-jumps per 32-bit addition"
                  % (mode, want, a.k, len(a.seeds), " / ".join("%.1f" % p for p in per)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
