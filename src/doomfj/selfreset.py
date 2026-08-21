"""M1 -- the self-reset prologue and the internal frame LOOP.

The fj program self-modifies, so historically the host restored a pristine image before every
frame. This module makes the program do it itself: a reset appended as a final program part, plus a
size-neutral patch turning the frame's trailing halt into a jump to that reset, which ends by
re-entering the frame at __hot_end. One execution then renders as many frames as the wire feeds.

WHY IT NEEDS TWO PASSES. Most of what a frame leaves dirty is macro-local scratch, and fj cannot
name a macro's local from outside it -- restoring only the fj-addressable declared state leaves up
to 4,495 pixels wrong (measured). So the reset bakes NUMERIC addresses taken from a first assembly
of the very same program. That is sound only because the new part is APPENDED and the main patch is
size-neutral (stl.loop -> ;m1_reset, one op either way), so no existing label moves -- and
verify_labels_unchanged re-checks exactly that before the binary is accepted.

The one new primitive, m1.zerobyte, lives in src/fj/m1_reset.fj. See docs/handoff-m1-reset.md.
The restore set is derived by the scratchpad pipeline and passed in as a file.
"""
from __future__ import annotations

import bisect
import gzip
import json
from pathlib import Path

import flipjump as fj
import flipjump.assembler.assembler as _asm

from doomfj.harness import W

DW = 2 * W
VAL_SHIFT = (W + W.bit_length()) - W
CODE_START_WORD = 17308

# Arrays written through hex.write_byte: 8 bits in ONE cell, so they need m1.zerobyte.
# n is the number of cells the program can REACH (a 1-cell stride), not the declared hex.vec size.
# drawn and sprflag are deliberately absent: they are write_byte-written but only ever hold small
# values -- frame.mark_drawn writes 1, sprflag writes 1 or 2 -- so the 19.5-op nibble clear is
# correct for them, and 91 ops each would be waste.
BYTE_ARRAYS = [("sshead", 682), ("pclm", 160), ("sfflag", 160)]


def capture_labels(paths, out_fjm, lzma_fast=True):
    """Assemble, and return the USER label table without paying for the debug-only families.

    assembler.assemble calls save_debugging_labels unconditionally and it returns early on a None
    path, so hooking it yields the labels for free while debugging_file_path=None keeps the
    :wflips:N and ---:start: families (16.1M + 1.7M entries on this program) from being built at
    all. The .fjm is byte-identical either way.
    """
    got = {}

    def hook(_path, labels):
        got.update(labels)

    prev = _asm.save_debugging_labels
    _asm.save_debugging_labels = hook
    try:
        fj.assemble([Path(p).resolve() for p in paths], Path(out_fjm), memory_width=W,
                    print_time=False, lzma_fast=lzma_fast)
    finally:
        _asm.save_debugging_labels = prev
    return got



