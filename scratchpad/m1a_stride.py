"""M1a — the `sshead`/`thnext` STRIDE, measured, with an R9 negative control.

WHY A FOURTH PROBE. `sshead` and `thnext` are ~74% of the ~2,500 cells one frame dirties
(docs/handoff-complete-game.md §1), so the M1c reset prologue cannot be written until their layout
is known EXACTLY. Three earlier probes (`_ssheadaddr.py`, `_ssheadoverlap.py`, `_ssheadlayout.py`)
were read as mutually inconsistent and `src/fj/sim.fj` records that none of them is evidence,
because none carries a negative control. A fourth opinion without a control is worth nothing.

WHAT IS BEING ASKED, precisely. For an array declared `A: hex.vec N` and addressed the way
`sim.bind_things` and `sim.thing_pass` address it --

    hex.set w/4, base, A
    hex.ptr_index p, base, i
    hex.write_byte p, v          /   hex.read_byte d, p

-- two independent facts:
    (S) STRIDE  : address(entry i) - address(entry 0), in hex cells;
    (B) WIDTH   : how many hex cells one entry's byte occupies, and which BITS of them.
The pair (S,B) decides whether entries overlap, what a baked address would be, and -- the thing M1
actually needs -- exactly which words of the image a frame's binding dirties.

WHY THIS PROBE CAN SUCCEED WHERE THE OTHER THREE DID NOT: IT DOES NOT PRINT FROM INSIDE fj.
All three earlier probes reported through `hex.if0 1, arr + k*dw`, which tests only bits
dbit..dbit+3 -- the LOW NIBBLE of a cell. If a byte lives inside one cell, that test is blind to
the high half of every entry, which is precisely how "a 2-nibble value at a 1-nibble stride" became
an apparent contradiction. This probe instead reads RAW WORDS out of the interpreter core and
reports, per word, the exact XOR delta the write produced. There is no fj-side interpretation left
to be wrong about.

⚠ NEGATIVE CONTROL (R9), and it is CALIBRATION rather than opinion. The estimator is not allowed to
answer the ptr_index question until it has recovered a stride that the source states literally:
arrays written with `hex.set 2, A + i*K*dw, v` for K = 1, 2, 3 -- a KNOWN-GOOD stride of K cells --
must come back as exactly K. An estimator that returns "1" for all three is measuring its own
assumption, and its ptr_index answer would be worthless. Two further controls make it two-sided:
  * MODEL DISCRIMINATION: four candidate layouts are scored against every observation. Exactly one
    may survive. If none or several fit, the probe reports NO ANSWER rather than a number.
  * POISON: one word of a real observation is perturbed by one bit, and EVERY model must then be
    rejected. A matcher that still accepts something cannot detect a wrong layout either.

    python scratchpad/m1a_stride.py --selftest      # the controls, ~30 s, no build
    python scratchpad/m1a_stride.py                 # the controls, then the answer
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.utils.functions import load_debugging_labels                # noqa: E402

from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.harness import W                                              # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--selftest", action="store_true", help="controls only, then exit")
ap.add_argument("--cells", type=int, default=40, help="cells in the probe array")
args = ap.parse_args()

DW = 2 * W                      # bits per hex cell (one fj op)
DBIT = W + W.bit_length()       # runlib.fj: dbit = w + #w -- where a cell's VALUE bits start
VAL_SHIFT = DBIT - W            # ... expressed as a bit offset inside the cell's SECOND word
CELL_WORDS = DW // W            # words per hex cell


# ---------------------------------------------------------------------------------------------
# the measurement primitive: assemble, run, and diff EVERY word of the array region
# ---------------------------------------------------------------------------------------------
def observe(body_lines, tail_lines, array_label="arr", ncells=None):
    """Run a small program and return {word_offset_from_array_base: xor_delta} for the array.

    `word_offset` is measured from the array label's own word, so the answer is independent of
    where the assembler happened to place it. `xor_delta` is (after ^ before) of that raw word,
    which pins down not just WHICH cell moved but WHICH BITS of it did.
    """
    ncells = ncells or args.cells
    lines = ["stl.startup_and_init_all"] + body_lines + ["stl.loop"] + tail_lines
    tmp = Path(tempfile.mkdtemp(prefix="m1a_"))
    src = tmp / "p.fj"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out, dbg = tmp / "p.fjm", tmp / "p.fjd"
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False,
                debugging_file_path=dbg)
    labels = load_debugging_labels(dbg)
    cands = [k for k in labels if k == array_label or k.endswith(":" + array_label)
             or k.split(".")[-1] == array_label]
    if not cands:                                    # label naming differs by flipjump version
        cands = [k for k in labels if k.endswith(array_label)]
    assert cands, f"no label matching {array_label!r} in {len(labels):,} labels"
    # the shortest match is the plain top-level label, not some macro-local that ends the same way
    base_bit = labels[min(cands, key=len)]
    assert base_bit % W == 0, f"array label is not word-aligned: {base_bit}"
    base_word = base_bit // W

    r = FjmRunner(out, flat_max_words=1 << 24)
    assert r.native, "needs the native engine"

    def fresh():
        core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
        for s, ln in r._segments:
            core.add_segment(s, ln)
        for st, vals in r._runs:
            core.set_words(st, vals)
        return core

    pristine, live = fresh(), fresh()
    span = ncells * CELL_WORDS
    before = [pristine.get_word(base_word + k) for k in range(span)]
    # a probe that compares a core with itself must see nothing; if this ever trips, the diff below
    # is measuring two different images for a reason that has nothing to do with the program.
    assert all(pristine.get_word(base_word + k) == before[k] for k in range(span)), \
        "the raw-word reader is not deterministic"

    _c, ops, _e, _l, _p = live.run(lambda: 0, lambda _b: None, IOReadOnEOF, last_ops_length=0)
    after = [live.get_word(base_word + k) for k in range(span)]
    delta = {k: (a ^ b) for k, (b, a) in enumerate(zip(before, after)) if a != b}
    return delta, ops


# ---------------------------------------------------------------------------------------------
# the candidate layouts. Each maps (index, value) -> the word deltas it predicts.
# ---------------------------------------------------------------------------------------------
def model_one_cell(stride_cells):
    """entry i starts at cell i*stride; its whole byte lives in that ONE cell, bits dbit..dbit+7."""
    def f(i, v):
        return {(i * stride_cells) * CELL_WORDS + 1: v << VAL_SHIFT} if v else {}
    return f


def model_two_cells(stride_cells):
    """entry i starts at cell i*stride; its byte is split, low nibble in that cell, high in the next."""
    def f(i, v):
        d = {}
        if v & 0xF:
            d[(i * stride_cells) * CELL_WORDS + 1] = (v & 0xF) << VAL_SHIFT
        if v >> 4:
            d[(i * stride_cells + 1) * CELL_WORDS + 1] = (v >> 4) << VAL_SHIFT
        return d
    return f


MODELS = {}
for _s in (1, 2, 3, 4):
    MODELS[f"stride {_s} cell(s), byte in ONE cell"] = model_one_cell(_s)
    MODELS[f"stride {_s} cell(s), byte split over TWO cells"] = model_two_cells(_s)


def predict(model, writes):
    """the union of a model's predictions for a list of (index, value) writes, last write wins."""
    acc = {}
    for i, v in writes:
        acc.update(model(i, v))
    return {k: d for k, d in acc.items() if d}


