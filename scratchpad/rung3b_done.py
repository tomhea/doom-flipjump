"""What rung 3b adds: the shipped tier (rung 3a) vs the render_frame_2s TARGET, same viewpoints."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from PIL import Image, ImageDraw
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.fixedpoint import _signed
from doomfj.wad import WadFile
cfg=Config(); rm=ReferenceModel(cfg)
mw=WadFile.from_path(str(ROOT/"tests/fixtures/freedoom_e1m1.wad"))
scene=build_scene(mw,mw,"E1M1"); pal=mw.playpal()
sp=spawn_state(mw,"E1M1"); sx,sy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16
VPS=[(sx,sy,sp.angle,"spawn"),(sx,sy,(sp.angle+0x40000000)&0xFFFFFFFF,"spawn +90"),
     (-309,636,0,"(-309,636)"),(-480,256,0,"(-480,256)")]
W,H,S=cfg.VIEW_W,cfg.VIEW_H,3
sheet=Image.new("RGB",(W*S*2+30,(H*S+26)*len(VPS)),(16,16,18)); d=ImageDraw.Draw(sheet)
for r,(vx,vy,va,name) in enumerate(VPS):
    st=SimState(vx<<16,vy<<16,va,"E1M1")
    a=rm.render_wall_frame(st,scene,floor_texturing=False,wall_mode="WPX",floor_mode_ft1=True,
                           plane_near=True)
    b=rm.render_frame_2s(st,scene)
    for c,(fb,lbl) in enumerate(((a,"rung 3a (shipped)"),(b,"rung 3b: fj, byte-exact"))):
        im=Image.new("RGB",(W,H)); im.putdata([pal[p] for p in fb])
        x0=c*(W*S+30); y0=r*(H*S+26)+20
        sheet.paste(im.resize((W*S,H*S),Image.NEAREST),(x0,y0))
        d.text((x0+2,y0-16),f"{name}   {lbl}",fill=(230,230,235))
out=ROOT/"scratchpad/rung3b_done.png"; sheet.save(out); print(out)