def load_restore_set(path, labels):
    """Resolve a LABEL+OFFSET restore set against THIS assembly's label table.

    The set is stored label-relative on purpose. Absolute word addresses are valid only for the one
    assembly they were derived from, and as a build input that is a landmine: a layout shift would
    silently point the reset at the wrong cells, and the pass1-vs-pass2 check cannot catch it
    because it compares the two passes to each other, not to the set.
    """
    doc = json.load(gzip.open(path, "rt", encoding="utf-8"))
    assert doc.get("format") == "label+offset",         "restore set %s is not label-relative; regenerate with scratchpad/m1_setfile.py" % path
    base = {}
    for k, v in labels.items():
        base.setdefault(k, int(v) // W)
    out = set()
    missing = []
    for entry in doc["entries"]:
        name = entry[0]
        if name not in base:
            missing.append(name)
            continue
        b = base[name]
        for off in entry[1:]:
            out.add(b + off)
    assert not missing, ("restore set names %d labels this build does not have, e.g. %s -- the set "
                         "was derived from a different program" % (len(missing), missing[:3]))
    assert len(out) == doc["words"],         "restore set resolved to %d words, expected %d" % (len(out), doc["words"])
    return out


def _extent(words_sorted, addr_word):
    i = bisect.bisect_right(words_sorted, addr_word)
    return words_sorted[i] if i < len(words_sorted) else addr_word + 2


def emit_reset_part(gen, labels, pristine_get_word, restore_set_path, mapname="e1m1"):
    """Write <map>_07_reset.fj and patch the main part into a loop.

    Returns (part_path, nibble_cells, byte_cells). pristine_get_word(word) reads the FIRST
    assembly's image -- that is where the value a non-zero cell is restored TO comes from, so it is
    never re-derived.
    """
    gen = Path(gen)
    bits = {}
    for k, v in labels.items():
        bits.setdefault(k, int(v))
    words_sorted = sorted(v // W for v in bits.values())

    words = sorted(load_restore_set(restore_set_path, bits))
    words = [x for x in words if x >= CODE_START_WORD]
    wset = set(words)

    byte_words, byte_bases = set(), []
    for name, n in BYTE_ARRAYS:
        assert name in bits, "self-reset: byte array %r is not in the label table" % name
        base = bits[name] // W
        byte_bases.append((name, bits[name], n))
        for k in range(n):
            byte_words.add(base + 2 * k)
            byte_words.add(base + 2 * k + 1)
    missing = byte_words - wset
    assert not missing, ("self-reset: %d byte-array words are outside the restore set -- "
                         "BYTE_ARRAYS disagrees with it" % len(missing))
    nib = sorted(wset - byte_words)

    # Drop read-only/code regions. A cell only nibble ops ever write cannot hold a pristine value
    # above 15, so anything that does is a packed LUT, code, or an extent that overran its
    # declaration. Derived, not a hand-kept list, so a new LUT is excluded automatically.
    ro = set()
    for x in nib:
        if x % 2 and (pristine_get_word(x) >> VAL_SHIFT) > 15:
            i = bisect.bisect_right(words_sorted, x) - 1
            ro.add(words_sorted[i])
    if ro:
        drop = set()
        for base in ro:
            drop.update(range(base, _extent(words_sorted, base)))
        nib = [x for x in nib if x not in drop]

    cells = sorted({x // 2 for x in nib})
    vals = {}
    for c in cells:
        v = pristine_get_word(2 * c + 1) >> VAL_SHIFT
        assert v <= 15, ("self-reset: cell at word %d has pristine value %#x > 15 -- a nibble op "
                         "would CORRUPT it; it belongs in BYTE_ARRAYS or out of the set"
                         % (2 * c, v))
        vals[c] = v

    lines, i = [], 0
    while i < len(cells):
        if vals[cells[i]]:
            lines.append("    hex.set 1, %d, %d" % (cells[i] * DW, vals[cells[i]]))
            i += 1
            continue
        j = i
        while j + 1 < len(cells) and cells[j + 1] == cells[j] + 1 and not vals[cells[j + 1]]:
            j += 1
        lines.append("    hex.zero %d, %d" % (j - i + 1, cells[i] * DW))
        i = j + 1
    for name, base_bits, n in byte_bases:
        # rep needs a LITERAL count; a rep whose count is a macro PARAMETER silently expands to
        # nothing, so the rep lives here, where n is a number.
        lines.append("    rep(%d, i) m1.zerobyte %d + i*dw      // %s" % (n, base_bits, name))
    lines.append("    ;__hot_end")

    hdr = ["// == M1: the self-reset prologue ======================================",
           "//   Restores every cell a frame leaves dirty, then re-enters the frame",
           "//   at __hot_end -- what replaces the host whole-image restore.",
           "//   ADDRESSES ARE BAKED, from a first assembly of THIS program; the build",
           "//   re-checks every one and refuses the binary if any moved.",
           "//   m1.zerobyte is defined in src/fj/m1_reset.fj.",
           "// =====================================================================",
           "m1_reset:"]
    part = gen / ("%s_07_reset.fj" % mapname.lower())
    part.write_text("\n".join(hdr + lines) + "\n", encoding="utf-8")

    main = gen / ("%s_02_main.fj" % mapname.lower())
    old_lines = main.read_text(encoding="utf-8").split("\n")
    hits = [k for k, l in enumerate(old_lines) if l.strip() == "stl.loop"]
    assert len(hits) == 1, ("self-reset: expected exactly 1 bare stl.loop (the frame tail), "
                            "found %d" % len(hits))
    assert sum(1 for l in old_lines if l.strip() == "bad: stl.loop") == 1, \
        "self-reset: bad: stl.loop (the junk-input halt) is not where it was"
    assert old_lines[hits[0] - 1].strip() == "stl.output_char 0xFF", \
        "self-reset: the line before the frame tail is not the 0xFF end-of-frame marker"
    new_lines = list(old_lines)
    new_lines[hits[0]] = ";m1_reset"          # 1 op -> 1 op: size-neutral, so nothing moves
    assert len(new_lines) == len(old_lines)
    main.write_text("\n".join(new_lines), encoding="utf-8")
    return part, len(cells), sum(n for _nm, _b, n in byte_bases)


def verify_labels_unchanged(old, new, restore_set_path):
    """Return the labels INSIDE the restored set whose address moved. Empty means the bake is sound.

    Membership, not a min..max range: the set spans tens of millions of words with enormous holes.
    A handful of CODE labels legitimately move -- hex.exact_xor's end/switch sit at wflip-chain
    spots whose recycled pad slots shift when the program gains wflips -- and a range test flags
    those while a membership test correctly ignores them.
    """
    s = load_restore_set(restore_set_path, new)
    out = []
    for k in set(old) & set(new):
        if old[k] != new[k] and ((old[k] // W) in s or (old[k] // W + 1) in s):
            out.append(k)
    return out