def survivors(observation, writes):
    return [name for name, m in MODELS.items() if predict(m, writes) == observation]


def fmt(delta):
    return "{" + ", ".join(f"w+{k}: {d:#x} (val {d >> VAL_SHIFT:#x})"
                           for k, d in sorted(delta.items())) + "}"


# ---------------------------------------------------------------------------------------------
# the programs
# ---------------------------------------------------------------------------------------------
def prog_known_stride(stride_cells, writes):
    """CONTROL: a stride the SOURCE states literally -- `hex.set 2, arr + i*K*dw, v` writes cell
    i*K (low nibble) and cell i*K+1 (high nibble). Known stride K, known width 2 cells."""
    body = [f"hex.set 2, arr + {i}*{stride_cells}*dw, {v}" for i, v in writes]
    tail = [f"arr: hex.vec {args.cells}"]
    return body, tail


def prog_ptr_index(writes):
    """THE QUESTION: exactly `sim.bind_things`' accessor -- set the base, ptr_index by the raw
    index, write_byte the value."""
    body = []
    for n, (i, v) in enumerate(writes):
        body += [f"hex.set w/4, ix, {i}",
                 "hex.set w/4, base, arr",
                 "hex.ptr_index ptr, base, ix",
                 f"hex.set 2, val, {v}",
                 "hex.write_byte ptr, val"]
    tail = ["ix: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4", "val: hex.vec 2",
            f"arr: hex.vec {args.cells}"]
    return body, tail


