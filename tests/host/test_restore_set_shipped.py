"""The SHIPPED restore sets -- invariants that hold without a build.

tests/host/test_selfreset.py covers the RESOLUTION LOGIC thoroughly but never opens the packaged
`src/doomfj/data/*.json.gz`. These tests open them, and they exist because a session was lost to the
class of defect they catch: a set is a PROVEN artifact whose keys go stale, and every attempt to
re-derive its membership from a measurement produced HOLES. A hole does not draw a wrong pixel --
it hangs the next frame -- so nothing cheap catches it downstream.

TWO sets ship now, and every structural invariant below is checked against BOTH:
  * `m1_restore_set.json.gz`  -- the hosted tier, the one M1 certified.
  * `m5_restore_set.json.gz`  -- the STANDALONE tier, re-keyed from it by scratchpad/m5_setfile.py.
The standalone one is a different program's set (no wire, so no `wmagic`; a keyboard, so six new
`kb*` globals), and the tests at the bottom pin exactly those differences -- so a re-key that
quietly dropped something else, or forgot to add a global, fails here in milliseconds instead of
during a 50-minute build.

None of these needs a label table, so they run in milliseconds.
"""
import gzip
import json
import re
from pathlib import Path

import pytest

from doomfj.build import DOOR_PERSIST, STANDALONE_PERSIST
from doomfj.collision import CHECK_SCRATCH_DECLS
from doomfj.selfreset import decl_words
from doomfj.wad import WadFile
from doomfj.wall_renderer import HOISTED_SCRATCH_DECLS, STANDALONE_SCRATCH_DECLS

DATA = Path(__file__).resolve().parents[2] / "src/doomfj/data"
SETS = {"hosted": DATA / "m1_restore_set.json.gz", "standalone": DATA / "m5_restore_set.json.gz"}
CELL_WORDS = 2                      # a hex cell is dw = 2w bits = 2 words


