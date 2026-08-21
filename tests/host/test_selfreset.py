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
from doomfj.selfreset import (BYTE_ARRAYS, load_restore_set, verify_labels_unchanged)


def _set_file(tmp_path, entries, words=None, fmt="label+offset"):
    p = tmp_path / "set.json.gz"
    n = words if words is not None else sum(len(e) - 1 for e in entries)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump({"format": fmt, "words": n, "labels": len(entries), "entries": entries}, f)
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


def test_byte_arrays_are_the_write_byte_arrays_only():
    """drawn/sprflag are write_byte-written but hold only small values (mark_drawn writes 1,
    sprflag writes 1 or 2), so they belong on the 19.5-op nibble path, not the 91-op byte path.
    pclm (a plane-pair id) and sfflag genuinely exceed a nibble and must stay."""
    names = {n for n, _c in BYTE_ARRAYS}
    assert names == {"sshead", "pclm", "sfflag"}
    assert "drawn" not in names and "sprflag" not in names
    assert dict(BYTE_ARRAYS)["sshead"] == 682          # nss: the REACHABLE cells, not 2*nss