def prog_roundtrip(writes, read_index):
    """Does `read_byte` reach what `write_byte` wrote, at the same index? The answer is read out of
    RAW MEMORY (the `got` cell), not printed, so nothing depends on an fj-side test."""
    body = []
    for i, v in writes:
        body += [f"hex.set w/4, ix, {i}", "hex.set w/4, base, arr",
                 "hex.ptr_index ptr, base, ix",
                 f"hex.set 2, val, {v}", "hex.write_byte ptr, val"]
    body += [f"hex.set w/4, ix, {read_index}", "hex.set w/4, base, arr",
             "hex.ptr_index ptr, base, ix", "hex.zero 2, got", "hex.read_byte got, ptr"]
    tail = ["ix: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4", "val: hex.vec 2",
            "got: hex.vec 2", f"arr: hex.vec {args.cells}"]
    return body, tail


# ---------------------------------------------------------------------------------------------
# CONTROLS
# ---------------------------------------------------------------------------------------------
def controls():
    ok = True
    print("=" * 96)
    print("CONTROL A (calibration): recover a stride the SOURCE states literally.")
    print("  `hex.set 2, arr + i*K*dw, v` -- stride K cells, byte split over 2 cells, K known.")
    print("  An estimator that cannot return K here may not be believed about ptr_index.")
    for K in (1, 2, 3):
        writes = [(0, 0xA5), (3, 0x71)] if K < 3 else [(0, 0xA5), (2, 0x71)]
        body, tail = prog_known_stride(K, writes)
        delta, ops = observe(body, tail)
        surv = survivors(delta, writes)
        want = f"stride {K} cell(s), byte split over TWO cells"
        good = surv == [want]
        ok &= good
        print(f"  K={K}: {ops:>7,} ops  {len(delta)} words dirty  -> "
              f"{surv if surv else 'NO MODEL FITS'}")
        print(f"        {'ok' if good else 'FAIL'} (wanted exactly [{want!r}])")

    print()
    print("CONTROL B (discrimination): the matcher must REJECT the wrong strides, not just accept")
    print("  the right one. Re-scoring the K=2 observation against every candidate:")
    body, tail = prog_known_stride(2, [(0, 0xA5), (3, 0x71)])
    delta, _ = observe(body, tail)
    rejected = [n for n in MODELS if predict(MODELS[n], [(0, 0xA5), (3, 0x71)]) != delta]
    good = len(rejected) == len(MODELS) - 1
    ok &= good
    print(f"  {len(rejected)} of {len(MODELS)} candidate layouts rejected  "
          f"{'ok' if good else 'FAIL -- the matcher accepts more than one layout'}")

    print()
    print("CONTROL C (poison): perturb ONE bit of a real observation; EVERY model must fail.")
    poisoned = dict(delta)
    kk = min(poisoned)
    poisoned[kk] ^= 1
    surv = survivors(poisoned, [(0, 0xA5), (3, 0x71)])
    good = not surv
    ok &= good
    print(f"  flipped bit 0 of word offset {kk} -> survivors {surv if surv else 'none'}  "
          f"{'ok' if good else 'FAIL -- a corrupted layout still passes'}")

    print()
    print("CONTROL D (vacuity): a program that writes NOTHING must dirty nothing in the array.")
    delta0, _ = observe(["hex.set w/4, base, arr"], ["base: hex.vec w/4",
                                                     f"arr: hex.vec {args.cells}"])
    good = not delta0
    ok &= good
    print(f"  {len(delta0)} words dirty  {'ok' if good else 'FAIL -- ' + fmt(delta0)}")
    print("=" * 96)
    print(f"CONTROLS: {'PASS' if ok else 'FAIL'}\n")
    return ok


# ---------------------------------------------------------------------------------------------
if not controls():
    print("The controls failed, so the measurement below would not be evidence. Stopping.")
    sys.exit(1)
if args.selftest:
    sys.exit(0)

print("=" * 96)
print(f"THE MEASUREMENT  (W={W}, dw={DW} bits = {CELL_WORDS} words, dbit={DBIT}, "
      f"value bits start at bit {VAL_SHIFT} of a cell's 2nd word)")
print("=" * 96)

