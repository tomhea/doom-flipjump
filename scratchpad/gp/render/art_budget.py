"""Price the ART that gameplay adds, in 32-bit words, under several bank formats.
Cheap Python over freedoom1.wad; reuses the oracle's own sprite_strip (R6) so the run counts are
what the shipped emitter would bake."""
import sys, collections
sys.path.insert(0, r"C:/Users/tomhe/Documents/doom-flipjump/src")
from doomfj.wad import WadFile, decode_picture
from doomfj.config import Config
from doomfj.reference_model import (ReferenceModel, SPRITE_HEIGHT_BUCKETS, sprite_bucket_height,
                                    SPRITE_HD_H, SPRITE_RUN_CAP_HD, DEG_SPR_MID_CAP,
                                    DEG_SPR_LOWRES_CAP, DEG_SPR_LOWRES_H)
from doomfj import wall_renderer as wr

cfg = Config(); rm = ReferenceModel(cfg)
fw = WadFile.from_path(r"C:/Users/tomhe/Documents/doom-flipjump/assets/freedoom1.wad")
names = fw.names()
spr = names[names.index("S_START") + 1:names.index("S_END")]
NLD = wr._spr_nlow(cfg); NB = SPRITE_HEIGHT_BUCKETS; STRIDE = wr.SPR_BLOCK_STRIDE
HB = [sprite_bucket_height(b, cfg.VIEW_H) for b in range(NB)]
ds = 2

