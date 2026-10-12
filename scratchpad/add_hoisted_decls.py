"""Add the emitter's scratch globals a restore set lacks, at their DECLARED extent -- no label table needed.

WHY. A rung that adds scratch registers (wall_renderer.hoisted_scratch_decls, collision.CHECK_SCRATCH_DECLS and,
standalone, STANDALONE_SCRATCH_DECLS) must add them to both shipped sets, or a two-pass tier's reset has a HOLE
where the program writes (tests/host/test_restore_set_shipped.py, test_every_hoisted_global_is_present_at_full_
declared_extent). m1_add_globals.py does it from a build's label table (extents from label addresses, cross-checked
against the declarations) -- which needs a pass-1 capture of the tier, ~75 heavy minutes. A scratch register is ONE
contiguous `hex.vec N` declaration, so its extent IS the declaration's: offsets 0 .. words - 1 (selfreset.decl_words,
the one parser) -- exactly what the test checks and what the reset resolves through a label table at build time.
P11 added twelve (the ledge test's and the shared third-slot painter's).

    python scratchpad/add_hoisted_decls.py --set src/doomfj/data/m1_restore_set.json.gz
    python scratchpad/add_hoisted_decls.py --set src/doomfj/data/m5_restore_set.json.gz --standalone
    python scratchpad/add_hoisted_decls.py --selftest

Only ADDS: a name already in the set keeps its entry (a stale extent there is the test's to catch, not this tool's).
`words` stays the deduped union; `generated_by` records this step.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.collision import CHECK_SCRATCH_DECLS                              # noqa: E402
from doomfj.selfreset import decl_words                                        # noqa: E402
from doomfj.wall_renderer import STANDALONE_SCRATCH_DECLS, hoisted_scratch_decls   # noqa: E402

STEP = "scratchpad/add_hoisted_decls.py"


def declared(standalone: bool) -> dict:
    decls = list(CHECK_SCRATCH_DECLS) + list(hoisted_scratch_decls())
    if standalone:
        decls += list(STANDALONE_SCRATCH_DECLS)
    out = {}
    for d in decls:
        name, words = decl_words(d)
        assert words is not None, "declared size is not evaluable: %r" % d
        out[name] = words
    return out


def add(doc: dict, standalone: bool) -> list:
    """the names added to `doc` (in place)"""
    have = {e[0] for e in doc["entries"]}
    added = []
    for name, words in declared(standalone).items():
        if name not in have:
            doc["entries"].append([name, *range(words)])
            added.append(name)
    doc["words"] = len({(e[0], off) for e in doc["entries"] for off in e[1:]})
    if added and STEP not in doc["generated_by"]:
        doc["generated_by"] += " + python %s (the declared scratch globals a set lacks)" % STEP
    return added


def selftest() -> int:
    doc = {"entries": [["a", 0, 1]], "words": 2, "generated_by": "x"}
    names = add(doc, standalone=False)
    want = declared(False)
    assert set(names) == set(want) - {"a"}, "every declared name added"
    assert all(e[1:] == list(range(want[e[0]])) for e in doc["entries"] if e[0] in want and e[0] != "a")
    assert doc["words"] == 2 + sum(want[n] for n in names) and STEP in doc["generated_by"]
    again = add(doc, standalone=False)                          # idempotent
    assert again == [] and doc["generated_by"].count(STEP) == 1
    # R9: a set missing ONE declared name gets exactly that name back, at its declared extent
    victim = next(n for n in want if want[n] > 1)
    doc["entries"] = [e for e in doc["entries"] if e[0] != victim]
    assert add(doc, standalone=False) == [victim]
    print("selftest OK: %d declared globals; a dropped one (%s, %d words) is restored" % (len(want), victim,
                                                                                         want[victim]))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set")
    ap.add_argument("--standalone", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    p = ROOT / a.set
    doc = json.load(gzip.open(p, "rt", encoding="utf-8"))
    added = add(doc, a.standalone)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(doc, f)
    print("%s: added %d globals%s" % (a.set, len(added), (": " + ", ".join(added)) if added else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
