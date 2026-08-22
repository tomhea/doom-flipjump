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
import hashlib
import json
from pathlib import Path

import flipjump as fj
import flipjump.assembler.assembler as _asm

from doomfj.harness import W

DW = 2 * W
VAL_SHIFT = (W + W.bit_length()) - W

# Arrays written through hex.write_byte: 8 bits in ONE cell, so they need m1.zerobyte and a
# nibble op on one CORRUPTS it. drawn and sprflag are deliberately absent: they are write_byte
# arrays too, but only ever hold small values -- frame.mark_drawn writes 1, sprflag writes 1 or 2
# -- so the 19.5-op nibble clear is correct for them and 91 ops each would be waste.
#
# The reachable CELL COUNT of each is DERIVED, never hardcoded (R6). sshead is declared
# hex.vec 2*nss and a 1-cell stride reaches only nss of it; pclm and sfflag are declared VIEW_W.
# Two independent sources must agree: the label EXTENT in this build's own table, and the geometry
# the caller passes (cfg.VIEW_W and len(cmap.subsectors)).
#
# WHY THIS MATTERS AND WHY NO GATE WOULD CATCH IT: the coverage assert below fires only when the
# count is too LARGE. Hardcode 160 and raise VIEW_W, or move to a map with more subsectors, and the
# extra byte cells silently fall out of the byte set, land in the nibble set, and get nibble-cleared
# -- which corrupts rather than fails (0xA5 -> 0x22A5). It stays byte-exact on the old map, so
# every gate passes.
BYTE_ARRAY_NAMES = ("sshead", "pclm", "sfflag")
# declared cells per reachable cell: sshead is over-allocated 2x, the per-column arrays are 1:1
_DECLARED_RATIO = {"sshead": 2, "pclm": 1, "sfflag": 1}



def byte_arrays(bits, words_sorted, view_w, nss):
    """Reachable cell count per write_byte array, derived and cross-checked two ways.

    `extent // 2` is the DECLARED cell count (2 words per cell); dividing by the declared ratio
    gives what a 1-cell stride can actually reach. The caller's geometry must agree, so a change to
    VIEW_W or to the map that this file does not know about fails the build instead of silently
    nibble-clearing byte cells.
    """
    expect = {"sshead": nss, "pclm": view_w, "sfflag": view_w}
    out = []
    for name in BYTE_ARRAY_NAMES:
        assert name in bits, "self-reset: byte array %r is not in the label table" % name
        base = bits[name] // W
        declared_cells = (_extent(words_sorted, base) - base) // 2
        derived = declared_cells // _DECLARED_RATIO[name]
        assert derived == expect[name], (
            "self-reset: %s spans %d declared cells -> %d reachable, but the geometry says %d. "
            "The emitter's declaration and cfg/map disagree; a hardcoded count here would "
            "silently nibble-clear byte cells." % (name, declared_cells, derived, expect[name]))
        out.append((name, derived))
    return out


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



