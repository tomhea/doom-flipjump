"""M13-2S rung 1: a HOST model of DOOM's two-sided wall clipping, to count the real populations
before any fj is written (R32: count on the real map first).

Walks the BSP front-to-back exactly like the fj renderer does, but keeps DOOM's per-column window
(ceilingclip/floorclip) instead of the 1-bit drawn[]. Reports, per viewpoint:
  - segs reaching the leaf / surviving the cheap culls / needing PROJECTION (the atan cost driver)
  - one-sided vs two-sided split of those
  - emitted runs, and how they'd split into 0x0B pairs
so the ops can be priced against the measured per-primitive costs before committing to a design.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doomfj.mapcompiler import NF_SUBSECTOR, bake_bsp
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ANGLE_MASK, ReferenceModel, build_scene, spawn_state
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
W, H = cfg.VIEW_W, cfg.VIEW_H


def study(mw, mapname, vx, vy, va, verbose=False):
    cmap = bake_bsp(mw, mapname)
    lds, sds, secs = mw.linedefs(mapname), mw.sidedefs(mapname), mw.sectors(mapname)
    verts = cmap.vertexes
    vx16, vy16 = vx << 16, vy << 16

    # the player's subsector floor sets viewz, as in the renderer
    ss_order = rm.bsp_render_order(cmap, vx, vy)
    ss = cmap.subsectors[ss_order[0]]
    viewz = rm.view_z(rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg]).floor_h)

    ceilclip = [-1] * W          # highest row NOT yet covered from the top (DOOM: ceilingclip)
    floorclip = [H] * W          # lowest row NOT yet covered from the bottom (DOOM: floorclip)
    stat = dict(leaf=0, culled=0, projected=0, proj_one=0, proj_two=0,
                runs=0, runs_one=0, runs_upper=0, runs_lower=0, cols_touched=0, closed_early=0)

    def window_open(x1, x2):
        return any(ceilclip[x] + 1 <= floorclip[x] - 1 for x in range(max(0, x1), min(W, x2)))

    order = []
    for ssi in ss_order:
        s = cmap.subsectors[ssi]
        order.extend(range(s.firstseg, s.firstseg + s.numsegs))

    for si in order:
        seg = cmap.segs[si]
        ld = lds[seg.linedef]
        stat["leaf"] += 1
        rng = rm.wall_x_range(vx16, vy16, va, seg, verts)      # the atan pair lives here
        if rng is None:
            stat["culled"] += 1
            continue
        x1, x2, _a1 = rng
        if not window_open(x1, x2):
            stat["closed_early"] += 1
            continue
        stat["projected"] += 1
        two = ld.back != -1
        stat["proj_two" if two else "proj_one"] += 1
        fsec = secs[sds[ld.front if seg.side == 0 else ld.back].sector]
        rw_norm, rw_dist = rm.wall_setup(vx16, vy16, seg, verts)
        bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector] if two else None
        for x in range(max(0, x1), min(W, x2)):
            if ceilclip[x] + 1 > floorclip[x] - 1:
                continue
            stat["cols_touched"] += 1
            scale = rm.scale_from_global_angle((va + rm.xtoviewangle[x]) & ANGLE_MASK, va,
                                              rw_norm, rw_dist) & ANGLE_MASK
            top, bot = rm.wall_screen_span(fsec.ceil_h, fsec.floor_h, viewz, scale)
            if not two:
                stat["runs"] += 1; stat["runs_one"] += 1
                ceilclip[x], floorclip[x] = H, -1          # solid: the column is finished
                continue
            # upper portion: front ceiling down to back ceiling
            if fsec.ceil_h > bsec.ceil_h:
                _t, ub = rm.wall_screen_span(fsec.ceil_h, bsec.ceil_h, viewz, scale)
                hi = max(top, ceilclip[x] + 1)
                lo = min(ub - 1, floorclip[x] - 1)
                if hi <= lo:
                    stat["runs"] += 1; stat["runs_upper"] += 1
                    ceilclip[x] = max(ceilclip[x], lo)
            else:
                ceilclip[x] = max(ceilclip[x], min(top - 1, floorclip[x] - 1))
            # lower portion: back floor down to front floor
            if bsec.floor_h > fsec.floor_h:
                lt, _b = rm.wall_screen_span(bsec.floor_h, fsec.floor_h, viewz, scale)
                hi = max(lt, ceilclip[x] + 1)
                lo = min(bot, floorclip[x] - 1)
                if hi <= lo:
                    stat["runs"] += 1; stat["runs_lower"] += 1
                    floorclip[x] = min(floorclip[x], hi)
            else:
                floorclip[x] = min(floorclip[x], max(bot + 1, ceilclip[x] + 1))
    return stat


mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle), (-480, 256, 0), (-309, 636, 0), (sx, sy, 0xE0000000)]
print("E1M1, DOOM two-sided clipping, front-to-back:")
print(" viewpoint                | leaf | culled | closed | PROJ | 1-sided | 2-sided | runs "
      "(solid/up/low)")
for vx, vy, va in VPS:
    s = study(mw, "E1M1", vx, vy, va)
    print(f" ({vx:5d},{vy:5d},{va:#010x}) | {s['leaf']:4d} | {s['culled']:6d} | "
          f"{s['closed_early']:6d} | {s['projected']:4d} | {s['proj_one']:7d} | {s['proj_two']:7d} "
          f"| {s['runs']:5d} ({s['runs_one']}/{s['runs_upper']}/{s['runs_lower']})")
