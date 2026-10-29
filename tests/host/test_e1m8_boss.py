"""M8 (E1M8, the boss level): the route planner, the bot and the combat-set criteria on a map whose exit opens only when
its Barons die (A_BossDeath: every MT_BRUISER dead -> the tag-666 floor, sector 3, lowers; its own W1 line 894 lies
behind it).

THE ROUTE (scripts/level_route.py). The boss floor is a MECHANISM triggered by the KILL of every boss the skill spawns
(`BOSS_TRIGGER`), reached when the flood stands within BOSS_REACH of each boss's spot -- E1M8's Barons stand in pits
ringed 104-112 units up until the tag-1 W1 lowers the rings, so that floor is the kill's dependency. The kill is fought
with what the map offers: the ways to the chaingun and the shotgun (`KILL_ARMS`: the tag-3 W1 floor lowers their
rings) are the kill's dependencies too, and they are taken before the leg that frees the Barons. The exit path crosses
sector 3 (a 16-unit sill no cell centre stands on), so the boss floor is a dependency of an edge CROSSING its sector.
  CONTROLS (R9): BOSS_TRIGGER off -> NO ROUTE (the flood closes: the 2026-10-29 state); KILL_ARMS empty -> no tag-3
  floor in the route; the crossing rule off -> the boss floor drops out of the closure (the exit leg is planned in the
  flood's world, `closure_gap`).

THE BOT (scripts/play.py Steer). On a KILL leg: the bosses are fought whatever they target (asleep or not); the leg ends
when every boss is dead (not before). CONTROLS: the same cells on a non-kill leg -> no foe; a boss alive -> no end.

THE CRITERIA (scratchpad/gp/scenarios_map.py, the owner 2026-10-29): scaled per map; on E1M2..E1M5 and E1M9 every value
is E1M1's (no patch: their sets validate as they did); on E1M8: kills 0, the kinds melee + fireball, doors 1, no
aftermath, no infighting. CONTROL: scenarios_v2's own criteria on the same metrics fail where the scaled ones pass.
THE SETUP FLOORS: an E1M8 checkpoint past the W1 floors starts with them lowered (the Barons' ring at 16); CONTROL: the
same setup without `floors` keeps the ring up.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
pytestmark = pytest.mark.skipif(not (FIX / "freedoom_e1m8.wad").exists(), reason="needs the E1M8 fixture wad")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lr():
    return _load("level_route", "scripts/level_route.py")


@pytest.fixture(scope="module")
def route(lr):
    return lr.plan("E1M8", "easy")


# ---- the route ---------------------------------------------------------------------------------------------------
def test_e1m8_route_kills_the_barons(route):
    r = route
    assert r["ok"], r.get("why")
    assert r["exit"]["special"] == 52 and r["exit"]["model"]
    kill = [n for n in r["needs"] if n["trigger"] == "kill"]
    assert len(kill) == 1 and kill[0]["sectors"] == [3], kill            # the tag-666 floor, by the Barons' deaths
    tag1 = next(n for n in r["needs"] if 38 in n["sectors"])              # the ring round the west Barons
    tag3 = next(n for n in r["needs"] if 50 in n["sectors"])              # the ring round the chaingun
    assert tag1["trigger"] == tag3["trigger"] == "walk"
    to = [g["to"] for g in r["legs"]]
    k = to.index(kill[0]["id"])
    leg = r["legs"][k]
    assert leg["action"] == "kill" and sorted(map(tuple, leg["bosses"])) == [(1, 1152, -1568), (3, -320, -256)]
    assert to[-1] == "exit" and k == len(to) - 2
    # the weapons before the leg that frees the Barons
    assert to.index("item:2002") < to.index(tag1["id"]) and to.index("item:2001") < to.index(tag1["id"])
    assert all(g["path"] for g in r["legs"]) and not any(g.get("closure_gap") for g in r["legs"])


def test_control_no_boss_trigger(lr, monkeypatch):
    monkeypatch.setattr(lr, "BOSS_TRIGGER", False)
    r = lr.plan("E1M8", "easy", with_legs=False)
    assert not r["ok"], "CONTROL: E1M8 planned with no boss trigger -- the exit is behind the boss floor"
    assert "flood closed" in r["why"]


def test_control_no_kill_arms(lr, monkeypatch):
    monkeypatch.setattr(lr, "KILL_ARMS", ())
    r = lr.plan("E1M8", "easy")
    assert r["ok"]
    assert not any(50 in n["sectors"] for n in r["needs"]), "CONTROL: the tag-3 floor is in the route without the arms"
    assert "item:2002" not in [g["to"] for g in r["legs"]]


def test_control_no_crossing_rule(lr, monkeypatch):
    monkeypatch.setattr(lr.Planner, "sector_segs", lambda self, sectors: [])
    r = lr.plan("E1M8", "easy")
    assert not any(n["trigger"] == "kill" for n in r["needs"]), "CONTROL: the crossing rule made no difference"
    assert any(g.get("closure_gap") for g in r["legs"])


# ---- the bot -----------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def steer(route):
    play = _load("play", "scripts/play.py")
    st = play.Steer(route, log=lambda s: None, seed=0)
    st.rt = list(range(len(st.mtype)))
    return play, st


def _cells(st, x, y, health, seen, target):
    n = len(st.mtype)
    bosses = next(g for g in st.legs if g["action"] == "kill")["bosses"]
    pos = [0] * n
    for m, bx, by in bosses:
        pos[m] = ((bx << 16) & 0xFFFFFFFF) | (((by << 16) & 0xFFFFFFFF) << 32)
    live = {b[0] for b in bosses}
    return {"mode": 0, "p_dead": 0, "p_rct": 0, "viewx": (int(x) << 16) & 0xFFFFFFFF,
            "viewy": (int(y) << 16) & 0xFFFFFFFF, "viewangle": 0,
            "mon_active": [1 if m in live else 0 for m in range(n)],
            "mon_health": [health.get(m, 1000) for m in range(n)], "thseen": [1 if m in seen else 0 for m in range(n)],
            "mon_target": [target] * n, "thpos_rt": pos, "p_atk": 0, "p_hp": 100, "am_clip": 50, "am_shell": 0,
            "wp_own": 0, "dstate": [0] * len(st.dorder), "lstate": [0] * len(st.lorder), "aim_sid": ()}


def _kill_leg(st):
    return next(i for i, g in enumerate(st.legs) if g["action"] == "kill")


def test_kill_leg_fights_a_boss_whatever_it_targets(steer):
    _play, st = steer
    st._leg(_kill_leg(st))
    c = _cells(st, -320, -500, {}, seen={3}, target=0)            # Baron 3 seen, asleep (target 0), 244 units off
    foe = st._foe(c, -320.0, -500.0, 10)
    assert foe is not None and foe[3] == 3
    st._leg(0)                                                     # CONTROL: the same cells on a non-kill leg
    assert st._foe(c, -320.0, -500.0, 10) is None, "CONTROL: an asleep monster was fought on an ordinary leg"


def test_kill_leg_ends_only_when_every_boss_is_dead(steer):
    _play, st = steer
    k = _kill_leg(st)
    st._leg(k)
    x, y = st.legs[k]["path"][0]
    st.decide(100, _cells(st, x, y, {1: 0}, seen=set(), target=1))          # one Baron dead, one alive
    assert st.li == k, "CONTROL: the kill leg ended with a Baron alive"
    st.decide(101, _cells(st, x, y, {1: 0, 3: -5}, seen=set(), target=1))   # both dead
    assert st.li == k + 1 and st.events[-1][3] == "every boss dead"
    assert st.legs[k]["to"] in st.active                         # the boss floor joins the world re-plans use


# ---- the criteria and the setup floors (scenarios_map: one map per process) ---------------------------------------
CODE = r"""
import json, sys
sys.path[:0] = [r"{root}/src", r"{root}/scratchpad", r"{root}/scratchpad/12m", r"{root}/scratchpad/gp", r"{root}/tests"]
import scenarios_map as SM, scenarios_v2 as S
SM.install("{m}", None)
out = {{"scale": SM.CRITERIA_SCALE, "patched": ("scenarios_v2", "criteria") in SM._ORIGINALS}}
if "{m}" == "E1M8":
    cp = {{"name": "t", "sector": 1, "want": (400, -400), "face": (-320, -256), "region": 1, "style": "fight"}}
    st = S.make_setup(cp)
    w = S.start_world(st)
    w0 = S.start_world({{k: v for k, v in st.items() if k != "floors"}})
    out.update(floors=st.get("floors"), ring=w.mover_heights_now().get(38, (w.secs[38].floor_h,))[0],
               ring0=w0.mover_heights_now().get(38, (w0.secs[38].floor_h,))[0],
               r0=S.make_setup(dict(cp, region=0)).get("floors"), boss=w.boss_group)
