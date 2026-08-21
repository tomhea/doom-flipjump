"""M1 -- the self-reset machinery's host logic (src/doomfj/selfreset.py).

The self-reset bakes NUMERIC addresses into the program, so the two functions that decide WHICH
addresses are load-bearing in a way a 40-minute build cannot check for you: get them wrong and the
reset writes the wrong cells, which does not produce a wrong pixel -- it produces a different
program. Both are pure logic over a label table, so they are testable in milliseconds.

Every test here is a NEGATIVE control in the R9 sense: each one breaks something real and requires
the code to refuse. A test that only fed valid input would pass just as happily against a function
that never checked anything.
"""
import gzip
import json

import pytest

from doomfj.harness import W
from doomfj import selfreset
from doomfj.selfreset import (BYTE_ARRAY_NAMES, byte_arrays, load_restore_set,
                              verify_labels_unchanged)


def _set_file(tmp_path, entries, words=None, fmt="label+offset", provenance=True):
    p = tmp_path / "set.json.gz"
    n = words if words is not None else sum(len(e) - 1 for e in entries)
    doc = {"format": fmt, "words": n, "labels": len(entries), "entries": entries}
    if provenance:
        doc.update(source_sha256="x" * 64, labels_sha256="y" * 64, generated_by="test")
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(doc, f)
    return p


LABELS = {"alpha": 100 * W, "beta": 500 * W, "gamma": 900 * W}


def test_resolves_label_plus_offset_to_absolute_words(tmp_path):
    p = _set_file(tmp_path, [["alpha", 0, 1, 2], ["beta", 10, 11]])
    got = load_restore_set(p, LABELS)
    assert got == {100, 101, 102, 510, 511}


def test_refuses_a_set_naming_a_label_this_build_does_not_have(tmp_path):
    """The failure this exists for: the set was derived against a DIFFERENT program.

    It is not hypothetical -- putting m1_reset.fj into the includes renumbered 200 of the set's
    labels, because a macro-expansion label is named f<file>:l<line>:... and inserting a file
    renumbers every file after it.
    """
    p = _set_file(tmp_path, [["alpha", 0], ["nosuchlabel", 3]])
    with pytest.raises(AssertionError, match="labels this build does not have"):
        load_restore_set(p, LABELS)


def test_refuses_an_absolute_address_set(tmp_path):
    """Absolute addresses are only valid for the assembly they came from -- refuse them outright."""
    p = tmp_path / "abs.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump({"runs": [[10, 20]]}, f)
    with pytest.raises(AssertionError, match="not label-relative"):
        load_restore_set(p, LABELS)


def test_refuses_when_the_resolved_word_count_disagrees(tmp_path):
    """A stated size that does not match what resolved means the file and the table disagree."""
    p = _set_file(tmp_path, [["alpha", 0, 1]], words=99)
    with pytest.raises(AssertionError, match="resolved to"):
        load_restore_set(p, LABELS)


def test_duplicate_offsets_do_not_inflate_the_count(tmp_path):
    """Resolution is a SET: the same word named twice is one word, and `words` must reflect that."""
    p = _set_file(tmp_path, [["alpha", 0, 0, 1]], words=2)
    assert load_restore_set(p, LABELS) == {100, 101}


def test_verify_flags_a_label_that_moved_INSIDE_the_restored_set(tmp_path):
    p = _set_file(tmp_path, [["alpha", 0, 1]])
    old = dict(LABELS)
    new = dict(LABELS)
    new["alpha"] = 101 * W                      # the restored region itself moved
    assert verify_labels_unchanged(old, new, p) == ["alpha"]


def test_verify_ignores_a_label_that_moved_OUTSIDE_the_restored_set(tmp_path):
    """The real build sees ~32 such labels every time -- hex.exact_xor's end/switch sit at
    wflip-chain spots whose recycled pad slots shift when the program gains wflips. They are code,
    not restored cells. A min..max RANGE test flags them; membership correctly does not."""
    p = _set_file(tmp_path, [["alpha", 0, 1]])
    old = dict(LABELS)
    new = dict(LABELS)
    new["gamma"] = 12345 * W                    # far outside the set, and far from alpha
    assert verify_labels_unchanged(old, new, p) == []


