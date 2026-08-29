"""V4 — dump ONE column's emitted pair list beside the oracle's run-list for the same column.

Runs against the CACHED binary (scratchpad/fjmcache), so this is seconds, not a build.
    python scratchpad/v4_col.py <viewpoint-tag> <col> [<col> ...]
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
from doomfj.config import Config
from doomfj.wireformat import encode_feed_mapunits
from doomfj.fastrun import FjmRunner
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from tests.fj.stream_screen import StreamScreen

cfg = Config()
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
art = WadFile.from_path('assets/freedoom1.wad')
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = {"spawn": (sx, sy, sp.angle), "courtyard": (1400, 1200, 0),
       "tree": (2432, 1344, 3221225472), "worst": (-309, -44, 0)}
tag = sys.argv[1] if len(sys.argv) > 1 else "worst"
COLS = [int(a) for a in sys.argv[2:]] or [119]
vx, vy, va = VPS[tag]


class DumpScreen(StreamScreen):
    def __init__(self, cols, **kw):
        super().__init__(**kw)
        self.want = set(cols)
        self.log: dict = {c: [] for c in cols}

    def _handle_collines_byte(self, byte):
        if self._cl_active and self._cl_x in self.want:
            if self._cl_pend is not None:
                self.log[self._cl_x].append((self._cl_pend, byte))
            elif byte == 0xFE:
                self.log[self._cl_x].append("DITTO(copy x-1)")
        super()._handle_collines_byte(byte)


fjm = sorted((ROOT / "scratchpad/fjmcache").glob("v4_*.fjm"),
             key=lambda p: p.stat().st_mtime)[-1]
print("binary:", fjm.name)
print(f"WARNING: picked newest v4_*.fjm by mtime ({fjm.name}); its build flags are NOT verified "
      "against this script's oracle settings -- a stale/differently-flagged cache diffs falsely")
scr = DumpScreen(COLS, stdin=encode_feed_mapunits(vx, vy, va))
try:
    ops = FjmRunner(fjm).run(scr)
except Exception as e:
    ops = -1
    print("device error:", e)

rm = ReferenceModel(cfg)
scene = build_scene(mw, mw, "E1M1")
want = rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"), scene,
                            wall_mode="WPX", floor_mode_ft1=True, plane_near=True,
                            wall_noise=True, sky=True, near_steps=True, things=True,
                            sprite_wad=art)


def runs(fb, x):
    out, prev, y0 = [], None, 0
    for y in range(cfg.VIEW_H):
        c = fb[y * cfg.VIEW_W + x]
        if prev is None:
            prev = c
        elif c != prev:
            out.append((y, prev)); prev = c
    out.append((cfg.VIEW_H, prev))
    return out


for c in COLS:
    print(f"\n=== {tag} column {c} ===")
    print(f"  ORACLE runs [y2,colour]: {runs(want, c)}")
    print(f"  FJ pairs    [y2,colour]: {scr.log[c]}")

# ---- what the fj's slot SHOULD hold for these columns, straight off the oracle ----
from doomfj.reference_model import (PNEAR_SEG_BUDGET, THING_BUDGET, THING_SPRITE, ANGLE_MASK,
                                    sprite_bucket, sprite_bucket_height)
lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
planes: list = []
rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"), scene,
                     wall_mode="WPX", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                     sky=True, near_steps=True, things=True, sprite_wad=art, planes_out=planes)
ceil_hi, floor_lo = planes[0][0], planes[0][1]
# re-derive the fragments the same way render_wall_frame does
viewx, viewy, viewangle = vx << 16, vy << 16, va
pss = scene.cmap.subsectors[rm.point_in_subsector(scene.cmap, vx, vy)]
viewz = rm.view_z(rm._seg_sector(lds, sds, secs, scene.cmap.segs[pss.firstseg]).floor_h)
drawn = bytearray(cfg.VIEW_W); sfrag = [None] * cfg.VIEW_W
cache: dict = {}; by: dict = {}; first: dict = {}
for t in mw.things("E1M1"):
    if THING_SPRITE.get(t.type) is None: continue
    by.setdefault(rm.point_in_subsector(scene.cmap, t.x, t.y), []).append(t)
for si, ss in enumerate(scene.cmap.subsectors):
    if ss.numsegs and si in by: first[ss.firstseg] = si
n_thing = 0; n_claimed = 0; pclaim = bytearray(cfg.VIEW_W)
for seg_i in rm.visible_segs(scene.cmap, vx, vy):
    if seg_i in first:
        for t in by[first[seg_i]]:
            if n_thing >= THING_BUDGET or n_claimed == cfg.VIEW_W: break
            a = rm.sprite_art(art, t.type, cache)
            if a is None: continue
            tss = scene.cmap.subsectors[first[seg_i]]
            ts = rm._seg_sector(lds, sds, secs, scene.cmap.segs[tss.firstseg])
            pr = rm.project_thing(viewx, viewy, viewangle, viewz, t.x, t.y, ts.floor_h, a)
            if pr is None: continue
            n_thing += 1
            x1, x2, ytop, h, istep = pr
            b = sprite_bucket(h, cfg.VIEW_H); hb = sprite_bucket_height(b, cfg.VIEW_H)
            y0b = ytop + h - hb
            frac = (max(0, x1) - x1) * istep
            for xx in range(max(0, x1), min(cfg.VIEW_W, x2 + 1)):
                u = min(a[2] - 1, max(0, frac >> 16)); frac += istep
                if drawn[xx] or sfrag[xx] is not None: continue
                st = rm.sprite_strip(a[0][u], a[1], hb)
                if st is None: continue
                sfrag[xx] = (y0b, st[0], st[1][-1][0], b, u, t.type, len(st[1]))
    seg = scene.cmap.segs[seg_i]
    if lds[seg.linedef].back != -1: continue
    rng = rm.wall_x_range(viewx, viewy, viewangle, seg, scene.cmap.vertexes)
    if rng is None: continue
    for xx in range(rng[0], rng[1]):
        if not drawn[xx]: drawn[xx] = 1
print()
for c in COLS:
    f = sfrag[c]
    ct = ceil_hi[c] + 1; fs = floor_lo[c]
    print(f"  col {c}: ctake={ct} fstart={fs}  fragment={f}")
    if f:
        y0, r0, lastrel, b, u, kind, nruns = f
        print(f"     -> y0={y0} r0={r0} lastrel={lastrel} bucket={b} u={u} kind={kind} nruns={nruns}"
              f"  sy1={max(y0+r0,0)} sy2p1={min(y0+lastrel, cfg.VIEW_H)} y0b={y0+128}")
