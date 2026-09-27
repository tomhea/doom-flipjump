"""M7 P1.3 -- are PR #92's review edits to src/ NEUTRAL for the binary? (the R6 constants, the one
persist composition, the hoisted extents)

blocked30 was built at 87c2c75; PR #92's review then changed src/ (things.LIST_MAX_THINGS read by
three layers, build.persist_labels, wall_renderer's _ss_cells/_th_cells). This extracts each tree
(`git archive`) and, in each tree's own process with its own doomfj, runs `build.build_wall_renderer`
-- the build's OWN path for the game tier, the shipped program, on E1M1 -- up to its first assembly,
where `selfreset.capture_labels` is replaced by a stop that records what the build hands it: every
file the assembler would read (the generated parts, fj_consts and the fj sources, hashed) and the
`_persist` tuple the build computed (read off build_wall_renderer's own frame, so the base's inline
composition and the head's `persist_labels` are each what they are). Equal inputs and an equal
tuple are the same assembly -- the counting pass and the binary are blocked30's.

CONTROL (R9): a copy of the head with BOTH edits undone the wrong way -- the build's persist call
given moving_things=False, and `_ss_cells` one cell wider -- must differ in the persist line AND in
an assembler input. A comparison that cannot tell those apart is not evidence.

    python scratchpad/gp/p13_emit_neutral.py [--base 87c2c75] [--head HEAD]
"""
import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def probe(wad, mapname):
    """run INSIDE an extracted tree (cwd = the tree, PYTHONPATH = its src): one line per value"""
    from doomfj import build, selfreset

    class Stop(Exception):
        pass
    seen = {}

    def stop_at_first_assembly(paths, out, lzma_fast=True):
        seen["persist"] = sys._getframe(1).f_locals["_persist"]
        seen["paths"] = [Path(p) for p in paths]
        raise Stop

    selfreset.capture_labels = stop_at_first_assembly
    with tempfile.TemporaryDirectory() as t:
        try:
            build.build_wall_renderer(Path(t) / "probe.fjm", wad_path=wad, mapname=mapname,
                                      tier="game")
        except Stop:
            pass
        assert seen, "the build never reached its first assembly"
        for p in seen["paths"]:
            print("input %-28s %s" % (p.name, hashlib.sha256(p.read_bytes()).hexdigest()[:16]))
    print("persist %s" % ",".join(seen["persist"]))


def extract(ref, dest):
    data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=ROOT, check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(dest)
    shutil.copytree(ROOT / "assets", Path(dest) / "assets")
    return Path(dest)


def run(tree, wad, mapname):
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe", wad, mapname],
                       cwd=tree, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    return [ln for ln in r.stdout.strip().splitlines() if ln.startswith(("input", "persist"))]


def mutate(tree, path, old, new):
    f = tree / path
    s = f.read_text(encoding="utf-8")
    assert s.count(old) == 1, "the control's mutation site moved: %r" % old
    f.write_text(s.replace(old, new), encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="87c2c75", help="the commit blocked30 was built at")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--probe", nargs=2, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.probe:
        probe(*args.probe)
        return 0
    E1M1 = ("tests/fixtures/freedoom_e1m1.wad", "E1M1")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base = run(extract(args.base, tmp / "base"), *E1M1)
        head = run(extract(args.head, tmp / "head"), *E1M1)
        neg = extract(args.head, tmp / "neg")
        mutate(neg, "src/doomfj/build.py",
               "_persist = persist_labels(standalone=standalone, doors=doors, moving_things=moving_things)",
               "_persist = persist_labels(standalone=standalone, doors=doors, moving_things=False)")
        mutate(neg, "src/doomfj/wall_renderer.py",
               "_ss_cells, _th_cells = 2 * _MT_NSS, 2 * _MT_NT",
               "_ss_cells, _th_cells = 2 * _MT_NSS + 1, 2 * _MT_NT")
        neg_out = run(neg, *E1M1)
    print("base %s (E1M1, the game tier, build_wall_renderer's own path to its first assembly):"
          % args.base)
    for ln in base:
        print("   " + ln)
    same = head == base
    print("head %s: %s" % (args.head, "EVERY ASSEMBLER INPUT EQUAL, the same persist tuple" if same
                            else "!! DIFFERS"))
    for a, b in zip(base, head):
        if a != b:
            print("   base  " + a + "\n   head  " + b)
    pers = [a != b for a, b in zip(head, neg_out) if a.startswith("persist")]
    inputs = [a.split()[1] for a, b in zip(head, neg_out) if a.startswith("input") and a != b]
    print("CONTROL the build's persist call with moving_things=False: %s"
          % ("caught -- the persist line differs" if any(pers) else "!! NOT CAUGHT"))
    print("CONTROL sshead declared one cell wider: %s"
          % ("caught -- %s differ" % ", ".join(inputs) if inputs else "!! NOT CAUGHT"))
    ok = same and any(pers) and bool(inputs) and len(head) == len(neg_out)
    print("EMISSION-NEUTRAL: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
