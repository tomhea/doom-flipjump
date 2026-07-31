"""V3 — prove the fj STORAGE MODEL before spending a build on it.

fj cannot keep the oracle's `ups[x] = (t0, ub-1, fsec, units)` tuple: a slot is BYTES, and t0/ub-1
are SIGNED rows that can sit off-screen on either side. So the fj slot stores
`[y1 clamped to 0..H-1][y2 clamped to 0..H-1][colour class]` plus a "written" bit, and decides
emptiness AT STORE TIME. This script checks that rewrite paints the identical pixels, i.e. that

    valid  <=>  (A <= B) and (B >= 0) and (A <= H-1)
    store  =    (max(A,0), min(B,H-1))

is equivalent to the oracle's "store raw, clip at splice time" for EVERY face at every viewpoint --
and that the clipped run always lands inside the region the emit walk will be in the middle of
(ceiling [0,ctake) for an upper face, floor [fstart,H) for a lower one), which is what keeps the
emitted column MONOTONE.
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
from doomfj.config import Config, PNEAR_SEG_BUDGET
from doomfj.fixedpoint import _signed
from doomfj.reference_model import (ANGLE_MASK, STEP_FACE_BASE, STEP_SEG_BUDGET, ReferenceModel,
                                    SimState, build_scene, spawn_state)
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
scene = build_scene(mw, mw, "E1M1")
colormap = mw.colormap()
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle, "spawn"), (1400, 1200, 0, "courtyard"), (-309, -44, 0, "worst"),
       (-480, 256, 0, "vp4"), (2432, 1344, 3221225472, "vp5")]
W, H = cfg.VIEW_W, cfg.VIEW_H
lds = scene.map_wad.linedefs("E1M1")
sds = scene.map_wad.sidedefs("E1M1")
secs = scene.map_wad.sectors("E1M1")
verts = scene.cmap.vertexes


def oracle_faces(vx, vy, va):
    """Re-run render_wall_frame's two-sided half verbatim, returning (ups, los, planes)."""
    state = SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1")
    viewx, viewy, viewangle = state.x, state.y, state.angle
    px, py = _signed(state.x, 32) >> 16, _signed(state.y, 32) >> 16
    pss = scene.cmap.subsectors[rm.point_in_subsector(scene.cmap, px, py)]
    viewz = rm.view_z(rm._seg_sector(lds, sds, secs, scene.cmap.segs[pss.firstseg]).floor_h)
    planes: list = []
    rm.render_wall_frame(state, scene, wall_mode="WPX", floor_mode_ft1=True, plane_near=True,
                         wall_noise=True, sky=True, near_steps=True, planes_out=planes)
    # ... and re-derive ups/los with the SAME logic (render_wall_frame does not export them)
    drawn = bytearray(W); pclaim = bytearray(W)
    ups = [None] * W; los = [None] * W
    n_face = 0; n_claimed = 0; n_ts = 0
    for seg_i in rm.visible_segs(scene.cmap, px, py):
        seg = scene.cmap.segs[seg_i]
        ld = lds[seg.linedef]
        if ld.back != -1:
            fsec = rm._seg_sector(lds, sds, secs, seg)
            bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
            if ((fsec.ceil_h, fsec.light, fsec.ceil_tex) == (bsec.ceil_h, bsec.light, bsec.ceil_tex)
                    and (fsec.floor_h, fsec.light, fsec.floor_tex)
                    == (bsec.floor_h, bsec.light, bsec.floor_tex)):
                continue
            if n_claimed == W or n_ts >= PNEAR_SEG_BUDGET:
                continue
            n_ts += 1
            rng2 = rm.wall_x_range(viewx, viewy, viewangle, seg, verts)
            if rng2 is None:
                continue
            has_up = fsec.ceil_h > bsec.ceil_h
            has_lo = bsec.floor_h > fsec.floor_h
            face_seg = (has_up or has_lo) and n_face < STEP_SEG_BUDGET
            if face_seg:
                n_face += 1
                rwn2, rwd2 = rm.wall_setup(viewx, viewy, seg, verts)
                sc2 = rm.scale_from_global_angle(
                    (viewangle + rm.xtoviewangle[rng2[0]]) & ANGLE_MASK, viewangle, rwn2, rwd2)
                if rng2[1] > rng2[0]:
                    sc2b = rm.scale_from_global_angle(
                        (viewangle + rm.xtoviewangle[rng2[1]]) & ANGLE_MASK, viewangle, rwn2, rwd2)
                    d2, sp2 = sc2b - sc2, rng2[1] - rng2[0]
                    st2 = -(abs(d2) // sp2) if d2 < 0 else d2 // sp2
                else:
                    st2 = 0
            for x in range(rng2[0], rng2[1]):
                if face_seg and not drawn[x] and not (
                        (not has_up or ups[x]) and (not has_lo or los[x])):
                    sc2m = sc2 & ANGLE_MASK
                    if has_up and ups[x] is None:
                        t0, _b = rm.wall_screen_span(fsec.ceil_h, fsec.ceil_h, viewz, sc2m)
                        _t, ub = rm.wall_screen_span(fsec.ceil_h, bsec.ceil_h, viewz, sc2m)
                        if t0 <= ub - 1:
                            ups[x] = (t0, ub - 1, fsec, fsec.ceil_h - bsec.ceil_h)
                    if has_lo and los[x] is None:
                        lt, _b2 = rm.wall_screen_span(bsec.floor_h, fsec.floor_h, viewz, sc2m)
                        _t2, b0 = rm.wall_screen_span(fsec.floor_h, fsec.floor_h, viewz, sc2m)
                        if lt <= b0:
                            los[x] = (lt, b0, fsec, bsec.floor_h - fsec.floor_h)
                if not pclaim[x]:
                    pclaim[x] = 1; n_claimed += 1
                if face_seg:
                    sc2 = (sc2 + st2) & ANGLE_MASK
            continue
        rng = rm.wall_x_range(viewx, viewy, viewangle, seg, verts)
        if rng is None:
            continue
        x1, x2, _ = rng
        for x in range(x1, x2):
            if not drawn[x]:
                if not pclaim[x]:
                    pclaim[x] = 1; n_claimed += 1
                drawn[x] = 1
    return ups, los, planes[0], viewz


def fj_store(A, B):
    """The fj STORE rule: (written?, y1, y2). Emptiness is decided here, not at the splice."""
    if not (A <= B and B >= 0 and A <= H - 1):
        return None
    return (max(A, 0), min(B, H - 1))


bad = 0
for vx, vy, va, tag in VPS:
    ups, los, planes, viewz = oracle_faces(vx, vy, va)
    c_hi, f_lo = planes[0], planes[1]
    nu = nl = 0
    for x in range(W):
        ctake = c_hi[x] + 1                      # emit-side: ctake == cexcl == ceil_hi+1
        fstart = f_lo[x]
        # ---- upper ----
        o = None
        if ups[x] is not None:
            y1, y2, fsc, units = ups[x]
            a, b = max(y1, 0), min(y2, c_hi[x])
            if a <= b:
                lr = rm.wall_light_row(rm.wall_lightnum(fsc.light, 0), b - a + 1, max(1, units))
                o = (a, b, colormap[lr][STEP_FACE_BASE])
        f = None
        if ups[x] is not None:
            st = fj_store(ups[x][0], ups[x][1])
            if st is not None and ctake > 0:
                a, b = st[0], min(st[1], ctake - 1)
                if a <= b:
                    fsc, units = ups[x][2], ups[x][3]
                    lr = rm.wall_light_row(rm.wall_lightnum(fsc.light, 0), b - a + 1, max(1, units))
                    f = (a, b, colormap[lr][STEP_FACE_BASE])
        if o != f:
            bad += 1
            print(f"  !! {tag} col {x} UPPER oracle {o} vs fj {f}  (raw {ups[x][:2]}, ctake {ctake})")
        if f:
            nu += 1
            assert 0 <= f[0] <= f[1] < ctake, f"upper outside the ceiling region: {f} ctake {ctake}"
        # ---- lower ----
        o = None
        if los[x] is not None:
            y1, y2, fsc, units = los[x]
            a, b = max(y1, f_lo[x]), min(y2, H - 1)
            if a <= b:
                lr = rm.wall_light_row(rm.wall_lightnum(fsc.light, 0), b - a + 1, max(1, units))
                o = (a, b, colormap[lr][STEP_FACE_BASE])
        f = None
        if los[x] is not None:
            st = fj_store(los[x][0], los[x][1])
            if st is not None:
                a, b = max(st[0], fstart), st[1]
                if a <= b:
                    fsc, units = los[x][2], los[x][3]
                    lr = rm.wall_light_row(rm.wall_lightnum(fsc.light, 0), b - a + 1, max(1, units))
                    f = (a, b, colormap[lr][STEP_FACE_BASE])
        if o != f:
            bad += 1
            print(f"  !! {tag} col {x} LOWER oracle {o} vs fj {f}  (raw {los[x][:2]}, fstart {fstart})")
        if f:
            nl += 1
            assert fstart <= f[0] <= f[1] < H, f"lower outside the floor region: {f} fstart {fstart}"
    print(f"{tag:10s}: upper faces drawn {nu:3d}   lower {nl:3d}   mismatches so far {bad}")

print("\nSTORE MODEL", "OK -- byte-identical to the oracle splice" if bad == 0 else f"BROKEN ({bad})")
