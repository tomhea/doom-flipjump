"""P1.6 probe: how far do the native lists + rowmap move the per-bucket strips they replace?

POPULATION -- E1M1's, as the game draws it:
  * the DRAWABLE kinds (`doomfj.things.drawable_things`: single-player things with art, the one
    definition the emitter, the oracle and the gates share), each distinct PATCH once -- the demon
    and the spectre both draw SARG, so it is counted once, not twice;
  * every downscaled column of each patch;
  * each TIER only at the buckets that tier is DRAWN at: `reference_model.sprite_tier` over a near
    and (with SPR-NEAR) a far thing -- HD from SPRITE_HD_H up, MID below it, LD below
    DEG_SPR_LOWRES_H. (The first version compared LD at the MID-only heights too, and every
    THING_SPRITE type rather than E1M1's.)

OLD = `ReferenceModel.sprite_strip` at the bucket's height with the tier's columns and cap (the
per-bucket bank's rule: P1.5's oracle); NEW = `strip_at(sprite_tier_list(...))` (P1.6's oracle, the
lists the emitter bakes). Counted: painted rows (the union of the two pictures), rows whose texel
differs, and column-bucket pairs one draws and the other does not. Also: how many column-tiers each
rule draws NON-MONOTONELY over the tier's buckets (drawn at one height, not at a taller one) -- the
reason `min_b` is a definition rather than a property (docs/gp-sprite-bank.md section 4); NEW's must
be 0, by that definition.

CONTROLS (R9), run every time: OLD against OLD and NEW against NEW must count 0 differing rows and 0
flips (the comparison invents nothing), and NEW against NEW RECOLOURED (every texel + 1) must count
every painted row (it misses nothing).

    python scratchpad/gp/probes/bank/compare.py
"""
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.config import Config                                            # noqa: E402
from doomfj.reference_model import (DEG_SPR_NEAR_TZ, SPRITE_HEIGHT_BUCKETS, SPRITE_TIERS,  # noqa: E402
                                    THING_SPRITE, ReferenceModel, sprite_bucket_height,
                                    sprite_tier, sprite_tier_list, sprite_tier_source)
from doomfj.spritebank import strip_at                                      # noqa: E402
from doomfj.things import drawable_things                                   # noqa: E402
from doomfj.wad import WadFile                                              # noqa: E402

cfg = Config()
rm = ReferenceModel(cfg)
H = cfg.VIEW_H
HEIGHTS = tuple(sprite_bucket_height(b, H) for b in range(SPRITE_HEIGHT_BUCKETS))
FARS = (False, True) if DEG_SPR_NEAR_TZ else (False,)       # LD exists only with SPR-NEAR


def paint(st):
    """the column's pixels (row -> texel) from a (r0, runs) strip"""
    if st is None:
        return {}
    r0, runs = st
    out, prev = {}, 0
    for e, t in runs:
        for r in range(prev, e):
            out[r0 + r] = t
        prev = e
    return out


def population():
    """[(sprite, kinds, art)]: E1M1's drawable kinds, one entry per distinct patch"""
    art_wad = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    cache = {}
    drawable, _ = drawable_things(rm, mw.things("E1M1"), art_wad, cache)
    by_sprite = {}
    for kind in sorted({t.type for t in drawable}):
        by_sprite.setdefault(THING_SPRITE[kind], []).append(kind)
    return [(s, ks, rm.sprite_art(art_wad, ks[0], cache)) for s, ks in sorted(by_sprite.items())]


def drawn_buckets(tier):
    """the buckets `tier` is drawn at, by the oracle's own rule"""
    return [b for b, hb in enumerate(HEIGHTS) if tier in {sprite_tier(hb, far) for far in FARS}]


