"""M7 P2a.1 (PR #99 review; the reviewer's probe, kept) -- kill criterion 6's view clause: is the blue card DRAWN on any frame of set v3?
Steps the model along each frozen run; on frames where the card is within +-55 deg of the view and
3000 units, renders the oracle's game picture twice (card hidden / shown) and compares bytes."""
import json, math, sys
from pathlib import Path
WT = Path(__file__).resolve().parents[2]
for q in (WT / "src", WT / "tests", WT / "scratchpad", WT / "scratchpad/gp"):
    sys.path.insert(0, str(q))
import scenarios_v2 as S
from doomfj.config import Config
from doomfj.doors import heights_for_states
from doomfj.reference_model import GAME_RENDER_KW, ReferenceModel, SimState, build_scene
from doomfj.things import drawable_things
from doomfj.wad import WadFile
from doomfj.fixedpoint import _signed

doc = json.loads((WT / "scratchpad/gp/scenarios/combat_scenarios_v3.json").read_text(encoding="ascii"))
mw = WadFile.from_path(str(WT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(WT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
drawable = drawable_things(rm, mw.things("E1M1"), art)[0]
card_di = [i for i, t in enumerate(drawable) if t.type == 5]
assert len(card_di) == 1, card_di
KX, KY = 2192, 576
cand = drawn = 0
for run in doc["runs"]:
    w = S.start_world(run["setup"])
    for f, s in enumerate(run["keys"]):
        w.tic(S.str_to_keys(s))
        ws = w.ws
        x, y = _signed(ws.px, 32) / 65536, _signed(ws.py, 32) / 65536
        ang = (ws.pangle & 0xFFFFFFFF) / 2**32 * 360
        dx, dy = KX - x, KY - y
        d = math.hypot(dx, dy)
        rel = (math.degrees(math.atan2(dy, dx)) - ang + 540) % 360 - 180
        if d > 3000 or abs(rel) > 55:
            continue
        if not w.los_points((ws.px, ws.py), (KX << 16, KY << 16)):
            continue
        cand += 1
        print("LOS %s f%d (%.0f,%.0f) d=%.0f rel=%.0f" % (run["name"], f, x, y, d, rel), flush=True)
        states = {si: ws.d_state[k] for k, si in enumerate(w.door_order)}
        rsc = build_scene(mw, mw, "E1M1", heights_for_states(secs, lds, sds, states))
        st = SimState(ws.px, ws.py, ws.pangle, "E1M1")
        a = bytes(rm.render_wall_frame(st, rsc, sprite_wad=art, thing_hidden=set(), **GAME_RENDER_KW))
        b = bytes(rm.render_wall_frame(st, rsc, sprite_wad=art, thing_hidden=set(card_di), **GAME_RENDER_KW))
        if a != b:
            drawn += 1
            print("DRAWN: %s frame %d pose (%.0f, %.0f) dist %.0f rel %.0f deg, %d px differ"
                  % (run["name"], f, x, y, d, rel, sum(p != q for p, q in zip(a, b))), flush=True)
    print("  %-20s done (candidates so far %d, drawn so far %d)" % (run["name"], cand, drawn), flush=True)
print("CARD VIEW: %d candidate frames, card drawn on %d" % (cand, drawn))
