"""P1.6 probe: the native-list bank's SIZE, measured -- the numbers docs/gp-sprite-bank.md section 6
and the ledger's P1.6 budget quote come from here, not from arithmetic in a doc.

Everything is measured at a COMMIT (`git archive`, each tree importing its own doomfj in its own
process), so an uncommitted change is never what the numbers name:

  * BANK: `wall_renderer._lines_sprite_bank` for E1M1, emitted, and its cells counted (64 cells a
    block, 128 words a block): the kinds' three regions and the animation's. With `--base REV` the
    same count at that revision's emitter -- the per-bucket bank P1.6 replaced.
  * ANIMATION: views (sprite, frame letter, rotation), distinct lumps, mirrored views.
  * ROWMAP: `wall_renderer.sprite_rowmap_fj` assembled after a prefix that puts its switch on an
    8,192-op boundary (its own `pad 8192` then inserts nothing), and the same program without it:
    the difference in the .fjm's data words is the table (switch, handlers, clean table, wflip
    chains). Where a real build lands it, that `pad` costs 0..8,191 ops (0..16,382 words) more.

CONTROLS (R9): the block counter reads a synthetic 3-block bank as 3 and REFUSES one cell short; the
assembler measurement reads an empty addition as 0 words and `rep(1000) stl.fj _end, _end` as 2,000.

    python scratchpad/gp/probes/bank/size.py [--rev HEAD] [--base 4653cc9]
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_CELL = re.compile(r"^;(0x[0-9a-f]+|\d+) \* dw$")


def count_blocks(text, header, stride):
    """the bank text's blocks: every line after `header` is one cell, and cells come in whole blocks"""
    lines = text.splitlines()
    assert lines[:len(header)] == header, "the bank does not open with its header"
    cells = lines[len(header):]
    bad = [c for c in cells if not _CELL.match(c)]
    assert not bad, "not a cell: %r" % bad[:3]
    assert len(cells) % stride == 0, "%d cells are not whole %d-cell blocks" % (len(cells), stride)
    return len(cells) // stride


def fjm_words(tmp, name, body):
    """(data words, span words) of `stl.startup_and_init_all` + a jump over `body` + a loop"""
    import flipjump as fj
    from fjmsize import read_fjm_size
    from doomfj.harness import W
    src = tmp / (name + ".fj")
    src.write_text("\n".join(["stl.startup_and_init_all", ";_end", *body, "_end:", "    stl.loop",
                              ""]), encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src], out, memory_width=W, print_time=False)
    s = read_fjm_size(out)
    return s.data_words, s.span_words


def probe():
    """inside a tree (cwd = its root, PYTHONPATH = its src): its counts as one JSON line"""
    sys.path.insert(0, str(Path("scratchpad/12m").resolve()))          # fjmsize, the one reader
    from doomfj import wall_renderer as wr
    from doomfj.config import Config
    from doomfj.reference_model import ReferenceModel
    from doomfj.wad import WadFile
    cfg = Config()
    rm = ReferenceModel(cfg)
    art = WadFile.from_path("assets/freedoom1.wad")
    mw = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
    res = wr._lines_sprite_bank(rm, art, cfg, mw, "E1M1")
    text, base, dw = res[0], res[1], res[2]
    hdr = wr.sprite_bank_header()
    out = dict(blocks=count_blocks(text, hdr, wr.SPR_BLOCK_STRIDE), stride=wr.SPR_BLOCK_STRIDE,
               kinds=len(base), columns=sum(dw.values()), chars=len(text))
    if len(res) > 4:                                   # M7 P1.6: the animation's regions
        from doomfj.reference_model import THING_SPRITE
        from doomfj.things import drawable_things
        anim = res[4]
        pats = wr.anim_patches(art, wr.anim_frames(mw, "E1M1"))
        out.update(views=len(anim), mirrored=sum(1 for v in anim.values() if v[2]),
                   lumps=len({v[0] for v in anim.values()}),
                   lump_names=len({lump for lump, _m in pats.values()}),
                   kind_blocks=3 * sum(dw.values()))
        # which of the bank's kinds a DRAWABLE thing uses (things.drawable_things, the one list
        # the thing tables index), and which kinds share one sprite (their regions are equal)
        drawn = {t.type for t in drawable_things(rm, mw.things("E1M1"), art, {})[0]}
        undrawn = sorted(k for k in base if k not in drawn)
        first = {}
        dup = sorted(k for k in sorted(base) if first.setdefault(THING_SPRITE[k], k) != k)
        out.update(drawable_kinds=len(drawn & set(base)), undrawn_kinds=undrawn,
                   undrawn_blocks=3 * sum(dw[k] for k in undrawn), dup_kinds=dup,
                   dup_blocks=3 * sum(dw[k] for k in dup if k not in undrawn))
    # CONTROL: the block counter reads 3 blocks as 3, and refuses one cell short
    three = "\n".join(hdr + [";0x%x * dw" % (k % 7) for k in range(3 * wr.SPR_BLOCK_STRIDE)])
    out["ctl_count3"] = count_blocks(three, hdr, wr.SPR_BLOCK_STRIDE) == 3
    try:
        count_blocks("\n".join(hdr + [";0 * dw"] * (3 * wr.SPR_BLOCK_STRIDE - 1)), hdr,
                     wr.SPR_BLOCK_STRIDE)
        out["ctl_short_refused"] = False
    except AssertionError:
        out["ctl_short_refused"] = True
    if hasattr(wr, "sprite_rowmap_fj"):
        pre = ["pad 8192", "rep(8190, i) stl.fj 0, 0"]    # rowmap.init's two ops end the page
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            d0, s0 = fjm_words(tmp, "p0", pre)
            d0b, s0b = fjm_words(tmp, "p0b", pre + [""])
            dc, _sc = fjm_words(tmp, "pc", pre + ["rep(1000, i) stl.fj _end, _end"])
            d1, s1 = fjm_words(tmp, "p1", pre + [wr.sprite_rowmap_fj(cfg)])
        out.update(rowmap_data=d1 - d0, rowmap_span=s1 - s0, ctl_empty=(d0b - d0, s0b - s0),
                   ctl_1000=dc - d0)
    print(json.dumps(out))


