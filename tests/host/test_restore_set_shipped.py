"""The SHIPPED M1 restore set -- invariants that hold without a build.

tests/host/test_selfreset.py covers the RESOLUTION LOGIC thoroughly but never opens the packaged
`src/doomfj/data/m1_restore_set.json.gz`. These tests open it, and they exist because a session was
lost to the class of defect they catch: the set is a PROVEN artifact whose keys go stale, and every
attempt to re-derive its membership from a measurement produced HOLES. A hole does not draw a wrong
pixel -- it hangs the next frame -- so nothing cheap catches it downstream.

None of these needs a label table, so they run in milliseconds.
"""
import gzip
import json
import re
from pathlib import Path

import pytest

from doomfj.collision import CHECK_SCRATCH_DECLS
from doomfj.selfreset import decl_words
from doomfj.wall_renderer import HOISTED_SCRATCH_DECLS

SET = Path(__file__).resolve().parents[2] / "src/doomfj/data/m1_restore_set.json.gz"
CELL_WORDS = 2                      # a hex cell is dw = 2w bits = 2 words


@pytest.fixture(scope="module")
def doc():
    with gzip.open(SET, "rt", encoding="utf-8") as f:
        return json.load(f)


def _declared():
    """Every global the restore set must carry, from BOTH sources.

    CHECK_SCRATCH_DECLS replaced the sim @-locals bdf1f1a hoisted; HOISTED_SCRATCH_DECLS replaced
    the 319 renderer @-locals the M1-HOIST rounds moved. Same hazard for both: the re-key DROPS
    the old macro-local keys because those registers no longer exist, and a dropped cell is a
    HOLE -- which hangs the next frame rather than drawing anything wrong.

    ⚠ Sizes may be SYMBOLIC (`hex.vec w/4`). An earlier version of this helper asserted on them,
    which is why it could only ever cover CHECK_SCRATCH_DECLS -- the 319 globals most at risk were
    silently out of scope. selfreset.decl_words is the one parser (R6).
    """
    out = {}
    for d in list(CHECK_SCRATCH_DECLS) + list(HOISTED_SCRATCH_DECLS):
        name, words = decl_words(d)
        assert words is not None, "declared size is not evaluable: %r" % d
        out[name] = words
    return out


def test_words_is_the_deduped_union_not_the_sum(doc):
    """`words` MUST be the resolved union.

    ca_remap_set.py emits OVERLAPPING entries by design -- it takes the superset where the old->new
    label mapping is ambiguous -- so summing offset-list lengths over-counts. selfreset.load_restore_set
    asserts `len(out) == doc["words"]`, so a summed count fails the BUILD, ~50 minutes in.
    """
    pairs = {(e[0], off) for e in doc["entries"] for off in e[1:]}
    assert doc["words"] == len(pairs), (
        "words=%d but there are %d distinct (label, offset) pairs -- words was probably summed "
        "over entries instead of deduped" % (doc["words"], len(pairs)))


def test_duplicate_entries_carry_identical_offsets(doc):
    """Overlapping entries are fine ONLY while every duplicate of a key agrees.

    ca_remap_set's soundness argument is that any bijection within a normalised-shape group restores
    the same words, which holds only because the offset lists are identical. If two entries for one
    label ever disagreed, the superset would silently depend on which one resolved last.
    """
    seen = {}
    for e in doc["entries"]:
        offs = tuple(e[1:])
        if e[0] in seen:
            assert seen[e[0]] == offs, "label %r has two DIFFERENT offset lists" % e[0]
        seen[e[0]] = offs


def test_every_hoisted_sim_global_is_present_at_full_declared_extent(doc):
    """bdf1f1a and the M1-HOIST rounds moved scratch to these globals; the re-key DROPS the
    registers they replaced.

    If one is missing, or present at less than its declared width, the set has a hole exactly where
    check_block/check_line write -- and the next frame hangs rather than drawing anything wrong.
    """
    have = {e[0]: list(e[1:]) for e in doc["entries"]}
    missing = [n for n in _declared() if n not in have]
    assert not missing, "restore set is missing hoisted globals: %s" % missing[:8]
    for name, words in _declared().items():
        assert have[name] == list(range(words)), (
            "%s must cover its whole declared extent 0..%d, got %d offsets (first/last %s/%s)"
            % (name, words - 1, len(have[name]),
               have[name][0] if have[name] else None, have[name][-1] if have[name] else None))


def test_no_key_still_names_the_hoisted_macro_locals(doc):
    """After the hoist, nothing may remain keyed on a check_block / check_line expansion path.

    Such a key cannot resolve against a current label table, which is what refused the build and
    started this whole repair.
    """
    stale = [e[0] for e in doc["entries"]
             if "sim.check_block" in e[0] or "sim.check_line" in e[0]]
    assert not stale, "%d keys still name hoisted macro-locals, e.g. %s" % (len(stale), stale[:2])


def test_provenance_names_commands_that_exist(doc):
    """R9: an artifact that cannot be regenerated from the tracked tree has no provenance.

    CR round 2 fixed exactly this once (m1_setfile.py's docstring records it) and CR 2026-08-25
    found it again in a new form -- `generated_by` named only the re-key, which does not add the
    globals. Every script the field names must be a real tracked file.
    """
    root = SET.resolve().parents[3]
    named = re.findall(r"scratchpad/[\w./-]+\.py", doc["generated_by"])
    assert named, "generated_by names no script: %r" % doc["generated_by"]
    for rel in named:
        assert (root / rel).exists(), "generated_by names %r, which is not in the tree" % rel
