"""M13-2S rung 3b: square room first (one-sided only -- it exercises the clip window, the sub-range
band walks, the pair buffers and the flush, with no two-sided segs in the way)."""
import sys, tempfile
from pathlib import Path
ROOT=Path('.').resolve()
for q in (ROOT/"tests", ROOT/"src", ROOT): sys.path.insert(0,str(q))
import flipjump as fj
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.stream_screen import StreamScreen
SRC=[ROOT/"src/fj"/f for f in ("fixed_point.fj","present.fj","projection.fj","frame_render.fj",
     "plane_render.fj","plane_bands.fj","stream_render.fj")]
cfg=Config(); rm=ReferenceModel(cfg)
MAP=sys.argv[1] if len(sys.argv)>1 else "square"
if MAP=="square":
    mw=WadFile.from_path('tests/fixtures/square_room.wad'); aw=WadFile.from_path('tests/fixtures/freedoom_assets.wad')
    name="MAP01"; scene=build_scene(mw,aw,name)
    sp=spawn_state(mw,name); spx,spy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16
    A45=0x20000000
    VPS=[(spx,spy,sp.angle),(spx,spy,A45),(200,128,0),(128,128,A45),(24,24,A45)]
else:
    mw=WadFile.from_path('tests/fixtures/freedoom_e1m1.wad'); aw=mw
    name="E1M1"; scene=build_scene(mw,mw,name)
    sp=spawn_state(mw,name); spx,spy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16
    VPS=[(spx,spy,sp.angle),(spx,spy,(sp.angle+0x40000000)&0xFFFFFFFF)]
ABL=frozenset({"pass1"}) if len(sys.argv)>2 and sys.argv[2]=="noscan" else frozenset()
main=emit_wall_renderer(mw,name,cfg,asset_wad=aw,over_align=False,floor_mode="FT1",
                        wall_mode="WPX",raster_mode="lines",two_sided=True,ablate=ABL)
tmp=Path(tempfile.mkdtemp()); consts=cfg.emit_fj_consts(tmp/"fj_consts.fj")
(tmp/"m.fj").write_text(main,encoding="utf-8")
out=tmp/"m.fjm"
fj.assemble([consts.resolve(),*[p.resolve() for p in SRC],(tmp/"m.fj").resolve()],out,
            memory_width=W,print_time=False)
print("assembled", flush=True)
for vx,vy,va in VPS:
    s=StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    t=fj.run(out,io_device=s,print_time=False,print_termination=False,flat_max_words=1<<26)
    want=bytes(rm.render_frame_2s(SimState(vx<<16,vy<<16,va,name),scene))
    px=bytes(s.pixel_indices)
    diff=sum(1 for a,b in zip(px,want) if a!=b)
    print(f"  ({vx},{vy},{va:#010x}) ops={t.op_counter:,} diff={diff:5d} term={t.termination_cause}")
    if diff and len(sys.argv)>2 and sys.argv[2]=="why":
        Wd,H=cfg.VIEW_W,cfg.VIEW_H
        cols={}
        for y in range(H):
            for xx in range(Wd):
                if px[y*Wd+xx]!=want[y*Wd+xx]: cols.setdefault(xx,[]).append(y)
        print(f"    {len(cols)} columns differ; first few:")
        for xx in sorted(cols)[:6]:
            ys=cols[xx]
            print(f"      col {xx}: rows {ys[0]}..{ys[-1]} ({len(ys)}) fj={px[ys[0]*Wd+xx]} want={want[ys[0]*Wd+xx]}")
        break