def _load(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module", params=sorted(SETS))
def tier(request):
    return request.param


@pytest.fixture(scope="module")
def doc(tier):
    return _load(SETS[tier])


def _declared(tier="hosted"):
    """Every global the restore set must carry, from ALL its sources.

    CHECK_SCRATCH_DECLS replaced the sim @-locals bdf1f1a hoisted; HOISTED_SCRATCH_DECLS replaced
    the 319 renderer @-locals the M1-HOIST rounds moved; STANDALONE_SCRATCH_DECLS is M5's keyboard
    state, which only the standalone program declares. Same hazard for all three: a re-key DROPS a
    key whose register no longer exists, and a dropped cell is a HOLE -- which hangs the next frame
    rather than drawing anything wrong.

    ⚠ Sizes may be SYMBOLIC (`hex.vec w/4`). An earlier version of this helper asserted on them,
    which is why it could only ever cover CHECK_SCRATCH_DECLS -- the 319 globals most at risk were
    silently out of scope. selfreset.decl_words is the one parser (R6).
    """
    decls = list(CHECK_SCRATCH_DECLS) + list(HOISTED_SCRATCH_DECLS)
    if tier == "standalone":
        decls += list(STANDALONE_SCRATCH_DECLS)
    out = {}
    for d in decls:
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


def test_every_hoisted_global_is_present_at_full_declared_extent(doc, tier):
    """bdf1f1a, the M1-HOIST rounds and M5 moved scratch to these globals; a re-key DROPS the
    registers they replaced.

    If one is missing, or present at less than its declared width, the set has a hole exactly where
    the program writes -- and the next frame hangs rather than drawing anything wrong.
    """
    have = {e[0]: list(e[1:]) for e in doc["entries"]}
    declared = _declared(tier)
    missing = [n for n in declared if n not in have]
    assert not missing, "%s restore set is missing globals: %s" % (tier, missing[:8])
    for name, words in declared.items():
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


def test_no_key_is_a_macro_expansion_path_at_all(doc):
    """The M1-HOIST goal, stated as an invariant: every key is a NAMED GLOBAL.

    A macro-expansion key (`f<file>:l<line>:macro(n)---local`) is re-keyed by every comment edit
    anywhere earlier in the file list. Zero of them is what makes a set survive a source change --
    and what let M5's set be derived from M1's by two named edits instead of a re-measurement.
    """
    paths = [e[0] for e in doc["entries"] if ":" in e[0]]
    assert not paths, "%d keys are macro-expansion paths, e.g. %s" % (len(paths), paths[:2])


def test_provenance_names_commands_that_exist(doc):
    """R9: an artifact that cannot be regenerated from the tracked tree has no provenance.

    CR round 2 fixed exactly this once (m1_setfile.py's docstring records it) and CR 2026-08-25
    found it again in a new form -- `generated_by` named only the re-key, which does not add the
    globals. Every script the field names must be a real tracked file.
    """
    root = DATA.resolve().parents[2]
    named = re.findall(r"scratchpad/[\w./-]+\.py", doc["generated_by"])
    assert named, "generated_by names no script: %r" % doc["generated_by"]
    for rel in named:
        assert (root / rel).exists(), "generated_by names %r, which is not in the tree" % rel


# -- M5: the two sets differ in exactly the two ways the standalone PROGRAM differs ---------------

def test_the_standalone_set_drops_only_the_wire_magic():
    """The hosted program checks a MAGIC byte on the wire; the standalone one has no wire. That is
    the ONLY label allowed to disappear -- anything else vanishing is a hole, and a hole hangs."""
    hosted = {e[0] for e in _load(SETS["hosted"])["entries"]}
    standalone = {e[0] for e in _load(SETS["standalone"])["entries"]}
    assert hosted - standalone == {"wmagic"}, (
        "the standalone set drops %s; only 'wmagic' may go" % sorted(hosted - standalone))
    # M2-R4: ...and the per-door state, because the shipped standalone tier has RUNTIME DOORS. The
    # names come from `door_decls` at the map's own door count rather than being written out here,
    # so a map with a different number of doors does not need this test edited -- and `duse`/`dbox`
    # are deliberately absent: they are rewritten every frame, so they are ordinary residue the
    # reset restores like anything else.
    from doomfj.doorcode import door_decls
    from doomfj.doors import door_states
    _w = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
    _nd = len(door_states(_w.sectors("E1M1"), _w.linedefs("E1M1"), _w.sidedefs("E1M1")))
    expected = {name for name, _ in
                (decl_words(d) for d in list(STANDALONE_SCRATCH_DECLS) + door_decls(_nd))}
    assert standalone - hosted == expected, (
        "the standalone set adds %s, which is not STANDALONE_SCRATCH_DECLS + the door state"
        % sorted(standalone - hosted))


def test_the_persist_labels_are_all_in_the_standalone_set():
    """`selfreset.emit_reset_part` refuses a persist label the set does not carry -- excluding a
    label that is not there protects nothing. That refusal costs an hour; this costs a millisecond.
    """
    standalone = {e[0] for e in _load(SETS["standalone"])["entries"]}
    absent = [n for n in STANDALONE_PERSIST if n not in standalone]
    assert not absent, "STANDALONE_PERSIST names %s, absent from the standalone set" % absent


def test_the_door_cells_are_in_the_standalone_set_too():
    """M2-R4, and the owner's standing rule as a test: a feature is not complete until the M1 reset
    loop carries its labels. `DOOR_PERSIST` is what keeps a door open across the reset -- without
    these four in the set, `emit_reset_part` cannot exclude them, the reset restores their pristine
    zeros, and every door in the level re-shuts on every single frame. The program would still
    render, still pass a one-frame check, and be unplayable.

    This is separate from the test above because the two tuples arrive by different routes:
    STANDALONE_PERSIST has been in the set since M5, DOOR_PERSIST since M2-R4 re-keyed it."""
    standalone = {e[0] for e in _load(SETS["standalone"])["entries"]}
    absent = [n for n in DOOR_PERSIST if n not in standalone]
    assert not absent, "DOOR_PERSIST names %s, absent from the standalone set" % absent


def test_the_two_sets_are_otherwise_identical():
    """Every shared label must carry the SAME offsets in both. The standalone program is the hosted
    one with a different frame prologue, so any other difference means the re-key did something it
    was not asked to -- which is how a hole gets in without anyone naming it."""
    hosted = {e[0]: tuple(e[1:]) for e in _load(SETS["hosted"])["entries"]}
    standalone = {e[0]: tuple(e[1:]) for e in _load(SETS["standalone"])["entries"]}
    differ = sorted(k for k in set(hosted) & set(standalone) if hosted[k] != standalone[k])
    assert not differ, "%d shared labels carry different offsets, e.g. %s" % (len(differ), differ[:4])


def test_the_two_sets_have_different_fingerprints():
    """R9 vacuity control for the test above: they are two DIFFERENT programs' sets. If the layout
    fingerprints ever matched, m5_setfile.py had not actually re-keyed anything and the whole
    comparison above would be comparing a file with itself."""
    assert (_load(SETS["hosted"])["layout_fingerprint"]
            != _load(SETS["standalone"])["layout_fingerprint"])