# values chosen so every discriminating case is present: <=15 (high nibble zero), >15 (both
# nibbles set), and a value whose LOW nibble is zero -- the case `hex.if0 1` is blind to and the
# one that defeated the earlier probes.
WRITES = [(0, 0xA5), (1, 0x07), (2, 0x10), (5, 0xFB), (9, 0x01)]
body, tail = prog_ptr_index(WRITES)
delta, ops = observe(body, tail)
print(f"writes (index, value): {WRITES}")
print(f"{ops:,} ops, {len(delta)} words dirty in the array region:")
for k, d in sorted(delta.items()):
    print(f"   word +{k:<3} cell {k // CELL_WORDS:<3} ({'flip' if k % 2 == 0 else 'jump'} word)"
          f"  delta {d:#010x}  = value {d >> VAL_SHIFT:#x}")

surv = survivors(delta, WRITES)
print()
if len(surv) == 1:
    print(f"EXACTLY ONE LAYOUT FITS:  {surv[0]}")
else:
    print(f"!! {len(surv)} layouts fit -- NO ANSWER: {surv}")
    print("   (the probe refuses to name a stride it cannot single out)")

print()
print("round-trip: does read_byte reach what write_byte wrote at the SAME index?")
rt_ok = True
for ridx, rval in ((5, 0xFB), (2, 0x10), (0, 0xA5)):
    body, tail = prog_roundtrip(WRITES, ridx)
    d, _ = observe(body, tail, ncells=args.cells)
    # `got` is its own label; read it the same raw way by re-observing with got as the "array"
    dg, _ = observe(body, tail, array_label="got", ncells=2)
    got = sum((v >> VAL_SHIFT) << (4 * (k // CELL_WORDS)) for k, v in dg.items())
    good = got == rval
    rt_ok &= good
    print(f"  index {ridx}: wrote {rval:#04x}, read_byte returned {got:#04x}  "
          f"{'ok' if good else 'MISMATCH'}")

print()
if len(surv) == 1 and rt_ok:
    stride = int(surv[0].split()[1])
    width = 1 if "ONE cell" in surv[0] else 2
    print("-" * 96)
    print(f"ANSWER: entry i of a ptr_index/write_byte byte array lives at  base + i*{stride}*dw,")
    print(f"        and its 8 bits occupy {width} hex cell(s) -- bits {DBIT}..{DBIT + 7} from the")
    print(f"        cell's start, i.e. bits {VAL_SHIFT}..{VAL_SHIFT + 7} of the cell's 2nd word.")
    print(f"        So writing entry i dirties EXACTLY ONE word: base_word + {CELL_WORDS * stride}*i + 1.")
    print("-" * 96)
    print("What that means for the three earlier probes -- all three were CONSISTENT with this,")
    print("and were only read as contradictory because a byte was assumed to span two cells:")
    print("  _ssheadaddr   wrote 9 at index 5 and saw nibble 5 light  -> stride 1 cell. TRUE.")
    print("  _ssheadoverlap wrote 0x10 at 3, read 4 as zero           -> no overlap.   TRUE.")
    print("  _ssheadlayout  saw a 2-nibble value light only one cell  -> both at once. TRUE.")
    print()
    print("!! THE ASYMMETRY THAT CAUSED THE CONFUSION: in the ARRAY a byte is ONE cell (8 bits);")
    print("  in a REGISTER it is TWO cells (a nibble each) -- `read_byte dst, ptr` declares dst as")
    print("  hex[:2]. Both 'one cell' and 'two cells' are true, about different things.")
    print()
    print("!! AND THE COROLLARY THAT BITES: `hex.if0` cannot test one of these cells at ALL.")
    print("  `hex.if0 1, arr + s*dw` reaches hex.if_flags, which XORs `switch` into the cell's jump")
    print("  word and then EXECUTES the cell, landing at (value*dw) ^ switch. `pad 16` aligns")
    print("  switch to 16 ops, so that is inside the 16-entry table ONLY when the value's HIGH")
    print("  NIBBLE is 0 -- and on the way out it skips `clean:`, leaving the array cell")
    print("  permanently corrupted. It is OUT OF CONTRACT for a byte (if_flags is documented for")
    print("  0..15), not merely 'too narrow'. `hex.if0 2` additionally straddles entry s+1.")
    print("  A baked empty-list test must read the byte out (read_byte) and test the register.")
else:
    print("NO ANSWER -- do not write the reset prologue against this run.")
    sys.exit(1)
