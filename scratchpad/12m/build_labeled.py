"""Run `build_blocked.py` with the label spy on, so the binary can be mapped back to its source.

WHY THIS EXISTS. The access census (`mkprof.py` -> `hotruns.py`) says WHICH ADDRESSES are hot;
re-tiering the emitter's hot list needs to know WHICH EMITTED OBJECT each hot address is. Only the
assembler knows that. flipjump's `assemble` RETURNS the labels (1.6.0; this used to wrap the assembler's
`labels_resolve`), the build hands them back, and build_blocked.py writes `name<TAB>bit-address` for exactly the
build that is running.

⚠ AND THE PAIR MUST COME FROM ONE BUILD. A label table from a DIFFERENT build is worse than no
label table: addresses shift with any change of pool geometry, tier, or emitted file list, so the
names would be confidently wrong. build/doom_e1m1_blocked25.fjm has no recorded build command
(checked: not in git log, the handoffs, or the ledger), which is exactly why this does not try to
reproduce it -- it builds a FRESH baseline whose command is recorded here, and the profile is then
taken from that same binary.

    python scratchpad/12m/build_labeled.py --out build/doom_e1m1_b26.fjm \\
        --labels scratchpad/12m/atlas/b26.labels.tsv.gz -- game --counts-cache ...

Everything after `--` is passed through to build_blocked.py verbatim.

HEAVY: a full game-tier assembly. CLAUDE.md rule 1 -- one at a time, nothing else running.
"""
import argparse
import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True, help="where to write the gzipped label table")
    ap.add_argument("rest", nargs=argparse.REMAINDER,
                    help="everything after -- goes to build_blocked.py")
    a = ap.parse_args()

    rest = a.rest
    if rest and rest[0] == "--":
        rest = rest[1:]
    if not rest:
        raise SystemExit("nothing to build: pass the build_blocked.py argv after --")

    spec = importlib.util.spec_from_file_location("build_blocked", ROOT / "scratchpad" / "12m" / "build_blocked.py")
    build_blocked = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_blocked)
    print("labels -> %s" % a.labels, flush=True)
    print("build: build_blocked.py %s" % " ".join(rest), flush=True)
    t0 = time.time()
    try:
        rc = build_blocked.main(rest, labels_out=a.labels)
    except SystemExit as e:
        rc = e.code
    if rc not in (0, None):
        raise SystemExit("build_blocked exited %r -- the label table may be missing" % (rc,))
    print("done in %.0fs; labels at %s" % (time.time() - t0, a.labels), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
