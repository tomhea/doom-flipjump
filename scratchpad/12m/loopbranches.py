"""loopbranches -- count the conditional branches in a _fjcore.pyd's hottest loop, from the
disassembly, so "11 branches per op -> N" is a fact about the binary and not about the C.

    python scratchpad/12m/loopbranches.py <pyd> [--dump]

Method: dumpbin /disasm the DLL, find every backward conditional jump (a loop back-edge), and for
each, the straight-line window from its target to itself; report the window with the most memory
loads that looks like the fj op (three loads, one store, a shift by 5 or a variable shift). The
count of Jcc instructions in that window is the branches per op on the hot path. Not a proof -
the compiler may lay the loop out with the cold blocks interleaved - so --dump prints the window
for a human to read."""
import re
import subprocess
import sys
from pathlib import Path

VCVARS = r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"


def disasm(pyd):
    cmd = 'cmd /c ""%s" >nul 2>&1 && dumpbin /nologo /disasm "%s""' % (VCVARS, pyd)
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
    lines = []
    for line in out.splitlines():
        m = re.match(r"\s+([0-9A-F]{16}):\s+((?:[0-9A-F]{2} )+)\s*(\S+)\s*(.*)$", line)
        if m:
            lines.append((int(m.group(1), 16), m.group(3).lower(), m.group(4).strip()))
    return lines


JCC = re.compile(r"^j(?!mp$)[a-z]+$")


def main():
    pyd = sys.argv[1]
    dump = "--dump" in sys.argv
    lines = disasm(pyd)
    if not lines:
        raise SystemExit("no disassembly (is dumpbin on the path via vcvars64?)")
    index = {addr: i for i, (addr, _, _) in enumerate(lines)}
    found = []
    for i, (addr, mnem, ops) in enumerate(lines):
        if not JCC.match(mnem):
            continue
        m = re.search(r"([0-9A-F]{16})", ops)
        if not m:
            continue
        target = int(m.group(1), 16)
        if target >= addr or target not in index:
            continue
        window = lines[index[target]:i + 1]
        if len(window) > 160 or any(mn in ("call", "ret") for _, mn, _ in window):
            continue
        magic = sum(1 for _, mn, op in window if "BB67AE85" in op)
        if not magic:
            continue
        jccs = sum(1 for _, mn, _ in window if JCC.match(mn))
        loads = sum(1 for _, mn, op in window if mn in ("mov", "movzx") and "ptr [" in op.split(",", 1)[-1])
        stores = sum(1 for _, mn, op in window if mn == "mov" and op.split(",")[0].strip().endswith("]"))
        shr = [op for _, mn, op in window if mn in ("shr", "shrx")]
        width = {"5": 32, "4": 16, "3": 8}.get(next((o.split(",")[-1] for o in shr if o.split(",")[-1] in "543"), "?"), "?")
        found.append((target, addr, len(window), jccs, loads, stores, magic, width, window))
    if not found:
        raise SystemExit("no loop window with the garbage-magic compare and no calls was found")
    print("%s: %d candidate hot-loop windows (backward Jcc, no calls, compares the garbage magic)"
          % (Path(pyd).name, len(found)))
    for target, addr, n, jccs, loads, stores, magic, width, window in found:
        print("  %016X..%016X  w=%-3s %3d instr  %2d Jcc/op  %d loads %d stores  %d magic cmps"
              % (target, addr, width, n, jccs, loads, stores, magic))
        if dump:
            for a, mn, op in window:
                print("      %016X  %-8s %s" % (a, mn, op))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
