"""M13-2S rung 1: HOST prototype of DOOM's full two-sided wall + per-column plane-region model.

Not the oracle yet -- a throwaway to see the LOOK and confirm the algorithm before touching
reference_model. Mirrors R_RenderSegLoop: walk front-to-back keeping per-column ceilingclip /
floorclip, and for each seg paint, in this order,
    front-sector CEILING plane region | upper wall | (opening) | lower wall | FLOOR plane region
narrowing the window from both ends. A one-sided seg closes the column.

Planes use the simple flat-colour tier (not FT1) -- enough to judge legibility, and far less code.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import (ANGLE_MASK, LIGHTLEVELS, LIGHTSEGSHIFT, WALL_BG,
                                    ReferenceModel, spawn_state)
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
W, H = cfg.VIEW_W, cfg.VIEW_H
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
cmap = bake_bsp(mw, "E1M1")
lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
verts = cmap.vertexes
colormap = mw.colormap()
pal = mw.playpal()
texcache, flatcache = {}, {}


def render(vx, vy, va, two_sided=True):
    fb = bytearray(W * H)
    vx16, vy16 = vx << 16, vy << 16
    pss = cmap.subsectors[rm.point_in_subsector(cmap, vx, vy)]
    viewz = rm.view_z(rm._seg_sector(lds, sds, secs, cmap.segs[pss.firstseg]).floor_h)
    ceilclip = [-1] * W
    floorclip = [H] * W
    stats = dict(upper=0, lower=0, solid=0, cplane=0, fplane=0)

    def plane(x, y1, y2, sec, is_ceil):
        """flat-colour plane region: the flat's base index, distance-lit per row."""
        base = rm._flat_base(mw, sec.ceil_tex if is_ceil else sec.floor_tex, flatcache)
        ph = abs(((sec.ceil_h if is_ceil else sec.floor_h) << 16) - viewz)
        for y in range(max(0, y1), min(H, y2 + 1)):
            fb[y * W + x] = rm._plane_pixel(colormap, ph, sec.light, base, y)

    def wallrun(x, y1, y2, texname, sec, wall_units):
        """a WPX 1x1-textured wall run over rows [y1,y2], scalelight-shaded like the shipped tier."""
        y1, y2 = max(0, y1), min(H - 1, y2)
        if y1 > y2:
            return
        h = y2 - y1 + 1
        tex = rm._wall_texture(mw, texname, texcache, wall_mode="WPX")
        texels, th, tw = tex if tex is not None else (None, 0, 0)
        ct = rm.wall_lightnum(sec.light, 0)
        lr = rm.wall_light_row(ct, h, max(1, wall_units))
        ya = y1
        for rel, c in rm.wpx_strip(texels, th, tw, colormap, lr, h):
            for y in range(ya, min(y1 + rel, y2 + 1)):
                fb[y * W + x] = c
            ya = y1 + rel

    for ssi in rm.bsp_render_order(cmap, vx, vy):
        ss = cmap.subsectors[ssi]
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            seg = cmap.segs[si]
            ld = lds[seg.linedef]
            two = ld.back != -1
            if two and not two_sided:
                continue
            sd = sds[ld.front if seg.side == 0 else ld.back]
            fsec = secs[sd.sector]
            bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector] if two else None
            if two and not (fsec.ceil_h > bsec.ceil_h or bsec.floor_h > fsec.floor_h):
                continue                                  # baked: this seg can never draw
            rng = rm.wall_x_range(vx16, vy16, va, seg, verts)
            if rng is None:
                continue
            x1, x2, _ = rng
            rw_norm, rw_dist = rm.wall_setup(vx16, vy16, seg, verts)
            for x in range(max(0, x1), min(W, x2)):
                if ceilclip[x] + 1 > floorclip[x] - 1:
                    continue
                scale = rm.scale_from_global_angle((va + rm.xtoviewangle[x]) & ANGLE_MASK, va,
                                                  rw_norm, rw_dist) & ANGLE_MASK
                top, bot = rm.wall_screen_span(fsec.ceil_h, fsec.floor_h, viewz, scale)
                # --- front sector's ceiling plane region, above this seg's ceiling
                c_hi, c_lo = ceilclip[x] + 1, min(top - 1, floorclip[x] - 1)
                if c_hi <= c_lo:
                    plane(x, c_hi, c_lo, fsec, True); stats["cplane"] += 1
                    ceilclip[x] = c_lo
                # --- front sector's floor plane region, below this seg's floor
                f_lo, f_hi = floorclip[x] - 1, max(bot + 1, ceilclip[x] + 1)
                if f_hi <= f_lo:
                    plane(x, f_hi, f_lo, fsec, False); stats["fplane"] += 1
                    floorclip[x] = f_hi
                win_hi, win_lo = ceilclip[x] + 1, floorclip[x] - 1
                if win_hi > win_lo:
                    continue
                if not two:
                    wallrun(x, max(top, win_hi), min(bot, win_lo), sd.middle, fsec,
                            fsec.ceil_h - fsec.floor_h)
                    stats["solid"] += 1
                    ceilclip[x], floorclip[x] = H, -1     # column finished
                    continue
                if fsec.ceil_h > bsec.ceil_h:             # upper wall (door lintel / step down)
                    _t, ub = rm.wall_screen_span(fsec.ceil_h, bsec.ceil_h, viewz, scale)
                    lo = min(ub - 1, win_lo)
                    if win_hi <= lo:
                        wallrun(x, win_hi, lo, sd.upper, fsec, fsec.ceil_h - bsec.ceil_h)
                        stats["upper"] += 1
                        ceilclip[x] = lo
                        win_hi = lo + 1
                if bsec.floor_h > fsec.floor_h:           # lower wall (step / ledge face)
                    lt, _b = rm.wall_screen_span(bsec.floor_h, fsec.floor_h, viewz, scale)
                    hi = max(lt, win_hi)
                    if hi <= win_lo:
                        wallrun(x, hi, win_lo, sd.lower, fsec, bsec.floor_h - fsec.floor_h)
                        stats["lower"] += 1
                        floorclip[x] = hi
    # anything still open at the end: leave it (shows as black -- the sky / unclosed window)
    return bytes(fb), stats


sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle), (-480, 256, 0), (-309, 636, 0)]
S, LBL = 3, 22
sheet = Image.new("RGB", (W * S * len(VPS), (H * S + LBL) * 2), (16, 16, 18))
d = ImageDraw.Draw(sheet)
for r, (lab, ts) in enumerate([("NOW: one-sided walls only (72% of surfaces skipped)", False),
                               ("WITH two-sided upper/lower walls + plane regions", True)]):
    for c, (a, b, ang) in enumerate(VPS):
        fbb, st = render(a, b, ang, two_sided=ts)
        im = Image.new("RGB", (W, H)); im.putdata([pal[p] for p in fbb])
        sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (c * W * S, r * (H * S + LBL) + LBL))
        if c == 0:
            print(f"{lab[:42]:42s} runs: solid {st['solid']:4d} upper {st['upper']:4d} "
                  f"lower {st['lower']:4d} | plane regions c/f {st['cplane']:4d}/{st['fplane']:4d}",
                  flush=True)
    d.text((6, r * (H * S + LBL) + 6), lab, fill=(235, 235, 240))
sheet.save(ROOT / "scratchpad/twosided_proto.png")
print("scratchpad/twosided_proto.png written")