def extract(ref, dest):
    data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=ROOT, check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(dest)
    (Path(dest) / "assets").mkdir(exist_ok=True)       # the art wad is not in git (.gitignore)
    (Path(dest) / "assets/freedoom1.wad").write_bytes((ROOT / "assets/freedoom1.wad").read_bytes())
    return Path(dest)


def run_probe(tree):
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe"], cwd=tree,
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def describe(ref):
    return subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %s", ref],
                          capture_output=True, text=True, check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rev", default="HEAD", help="the revision to measure")
    ap.add_argument("--base", help="also count the bank at this revision (the one P1.6 replaced)")
    ap.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.probe:
        probe()
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        now = run_probe(extract(a.rev, Path(tmp) / "rev"))
        was = run_probe(extract(a.base, Path(tmp) / "base")) if a.base else None
    print("size.py: --rev %s = %s" % (a.rev, describe(a.rev)))
    ok = now["ctl_count3"] and now["ctl_short_refused"]
    print("CONTROL block counter: 3 blocks read as 3 %s; one cell short refused %s" % (
        "ok" if now["ctl_count3"] else "!! FAILED", "ok" if now["ctl_short_refused"] else "!! FAILED"))
    c3, c4 = tuple(now["ctl_empty"]) == (0, 0), now["ctl_1000"] == 2000
    ok = ok and c3 and c4
    print("CONTROL assembler: an empty addition %s data/span words (%s); 1,000 ops %d data words (%s)"
          % (tuple(now["ctl_empty"]), "ok" if c3 else "!! FAILED", now["ctl_1000"],
             "ok" if c4 else "!! FAILED"))
    words = 2 * now["stride"]
    print("BANK: %d blocks = %d words -- %d kinds, %d columns: %d blocks in the kinds' three "
          "regions, %d in the animation's; %d characters of fj" % (
              now["blocks"], now["blocks"] * words, now["kinds"], now["columns"], now["kind_blocks"],
              now["blocks"] - now["kind_blocks"], now["chars"]))
    print("KINDS: %d in the bank, %d of them drawn by a drawable (single-player) thing; the %d no "
          "drawable thing uses %s hold %d blocks = %d words; kinds banked again under a sprite "
          "another kind already holds %s: %d more blocks = %d words" % (
              now["kinds"], now["drawable_kinds"], len(now["undrawn_kinds"]), now["undrawn_kinds"],
              now["undrawn_blocks"], now["undrawn_blocks"] * words, now["dup_kinds"],
              now["dup_blocks"], now["dup_blocks"] * words))
    print("ANIMATION: %d views, %d distinct lumps (%d by lump name), %d views mirrored" % (
        now["views"], now["lumps"], now["lump_names"], now["mirrored"]))
    print("ROWMAP: %d data words (%d span words) with its switch aligned, plus 0..%d words of its "
          "own `pad 8192` wherever a build lands it" % (now["rowmap_data"], now["rowmap_span"],
                                                        2 * 8191))
    if was:
        print("BANK at --base %s = %s: %d blocks = %d words -- %d kinds, %d columns; %d characters"
              % (a.base, describe(a.base), was["blocks"], was["blocks"] * 2 * was["stride"],
                 was["kinds"], was["columns"], was["chars"]))
        dbank = now["blocks"] * words - was["blocks"] * 2 * was["stride"]
        print("DELTA: the bank %+d blocks = %+d words; with the rowmap (aligned) %+d words = "
              "%+.3f%% of 2^27" % (now["blocks"] - was["blocks"], dbank, dbank + now["rowmap_data"],
                                   100.0 * (dbank + now["rowmap_data"]) / 2 ** 27))
    print("CONTROLS %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
