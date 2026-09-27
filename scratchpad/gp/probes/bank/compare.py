"""P1.6 probe: how far do native lists + rowmap move today's per-bucket strips? Over every E1M1 kind,
every downscaled column, every tier the oracle uses and every bucket height: pixels painted
differently (the column's painted rows as texels), and whether a column is drawn at all."""
import sys
from pathlib import Path

sys.path.insert(0, "src")
from doomfj.config import Config
from doomfj.reference_model import (DEG_SPR_LOWRES_CAP, DEG_SPR_MID_CAP, ReferenceModel,
                                    SPRITE_HEIGHT_BUCKETS, SPRITE_RUN_CAP_HD, THING_SPRITE,
                                    sprite_bucket_height)
from doomfj.spritebank import bank_list, strip_at
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
art_wad = WadFile.from_path("assets/freedoom1.wad")
H = cfg.VIEW_H
heights = [sprite_bucket_height(b, H) for b in range(SPRITE_HEIGHT_BUCKETS)]


def paint(st, hb):
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


cache, kinds = {}, sorted(set(THING_SPRITE))
tot_px = diff_px = cols = drawn_flip = 0
worst = []
for kind in kinds:
    art = rm.sprite_art(art_wad, kind, cache)
    if art is None:
        continue
    cols_h, dh_h = art[7], art[8]          # full-res (HD)
    cols_m, dh_m = art[0], art[1]          # half-res (mid / coarse)
    for tier, cols_, dh, cap in (("hd", cols_h, dh_h, SPRITE_RUN_CAP_HD),
                                 ("mid", cols_m, dh_m, DEG_SPR_MID_CAP),
                                 ("ld", cols_m, dh_m, DEG_SPR_LOWRES_CAP)):
        for u, col in enumerate(cols_):
            bl = bank_list(col, dh, cap, heights)
            for b, hb in enumerate(heights):
                if tier == "hd" and hb < 40:
                    continue
                if tier != "hd" and hb >= 40:
                    continue
                old = rm.sprite_strip(col, dh, hb, cap=cap)
                new = strip_at(bl, b, hb)
                po, pn = paint(old, hb), paint(new, hb)
                rows = set(po) | set(pn)
                d = sum(1 for r in rows if po.get(r) != pn.get(r))
                cols += 1
                tot_px += len(rows)
                diff_px += d
                drawn_flip += (old is None) != (new is None)
                if d:
                    worst.append((d, kind, tier, u, hb))
print("columns x buckets compared: %d; painted rows %d; rows that differ %d (%.2f%%); "
      "drawn/not-drawn flips %d" % (cols, tot_px, diff_px, 100.0 * diff_px / max(1, tot_px), drawn_flip))
worst.sort(reverse=True)
print("worst:", worst[:8])
