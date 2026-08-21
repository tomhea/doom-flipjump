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


def test_byte_arrays_covers_only_the_write_byte_arrays():
    """drawn/sprflag are write_byte arrays too but only ever hold values <= 2, so the 19.5-op
    nibble clear is correct for them and the 91-op byte clear would be waste."""
    assert BYTE_ARRAY_NAMES == ("sshead", "pclm", "sfflag")
    assert "drawn" not in BYTE_ARRAY_NAMES and "sprflag" not in BYTE_ARRAY_NAMES
