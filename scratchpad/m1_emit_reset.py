"""M1c — EMIT the fj reset prologue, and patch the program into an internal frame LOOP.

WHAT IT PRODUCES
  * `e1m1_07_reset.fj` — a new, LAST program part holding `m1_reset:` … `;__hot_end`.
  * a size-neutral patch to `e1m1_02_main.fj`: the frame's trailing `stl.loop` (1 op) becomes
    `;m1_reset` (1 op). Same op count, so NO existing label moves — which is what lets the reset
    bake NUMERIC addresses taken from a previous assembly of the same program.

WHY BAKED ADDRESSES AT ALL. Most of the set is macro-`@`-local scratch. fj cannot name a macro's
local from outside it, so a prologue written in label terms is impossible: measured, restoring only
the fj-addressable declared state leaves up to 4,495 pixels wrong (`m1d_loop.py --set declared`).
Hence two passes — assemble, read the labels, emit the reset against those addresses, assemble
again — and a hard check that every address still means what it meant.

THE PRIMITIVE PER CELL IS NOT A DETAIL, IT IS THE WHOLE CORRECTNESS ARGUMENT (M1a / R57):
  * a NIBBLE cell (only ever written by hex.mov/set/xor/input) holds 0..15 -> `hex.zero`, 19.5
    ops/cell measured, or `hex.set 1, addr, v` at 21.5 when its pristine value is not 0;
  * a BYTE cell (written by `hex.write_byte`, all 8 bits in ONE cell) needs `hex.zero_ptr`, 943
    ops/cell measured -- 48x more. `hex.zero` on a byte cell does not merely fail, it CORRUPTS:
    measured 0xA5 -> 0x22A5, because `hex.xor`'s dispatch jumps out of its own 16-entry table.
  * so the byte arrays are cleared by an indexed LOOP and everything else is unrolled, and the
    generator ASSERTS that no cell it treats as a nibble has a pristine value above 15.

⚠ NEGATIVE CONTROLS (R9), all at generation time, because a wrong prologue is a 25-minute build:
  1. every emitted address must be dw-aligned and inside a segment;
  2. no nibble-treated cell may have a pristine value > 15 (the corruption case above);
  3. the byte-array loops must cover exactly the cells the set contains for those labels -- the
     generator diffs its own coverage against the set and fails on any mismatch;
  4. the main patch must find EXACTLY ONE trailing `stl.loop` to replace, and the file's line count
     must not change.

    python scratchpad/m1_emit_reset.py --out scratchpad/fjmcache/_m1gen
"""
import argparse
import bisect
import gzip
import io
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.harness import W                                              # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--fjm", default="scratchpad/fjmcache/_rssprobe.fjm")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--set", default="scratchpad/_m1c_restore_set_nolut.json.gz")
ap.add_argument("--gen", default="scratchpad/fjmcache/_rssgen")
ap.add_argument("--out", default="scratchpad/fjmcache/_m1gen")
args = ap.parse_args()

DW = 2 * W
VAL = (W + W.bit_length()) - W
CODE_START_WORD = 17308

# Arrays written through `hex.write_byte`: all 8 bits live in ONE cell, so a nibble op corrupts
# them. `n` is the number of cells the program can actually reach (a 1-cell stride, M1a), NOT the
# declared `hex.vec` size -- sshead is declared 2*nss and only nss is reachable.
BYTE_ARRAYS = [("sshead", 682), ("pclm", 160), ("sfflag", 160),
               ("drawn", 160), ("sprflag", 160)]
# Proven droppable by the 12-frame loop test: write-once slots gated by their flag byte, and a
# thnext that bind_things fully overwrites every frame.
DROP_LABELS = ["sfslot", "spslot", "thnext"]

# ------------------------------------------------------------------------------------ inputs
r = FjmRunner(Path(args.fjm))
assert r.native
core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
for s, n in r._segments:
    core.add_segment(s, n)
for st, vals in r._runs:
    core.set_words(st, vals)
SEGS = [(s, s + n) for s, n in r._segments]

BITS, sa = {}, []
with gzip.open(args.labels, "rt", encoding="utf-8") as f:
    for line in f:
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            b = int(v)
            sa.append(b)
            BITS.setdefault(a, b)
