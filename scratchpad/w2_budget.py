"""Sizing the W2-walls + minor-textured-floors tier for the lines protocol (E1M1 spawn).

The lines emit cost is per (y2, colour) PAIR. Today a claimed column emits ~1 wall pair + a
handful of ceiling/floor band pairs, and 58% of columns are pure ditto copies. Adding wall
texture turns the single wall pair into N pairs; adding floor texture turns each band into
several. This counts, for every candidate, the pairs and the surviving ditto rate.

Candidates
  W2-tile    : the EXISTING W2 tier -- 1x16 strip tiled by the real DOOM v-DDA (frac 8.8 mod
               2^16, texel = (frac>>8)&15). Exact but scale-dependent per column.
  W2-stretch : the 16 strip texels spread evenly over each wall's [top,bottom) span. Depends
               only on (top,bottom,seg) -> DITTO-PRESERVING, and needs no per-row DDA.
  floor-bandtex : keep the distance-light band structure, but colour each band from the flat's
               texel sampled once per band (instead of one flat base colour for all bands).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config
from doomfj.fixedpoint import _signed, fixed_mul
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import (ReferenceModel, ANGLE_MASK, COLORMAP_LIGHTS, LIGHT_SHIFT,
                                    spawn_state, build_scene)
from doomfj.wad import WadFile

cfg = Config()
wad = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
rm = ReferenceModel(cfg)
cmap = bake_bsp(wad, "E1M1")
scene = build_scene(wad, wad, "E1M1")
lds = wad.linedefs("E1M1"); sds = wad.sidedefs("E1M1"); secs = wad.sectors("E1M1")
sp = spawn_state(wad, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
H, W, CY = cfg.VIEW_H, cfg.VIEW_W, cfg.CENTERY
verts = cmap.vertexes
pss = cmap.subsectors[rm.point_in_subsector(cmap, spx, spy)]
viewz = rm.view_z(rm._seg_sector(lds, sds, secs, cmap.segs[pss.firstseg]).floor_h)
vzs = _signed(viewz, 32)
ds = rm.downscale

drawn = bytearray(W)
cols = []          # per claimed column: (x, seg_i, top, bottom, scale, sec)
for seg_i in rm.visible_segs(cmap, spx, spy):
    seg = cmap.segs[seg_i]
    if lds[seg.linedef].back != -1:
        continue
    rng = rm.wall_x_range(sp.x, sp.y, sp.angle, seg, verts)
    if rng is None:
        continue
    x1, x2, rwa = rng
    nrm, rwd = rm.wall_setup(sp.x, sp.y, seg, verts)
    scale = rm.scale_from_global_angle((sp.angle + rm.xtoviewangle[x1]) & ANGLE_MASK,
                                       sp.angle, nrm, rwd)
    if x2 > x1:
        s2 = rm.scale_from_global_angle((sp.angle + rm.xtoviewangle[x2]) & ANGLE_MASK,
                                        sp.angle, nrm, rwd)
        d, span = s2 - scale, x2 - x1
        step = -(abs(d) // span) if d < 0 else d // span
    else:
        step = 0
    sec = rm._seg_sector(lds, sds, secs, seg)
    for x in range(x1, x2):
        if 0 <= x < W and not drawn[x]:
            top, bottom = rm.wall_screen_span(sec.ceil_h, sec.floor_h, viewz, scale & ANGLE_MASK)
            top = max(0, top); bottom = min(H - 1, bottom)
            cols.append((x, seg_i, top, bottom, scale & ANGLE_MASK, sec))
            drawn[x] = 1
        scale = (scale + step) & ANGLE_MASK

# ---- ditto structure (adjacent, same-seg, same clip rows)
emit_cols, ditto_cols = [], 0
prev = None
for (x, si, top, bot, sc, sec) in cols:
    key = (si, top, bot)
    if prev is not None and prev[0] == x - 1 and prev[1] == key:
        ditto_cols += 1
    else:
        emit_cols.append((x, si, top, bot, sc, sec))
    prev = (x, key)
print(f"claimed columns {len(cols)}   emitting {len(emit_cols)}   ditto {ditto_cols}")

wall_rows = sum(max(0, b - t + 1) for _, _, t, b, _, _ in emit_cols)
print(f"wall rows over emitting columns: {wall_rows}  "
      f"(mean {wall_rows / max(1,len(emit_cols)):.1f}/col)")

# ---- W2-tile: exact DOOM v-DDA texel-change runs
def w2_runs(top, bottom, scale, sec):
    if top > bottom:
        return 0
    worldtop = sec.ceil_h - (vzs >> 16)
    iscale = rm._recip_div32(scale) // ds
    texturemid = (worldtop << 16) // ds
    frac = texturemid + (top - CY) * iscale
    f = (frac >> 8) & 0xFFFF
    st = (iscale >> 8) & 0xFFFF
    runs, cur = 0, None
    for _ in range(bottom - top + 1):
        t = (f >> 8) & 15
        if t != cur:
            runs += 1; cur = t
        f = (f + st) & 0xFFFF
    return runs

tile_runs = sum(w2_runs(t, b, sc, sec) for _, _, t, b, sc, sec in emit_cols)
stretch_runs = sum(min(16, max(0, b - t + 1)) for _, _, t, b, _, _ in emit_cols)
print(f"W2-tile   wall pairs: {tile_runs}   (vs 1/col today = {len(emit_cols)})")
print(f"W2-stretch wall pairs: {stretch_runs}")

# ---- current ceiling/floor band pairs (from the baked bank shape)
def band_pairs(ph, light, lo, hi):
    if hi <= lo:
        return 0
    zid = rm._zidx_band_walk(ph, list(range(lo, hi)))
    lvl = max(0, min(15, light >> 4))
    seq = [rm.zlight[lvl][z] for z in zid]
    n, cur = 0, None
    for s in seq:
        if s != cur:
            n += 1; cur = s
    return n

cpairs = fpairs = 0
for _, _, t, b, _, sec in emit_cols:
    phc = abs((sec.ceil_h << 16) - vzs); phf = abs((sec.floor_h << 16) - vzs)
    cpairs += band_pairs(phc, sec.light, 0, max(0, min(t, H)))
    fpairs += band_pairs(phf, sec.light, min(H, b + 1), H)
print(f"ceiling band pairs {cpairs}   floor band pairs {fpairs}   "
      f"TOTAL pairs today ~{cpairs + fpairs + len(emit_cols)}")

# ---- floor rows available for a texture pass
floor_rows = sum(max(0, H - (b + 1)) for _, _, _, b, _, _ in emit_cols)
ceil_rows = sum(max(0, min(t, H)) for _, _, t, _, _, _ in emit_cols)
print(f"ceiling rows {ceil_rows}   floor rows {floor_rows}")
for K in (2, 4, 8):
    print(f"  floor+ceil pairs if each band splits every {K} rows: "
          f"~{(ceil_rows + floor_rows) // K}")

# ---- W2-stretch with RUN-MERGED strips (the shipping candidate)
from doomfj.reference_model import COLORMAP_LIGHTS, LIGHT_SHIFT
colormap = wad.colormap(); _cache = {}
def strip_runs(sec, seg):
    ld = lds[seg.linedef]; sd = sds[ld.front if seg.side == 0 else ld.back]
    t = rm._wall_texture(wad, sd.middle, _cache, wall_mode="W2")
    lr = max(0, min(COLORMAP_LIGHTS - 1, sec.light >> LIGHT_SHIFT))
    if t is None:
        return [(16, colormap[lr][0])]
    texels, th, tw = t
    cols = [colormap[lr][texels[i]] for i in range(min(16, len(texels)))]
    runs, cur = [], None
    for j, c in enumerate(cols):
        if c != cur:
            runs.append([j + 1, c]); cur = c
        else:
            runs[-1][0] = j + 1
    return runs

tot = 0
for (x, si, top, bot, sc, sec) in emit_cols:
    h = bot - top + 1
    if h <= 0:
        continue
    prev_y, n = top, 0
    for cum, c in strip_runs(sec, cmap.segs[si]):
        y2 = top + ((cum * h) >> 4)
        if y2 > prev_y:
            n += 1; prev_y = y2
    tot += n
print(f"W2-stretch MERGED wall pairs: {tot}  (unmerged 929, today {len(emit_cols)})"
      f" -> delta {tot - len(emit_cols)} pairs ~ {(tot - len(emit_cols)) * 3.7e3 / 1e6:.2f}M")
