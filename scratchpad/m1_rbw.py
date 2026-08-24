"""M1 — READ-BEFORE-WRITE analysis: which cells actually need a value at frame start.

THE RIGHT PREDICATE, and I had been using the wrong one. A cell needs restoring iff the next frame
READS it before it WRITES it. "The frame dirties it" is not the same thing and is much larger: most
scratch is overwritten by a `mov`/`zero`/`set` before anything looks at it, so restoring it is pure
cost.

Doing this per CELL is hopeless (56k cells). Doing it per (MACRO, LOCAL) is easy: the 1,321
macro-local labels in the restore set are instantiations of only 349 distinct (macro, local) pairs,
and whether a local is read-before-written is a property of the MACRO BODY, identical in every
instantiation. So: parse the macro, walk its body in order, find the FIRST statement that mentions
the local, and classify that statement.

The classification table below is the load-bearing part, so it is explicit rather than clever:
  WRITE-FIRST (the destination is fully overwritten, so no restore is needed)
      hex.zero / hex.set / hex.mov / hex.read_hex / hex.read_byte / hex.ptr_index / hex.input
      -- `mov` is `zero` then `xor`, and `read_*` zero the destination first, so each of these
      leaves the destination independent of its previous contents.
  READ (or read-modify-write, so a stale value reaches the answer)
      hex.add / sub / xor / or / and / inc / dec / shl_* / shr_* / xor_by / cmp / scmp /
      if0 / if1 / if_flags / sign / write_hex / write_byte / fixed_mul* / mul* ...
      -- and ANYTHING NOT IN THE TABLE, which is the safe default.

⚠ NEGATIVE CONTROLS (R9):
  1. The table's default is READ. An unrecognised macro can only make the set BIGGER, never
     smaller, so a gap in the table cannot silently drop a needed cell.
  2. `hex.scmp`'s `ba`/`bb` are asserted WRITE-FIRST and `sim.check_line`'s `rrow` is asserted
     READ -- two hand-checked anchors. If the parser stops agreeing with the source on those, it
     is broken and says so.
  3. The verdict is only a CANDIDATE set. It is worthless until the 12-frame chain and the
     260-frame sweep confirm it, because a wrong "write-first" silently corrupts a later frame.

    python scratchpad/m1_rbw.py
"""
import argparse
import bisect
import gzip
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump                                                           # noqa: E402
from doomfj.harness import W                                              # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--set", default="scratchpad/_m1_setB.json.gz")
ap.add_argument("--gen", default="scratchpad/fjmcache/_m1gen")
ap.add_argument("--out", default="scratchpad/_m1_setD.json.gz")
args = ap.parse_args()

# ------------------------------------------------------------------ the classification table
# name -> the 0-based ARGUMENT INDICES that are written WITHOUT being read first, given the arity.
# `None` for the arity key means "any arity"; the count-prefixed forms (`hex.zero n, x`) shift the
# destination by one, so both shapes are listed.
WRITE_FIRST = {
    "hex.zero":       {1: [0], 2: [1]},
    "bit.zero":       {1: [0], 2: [1]},
    "hex.set":        {2: [0], 3: [1]},
    "bit.set":        {2: [0], 3: [1]},
    "hex.mov":        {2: [0], 3: [1]},
    "bit.mov":        {2: [0], 3: [1]},
    "hex.read_hex":   {2: [0], 3: [1]},
    "hex.read_byte":  {2: [0], 3: [1]},
    "hex.ptr_index":  {3: [0]},
    "hex.input":      {1: [0], 2: [1]},
    # Project macros, each checked against its body before being added here -- a wrong entry
    # silently drops a cell that IS read, and the symptom is a corrupted later frame:
    #   read_table_packed nb, dst, table, idx_n, idx  -> `rep(nb,k) .read_byte_and_inc dst+..`,
    #        and read_byte zeroes its destination (fixed_point.fj:178-183)
    #   fixed_mul_lo n, f, dst, a, b                  -> ends `.mov n, dst, res + f*dw`, and dst
    #        appears nowhere earlier in the body (fixed_point.fj:77-84)
    #   sim.fix16 dst, src                            -> `hex.zero 8, dst` first (sim.fj:48-50)
    "hex.read_table_packed": {5: [1]},
    "hex.fixed_mul_lo":      {5: [2]},
    "sim.fix16":             {2: [0]},
}
# ⚠ Inside `ns hex`, the stl writes `.mov`, not `hex.mov` -- the leading dot IS the namespace. A
# table keyed only on full names classifies every stl-internal use as READ, which is safe but
# useless (it kept the whole set). The bare aliases below are what make the analysis see anything;
# the hand-checked anchors are what caught their absence.
for _k in list(WRITE_FIRST):
    WRITE_FIRST[_k.split(".")[-1]] = WRITE_FIRST[_k]


