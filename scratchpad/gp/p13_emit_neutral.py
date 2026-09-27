"""M7 P1.3 -- are PR #92's round-1 source edits EMISSION-NEUTRAL? (the R6 constants, the one persist
composition, the hoisted extents)

blocked30 was built at 87c2c75; PR #92's review round 1 then changed src/ (things.LIST_MAX_THINGS read
by three layers, build.persist_labels, wall_renderer's _ss_cells/_th_cells). This extracts each tree
(`git archive`), EMITS the game tier -- the shipped program -- on E1M1 with each tree's own doomfj in
its own process, and compares every part's SHA-256 and the build's persist tuple. Equal parts are the
same program, so the binary is blocked30's bytes (the counting pass is a function of the program).

CONTROL (R9): the same comparison on the one-room fixture must CATCH a copy of the head whose
`_ss_cells` is one cell wider -- emitted in seconds, through the same code path. A comparison that
cannot tell those apart is not evidence.

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


def probe(wad, mapname, asset):
    """run INSIDE an extracted tree (cwd = the tree, PYTHONPATH = its src): one line per value"""
    from doomfj import wall_renderer as wr
    from doomfj.build import DOOR_PERSIST, STANDALONE_PERSIST
    from doomfj.config import Config
    from doomfj.wad import WadFile
    parts = wr.emit_wall_renderer(WadFile.from_path(wad), mapname, Config(), tier="game",
                                  asset_wad=WadFile.from_path(asset),
                                  sprite_wad=WadFile.from_path("assets/freedoom1.wad"),
                                  return_parts=True)
    for name, text in parts:
        print("part %-14s %s (%d chars)" % (name, hashlib.sha256(text.encode()).hexdigest()[:16],
                                             len(text)))
    try:
        from doomfj.build import persist_labels
        t = wr.TIERS["game"]
        persist = persist_labels(standalone=t["standalone"], doors=t["doors"],
                                 moving_things=t["moving_things"])
    except ImportError:                       # the base composes it inline (build.py's _persist)
        from doomfj.build import THING_PERSIST
        persist = STANDALONE_PERSIST + DOOR_PERSIST + THING_PERSIST
    print("persist %s" % ",".join(persist))


def extract(ref, dest):
    data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=ROOT, check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(dest)
    shutil.copytree(ROOT / "assets", Path(dest) / "assets")
    return Path(dest)


def run(tree, wad, mapname, asset):
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe", wad, mapname,
                        asset], cwd=tree, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    return [ln for ln in r.stdout.strip().splitlines() if ln.startswith(("part", "persist"))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="87c2c75", help="the commit blocked30 was built at")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--probe", nargs=3, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.probe:
        probe(*args.probe)
        return 0
    E1M1 = ("tests/fixtures/freedoom_e1m1.wad", "E1M1", "tests/fixtures/freedoom_e1m1.wad")
    ROOM = ("tests/fixtures/square_room.wad", "MAP01", "tests/fixtures/freedoom_assets.wad")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bt, ht = extract(args.base, tmp / "base"), extract(args.head, tmp / "head")
        base, head = run(bt, *E1M1), run(ht, *E1M1)
        rb, rh = run(bt, *ROOM), run(ht, *ROOM)
        neg = extract(args.head, tmp / "neg")
        f = neg / "src/doomfj/wall_renderer.py"
        s = f.read_text(encoding="utf-8")
        old = "_ss_cells, _th_cells = 2 * _MT_NSS, 2 * _MT_NT"
        assert s.count(old) == 1, "the control's mutation site moved"
        f.write_text(s.replace(old, "_ss_cells, _th_cells = 2 * _MT_NSS + 1, 2 * _MT_NT"),
                     encoding="utf-8", newline="\n")
        rn = run(neg, *ROOM)
    print("base %s (E1M1, the game tier):" % args.base)
    for ln in base:
        print("   " + ln)
    same = head == base
    print("head %s: %s" % (args.head, "EVERY PART EQUAL, the same persist tuple" if same
                            else "!! DIFFERS"))
    for a, b in zip(base, head):
        if a != b:
            print("   base  " + a + "\n   head  " + b)
    room_same = rh == rb
    caught = rn != rh
    print("the one-room map, base vs head: %s" % ("equal" if room_same else "!! DIFFERS"))
    print("CONTROL sshead declared one cell wider (the one-room map): %s"
          % ("caught -- %d line(s) differ" % sum(a != b for a, b in zip(rh, rn)) if caught
             else "!! NOT CAUGHT"))
    ok = same and room_same and caught
    print("EMISSION-NEUTRAL: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