print("RESULT " + json.dumps(out))
"""


def _run(m):
    r = subprocess.run([sys.executable, "-c", CODE.format(root=ROOT.as_posix(), m=m)], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=900)
    line = [x for x in r.stdout.splitlines() if x.startswith("RESULT ")]
    assert line, r.stdout[-1000:] + r.stderr[-2000:]
    return json.loads(line[0][7:])


WAD = ROOT / "assets" / "freedoom1.wad"


@pytest.mark.skipif(not WAD.exists(), reason="needs assets/freedoom1.wad")
def test_e1m8_criteria_scaled_and_floors_lowered():
    got = _run("E1M8")
    sc = got["scale"]
    assert got["patched"] and sc["kills"] == 0 and sc["kinds"] == ["melee", "fireball"] and sc["doors"] == 1
    assert not sc["aftermath"] and not sc["infight"] and sc["dodge"] and sc["pickups"] == 6
    assert got["floors"] == [0, 1] and got["boss"] == 2 and got["r0"] is None
    assert got["ring"] == 16, "the tag-1 ring round the west Barons is lowered by the setup (to its trench, 16)"
    assert got["ring0"] == 128, "CONTROL: without `floors` the ring stays up"


@pytest.mark.skipif(not WAD.exists(), reason="needs assets/freedoom1.wad")
@pytest.mark.parametrize("m", ["E1M2", "E1M3", "E1M4", "E1M5", "E1M9"])
def test_other_maps_keep_e1m1_criteria(m):
    got = _run(m)
    assert got["scale"] == {} and not got["patched"], got


def _metrics(**kw):
    r = {"census": False, "name": "x", "frames": 100, "dead": [], "health": 80, "mkills": 0, "bkills": 0,
         "shotgun": 0, "doors_player": [1], "doors_monster": [], "move_key": 80, "strafe": 40, "moving": 70,
         "move_frames": 80, "dodges": 2, "threat_frames": 5, "corpses_near_start": 0, "cam_part": 0,
         "door_part": 0, "use_strafe": 0, "infight": 0, "fight": True, "knock": False,
         "totals": {"deaths": 0, "mon_shots": 0, "mon_melee": 3, "proj_spawns": 4, "pickups": 6, "level_done": 0}}
    r.update(kw)
    return r


def test_scaled_criteria_rows_and_control():
    for p in ("src", "scratchpad", "scratchpad/12m", "scratchpad/gp", "tests"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    import scenarios_map as SM
    import scenarios_v2 as S
    sc = {"kills": 0, "kinds": ["melee", "fireball"], "doors": 1, "pickups": 6, "aftermath": False,
          "infight": False, "dodge": True}
    ms = [_metrics()]
    rows = {n: ok for n, ok, _d in SM.scaled_criteria(S, sc, S.criteria, ms)}
    assert rows[">= 0 kills"] and rows["the map's monster attack kinds (melee, fireball)"]
    assert rows[">= 1 doors opened by the player"]
    assert all(ok for n, ok in rows.items() if "N/A on" in n) and sum("N/A on" in n for n in rows) == 2
    assert (S.MIN_KILLS, S.MIN_DOORS) == (8, 3)                    # restored after the call
    orig = {n: ok for n, ok, _d in S.criteria(ms)}                 # CONTROL: E1M1's criteria on the same metrics
    assert not orig[">= 8 kills"] and not orig["all three monster attack kinds"]
    assert not orig[">= 3 doors opened by the player"]
    assert not next(ok for n, ok in orig.items() if n.startswith("an aftermath run"))
    assert not next(ok for n, ok in orig.items() if n.startswith(">= 1 infighting"))


# ---- the oracle mirror the playthrough gate steps (p2a_gate.Mirror / monsters.MonsterPhase.frame) -----------------
# Before 2026-10-29 the model-only E1M8 play killed both Barons and stood at the W1 exit with no LEVEL COMPLETE: the
# mirror's mover state never took A_BossDeath's fire (the world fired it inside the monsters' tic, the next `sync`
# wrote the gate's state back over it), and its lvdone came from the S1 exit's press only.
MIRROR = r"""
import os, sys, json
os.environ["DOOMFJ_MAP"] = "E1M8"
sys.path[:0] = [r"{root}" + p for p in ("/src", "/scratchpad", "/scratchpad/12m", "/scratchpad/gp", "/tests")]
import onewalk, p2a_gate as G
dsim = onewalk.DoorSim()
out = {{}}
for ctl in (None, "no_walk_exit"):
    fr = G.Mirror(dsim, -1, ctl=ctl).run((880 << 16, 288 << 16, 0), [{{"forward": True}}] * 6)
    out[str(ctl)] = [f["lvdone"] for f in fr]
