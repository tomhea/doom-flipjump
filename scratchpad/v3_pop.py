"""V3 — the POPULATIONS the fj step-face path will pay for, counted off the oracle.

The handoff prices V3 from unit costs (93k per face-seg setup, 11.9k per column projection) but
never counted the columns those multiply by. This does, at both gate viewpoints, and it also
answers the design question that decides the fj shape: does the oracle's per-column
`scale_from_global_angle` have to stay, or can the face path use the SAME scale/scalestep DDA the
wall path already runs (interpolation is what DOOM itself does, and what fj can afford)?
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
from doomfj.config import Config, PNEAR_SEG_BUDGET
from doomfj.fixedpoint import _signed
from doomfj.reference_model import (ANGLE_MASK, STEP_SEG_BUDGET, ReferenceModel, SimState,
                                    build_scene, spawn_state)
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle, "spawn"), (1400, 1200, 0, "courtyard"), (-309, -44, 0, "worst")]

lds = scene.map_wad.linedefs("E1M1")
sds = scene.map_wad.sidedefs("E1M1")
secs = scene.map_wad.sectors("E1M1")
verts = scene.cmap.vertexes
W, H = cfg.VIEW_W, cfg.VIEW_H


def count(vx, vy, va):
    state = SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1")
    viewx, viewy, viewangle = state.x, state.y, state.angle
    px, py = _signed(state.x, 32) >> 16, _signed(state.y, 32) >> 16
    pss = scene.cmap.subsectors[rm.point_in_subsector(scene.cmap, px, py)]
    viewz = rm.view_z(rm._seg_sector(lds, sds, secs, scene.cmap.segs[pss.firstseg]).floor_h)

    drawn = bytearray(W); pclaim = bytearray(W)
    ups = [None] * W; los = [None] * W
    n_face = 0; n_claimed = 0; n_ts = 0
    stats = dict(face_segs=0, face_cols=0, face_cols_drawn=0, face_cols_full=0, proj_cols=0,
                 proj_calls=0, u_written=0, l_written=0, interp_mismatch=0, interp_rows=0)
    classes = set()
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
                stats["face_segs"] += 1
                rwn2, rwd2 = rm.wall_setup(viewx, viewy, seg, verts)
                if has_up:
                    classes.add((rm.wall_lightnum(fsec.light, 0), max(1, fsec.ceil_h - bsec.ceil_h)))
                if has_lo:
                    classes.add((rm.wall_lightnum(fsec.light, 0), max(1, bsec.floor_h - fsec.floor_h)))
                # the INTERPOLATED scale (wall_scale_setup_m + the pass-2 DDA), for comparison
                isc = rm.scale_from_global_angle((viewangle + rm.xtoviewangle[rng2[0]]) & ANGLE_MASK,
                                                 viewangle, rwn2, rwd2)
                if rng2[1] > rng2[0]:
                    s2 = rm.scale_from_global_angle((viewangle + rm.xtoviewangle[rng2[1]]) & ANGLE_MASK,
                                                    viewangle, rwn2, rwd2)
                    d, sp2 = s2 - isc, rng2[1] - rng2[0]
                    istep = -(abs(d) // sp2) if d < 0 else d // sp2
                else:
                    istep = 0
            for x in range(rng2[0], rng2[1]):
                if face_seg:
                    stats["face_cols"] += 1
                    if drawn[x]:
                        stats["face_cols_drawn"] += 1
                    elif (not has_up or ups[x]) and (not has_lo or los[x]):
                        stats["face_cols_full"] += 1
                if face_seg and not drawn[x] and not (
                        (not has_up or ups[x]) and (not has_lo or los[x])):
                    stats["proj_cols"] += 1
                    sc2 = rm.scale_from_global_angle(
                        (viewangle + rm.xtoviewangle[x]) & ANGLE_MASK, viewangle, rwn2, rwd2) & ANGLE_MASK
                    sci = isc & ANGLE_MASK
                    if has_up and ups[x] is None:
                        stats["proj_calls"] += 1
                        t0, _b = rm.wall_screen_span(fsec.ceil_h, fsec.ceil_h, viewz, sc2)
                        _t, ub = rm.wall_screen_span(fsec.ceil_h, bsec.ceil_h, viewz, sc2)
                        it0, _ = rm.wall_screen_span(fsec.ceil_h, fsec.ceil_h, viewz, sci)
                        _, iub = rm.wall_screen_span(fsec.ceil_h, bsec.ceil_h, viewz, sci)
                        stats["interp_rows"] += 2
                        stats["interp_mismatch"] += (it0 != t0) + (iub != ub)
                        if t0 <= ub - 1:
                            ups[x] = (t0, ub - 1, fsec, fsec.ceil_h - bsec.ceil_h)
                            stats["u_written"] += 1
                    if has_lo and los[x] is None:
                        stats["proj_calls"] += 1
                        lt, _b2 = rm.wall_screen_span(bsec.floor_h, fsec.floor_h, viewz, sc2)
                        _t2, b0 = rm.wall_screen_span(fsec.floor_h, fsec.floor_h, viewz, sc2)
                        ilt, _ = rm.wall_screen_span(bsec.floor_h, fsec.floor_h, viewz, sci)
                        _, ib0 = rm.wall_screen_span(fsec.floor_h, fsec.floor_h, viewz, sci)
                        stats["interp_rows"] += 2
                        stats["interp_mismatch"] += (ilt != lt) + (ib0 != b0)
                        if lt <= b0:
                            los[x] = (lt, b0, fsec, bsec.floor_h - fsec.floor_h)
                            stats["l_written"] += 1
                if not pclaim[x]:
                    pclaim[x] = 1
                    n_claimed += 1
                if face_seg:
                    isc = (isc + istep) & ANGLE_MASK
            continue
        rng = rm.wall_x_range(viewx, viewy, viewangle, seg, verts)
        if rng is None:
            continue
        x1, x2, rw_angle1 = rng
        rw_normalangle, rw_distance = rm.wall_setup(viewx, viewy, seg, verts)
        scale = rm.scale_from_global_angle((viewangle + rm.xtoviewangle[x1]) & ANGLE_MASK,
                                           viewangle, rw_normalangle, rw_distance)
        if x2 > x1:
            scale2 = rm.scale_from_global_angle((viewangle + rm.xtoviewangle[x2]) & ANGLE_MASK,
                                                viewangle, rw_normalangle, rw_distance)
            diff, span = scale2 - scale, x2 - x1
            scalestep = -(abs(diff) // span) if diff < 0 else diff // span
        else:
            scalestep = 0
        sec = rm._seg_sector(lds, sds, secs, seg)
        for x in range(x1, x2):
            if not drawn[x]:
                if not pclaim[x]:
                    pclaim[x] = 1; n_claimed += 1
                drawn[x] = 1
            scale = (scale + scalestep) & ANGLE_MASK
    stats["cols_with_u"] = sum(1 for v in ups if v)
    stats["cols_with_l"] = sum(1 for v in los if v)
    stats["cols_with_any"] = sum(1 for u, l in zip(ups, los) if u or l)
    return stats, classes


allcls = set()
for vx, vy, va, tag in VPS:
    st, cls = count(vx, vy, va)
    allcls |= cls
    print(f"\n=== {tag} ({vx},{vy}) ===")
    for k, v in st.items():
        print(f"   {k:20s} {v}")
print(f"\ndistinct (lightnum, units) face classes seen: {len(allcls)}")
print(sorted(allcls))