def classify(line, local):
    """Is `local`'s FIRST appearance in `line` a pure write? Default: READ (the safe direction)."""
    s = line.split("//")[0].strip()
    if not s:
        return None
    m = re.match(r"^\.?([A-Za-z_][\w.]*)\s*(.*)$", s)
    if not m:
        return "read"
    name, rest = m.group(1), m.group(2)
    if name.startswith("."):
        name = name[1:]
    args = [a.strip() for a in rest.split(",")] if rest else []
    # `name:` alone, `name: hex.vec n`, and a bare `.vec n` are DECLARATIONS, not uses. Counting a
    # declaration as a local's first use classifies it READ (the safe default) and makes the whole
    # analysis nearly vacuous -- that is why the first run could only drop 28%.
    if (s.endswith(":") or re.match(r"^[A-Za-z_]\w*:\s*(hex\.|bit\.|\.)?vec\b", s)
            or re.match(r"^(hex|bit)\.vec\b", s) or re.match(r"^\.?vec\b", s)):
        return None
    idxs = WRITE_FIRST.get(name, {}).get(len(args))
    if idxs is None and name in WRITE_FIRST:
        idxs = WRITE_FIRST[name].get(None)
    if idxs:
        for i in idxs:
            if i < len(args) and re.match(r"^%s\b" % re.escape(local), args[i]):
                return "write"
    return "read"


# ------------------------------------------------------------------------ parse the macro bodies
SRCS = list((ROOT / "src/fj").glob("*.fj"))
SRCS += list((Path(flipjump.__file__).parent / "stl").rglob("*.fj"))
GEN = Path(args.gen)
SRCS += [GEN / f for f in ("e1m1_01_tables.fj", "e1m1_02_main.fj", "e1m1_06_banks.fj")
         if (GEN / f).is_file()]

MACROS = {}          # short name -> list of body lines
for p in SRCS:
    ns = []
    cur = None
    depth = 0
    # ⚠ Many defs continue their header across lines with a trailing backslash
    # (`def foo a, b \` / `@ x, y < z {`). A parser that requires `{` on the def line misses those
    # bodies entirely and then answers "macro body not found -> default READ" for every one of
    # their locals: safe, but it keeps the whole set and the analysis does nothing.
    _txt = re.sub(r"\\\s*\n\s*", " ", io.open(p, encoding="utf-8", errors="replace").read())
    for raw in _txt.split("\n"):
        line = raw.split("//")[0].rstrip()
        st = line.strip()
        mns = re.match(r"^ns\s+([\w.]+)\s*\{", st)
        if mns:
            ns.append(mns.group(1))
            continue
        md = re.match(r"^def\s+([\w.]+)([^{]*)\{", st)
        if md and cur is None:
            nm = md.group(1)
            full = ".".join(ns + [nm]) if ns else nm
            cur = (full, [])
            depth = 1
            continue
        if cur is not None:
            depth += st.count("{") - st.count("}")
            if depth <= 0:
                MACROS.setdefault(cur[0], cur[1])
                MACROS.setdefault(cur[0].split(".")[-1], cur[1])
                cur = None
            else:
                cur[1].append(st)
        elif st == "}" and ns:
            ns.pop()
print(f"parsed {len(MACROS):,} macro names from {len(SRCS)} sources")


def first_use(macro, local):
    body = MACROS.get(macro) or MACROS.get(macro.split(".")[-1])
    if body is None:
        return "read", "(macro body not found -> default READ)"
    pat = re.compile(r"\b%s\b" % re.escape(local))
    for line in body:
        if not pat.search(line):
            continue
        v = classify(line, local)
        if v is None:
            continue
        return v, line
    return "read", "(no use found -> default READ)"