def art_of(lump):
    pic = decode_picture(fw.get_data(lump))
    dw, dh = max(1, pic.width // ds), max(1, pic.height // ds)
    cols, fcols = [], []
    for u in range(dw):
        dense = [-1] * pic.height
        for (v, t) in pic.columns[min(pic.width - 1, u * ds)]:
            if 0 <= v < pic.height:
                dense[v] = t
        cols.append([dense[min(pic.height - 1, v * ds)] for v in range(dh)])
        fcols.append(dense)
    return pic, cols, dh, dw, fcols

cache = {}
def price(lump):
    """ops per format for one patch (one rotation/frame)"""
    if lump in cache:
        return cache[lump]
    pic, cols, dh, dw, fcols = art_of(lump)
    f0 = dw * (NB + NLD) * STRIDE                     # shipped: every block padded to 64 ops
    f1 = 0                                             # shipped layout, blocks packed (no pad)
    for u in range(dw):
        for b in range(NB):
            hb = HB[b]
            st = (rm.sprite_strip(fcols[u], pic.height, hb, cap=SPRITE_RUN_CAP_HD) if hb >= SPRITE_HD_H
                  else rm.sprite_strip(cols[u], dh, hb, cap=DEG_SPR_MID_CAP))
            f1 += 3 + (0 if st is None else 2 * len(st[1]))
        for b in range(NLD):
            st = rm.sprite_strip(cols[u], dh, HB[b], cap=DEG_SPR_LOWRES_CAP)
            f1 += 3 + (0 if st is None else 2 * len(st[1]))
    # native lists: one full-res list (h = pic.height, cap 24), one downscaled (h = dh, cap 12),
    # one coarse (h = dh, cap 4) per column -- scaled to the on-screen height at RUNTIME
    f2 = 0; runs_hd = runs_mid = runs_ld = 0
    for u in range(dw):
        a = rm.sprite_strip(fcols[u], pic.height, pic.height, cap=SPRITE_RUN_CAP_HD)
        m = rm.sprite_strip(cols[u], dh, dh, cap=DEG_SPR_MID_CAP)
        l = rm.sprite_strip(cols[u], dh, dh, cap=DEG_SPR_LOWRES_CAP)
        for s in (a, m, l):
            f2 += 3 + (0 if s is None else 2 * len(s[1]))
        runs_hd += 0 if a is None else len(a[1]); runs_mid += 0 if m is None else len(m[1]); runs_ld += 0 if l is None else len(l[1])
    f3 = dw * (64 + 32 + 16)                           # native lists at pow2 strides (shift addressing)
    f4 = dw * (32 + 16)                                # native: mid (cap 12, 27<32) + coarse only
    res = dict(dw=dw, dh=dh, w=pic.width, h=pic.height, f0=f0, f1=f1, f2=f2, f3=f3, f4=f4,
               rhd=runs_hd, rmid=runs_mid, rld=runs_ld)
    cache[lump] = res
    return res

def frames(prefix):
    fr = collections.defaultdict(dict)
    for n in spr:
        if not n.startswith(prefix):
            continue
        body = n[4:]
        fr[body[0]][int(body[1])] = (n, False)
        if len(body) >= 4:
            fr[body[2]][int(body[3])] = (n, True)
    return fr

def patch_set(prefix, letters, rots, mirror5=True):
    """distinct LUMPS needed: letters x rots (rot 0 frames need only 0). With mirror5 a rotation
    6/7/8 is drawn as 4/3/2 flipped at draw time, so only 1..5 are stored."""
    fr = frames(prefix); need = set()
    for L in letters:
        rs = fr[L]
        if 0 in rs:
            need.add(rs[0][0]); continue
        want = [r for r in rots if (not mirror5 or r <= 5)]
        for r in want:
            need.add(rs[r][0])
    return sorted(need)

MON = {
    # prefix: (walk, attack, pain, death, xdeath)
    "POSS": ("ABCD", "EF", "G", "HIJKL", "MNOPQRSTU"),
    "SPOS": ("ABCD", "EF", "G", "HIJKL", "MNOPQRSTU"),
    "TROO": ("ABCD", "EFG", "H", "IJKLM", "NOPQRSTU"),
    "SARG": ("ABCD", "EFG", "H", "IJKLMN", ""),
}
ALL8 = [1, 2, 3, 4, 5, 6, 7, 8]
def policy_lumps(prefix, pol):
    walk, atk, pain, death, xd = MON[prefix]
    if pol == "FULL8":       # every frame, every stored rotation, no forced mirroring
        return patch_set(prefix, walk + atk + pain + death + xd, ALL8, mirror5=False)
    if pol == "DOOM5":       # every frame, 5 rotations (6-8 mirrored at draw time)
        return patch_set(prefix, walk + atk + pain + death + xd, ALL8, mirror5=True)
    if pol == "LEAN":        # walk x5 rot; attack + pain FRONT only (A_FaceTarget); death; no gibs
        return sorted(set(patch_set(prefix, walk, ALL8)) | set(patch_set(prefix, atk + pain, [1]))
                      | set(patch_set(prefix, death, [0])))
    if pol == "MIN":         # 2-frame walk (A,C) x5; one attack frame (fire) + pain front; 2 death frames
        return sorted(set(patch_set(prefix, walk[0] + walk[2], ALL8)) |
                      set(patch_set(prefix, atk[-1] + pain, [1])) |
                      set(patch_set(prefix, death[0] + death[-1], [0])))

def tot(lumps, key):
    return sum(price(l)[key] for l in lumps)

print(f"NB={NB} NLD={NLD} stride={STRIDE}; words = 2 x ops")
print(f"{'set':22s} {'patches':>7s} {'cols':>6s} {'F0 shipped':>12s} {'F1 packed':>11s} {'F2 native':>10s} {'F3 nat-pow2':>11s} {'F4 mid+ld':>10s}")
grand = collections.Counter()
for pol in ("FULL8", "DOOM5", "LEAN", "MIN"):
    tl = collections.Counter()
    for p in MON:
        ls = policy_lumps(p, pol)
        row = dict(n=len(ls), cols=tot(ls, "dw"), **{k: 2 * tot(ls, k) for k in ("f0", "f1", "f2", "f3", "f4")})
        tl.update(row)
        print(f"{pol+' '+p:22s} {row['n']:7d} {row['cols']:6d} {row['f0']:12,d} {row['f1']:11,d} {row['f2']:10,d} {row['f3']:11,d} {row['f4']:10,d}")
    print(f"{pol+' TOTAL':22s} {tl['n']:7d} {tl['cols']:6d} {tl['f0']:12,d} {tl['f1']:11,d} {tl['f2']:10,d} {tl['f3']:11,d} {tl['f4']:10,d}")
    print()

# projectiles / effects (rotation 0 only)
for p, letters in (("BAL1", "ABCDE"), ("PUFF", "ABCD"), ("BLUD", "ABC")):
    ls = patch_set(p, letters, [0])
    print(f"{p:6s} {len(ls):3d} patches cols {tot(ls,'dw'):4d}  F0 {2*tot(ls,'f0'):10,d}  F1 {2*tot(ls,'f1'):9,d}  F2 {2*tot(ls,'f2'):8,d}  F3 {2*tot(ls,'f3'):8,d}")

# run statistics (for the per-run runtime cost)
for p in MON:
    ls = policy_lumps(p, "LEAN")
    c = tot(ls, "dw")
    print(f"{p}: mean runs/col  hd {tot(ls,'rhd')/c:.1f}  mid {tot(ls,'rmid')/c:.1f}  ld {tot(ls,'rld')/c:.1f}")

# ---- the SHIPPED static bank, re-priced in each format (the 32 kinds sprite_art bakes today)
from doomfj.reference_model import THING_SPRITE
mw = WadFile.from_path(r"C:/Users/tomhe/Documents/doom-flipjump/tests/fixtures/freedoom_e1m1.wad")
kinds = sorted({t.type for t in mw.things("E1M1") if t.type in THING_SPRITE})
lumps = []
for k in kinds:
    pre = THING_SPRITE[k]
    for suf in ("A0", "A1", "A2A8", "A1D1"):
        if pre + suf in set(spr):
            lumps.append(pre + suf); break
print("static kinds", len(lumps), "cols", sum(price(l)["dw"] for l in lumps))
for key in ("f0", "f1", "f2", "f3", "f4"):
    print(f"  static bank {key}: {2*sum(price(l)[key] for l in lumps):,} words")
# weapon frames (for the psprite word estimate: pairs x ~32 words baked as code)
