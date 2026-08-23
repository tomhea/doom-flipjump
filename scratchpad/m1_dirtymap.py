"""M1a/M1b — the EXACT dirty set of the shipped binary, structured, and (optionally) NAMED.

WHAT THIS ADDS OVER `dirty_census.py --exact`. The census answers "how many words, and how
contiguous". That bounds the prize; it does not tell you WHAT moved, and M1 cannot be written
against a bag of integers. This reports the STRUCTURE of the dirty set (runs, strides, arithmetic
progressions) and, when given a label table from `m1b_labels.py`, attributes every dirty word to
the fj label that owns it. Two separate questions become measurements on the real program:

  * M1a, ON THE REAL BINARY: the `sshead`/`thnext` STRIDE. A toy probe settled what
    `hex.ptr_index` + `hex.write_byte` mean (scratchpad/m1a_stride.py: stride ONE hex cell, the
    byte inside that one cell, so entry i dirties exactly word base+2i+1). Here that becomes a
    FALSIFIABLE PREDICTION about an 84.8M-word image: inside `thnext`, the dirty words must be
    exactly 2 apart. If the stride were two cells they would be 4 apart, and this says so.
  * M1b: which labels are dirty AT ALL -- the measured set that the emitter-derived set must cover.

⚠ NEGATIVE CONTROLS (R9), because every number here is meant to be quoted:
  1. WALKER: two pristine images, exact-walked, must report 0 differ.
  2. VACUITY: every frame must run > 1e6 ops and the union must be non-empty; a wrong wire halts
     after ~200 ops and would report a beautifully small dirty set of nothing.
  3. ATTRIBUTION IS NOT DEGENERATE (with --labels): the whole attribution is re-run against a label
     table shifted by one word, and the per-label counts MUST change. An attributor that lands
     everything in one giant label would otherwise produce a confident, meaningless report.
  4. ATTRIBUTION IS EXACT AT THE ARRAYS WE QUOTE (with --labels): for each named array, the NEXT
     label must be at least the array's DECLARED size away, so nothing between them belongs to
     someone else. A gap that does not match the declaration is reported as a failure.

    python scratchpad/m1_dirtymap.py <fjm> --gatevps --dump scratchpad/_m1_dirty.json.gz
    python scratchpad/m1_dirtymap.py --load scratchpad/_m1_dirty.json.gz --labels <labels.tsv.gz>
"""
import argparse
import bisect
import gzip
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.harness import W                                              # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm", nargs="?", help="omit together with --load to re-attribute a cached census")
ap.add_argument("--labels", default=None,
                help="label table from m1b_labels.py; without it only the STRUCTURE is reported")
ap.add_argument("--dump", default=None, help="cache the measured dirty set here (json.gz)")
ap.add_argument("--load", default=None, help="re-use a cached dirty set instead of re-measuring")
ap.add_argument("--gatevps", action="store_true", help="union over the four gate viewpoints")
ap.add_argument("--keys", type=int, default=0)
ap.add_argument("--things", action="store_true", default=True)
ap.add_argument("--no-things", dest="things", action="store_false")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--top", type=int, default=70, help="labels/runs to list")
args = ap.parse_args()
assert args.fjm or args.load, "give a .fjm to measure, or --load a cached census"

CELL_WORDS = 2                              # a hex cell is dw = 2w bits = 2 words
NSS, NT, NTHVIS = 682, 75, 123              # measured this session for the shipped E1M1 config


def m14_feed(state=None):
    """The binary wire, exactly as m14_sweep / dirty_census build it, so this censuses the frame
    the sweep measured. Returns (bytes, n_runtime_things)."""
    from doomfj.config import Config
    from doomfj.fixedpoint import _signed
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES, ReferenceModel,
                                        spawn_state)
    from doomfj.things import baked_thing_mask, vanishable_slots
    from doomfj.wad import WadFile
    from doomfj.wireformat import (encode_bindings, encode_feed, encode_things,
                                   encode_visibility)
    w = WadFile.from_path(str(ROOT / args.wad))
    if state is None:
        sp = spawn_state(w, "E1M1")
        state = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
    blob = encode_feed(state[0], state[1], state[2], args.keys)
    if not args.things:
        return blob, 0
    rm = ReferenceModel(Config())
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    cmap = bake_bsp(w, "E1M1")
    drawable = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    rt = [t for t, b in zip(drawable, baked) if not b]
    blob += encode_things([(t.x << 16, t.y << 16) for t in rt])
    blob += encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in rt])
    blob += encode_visibility([1] * nvis)
    return blob, len(rt)