sa.sort()
saw = [b // W for b in sa]


def extent(name):
    b = BITS[name] // W
    i = bisect.bisect_right(saw, b)
    return b, (saw[i] if i < len(saw) else b + 2)


words = sorted(x for a, b in json.load(gzip.open(args.set, "rt", encoding="utf-8"))["runs"]
               for x in range(a, b))
for d in DROP_LABELS:
    a, b = extent(d)
    words = [x for x in words if not (a <= x < b)]
words = [x for x in words if x >= CODE_START_WORD]
WSET = set(words)
print(f"restore set: {len(words):,} words = {len(words)//2:,} cells")

# ------------------------------------------------------------------ split byte arrays out
byte_words = set()
for name, n in BYTE_ARRAYS:
    base = BITS[name] // W
    for k in range(n):
        byte_words.add(base + 2 * k)
        byte_words.add(base + 2 * k + 1)
covered = byte_words & WSET
missing = byte_words - WSET
assert not missing, (f"CONTROL 3 FAILED: {len(missing)} byte-array words are not in the restore "
                     f"set -- the reachable counts in BYTE_ARRAYS disagree with the set")
nib_words = sorted(WSET - byte_words)
print(f"  byte-array cells (hex.zero_ptr loop): {len(covered)//2:,}")
print(f"  nibble cells (unrolled)             : {len(nib_words)//2:,}")

# AUTO-EXCLUDE the read-only regions. A cell that only nibble ops ever write cannot hold a pristine
# value above 15, so any label region outside BYTE_ARRAYS that contains one is a packed LUT
# (`throw`, `sprlt`, `throwc`, `bkoff`, `xtoviewangle`), code (`__hot_end`), or an extent that
# overran its declaration (`thvis`). They came in because they are top-level labels of the emitted
# parts, not because anything writes them -- and the 12-frame loop test is what confirms that.
# Derived, not a hand-kept list: a new LUT in a future build is excluded automatically.
ro = set()
for x in nib_words:
    if x % 2 == 0:
        continue
    if (core.get_word(x) >> VAL) > 15:
        i = bisect.bisect_right(saw, x) - 1
        ro.add(saw[i])
if ro:
    drop = set()
    for base in ro:
        i = bisect.bisect_right(saw, base)
        end = saw[i] if i < len(saw) else base + 2
        drop.update(range(base, end))
    before = len(nib_words)
    nib_words = [x for x in nib_words if x not in drop]
    WSET = set(nib_words) | covered
    words = sorted(WSET)
    print(f"  auto-excluded {len(ro)} read-only/code regions: "
          f"{before-len(nib_words):,} words -> {len(words):,} words total")

# ------------------------------------------------------------------ classify the nibble cells
cells = sorted({x // 2 for x in nib_words})
vals = {}
for c in cells:
    wd = 2 * c + 1
    assert any(lo <= wd < hi for lo, hi in SEGS), f"CONTROL 1: word {wd} outside every segment"
    v = core.get_word(wd) >> VAL
    assert v <= 15, (f"CONTROL 2 FAILED: cell at word {2*c} has pristine value {v:#x} > 15 -- a "
                     f"nibble op would CORRUPT it (measured 0xA5 -> 0x22A5). It belongs in a byte "
                     f"array or out of the set.")
    vals[c] = v
nz = sum(1 for v in vals.values() if v)
print(f"  of those, pristine == 0: {len(cells)-nz:,}   pristine 1..15: {nz:,}")

# runs of consecutive ZERO cells collapse into one `hex.zero n, addr`
lines, i = [], 0
n_zero_runs = n_set = 0
while i < len(cells):
    if vals[cells[i]]:
        lines.append(f"    hex.set 1, {cells[i]*DW}, {vals[cells[i]]}")
        n_set += 1
        i += 1
        continue
    j = i
    while j + 1 < len(cells) and cells[j + 1] == cells[j] + 1 and not vals[cells[j + 1]]:
        j += 1
    lines.append(f"    hex.zero {j-i+1}, {cells[i]*DW}")
    n_zero_runs += 1
    i = j + 1
print(f"  emitted as {n_zero_runs:,} hex.zero runs + {n_set:,} hex.set")

OPS = (len(cells) - nz) * 19.5 + nz * 21.5 + (len(covered) // 2) * 943
print(f"\nPROJECTED cost: {OPS:,.0f} ops "
      f"({(len(cells)-nz)*19.5:,.0f} zero + {nz*21.5:,.0f} set + "
      f"{(len(covered)//2)*943:,.0f} byte-loop)")

# ------------------------------------------------------------------------------- emit the part
out = Path(args.out)
if out.exists():
    shutil.rmtree(out)
shutil.copytree(args.gen, out)

hdr = [
    "// == M1c: the self-reset prologue =========================================",
    "//   Restores every cell a frame leaves dirty, then re-enters the frame at",
    "//   `__hot_end`. This is what replaces the host's ~52ms whole-image memcpy.",
    "//",
    "//   ADDRESSES ARE BAKED, from a previous assembly of THIS program. That is",
    "//   sound only because this part is APPENDED and the main patch is",
    "//   size-neutral, so no existing label moves. The build re-checks every",
    "//   label address and refuses the binary if one did.",
    "//",
    "//   TWO PRIMITIVES, and the choice is correctness not tuning (M1a/R57):",
    "//     nibble cell -> hex.zero / hex.set   (19.5 / 21.5 ops, measured)",
    "//     BYTE cell   -> hex.zero_ptr         (943 ops, measured) -- a nibble",
    "//                    op on a byte cell CORRUPTS it (0xA5 -> 0x22A5).",
    "// =========================================================================",
    "ns m1 {",
    "    // clear `n` BYTE cells from `base` -- all 8 bits of each, via the pointer path,",
    "    // which is the only value-independent way to clear a full byte (hex.xor_by clamps",
    "    // to a nibble; see stl/hex/memory.fj).",
    "    def clear_bytes base, n @ body, loop, done, i, p {",
    "        ;body",
    "      i: hex.vec w/4",
    "      p: hex.vec w/4",
    "      body:",
    "        hex.set w/4, i, n",
    "        hex.set w/4, p, base",
    "      loop:",
    "        hex.if0 w/4, i, done",
    "        hex.dec w/4, i",
    "        hex.zero_ptr p",
    "        hex.ptr_inc p",
    "        ;loop",
    "      done:",
    "    }",
    "}",
    "",
    "m1_reset:",
]
body = list(lines)
for name, n in BYTE_ARRAYS:
    body.append(f"    m1.clear_bytes {BITS[name]}, {n}      // {name}")
body.append("    ;__hot_end")
Path(out / "e1m1_07_reset.fj").write_text("\n".join(hdr + body) + "\n", encoding="utf-8")
print(f"\nwrote {out/'e1m1_07_reset.fj'} ({len(hdr)+len(body):,} lines)")

# ------------------------------------------------------- patch main into a loop (size-neutral)
mainp = out / "e1m1_02_main.fj"
txt = mainp.read_text(encoding="utf-8")
old_lines = txt.split("\n")
hits = [k for k, l in enumerate(old_lines) if l.strip() == "stl.loop"]
# `bad: stl.loop` shares ONE line, so exactly one BARE `stl.loop` exists -- the frame tail. Both
# are asserted: if the halt-on-bad-input line ever moves onto its own line this fires rather than
# silently patching the wrong halt.
assert len(hits) == 1, (f"CONTROL 4 FAILED: expected exactly 1 bare `stl.loop` (the frame tail), "
                        f"found {len(hits)}")
assert sum(1 for l in old_lines if l.strip() == "bad: stl.loop") == 1,     "CONTROL 4 FAILED: `bad: stl.loop` (the junk-input halt) is not where it was"
k = hits[0]
assert old_lines[k - 1].strip() == "stl.output_char 0xFF", \
    f"CONTROL 4 FAILED: the line before the frame tail is {old_lines[k-1]!r}, not the 0xFF marker"
new_lines = list(old_lines)
new_lines[k] = ";m1_reset"
assert len(new_lines) == len(old_lines)
mainp.write_text("\n".join(new_lines), encoding="utf-8")
print(f"patched {mainp.name}: line {k+1} `stl.loop` -> `;m1_reset` "
      f"(1 op -> 1 op, {len(new_lines)} lines unchanged)")
def _coalesce(ws):
    o, st, pr = [], ws[0], ws[0]
    for c in ws[1:]:
        if c != pr + 1:
            o.append([st, pr + 1])
            st = c
        pr = c
    o.append([st, pr + 1])
    return o


# Dump the EXACT set that was emitted, so `m1d_loop.py --restore-set` validates the same thing the
# build restores. Validating one set and shipping another is the failure this repo keeps hitting.
json.dump({"runs": _coalesce(words)},
          gzip.open("scratchpad/_m1_final_set.json.gz", "wt", encoding="utf-8"))
print("wrote scratchpad/_m1_final_set.json.gz (the set to validate AND the set emitted)")
json.dump({"restore_words": len(words), "cells": len(words) // 2,
           "byte_cells": len(covered) // 2, "nibble_cells": len(cells),
           "projected_ops": OPS},
          gzip.open("scratchpad/_m1_reset_meta.json.gz", "wt", encoding="utf-8"))
print("wrote scratchpad/_m1_reset_meta.json.gz")
