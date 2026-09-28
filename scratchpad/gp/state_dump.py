"""M7 P2a.1 -- the grown-schema rehash's witness (scratchpad/gp/scenarios_v2.py `--rehash-grown`).

Every run of a frozen set, stepped on a fresh model from the code tree at `--root`, with the whole
WorldState written after EVERY frame (gz JSON lines). The same file drives both sides: the current
tree, and the tree the set was frozen at, `git archive`d into a temp dir -- so the two dumps differ
only by the code under `--root`.

    python scratchpad/gp/state_dump.py --root DIR --set scratchpad/gp/scenarios/combat_scenarios_v3.json --out F.jsonl.gz

The header line carries the tree's door order, sound node per sector and schema (field, count,
group) -- what a door-indexed or sound-node-indexed field is re-keyed by; each run ends with its
final digest (`World.digest`), which is what the freeze recorded -- the old side's control.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="the code tree (its src/ and scratchpad/gp/)")
    ap.add_argument("--set", required=True, help="the frozen scenario set (json)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    for q in (root / "scratchpad" / "gp", root / "src"):
        sys.path.insert(0, str(q))
    import scenarios_v2 as SV                                   # the tree's own
    import doomfj
    for mod in (SV, doomfj):                                    # never a module from elsewhere
        assert Path(mod.__file__).resolve().is_relative_to(root), (mod.__file__, root)
    doc = json.loads(Path(a.set).read_text(encoding="ascii"))
    w0 = SV.new_world()
    with gzip.open(a.out, "wt", encoding="ascii") as fh:
        fh.write(json.dumps({"root": str(root), "door_order": list(w0.door_order),
                             "sector_node": list(w0.sector_node),
                             "schema": [[x.name, x.count, x.group] for x in w0.ws.schema]}) + "\n")
        for run in doc["runs"]:
            w = SV.start_world(run["setup"])
            for f, s in enumerate(run["keys"]):
                w.tic(SV.str_to_keys(s))
                fh.write(json.dumps({"run": run["name"], "f": f, "s": w.ws.as_dict()},
                                    separators=(",", ":")) + "\n")
            fh.write(json.dumps({"run": run["name"], "final_digest": w.digest()}) + "\n")
    print("state_dump: %d runs from %s -> %s" % (len(doc["runs"]), root, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