print("RESULT " + json.dumps(out))
"""


def test_mirror_w1_exit_ends_the_level():
    r = subprocess.run([sys.executable, "-c", MIRROR.format(root=ROOT.as_posix())], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=900)
    line = [x for x in r.stdout.splitlines() if x.startswith("RESULT ")]
    assert line, r.stdout[-1000:] + r.stderr[-2000:]
    got = json.loads(line[0][7:])
    assert got["None"][0] == 0 and got["None"][-1] == 1, got          # walked east over line 228 (W1 52)
    assert not any(got["no_walk_exit"]), "CONTROL: the level ended without the mirror's W1 exit rule"


def test_mirror_takes_the_boss_floor_back():
    from doomfj import gamedata as gd
    from doomfj.config import Config
    from doomfj.monsters import MonsterPhase
    from doomfj.reference_model import ReferenceModel
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
    from doomfj.world import TicEvents
    lr = _load("level_route", "scripts/level_route.py")
    lv = lr.Level("E1M8", None, "easy")
    ph = MonsterPhase(WadFile.from_path(str(FIX / "freedoom_e1m8.wad")), "E1M8", gd.SK_EASY,
                      rm=ReferenceModel(Config()), mode=MONSTER_MODE, player=PLAYER_MODE)
    w = ph.world
    g, ng = w.boss_group, len(w.floor_groups)
    for m in (1, 3):                                   # easy's two Barons
        w.ws.mon_health[m] = 1
        w.damage_monster(m, 10, ("player", -1), None, TicEvents(0))
    dps, mps = lv.dp.initial(), lv.mp.initial()
    for _ in range(40):
        dps, mps = ph.frame(dps, mps, 2464 << 16, 360 << 16, 0)
    assert w.boss_log, "A_BossDeath fired in the world"
    assert mps[2][g] > 0 or mps[2][ng + g] > 0, "the gate's mover state took the boss floor's fire"
    # CONTROL: the frame as it was (sync, tic, the gate's own sw handed back) loses it -- the world's cells hold it
    sw = tuple(0 for _ in range(2 * ng))
    ph.sync(dps[0], mps[0], sw)
    ph.tic(2464 << 16, 360 << 16, 0)
    assert sw[g] == 0 and sw[ng + g] == 0


def test_kill_leg_takes_the_launcher_only_far_off(steer):
    _play, st = steer
    from doomfj import gamedata as gd
    k = _kill_leg(st)
    st._leg(k)
    own = (1 << 4 * 4) | (1 << 4 * 5) | (1 << 4 * 2) | 0x11      # fist, pistol, shotgun, launcher, chaingun
    far = dict(_cells(st, -320, -700, {}, seen=set(), target=1), wp_own=own, am_misl=5, am_clip=100, am_shell=20,
               wp_rdy=gd.WP_CHAINGUN, wp_pend=gd.WP_NOCHANGE)      # Baron 3 444 units off
    kd = set()
    st._arm(0, far, kd)
    assert kd == {"w5"}, kd
    near = dict(far, viewy=((-400 << 16) & 0xFFFFFFFF))         # 144 units off: inside the blast's reach
    kd = set()
    st._arm(0, near, kd)
    assert "w5" not in kd
    st._leg(0)                                                   # CONTROL: an ordinary leg never takes the launcher
    kd = set()
    st._arm(0, far, kd)
    assert "w5" not in kd
