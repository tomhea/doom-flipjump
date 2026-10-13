"""P11: gamespeed run 7, frame F, monster M -- SeenHook's render (GameSim's seen rule, the trail's reference) against
the gates' mirror render (probe.Oracle.render's call, the inputs b0 passes), both built as render_wall_frame keyword
sets; then SeenHook's set with ONE of the mirror's inputs swapped in at a time, and the mirror's with one of
SeenHook's. Prints M's seen flag for each, so the input that flips it is named.
Run in a doom-flipjump checkout: PYTHONPATH="src;scratchpad/12m;scratchpad/gp;scratchpad" python seen_swap_probe.py [F] [M]"""
import sys

sys.path[:0] = ["scratchpad/12m", "scratchpad/gp", "scratchpad", "src"]
import gamespeed as GS  # noqa: E402
import probe as P  # noqa: E402
import scenarios_v2 as S  # noqa: E402
from doomfj.monsters import MonsterPhase  # noqa: E402
from doomfj.reference_model import SimState, GAME_RENDER_KW  # noqa: E402

F = int(sys.argv[1]) if len(sys.argv) > 1 else 52
M = int(sys.argv[2]) if len(sys.argv) > 2 else 21
sim = GS.GameSim()
st = sim.reset()
w = sim.w
for f, kd in enumerate(GS.script(7, F + 1)):
    st = sim.step(st, kd)
    if f == F:
        break
ws = w.ws
hook = next((h for h in getattr(w, "_post_tic", []) if type(h).__name__ == "SeenHook"), None)
if hook is None:
    from doomfj.sight import SeenHook
    hook = SeenHook(w)
print("frame %d: monster %d seen (GameSim) = %d, at (%d, %d) active %d state %d"
      % (F, M, ws.mon_seen[M], ws.mon_x[M], ws.mon_y[M], ws.mon_active[M], ws.mon_state[M]))

# SeenHook's keyword set, as SeenHook.__call__ builds it -- through the WORLD's renderer (w.rm, Config()'s full
# screen): the picture SeenHook drew before P11's fix
n = w.layout.nmon
pos = [(t.x, t.y) for t in hook.drawable]
hid = set()
for m in range(n):
    di = hook.views.mdi[m]
    pos[di] = (ws.mon_x[m], ws.mon_y[m])
    if not ws.mon_active[m]:
        hid.add(di)
views = [None] * hook.views.n
for m, v in hook._mviews(w).items():
    views[hook.views.mdi[m]] = v
A = dict(rm=w.rm, scene=hook._scene(w), sprite_wad=hook.art, thing_positions=pos, thing_hidden=hid,
         thing_views=views, kw=dict(GAME_RENDER_KW))

# the mirror's keyword set, as probe.Oracle.render builds it from b0's inputs
orc = P.Oracle()
mph = MonsterPhase.__new__(MonsterPhase)
mph.world, mph.gd = w, S.gd
B = dict(rm=orc.rm, scene=orc.scene_for(tuple(ws.d_state), dict(w.heights_now)),
         sprite_wad=orc.art, thing_positions=orc.monster_positions(mph),
         thing_hidden=set(orc.hidden), thing_views=orc.monster_views(mph, ws.px, ws.py),
         mobiles=mph.mobiles(), thing_removed=orc.monster_removed(mph), barrel_views=orc.monster_barrel_views(mph),
         kw=dict(orc.RENDER_KW))
vd = mph.view_drop()
if vd:
    B["view_drop"] = vd


def seen(d):
    d = dict(d)
    rm, kw = d.pop("rm"), d.pop("kw")
    scene = d.pop("scene")
    s = set()
    rm.render_wall_frame(SimState(ws.px, ws.py, ws.pangle, w.mapname), scene, seen_out=s, **d, **kw)
    return hook.views.mdi[M] in s


print("SeenHook's set: %s   the mirror's set: %s" % (seen(A), seen(B)))
print("SeenHook's hidden: %d drawables; the mirror's: %d (skill-absent %d); only in the mirror's: %s"
      % (len(A["thing_hidden"]), len(B["thing_hidden"]), len(orc.hidden), sorted(B["thing_hidden"] - A["thing_hidden"])[:20]))
print("positions differ at %s" % [i for i, (a, b) in enumerate(zip(A["thing_positions"], B["thing_positions"])) if a != b][:20])
print("views differ at %s" % [i for i, (a, b) in enumerate(zip(A["thing_views"], B["thing_views"])) if a != b][:20])
print("mobiles %d, removed %s, barrel_views %d, view_drop %s, scene same %s, kw same %s, art same %s"
      % (len(B["mobiles"] or ()), sorted(B["thing_removed"] or ())[:12], len(B["barrel_views"] or {}), vd,
         A["scene"] is B["scene"], A["kw"] == B["kw"], A["sprite_wad"] is B["sprite_wad"]))
for k in sorted(set(A) | set(B)):
    a2 = dict(A)
    if k in B:
        a2[k] = B[k]
    else:
        a2.pop(k)
    b2 = dict(B)
    if k in A:
        b2[k] = A[k]
    else:
        b2.pop(k)
    print("   swap %-15s SeenHook's set with the mirror's: %-5s   the mirror's with SeenHook's: %s" % (k, seen(a2), seen(b2)))
