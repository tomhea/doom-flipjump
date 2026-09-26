"""S5 -- why the picture's aim and the geometric aim disagree at the pistol's column (80).

    python scratchpad/gp/census_aimdiag.py [S4 run name] [snapshot path]

Replays one S4 run (with the replay control), renders the 'game' picture each tic, and classifies
every frame where the two aims name different targets at column 80:
  geo-only   the geometric aim hits something the picture did not draw there -- split by what the
             picture has in column 80 instead (a nearer wall, another sprite, nothing);
  pic-only   the picture shows a shootable target the geometric aim rejects -- split by the reason
             the geometric test fails (outside its box span, beyond 2048 units, 2D line of sight);
  both       each names a different target.
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import census_lib as CL                                                     # noqa: E402
from census import LETTERS                                                  # noqa: E402
from census_lib import W                                                    # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "R0-south-hall"
snap = sys.argv[2] if len(sys.argv) > 2 else str(HERE / "census_out/s4/combat_scenarios_v1.snapshot.json")
run = next(r for r in json.loads(Path(snap).read_text())["runs"] if r["name"] == name)
c = CL.Census(run["checkpoint"].get("skill", 3))
w, ws = c.world, c.world.ws
cp = run["checkpoint"]
w.teleport_player(cp["x16"], cp["y16"], cp["angle"])
COL = 80
why = Counter()
n = 0
for s in run["keys"]:
    w.tic({LETTERS[ch]: True for ch in s if LETTERS.get(ch)})
    th, bk, me, mt = c.game_things()
    _fb, arr = c.render(th, bk, me, mt)
    geo = w.aim_geometric(w, COL)
    claim = [(k, r) for k, r in enumerate(arr) if COL in r["A"] or COL in r["B"]]
    shoot = [(k, r) for k, r in claim if r["meta"] is not None and r["meta"].shoot]
    pic = None
    if shoot:
        m = shoot[0][1]["meta"]
        pic = ("mon", m.idx) if m.role == "live" else ("bar", m.idx)
    n += 1
    if pic == geo:
        continue
    if pic is None:
        tgt = next((r for r in arr if r["meta"] is not None and r["meta"].shoot
                    and (("mon", r["meta"].idx) if r["meta"].role == "live" else ("bar", r["meta"].idx)) == geo), None)
        if tgt is None:
            why["geo-only: target never reached the walk (leaf not visited / after the full stop)"] += 1
        elif tgt["res"] is None:
            why["geo-only: target degraded or rejected by the projection"] += 1
        elif tgt["drawn"][COL]:
            why["geo-only: a wall already drew column 80 when the target arrived"] += 1
        else:
            x1, x2, _y, _h, istep, _tz = tgt["res"]
            if not x1 <= COL <= x2:
                why["geo-only: the sprite's span %d..%d misses col 80 (the radius box covers it)"
                    % (x1, x2) if False else "geo-only: the sprite's span misses col 80 (the radius box covers it)"] += 1
            else:
                a = tgt["art"]
                frac = (max(0, x1) - x1) * istep + (COL - max(0, x1)) * istep
                u = min(a[2] - 1, max(0, frac >> 16))
                if not any(v >= 0 for v in a[0][u]):
                    why["geo-only: the sprite is TRANSPARENT at col 80 (a gap in the art; the box covers it)"] += 1
                elif claim:
                    why["geo-only: col 80 held by another sprite (%s) and slot B refused" % claim[0][1]["meta"].role] += 1
                else:
                    why["geo-only: other"] += 1
    elif geo is None:
        m = shoot[0][1]["meta"]
        x, y = (ws.mon_x[m.idx], ws.mon_y[m.idx]) if m.role == "live" else (
            w.barrel_things[m.idx].x, w.barrel_things[m.idx].y)
        dist = W.aprox_distance(x - (ws.px >> 16), y - (ws.py >> 16))
        if dist > 2048:
            why["pic-only: beyond MISSILERANGE"] += 1
        elif not w.los_points((ws.px, ws.py), (x << 16, y << 16)):
            why["pic-only: 2D line of sight blocked"] += 1
        else:
            why["pic-only: sprite covers col 80, the radius box does not"] += 1
    else:
        why["both name a target, different ones"] += 1
print("run %s: %d frames; digest %s" % (name, n, "EQUALS" if w.digest() == run["model_final_digest"]
                                          else "!! DIFFERS"))
for k, v in why.most_common():
    print("  %3d  %s" % (v, k))
