"""M7 P1.6 review, finding 7 -- is the ONE tier helper NEUTRAL?

`reference_model.sprite_tier` / `sprite_tier_source` / `sprite_tier_list` replaced two copies of the
tier -> (columns, drawn height, run cap) mapping: the oracle's inline three-way column choice and
`wall_renderer.sprite_tier_lists`' own. Nothing may move. This extracts the base commit and the head
(`git archive`) and, in EACH tree's own process, computes both mirrors' output:
  * the EMITTER's: the E1M1 sprite bank (`_lines_sprite_bank`'s text), SHA-256;
  * the ORACLE's: 24 frames -- the P1.4 probe's 8 sprite-heavy viewpoints x its static placement and
    its two fights that move monsters in front of the camera (scratchpad/gp/probes/sprite/cases.py)
    -- each frame's pixels and its slot-A fragments and thing count (`things_out`), SHA-256.
Every value must match.

CONTROLS (R9): two copies of the head, each mutated, must DIFFER from the base -- the MID tier's cap
12 -> 11 in `sprite_tier_source` (both mirrors move: the bank and the frames), and `sprite_tier`
sending a far short thing to MID instead of LD (only the oracle's frames move: the bank holds every
tier regardless). A comparison that cannot see those is not evidence.

    python scratchpad/gp/p16_tierlist_neutral.py [--base 13bea6b] [--head HEAD]
"""
import argparse
import hashlib
import io
import math
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# the P1.4 probe's viewpoints and fights (scratchpad/gp/probes/sprite/cases.py), copied so this tool
# does not import a probe that builds P1.4's bank
VPS = [("gate664", 664, 291, 0x18000000), ("gate1869", 1869, 479, 0x80000000),
       ("h57", 2893, 2015, 0x80000000), ("h71", 2637, 991, 0x0), ("h100", 2637, 991, 0x40000000),
       ("h28", 2893, 1503, 0x0), ("h42", 2381, -289, 0xC0000000), ("h85", 333, -33, 0x40000000)]
FIGHTS = {
    "static": [],
    "heavy": [(3001, 200, -60), (3001, 230, 40), (3001, 260, 110), (3004, 320, -140),
              (3004, 300, 150), (9, 380, 0)],
    "melee": [(3002, 70, 0), (3001, 160, -80), (3001, 180, 70), (3004, 260, 0)],
}


def probe():
    """inside a tree (cwd = its root, PYTHONPATH = its src): one line per value"""
    from doomfj import wall_renderer as wr
    from doomfj.config import Config
    from doomfj.reference_model import (GAME_RENDER_KW, MONSTER_TYPES, ReferenceModel, SimState,
                                        build_scene)
    from doomfj.things import baked_thing_mask, drawable_things
    from doomfj.wad import WadFile

    def h(v):
        return hashlib.sha256(v if isinstance(v, bytes) else repr(v).encode()).hexdigest()[:16]
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
    art = WadFile.from_path("assets/freedoom1.wad")
    text = wr._lines_sprite_bank(rm, art, cfg, mw, "E1M1")[0]
    print("bank %s (%d lines)" % (h(text.encode()), text.count("\n")))
    scene = build_scene(mw, mw, "E1M1")
    drawable, _ = drawable_things(rm, mw.things("E1M1"), art, {})
    baked = baked_thing_mask(rm, scene.cmap, drawable, MONSTER_TYPES)
    mons = {k: [i for i, t in enumerate(drawable) if not baked[i] and t.type == k]
            for k in (3001, 3004, 9, 3002)}
    for fight, placements in FIGHTS.items():
        for name, vx, vy, va in VPS:
            pos, used, moved = [(t.x, t.y) for t in drawable], {k: 0 for k in mons}, 0
            a = (va & 0xFFFFFFFF) / 2 ** 32 * 2 * math.pi
            for typ, d, lat in placements:
                if used[typ] < len(mons[typ]):
                    pos[mons[typ][used[typ]]] = (int(round(vx + d * math.cos(a) - lat * math.sin(a))),
                                                 int(round(vy + d * math.sin(a) + lat * math.cos(a))))
                    used[typ] += 1
                    moved += 1
            things = []
            px = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                      sprite_wad=art, **GAME_RENDER_KW, things_out=things,
                                      thing_positions=pos if placements else None)
            frags = things[0]
            print("%s:%s moved %d, fragments %d: pixels %s fragments %s" % (
                fight, name, moved, sum(f is not None for f in frags), h(bytes(px)), h(things)))


def extract(ref, dest):
    data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=ROOT, check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(dest)
    (Path(dest) / "assets").mkdir(exist_ok=True)       # the art wad is not in git (.gitignore)
    (Path(dest) / "assets/freedoom1.wad").write_bytes((ROOT / "assets/freedoom1.wad").read_bytes())
    return Path(dest)


def mutate(tree, old, new):
    f = tree / "src/doomfj/reference_model.py"
    s = f.read_text(encoding="utf-8")
    assert s.count(old) == 1, "the control's mutation site moved: %r" % old
    f.write_text(s.replace(old, new), encoding="utf-8", newline="\n")


def run(tree):
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe"], cwd=tree, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout.strip().splitlines()


def describe(ref):
    """a commit's `%h %s`; a bare TREE (`git write-tree` of a staged change) says so"""
    r = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %s", ref],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():             # (a tree logs nothing, and exits 0)
        return r.stdout.strip()
    kind = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-t", ref], capture_output=True,
                          text=True, check=True).stdout.strip()
    return "a %s, not a commit (the staged change, before its commit)" % kind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="13bea6b", help="the rung before the helper")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.probe:
        probe()
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base, head = run(extract(args.base, tmp / "base")), run(extract(args.head, tmp / "head"))
        neg1 = extract(args.head, tmp / "neg_cap")
        mutate(neg1, "        return art[0], art[1], DEG_SPR_MID_CAP\n",
               "        return art[0], art[1], DEG_SPR_MID_CAP - 1\n")
        neg2 = extract(args.head, tmp / "neg_tier")
        mutate(neg2, '    return "LD" if (far and hb < DEG_SPR_LOWRES_H) else "MID"\n',
               '    return "MID"\n')
        n1, n2 = run(neg1), run(neg2)
    print("base %s = %s:" % (args.base, describe(args.base)))
    for ln in base:
        print("   " + ln)
    same = head == base
    print("head %s = %s: %s" % (args.head, describe(args.head),
                                "EVERY VALUE EQUAL (%d)" % len(base) if same else "!! DIFFERS"))
    for a, b in zip(base, head):
        if a != b:
            print("   base  " + a + "\n   head  " + b)
    d1 = [(a, b) for a, b in zip(base, n1) if a != b]
    d2 = [(a, b) for a, b in zip(base, n2) if a != b]
    c1 = bool(d1) and d1[0][0].startswith("bank") and len(d1) > 1   # the bank AND frames moved
    c2 = bool(d2) and not d2[0][0].startswith("bank")                 # frames moved, the bank not
    print("CONTROL MID cap 12 -> 11:        %s" % ("caught -- %d value(s) differ, the bank among them"
                                                  % len(d1) if c1 else "!! NOT CAUGHT (%d)" % len(d1)))
    print("CONTROL far short thing -> MID:  %s" % ("caught -- %d frame value(s) differ, the bank not"
                                                  % len(d2) if c2 else "!! NOT CAUGHT (%d)" % len(d2)))
    ok = same and c1 and c2
    print("TIER HELPER NEUTRAL: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