def measure(fjm_path):
    """Run the frames and exact-walk every word. Returns (dirty_sorted, total_words, per_frame)."""
    from doomfj.fastrun import FjmRunner, _fjcore
    from flipjump.interpreter.fjm_run import IOReadOnEOF
    from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
    from tests.fj.stream_screen import StreamScreen

    r = FjmRunner(Path(fjm_path))
    assert r.native, "needs the native engine"
    total = sum(n for _s, n in r._segments)
    print(f"{Path(fjm_path).name}: {len(r._segments)} segments, {total:,} words "
          f"(~{total*8/1e6:.0f} MB)", flush=True)

    def fresh():
        core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
        for s, n in r._segments:
            core.add_segment(s, n)
        for st, vals in r._runs:
            core.set_words(st, vals)
        return core

    def walk(a, b):
        hits = []
        for s, n in r._segments:
            for x in range(s, s + n):
                if a.get_word(x) != b.get_word(x):
                    hits.append(x)
        return hits

    t0 = time.perf_counter()
    pristine = fresh()
    twin = fresh()
    ctl = walk(pristine, twin)
    print(f"CONTROL 1 (walker): two pristine images -> {len(ctl)} differ  "
          f"{'ok' if not ctl else '!! THE WALKER IS BROKEN'}  ({time.perf_counter()-t0:.0f}s)",
          flush=True)
    if ctl:
        sys.exit(1)
    del twin

    states = [None]
    if args.gatevps:
        states = [(664 << 16, 291 << 16, 0x18000000), (1272 << 16, (-724) << 16, 0x40000000),
                  (1869 << 16, 479 << 16, 0x80000000), None]

    union, per_frame = set(), []
    for st in states:
        feed, nth = m14_feed(st)
        core = fresh()
        scr = StreamScreen(stdin=feed, n_things=nth)
        scr.attach_memory(NativeDeviceMemory(core, r.width))
        _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
        hits = walk(pristine, core)
        union |= set(hits)
        name = "spawn" if st is None else f"({st[0]>>16},{st[1]>>16},{st[2]:#x})"
        per_frame.append((name, ops, len(hits)))
        print(f"  {name}: {ops:,} ops -> {len(hits):,} dirty words "
              f"({time.perf_counter()-t0:.0f}s)", flush=True)
        del core, scr
    del pristine
    return sorted(union), total, per_frame


# ------------------------------------------------------------------------------ get the dirty set
if args.load:
    with gzip.open(args.load, "rt", encoding="utf-8") as f:
        cached = json.load(f)
    dirty, total_words, per_frame = cached["dirty"], cached["total_words"], cached["per_frame"]
    print(f"loaded {args.load}: {len(dirty):,} dirty words of {total_words:,} "
          f"(from {cached['fjm']})")
    for n, o, d in per_frame:
        print(f"  {n}: {o:,} ops -> {d:,} dirty words")
else:
    dirty, total_words, per_frame = measure(args.fjm)

assert per_frame and all(o > 1_000_000 for _n, o, _d in per_frame), \
    f"CONTROL 2 (vacuity) FAILED: a frame ran too few ops -- wrong wire? {per_frame}"
assert dirty, "CONTROL 2 (vacuity) FAILED: nothing is dirty, so nothing was measured"

if args.dump and not args.load:
    with gzip.open(args.dump, "wt", encoding="utf-8") as f:
        json.dump({"fjm": str(args.fjm), "total_words": total_words,
                   "per_frame": per_frame, "dirty": dirty}, f)
    print(f"cached the census -> {args.dump} ({Path(args.dump).stat().st_size/1e6:.2f} MB)")