# CONTROL 2: hand-checked anchors, plus the safe-direction property.
# ⚠ My first version asserted `sim.check_line.rrow` was READ. It is not -- it is filled by
# `hex.read_table_packed 22, rrow, ...`, which writes every one of its 44 cells. The control fired
# and the EXPECTATION was what was wrong. Anchors are only worth having if a failure sends you back
# to the source rather than to the code.
# ⚠ 2026-08-24: it fired a SECOND time, and again the expectation was stale rather than the
# parser. bdf1f1a hoisted check_line's scratch to named globals, so `rrow` no longer exists and
# the anchor reported '(no use found -> default READ)'. The cell is now `cl_rest`, filled by the
# same statement -- `hex.read_table_packed 14, cl_rest, lnrow, n_ln, li` -- so the hand-checked
# claim is unchanged: 14 bytes = 28 cells, all written before any read.
for mac, loc, want in (("hex.scmp", "ba", "write"),          # .mov n, ba, a
                       ("hex.scmp", "bb", "write"),          # .mov n, bb, b
                       ("hex.fixed_mul_lo", "res", "write"),  # .zero n+f, res
                       ("sim.check_line", "cl_rest", "write")):  # read_table_packed fills all 28
    got, why = first_use(mac, loc)
    assert got == want, (f"CONTROL 2 FAILED: {mac}.{loc} classified {got}, expected {want} "
                         f"(first use: {why!r})")
# the safe direction: anything unrecognised must come back READ, so a gap in the table can only
# make the set BIGGER. If this ever returns "write" the analysis can silently drop live cells.
assert first_use("no.such.macro", "whatever")[0] == "read", \
    "CONTROL 2 FAILED: an unknown macro must default to READ"
assert classify("frame.some_unknown_macro a, b, c", "a") == "read", \
    "CONTROL 2 FAILED: an unknown statement must default to READ"
print("CONTROL 2: anchors agree, and unknown macros/statements default to READ (safe direction)")

# ------------------------------------------------------------------------- apply to the set
S0 = sorted(x for a, b in json.load(gzip.open(args.set, "rt", encoding="utf-8"))["runs"]
            for x in range(a, b))
sa, sn = [], []
with gzip.open(args.labels, "rt", encoding="utf-8") as f:
    for line in f:
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            sa.append(int(v) // W)
            sn.append(a)
o = sorted(range(len(sa)), key=lambda i: sa[i])
sa = [sa[i] for i in o]
sn = [sn[i] for i in o]
piece = defaultdict(list)
for x in S0:
    i = bisect.bisect_right(sa, x) - 1
    piece[sn[i] if i >= 0 else "<none>"].append(x)

verdict = {}
keep_words, drop_words = [], []
pair_v = {}
for n, ws in piece.items():
    if n and "---" in n:
        chain = n.split("---")
        loc = chain[-1]
        mac = (chain[-2] if len(chain) >= 2 else chain[0]).split(":")[-1].split("(")[0]
        v, why = first_use(mac, loc)
        pair_v[(mac, loc)] = (v, why)
    else:
        v = "read"          # top-level named cells: never dropped by this analysis
    verdict[n] = v
    (drop_words if v == "write" else keep_words).extend(ws)

print(f"\n{len(pair_v)} distinct (macro, local) pairs classified")
wf = [(m, l) for (m, l), (v, _w) in pair_v.items() if v == "write"]
print(f"  WRITE-FIRST (droppable): {len(wf)}   READ-FIRST (must restore): {len(pair_v)-len(wf)}")
byw = defaultdict(int)
for n, ws in piece.items():
    if n and "---" in n:
        chain = n.split("---")
        loc = chain[-1]
        mac = (chain[-2] if len(chain) >= 2 else chain[0]).split(":")[-1].split("(")[0]
        byw[(mac, loc, pair_v[(mac, loc)][0])] += len(ws)
print(f"\n{'macro':<24}{'local':<13}{'verdict':<8}{'words':>8}  first use")
print("-" * 108)
for (m, l, v), c in sorted(byw.items(), key=lambda kv: -kv[1])[:26]:
    print(f"{m[:24]:<24}{l[:13]:<13}{v:<8}{c:>8,}  {pair_v[(m,l)][1][:44]}")

print(f"\nset: {len(S0):,} words -> keep {len(keep_words):,}  (drop {len(drop_words):,} = "
      f"{100*len(drop_words)/len(S0):.0f}%)")


def co(ws):
    ws = sorted(ws)
    out, s0, p = [], ws[0], ws[0]
    for c in ws[1:]:
        if c != p + 1:
            out.append([s0, p + 1])
            s0 = c
        p = c
    out.append([s0, p + 1])
    return out


json.dump({"runs": co(keep_words)}, gzip.open(args.out, "wt", encoding="utf-8"))
print(f"wrote {args.out}")
print("\n!! CANDIDATE ONLY. Confirm before building:")
print(f"   python scratchpad/m1d_loop.py --set full --restore-set {args.out} --sweep")
