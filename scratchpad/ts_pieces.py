"""What pieces does the 2S oracle produce for one column? (regions + wall runs, in order)"""
import sys; sys.path.insert(0,'src')
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state, _signed
from doomfj.wad import WadFile
cfg=Config(); rm=ReferenceModel(cfg)
import sys as _s
NM="E1M1" if len(_s.argv)>1 and _s.argv[1]=="e1m1" else "MAP01"
if NM=="E1M1":
    mw=WadFile.from_path('tests/fixtures/freedoom_e1m1.wad'); aw=mw
else:
    mw=WadFile.from_path('tests/fixtures/square_room.wad'); aw=WadFile.from_path('tests/fixtures/freedoom_assets.wad')
scene=build_scene(mw,aw,NM); sp=spawn_state(mw,NM)
lds=mw.linedefs(NM); sds=mw.sidedefs(NM); secs=mw.sectors(NM)
cm=scene.cmap; verts=cm.vertexes; W,H=cfg.VIEW_W,cfg.VIEW_H
XCOL=int(_s.argv[2]) if len(_s.argv)>2 else 0
st=SimState(sp.x,sp.y,sp.angle,NM)
px,py=_signed(st.x,32)>>16,_signed(st.y,32)>>16
pss=cm.subsectors[rm.point_in_subsector(cm,px,py)]
viewz=rm.view_z(rm._seg_sector(lds,sds,secs,cm.segs[pss.firstseg]).floor_h)
ceilclip=[-1]*W; floorclip=[H]*W
from doomfj.reference_model import ANGLE_MASK
for seg_i in rm.visible_segs(cm,px,py):
    seg=cm.segs[seg_i]; ld=lds[seg.linedef]; two=ld.back!=-1
    sd=sds[ld.front if seg.side==0 else ld.back]; fsec=secs[sd.sector]
    if two:
        bsec=secs[sds[ld.back if seg.side==0 else ld.front].sector]
        if ((fsec.ceil_h,fsec.light,fsec.ceil_tex)==(bsec.ceil_h,bsec.light,bsec.ceil_tex)
            and (fsec.floor_h,fsec.light,fsec.floor_tex)==(bsec.floor_h,bsec.light,bsec.floor_tex)): continue
    rng=rm.wall_x_range(st.x,st.y,st.angle,seg,verts)
    if rng is None: continue
    x1,x2,_=rng
    if not (x1<=XCOL<x2): continue
    na,rd=rm.wall_setup(st.x,st.y,seg,verts)
    scale=rm.scale_from_global_angle((st.angle+rm.xtoviewangle[x1])&ANGLE_MASK,st.angle,na,rd)
    if x2>x1:
        s2=rm.scale_from_global_angle((st.angle+rm.xtoviewangle[x2])&ANGLE_MASK,st.angle,na,rd)
        diff,span=s2-scale,x2-x1
        step=-(abs(diff)//span) if diff<0 else diff//span
    else: step=0
    sc=(scale+step*(XCOL-x1))&ANGLE_MASK
    if ceilclip[XCOL]+1>floorclip[XCOL]-1: continue
    top,bot=rm.wall_screen_span(fsec.ceil_h,fsec.floor_h,viewz,sc)
    print(f"seg {seg_i} two={two} top={top} bot={bot} chi={ceilclip[XCOL]+1} flo={floorclip[XCOL]}")
    c_hi,c_lo=ceilclip[XCOL]+1,min(top-1,floorclip[XCOL]-1)
    if c_hi<=c_lo:
        print(f"   CEIL region rows [{c_hi},{c_lo}] -> exclusive end {c_lo+1}")
        ceilclip[XCOL]=c_lo
    f_lo,f_hi=floorclip[XCOL]-1,max(bot+1,ceilclip[XCOL]+1)
    if f_hi<=f_lo:
        print(f"   FLOOR region rows [{f_hi},{f_lo}]")
        floorclip[XCOL]=f_hi
    wh,wl=ceilclip[XCOL]+1,floorclip[XCOL]-1
    if wh<=wl:
        if not two:
            print(f"   WALL run rows [{max(top,wh)},{min(bot,wl)}]")
            ceilclip[XCOL],floorclip[XCOL]=H,-1
        else:
            bsec=secs[sds[ld.back if seg.side==0 else ld.front].sector]
            if fsec.ceil_h>bsec.ceil_h:
                _t,ub=rm.wall_screen_span(fsec.ceil_h,bsec.ceil_h,viewz,sc)
                lo=min(ub-1,wl)
                if wh<=lo:
                    print(f"   UPPER run rows [{wh},{lo}]"); ceilclip[XCOL]=lo; wh=lo+1
            if bsec.floor_h>fsec.floor_h:
                lt,_b=rm.wall_screen_span(bsec.floor_h,fsec.floor_h,viewz,sc)
                hi=max(lt,wh)
                if hi<=wl:
                    print(f"   LOWER run rows [{hi},{wl}]"); floorclip[XCOL]=hi