def test_verify_is_clean_when_nothing_moved(tmp_path):
    p = _set_file(tmp_path, [["alpha", 0, 1], ["beta", 0]])
    assert verify_labels_unchanged(dict(LABELS), dict(LABELS), p) == []


# ---------------------------------------------------------------------------------------------
# The R6/R9 fixes from the CR of PR #76. Each of these guards a failure that is BYTE-EXACT on the
# map we ship, so no rendering gate can see it.
# ---------------------------------------------------------------------------------------------

def _fake_labels(spec):
    """spec: {name: (word_addr, declared_cells)} -> a bit-address label dict with a next label
    placed exactly `declared_cells` cells later, which is what the extent derivation reads."""
    out = {}
    for name, (base, cells) in spec.items():
        out[name] = base * W
        out["_after_" + name] = (base + 2 * cells) * W
    return out


def _byte_call(spec, view_w, nss):
    bits = _fake_labels(spec)
    return byte_arrays(bits, sorted(v // W for v in bits.values()), view_w, nss)


def test_byte_array_counts_are_derived_not_hardcoded():
    """sshead is declared 2*nss cells and a 1-cell stride reaches nss; the per-column arrays are
    declared VIEW_W and reach VIEW_W."""
    spec = {"sshead": (1000, 1364), "pclm": (10000, 200), "sfflag": (20000, 200)}
    assert _byte_call(spec, 200, 682) == [("sshead", 682), ("pclm", 200), ("sfflag", 200)]


def test_byte_array_counts_follow_a_wider_viewport():
    """THE BUG THIS EXISTS FOR. With a hardcoded 160 a wider VIEW_W leaves the extra byte cells in
    the NIBBLE set, where the clear CORRUPTS them (0xA5 -> 0x22A5) instead of failing -- and it
    stays byte-exact on the old map, so every gate passes."""
    spec = {"sshead": (1000, 1364), "pclm": (10000, 640), "sfflag": (20000, 640)}
    assert _byte_call(spec, 640, 682)[1] == ("pclm", 640)


def test_byte_arrays_refuse_geometry_that_disagrees_with_the_layout():
    spec = {"sshead": (1000, 1364), "pclm": (10000, 200), "sfflag": (20000, 200)}
    with pytest.raises(AssertionError, match="geometry says"):
        _byte_call(spec, 160, 682)            # emitter laid out 200, caller claims 160
    with pytest.raises(AssertionError, match="geometry says"):
        _byte_call(spec, 200, 683)            # one more subsector than the layout has


def test_restore_set_without_provenance_is_refused(tmp_path):
    """R9. 308 label names that all happen to exist in a DIFFERENT program resolve clean and
    restore the wrong cells. A set that cannot say what it came from is refused."""
    p = _set_file(tmp_path, [["a", 0]], provenance=False)
    with pytest.raises(AssertionError, match="source_sha256"):
        load_restore_set(p, {"a": 0, "b": 8 * W})


def test_offset_running_past_its_label_is_refused(tmp_path):
    """R9. Attribution is nearest-preceding-label with no containment of its own. If THIS build
    spaces the labels differently, an offset can point at an unrelated cell and still resolve."""
    p = _set_file(tmp_path, [["a", 0, 9]])
    load_restore_set(p, {"a": 0, "b": 20 * W})                        # 9 < 20: inside, fine
    with pytest.raises(AssertionError, match="past the end"):
        load_restore_set(p, {"a": 0, "b": 4 * W})                     # 9 >= 4: escaped


# ---------------------------------------------------------------------------------------------
# emit_reset_part -- the function that actually writes the program. CR round 2 was right that it
# had no test at all, while being the piece that derives code_start, splits the set into nibble vs
# byte, drops read-only extents, coalesces the zero runs, and performs the size-neutral surgery on
# the main part. It is pure and fully injectable, so a fake label table tests all of it in
# milliseconds -- no build.
# ---------------------------------------------------------------------------------------------

VAL_SHIFT = (W + W.bit_length()) - W
CODE_START = 100

# A miniature program: 3 subsectors, a 2-column viewport, one scratch region, one read-only LUT.
# sshead is declared 2*nss cells (the real over-allocation), so only its first 3 cells are
# reachable and its last 3 are padding.
FAKE = {"sshead": 200, "pclm": 212, "sfflag": 216, "scratch": 220, "lut": 230, "zzz_end": 240}
FAKE_BITS = {k: v * W for k, v in FAKE.items()}


def _pristine(values):
    """word -> content. Word 1 is op0's jump field and carries code_start; a cell's value lives in
    the odd (jump) word, shifted."""
    def get(word):
        if word == 1:
            return CODE_START * W
        return values.get(word, 0) << VAL_SHIFT
    return get


def _emit(tmp_path, entries, values, view_w=2, nss=3, main=None):
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "e1m1_02_main.fj").write_text(
        main if main is not None else "stl.output_char 0xFF\nstl.loop\nbad: stl.loop\n",
        encoding="utf-8")
    p = _set_file(tmp_path, entries)
    part, n_nib, n_byte = selfreset.emit_reset_part(
        gen, dict(FAKE_BITS), _pristine(values), p, view_w, nss, "e1m1")
    return part.read_text(encoding="utf-8"), n_nib, n_byte, gen


BYTE_ENTRIES = [["sshead", 0, 1, 2, 3, 4, 5], ["pclm", 0, 1, 2, 3], ["sfflag", 0, 1, 2, 3]]


def test_emit_splits_byte_arrays_from_nibble_cells(tmp_path):
    txt, n_nib, n_byte, _g = _emit(tmp_path, BYTE_ENTRIES + [["scratch", 0, 1, 2, 3]], {})
    assert n_byte == 3 + 2 + 2                      # nss + view_w + view_w reachable cells
    assert n_nib == 2                               # scratch is 2 cells
    assert "rep(3, i) m1.zerobyte %d + i*dw" % (200 * W) in txt
    assert txt.rstrip().endswith(";__hot_end")


def test_emit_coalesces_zero_runs_and_keeps_non_zero_singles(tmp_path):
    """A run of zero cells becomes ONE hex.zero; a cell with a real pristine value must be set back
    to that value, not zeroed -- restoring it to 0 would be a silent wrong-value bug."""
    ents = BYTE_ENTRIES + [["scratch", 0, 1, 2, 3, 4, 5]]
    txt, _n, _b, _g = _emit(tmp_path, ents, {221: 0, 223: 7, 225: 0})
    assert "hex.set 1, %d, 7" % ((220 // 2 + 1) * 2 * W) in txt
    zeros = [l for l in txt.splitlines() if "hex.zero" in l]
    assert len(zeros) == 2 and all(" 1, " in z for z in zeros), zeros


def test_emit_drops_a_read_only_extent(tmp_path):
    """A cell only nibble ops ever write cannot hold a pristine value above 15, so a label whose
    extent contains one is a packed LUT or code -- and the WHOLE extent goes, not just that cell."""
    ents = BYTE_ENTRIES + [["scratch", 0, 1], ["lut", 0, 1, 2, 3]]
    txt, n_nib, _b, _g = _emit(tmp_path, ents, {231: 0xFF, 233: 0})
    assert n_nib == 1                               # scratch's one cell survives, both lut cells go
    assert str(230 * 2 * W) not in txt


def test_emit_ignores_words_below_code_start(tmp_path):
    """code_start is DERIVED from word 1, and everything below it is the stl's own tables."""
    bits = dict(FAKE_BITS, low=50 * W)
    gen = tmp_path / "gen"; gen.mkdir()
    (gen / "e1m1_02_main.fj").write_text("stl.output_char 0xFF\nstl.loop\nbad: stl.loop\n",
                                         encoding="utf-8")
    p = _set_file(tmp_path, BYTE_ENTRIES + [["low", 0, 1], ["scratch", 0, 1]])
    _part, n_nib, _b = selfreset.emit_reset_part(gen, bits, _pristine({}), p, 2, 3, "e1m1")
    assert n_nib == 1                               # `low` is below code_start and never emitted


def test_emit_refuses_set_words_in_the_unreachable_tail_of_a_byte_array(tmp_path):
    """THE TWO-SIDED HALF OF THE GUARD. sshead is declared 2*nss but reaches nss, so offsets 6..11
    address padding. They are not byte cells, so they would fall through to the NIBBLE clear -- and
    a nibble op on a byte cell corrupts it rather than failing. Refuse instead."""
    ents = [["sshead", 0, 1, 2, 3, 4, 5, 6, 7], ["pclm", 0, 1, 2, 3], ["sfflag", 0, 1, 2, 3]]
    with pytest.raises(AssertionError, match="outside its reachable part"):
        _emit(tmp_path, ents, {})


def test_emit_patches_the_frame_tail_size_neutrally(tmp_path):
    """1 op -> 1 op. If the patch changed the line count, every baked address after it would move
    and the whole two-pass scheme would be void."""
    _txt, _n, _b, gen = _emit(tmp_path, BYTE_ENTRIES + [["scratch", 0, 1]], {})
    out = (gen / "e1m1_02_main.fj").read_text(encoding="utf-8").split("\n")
    assert out == ["stl.output_char 0xFF", ";m1_reset", "bad: stl.loop", ""]


@pytest.mark.parametrize("main,match", [
    ("stl.output_char 0xFF\nstl.loop\nstl.loop\nbad: stl.loop\n", "exactly 1 bare stl.loop"),
    ("stl.output_char 0xFF\nstl.loop\n", "junk-input halt"),
    ("nop\nstl.loop\nbad: stl.loop\n", "0xFF end-of-frame marker"),
])
def test_emit_refuses_a_main_part_it_does_not_recognise(tmp_path, main, match):
    """The patch is done by text surgery on generated code. If the frame tail is not exactly where
    it is expected, patching the wrong line would redirect the program silently."""
    with pytest.raises(AssertionError, match=match):
        _emit(tmp_path, BYTE_ENTRIES + [["scratch", 0, 1]], {}, main=main)


def test_no_byte_array_word_is_ever_nibble_cleared(tmp_path):
    """The property, not a restatement of the list. Every word of a byte array must leave through
    the `rep m1.zerobyte` path and none may appear as a `hex.zero`/`hex.set` address, because a
    nibble op on a byte cell CORRUPTS it (0xA5 -> 0x22A5) instead of failing.

    ** The MEMBERSHIP of BYTE_ARRAY_NAMES cannot be settled here. ** src/fj/ writes bytes through
    POINTER registers, so no static rule can name the arrays they reach; `scratchpad/m1_bytecheck.py`
    settles it empirically instead -- it runs real frames and checks that no cell the reset
    nibble-clears ever holds a value > 15, with the three known arrays as the vacuity control
    (measured: sshead 96, pclm 640, sfflag 503 cells > 15, and 0 elsewhere over 4 viewpoints).
    """
    txt, _n, n_byte, _g = _emit(tmp_path, BYTE_ENTRIES + [["scratch", 0, 1]], {})
    assert n_byte == 7
    addr_lines = [l for l in txt.splitlines() if "hex.zero" in l or "hex.set" in l]
    for name, cells in (("sshead", 3), ("pclm", 2), ("sfflag", 2)):
        for k in range(cells):
            a = (FAKE[name] // 2 + k) * 2 * W
            assert not any(str(a) in l for l in addr_lines),                 "%s cell %d reached a nibble op" % (name, k)
