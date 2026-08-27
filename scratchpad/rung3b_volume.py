"""M13-2S rung 3b, priced from the ORACLE's own emit volume (no fj build, no confounds).

The lines tier's cost is dominated by what it EMITS: [y2][colour] pairs (~3.7k ops each, measured)
plus the per-column record framing. Count what rung 3b would emit vs what the shipped tier emits, at
the same viewpoints, straight from the two oracles."""
import sys; sys.path.insert(0,'src')
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, build_scene, spawn_state, SimState, _signed
from doomfj.wad import WadFile
cfg=Config(); rm=ReferenceModel(cfg)
mw=WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
scene=build_scene(mw,mw,'E1M1')
lds=mw.linedefs('E1M1'); sds=mw.sidedefs('E1M1'); secs=mw.sectors('E1M1')
cm=scene.cmap; verts=cm.vertexes; W,H=cfg.VIEW_W,cfg.VIEW_H
sp=spawn_state(mw,'E1M1'); sx,sy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16

def colour_runs(fb,x):
    """the pairs a column-run emit must produce for column x = its vertical colour runs."""
    n=1
    for y in range(1,H):
        if fb[y*W+x]!=fb[(y-1)*W+x]: n+=1
    return n

def count(vx,vy,va):
    st=SimState(vx<<16,vy<<16,va,'E1M1')
    a=rm.render_wall_frame(st,scene,floor_texturing=False,wall_mode="WPX",floor_mode_ft1=True,
                           plane_near=True)
    b=rm.render_frame_2s(st,scene)
    ra=sum(colour_runs(a,x) for x in range(W)); rb=sum(colour_runs(b,x) for x in range(W))
    return ra,rb
PER_PAIR=3700   # measured: docs/handoff-m13-2s.md §4
print("colour runs per frame (an upper bound on emitted pairs; the ditto path collapses repeats):")
for vx,vy,va,name in [(sx,sy,sp.angle,"spawn"),(sx,sy,(sp.angle+0x40000000)&0xFFFFFFFF,"spawn+90"),
                      (-309,636,0,"(-309,636)"),(-309,-44,0,"(-309,-44)")]:
    ra,rb=count(vx,vy,va)
    print(f"  {name:12s} rung 3a {ra:5d}   rung 3b {rb:5d}   delta {rb-ra:+5d} "
          f"=> ~{(rb-ra)*PER_PAIR/1e6:+.2f}M ops of extra EMIT alone")
