"""Run `build_blocked.py` with the label spy on, so the binary can be mapped back to its source.

WHY THIS EXISTS. The access census (`mkprof.py` -> `hotruns.py`) says WHICH ADDRESSES are hot;
re-tiering the emitter's hot list needs to know WHICH EMITTED OBJECT each hot address is. Only the
assembler knows that, and only at the moment it resolves labels. `popcount_census._spy_on_labels`
wraps `labels_resolve` to dump `name<TAB>bit-address` for exactly the build that is running.

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
import runpy
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "scratchpad", ROOT / "src", ROOT / "tests", ROOT):
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

    Path(a.labels).parent.mkdir(parents=True, exist_ok=True)

    import popcount_census as pc
    from flipjump.assembler import assembler as asm

    unhook = pc._spy_on_labels(asm, a.labels)
    print("label spy armed -> %s" % a.labels, flush=True)
    print("build: build_blocked.py %s" % " ".join(rest), flush=True)

    saved_argv = sys.argv
    sys.argv = ["build_blocked.py"] + rest
    t0 = time.time()
    try:
        runpy.run_path(str(ROOT / "scratchpad" / "12m" / "build_blocked.py"),
                       run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise SystemExit("build_blocked exited %r -- the label table may be partial" % (e.code,))
    finally:
        sys.argv = saved_argv
        unhook()
    print("done in %.0fs; labels at %s" % (time.time() - t0, a.labels), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