def compare(pop, old_fn, new_fn):
    """(Counter, worst): painted rows, differing rows and drawn/not-drawn flips, per tier and total"""
    c, worst = Counter(), []
    for sprite, _kinds, art in pop:
        for tier in SPRITE_TIERS:
            bks = drawn_buckets(tier)
            if not bks:
                continue
            cols, dh, cap = sprite_tier_source(art, tier)
            for u in range(len(cols)):
                for b in bks:
                    old, new = old_fn(art, tier, u, b), new_fn(art, tier, u, b)
                    po, pn = paint(old), paint(new)
                    rows = set(po) | set(pn)
                    d = sum(1 for r in rows if po.get(r) != pn.get(r))
                    flip = (old is None) != (new is None)
                    for key in (tier, "total"):
                        c[key, "pairs"] += 1
                        c[key, "rows"] += len(rows)
                        c[key, "diff"] += d
                        c[key, "flips"] += flip
                    if d:
                        worst.append((d, sprite, tier, u, HEIGHTS[b]))
    worst.sort(reverse=True)
    return c, worst


def nonmonotone(pop, fn):
    """(column-tiers drawn at some bucket and not at a taller one of the same tier, column-tiers)"""
    n = tot = 0
    for _sprite, _kinds, art in pop:
        for tier in SPRITE_TIERS:
            bks = drawn_buckets(tier)
            if not bks:
                continue
            for u in range(len(sprite_tier_source(art, tier)[0])):
                seq = [fn(art, tier, u, b) is not None for b in bks]
                tot += 1
                n += any(seq[i] and not all(seq[i:]) for i in range(len(seq)))
    return n, tot


def old_strip(art, tier, u, b):
    cols, dh, cap = sprite_tier_source(art, tier)
    return rm.sprite_strip(cols[u], dh, HEIGHTS[b], cap=cap)


def new_strip(art, tier, u, b):
    return strip_at(sprite_tier_list(art, tier, u, HEIGHTS), b, HEIGHTS[b])


def recoloured(art, tier, u, b):
    st = new_strip(art, tier, u, b)
    return None if st is None else (st[0], [[e, t + 1] for e, t in st[1]])


def main():
    head = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %s"],
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "src"],
                           capture_output=True, text=True).stdout.strip()
    print("compare.py at %s%s" % (head, "  (!! src/ has UNCOMMITTED changes)" if dirty else ""))
    pop = population()
    print("population: %d distinct patches from %d drawable kinds: %s" % (
        len(pop), sum(len(ks) for _s, ks, _a in pop),
        ", ".join("%s%s" % (s, "(%s)" % "+".join(map(str, ks)) if len(ks) > 1 else "")
                  for s, ks, _a in pop)))
    print("columns: %d; tiers drawn at: %s" % (sum(a[2] for _s, _k, a in pop), "; ".join(
        "%s %s" % (t, [HEIGHTS[b] for b in drawn_buckets(t)]) for t in SPRITE_TIERS)))
    ok = True
    for name, fa, fb, want_all in (("OLD vs OLD", old_strip, old_strip, False),
                                   ("NEW vs NEW", new_strip, new_strip, False),
                                   ("NEW vs NEW recoloured", new_strip, recoloured, True)):
        c, _w = compare(pop, fa, fb)
        good = (c["total", "diff"] == c["total", "rows"] and c["total", "flips"] == 0) if want_all \
            else (c["total", "diff"] == 0 and c["total", "flips"] == 0)
        ok &= good
        print("CONTROL %-22s rows %d, differing %d, flips %d -> %s" % (
            name, c["total", "rows"], c["total", "diff"], c["total", "flips"],
            "ok" if good else "!! FAILED"))
    c, worst = compare(pop, old_strip, new_strip)
    for key in SPRITE_TIERS + ("total",):
        if c[key, "pairs"]:
            print("%-5s column-bucket pairs %6d; painted rows %8d; rows that differ %7d (%.2f%%); "
                  "drawn/not-drawn flips %d" % (key, c[key, "pairs"], c[key, "rows"], c[key, "diff"],
                                                100.0 * c[key, "diff"] / max(1, c[key, "rows"]),
                                                c[key, "flips"]))
    print("worst (rows, sprite, tier, u, height):", worst[:8])
    (no, to), (nn, tn) = nonmonotone(pop, old_strip), nonmonotone(pop, new_strip)
    print("non-monotone column-tiers: OLD %d of %d; NEW %d of %d%s" % (
        no, to, nn, tn, "" if nn == 0 else "  !! min_b promised 0"))
    ok &= nn == 0
    print("CONTROLS %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