def load_restore_set(path, labels, check_layout=True):
    """Resolve a LABEL+OFFSET restore set against THIS assembly's label table.

    The set is stored label-relative on purpose. Absolute word addresses are valid only for the one
    assembly they were derived from, and as a build input that is a landmine: a layout shift would
    silently point the reset at the wrong cells, and the pass1-vs-pass2 check cannot catch it
    because it compares the two passes to each other, not to the set.
    """
    doc = json.load(gzip.open(path, "rt", encoding="utf-8"))
    assert doc.get("format") == "label+offset",         "restore set %s is not label-relative; regenerate with scratchpad/m1_setfile.py" % path
    # PROVENANCE (R9), and be precise about which half is which.
    #
    # source_sha256 / labels_sha256 / generated_by are PROVENANCE FOR A HUMAN. They are asserted
    # present and are NEVER compared against the program being built -- they cannot be: a comment
    # edit anywhere renames the `f<file>:l<line>` macro-expansion labels, so a whole-table hash
    # would never match again. Do not read them as closing the "wrong program" hazard.
    for k in ("source_sha256", "labels_sha256", "generated_by"):
        assert doc.get(k),             "restore set %s carries no %s; regenerate with scratchpad/m1_setfile.py" % (path, k)

    base = {}
    for k, v in labels.items():
        base.setdefault(k, int(v) // W)
    addrs = sorted(set(base.values()))

    out = set()
    missing, escaped = [], []
    for entry in doc["entries"]:
        name = entry[0]
        if name not in base:
            missing.append(name)
            continue
        b = base[name]
        # CONTAINMENT (R9). Attribution is nearest-preceding-label, so an offset is only meaningful
        # while it stays inside that label's span. If THIS build spaces the labels differently, an
        # offset can run past the next label and point at an unrelated cell -- resolving "clean"
        # while restoring the wrong words. verify_labels_unchanged cannot see this: it compares
        # pass 1 to pass 2 of the same program, never the set to the program.
        i = bisect.bisect_right(addrs, b)
        # ⚠ ONE-SIDED AT THE TOP OF THE ADDRESS SPACE was the shape of the round-2 bug, so the
        # highest-addressed label is bounded too. CR round 7: be exact about WHAT it is bounded by
        # -- `addrs[-1] + 2` is that label's own address plus ONE CELL, not "the program's extent"
        # as an earlier comment claimed. That is the tightest bound available here (this function
        # sees only the label table, never the image), and it is inert today because no set label
        # is the global maximum. The claim is narrowed to what the code does.
        span = (addrs[i] - b) if i < len(addrs) else 2
        for off in entry[1:]:
            if off >= span:
                escaped.append((name, off, span))
            out.add(b + off)
    assert not missing, ("restore set names %d labels this build does not have, e.g. %s -- the set "
                         "was derived from a different program" % (len(missing), missing[:3]))
    assert not escaped, ("restore set: %d offsets run past the end of the label they are relative "
                         "to, e.g. %s (name, offset, span) -- this build lays those labels out "
                         "differently, so the set does not describe it" % (len(escaped), escaped[:3]))
    assert len(out) == doc["words"],         "restore set resolved to %d words, expected %d" % (len(out), doc["words"])

    # THE HALF THAT IS ACTUALLY CHECKED: a LAYOUT FINGERPRINT over the set's OWN labels -- sha256
    # of the sorted (name, span_words) pairs. It is invariant to line-number churn elsewhere in the
    # program, which is what makes a whole-table hash useless here, and it catches what resolution
    # + containment + count miss: a set whose names all happen to exist and whose offsets all
    # happen to fit, but whose labels are laid out differently.
    #
    # ⚠ SCOPE (CR round 7 measured this): over the shipped set the 308 labels have only TEN
    # distinct span values -- 2400 of them share span 2, 320 share span 4. So the discriminating
    # power sits in the few wide, resolution-or-map-dependent rows (sshead's 2*nss, the VIEW_W
    # arrays), not uniformly across 308 labels. It is a real check, not a strong hash.
    want = doc.get("layout_fingerprint")
    assert want, ("restore set %s has no layout_fingerprint; regenerate with "
                  "scratchpad/m1_setfile.py" % path)
    if not check_layout:
        return out
    got = layout_fingerprint(doc, labels)
    assert got == want, (
        "restore set layout fingerprint %s != %s -- the labels this set names are laid out "
        "DIFFERENTLY in this build, so it describes a different program. Resolution and "
        "containment cannot see this on their own." % (got[:12], str(want)[:12]))
    return out


def layout_fingerprint(doc, labels):
    """sha256 over the sorted (label, span-in-words) pairs of the labels the SET names."""
    base = {}
    for k, v in labels.items():
        base.setdefault(k, int(v) // W)
    addrs = sorted(set(base.values()))
    h = hashlib.sha256()
    for name in sorted(e[0] for e in doc["entries"]):
        if name not in base:
            continue
        b = base[name]
        i = bisect.bisect_right(addrs, b)
        span = (addrs[i] - b) if i < len(addrs) else -1
        h.update(("%s:%d;" % (name, span)).encode())
    return h.hexdigest()


def _extent(words_sorted, addr_word):
    i = bisect.bisect_right(words_sorted, addr_word)
    return words_sorted[i] if i < len(words_sorted) else addr_word + 2


def emit_reset_part(gen, labels, pristine_get_word, restore_set_path, view_w, nss,
                    mapname="e1m1"):
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

    # R6: code_start is not a literal. Word 1 is op 0's jump field and its PRISTINE value IS
    # code_start, so the program states where its own code begins.
    code_start_word = pristine_get_word(1) // W
    assert 0 < code_start_word < 1 << 24,         "self-reset: derived code_start word %d is implausible" % code_start_word

    words = sorted(load_restore_set(restore_set_path, bits))
    words = [x for x in words if x >= code_start_word]
    wset = set(words)

    byte_words, byte_bases, declared_words = set(), [], set()
    for name, n in byte_arrays(bits, words_sorted, view_w, nss):
        base = bits[name] // W
        byte_bases.append((name, bits[name], n))
        declared_words.update(range(base, _extent(words_sorted, base)))
        for k in range(n):
            byte_words.add(base + 2 * k)
            byte_words.add(base + 2 * k + 1)
    missing = byte_words - wset
    assert not missing, ("self-reset: %d byte-array words are outside the restore set -- "
                         "the byte arrays disagree with it" % len(missing))
    # THE OTHER SIDE OF THE SAME GUARD, and the one that was missing. The assert above catches a
    # byte cell the set forgot; this one catches a set word that lies INSIDE a byte array's
    # DECLARED extent but outside its REACHABLE part. Such a word would fall through to `nib` and
    # be nibble-cleared -- and if the reachable count were ever wrong, that is precisely the
    # corruption this module exists to prevent, arriving silently and byte-exact.
    #
    # It fires on the pre-2026-08-21 set, which carried each label's whole extent: sshead is
    # declared hex.vec 2*nss but a 1-cell stride reaches only nss, so 1,364 words of unreachable
    # padding were being nibble-cleared -- ~682 dead cells, MEASURED at 0 dirty words across all
    # five dirty maps in scratchpad/, i.e. provably-dead work, not corruption. The set is trimmed
    # now; this assert is what keeps it trimmed.
    stray = sorted((wset & declared_words) - byte_words)
    assert not stray, (
        "self-reset: %d restore-set words lie inside a byte array's declared extent but outside "
        "its reachable part (e.g. %s). They would be NIBBLE-cleared, which corrupts a byte cell "
        "rather than failing. Re-generate the set with scratchpad/m1_setfile.py, which trims the "
        "unreachable tail." % (len(stray), stray[:3]))
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
    """Return the labels the restore set NAMES whose address moved between the two passes.

    Empty means the bake is sound: the reset writes addresses taken from pass 1, so if any of them
    moved in pass 2 the binary must be refused.

    ⚠⚠ THIS WAS WRONG UNTIL CR ROUND 7, AND IT WAS WRONG IN THE DIRECTION THAT SHIPS A BAD BINARY.
    It used to resolve the set against the PASS-2 table and then test whether each PASS-1 address
    was a member:

        s = load_restore_set(path, new, check_layout=False)
        if old[k] != new[k] and ((old[k] // W) in s or (old[k] // W + 1) in s): ...

    A label that moves by ONE word still has its old address inside the new-resolved set, so
    1-word moves were caught -- which is what made the bug invisible. A label that moves TWO OR
    MORE words does not, so it was reported CLEAN. Measured, on this exact code:

        alpha 100 -> 101   ['alpha']     caught
        alpha 100 -> 102   []            REPORTED CLEAN
        alpha 100 -> 110   []            REPORTED CLEAN
        alpha 100 ->  90   []            REPORTED CLEAN

    `build.py` asserts `not moved` and then records `labels_moved_in_set: 0` -- a field that could
    not tell "nothing moved" from "something moved two words". The layout fingerprint DOES catch
    all four cases, and this function used to switch it off with check_layout=False, justified by a
    comment claiming the opt-out cost only a nicer diagnostic. It cost the detection.

    The check is TOTAL now: every label the set names is compared directly, and the two resolved
    word sets must be equal. A membership test replaced a min..max range test in §7.8 to kill false
    positives; it introduced a false negative. Comparing the two tables has neither.
    """
    doc = json.load(gzip.open(restore_set_path, "rt", encoding="utf-8"))
    named = {e[0] for e in doc["entries"]}
    moved = sorted(k for k in named if k in old and k in new and old[k] != new[k])

    # Belt and braces, and it is what makes this total rather than name-by-name: the addresses the
    # reset actually bakes must be identical under both tables.
    a = load_restore_set(restore_set_path, old, check_layout=False)
    b = load_restore_set(restore_set_path, new, check_layout=False)
    if a != b and not moved:
        moved = ["<%d baked addresses differ between the passes>" % len(a ^ b)]
    return moved
