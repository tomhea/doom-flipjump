"""Step 6: the sprite part of pass 2's DITTO LADDER, TODAY vs PROPOSED -- paid on EVERY column
that reaches the ladder, sprite or not. TODAY compares (sy1, sy2, y0b, blk) for slot A and B and
saves all eight shadows after every emitted column; the 3-byte record compares (slot, blk) and
saves four. The compare cost depends on how far equality runs, so three patterns are priced.
The TODAY lines are TRANSPLANTED from frame_render.fj at run time."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402

SRC = (plib.ROOT / "src/fj/frame_render.fj").read_text(encoding="utf-8")
lad = SRC[SRC.index("      ck_spr_sy1:"):SRC.index("      ck_piece_ucnt:")]
lad = "\n".join(l for l in lad.splitlines() if not l.strip().startswith("//"))
lad = lad.replace("rep(things, k) ", "")
sav = [l.strip() for l in SRC.splitlines()
       if l.strip().startswith("hex.sparse_mov HOT_PAD") and re.search(r"p2_ds(sy|y0|blk)", l)]
assert len(sav) == 8, sav
REGS = ["p2_ssy1", "p2_ssy2", "p2_sy0b", "p2_sblk", "p2_ssy1b", "p2_ssy2b", "p2_sy0bb", "p2_sblkb",
        "p2_dssy1", "p2_dssy2", "p2_dsy0b", "p2_dsblk", "p2_dssy1b", "p2_dssy2b", "p2_dsy0bb", "p2_dsblkb",
        "p2_s", "p2_ds", "p2_sb", "p2_dsb"]
W4 = {"p2_sy0b", "p2_sblk", "p2_sy0bb", "p2_sblkb", "p2_dsy0b", "p2_dsblk", "p2_dsy0bb", "p2_dsblkb"}
DECL = ["%s: hex.vec %d" % (r, 4 if r in W4 else 2) for r in ("p2_s", "p2_ds", "p2_sb", "p2_dsb")]


def today_ladder(tag):
    t = lad
    for lab in re.findall(r"^\s*(ck_[a-z0-9_]+):", lad, re.M):
        t = re.sub(r"\b%s\b" % lab, "%s_%s" % (tag, lab), t)
    t = t.replace("emit_full", "%s_x" % tag)
    t = re.sub(r"\bck_piece_ucnt\b", "%s_ck_piece_ucnt" % tag, t)
    return t.splitlines() + ["%s_ck_piece_ucnt:" % tag, "%s_x:" % tag]


def prop_ladder(tag):
    return ["hex.cmp 2, p2_s, p2_ds, {0}_x, {0}_a, {0}_x".format(tag), "{0}_a:".format(tag),
            "hex.cmp 4, p2_sblk, p2_dsblk, {0}_x, {0}_b, {0}_x".format(tag), "{0}_b:".format(tag),
            "hex.cmp 2, p2_sb, p2_dsb, {0}_x, {0}_c, {0}_x".format(tag), "{0}_c:".format(tag),
            "hex.cmp 4, p2_sblkb, p2_dsblkb, {0}_x, {0}_x, {0}_x".format(tag), "{0}_x:".format(tag)]


PROP_SAV = ["hex.sparse_mov HOT_PAD, 2, p2_ds, p2_s", "hex.sparse_mov HOT_PAD, 4, p2_dsblk, p2_sblk",
            "hex.sparse_mov HOT_PAD, 2, p2_dsb, p2_sb", "hex.sparse_mov HOT_PAD, 4, p2_dsblkb, p2_sblkb"]
# value patterns: (current, shadow) for each register
PATTERNS = {
    "first field differs": dict(p2_ssy1=(30, 31), p2_s=(3, 4)),
    "same thing, next block": dict(p2_ssy1=(30, 30), p2_ssy2=(80, 80), p2_sy0b=(0x8020, 0x8020),
                                   p2_sblk=(0x0123, 0x0143), p2_s=(3, 3)),
    "all equal (a ditto)": dict(p2_ssy1=(30, 30), p2_ssy2=(80, 80), p2_sy0b=(0x8020, 0x8020),
                                p2_sblk=(0x0123, 0x0123), p2_s=(3, 3)),
}
fr = plib.Frame(plib.by_frame(plib.load_cases())[("heavy", "gate664")][:2])


def price(body_fn, pat):
    sets = []
    for r, (cur, sh) in pat.items():
        sets.append("hex.set %d, %s, %d" % (4 if r in W4 else 2, r, cur))
        d = r.replace("p2_", "p2_d")
        sets.append("hex.set %d, %s, %d" % (4 if r in W4 else 2, d, sh))
    ops = []
    for reps in (10, 30):
        body = []
        for k in range(reps):
            body += body_fn("r%d" % k)
        text = plib.program(fr, [], 1, pre_loop=sets + body, lite=True, extra_text="\n".join(DECL))
        ops.append(plib.assemble_run(text, "lad", want_output=False)[0])
    return (ops[1] - ops[0]) / 20.0


if __name__ == "__main__":
    for name, pat in PATTERNS.items():
        t = price(today_ladder, pat)
        p = price(prop_ladder, pat)
        print("  ladder, %-24s TODAY %6.0f   PROPOSED %6.0f" % (name, t, p), flush=True)
    t = price(lambda tag: sav, {})
    p = price(lambda tag: PROP_SAV, {})
    print("  shadow saves (every emitted column)  TODAY %6.0f   PROPOSED %6.0f" % (t, p))
