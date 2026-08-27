"""Phase 2 prototype — distance-bucketed floor oracle, tuned empirically (PNG + diff%).

Captures the per-column plane arrays from render_wall_frame (textured) via a monkeypatch, then
re-renders the planes with a BUCKETED u,v sample: per band b, precompute spot_table[b][x] (the
continuous perspective DDA at the band's representative distance); per span, band = band_of(distance)
(keeps ONE fixed_mul/span), per pixel read spot_table[band][x]. Only the u,v sample is bucketed;
the per-span distance + zlight lighting stay exact. Prints distance histogram + diff% vs textured,
and writes PNGs for visual inspection.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from doomfj.config import Config
from doomfj.fixedpoint import fixed_mul
from doomfj.reference_model import (ReferenceModel, SimState, build_scene, spawn_state,
                                    ANG90, ANGLE_MASK)
from doomfj.fixedpoint import fixed_div
from doomfj.wad import WadFile

E1M1 = "tests/fixtures/freedoom_e1m1.wad"
ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"


def capture_planes(rm, state, scene):
    """Run render_wall_frame (textured) but capture the planes args + the reference frame."""
    cap = {}
    orig = rm._render_planes_textured

    def spy(fb, colormap, asset_wad, flatcache, viewx, viewy, viewangle, viewz, *planes):
        cap['args'] = (colormap, asset_wad, flatcache, viewx, viewy, viewangle, viewz, planes)
        return orig(fb, colormap, asset_wad, flatcache, viewx, viewy, viewangle, viewz, *planes)

    rm._render_planes_textured = spy
    ref = rm.render_wall_frame(state, scene)
    rm._render_planes_textured = orig
    return ref, cap['args']


def render_bucketed(rm, args, B, SHIFT, fb_walls):
    """Bucketed plane raster. fb_walls = the frame with walls already painted (we overwrite plane px)."""
    cfg = rm.cfg
    W, H = cfg.VIEW_W, cfg.VIEW_H
    colormap, asset_wad, flatcache, viewx, viewy, viewangle, viewz, planes = args
    ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff = planes
    fb = bytearray(fb_walls)

    cxfrac = cfg.CENTERX << 16
    ang_b = ((viewangle - ANG90) & ANGLE_MASK) >> rm.angle_shift
    basexscale = fixed_div(rm._finecos_idx(ang_b), cxfrac, 8, 4)
    baseyscale = (-fixed_div(rm._finesin_idx(ang_b), cxfrac, 8, 4)) & ANGLE_MASK
    viewx32, viewy32 = viewx & 0xFFFFFFFF, viewy & 0xFFFFFFFF

    # LOG (block-floating-point) bucket: band = exponent (bit-length) * 2^MANT | top MANT mantissa bits.
    # SHIFT carries MANT here; B is unused (bands = exponent range * 2^MANT). Distances span ~22..29 bits.
    MANT = SHIFT

    def band_of(d):
        if d <= 0:
            return 0
        e = d.bit_length()                       # 1..29
        if e <= MANT:
            return d                              # tiny: identity-ish (won't happen; min dist ~22-bit)
        mant = (d >> (e - 1 - MANT)) & ((1 << MANT) - 1)
        return (e << MANT) | mant

    def rep_dist(b):
        e = b >> MANT
        mant = b & ((1 << MANT) - 1)
        if e <= MANT:
            return max(1, b)
        base = (1 << (e - 1)) | (mant << (e - 1 - MANT))
        half = 1 << (e - 2 - MANT) if e - 2 - MANT >= 0 else 0
        return base + half                       # band midpoint (block-FP)

    # spot_table[band][x] — continuous DDA across the row at the band's rep distance (lazy per band)
    spot_table = {}

    def build_band(b):
        d = rep_dist(b)
        xstep = fixed_mul(d, basexscale, 8, 4)
        ystep = fixed_mul(d, baseyscale, 8, 4)
        length = fixed_mul(d, rm.distscale[0], 8, 4)
        idx = ((viewangle + rm.xtoviewangle[0]) & ANGLE_MASK) >> rm.angle_shift
        xfrac = (viewx32 + fixed_mul(rm._finecos_idx(idx), length, 8, 4)) & 0xFFFFFFFF
        yfrac = (-viewy32 - fixed_mul(rm._finesin_idx(idx), length, 8, 4)) & 0xFFFFFFFF
        row = [0] * W
        for x in range(W):
            row[x] = ((yfrac >> 10) & 4032) + ((xfrac >> 16) & 63)
            xfrac = (xfrac + xstep) & 0xFFFFFFFF
            yfrac = (yfrac + ystep) & 0xFFFFFFFF
        spot_table[b] = row
        return row

    dist_samples = []
    for y in range(H):
        x = 0
        while x < W:
            region = rm._plane_region_at(x, y, ceil_hi, floor_lo)
            if region is None:
                x += 1
                continue
            ch, cf = (col_ch, col_cf) if region == 'c' else (col_fh, col_ff)
            height, flat, light = ch[x], cf[x], col_lt[x]
            x2 = x
            while x2 + 1 < W and rm._plane_region_at(x2 + 1, y, ceil_hi, floor_lo) == region \
                    and ch[x2 + 1] == height and cf[x2 + 1] == flat and col_lt[x2 + 1] == light:
                x2 += 1
            planeheight = abs((height << 16) - viewz)
            distance = fixed_mul(planeheight, rm.yslope[y], 8, 4)
            dist_samples.append(distance)
            b = band_of(distance)
            srow = spot_table.get(b) or build_band(b)
            row = colormap[rm.plane_light_row(light, distance)]
            texels = rm._flat_texels(asset_wad, flat, flatcache)
            for xx in range(x, x2 + 1):
                fb[y * W + xx] = row[texels[srow[xx]]]
            x = x2 + 1
    return bytes(fb), dist_samples


def save_png(frame, palette_rgb, path, W, H):
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = palette_rgb[frame[y * W + x]]
        # nearest-neighbor 3x upscale for visibility
    img = img.resize((W * 3, H * 3), Image.NEAREST)
    img.save(path)


def main():
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1)
    scene = build_scene(mw, mw, "E1M1")
    state = spawn_state(mw, "E1M1")
    W, H = cfg.VIEW_W, cfg.VIEW_H

    palette_rgb = [tuple(c) for c in mw.playpal()[:256]]

    ref, args = capture_planes(rm, state, scene)

    # walls-only frame (planes blanked) to overpaint: re-run with flat-colored OFF is messy; instead
    # take ref and let bucketed overwrite every plane pixel (walls are disjoint from plane rows).
    out = Path(__file__).resolve().parent
    save_png(ref, palette_rgb, out / "ref_textured.png", W, H)

    # distance histogram (one band scheme to collect samples)
    _, dist = render_bucketed(rm, args, 16, 16, ref)
    dist.sort()
    n = len(dist)
    print(f"floor/ceil spans: {n}; distance min={dist[0]} max={dist[-1]} "
          f"med={dist[n//2]} p10={dist[n//10]} p90={dist[9*n//10]}")
    print(f"  max>>16={dist[-1]>>16}  max>>20={dist[-1]>>20}  bits={dist[-1].bit_length()}")

    for MANT in [2, 3, 4, 5, 6]:                  # bands/octave = 2^MANT; ~8 octaves of distance
        got, _ = render_bucketed(rm, args, 0, MANT, ref)
        diff = sum(1 for a, b in zip(got, ref) if a != b)
        nb = len({band_of_static(d, MANT) for d in dist})
        print(f"MANT={MANT} (={2**MANT}/octave, {nb} bands used): diff {diff:5d}/{W*H} ({100*diff/(W*H):.1f}%)")
        save_png(got, palette_rgb, out / f"bucket_logM{MANT}.png", W, H)


def band_of_static(d, MANT):
    if d <= 0:
        return 0
    e = d.bit_length()
    if e <= MANT:
        return d
    mant = (d >> (e - 1 - MANT)) & ((1 << MANT) - 1)
    return (e << MANT) | mant


if __name__ == "__main__":
    main()
