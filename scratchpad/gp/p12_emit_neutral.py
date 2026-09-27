"""M7 P1.2 -- is the ARG_CELLS refactor EMISSION-NEUTRAL? (PR #91 review, round 2)

blocked29 was rebuilt at 61672ad -- 34960cb since CR #91 round 2 reworded two commit messages
(the same tree); the only src/ change between that build and the PR's head is
collision.py's one-table refactor of the argument cells (CR #91 round 1). This extracts both trees
(`git archive`), imports EACH tree's own doomfj.collision in its own process, and compares what the
build consumes: the emitted collision routine on both E1M1 wads (the door-aware form the emitter
emits), every line's `line_constants`, `_xor_lines` over a 6,072-constant sweep (every argument cell,
random values and the edge cases), `CELL_DECLS` and `COLLISION_STATE_DECLS`. Every value must match.

CONTROLS (R9): two copies of the head, each mutated, must DIFFER from the build commit -- ca_slope
declared two nibbles wide (the declarations move) and ca_dx's top nibble dropped from the xor (the
text moves). A comparison that cannot tell those apart is not evidence.

    python scratchpad/gp/p12_emit_neutral.py [--base 34960cb] [--head HEAD]
"""
import argparse
import hashlib
import io
import os
import random
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def probe():
    """run INSIDE an extracted tree (cwd = the tree, PYTHONPATH = its src): one line per value"""
    from doomfj.collision import (CELL_DECLS, COLLISION_STATE_DECLS, _xor_lines, cell_lists,
                                  collision_cells_fj, line_constants, line_rows)
    from doomfj.doorcode import door_line_ids
    from doomfj.doors import door_states, pass_state
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import ML_BLOCKING, PLAYER_RADIUS, apply_sector_heights
    from doomfj.wad import WadFile

    def h(s):
        return hashlib.sha256(s.encode()).hexdigest()[:16]
    for wadp in ("tests/fixtures/freedoom_e1m1.wad", "tests/fixtures/e1m1_lite.wad"):
        wad = WadFile.from_path(Path(wadp))
        cmap = bake_bsp(wad, "E1M1")
        lds, sds, secs = wad.linedefs("E1M1"), wad.sidedefs("E1M1"), wad.sectors("E1M1")
        tbl = door_states(secs, lds, sds)
        order = sorted(tbl)
        lines_of = door_line_ids(secs, lds, sds, tbl)
        passes = [pass_state(secs, lds, sds, si) for si in order]
        open_h = {si: (secs[si].floor_h, tbl[si][-1]) for si in order}
        rows = line_rows(lds, cmap.vertexes, secs, sds, ML_BLOCKING,
                         secs_open=apply_sector_heights(secs, open_h),
                         door_line_ids={li for v in lines_of.values() for li in v})
        doors = {}
        for d, si in enumerate(order):
            for li in lines_of.get(si, ()):
                doors.setdefault(li, []).append((d, passes[d]))
        text, root = collision_cells_fj("e1m1", rows, cell_lists(rows, PLAYER_RADIUS), doors=doors)
        print("%s text %s (%d lines, %d xor_by) root %s" % (Path(wadp).name, h(text),
                                                             text.count("\n"), text.count("hex.xor_by"), root))
        print("%s line_constants %s (%d rows)" % (Path(wadp).name,
                                                  h("\n".join(repr(line_constants(r)) for r in rows)),
                                                  len(rows)))
    rng = random.Random(7)
    names = ["ca_minx", "ca_maxx", "ca_miny", "ca_maxy", "ca_v1x", "ca_v1y", "ca_dx", "ca_dy",
             "ca_ob", "ca_ot", "ca_slope", "ca_flags"]
    sweep = [(n, rng.getrandbits(32)) for n in names for _ in range(500)] + \
            [(n, v) for n in names for v in (0, 1, 15, 16, 0xFFFFFFFF, 0x80000000)]
    print("xor_lines sweep (%d consts) %s" % (len(sweep), h("\n".join(_xor_lines(sweep)))))
    print("CELL_DECLS %s" % h("\n".join(CELL_DECLS)))
    print("COLLISION_STATE_DECLS %s (%d names)" % (h("\n".join(COLLISION_STATE_DECLS)),
                                                   len(COLLISION_STATE_DECLS)))


def extract(ref, dest):
    data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=ROOT, check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(dest)
    return Path(dest)


def mutate(tree, old, new):
    f = tree / "src/doomfj/collision.py"
    s = f.read_text(encoding="utf-8")
    assert s.count(old) == 1, "the control's mutation site moved: %r" % old
    f.write_text(s.replace(old, new), encoding="utf-8", newline="\n")


def run(tree):
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe"], cwd=tree, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip().splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="34960cb", help="the commit the binary was built at")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.probe:
        probe()
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base, head = run(extract(args.base, tmp / "base")), run(extract(args.head, tmp / "head"))
        neg1 = extract(args.head, tmp / "neg_decl")
        mutate(neg1, '("ca_slope", 1)', '("ca_slope", 2)')
        neg2 = extract(args.head, tmp / "neg_xor")
        mutate(neg2, "for i in range(_ARG_WIDTH[cell]):",
               'for i in range(_ARG_WIDTH[cell] - (cell == "ca_dx")):')
        n1, n2 = run(neg1), run(neg2)
    print("base %s:" % args.base)
    for ln in base:
        print("   " + ln)
    same = head == base
    print("head %s: %s" % (args.head, "EVERY VALUE EQUAL" if same else "!! DIFFERS"))
    for a, b in zip(base, head):
        if a != b:
            print("   base  " + a + "\n   head  " + b)
    c1, c2 = n1 != base, n2 != base
    print("CONTROL ca_slope declared 2 wide:   %s" % ("caught -- %d value(s) differ" % sum(
        a != b for a, b in zip(base, n1)) if c1 else "!! NOT CAUGHT"))
    print("CONTROL ca_dx's top nibble dropped: %s" % ("caught -- %d value(s) differ" % sum(
        a != b for a, b in zip(base, n2)) if c2 else "!! NOT CAUGHT"))
    ok = same and c1 and c2
    print("EMISSION-NEUTRAL: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
