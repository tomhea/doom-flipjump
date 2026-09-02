"""Negative control for the CELL_BITS decoder table (R9).

tests/unit/test_cell_bits.py claims that a pointer program is still correct at CELL_BITS 8, 12 and
16. This checks the claim can fail: each mutation below breaks the table arithmetic on purpose and
must be REJECTED.

Why this is not optional here: none of these crashes. The decoder table turns "where we landed"
into bits, so an off-by-one in the nibble/bit selection silently xors a value into the WRONG hex of
read_byte, and an arming flip of the wrong bit lands on the wrong table entry entirely. Both come
back as a wrong digit.

Two of the mutations are inert at the default width by construction -- they only bite at 12 or 16 --
which is the point of testing all three widths rather than just the default.
"""

import subprocess
import sys
from pathlib import Path

WORKTREE = Path("C:/Users/tomhe/Documents/flipjump-wide")
STL = WORKTREE / "flipjump" / "stl"
RUNLIB = STL / "runlib.fj"
BASIC = STL / "hex" / "pointers" / "basic_pointers.fj"
FROM_PTR = STL / "hex" / "pointers" / "xor_from_pointer.fj"
TO_PTR = STL / "hex" / "pointers" / "xor_to_pointer.fj"
NL = chr(10)
TIMEOUT = 1800
TOUCHED = (RUNLIB, BASIC, FROM_PTR, TO_PTR)

ENTRY = "                d==0 ? 0 : (.read_byte + (((#d)-1)/4)*dw + dbit + ((#d)-1)%4), "

MUTATIONS = [
    ("M1 the table is sized from a literal 256 instead of CELL_BITS", BASIC,
     "            rep(1<<.CELL_BITS, d) stl.fj ", "            rep(256, d) stl.fj ",
     "at 12/16 the table is too short for the entries the slot can reach"),
    ("M2 the table is no longer aligned to its own size", BASIC,
     "            pad 1<<.CELL_BITS", "            pad 256",
     "the table does not start at op 2^CELL_BITS, so entry V is not at V"),
    ("M3 nibble selection off by one hex", BASIC,
     ENTRY, "                d==0 ? 0 : (.read_byte + ((#d)/4)*dw + dbit + ((#d)-1)%4), ",
     "high bits land in the wrong hex of read_byte"),
    ("M4 bit-in-nibble selection off by one", BASIC,
     ENTRY, "                d==0 ? 0 : (.read_byte + (((#d)-1)/4)*dw + dbit + (#d)%4), ",
     "every decoded bit is one position out"),
    ("M5 the arming flip still adds 256, not 2^CELL_BITS", FROM_PTR,
     "            wflip hex.pointers.to_flip, dbit+hex.pointers.CELL_BITS" + NL
     + NL + "            // 2.  *(ptr+w) ^= 2^CELL_BITS",
     "            wflip hex.pointers.to_flip, dbit+8" + NL
     + NL + "            // 2.  *(ptr+w) ^= 2^CELL_BITS",
     "the slot lands 2^CELL_BITS-256 entries away from its own"),
    ("M6 the read destination is not cleared across the whole cell", FROM_PTR,
     "            hex.zero hex.pointers.CELL_BITS/4, hex.pointers.read_byte",
     "            hex.zero 2, hex.pointers.read_byte",
     "a wide read keeps the previous read's high hexes"),
    ("M7 zero_ptr clears only two hexes of a wider cell", TO_PTR,
     "            rep(hex.pointers.CELL_BITS/4, i) .xor_hex_to_flip_ptr hex+i*dw, 4*i",
     "            rep(2, i) .xor_hex_to_flip_ptr hex+i*dw, 4*i",
     "the write side stops matching the read side -- section 0.1"),
    ("M8 CELL_BITS is declared after the file that uses it", RUNLIB,
     "        CELL_BITS = 8", "        CELL_BITS = 4",
     "a 4-bit cell cannot hold the byte the programs store"),
]


def run_tests():
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/test_cell_bits.py", "-q", "--no-header", "-x"],
            cwd=str(WORKTREE), capture_output=True, timeout=TIMEOUT, text=True)
    except subprocess.TimeoutExpired:
        return False, "<TIMED OUT>"
    tail = [ln for ln in r.stdout.splitlines() if "passed" in ln or "failed" in ln or "error" in ln]
    return r.returncode == 0, (tail[-1] if tail else r.stdout[-90:]).strip()


def restore_from_backups():
    healed = []
    for f in TOUCHED:
        bak = f.with_suffix(f.suffix + ".orig")
        if bak.exists():
            f.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8", newline="")
            bak.unlink()
            healed.append(f.name)
    return healed


def main():
    healed = restore_from_backups()
    if healed:
        print("HEALED a previous interrupted run: restored " + ", ".join(healed) + NL)
    originals = {f: f.read_text(encoding="utf-8") for f in TOUCHED}
    for f, text in originals.items():
        f.with_suffix(f.suffix + ".orig").write_text(text, encoding="utf-8", newline="")
    failures = []
    try:
        print("BASELINE -- must PASS")
        ok, line = run_tests()
        print("      " + line)
        if not ok:
            print(NL + "BASELINE FAILED. Nothing below is evidence of anything.")
            return 2
        print(NL + "MUTATIONS -- each must be REJECTED")
        for name, path, find, repl, breaks in MUTATIONS:
            text = originals[path]
            n = text.count(find)
            if n != 1:
                failures.append(name + ": anchor found %d times, expected 1" % n)
                print("  " + name + NL + "      ANCHOR NOT UNIQUE (%d) -- not applied" % n)
                continue
            path.write_text(text.replace(find, repl, 1), encoding="utf-8", newline="")
            try:
                ok, line = run_tests()
            finally:
                path.write_text(text, encoding="utf-8", newline="")
            print("  " + name + NL + "      breaks: " + breaks
                  + NL + "      -> " + ("rejected" if not ok else "SURVIVED") + "   " + line)
            if ok:
                failures.append(name + ": SURVIVED")
    finally:
        for f, text in originals.items():
            f.write_text(text, encoding="utf-8", newline="")
            f.with_suffix(f.suffix + ".orig").unlink(missing_ok=True)
        print(NL + "restored: " + ", ".join(f.name for f in TOUCHED))
    print()
    if failures:
        print("NEGATIVE CONTROL FAILED -- %d problem(s):" % len(failures))
        for f in failures:
            print("    " + f)
        return 1
    print("NEGATIVE CONTROL PASSED -- baseline passes, all %d mutations rejected." % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
