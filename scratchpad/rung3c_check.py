"""Does the rung 3c plan survive contact with E1M1? Three questions:
 1. how much geometry does "nearest upper/lower per column" actually drop?
 2. does the splice ever go NON-MONOTONE (a near step overlapping the closing wall's band)?
 3. how many columns would a closed door close early (the free win), and how many never close?"""
import sys; sys.path.insert(0,'src')
from collections import Counter
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state, _signed, ANGLE_MASK
from doomfj.wad import WadFile
cfg=Config(); rm=ReferenceModel(cfg)
mw=WadFile.from_path('tests/fixtures/freedoom_e1m1.wad'); scene=build_scene(mw,mw,'E1M1')
lds=mw.linedefs('E1M1'); sds=mw.sidedefs('E1M1'); secs=mw.sectors('E1M1')
cm=scene.cmap; verts=cm.vertexes; W,H=cfg.VIEW_W,cfg.VIEW_H
sp=spawn_state(mw,'E1M1'); sx,sy=_signed(sp.x,32)>>16,_signed(sp.y,32)>>16
def marks(seg):
    ld=lds[seg.linedef]
    if ld.back==-1: return True
    fs=secs[sds[ld.front if seg.side==0 else ld.back].sector]; bs=secs[sds[ld.back if seg.side==0 else ld.front].sector]
    return ((fs.ceil_h,fs.light,fs.ceil_tex)!=(bs.ceil_h,bs.light,bs.ceil_tex) or (fs.floor_h,fs.light,fs.floor_tex)!=(bs.floor_h,bs.light,bs.floor_tex))
def run(vx,vy,va):
    st=SimState(vx<<16,vy<<16,va,'E1M1')
    px,py=_signed(st.x,32)>>16,_signed(st.y,32)>>16
    pss=cm.subsectors[rm.point_in_subsector(cm,px,py)]
    viewz=rm.view_z(rm._seg_sector(lds,sds,secs,cm.segs[pss.firstseg]).floor_h)
    ups=[[] for _ in range(W)]; los=[[] for _ in range(W)]
    closed=[None]*W; ctake=[None]*W; fstart=[None]*W; doorclose=0
    for seg_i in rm.visible_segs(cm,px,py):
        seg=cm.segs[seg_i]; ld=lds[seg.linedef]; two=ld.back!=-1
        if two and not marks(seg): continue
        sd=sds[ld.front if seg.side==0 else ld.back]; fs=secs[sd.sector]
        rng=rm.wall_x_range(st.x,st.y,st.angle,seg,verts)
        if rng is None: continue
        x1,x2,_=rng
        na,rd=rm.wall_setup(st.x,st.y,seg,verts)
        sc0=rm.scale_from_global_angle((st.angle+rm.xtoviewangle[x1])&ANGLE_MASK,st.angle,na,rd)
        if x2>x1:
            s2=rm.scale_from_global_angle((st.angle+rm.xtoviewangle[x2])&ANGLE_MASK,st.angle,na,rd)
            d,sn=s2-sc0,x2-x1; step=-(abs(d)//sn) if d<0 else d//sn
        else: step=0
        bs=secs[sds[ld.back if seg.side==0 else ld.front].sector] if two else None
        for x in range(x1,x2):
            if closed[x] is not None: continue          # a one-sided wall already owns this column
            sc=(sc0+step*(x-x1))&ANGLE_MASK
            top,bot=rm.wall_screen_span(fs.ceil_h,fs.floor_h,viewz,sc)
            if not two:
                closed[x]=seg_i; ctake[x]=max(0,min(top,H)); fstart[x]=max(0,min(bot+1,H))
                continue
            if fs.ceil_h>bs.ceil_h:
                _t,ub=rm.wall_screen_span(fs.ceil_h,bs.ceil_h,viewz,sc)
                y1,y2=max(0,min(top,H)),max(0,min(ub,H))
                if y1<y2: ups[x].append((y1,y2))
            if bs.floor_h>fs.floor_h:
                lt,_b=rm.wall_screen_span(bs.floor_h,fs.floor_h,viewz,sc)
                y1,y2=max(0,min(lt,H)),max(0,min(bot+1,H))
                if y1<y2: los[x].append((y1,y2))
            if bs.ceil_h<=bs.floor_h and ups[x] and los[x]:      # a CLOSED door: upper+lower meet
                doorclose+=1
    nup=Counter(len(u) for u in ups); nlo=Counter(len(l) for l in los)
    lost=sum(max(0,len(u)-1) for u in ups)+sum(max(0,len(l)-1) for l in los)
    kept=sum(1 for u in ups if u)+sum(1 for l in los if l)
    # non-monotone splice: the NEAREST upper ends below the closing wall's ctake?
    bad_up=sum(1 for x in range(W) if ups[x] and ctake[x] is not None and ups[x][0][1]>ctake[x])
    bad_lo=sum(1 for x in range(W) if los[x] and fstart[x] is not None and los[x][0][0]<fstart[x])
    never=sum(1 for x in range(W) if closed[x] is None)
    return nup,nlo,kept,lost,bad_up,bad_lo,never,doorclose
xs=[v[0] for v in cm.vertexes]; ys=[v[1] for v in cm.vertexes]
VPS=[(sx,sy,sp.angle,"spawn"),(sx,sy,(sp.angle+0x40000000)&0xFFFFFFFF,"spawn+90"),
     (-309,636,0,"(-309,636)"),(-309,-44,0,"(-309,-44)"),(-480,256,0,"(-480,256)")]
tot_bad=tot_kept=tot_lost=0
for vx,vy,va,nm in VPS:
    nup,nlo,kept,lost,bu,bl,never,dc=run(vx,vy,va)
    tot_bad+=bu+bl; tot_kept+=kept; tot_lost+=lost
    print(f"{nm:12s} uppers/col {dict(sorted(nup.items()))}  lowers/col {dict(sorted(nlo.items()))}")
    print(f"             runs kept(nearest-only)={kept} dropped={lost}  "
          f"SPLICE-OVERLAP up={bu} lo={bl}  columns never closed={never}  closed-door cols={dc}")
print(f"\nTOTAL over 5 viewpoints: kept {tot_kept} runs, dropped {tot_lost} "
      f"({100*tot_lost/max(1,tot_kept+tot_lost):.0f}%), splice overlaps {tot_bad}")