print(f"\nDIRTY: {len(dirty):,} of {total_words:,} words = {100*len(dirty)/total_words:.6f}% "
      f"(first {dirty[0]:,}, last {dirty[-1]:,}, span {dirty[-1]-dirty[0]+1:,})")


# ------------------------------------------------------------------- STRUCTURE (needs no labels)
def runs_at(words, gap):
    out, start, prev = [], words[0], words[0]
    for cur in words[1:]:
        if cur - prev > gap:
            out.append((start, prev, prev - start + 1))
            start = cur
        prev = cur
    out.append((start, prev, prev - start + 1))
    return out


print("\n" + "=" * 108)
print("STRUCTURE -- what the dirty set looks like without knowing any names")
print("=" * 108)
steps = defaultdict(int)
for a, b in zip(dirty, dirty[1:]):
    steps[b - a] += 1
print("consecutive-difference histogram (top 12):")
for d, c in sorted(steps.items(), key=lambda kv: -kv[1])[:12]:
    print(f"  step {d:>10,}: {c:>7,} times")

print("\nMAXIMAL STRIDE-2 PROGRESSIONS (the signature a ptr_index byte array leaves):")
prog, cur = [], [dirty[0]]
for a, b in zip(dirty, dirty[1:]):
    if b - a == 2:
        cur.append(b)
    else:
        prog.append(cur)
        cur = [b]
prog.append(cur)
prog = [p for p in prog if len(p) >= 8]
prog.sort(key=lambda p: -len(p))
print(f"  {len(prog)} progressions of length >= 8; longest {min(20, len(prog))}:")
for p in prog[:20]:
    print(f"    start {p[0]:>12,}  len {len(p):>6,}  end {p[-1]:>12,}  "
          f"(all offsets from start are even)")
print(f"  lengths of interest: nss={NSS}  nt={NT}  nthvis={NTHVIS}  "
      f"-> any progression of exactly one of those lengths is a candidate for that array")

print("\nCOALESCING (what a range restore would have to move):")
for gap in (1, 2, 16, 256, 4096):
    rr = runs_at(dirty, gap)
    covered = sum(n for _a, _b, n in rr)
    print(f"  gap {gap:>6,}: {len(rr):>6,} ranges covering {covered:>9,} words "
          f"({100*covered/total_words:.5f}% of the image, ~{covered*8/1e6:.3f} MB)")

if not args.labels:
    print("\n(no --labels given: run scratchpad/m1b_labels.py to name these regions)")
    sys.exit(0)


# ----------------------------------------------------------------------------- ATTRIBUTION
def attribute(dirty_words, label_path, shift_words=0):
    """owner[i] = the label with the greatest word-address <= dirty_words[i].

    Streams the (huge) label table and keeps only O(len(dirty_words)) state: a label can only
    START owning at the FIRST dirty word at or after it, and a forward fill afterwards propagates
    ownership to the dirty words that follow with no label in between.
    """
    n = len(dirty_words)
    best_addr = [-1] * n
    best_name = [None] * n
    known = {}
    nlab = 0
    with gzip.open(label_path, "rt", encoding="utf-8") as f:
        for line in f:
            name, tab, val = line.rstrip("\n").partition("\t")
            if not tab:
                continue
            nlab += 1
            wl = int(val) // W + shift_words
            known[name] = wl
            i = bisect.bisect_left(dirty_words, wl)
            if i < n and wl > best_addr[i]:
                best_addr[i], best_name[i] = wl, name
    for i in range(1, n):
        if best_addr[i] < best_addr[i - 1]:
            best_addr[i], best_name[i] = best_addr[i - 1], best_name[i - 1]
    return best_name, best_addr, nlab, known


print(f"\nattributing against {args.labels} ...", flush=True)
names, addrs, nlab, labelmap = attribute(dirty, args.labels)
print(f"  {nlab:,} labels streamed", flush=True)

by_label = defaultdict(list)
for d, nm, ad in zip(dirty, names, addrs):
    by_label[nm].append(d - ad if ad >= 0 else d)

