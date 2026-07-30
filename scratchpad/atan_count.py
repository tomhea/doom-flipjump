"""How many point_to_angle calls does a frame actually make? (segs that pass the affine cull)"""
import sys; sys.path.insert(0,'src')
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, build_scene, spawn_state, SimState, _signed
from doomfj.fixedpoint import fixed_mul
from doomfj.mapcompiler import seg_affine_coeffs
from doomfj.wad import WadFile
from doomfj.config import PNEAR_SEG_BUDGET
cfg=Config(); rm=ReferenceModel(cfg)
mw=WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
scene=build_scene(mw,mw,'E1M1')
lds=mw.linedefs('E1M1'); sds=mw.sidedefs('E1M1'); secs=mw.sectors('E1M1')
cm=scene.cmap; verts=cm.vertexes; W=cfg.VIEW_W; MASK=0xFFFFFFFF
sp=spawn_state(mw,'E1M1'); sx,sy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16
def marks(seg):
    ld=lds[seg.linedef]
    if ld.back==-1: return True
    fs=secs[sds[ld.front if seg.side==0 else ld.back].sector]
    bs=secs[sds[ld.back if seg.side==0 else ld.front].sector]
    return ((fs.ceil_h,fs.light&0xff,fs.ceil_tex.upper())!=(bs.ceil_h,bs.light&0xff,bs.ceil_tex.upper())
         or (fs.floor_h,fs.light&0xff,fs.floor_tex.upper())!=(bs.floor_h,bs.light&0xff,bs.floor_tex.upper()))
def count(vx,vy,va):
    st=SimState(vx<<16,vy<<16,va,'E1M1')
    px,py=_signed(st.x,32)>>16,_signed(st.y,32)>>16
    pcl=[0]*W; claimed=0; nts=0; pairs=0; drawn=[0]*W; nd=0
    for seg_i in rm.visible_segs(cm,px,py):
        seg=cm.segs[seg_i]; two=lds[seg.linedef].back!=-1
        if two:
            if not marks(seg) or claimed==W or nts>=PNEAR_SEG_BUDGET: continue
            nts+=1
        elif nd==W: continue
        a,b,c=seg_affine_coeffs(seg,verts)
        if _signed((fixed_mul(a,st.x,8,4)+fixed_mul(b,st.y,8,4)+c)&MASK,32)<=0: continue
        pairs+=1                                   # this seg pays TWO point_to_angle calls
        r=rm.wall_x_range(st.x,st.y,st.angle,seg,verts)
        if r is None: continue
        for x in range(r[0],r[1]):
            if not pcl[x]: pcl[x]=1; claimed+=1
            if not two and not drawn[x]: drawn[x]=1; nd+=1
    return pairs
for vx,vy,va,nm,cost in [(sx,sy,sp.angle,"spawn",5_473_808),(-309,-44,0,"(-309,-44)",7_902_894)]:
    n=count(vx,vy,va)
    print(f"{nm:12s}: ~{n} segs reach the atans => {2*n} point_to_angle calls, "
          f"{cost:,} ops => ~{cost/(2*n):,.0f} ops each")
