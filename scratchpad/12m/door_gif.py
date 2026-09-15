"""ORACLE-ONLY door GIF: spawn -> walk to door 10 -> use -> walk through -> turn around ->
use -> watch it open and shut.  No .fjm, no assembly: the oracle IS the shipped picture."""
import sys, time
from pathlib import Path
ROOT = Path(r"C:/Users/tomhe/Documents/doom-flipjump")
for q in (ROOT/"tests", ROOT/"src", ROOT): sys.path.insert(0, str(q))
sys.path.insert(0, str(ROOT/"scratchpad"))

from PIL import Image
from doomfj.config import Config
from doomfj.doorcode import door_line_ids
from doomfj.doors import (door_states, door_tic, heights_for_states, in_use_box_fixed,
                          initial_states, pass_state, use_boxes_xy, WAIT, SPEED)
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import (ANGLE_TURN, ReferenceModel, Scene, SimState, build_scene,
                                    _signed, spawn_state)
from doomfj.wad import WadFile
from doomfj.wireformat import KEY_NAMES
from m2_std_gate import plan_walkable, walkable_cells, NAV_CELL

T0 = time.time()
def log(m): print("[%6.1fs] %s" % (time.time()-T0, m), flush=True)

MAP = "E1M1"
cfg = Config(); W, H = cfg.VIEW_W, cfg.VIEW_H
mw  = WadFile.from_path(str(ROOT/"tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT/"assets/freedoom1.wad"))
rm  = ReferenceModel(cfg)
pal = art.playpal(0)
CMAP = bake_bsp(mw, MAP)                       # bake ONCE (build_scene re-bakes every call)
def scene_of(heights=None, blocked=frozenset()):
    return Scene(mw, mw, MAP, CMAP, heights, frozenset(blocked))

secs, lds, sds = mw.sectors(MAP), mw.linedefs(MAP), mw.sidedefs(MAP)
tbl     = door_states(secs, lds, sds); order = sorted(tbl)
boxes   = use_boxes_xy(secs, lds, sds, CMAP.vertexes)
lines_of= door_line_ids(secs, lds, sds, tbl)
passes  = {si: pass_state(secs, lds, sds, si) for si in order}
nstates = {si: len(v) for si, v in tbl.items()}
open_h  = {si: (secs[si].floor_h, tbl[si][-1]) for si in order}

sp = spawn_state(mw, MAP)
shut_scene = scene_of()
_, cells = walkable_cells(rm, shut_scene, _signed(sp.x,32)>>16, _signed(sp.y,32)>>16)
def reachable(si):
    x0,y0,x1,y1 = boxes[si]
    return any(x0<=cx*NAV_CELL+8<=x1 and y0<=cy*NAV_CELL+8<=y1 for cx,cy in cells)
cands = [si for si in order if reachable(si)]
target = min(cands, key=lambda si: ((boxes[si][0]+boxes[si][2])//2-(sp.x>>16))**2
                                 + ((boxes[si][1]+boxes[si][3])//2-(sp.y>>16))**2)
log("target door %d  states=%d pass=%d box=%s" % (target, nstates[target], passes[target], boxes[target]))

segs_ = [(CMAP.vertexes[lds[li].v1], CMAP.vertexes[lds[li].v2]) for li in sorted(lines_of[target])]
(ax,ay),(bx,by) = segs_[0]
mx,my = (ax+bx)/2.0, (ay+by)/2.0
nx,ny = -(by-ay), (bx-ax); nl = (nx*nx+ny*ny)**0.5 or 1.0; nx,ny = nx/nl, ny/nl
sgn = -1.0 if ((sp.x>>16)-mx)*nx + ((sp.y>>16)-my)*ny > 0 else 1.0
approach = (mx - sgn*nx*56, my - sgn*ny*56)
beyond   = (mx + sgn*nx*48, my + sgn*ny*48)      # PAST the door but still INSIDE the use box
log("doorway mid=(%.0f,%.0f) approach=%s beyond=%s" % (mx,my,tuple(map(round,approach)),tuple(map(round,beyond))))

route = plan_walkable(rm, shut_scene, sp, approach, 40,
                      accept=lambda st: in_use_box_fixed(boxes[target], st.x, st.y)
                      and ((st.x>>16)-approach[0])**2 + ((st.y>>16)-approach[1])**2 <= 72**2)
assert route, "no route"
log("route %d frames" % len(route))

# advance a private mirror through route+press+open so `through` is planned from the real pose
st, ds = sp, initial_states(secs, lds, sds)
press   = [{"use": True}, {"use": True}]
# ⚠ DERIVED, never a constant. This was `range(8)`, which is `SPEED*(9-1)` -- right only while a
# door had 9 stops. Raising the smoothness (DEFAULT_QUANT 16 -> 12) gave door 10 thirteen stops and
# the assert below fired at state 1, blaming the door for the script's arithmetic. Same coupling
# that bit m2_std_gate's --open-wait.
OPEN_FRAMES = SPEED * (nstates[target] - 1) + 2
opening = [{} for _ in range(OPEN_FRAMES)]
for kd in route + press + opening:
    used = bool(kd.get("use"))
    ds = {si: door_tic(ds[si], nstates[si], used and in_use_box_fixed(boxes[si], st.x, st.y)) for si in order}
    blk = frozenset(li for si in order if ds[si][0] < passes[si] for li in lines_of.get(si, ()))
    st = rm.step_sim(st, kd, scene=scene_of(open_h, blk))
assert ds[target][0] == nstates[target]-1, (
    "door %d reached state %d of %d after %d opening frames -- OPEN_FRAMES is wrong, not the door"
    % (target, ds[target][0], nstates[target]-1, OPEN_FRAMES))
through = plan_walkable(rm, scene_of(open_h), st, beyond, 40)
assert through, "no route through"
log("through %d frames" % len(through))

TURN = round((1 << 31) / ANGLE_TURN)             # frames for ~180 deg
turn  = [{"turn_left": True} for _ in range(TURN)]
idle  = [{} for _ in range(SPEED*(nstates[target]-1) + WAIT + SPEED*(nstates[target]-1) + 4)]
script = route + press + opening + through + turn + press + idle
log("script %d frames  (route %d, press 2, open %d, through %d, turn %d, press 2, idle %d)"
    % (len(script), len(route), OPEN_FRAMES, len(through), TURN, len(idle)))

RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                 near_steps=True, stack_steps=True, things=True, sprite_wad=art,
                 degrade=True, sky=True, bbox_cull=True)         # deg_gate's kwargs
state, dstates = sp, initial_states(secs, lds, sds)
imgs, trace = [], []
for f, kd in enumerate(script):
    used = bool(kd.get("use"))
    dstates = {si: door_tic(dstates[si], nstates[si],
                            used and in_use_box_fixed(boxes[si], state.x, state.y)) for si in order}
    blocked = frozenset(li for si in order if dstates[si][0] < passes[si] for li in lines_of.get(si, ()))
    state = rm.step_sim(state, kd, scene=scene_of(open_h, blocked))
    rsc = scene_of(heights_for_states(secs, lds, sds, {si: dstates[si][0] for si in order}))
    px = rm.render_wall_frame(state, rsc, **RENDER_KW)
    im = Image.new("P", (W, H)); im.putdata(px)
    im.putpalette([c for rgb in pal for c in rgb])
    imgs.append(im)
    trace.append((f, state.x>>16, state.y>>16, state.angle, dstates[target][0]))
    if f % 40 == 0: log("  frame %d/%d door=%d" % (f, len(script), dstates[target][0]))
log("rendered %d frames" % len(imgs))
out = ROOT/"scratchpad/12m/atlas"
out.mkdir(parents=True, exist_ok=True)
G = Path(r"C:/Users/tomhe/AppData/Local/Temp/claude/C--Users-tomhe-Documents-doom-flipjump/29ddbecf-cbb7-4734-805a-36c0e391327d/scratchpad/door_walk.gif")
big = [im.resize((W*3, H*3), Image.NEAREST) for im in imgs]
big[0].save(G, save_all=True, append_images=big[1:], duration=70, loop=0, optimize=False)
log("wrote %s  (%.2f MB)" % (G, G.stat().st_size/1e6))
seen = sorted({t[4] for t in trace})
log("door %d states seen: %s" % (target, seen))
