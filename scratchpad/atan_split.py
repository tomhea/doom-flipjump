"""M13-EMIT rung 3: what share of the frame is point_to_angle? Measured by ADDING a second, dead
pair of vertex atans per seg -- everything downstream stays bit-identical, so the frames must come
out BYTE-EXACT and the delta is the atan cost alone."""
import sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT/"tests", ROOT/"src", ROOT): sys.path.insert(0, str(q))
import flipjump as fj
from doomfj.config import Config
from doomfj.fastrun import FjmRunner
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.stream_screen import StreamScreen
SRC=[ROOT/"src/fj"/f for f in ("fixed_point.fj","present.fj","projection.fj","frame_render.fj",
     "plane_render.fj","plane_bands.fj","stream_render.fj")]
cfg=Config(); rm=ReferenceModel(cfg)
mw=WadFile.from_path(str(ROOT/"tests/fixtures/freedoom_e1m1.wad"))
scene=build_scene(mw,mw,"E1M1")
sp=spawn_state(mw,"E1M1"); sx,sy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16
VPS=[(sx,sy,sp.angle),(-309,-44,0)]
want=[bytes(rm.render_wall_frame(SimState(vx<<16,vy<<16,va,"E1M1"),scene,floor_texturing=False,
                                 wall_mode="WPX",floor_mode_ft1=True,plane_near=True))
      for vx,vy,va in VPS]
for tag, ab in (("shipped                    ", frozenset()),
                ("+ the slope DIVIDE twice   ", frozenset({"slopetwice"})),
                ("+ the tantoangle READ twice", frozenset({"tabletwice"}))):
    t0=time.time()
    main=emit_wall_renderer(mw,"E1M1",cfg,asset_wad=mw,over_align=False,floor_mode="FT1",
                            wall_mode="WPX",raster_mode="lines",ablate=ab,plane_near=True)
    tmp=Path(tempfile.mkdtemp()); consts=cfg.emit_fj_consts(tmp/"fj_consts.fj")
    (tmp/"m.fj").write_text(main,encoding="utf-8")
    fj.assemble([consts.resolve(),*[p.resolve() for p in SRC],(tmp/"m.fj").resolve()],
                tmp/"m.fjm",memory_width=W,print_time=False)
    r=FjmRunner(tmp/"m.fjm")
    ops=[]
    for (vx,vy,va),exp in zip(VPS,want):
        s=StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
        ops.append(r.run(s))
        assert bytes(s.pixel_indices)==exp, f"FRAME CHANGED at ({vx},{vy},{va:#x}) -- the probe is not inert"
    print(f"{tag}: " + "  ".join(f"{o:,}" for o in ops) + f"   (build {time.time()-t0:.0f}s, frames byte-exact)", flush=True)
