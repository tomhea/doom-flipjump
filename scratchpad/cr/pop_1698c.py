"""Trace every seg that touches column 108 (and 100) at the two viewpoints: walk order,
x-range, scales, screen rows -- find the phantom giant projection."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
import doomfj.reference_model as RMM
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile

cfg = Config()
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
lds, sds = mw.linedefs("E1M1"), mw.sidedefs("E1M1")
verts = scene.cmap.vertexes
VA = 0x20000000
XWATCH = (100, 108)


class TraceModel(ReferenceModel):
    def wall_x_range(self, *a, **k):
        r = super().wall_x_range(*a, **k)
        self._last_xr = r
        return r


tm = TraceModel(cfg)
LOG = []
_orig_scale = ReferenceModel.scale_from_global_angle


for tag, (vx, vy) in {"FAR": (1698, 892), "NEAR": (1715, 909)}.items():
    # walk the BSP exactly like the renderer, computing each seg's projection ourselves
    order = list(tm.visible_segs(scene.cmap, vx, vy, va=VA))
    print(f"\n=== {tag} ({vx},{vy}) -- segs touching x in {XWATCH} (walk order) ===")
    for si in order:
        seg = scene.cmap.segs[si]
        ld = lds[seg.linedef]
        xr = tm.wall_x_range(vx << 16, vy << 16, VA, seg, verts)
        if xr is None:
            continue
        x1, x2 = xr[0], xr[1]
        if not any(x1 <= xw <= x2 for xw in XWATCH):
            continue
        two = ld.back != -1 and ld.front != -1
        rwn, rwd = tm.wall_setup(vx << 16, vy << 16, seg, verts)
        # scale at the watch column(s)
        sc = {}
        for xw in XWATCH:
            if x1 <= xw <= x2:
                visang = (VA + tm.xtoviewangle[xw]) & 0xFFFFFFFF
                sc[xw] = tm.scale_from_global_angle(visang, VA, rwn, rwd)
        v1, v2 = verts[seg.v1], verts[seg.v2]
        mid = sds[ld.front if seg.side == 0 else ld.back].middle if (ld.front if seg.side == 0 else ld.back) != -1 else "?"
        print(f"  seg{si:4} {'2S' if two else '1S'} mid={mid!r:10} v1={v1} v2={v2} "
              f"x[{x1},{x2}] rwd={rwd >> 16} scales={ {k: hex(v) for k, v in sc.items()} }")