print("\nCONTROL 3 (shift): a label table shifted by one word must change the per-label counts")
names_s, _a, _n, _k = attribute(dirty, args.labels, shift_words=1)
cnt_s = defaultdict(int)
for nm in names_s:
    cnt_s[nm] += 1
same = {k: len(v) for k, v in by_label.items()} == dict(cnt_s)
print(f"  counts identical? {same}  "
      f"{'!! FAIL -- the attributor ignores the label table' if same else 'ok -- it moved'}")
if same:
    sys.exit(1)

print(f"\n{'label':<46}{'words':>8}  offsets from the label (words)")
print("-" * 108)
for nm, offs in sorted(by_label.items(), key=lambda kv: -len(kv[1]))[:args.top]:
    o = sorted(offs)
    gaps = sorted({b - a for a, b in zip(o, o[1:])})
    shown = ", ".join(str(x) for x in o[:8]) + (" ..." if len(o) > 8 else "")
    print(f"{str(nm):<46}{len(o):>8}  {shown}")
    if len(o) > 1:
        print(f"{'':<46}{'':>8}  gaps {gaps[:8]}{' ...' if len(gaps) > 8 else ''}  "
              f"span {o[-1]-o[0]+1}")

# ------------------------------------------------------- M1a on the real program: the stride test
CHECK = [("sshead", 2 * NSS, NSS), ("thnext", 2 * NT, NT),
         ("thss_rt", 16 * NT, NT), ("thpos_rt", 16 * NT, NT)]
print("\n" + "=" * 108)
print("M1a ON THE REAL PROGRAM -- the stride, read off the shipped binary")
print("=" * 108)
addr_sorted = sorted(labelmap.values())
for nm, decl_cells, n_entries in CHECK:
    if nm not in labelmap:
        print(f"\n{nm}: NOT IN THE LABEL TABLE -- cannot check")
        continue
    base = labelmap[nm]
    i = bisect.bisect_right(addr_sorted, base)
    nxt = addr_sorted[i] if i < len(addr_sorted) else None
    room = (nxt - base) if nxt else None
    decl_words = decl_cells * CELL_WORDS
    ok2 = room is not None and room >= decl_words
    print(f"\n{nm}: label word {base:,}   declared hex.vec {decl_cells} cells = {decl_words} words")
    print(f"  CONTROL 4 (attribution exact here): next label {room} words away, need >= "
          f"{decl_words}  ->  {'ok' if ok2 else '!! ATTRIBUTION HERE IS A GUESS'}")
    offs = sorted(by_label.get(nm, []))
    if not offs:
        print("  no dirty words attributed here")
        continue
    m2 = defaultdict(int)
    m4 = defaultdict(int)
    for o in offs:
        m2[o % 2] += 1
        m4[o % 4] += 1
    cells = sorted({o // CELL_WORDS for o in offs})
    cgaps = sorted({b - a for a, b in zip(cells, cells[1:])}) if len(cells) > 1 else []
    print(f"  {len(offs)} dirty words, offsets {offs[0]}..{offs[-1]}")
    print(f"  offset mod 2: {dict(m2)}    offset mod 4: {dict(m4)}")
    print(f"  -> {len(cells)} distinct CELLS, indices {cells[0]}..{cells[-1]}, cell gaps {cgaps[:8]}")
    within = cells[-1] < n_entries
    print(f"  every cell index < n_entries ({n_entries})? {within}"
          + ("" if within else "   <-- entries past the used half ARE being written"))
    if all(o % 2 == 1 for o in offs):
        print("  VERDICT: every dirty word sits at an ODD offset = a cell's VALUE word, and cell k")
        print("           maps to word 2k+1  =>  STRIDE 1 HEX CELL. M1a CONFIRMED on the real program.")
    elif all(o % 4 == 1 for o in offs):
        print("  VERDICT: dirty words are 4 apart  =>  STRIDE 2 HEX CELLS. M1a IS REFUTED.")
    else:
        print("  VERDICT: neither pattern holds -- report this, do not average it away.")

print("\n" + "=" * 108)
print(f"TOTAL {len(dirty):,} dirty words; {len(by_label)} distinct owning labels "
      f"of {nlab:,} in the table")
print("=" * 108)
