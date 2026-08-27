"""Where do rung 3b's ops go? full vs no-flush vs no-walk, E1M1 spawn."""
import sys, tempfile, time
from pathlib import Path
ROOT=Path('.').resolve()
for q in (ROOT/"tests", ROOT/"src", ROOT): sys.path.insert(0,str(q))
import flipjump as fj
from doomfj.config import Config
from doomfj.fastrun import FjmRunner
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.stream_screen import StreamScreen
SRC=[ROOT/"src/fj"/f for f in ("fixed_point.fj","present.fj","projection.fj","frame_render.fj",
     "plane_render.fj","plane_bands.fj","stream_render.fj")]
cfg=Config(); mw=WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
sp=spawn_state(mw,"E1M1"); sx,sy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16
for tag,ab in (("everything but the per-column body",frozenset({"noflush","colstub"})),):
    t0=time.time()
    main=emit_wall_renderer(mw,"E1M1",cfg,asset_wad=mw,over_align=False,floor_mode="FT1",
                            wall_mode="WPX",raster_mode="lines",two_sided=True,ablate=ab)
    tmp=Path(tempfile.mkdtemp()); consts=cfg.emit_fj_consts(tmp/"fj_consts.fj")
    (tmp/"m.fj").write_text(main,encoding="utf-8")
    fj.assemble([consts.resolve(),*[p.resolve() for p in SRC],(tmp/"m.fj").resolve()],tmp/"m.fjm",
                memory_width=W,print_time=False)
    r=FjmRunner(tmp/"m.fjm")
    ops=r.run(StreamScreen(stdin=f"{sx}\n{sy}\n{sp.angle}\n".encode()))
    print(f"{tag}: {ops:,}   (build {time.time()-t0:.0f}s)", flush=True)
