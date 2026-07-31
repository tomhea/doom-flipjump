"""How many REGION entries does a column collect (top / bottom) in the 2S model?"""
import sys; sys.path.insert(0,'src')
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state, _signed, ANGLE_MASK
from doomfj.wad import WadFile
cfg=Config(); rm=ReferenceModel(cfg)
mw=WadFile.from_path('tests/fixtures/freedoom_e1m1.wad'); scene=build_scene(mw,mw,'E1M1')
lds=mw.linedefs('E1M1'); sds=mw.sidedefs('E1M1'); secs=mw.sectors('E1M1')
cm=scene.cmap; verts=cm.vertexes; W,H=cfg.VIEW_W,cfg.VIEW_H
sp=spawn_state(mw,'E1M1'); sx,sy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16
def run(vx,vy,va):
    st=SimState(vx<<16,vy<<16,va,'E1M1')
    px,py=_signed(st.x,32)>>16,_signed(st.y,32)>>16
    pss=cm.subsectors[rm.point_in_subsector(cm,px,py)]
    viewz=rm.view_z(rm._seg_sector(lds,sds,secs,cm.segs[pss.firstseg]).floor_h)
    cc=[-1]*W; fc=[H]*W; top_n=[0]*W; bot_n=[0]*W
    for seg_i in rm.visible_segs(cm,px,py):
        seg=cm.segs[seg_i]; ld=lds[seg.linedef]; two=ld.back!=-1
        sd=sds[ld.front if seg.side==0 else ld.back]; fs=secs[sd.sector]
        if two:
            bs=secs[sds[ld.back if seg.side==0 else ld.front].sector]
            if ((fs.ceil_h,fs.light,fs.ceil_tex)==(bs.ceil_h,bs.light,bs.ceil_tex)
                and (fs.floor_h,fs.light,fs.floor_tex)==(bs.floor_h,bs.light,bs.floor_tex)): continue
        rng=rm.wall_x_range(st.x,st.y,st.angle,seg,verts)
        if rng is None: continue
        x1,x2,_=rng
        na,rd=rm.wall_setup(st.x,st.y,seg,verts)
        scale=rm.scale_from_global_angle((st.angle+rm.xtoviewangle[x1])&ANGLE_MASK,st.angle,na,rd)
        if x2>x1:
            s2=rm.scale_from_global_angle((st.angle+rm.xtoviewangle[x2])&ANGLE_MASK,st.angle,na,rd)
            d,sn=s2-scale,x2-x1; step=-(abs(d)//sn) if d<0 else d//sn
        else: step=0
        for x in range(x1,x2):
            sc=(scale+step*(x-x1))&ANGLE_MASK
            if cc[x]+1<=fc[x]-1:
                top,bot=rm.wall_screen_span(fs.ceil_h,fs.floor_h,viewz,sc)
                c_hi,c_lo=cc[x]+1,min(top-1,fc[x]-1)
                if c_hi<=c_lo: top_n[x]+=1; cc[x]=c_lo
                f_lo,f_hi=fc[x]-1,max(bot+1,cc[x]+1)
                if f_hi<=f_lo: bot_n[x]+=1; fc[x]=f_hi
                wh,wl=cc[x]+1,fc[x]-1
                if wh<=wl:
                    if not two:
                        top_n[x]+=1; cc[x],fc[x]=H,-1
                    else:
                        bs=secs[sds[ld.back if seg.side==0 else ld.front].sector]
                        if fs.ceil_h>bs.ceil_h:
                            _t,ub=rm.wall_screen_span(fs.ceil_h,bs.ceil_h,viewz,sc)
                            lo=min(ub-1,wl)
                            if wh<=lo: top_n[x]+=1; cc[x]=lo; wh=lo+1
                        if bs.floor_h>fs.floor_h:
                            lt,_b=rm.wall_screen_span(bs.floor_h,fs.floor_h,viewz,sc)
                            hi=max(lt,wh)
                            if hi<=wl: bot_n[x]+=1; fc[x]=hi
    return max(top_n),max(bot_n),sum(top_n)+sum(bot_n)
xs=[v[0] for v in cm.vertexes]; ys=[v[1] for v in cm.vertexes]
VPS=[(sx,sy,sp.angle),(sx,sy,(sp.angle+0x40000000)&0xFFFFFFFF),(-309,-44,0),(-309,636,0),(-480,256,0)]
for i in range(5):
    for j in range(5):
        VPS.append((min(xs)+(max(xs)-min(xs))*(2*i+1)//10, min(ys)+(max(ys)-min(ys))*(2*j+1)//10, 0))
mt=mb=0; tot=0
for vx,vy,va in VPS:
    a,b,c=run(vx,vy,va); mt=max(mt,a); mb=max(mb,b); tot=max(tot,c)
print(f"max TOP entries in a column={mt}   max BOTTOM={mb}   max total entries/frame={tot}")
