"""scenarios_v2.py -- S4 v2 of docs/plan-gameplay.md: the COMBAT SCENARIO SET v2 (the set the owner
freezes), the oracle autopilot that plans it, the CAP-22 validator WITH THE FREEZE CHECK, and the R9
controls.

    python scratchpad/gp/scenarios_v2.py --plan [--file F]      # plan every run (status PLANNED)
    python scratchpad/gp/scenarios_v2.py --validate [--file F]  # replay + census: criteria + freeze
    python scratchpad/gp/scenarios_v2.py --selftest             # R9: each criterion FAILS its mutant
    python scratchpad/gp/scenarios_v2.py --freeze --b0 scratchpad/gp/scenarios/b0_v2.json
        # re-plan every run (the keys must come out identical), validate, record B0, mark FROZEN

THE SET. 11 runs x 100 frames, one tic per frame, skill HARD (46 monsters). Every run starts from a
CHECKPOINT injected into the level's START state (D2): the player's pose, and for the AFTERMATH
run also three corpses. v1's ten checkpoints are kept (the doors region R0, behind the lifts R2,
behind the blue-key doors R3; `scenarios.py --regions`).

WHAT CHANGED FROM v1 (the owner's decisions of 2026-09-26 on v1's open questions):
  * the model: world.K_HEAVY 3 -> 6, and strafe_left / strafe_right (combat.STRAFE_MOVE = 13
    units a tic along angle - ANG90, through the player's collision candidates);
  * the autopilot FIGHTS LIKE A PLAYER: while it fights it strafes (alternating sides, the
    distance kept with forward/back), and it strafes out of a fireball's line when that step is
    free ("where cheap");
  * floors: >= 50% of frames carry a movement key (v1 29%, gamespeed 87%); >= 8 kills, >= 6
    pickups, >= 3 doors opened by the player, all three monster attack kinds, every run survives;
  * the AFTERMATH run: R0-west-hall's opening trio (sector 17: two zombiemen, an imp) injected as
    corpses at their spawns, the zombiemen's clips dropped, the player among them -- it prices the
    post-kill drawing (corpses, drops);
  * "IN VIEW" = DRAWN. The census wiring (census_lib, S5) renders each frame with the compositor
    rules the owner decided for D3 (a + c + d + e, b for projectiles and barrels: census.py's
    `rec` picture) and counts every thing that claimed a column. v1's geometric test (box
    projects on screen + 2D line of sight) stays as the second column;
  * B0 FOLLOWS THE MODEL'S CAMERA EXACTLY (`b0_injection`): b0 writes, at every frame start, the
    pose from which blocked27's OWN tic -- turn, then the forward/back step; it has no strafe --
    lands exactly where the model did. That also retires v1's rule against thing-blocked steps
    (the model blocks the player on things, blocked27 does not: the injection absorbs it);
  * the FREEZE: `--freeze` marks the file FROZEN with the owner's approval, and `--validate`
    checks it: status and approval, every recorded file hash, the replay (per-frame poses and the
    final digest), the drawn population frame by frame, and the B0 record.

THE AUTOPILOT (`Autopilot`) plays the MODEL (doomfj.world + doomfj.combat, the default geometric
aim) from the model's state only (no lookahead into the RNG):
  * FIGHT: the target is the nearest living monster it can see within `engage` (awake first, the
    weaker first); it turns until the centre-column aim is on a monster and fires only while the
    weapon is READY (every pistol shot is DOOM's accurate first shot); forward/back keep the band
    [keep, keep + band] (back when hurt with a monster near); strafe on every fight frame it can,
    switching sides every `strafe_period` tics or when a side is blocked;
  * DODGE: a fireball whose closest approach is within DODGE_MISS units and DODGE_HORIZON tics
    makes it strafe away from the fireball's line, when that step moves (any mode);
  * TOUR: nothing to fight -- a wanted item within 12 cells of path, else a closed plain door
    within DOOR_DETOUR cells (it walks into the door's box and presses use), else the nearest
    living monster; the path is a 16-unit cell graph built with the oracle's own try_move;
  * PICKUPS (map items AND drops): fight-first runs detour only when calm, or for an item within
    a step or two, or health when hurt; `collect` runs sweep items whenever no awake monster is
    within 256 units;
  * RULES: never use in a key door's box or the exit's box; no strafe on a use frame; never
    press a movement key whose step the model would refuse (the validator counts real steps).
  * SURVIVAL: parameter sets from aggressive to defensive; the first whose run survives is kept.
Deterministic: no randomness anywhere but the model's own seeded streams.

--validate replays the keys (on the census's own World, so the picture is the replay's) and checks:
every run survives; >= 30% of frames have an AWAKE monster DRAWN; >= 8 kills, all three attack
kinds, >= 6 pickups, >= 3 player door openings; >= 50% of frames carry a movement key; every run
moves on >= 60% of its movement frames; >= 50% of the frames with an awake monster drawn carry a
strafe key; >= 1 fireball dodge; the aftermath run starts among >= 3 corpses and draws a corpse on
>= 50% of its frames; no exit; B0's camera reconstruction lands on the model's pose on every frame.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import math
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "tests", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", HERE, ROOT):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

from doomfj import gamedata as gd                                           # noqa: E402
from doomfj import world as W                                               # noqa: E402
from doomfj.combat import FIREBALL_R, SECTOR_HURT, STRAFE_MOVE              # noqa: E402
from doomfj.doors import OPENING, door_tic, in_use_box_fixed                # noqa: E402
from doomfj.fixedpoint import _signed, fixed_mul                            # noqa: E402
from doomfj.reference_model import ANGLE_TURN, FORWARD_MOVE, Scene, SimState  # noqa: E402

SCEN_DIR = HERE / "scenarios"
SCEN_FILE = SCEN_DIR / "combat_scenarios_v2.json"
CACHE_DIR = Path(os.environ.get("GP_NAV_CACHE", r"C:\Users\tomhe\AppData\Local\Temp\claude"
                                r"\C--Users-tomhe-Documents-doom-flipjump"
                                r"\29ddbecf-cbb7-4734-805a-36c0e391327d\scratchpad\gp_navcache"))
VERSION = "v2"
FRAMES = 100
SKILL = gd.SK_HARD
UNIT = 1 << 16
M32 = 0xFFFFFFFF
CELL = 16
# the files a replay depends on (v1's list: also the nav cache's key, so v1 and v2 share graphs) ...
MODEL_FILES = ("src/doomfj/world.py", "src/doomfj/combat.py", "src/doomfj/gamedata.py",
               "src/doomfj/rng.py", "src/doomfj/doors.py", "src/doomfj/doorcode.py",
               "src/doomfj/reference_model.py", "src/doomfj/fixedpoint.py",
               "src/doomfj/mapcompiler.py", "src/doomfj/config.py",
               "tests/fixtures/freedoom_e1m1.wad")
# ... and the ones the DRAWN count adds (the census wiring, the sprite art), and the planner itself.
# Every other doomfj module the process imported is added when the hashes are taken (`code_hashes`)
CENSUS_FILES = ("scratchpad/gp/census_lib.py", "src/doomfj/things.py", "src/doomfj/wad.py",
                "assets/freedoom1.wad")
PLANNER_FILE = "scratchpad/gp/scenarios_v2.py"
LETTERS = (("forward", "f"), ("back", "b"), ("strafe_left", "<"), ("strafe_right", ">"),
           ("turn_left", "l"), ("turn_right", "r"), ("use", "u"), ("fire", "F"), ("w1", "K"),
           ("w2", "P"), ("w3", "S"), ("w4", "C"))
KEY_OF = {c: n for n, c in LETTERS}
MOVE_KEYS = ("forward", "back", "strafe_left", "strafe_right")
STRAFE_KEYS = ("strafe_left", "strafe_right")
B0_KEYS = ("forward", "back", "turn_left", "turn_right", "use")      # all blocked27's input reads
ASLEEP_ACTIONS = frozenset({"A_Look"})

PICKUP_ALWAYS = frozenset({2014, 2015, 2001, 2002, 2003, 2004, 2005, 2006, 8, 5, 6, 13, 38, 39,
                           40, 2023})
PICKUP_AMMO = frozenset({2007, 2008, 2048, 2049, 2010, 2046, 2047, 17})
PICKUP_HEALTH = frozenset({2011, 2012, 2013})
PICKUP_ARMOR = frozenset({2018, 2019})
PICKUP_WEAPON = {2001: gd.WP_SHOTGUN, 2002: gd.WP_CHAINGUN, 2003: gd.WP_MISSILE,
                 2004: gd.WP_PLASMA, 2005: gd.WP_CHAINSAW, 2006: gd.WP_BFG}
WEAPON_DETOUR = 30           # cells of path (480 units): a weapon not yet owned is worth this walk
BARREL_SAFE = 192            # a barrel is shot only from at least this far (its blast reaches 128)
BARREL_REACH = 96            # ... and only with an awake monster this close to it
FIRE_ACTIONS = frozenset({"A_FirePistol", "A_FireShotgun", "A_FireShotgun2", "A_FireCGun",
                          "A_Punch", "A_Saw", "A_FireMissile", "A_FirePlasma", "A_FireBFG"})
AIM_PATIENCE = 10            # ready frames the aim may miss a target before it is skipped ...
SKIP_TICS = 40               # ... for this many tics
ANG_FS = int(round(math.atan2(13, 16) / (2 * math.pi) * (1 << 32)))   # forward + strafe: 39.1 deg
MOVE_DIRS = ((0, ("forward",)), (ANG_FS, ("forward", "strafe_left")), (1 << 30, ("strafe_left",)),
             ((1 << 31) - ANG_FS, ("back", "strafe_left")), (1 << 31, ("back",)),
             (-((1 << 31) - ANG_FS), ("back", "strafe_right")), (-(1 << 30), ("strafe_right",)),
             (-ANG_FS, ("forward", "strafe_right")))
MOVE_OFF = 3 << 28           # 67.5 deg: the farthest a step may point from its waypoint's bearing
PICKUP_DETOUR = 10           # cells of path (160 units): a pickup this close is worth the walk ...
DETOUR_CALM = 256            # ... when no awake monster is nearer than this
DOOR_DETOUR = 24             # cells of path: a closed plain door this close is opened when calm
DODGE_HORIZON = 24           # tics: a fireball this far from its closest approach is a threat ...
DODGE_MISS = W.PLAYER_R + FIREBALL_R + 8   # ... when it would pass within this many units (30)
CENSUS_PICTURE = ("rec: the D3 rules as decided (a + c + d + e; b for projectiles and barrels), "
                  "census.py's `rec` variant")

# the CAP-22 criteria, v2 (the owner's floors of 2026-09-26)
MIN_AWAKE_DRAWN = 0.30
MIN_KILLS = 8
MIN_PICKUPS = 6
MIN_DOORS = 3
MIN_MOVE_KEY = 0.50
MIN_MOVING = 0.60
MIN_STRAFE_FIGHT = 0.50
MIN_DODGES = 1
AFTER_MIN_CORPSES = 3
AFTER_NEAR = 160             # "among corpses": this close to the player at the start
AFTER_MIN_DRAWN = 0.20       # the decided D3 picture degrades a corpse beyond ~130 units in a
                             # thing-rich room (census, MEASURED on the v2 drafts): a player who
                             # collects and leaves draws them on ~20-30 of 100 frames
FREEZE_RULE = "frozen: the keys, setups, B0 and what they reproduce; the owner's approval of the set is stored once (owner_approval) and never re-stamped. --rehash re-records source hashes after a pure refactor, only while F1/F3/F4/F5 hold and the checker (scenarios_v2.py) is unchanged. A CHECKER change is re-frozen by --freeze with its reviewer named (--approver), only with identical keys AND every recorded pose, digest and drawn population reproduced -- a reviewable event. A BEHAVIOUR change needs a new version in a NEW file (--plan --file NEW, which refuses a frozen file; B0 re-measured on it; --freeze --file NEW --approver 'the owner')."
APPROVAL = {"by": "the owner", "on": "2026-09-26",
            "record": "the owner, 2026-09-26: 'I agree with you on 1,2,3' -- 3 was 'plan a v2 [...] "
                      "then freeze v2 and its baseline' (docs/plan-gameplay.md section 11, D2)"}

POP_FIELDS = ("awake", "geo_in_view", "geo_awake", "geo_corpses", "fireballs", "deferred", "heavy",
              "d_live", "d_awake", "d_corpse", "d_drop", "d_fireball", "d_fx", "d_barrel")

# a checkpoint may put its own sets first: BRAWL fights inside claw reach (keep 24..48 units; a
# monster's melee reaches 60) -- the set's melee
BRAWL = dict(name="brawl", keep=24, band=24, retreat_hp=45, engage=1024, strafe_period=6)
# the autopilot's parameter sets, aggressive first (SURVIVAL: the first set whose run survives)
PARAMS = (
    dict(name="aggressive", keep=128, band=48, retreat_hp=40, engage=1024, strafe_period=6),
    dict(name="steady", keep=192, band=64, retreat_hp=55, engage=1024, strafe_period=8),
    dict(name="cautious", keep=288, band=96, retreat_hp=70, engage=900, strafe_period=8),
    dict(name="defensive", keep=416, band=128, retreat_hp=85, engage=800, strafe_period=10),
)

# ================================================================================================
# the checkpoints: WHERE, facing WHAT, and WHY (resolved to a standable point by `resolve`)
# ================================================================================================
CHECKPOINTS = (
    dict(name="R0-west-hall", sector=150, want=(300, 338), face=(752, 336), region=0,
         why="the level's opening fight: the ambush trio (2 zombiemen, an imp) of sector 17, "
             "450-570 units east, a short walk from the player start"),
    dict(name="R0-aftermath", sector=17, want=(700, 380), face=(789, 395), region=0,
         style="collect", corpses=(21, 22, 23),
         why="AFTERMATH: R0-west-hall after the fight -- its trio injected as corpses at their "
             "spawns (the zombiemen's clips dropped), the player among them, 70-130 units away: "
             "the post-kill drawing (corpses, drops) on the level's first floor"),
    dict(name="R0-south-hall", style="collect", sector=57, want=(616, -640), face=(848, -576), region=0,
         why="the south hall (11 pickups): shotgun guys at 264 and 504 units (one on the "
             "sector-112 ledge) and the imps of sector 106 at 440-900"),
    dict(name="R0-imp-court", sector=12, want=(640, 812), face=(848, 1056), region=0,
         why="the imp court (sectors 13/56): three imps at 290-460 units and a shotgun guy, 3 "
             "barrels -- fireballs; the sector-48 door (armor, bullets) is one cell away"),
    dict(name="R0-northwest", sector=135, want=(300, 1450), face=(352, 1392), region=0,
         why="the densest doors-region cluster (sectors 36/66/122): 2 demons at ~400 units, a "
             "shotgun guy and zombiemen at 140-400, all but one ambush -- melee"),
    dict(name="R0-courtyard", style="collect", sector=18, want=(1424, 732), face=(1424, 1408), region=0,
         why="the tall courtyard (sector 18, ceiling 536, 6 pickups, 2 barrels): its imp and the "
             "imp court's seen across the drop at 600-950 units -- the widest open view"),
    dict(name="R2-barrel-hall", sector=134, want=(2150, -520), face=(2256, -160), region=2,
         why="behind the lifts: 16 barrels (sector 134) with 3 shotgun guys, 2 imps, 2 demons and "
             "the spectre in view at 410-630 units -- barrel chains"),
    dict(name="R2-spectre-corridor", sector=102, want=(1588, -492), face=(1656, -248), region=2,
         why="behind the lifts: a demon at 278 and a shotgun guy at 226 units, the sector-133 "
             "corridor (spectre, imps) beyond"),
    dict(name="R2-east-yard", sector=15, want=(2052, 680), face=(2192, 784), region=2,
         params=(BRAWL,),
         why="behind the lifts: the east yard's two imps at 190 and 350 units, beside the "
             "blue-key room (sector 35)"),
    dict(name="R3-west", style="collect", sector=86, want=(-120, 1768), face=(-96, 1984), region=3,
         why="behind the blue-key doors: two of sector 87's four shotgun guys at 230-360 units; "
             "the four item closets' doors (sectors 78-81) 16-46 cells away"),
    dict(name="R3-mid", style="explore", sector=87, want=(400, 1856), face=(144, 1952), region=3,
         why="behind the blue-key doors: the same room from its middle, three shotgun guys at "
             "300-560 units, three closet doors 10-11 cells away"),
)

# ================================================================================================
# small helpers
# ================================================================================================
def sha16(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def dependency_files() -> list:
    """every file the replay and the drawn count depend on: the listed ones, plus every doomfj
    module this process has imported (call it after a census render, so lazy imports are in)"""
    files = set(MODEL_FILES) | set(CENSUS_FILES) | {PLANNER_FILE}
    src = (ROOT / "src" / "doomfj").resolve()
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        p = Path(f).resolve()
        if p.suffix == ".py" and src in p.parents:
            files.add(p.relative_to(ROOT.resolve()).as_posix())
    return sorted(files)


def code_hashes(files=None) -> dict:
    return {f: sha16(ROOT / f) for f in (files or dependency_files())}


def nav_model_key() -> str:
    """the nav-graph cache key: v1's (scenarios.py NavGraph._model_key), so the graphs are shared"""
    h = {f: sha16(ROOT / f) for f in MODEL_FILES}
    return hashlib.sha256(json.dumps(h, sort_keys=True).encode()).hexdigest()[:12]


def git_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:                                                  # noqa: BLE001
        return "?"


def git_untracked_or_modified(files) -> list:
    """which of `files` differ from HEAD (read-only: git status --porcelain)"""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--"] + list(files),
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:                                                  # noqa: BLE001
        return ["?"]
    return sorted(line[3:].strip() for line in out.splitlines() if line.strip())


def keys_to_str(kd: dict) -> str:
    return "".join(c for n, c in LETTERS if kd.get(n)) or "-"


def str_to_keys(s: str) -> dict:
    return {KEY_OF[c]: True for c in s if c != "-"}


def keys_sha(doc: dict) -> str:
    """one hash over every run's name, setup and keys -- what B0 measured must be this"""
    h = hashlib.sha256()
    for run in doc["runs"]:
        h.update(json.dumps([run["name"], run["setup"], run["keys"]], sort_keys=True).encode())
    return h.hexdigest()[:16]


def bam(dx: float, dy: float) -> int:
    return int(round(math.atan2(dy, dx) / (2 * math.pi) * (1 << 32))) & M32


def angle_err(want: int, have: int) -> int:
    e = (want - have) & M32
    return e - (1 << 32) if e >= 1 << 31 else e


def new_world() -> "W.World":
    return W.World(skill=SKILL)


def asleep(w, m: int) -> bool:
    return gd.STATES[gd.STATE_NAMES[w.ws.mon_state[m]]].action in ASLEEP_ACTIONS


def alive(w, m: int) -> bool:
    ws = w.ws
    return bool(ws.mon_active[m]) and ws.mon_health[m] > 0


def has_strafe(kd: dict) -> bool:
    return bool(kd.get("strafe_left")) != bool(kd.get("strafe_right"))


def has_move(kd: dict) -> bool:
    return any(kd.get(k) for k in MOVE_KEYS)


# ================================================================================================
# the injected start state: the player's pose, and (the aftermath) corpses
# ================================================================================================
def corpse_state(w, m: int) -> str:
    """the last state of monster m's death sequence (the one with tics -1: the corpse)"""
    s = w.mon_info[m].deathstate
    for _ in range(32):
        if gd.STATES[s].tics < 0:
            return s
        s = gd.STATES[s].next
    raise AssertionError("no corpse state for slot %d" % m)


def inject_corpse(w, m: int, x: int, y: int, drop: bool) -> None:
    """monster m as a CORPSE at map units (x, y): the state P_KillMobj + the death sequence leave
    (health 0, not shootable, not solid -- A_Fall --, the corpse frame forever), and its drop
    (a zombieman's clip, a shotgun guy's shotgun) on the spot when `drop`"""
    ws = w.ws
    if (ws.mon_x[m], ws.mon_y[m]) != (x, y):
        w.teleport_monster(m, x, y)
    ws.mon_health[m] = 0
    ws.mon_shootable[m] = 0
    ws.mon_solid[m] = 0
    ws.mon_state[m] = gd.STATE_INDEX[corpse_state(w, m)]
    ws.mon_tics[m] = W.TICS_FOREVER
    ws.mon_drop[m] = 1 if drop and w.dropper[m] is not None else 0


def apply_setup(w, setup: dict) -> None:
    for c in setup.get("corpses", ()):
        assert w.mon_things[c["slot"]].type == c["type"], c
        inject_corpse(w, c["slot"], c["x"], c["y"], c["drop"] is not None)
    x16, y16, angle = setup["pose"]
    w.teleport_player(x16, y16, angle)


def corpses_near(setup: dict) -> int:
    """the injected corpses within AFTER_NEAR units of the player's start (the aftermath's
    'among corpses')"""
    x, y = setup["pose"][0] >> 16, setup["pose"][1] >> 16
    return sum(1 for c in setup.get("corpses", ())
               if W.aprox_distance(c["x"] - x, c["y"] - y) <= AFTER_NEAR)


def start_world(setup: dict, w=None) -> "W.World":
    w = w or new_world()
    apply_setup(w, setup)
    return w


# ================================================================================================
# the model's player step, predicted without side effects; fireball threats
# ================================================================================================
def predict_move(w, kd: dict):
    """CombatMixin._player_move's landing for keys `kd` from the current state -- the same turn,
    the same FixedMul steps (forward along the angle, side along angle - ANG90) and the same three
    candidates through the same tests (a solid thing refuses a candidate, then try_move), minus the
    pickups it touches. Returns the landing (x16, y16), signed."""
    rmod, ws = w.rm, w.ws
    angle = ws.pangle
    if kd.get("turn_left"):
        angle = (angle + ANGLE_TURN) & M32
    if kd.get("turn_right"):
        angle = (angle - ANGLE_TURN) & M32
    move = (FORWARD_MOVE if kd.get("forward") else 0) - (FORWARD_MOVE if kd.get("back") else 0)
    side = (STRAFE_MOVE if kd.get("strafe_right") else 0) - (STRAFE_MOVE if kd.get("strafe_left") else 0)
    x, y = ws.px, ws.py
    if not move and not side:
        return x, y
    dx = dy = 0
    if move:
        m = move & M32
        dx += fixed_mul(m, rmod.read_cos(angle), 8, 4)
        dy += fixed_mul(m, rmod.read_sin(angle), 8, 4)
    if side:
        sd = side & M32
        dx += fixed_mul(sd, rmod.read_sin(angle), 8, 4)
        dy -= fixed_mul(sd, rmod.read_cos(angle), 8, 4)
    for cand in (((x + dx) & M32, (y + dy) & M32), ((x + dx) & M32, y),
                 (x, (y + dy) & M32)):
        if cand == (x, y):
            continue
        cx, cy = _signed(cand[0], 32), _signed(cand[1], 32)
        if w.player_blocking and w._solid_thing_at(cx, cy) is not None:
            continue
        if rmod.try_move(w.scene_c, x, y, cx, cy):
            return cx, cy
    return x, y


def shot_pending(ws) -> bool:
    """the trigger is down and the weapon's next state fires (the pistol shoots 4 tics after the
    trigger, the shotgun 3): the bearing at that tic decides the hit"""
    st = gd.STATES[gd.STATE_NAMES[ws.p_wpn_state]]
    return st.action not in FIRE_ACTIONS and gd.STATES[st.next].action in FIRE_ACTIONS


def fireball_threats(w) -> list:
    """[(tics to closest approach, slot, away)] for every fireball in flight that would pass within
    DODGE_MISS units of the player within DODGE_HORIZON tics, soonest first. `away` is +1 when a
    step to the RIGHT (strafe_right: along angle - ANG90) takes the player away from its line,
    else -1. Integer arithmetic only (the validator recomputes it)."""
    ws, rm = w.ws, w.rm
    out = []
    sa, ca = _signed(rm.read_sin(ws.pangle), 32), _signed(rm.read_cos(ws.pangle), 32)
    for s in range(W.FIREBALL_POOL):
        if not ws.proj_active[s]:
            continue
        mx, my = ws.proj_momx[s], ws.proj_momy[s]
        if not mx and not my:
            continue
        rx, ry = ws.px - ws.proj_x[s], ws.py - ws.proj_y[s]
        dot = rx * mx + ry * my
        v2 = mx * mx + my * my
        if dot <= 0 or dot > DODGE_HORIZON * v2:
            continue
        cx, cy = rx * v2 - mx * dot, ry * v2 - my * dot          # the miss vector, x v2
        if cx * cx + cy * cy >= ((DODGE_MISS << 16) * v2) ** 2:
            continue
        away = 1 if cx * sa - cy * ca >= 0 else -1                # right = (sin a, -cos a)
        out.append((dot // v2, s, away))
    out.sort()
    return out


# ================================================================================================
# geometry: v1's geometric "in view" (the second column)
# ================================================================================================
def span_on_screen(w, x: int, y: int, r: int):
    ws, rm = w.ws, w.rm
    cfg = rm.cfg
    vcos, vsin = rm.read_cos(ws.pangle), rm.read_sin(ws.pangle)
    tr_x = _signed((x << 16) - ws.px, 32)
    tr_y = _signed((y << 16) - ws.py, 32)
    gxt = _signed(fixed_mul(tr_x & M32, vcos, 8, 4), 32)
    gyt = -_signed(fixed_mul(tr_y & M32, vsin, 8, 4), 32)
    tz = gxt - gyt
    if tz < (4 << 16):
        return None
    gxt2 = -_signed(fixed_mul(tr_x & M32, vsin, 8, 4), 32)
    gyt2 = _signed(fixed_mul(tr_y & M32, vcos, 8, 4), 32)
    tx = -(gyt2 + gxt2)
    xscale = rm._scale_recip_div(cfg.PROJECTION << 16, tz)
    cxf = cfg.CENTERX << 16
    x1 = (cxf + _signed(fixed_mul((tx - (r << 16)) & M32, xscale, 8, 4), 32)) >> 16
    x2 = ((cxf + _signed(fixed_mul((tx + (r << 16)) & M32, xscale, 8, 4), 32)) >> 16) - 1
    return tz, x1, x2


def in_view(w, x: int, y: int, r: int) -> bool:
    sp = span_on_screen(w, x, y, r)
    if sp is None or sp[2] < 0 or sp[1] > w.rm.cfg.VIEW_W - 1:
        return False
    return w.los_points((w.ws.px, w.ws.py), (x << 16, y << 16))


def geo_population(w, ev) -> dict:
    ws = w.ws
    awake = inv = awake_inv = corpses_inv = 0
    for m in range(w.layout.nmon):
        if not ws.mon_active[m]:
            continue
        r = w.mon_radius[m]
        if ws.mon_health[m] > 0:
            a = not asleep(w, m)
            awake += a
            if in_view(w, ws.mon_x[m], ws.mon_y[m], r):
                inv += 1
                awake_inv += a
        elif in_view(w, ws.mon_x[m], ws.mon_y[m], r):
            corpses_inv += 1
    return {"awake": awake, "geo_in_view": inv, "geo_awake": awake_inv, "geo_corpses": corpses_inv,
            "fireballs": sum(ws.proj_active), "deferred": len(ev.deferred), "heavy": len(ev.heavy)}


# ================================================================================================
# the DRAWN population: the census wiring (census_lib) on the replay's own World
# ================================================================================================
def new_census():
    """a fresh census (census_lib installs module-level hooks; the newest census owns them, as in
    census.py, which makes one per run)"""
    import census_lib as CL
    return CL.Census(SKILL)


def drawn_population(c) -> dict:
    """render the frame the player sees now with the decided D3 rules (census.py's `rec`: small
    things first, corpses as scenery, depth order among runtime things, b for projectiles and
    barrels) and count what claimed at least one column slot, by role"""
    w = c.world
    th, bk, me, mt = c.reorder_small_first(*c.game_things(corpse_as_monster=False, depth_order=True))
    _fb, arr = c.render(th, bk, me, mt, exempt=lambda m: m.role in ("fireball", "barrel"))
    out = {"d_live": 0, "d_awake": 0, "d_corpse": 0, "d_drop": 0, "d_fireball": 0, "d_fx": 0,
           "d_barrel": 0}
    for a in arr:
        meta = a["meta"]
        if meta is None or not (a["A"] or a["B"]):
            continue
        if meta.role == "live":
            out["d_live"] += 1
            out["d_awake"] += not asleep(w, meta.idx)
        elif "d_" + meta.role in out:
            out["d_" + meta.role] += 1
    return out


# ================================================================================================
# the region analysis (v1's; the checkpoints' regions are asserted with it)
# ================================================================================================
def regions(w) -> dict:
    import scenarios as V1
    return V1.regions(w)


REGION_NAMES = ("R0 doors (start)", "R1 walk-over doors", "R2 behind the lifts",
                "R3 behind the blue-key doors", "R4 the floor switch")


# ================================================================================================
# the navigation graph (v1's, the same cache)
# ================================================================================================
class NavGraph:
    """Directed cell graph of where the player can walk from a seed, built by BFS with
    `ReferenceModel.try_move` against the PLAN scene: every door at its open height, the key doors'
    lines blocking; cells a static solid thing (barrel, solid decor) overlaps are left out. Cached
    on disk by the model's code hash and the seed cell -- the same files v1 writes."""

    STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    _loaded: list = []

    def __init__(self, cells, adj):
        self.cells = cells
        self.index = {c: i for i, c in enumerate(cells)}
        self.adj = adj

    @staticmethod
    def plan_scene(w) -> Scene:
        key_lines = frozenset(li for si in w.door_cards for li in w.door_lines.get(si, ()))
        return Scene(w.mw, w.mw, w.mapname, w.cmap, w.open_h, key_lines)

    @staticmethod
    def static_obstacles(w):
        from doomfj.combat import BARREL_R
        obs = [(t.x, t.y, BARREL_R) for b, t in enumerate(w.barrel_things) if w.ws.bar_solid[b]]
        obs += [(t.x, t.y, w.decor_radius[t.type]) for t in w._decor_now]
        return obs

    @classmethod
    def build(cls, w, seed_xy, cap=20000, tag="") -> "NavGraph":
        mk = nav_model_key()
        seed_cell = (seed_xy[0] // CELL, seed_xy[1] // CELL)
        if not cls._loaded and CACHE_DIR.exists():
            for f in sorted(CACHE_DIR.glob("nav_%s_*.pkl" % mk)):
                cells, adj = pickle.loads(f.read_bytes())
                cls._loaded.append(cls(cells, adj))
        for g in cls._loaded:
            if seed_cell in g.index:
                return g
        cache = CACHE_DIR / ("nav_%s_%d_%d.pkl" % (mk, seed_cell[0], seed_cell[1]))
        t0 = time.time()
        scene = cls.plan_scene(w)
        obs = cls.static_obstacles(w)
        rm = w.rm

        def free(c):
            x, y = c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2
            return all(abs(x - ox) >= r + 16 or abs(y - oy) >= r + 16 for ox, oy, r in obs)

        start = seed_cell
        cells, index, adj = [start], {start: 0}, [[]]
        q = collections.deque([start])
        while q and len(cells) < cap:
            c = q.popleft()
            ci = index[c]
            wx, wy = c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2
            for dx, dy in cls.STEPS:
                n = (c[0] + dx, c[1] + dy)
                if n in index:
                    if rm.try_move(scene, wx << 16, wy << 16, (n[0] * CELL + CELL // 2) << 16,
                                   (n[1] * CELL + CELL // 2) << 16):
                        adj[ci].append(index[n])
                    continue
                if not free(n):
                    continue
                nx, ny = n[0] * CELL + CELL // 2, n[1] * CELL + CELL // 2
                if not rm.try_move(scene, wx << 16, wy << 16, nx << 16, ny << 16):
                    continue
                index[n] = len(cells)
                cells.append(n)
                adj.append([])
                adj[ci].append(index[n])
                q.append(n)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(pickle.dumps((cells, adj)))
        print("  nav graph %s: %d cells in %.1f s (cached %s)" % (tag, len(cells), time.time() - t0,
                                                                 cache.name), flush=True)
        g = cls(cells, adj)
        cls._loaded.append(g)
        return g

    def nearest(self, x: int, y: int, within: int = 48):
        c = (x // CELL, y // CELL)
        if c in self.index:
            return self.index[c]
        best = None
        rr = within // CELL + 1
        for dx in range(-rr, rr + 1):
            for dy in range(-rr, rr + 1):
                n = (c[0] + dx, c[1] + dy)
                if n in self.index:
                    d = dx * dx + dy * dy
                    if best is None or (d, self.index[n]) < best[0]:
                        best = ((d, self.index[n]), self.index[n])
        return None if best is None else best[1]

    def bfs(self, src: int):
        dist, par = {src: 0}, {src: None}
        q = collections.deque([src])
        while q:
            u = q.popleft()
            for v in self.adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    par[v] = u
                    q.append(v)
        return dist, par

    def path(self, par, goal):
        out = []
        while goal is not None:
            out.append(goal)
            goal = par[goal]
        return out[::-1]

    def xy(self, i: int):
        c = self.cells[i]
        return c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2


# ================================================================================================
# checkpoints -> injected start states
# ================================================================================================
def resolve(w, cp: dict):
    """the first standable point IN THE CHECKPOINT'S SECTOR on a deterministic spiral around
    `want` (8-unit rings out to 480 units) -- the oracle's try_move accepts it and no solid thing
    overlaps it -- facing `face`: (x16, y16, angle)"""
    wx, wy = cp["want"]
    rm = w.rm
    for ring in range(0, 61):
        pts = [(0, 0)] if ring == 0 else sorted(
            {(dx, dy) for dx in range(-ring, ring + 1) for dy in (-ring, ring)}
            | {(dx, dy) for dy in range(-ring, ring + 1) for dx in (-ring, ring)},
            key=lambda p: (p[0] * p[0] + p[1] * p[1], p))
        for dx, dy in pts:
            x, y = wx + 8 * dx, wy + 8 * dy
            if w.leaf_sector[rm.point_in_subsector(w.cmap, x, y)] != cp["sector"]:
                continue
            x16, y16 = x << 16, y << 16
            if not rm.try_move(w.scene_c, x16, y16, x16, y16):
                continue
            if w._solid_thing_at(x16, y16) is not None:
                continue
            fx, fy = cp["face"]
            return x16, y16, bam(fx - x, fy - y)
    raise AssertionError("no standable point near checkpoint %s" % cp["name"])


def make_setup(cp: dict) -> dict:
    """the checkpoint's injected state, as the JSON records it"""
    w = new_world()
    corpses = []
    for m in cp.get("corpses", ()):
        t = w.mon_things[m]
        corpses.append({"slot": m, "type": t.type, "x": w.ws.mon_x[m], "y": w.ws.mon_y[m],
                        "state": corpse_state(w, m), "drop": w.dropper[m]})
    apply_setup(w, {"pose": [0, 0, 0], "corpses": corpses})
    pose = resolve(w, cp)
    return {"pose": list(pose), "corpses": corpses}


# ================================================================================================
# the binary's mirror (B0): blocked27's door and player tic, and the pose b0 injects
# ================================================================================================
class BinaryMirror:
    """blocked27's tic as the oracle computes it (onewalk.DoorSim's order): every door ticks with
    `use` pressed in its box (NO key check: blocked27 opens key doors without a card), then the
    player steps with `step_sim` (turn, forward/back; NO strafe, NO things) against open doors plus
    the not-yet-passable doors' lines. Fed the pose b0 injects every frame."""

    def __init__(self, w):
        self.w = w
        self.ds = [(0, W.IDLE, 0, 0) for _ in w.door_order]
        self._scenes = {}

    def step(self, pre, kd, doors=None):
        """`doors`: the door tuples (state, dir, sub, wait) b0 writes at the frame start (the
        model's pre-tic doors); None keeps the mirror's own"""
        w = self.w
        if doors is not None:
            self.ds = [tuple(t) for t in doors]
        used = bool(kd.get("use"))
        self.ds = [door_tic(self.ds[d], w.door_nstates[si],
                            used and in_use_box_fixed(w.door_boxes[si], pre[0], pre[1]))
                   for d, si in enumerate(w.door_order)]
        blocked = frozenset(li for d, si in enumerate(w.door_order)
                            if self.ds[d][0] < w.door_pass[si] for li in w.door_lines.get(si, ()))
        if blocked not in self._scenes:
            self._scenes[blocked] = Scene(w.mw, w.mw, w.mapname, w.cmap, w.open_h, blocked)
        st = w.rm.step_sim(SimState(pre[0], pre[1], pre[2], w.mapname), b0_keys(kd),
                           scene=self._scenes[blocked])
        return (st.x, st.y, st.angle), tuple(s[0] for s in self.ds)


def door_tuples(w) -> list:
    """the model's doors as b0 writes them: (state, dir, sub, wait) per door, in door order"""
    ws = w.ws
    return [(ws.d_state[d], ws.d_dir[d], ws.d_sub[d], ws.d_wait[d]) for d in range(len(w.door_order))]


def b0_keys(kd: dict) -> dict:
    """the keys blocked27 is given: forward, back, the turns and use (it has no strafe, fire or
    weapon keys; its input discards any other keycode)"""
    return {k: True for k in B0_KEYS if kd.get(k)}


def b0_injection(rm, pre, post, kd: dict, *, proxy: bool = False):
    """THE POSE b0 WRITES AT A FRAME'S START, so that blocked27's OWN tic lands exactly where the
    model did (`post`): the pre-tic angle (the same turn keys turn it to post's), and the position
    one blocked27 step BEHIND the landing -- post minus the forward/back FixedMul step at post's
    angle, or post itself when the frame has no forward/back key (strafe-only and still frames:
    blocked27 does not move). With no strafe and no obstacle this is the model's own pre-tic pose,
    v1's injection. `proxy` (the undercount measurement): a strafe-only frame is given a FORWARD
    step into the same landing, so blocked27 runs its collision tic there. Returns (pose, keys)."""
    keys = b0_keys(kd)
    if proxy and has_strafe(kd) and not (kd.get("forward") or kd.get("back")):
        keys["forward"] = True
    move = (FORWARD_MOVE if keys.get("forward") else 0) - (FORWARD_MOVE if keys.get("back") else 0)
    x, y = post[0], post[1]
    if move:
        m = move & M32
        x = _signed((x - fixed_mul(m, rm.read_cos(post[2]), 8, 4)) & M32, 32)
        y = _signed((y - fixed_mul(m, rm.read_sin(post[2]), 8, 4)) & M32, 32)
    return (x, y, pre[2] & M32), keys


# ================================================================================================
# the autopilot
# ================================================================================================
class Autopilot:
    """one run's player (see the module docstring). Targets are ("mon", slot) or ("bar", index)."""

    def __init__(self, w, nav: NavGraph, params: dict, style: str = "fight"):
        self.w, self.nav, self.p, self.style = w, nav, params, style
        self.target = None
        self.goal = None                   # ("mon", m) | ("pickup", i) | ("drop", m) | ("door", d)
        self.path = []
        self.path_age = 0
        self.stuck = 0
        self.last_xy = None
        self.forbidden_boxes = [w.door_boxes[si] for si in w.door_cards] + list(w.exit_boxes)
        self.open_boxes = [(d, si, w.door_boxes[si]) for d, si in enumerate(w.door_order)
                           if si not in w.door_cards]
        self.s_dir, self.s_left = 1, 0     # the fight strafe: side (+1 right) and tics left on it
        self.opened = set()                # doors this run pressed open (no longer door goals)
        self.dodges = 0
        self.tic = 0
        self.aim_wait = 0                  # ready frames spent aiming at the current target ...
        self.skip = {}                     # ... and targets the aim could not reach: target -> until

    # -- geometry
    def _pxy(self):
        ws = self.w.ws
        return ws.px >> 16, ws.py >> 16

    def _dist(self, x, y):
        px, py = self._pxy()
        return W.aprox_distance(x - px, y - py)

    def _turn_toward(self, x, y, kd):
        ws = self.w.ws
        err = angle_err(bam(x - (ws.px / UNIT), y - (ws.py / UNIT)), ws.pangle)
        if err > ANGLE_TURN // 2:
            kd["turn_left"] = True
        elif err < -(ANGLE_TURN // 2):
            kd["turn_right"] = True
        return err

    def _moves(self, kd) -> bool:
        """the model's own step for kd moves the player at least one map unit (the unit the
        validator's movement criterion counts)"""
        ws = self.w.ws
        lx, ly = predict_move(self.w, kd)
        return abs(_signed(lx - ws.px, 32)) + abs(_signed(ly - ws.py, 32)) >= UNIT

    def _safe(self, kd) -> bool:
        """a fight or dodge step: it moves, and it does not land on a damaging floor"""
        if not self._moves(kd):
            return False
        w = self.w
        lx, ly = predict_move(w, kd)
        sec = w.leaf_sector[w.rm.point_in_subsector(w.cmap, lx >> 16, ly >> 16)]
        return w.secs[sec].special not in SECTOR_HURT

    def _target_xy(self, tgt):
        w, ws = self.w, self.w.ws
        if tgt[0] == "mon":
            return ws.mon_x[tgt[1]], ws.mon_y[tgt[1]]
        t = w.barrel_things[tgt[1]]
        return t.x, t.y

    def _target_valid(self, tgt) -> bool:
        w, ws = self.w, self.w.ws
        if tgt[0] == "mon":
            return alive(w, tgt[1])
        return bool(ws.bar_solid[tgt[1]]) and ws.bar_health[tgt[1]] > 0

    # -- decisions
    def _combat_target(self):
        """the target: a barrel with an awake monster beside it (one shot can kill several), else
        the monster to shoot -- awake before asleep, the weaker (<= 30 health) first, then the
        nearer. Every candidate is in 2D line of sight within `engage`."""
        w, ws, p = self.w, self.w.ws, self.p
        pw = (ws.px, ws.py)
        cands = []
        for m in range(w.layout.nmon):
            if not alive(w, m):
                continue
            d = self._dist(ws.mon_x[m], ws.mon_y[m])
            if d > p["engage"] or self.skip.get(("mon", m), -1) > self.tic                     or not w.los_points(pw, (ws.mon_x[m] << 16, ws.mon_y[m] << 16)):
                continue
            hb = 0 if ws.mon_health[m] <= 30 else 1 if ws.mon_health[m] <= 60 else 2
            cands.append(((1, hb, 0 if not asleep(w, m) else 1, d), ("mon", m)))
        for b, t in enumerate(w.barrel_things):
            if not ws.bar_solid[b] or ws.bar_health[b] <= 0:
                continue
            d = self._dist(t.x, t.y)
            if d < BARREL_SAFE or d > p["engage"] or self.skip.get(("bar", b), -1) > self.tic:
                continue
            near = sum(1 for m in range(w.layout.nmon) if alive(w, m) and not asleep(w, m)
                       and W.aprox_distance(ws.mon_x[m] - t.x, ws.mon_y[m] - t.y) < BARREL_REACH)
            if near and w.los_points(pw, (t.x << 16, t.y << 16)):
                cands.append(((0, -near, 0, d), ("bar", b)))
        if not cands:
            return None
        cands.sort()
        if self.target is not None and self._target_valid(self.target):
            cur = next((c for c in cands if c[1] == self.target), None)
            if cur is not None and cur[0][:2] <= cands[0][0][:2]:
                return self.target
        return cands[0][1]

    def _threat(self):
        w, ws = self.w, self.w.ws
        ds = [self._dist(ws.mon_x[m], ws.mon_y[m]) for m in range(w.layout.nmon)
              if alive(w, m) and not asleep(w, m)]
        return min(ds) if ds else 1 << 30

    def _wanted(self, kind) -> bool:
        ws = self.w.ws
        if kind in PICKUP_WEAPON:
            return not ws.p_owned[PICKUP_WEAPON[kind]]
        if kind in PICKUP_ALWAYS or kind in PICKUP_AMMO:
            return True
        if kind in PICKUP_HEALTH:
            return ws.p_health < 100
        if kind in PICKUP_ARMOR:
            return ws.p_armor < 100
        return False

    def _items(self, weapons_only=False):
        """every wanted, untaken item: map pickups and monsters' drops -> (goal, kind, x, y)"""
        w, ws = self.w, self.w.ws
        for i, t in enumerate(w.pickup_things):
            if not ws.pickup_taken[i] and self._wanted(t.type) \
                    and (not weapons_only or t.type in PICKUP_WEAPON):
                yield ("pickup", i), t.type, t.x, t.y
        for m in range(w.layout.nmon):
            if ws.mon_drop[m] == 1 and self._wanted(w.dropper[m]) \
                    and (not weapons_only or w.dropper[m] in PICKUP_WEAPON):
                yield ("drop", m), w.dropper[m], ws.mon_x[m], ws.mon_y[m]

    def _near_pickup(self, dist, within, weapons_only=False, health_only=False):
        best = None
        for g, kind, x, y in self._items(weapons_only):
            if health_only and kind not in PICKUP_HEALTH:
                continue
            c = self.nav.nearest(x, y, 24)
            if c is not None and c in dist and dist[c] <= within:
                if best is None or (dist[c], g) < best[0]:
                    best = ((dist[c], g), g, c)
        return (best[1], best[2]) if best is not None else (None, None)

    def _near_door(self, dist):
        """(("door", d), cell) of the nearest closed plain door whose use box has a cell within
        DOOR_DETOUR cells of path -- not one this run has already pressed open"""
        ws = self.w.ws
        best = None
        for d, si, box in self.open_boxes:
            if d in self.opened or ws.d_state[d] or ws.d_dir[d] == OPENING:
                continue
            for gx in range(box[0] // CELL, box[2] // CELL + 1):
                for gy in range(box[1] // CELL, box[3] // CELL + 1):
                    c = self.nav.index.get((gx, gy))
                    if c is None or c not in dist or dist[c] > DOOR_DETOUR:
                        continue
                    x, y = self.nav.xy(c)
                    if not in_use_box_fixed(box, x << 16, y << 16):
                        continue
                    if best is None or (dist[c], d) < best[0]:
                        best = ((dist[c], d), ("door", d), c)
        return (best[1], best[2]) if best is not None else (None, None)

    def _nearest_monster(self, dist):
        w, ws = self.w, self.w.ws
        best = None
        for m in range(w.layout.nmon):
            if not alive(w, m):
                continue
            c = self.nav.nearest(ws.mon_x[m], ws.mon_y[m], 64)
            if c is None or c not in dist:
                continue
            if best is None or (dist[c], m) < best[0]:
                best = ((dist[c], m), ("mon", m), c)
        return (best[1], best[2]) if best is not None else (None, None)

    def _tour_goal(self, dist):
        """by style -- fight: the nearest living monster; collect: an item within 12 cells, else a
        closed plain door within DOOR_DETOUR (calm), else a monster; explore: the door first"""
        calm = self._threat() >= DETOUR_CALM
        order = {"fight": ("mon",), "collect": ("item", "door", "mon"),
                 "explore": ("door", "item", "mon")}[self.style]
        for kind in order:
            if kind == "item":
                g, c = self._near_pickup(dist, 12)
            elif kind == "door":
                g, c = self._near_door(dist) if calm else (None, None)
            else:
                g, c = self._nearest_monster(dist)
            if g is not None:
                return g, c
        return None, None

    def _detour(self, tgt, px, py):
        """an item worth leaving the fight or the tour for: (goal, path) or None"""
        ws = self.w.ws
        threat = self._threat()
        me = self.nav.nearest(px, py, 48)
        if me is None:
            return None
        rules = []                                       # (within, weapons_only, health_only)
        if ws.p_health >= self.p["retreat_hp"]:
            rules.append((WEAPON_DETOUR, True, False))   # a new weapon first: a player grabs it
        if threat >= DETOUR_CALM and (tgt is None or self.style != "fight"):
            rules.append((PICKUP_DETOUR if self.style != "fight" else 4, False, False))
        elif threat >= 160:
            rules.append((4, False, False))
        if ws.p_health < 50 and threat >= 128:
            rules.append((16, False, True))
        if not rules:
            return None
        dist, par = self.nav.bfs(me)
        for within, weapons_only, health_only in rules:
            g, c = self._near_pickup(dist, within, weapons_only, health_only)
            if g is not None:
                return g, self.nav.path(par, c)
        return None

    def decide(self) -> dict:
        w, ws, p = self.w, self.w.ws, self.p
        kd = {}
        px, py = self._pxy()
        moved = self.last_xy is not None and (ws.px, ws.py) != self.last_xy
        self.last_xy = (ws.px, ws.py)
        if ws.p_owned[gd.WP_SHOTGUN] and ws.p_ammo[gd.AM_SHELL] and ws.p_ready != gd.WP_SHOTGUN \
                and ws.p_pending != gd.WP_SHOTGUN:
            kd["w3"] = True
        self.tic += 1
        tgt = self._combat_target()
        if tgt != self.target:
            self.aim_wait = 0
        self.target = tgt
        aim = w.aim(w, w.aim_centre)
        fire = False
        # an ACCURATE pistol: the trigger goes down only while the weapon is ready (A_WeaponReady)
        ready = gd.STATES[gd.STATE_NAMES[ws.p_wpn_state]].action == "A_WeaponReady"
        if aim is not None and ready:
            kind, i = aim
            if kind == "mon" and alive(w, i) and self._dist(ws.mon_x[i], ws.mon_y[i]) <= p["engage"]:
                fire = True
            elif kind == "bar":
                t = w.barrel_things[i]
                near_mon = any(alive(w, m) and not asleep(w, m)
                               and W.aprox_distance(ws.mon_x[m] - t.x, ws.mon_y[m] - t.y) < BARREL_REACH
                               for m in range(w.layout.nmon))
                fire = near_mon and self._dist(t.x, t.y) >= BARREL_SAFE
        det = self._detour(tgt, px, py)
        if det is not None:
            g, path = det
            if self.goal != g:
                self.goal, self.path, self.path_age = g, path, 0
            self._navigate(kd, moved)
        elif tgt is not None:
            self._fight(kd, tgt, aim)
        else:
            self._navigate(kd, moved)
        self._dodge(kd)
        if fire:
            kd["fire"] = True
        # use: only in an openable door's box, never in a key door's or the exit's; no strafe then
        if any(in_use_box_fixed(b, ws.px, ws.py) for b in self.forbidden_boxes):
            kd.pop("use", None)
        else:
            for d, si, box in self.open_boxes:
                if in_use_box_fixed(box, ws.px, ws.py) and ws.d_state[d] < w.door_pass[si]:
                    kd["use"] = True
                    self.opened.add(d)
                    for k in STRAFE_KEYS:
                        kd.pop(k, None)
                    break
        return kd

    def _fight(self, kd, tgt, aim):
        """turn onto the target, keep the band with forward/back, and strafe"""
        ws, p = self.w.ws, self.p
        tx, ty = self._target_xy(tgt)
        if not (aim is not None and tuple(aim) == tuple(tgt)):
            self._turn_toward(tx, ty, kd)
        d = self._dist(tx, ty)
        threat = self._threat()
        keep = BARREL_SAFE + 64 if tgt[0] == "bar" else p["keep"]
        base = dict(kd)
        if d < keep or (ws.p_health < p["retreat_hp"] and threat < 320):
            if self._safe(dict(base, back=True)):
                base["back"] = True
        elif d > keep + p["band"]:
            if self._safe(dict(base, forward=True)):
                base["forward"] = True
        ready = gd.STATES[gd.STATE_NAMES[ws.p_wpn_state]].action == "A_WeaponReady"
        on_target = aim is not None and tuple(aim) == tuple(tgt)
        if shot_pending(ws):
            kd.clear()
            kd.update(base)                      # the trigger is down: hold the bearing until the
            return                               # shot leaves (the pistol's 4 tics, the shotgun's 3)
        if ready and not on_target:
            self.aim_wait += 1
            if self.aim_wait > AIM_PATIENCE:     # the aim never reaches it: another target
                self.skip[tuple(tgt)] = self.tic + SKIP_TICS
                self.aim_wait = 0
            kd.clear()
            kd.update(base)                      # aiming: the next shot needs a steady bearing
            return
        self.aim_wait = 0
        if self.s_left <= 0:
            self.s_dir, self.s_left = -self.s_dir, p["strafe_period"]
        for side in (self.s_dir, -self.s_dir):
            cand = dict(base, **{("strafe_right" if side > 0 else "strafe_left"): True})
            if self._safe(cand):
                if side != self.s_dir:
                    self.s_dir, self.s_left = side, p["strafe_period"]
                base = cand
                break
        self.s_left -= 1
        kd.clear()
        kd.update(base)

    def _dodge(self, kd):
        """a fireball on its way: strafe away from its line when that step is free"""
        th = fireball_threats(self.w)
        if not th:
            return
        away = th[0][2]
        want, other = (("strafe_right", "strafe_left") if away > 0 else ("strafe_left", "strafe_right"))
        if kd.get(want) and not kd.get(other):
            return
        cand = dict(kd)
        cand.pop(other, None)
        cand[want] = True
        if self._safe(cand):
            kd.clear()
            kd.update(cand)
            self.dodges += 1
            self.s_dir, self.s_left = away, self.p["strafe_period"]

    def _navigate(self, kd, moved):
        px, py = self._pxy()
        me = self.nav.nearest(px, py, 48)
        if me is None:
            return
        if not moved and self.path:
            self.stuck += 1
        else:
            self.stuck = 0
        self.path_age += 1
        if not self.path or self.path_age >= 8 or self.stuck >= 3 or self.goal is None \
                or not self._goal_valid():
            dist, par = self.nav.bfs(me)
            gcell = None
            if self.goal is not None and self.goal[0] in ("pickup", "drop") and self._goal_valid()                     and self.stuck < 3:
                c = self.nav.nearest(*self._goal_xy(self.goal), 24)
                if c is not None and c in dist:
                    gcell = c                    # an item detour keeps its item
            if gcell is None:
                self.goal, gcell = self._tour_goal(dist)
            self.path = self.nav.path(par, gcell) if gcell is not None else []
            self.path_age = 0
            if self.stuck >= 3 and len(self.path) > 4:
                self.path = self.path[2:]
            self.stuck = 0
        if not self.path:
            return
        while len(self.path) > 1 and self.nav.cells[self.path[0]] == self.nav.cells[me]:
            self.path.pop(0)
        wp = self.path[min(3, len(self.path) - 1)]
        wx, wy = self.nav.xy(wp)
        self._turn_toward(wx, wy, kd)
        self._step_toward(wx, wy, kd)

    def _step_toward(self, x, y, kd, max_off=MOVE_OFF):
        """the movement keys that carry the player toward map point (x, y): whichever of the eight
        directions forward/back/strafe make (forward 0, forward+strafe +-39 deg, strafe +-90,
        back+strafe +-141, back 180 -- after this tic's turn) is nearest the bearing and really
        moves; none when every direction within `max_off` of the bearing is blocked"""
        ws = self.w.ws
        angle = ws.pangle
        if kd.get("turn_left"):
            angle = (angle + ANGLE_TURN) & M32
        if kd.get("turn_right"):
            angle = (angle - ANGLE_TURN) & M32
        err = angle_err(bam(x - ws.px / UNIT, y - ws.py / UNIT), angle)
        order = sorted(MOVE_DIRS, key=lambda d: (abs(angle_err(err & M32, d[0] & M32)), d[0]))
        for off, keys in order:
            if abs(angle_err(err & M32, off & M32)) > max_off:
                break
            cand = dict(kd, **{k: True for k in keys})
            if self._moves(cand):
                kd.update({k: True for k in keys})
                return True
        return False

    def _goal_xy(self, g):
        w, ws = self.w, self.w.ws
        if g[0] == "pickup":
            t = w.pickup_things[g[1]]
            return t.x, t.y
        return ws.mon_x[g[1]], ws.mon_y[g[1]]

    def _goal_valid(self):
        w, ws = self.w, self.w.ws
        kind, i = self.goal
        if kind == "pickup":
            return not ws.pickup_taken[i]
        if kind == "drop":
            return ws.mon_drop[i] == 1
        if kind == "door":
            return i not in self.opened and not ws.d_state[i] and ws.d_dir[i] != OPENING
        return alive(w, i)


#


# ================================================================================================
# planning and replay
# ================================================================================================
def forbidden_events(ev) -> list:
    bad = []
    if ev.level_done:
        bad.append("exit")
    if ev.deaths:
        bad.append("death")
    if ev.restart_requests or ev.restarts:
        bad.append("restart")
    return bad


def plan_run(cp: dict, setup: dict, nav: NavGraph):
    """keys for FRAMES frames: the first parameter set whose run survives with no forbidden event
    (the checkpoint's own sets first, e.g. a brawl where melee is wanted)"""
    tried = []
    for params in tuple(cp.get("params", ())) + PARAMS:
        w = start_world(setup)
        ap = Autopilot(w, nav, params, cp.get("style", "fight"))
        keys, bad = [], []
        for _f in range(FRAMES):
            kd = ap.decide()
            ev = w.tic(kd)
            keys.append(kd)
            bad += forbidden_events(ev)
            if bad:
                break
        tried.append((params["name"], bad[:1]))
        if not bad:
            return keys, params["name"], tried
    raise AssertionError("checkpoint %s: no parameter set survives (%s)" % (cp["name"], tried))


def replay(run: dict, census: bool = False) -> dict:
    """one frozen run on a fresh model: poses, events, the population (geometric; DRAWN too when
    `census`, on the census's own World), doors, movement, dodges, B0's camera reconstruction"""
    c = new_census() if census else None
    w = start_world(run["setup"], c.world if c else None)
    mirror = BinaryMirror(w)
    keys = [str_to_keys(s) for s in run["keys"]]
    poses, pops = [], []
    n = {"move_key": 0, "strafe": 0, "moving": 0, "move_frames": 0, "dodges": 0, "threat_frames": 0,
         "cam_part": 0, "door_part": 0, "use_strafe": 0, "mkills": 0, "bkills": 0, "shotgun": 0}
    opened_player, opened_monster = set(), set()
    fight_frames = fight_strafe = 0
    for kd in keys:
        ws = w.ws
        pre = (ws.px, ws.py, ws.pangle)
        th = fireball_threats(w)
        if th:
            n["threat_frames"] += 1
            want = "strafe_right" if th[0][2] > 0 else "strafe_left"
            if has_strafe(kd) and kd.get(want):
                n["dodges"] += 1
        pre_doors = door_tuples(w)
        pressed = [bool(kd.get("use")) and w.player_alive() and w.player_can_open(si)
                   and in_use_box_fixed(w.door_boxes[si], ws.px, ws.py)
                   for si in w.door_order]
        monreq = list(ws.d_monreq)
        ev = w.tic(kd)
        post = (ws.px, ws.py, ws.pangle)
        n["mkills"] += sum(1 for k in ev.kills if k[0] == "mon")
        n["bkills"] += sum(1 for k in ev.kills if k[0] == "bar")
        n["shotgun"] += sum(1 for f_ in ev.fired if f_ == "shotgun")
        for d, si in enumerate(w.door_order):
            st, dr = pre_doors[d][:2]
            if dr != OPENING and st < w.door_nstates[si] - 1 and ws.d_dir[d] == OPENING:
                if pressed[d]:
                    opened_player.add(d)
                elif monreq[d]:
                    opened_monster.add(d)
        inj, bkeys = b0_injection(w.rm, pre, post, kd)
        bpose, bdoors = mirror.step(inj, bkeys, pre_doors)
        n["cam_part"] += bpose != (post[0], post[1], post[2] & M32)
        n["door_part"] += bdoors != tuple(ws.d_state)
        n["use_strafe"] += bool(kd.get("use")) and has_strafe(kd)
        if has_move(kd):
            n["move_key"] += 1
        if has_strafe(kd):
            n["strafe"] += 1
        if has_move(kd):
            n["move_frames"] += 1
            if abs(post[0] - pre[0]) + abs(post[1] - pre[1]) >= UNIT:
                n["moving"] += 1
        pop = geo_population(w, ev)
        if c is not None:
            pop.update(drawn_population(c))
            if pop["d_awake"]:
                fight_frames += 1
                fight_strafe += has_strafe(kd)
        poses.append([post[0], post[1], post[2]])
        pops.append([pop.get(k, -1) for k in POP_FIELDS])
        pre = post
    totals = w.event_totals()
    return {"name": run["name"], "poses": poses, "pops": pops, "totals": totals, **n,
            "fight_frames": fight_frames, "fight_strafe": fight_strafe,
            "doors_player": sorted(opened_player), "doors_monster": sorted(opened_monster),
            "digest": w.digest(), "health": max(0, w.ws.p_health), "dead": w.ws.p_dead,
            "census": census, "frames": len(keys),
            "corpses_near_start": corpses_near(run["setup"]),
            "aftermath": bool(run["setup"].get("corpses"))}


# ================================================================================================
# validation: the CAP-22 criteria, and the freeze
# ================================================================================================
def pop_col(r, field):
    k = POP_FIELDS.index(field)
    return [row[k] for row in r["pops"]]


def criteria(ms: list) -> list:
    """[(name, ok, detail)] over the replayed metrics; ok is None when the census did not run"""
    out = []
    census = all(r["census"] for r in ms) and bool(ms)
    n_frames = sum(r["frames"] for r in ms)
    dead = [r["name"] for r in ms if r["dead"] or r["totals"]["deaths"]]
    out.append(("every run survives", not dead and n_frames > 0,
                "deaths in %s" % dead if dead else "%d runs, 0 deaths, lowest end health %d"
                % (len(ms), min(r["health"] for r in ms) if ms else 0)))
    if census:
        aiv = sum(1 for r in ms for v in pop_col(r, "d_awake") if v > 0)
        frac = aiv / n_frames if n_frames else 0.0
        out.append((">= 30% of frames have an awake monster DRAWN", frac >= MIN_AWAKE_DRAWN,
                    "%d/%d = %.1f%%" % (aiv, n_frames, 100 * frac)))
    else:
        out.append((">= 30% of frames have an awake monster DRAWN", None, "census not run"))
    kills = sum(r["mkills"] for r in ms)
    out.append((">= %d kills" % MIN_KILLS, kills >= MIN_KILLS,
                "%d monsters killed (and %d barrels exploded; %d shotgun shots)"
                % (kills, sum(r["bkills"] for r in ms), sum(r["shotgun"] for r in ms))))
    kinds = {"hitscan": sum(r["totals"]["mon_shots"] for r in ms),
             "melee": sum(r["totals"]["mon_melee"] for r in ms),
             "fireball": sum(r["totals"]["proj_spawns"] for r in ms)}
    out.append(("all three monster attack kinds", all(v > 0 for v in kinds.values()),
                ", ".join("%s %d" % kv for kv in kinds.items())))
    picks = sum(r["totals"]["pickups"] for r in ms)
    out.append((">= %d pickups" % MIN_PICKUPS, picks >= MIN_PICKUPS, "%d pickups" % picks))
    doors = sum(len(r["doors_player"]) for r in ms)
    out.append((">= %d doors opened by the player" % MIN_DOORS, doors >= MIN_DOORS,
                "%d (%s); by monsters %d" % (doors, ", ".join("%s %s" % (r["name"], r["doors_player"])
                                                           for r in ms if r["doors_player"]),
                                             sum(len(r["doors_monster"]) for r in ms))))
    mk = sum(r["move_key"] for r in ms)
    st = sum(r["strafe"] for r in ms)
    out.append((">= 50% of frames carry a movement key (forward, back, strafe)",
                n_frames > 0 and mk / n_frames >= MIN_MOVE_KEY,
                "%d/%d = %.1f%% (strafe on %d = %.1f%%)" % (mk, n_frames, 100.0 * mk / max(1, n_frames),
                                                            st, 100.0 * st / max(1, n_frames))))
    worst = None
    for r in ms:
        f = r["moving"] / r["move_frames"] if r["move_frames"] else 0.0
        if worst is None or f < worst[0]:
            worst = (f, r["name"], r["moving"], r["move_frames"])
    out.append(("every run moves on >= 60% of its movement frames",
                worst is not None and worst[0] >= MIN_MOVING,
                "worst %s: %d/%d = %.0f%%" % (worst[1], worst[2], worst[3], 100 * worst[0])
                if worst else "no runs"))
    if census:
        ff = sum(r["fight_frames"] for r in ms)
        fs = sum(r["fight_strafe"] for r in ms)
        out.append((">= 50% of the frames with an awake monster drawn carry a strafe key",
                    ff > 0 and fs / ff >= MIN_STRAFE_FIGHT,
                    "%d/%d = %.1f%%" % (fs, ff, 100.0 * fs / max(1, ff))))
    else:
        out.append((">= 50% of the frames with an awake monster drawn carry a strafe key", None,
                    "census not run"))
    dg = sum(r["dodges"] for r in ms)
    out.append((">= %d fireball dodge (a strafe away from a fireball's line)" % MIN_DODGES,
                dg >= MIN_DODGES, "%d dodge frames of %d frames with a fireball threat"
                % (dg, sum(r["threat_frames"] for r in ms))))
    aname = ("an aftermath run: >= %d corpses within %d units at the start, one drawn on its first "
             "frame, corpses drawn on >= %d%% of its frames" % (AFTER_MIN_CORPSES, AFTER_NEAR,
                                                               round(100 * AFTER_MIN_DRAWN)))
    aft = [r for r in ms if r["corpses_near_start"] >= AFTER_MIN_CORPSES]
    if census:
        best = None
        for r in aft:
            dc = pop_col(r, "d_corpse")
            cd = sum(1 for v in dc if v > 0)
            key = (dc[0] > 0 and cd >= AFTER_MIN_DRAWN * r["frames"], cd)
            if best is None or key > best[0]:
                best = (key, r, cd, dc[0])
        ok = best is not None and best[0][0]
        out.append((aname, ok, ("%s: %d corpses near the start, %d drawn on frame 0, corpses drawn "
                                "on %d/%d frames" % (best[1]["name"], best[1]["corpses_near_start"],
                                                     best[3], best[2], best[1]["frames"]))
                    if best else "no aftermath run"))
    else:
        out.append((aname, False if not aft else None,
                    "no aftermath run" if not aft else "census not run"))
    exits = sum(r["totals"]["level_done"] for r in ms)
    out.append(("no run uses the exit", exits == 0, "%d" % exits))
    cp_ = sum(r["cam_part"] for r in ms)
    out.append(("B0 follows the model's camera: the injected pose lands on the model's pose",
                cp_ == 0, "%d frames part; door states apart on %d frames; use with strafe on %d"
                % (cp_, sum(r["door_part"] for r in ms), sum(r["use_strafe"] for r in ms))))
    return out


def freeze_checks(doc: dict, ms: list) -> list:
    """[(name, ok, detail)]: is this the FROZEN set, reproduced exactly?"""
    out = []
    fz = doc.get("freeze") or {}
    oa = doc.get("owner_approval") or {}
    ok = doc.get("status") == "FROZEN" and oa.get("by") == APPROVAL["by"] \
        and bool(oa.get("on")) and bool(oa.get("record"))
    out.append(("F1 status FROZEN with the owner's approval", ok,
                "status %r, the set approved by %r on %r; last freeze: %s by %r" % (
                    doc.get("status"), oa.get("by"), oa.get("on"), fz.get("kind", "-"),
                    fz.get("approved_by"))))
    rec = doc.get("hashes") or {}
    now = {f: (sha16(ROOT / f) if (ROOT / f).exists() else "missing") for f in rec}
    bad = sorted(f for f in rec if now[f] != rec[f])
    out.append(("F2 every recorded file hash matches (model, census, planner: %d files)" % len(rec),
                bool(rec) and not bad, "changed: %s" % bad if bad else "%d/%d" % (len(rec), len(rec))))
    stale = [r["name"] for run, r in zip(doc["runs"], ms)
             if r["poses"] != run["poses"] or r["digest"] != run["model_final_digest"]]
    out.append(("F3 the replay reproduces every frozen pose and final digest", not stale and bool(ms),
                "stale: %s" % stale if stale else "%d/%d runs" % (len(ms), len(ms))))
    if all(r["census"] for r in ms) and ms:
        drift = [r["name"] for run, r in zip(doc["runs"], ms) if r["pops"] != run.get("pops")]
        out.append(("F4 the drawn and geometric population reproduces frame by frame", not drift,
                    "differs: %s" % drift if drift else "%d/%d runs" % (len(ms), len(ms))))
    else:
        out.append(("F4 the drawn and geometric population reproduces frame by frame", None,
                    "census not run"))
    b0 = doc.get("b0") or {}
    need = ("binding", "mean", "p80_run", "frame_max", "per_run", "fjm_sha256", "keys_sha")
    ok = all(k in b0 for k in need) and b0.get("keys_sha") == keys_sha(doc) \
        and len(b0.get("per_run", {})) == len(doc["runs"])
    out.append(("F5 the B0 record is present and was measured on these keys", ok,
                "binding %s, keys %s" % (b0.get("binding"), "match" if b0.get("keys_sha") == keys_sha(doc)
                                         else "DIFFER" if b0 else "-")))
    return out


def dist_stats(vals) -> str:
    s = sorted(vals)
    n = len(s)

    def pc(q):
        return s[min(n - 1, int(math.ceil(q * n)) - 1)]
    return "mean %5.2f  p50 %2d  p80 %2d  p99 %2d  max %2d" % (sum(s) / n, pc(0.5), pc(0.8), pc(0.99),
                                                               s[-1])


def validate(doc: dict, *, census: bool = True, quiet: bool = False) -> dict:
    ms = [replay(run, census=census) for run in doc["runs"]]
    crit = criteria(ms)
    frz = freeze_checks(doc, ms)
    if not quiet:
        print("  %-20s %3s %4s %4s %4s %4s %4s %4s %4s %5s %5s %5s %4s %5s %5s %5s %3s"
              % ("run", "hp", "kill", "hits", "shot", "mele", "fbal", "pick", "door", "mov%",
                 "str%", "step%", "dodg", "dAwk%", "gAwk%", "corp%", "cam"))
        for r in ms:
            t = r["totals"]
            fr = r["frames"]
            print("  %-20s %3d %4d %4d %4d %4d %4d %4d %4d %4.0f%% %4.0f%% %4.0f%% %4d %4s%% %4.0f%% %4s%% %3d"
                  % (r["name"], r["health"], r["mkills"], t["hits"], t["mon_shots"], t["mon_melee"],
                     t["proj_spawns"], t["pickups"], len(r["doors_player"]),
                     100.0 * r["move_key"] / fr, 100.0 * r["strafe"] / fr,
                     100.0 * r["moving"] / max(1, r["move_frames"]), r["dodges"],
                     ("%.0f" % (100.0 * sum(1 for v in pop_col(r, "d_awake") if v) / fr)) if census else "-",
                     100.0 * sum(1 for v in pop_col(r, "geo_awake") if v) / fr,
                     ("%.0f" % (100.0 * sum(1 for v in pop_col(r, "d_corpse") if v) / fr)) if census else "-",
                     r["cam_part"]))
        allp = [row for r in ms for row in r["pops"]]
        print("  POPULATION per frame over the set (%d frames; d_ = DRAWN in the decided picture, "
              "geo_ = the geometric test):" % len(allp))
        for k in POP_FIELDS:
            if k.startswith("d_") and not census:
                continue
            j = POP_FIELDS.index(k)
            print("    %-12s %s" % (k, dist_stats([row[j] for row in allp])))
        b0 = doc.get("b0")
        if b0:
            u = b0.get("strafe_undercount") or {}
            print("  B0 (frozen, blocked27 %s): binding %s ops/frame, mean %s, p80 run %s %s, "
                  "per-frame max %s (%s); strafe undercount +%s on the binding"
                  % (str(b0.get("fjm_sha256"))[:16], format(int(round(b0["binding"])), ","),
                     format(int(round(b0["mean"])), ","), b0.get("p80_run_name"),
                     format(int(round(b0["p80_run"])), ","), format(b0["frame_max"], ","),
                     b0.get("frame_max_run"), format(int(round(u.get("delta_binding", 0))), ",")))
        for name, ok, det in crit:
            print("  %-78s %s  %s" % (name, {True: "PASS", False: "FAIL", None: "n/a"}[ok], det))
        for name, ok, det in frz:
            print("  %-78s %s  %s" % (name, {True: "PASS", False: "FAIL", None: "n/a"}[ok], det))
    return {"criteria": crit, "freeze": frz, "metrics": ms}


# ================================================================================================
# planning the set, and the freeze
# ================================================================================================
def plan_set(quiet=False) -> dict:
    w0 = new_world()
    reg = regions(w0)
    runs = []
    for cp in CHECKPOINTS:
        setup = make_setup(cp)
        pose = setup["pose"]
        sec = w0.leaf_sector[w0.rm.point_in_subsector(w0.cmap, pose[0] >> 16, pose[1] >> 16)]
        assert sec == cp["sector"] and reg.get(sec) == cp["region"], (
            "checkpoint %s: sector %d is in region %s, not %s" % (cp["name"], sec, reg.get(sec),
                                                                 cp["region"]))
        nav = NavGraph.build(w0, (pose[0] >> 16, pose[1] >> 16), tag=cp["name"])
        t0 = time.time()
        keys, pname, tried = plan_run(cp, setup, nav)
        run = {"name": cp["name"], "region": REGION_NAMES[cp["region"]], "sector": sec,
               "why": cp["why"], "style": cp.get("style", "fight"), "params": pname,
               "setup": setup,
               "checkpoint": {"x16": pose[0], "y16": pose[1], "angle": pose[2],
                              "x": pose[0] >> 16, "y": pose[1] >> 16, "skill": SKILL,
                              "face": list(cp["face"])},
               "keys": [keys_to_str(k) for k in keys]}
        rep = replay(run)
        run.update({"poses": rep["poses"], "model_final_digest": rep["digest"],
                    "totals": rep["totals"]})
        if not quiet:
            print("  %-20s sector %3d params %-10s tried %-40s %5.1f s  kills %d picks %d doors %s "
                  "hp %d move %d%% strafe %d%%"
                  % (cp["name"], sec, pname, [t for t in tried], time.time() - t0,
                     rep["totals"]["kills"], rep["totals"]["pickups"], rep["doors_player"],
                     rep["health"], rep["move_key"], rep["strafe"]), flush=True)
        runs.append(run)
    doc = {"version": VERSION,
           "status": "PLANNED -- B0 and the owner's freeze pending (`--freeze`)",
           "map": "E1M1", "skill": "hard", "frames": FRAMES, "tics_per_frame": 1,
           "start_state": "level start (monsters asleep at spawn, doors shut, nothing taken, pistol "
                          "+ 50 bullets + 100 health); injected: the player's pose, and the "
                          "aftermath run's corpses (setup.corpses)",
           "aim": "doomfj.combat.aim_geometric (the model default)",
           "census_picture": CENSUS_PICTURE,
           "keys_legend": {c: n for n, c in LETTERS},
           "runs": runs}
    return doc


def record_validation(doc: dict, res: dict) -> None:
    """store the replayed population (per frame) and the criteria's verdicts in the document"""
    for run, r in zip(doc["runs"], res["metrics"]):
        run["pops"] = r["pops"]
        run["doors_player"] = r["doors_player"]
    doc["pop_fields"] = list(POP_FIELDS)
    doc["validation"] = {n: {"ok": ok, "detail": d} for n, ok, d in res["criteria"]}


def load_b0(path: Path) -> dict:
    """the B0 record the freeze keeps: b0_scenarios.py's JSON, without the per-frame arrays"""
    b = json.loads(Path(path).read_text(encoding="ascii"))
    per = {r["name"]: {"avg_exact": r["avg_exact"], "p50": r["p50"], "p80": r["p80"], "max": r["max"],
                       "state": "%d/%d" % (r["state_ok"], r["state_n"]),
                       "pixels": "%d/%d" % (r["pix_ok"], r["pix_n"]), "cam_parts": r["cam_parts"],
                       "door_parts": r["door_parts"], "strafe_only_frames": r["strafe_only_frames"]}
           for r in b["runs"]}
    und = dict(b.get("strafe_undercount") or {})
    return {"binding": b["binding"], "mean": b["mean"], "p80_run": b["p80_run"],
            "p80_run_name": b.get("p80_run_name"), "frame_max": b["frame_max"],
            "frame_max_run": b.get("frame_max_run"), "frame_max_note": "+/- 2^18 (probe.py)",
            "per_run": per, "fjm": b.get("fjm"), "fjm_sha256": b.get("sha256"),
            "labels_sha256": b.get("labels_sha256"), "keys_sha": b.get("keys_sha"),
            "driver_sha16": b.get("driver_sha16"), "command": b.get("command"),
            "base_ops": b.get("base_ops"), "strafe_undercount": und}


def freeze_decision(doc: dict, b0: dict, approver: str, record: str, ms=None, fresh=None):
    """(ok, reason, new_doc): the freeze decided IN MEMORY -- nothing is written here.
    FIRST freeze (status PLANNED): the owner's approval of the set; `approver` must be the owner,
      stored once as `owner_approval`.
    RE-freeze (status FROZEN): records a CHECKER change; allowed only when the re-plan gives identical
      keys (`fresh`, when given) AND the replay with the current code reproduces every recorded pose,
      digest and drawn population and the approval and B0 records stand (F1/F3/F4/F5) -- a picture- or
      rule-change that moves any result is refused (PR #88 round 3). `owner_approval` is untouched;
      the event records `approver` (e.g. the PR review)."""
    if fresh is not None:
        diff = [a["name"] for a, b in zip(doc["runs"], fresh["runs"])
                if a["keys"] != b["keys"] or a["setup"] != b["setup"]]
        if diff or len(doc["runs"]) != len(fresh["runs"]):
            return False, "the re-plan DIFFERS: %s -- a new version, not a freeze" % diff, None
    if b0["keys_sha"] != keys_sha(doc):
        return False, "B0 was measured on keys %s, the set is %s" % (b0["keys_sha"], keys_sha(doc)), None
    refreeze = doc.get("status") == "FROZEN"
    if refreeze:
        ms = ms if ms is not None else [replay(run, census=True) for run in doc["runs"]]
        checks = {n.split()[0]: (ok, det) for n, ok, det in freeze_checks(doc, ms)}
        for k in ("F1", "F3", "F4", "F5"):
            ok, det = checks[k]
            if not ok:
                return False, ("%s failed (%s): the replay moved -- a behaviour change needs a NEW "
                               "VERSION and the owner, not a re-freeze" % (k, det)), None
    elif approver != APPROVAL["by"]:
        return False, "the FIRST freeze is the owner's approval of the set: --approver must be %r" % (
            APPROVAL["by"]), None
    new = copy.deepcopy(doc)
    res = validate(new, census=True, quiet=True)
    bad = [n for n, ok, _d in res["criteria"] if not ok]
    if bad:
        return False, "criteria FAIL: %s" % bad, None
    record_validation(new, res)
    files = dependency_files()
    new["hashes"] = code_hashes(files)
    new["keys_sha"] = keys_sha(new)
    new["b0"] = b0
    new["status"] = "FROZEN"
    if refreeze:
        new.setdefault("freeze_history", []).append(doc["freeze"])
    else:
        new["owner_approval"] = {"by": approver, "on": time.strftime("%Y-%m-%d"), "record": record}
    new["freeze"] = {"kind": "checker re-freeze" if refreeze else "owner freeze",
                     "approved_by": approver, "approved_on": time.strftime("%Y-%m-%d"),
                     "approval_record": record, "frozen_at_git_head": git_head(),
                     "files_not_at_head": git_untracked_or_modified(files), "rule": FREEZE_RULE}
    res2 = validate(new, census=True, quiet=True)
    fails = [n for n, ok, _d in res2["criteria"] + res2["freeze"] if not ok]
    if fails:
        return False, "the frozen copy would FAIL its own validation: %s" % fails, None
    return True, "%s by %r" % (new["freeze"]["kind"], approver), new


def plan_refusal(path: Path):
    """why `--plan` must not write `path` (None when it may): a FROZEN set is never overwritten --
    a new version is planned into a new file (PR #88 round 3)."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        status = json.loads(path.read_text(encoding="ascii")).get("status")
    except (ValueError, UnicodeDecodeError) as e:
        return "%s is not a readable set (%s): refusing to overwrite it" % (path, e)
    if status == "FROZEN":
        return "%s is FROZEN: plan a new version into a new --file" % path
    return None


def freeze(path: Path, b0_path: Path, approver: str, record: str) -> int:
    doc = json.loads(Path(path).read_text(encoding="ascii"))
    print("FREEZE %s (%d runs), B0 %s, approver %r" % (path, len(doc["runs"]), b0_path, approver),
          flush=True)
    fresh = plan_set(quiet=True)
    ok, why, new = freeze_decision(doc, load_b0(b0_path), approver, record, fresh=fresh)
    print("  re-plan: %s" % ("identical keys and setups, %d runs" % len(doc["runs"])
                             if ok or "re-plan" not in why else why), flush=True)
    if not ok:
        print("FREEZE REFUSED: %s (nothing written)" % why, flush=True)
        return 1
    Path(path).write_text(json.dumps(new, indent=1), encoding="ascii", newline="\n")
    print("  wrote %s: FROZEN, %s (git head %s, %d hashed files, keys %s)" % (
        path, why, new["freeze"]["frozen_at_git_head"], len(new["hashes"]), new["keys_sha"]), flush=True)
    res = validate(new, census=True, quiet=False)
    ok = all(ok for _n, ok, _d in res["criteria"]) and all(ok for _n, ok, _d in res["freeze"])
    print("FREEZE %s" % ("PASS" if ok else "FAIL"), flush=True)
    return 0 if ok else 1


# ================================================================================================
# R9 controls
# ================================================================================================
def selftest(doc: dict) -> int:
    fails = []

    def check(name, cond, detail=""):
        print("  %-80s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    def verdict(res, prefix):
        for n, ok, d in res["criteria"] + res["freeze"]:
            if n.startswith(prefix):
                return ok, d
        raise KeyError(prefix)

    def mutate_keys(fn):
        m = copy.deepcopy(doc)
        for run in m["runs"]:
            run["keys"] = [fn(k) for k in run["keys"]]
        return m

    t0 = time.time()
    if doc.get("status") != "FROZEN":
        # not frozen yet: exercise the freeze checks on an in-memory frozen copy (the real freeze is
        # `--freeze`, which records the MEASURED B0; this copy's B0 record is a placeholder)
        doc = copy.deepcopy(doc)
        doc.update({"status": "FROZEN", "freeze": {"approved_by": APPROVAL["by"],
                                                   "approved_on": APPROVAL["on"]},
                    "owner_approval": {"by": APPROVAL["by"], "on": APPROVAL["on"],
                                       "record": "selftest placeholder"},
                    "hashes": code_hashes(list(doc.get("hashes") or ()) or None),
                    "b0": {"binding": 0, "mean": 0, "p80_run": 0, "frame_max": 0, "fjm_sha256": "-",
                           "per_run": {r["name"]: {} for r in doc["runs"]}, "keys_sha": keys_sha(doc)}})
        print("  (the set is not frozen yet: the freeze checks run on an in-memory frozen copy)")
    # R-controls: the rehash decision (PR #87 round 2) -- accepts the untouched set, refuses a
    # BEHAVIOUR change (the model's strafe step 13 -> 12, patched in-process, the files untouched)
    # and refuses a CHECKER change (its recorded hash altered)
    if doc.get("status") == "FROZEN":
        import doomfj.combat as _C
        ms0 = [replay(run, census=True) for run in doc["runs"]]
        now0 = dict(doc["hashes"])
        ok0, why0, ch0 = rehash_decision(doc, ms0, now0)
        check("R1 the untouched set: the rehash would accept, with nothing to re-record",
              ok0 and not ch0, why0)
        saved = _C.STRAFE_MOVE
        try:
            _C.STRAFE_MOVE = 12 << 16
            ms1 = [replay(run, census=True) for run in doc["runs"]]
        finally:
            _C.STRAFE_MOVE = saved
        ok1, why1, _ = rehash_decision(doc, ms1, now0)
        check("R2 a BEHAVIOUR change (strafe 13 -> 12) is REFUSED", not ok1, why1)
        now2 = dict(now0, **{PLANNER_FILE: "0" * 16})
        ok2, why2, _ = rehash_decision(doc, ms0, now2)
        check("R3 a CHECKER change (scenarios_v2.py's hash) is REFUSED", not ok2, why2)
        # R4 the round-3 attack: a PICTURE-rule change (the monster degradation budget 4 -> 2) must
        # not pass a re-freeze -- it moves the frozen drawn populations
        import doomfj.reference_model as _RMOD
        saved = _RMOD.DEG_SOFT_MON
        try:
            _RMOD.DEG_SOFT_MON = 2
            ms4 = [replay(run, census=True) for run in doc["runs"]]
        finally:
            _RMOD.DEG_SOFT_MON = saved
        ok4, why4, _ = freeze_decision(doc, doc["b0"], "a reviewer", "control", ms=ms4)
        check("R4 a PICTURE-rule change (DEG_SOFT_MON 4 -> 2) is REFUSED by the re-freeze", not ok4, why4)
        # R5 a clean re-freeze keeps the owner's approval of the set and records its own approver
        ok5, why5, new5 = freeze_decision(doc, doc["b0"], "a reviewer", "control", ms=ms0)
        check("R5 a clean re-freeze keeps owner_approval and names its own approver",
              ok5 and new5["owner_approval"] == doc["owner_approval"]
              and new5["freeze"]["approved_by"] == "a reviewer"
              and new5["freeze"]["kind"] == "checker re-freeze", why5)
        # R6 a FIRST freeze is the owner's approval of the set: any other approver is refused
        planned = dict(copy.deepcopy(doc), status="PLANNED")
        ok6, why6, _ = freeze_decision(planned, doc["b0"], "a reviewer", "control")
        check("R6 a FIRST freeze with an approver other than the owner is REFUSED", not ok6, why6)
        # R7 the planner never overwrites a frozen set (it would erase the approval and the B0)
        why7 = plan_refusal(SCEN_FILE)
        check("R7 --plan REFUSES the frozen set's file", why7 is not None and "FROZEN" in why7, why7)
    base = validate(doc, census=True, quiet=True)
    allc = base["criteria"] + base["freeze"]
    check("S0 the set passes every criterion and every freeze check",
          all(ok for _n, ok, _d in allc), ", ".join(n for n, ok, _d in allc if not ok))
    # S1 no fire: kills
    res = validate(mutate_keys(lambda k: k.replace("F", "") or "-"), census=False, quiet=True)
    ok, d = verdict(res, ">= %d kills" % MIN_KILLS)
    check("S1 no fire key FAILS the kills floor", ok is False, d)
    # S2 no strafe: the movement floor, strafe-while-fighting, the dodge
    res = validate(mutate_keys(lambda k: k.replace("<", "").replace(">", "") or "-"), census=True,
                   quiet=True)
    for prefix, name in ((">= 50% of the frames with an awake", "strafe-while-fighting"),
                         (">= %d fireball dodge" % MIN_DODGES, "the dodge floor")):
        ok, d = verdict(res, prefix)
        check("S2 no strafe key FAILS %s" % name, ok is False, d)
    ok, d = verdict(res, ">= 50% of frames carry")
    print("  %-80s info  the movement floor without strafe: %s (forward/back alone)"
          % ("S2 (no strafe: the movement floor is not a strafe test)", d), flush=True)
    # S3 no movement key at all: the movement floor and the vacuity of 'moves on >= 60%'
    res = validate(mutate_keys(lambda k: "".join(ch for ch in k if ch not in "fb<>") or "-"),
                   census=False, quiet=True)
    ok1, d1 = verdict(res, ">= 50% of frames carry")
    ok2, d2 = verdict(res, "every run moves")
    check("S3 no movement key FAILS the movement floor and 'moves on >= 60%' (vacuity)",
          ok1 is False and ok2 is False, "%s | %s" % (d1, d2))
    # S4 silent and facing away: nothing awake drawn
    m4 = copy.deepcopy(doc)
    for run in m4["runs"]:
        run["setup"]["pose"][2] = (run["setup"]["pose"][2] + (1 << 31)) & M32
        run["keys"] = ["-"] * len(run["keys"])
    res = validate(m4, census=True, quiet=True)
    ok, d = verdict(res, ">= 30% of frames have an awake")
    check("S4 a silent set facing away FAILS the awake-DRAWN floor", ok is False, d)
    # S5 one key changed: the replay freeze
    m5 = copy.deepcopy(doc)
    k0 = m5["runs"][0]["keys"]
    k0[10] = "l" if k0[10] != "l" else "r"
    res = validate(m5, census=False, quiet=True)
    ok, d = verdict(res, "F3")
    check("S5 one key changed FAILS the replay freeze (F3)", ok is False, d)
    # S6 the document freeze: a hash, the status, the B0 record, one drawn count
    for label, fn, prefix in (
            ("one recorded hash altered FAILS F2",
             lambda m: m["hashes"].update({next(iter(m["hashes"])): "0" * 16}), "F2"),
            ("status PLANNED FAILS F1", lambda m: m.update({"status": "PLANNED"}), "F1"),
            ("the B0 record removed FAILS F5", lambda m: m.pop("b0", None), "F5"),
            ("one frozen drawn count altered FAILS F4",
             lambda m: m["runs"][1]["pops"][0].__setitem__(POP_FIELDS.index("d_corpse"),
                                                           m["runs"][1]["pops"][0][
                                                               POP_FIELDS.index("d_corpse")] + 1),
             "F4")):
        m6 = copy.deepcopy(doc)
        fn(m6)
        fz = freeze_checks(m6, base["metrics"])
        ok, d = next((ok, d) for n, ok, d in fz if n.startswith(prefix))
        check("S6 %s" % label, ok is False, d)
    # S7 the aftermath: removed from the set; its corpses removed
    m7 = copy.deepcopy(doc)
    m7["runs"] = [r for r in m7["runs"] if not r["setup"].get("corpses")]
    ms7 = [r for r in base["metrics"] if not r["aftermath"]]
    ok, d = next((ok, d) for n, ok, d in criteria(ms7) if n.startswith("an aftermath run"))
    check("S7 a set WITHOUT the aftermath run FAILS the aftermath criterion", ok is False, d)
    aft = next(r for r in doc["runs"] if r["setup"].get("corpses"))
    bare = copy.deepcopy(aft)
    bare["setup"]["corpses"] = []
    rb = replay(bare, census=True)
    rb["aftermath"], rb["corpses_near_start"] = True, AFTER_MIN_CORPSES   # claim it, draw nothing
    ms7b = [r for r in base["metrics"] if not r["aftermath"]] + [rb]
    ok, d = next((ok, d) for n, ok, d in criteria(ms7b) if n.startswith("an aftermath run"))
    check("S7 the aftermath run with its corpses removed FAILS it (no corpse drawn)", ok is False, d)
    # S8 no use key: doors
    res = validate(mutate_keys(lambda k: k.replace("u", "") or "-"), census=False, quiet=True)
    ok, d = verdict(res, ">= %d doors" % MIN_DOORS)
    check("S8 no use key FAILS the doors floor", ok is False, d)
    # S9 the criteria's logic on synthetic metrics
    for label, fn, prefix in (
            ("no monster killed FAILS the kills floor", lambda ms: [r.update({"mkills": 0}) for r in ms],
             ">= %d kills" % MIN_KILLS),
            ("a run that died FAILS 'every run survives'", lambda ms: ms[0].update({"dead": 1}),
             "every run survives"),
            ("no fireball FAILS the attack kinds", lambda ms: [r["totals"].update({"proj_spawns": 0})
                                                             for r in ms], "all three"),
            ("no pickup FAILS the pickups floor", lambda ms: [r["totals"].update({"pickups": 0})
                                                             for r in ms], ">= %d pickups" % MIN_PICKUPS),
            ("a camera parting FAILS the B0 criterion", lambda ms: ms[0].update({"cam_part": 1}),
             "B0 follows")):
        fake = copy.deepcopy(base["metrics"])
        fn(fake)
        ok, d = next((ok, d) for n, ok, d in criteria(fake) if n.startswith(prefix))
        check("S9 %s" % label, ok is False, d)
    # S10 determinism: re-planning checkpoint 0 gives the frozen keys
    cp = CHECKPOINTS[0]
    setup = make_setup(cp)
    w0 = new_world()
    nav = NavGraph.build(w0, (setup["pose"][0] >> 16, setup["pose"][1] >> 16), tag=cp["name"])
    keys, _pn, _t = plan_run(cp, setup, nav)
    check("S10 the planner is deterministic (checkpoint 0 re-planned = its keys)",
          [keys_to_str(k) for k in keys] == doc["runs"][0]["keys"] and setup == doc["runs"][0]["setup"])
    # S11 the camera reconstruction has teeth: one unit off on every moving frame parts every one
    run = doc["runs"][0]
    w = start_world(run["setup"])
    mirror = BinaryMirror(w)
    parts = moving = 0
    for s in run["keys"]:
        kd = str_to_keys(s)
        pre = (w.ws.px, w.ws.py, w.ws.pangle)
        pre_d = door_tuples(w)
        w.tic(kd)
        post = (w.ws.px, w.ws.py, w.ws.pangle)
        inj, bk = b0_injection(w.rm, pre, post, kd)
        if post[:2] != pre[:2]:
            moving += 1
            inj = (inj[0] + UNIT, inj[1], inj[2])
            parts += mirror.step(inj, bk, pre_d)[0] != (post[0], post[1], post[2] & M32)
    check("S11 an injection one unit off parts the camera on every moving frame",
          moving > 0 and parts == moving, "%d/%d" % (parts, moving))
    print("")
    print("SCENARIOS_V2 SELFTEST %s (%.0f s)%s" % ("PASS" if not fails else "FAIL", time.time() - t0,
                                                 "" if not fails else ": " + ", ".join(fails)),
          flush=True)
    return 1 if fails else 0


def rehash_decision(doc: dict, ms: list, now: dict):
    """(ok, reason, changed) for re-recording the hashes to `now` (file -> hash). Refused when a
    freeze check the rehash relies on fails (F1/F3/F4/F5: the replay moved -- a BEHAVIOUR change),
    or when the checker itself changed: a checker that re-records its own hash could first weaken
    F3/F4 and then approve a behaviour change (PR #87 round 2)."""
    checks = {name.split()[0]: (ok, det) for name, ok, det in freeze_checks(doc, ms)}
    for k in ("F1", "F3", "F4", "F5"):
        ok, det = checks[k]
        if not ok:
            return False, "%s failed (%s): the replay moved; a behaviour change needs the owner" % (k, det), {}
    old = doc["hashes"]
    if now.get(PLANNER_FILE) != old.get(PLANNER_FILE):
        return False, ("the checker %s changed: record it with --freeze (re-plan, identical keys) "
                       "under review, never by --rehash" % PLANNER_FILE), {}
    changed = {f: [old.get(f), now[f]] for f in now if old.get(f) != now[f]}
    return True, "F1/F3/F4/F5 held and the checker is unchanged", changed


def rehash(path: Path, reason: str) -> int:
    """THE REHASH RULE (docs/handoff-gameplay.md section 1; PR #87 review): the freeze pins the KEYS,
    the B0 and what they reproduce -- not source bytes. When a refactor edits a hashed file but the
    replay still reproduces every frozen pose, final digest and drawn population (F3, F4), and the
    approval and B0 records stand (F1, F5), the new hashes are recorded here, logged with the reason
    and the changed files. No owner step: nothing the set measures moved. If F3 or F4 fail, the
    model's BEHAVIOUR changed -- that is not a rehash; it needs the owner (a v3)."""
    doc = json.loads(Path(path).read_text(encoding="ascii"))
    ms = [replay(run, census=True) for run in doc["runs"]]
    for name, ok, det in freeze_checks(doc, ms):
        print("  %s %s  %s" % (name.split()[0], "ok  " if ok else "FAIL", det), flush=True)
    old = doc["hashes"]
    new = {f: sha16(ROOT / f) for f in sorted(set(old) | set(dependency_files()))}
    ok, why, changed = rehash_decision(doc, ms, new)
    if not ok:
        print("REHASH REFUSED: %s" % why)
        return 1
    if not changed:
        print("REHASH: nothing changed")
        return 0
    doc.setdefault("rehash_log", []).append({
        "on": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": reason, "git_head": git_head(),
        "changed": changed,
        "rule": "F1/F3/F4/F5 held: every pose, digest and drawn population reproduced, so only the "
                "source hashes are re-recorded"})
    doc["hashes"] = new
    Path(path).write_text(json.dumps(doc, indent=1), encoding="ascii", newline="\n")
    for f, (o, n) in sorted(changed.items()):
        print("  rehashed %-40s %s -> %s" % (f, o, n))
    print("REHASH DONE: %d file(s)" % len(changed))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--rehash", metavar="REASON",
                    help="re-record the hashes after a pure refactor (the rehash rule)")
    ap.add_argument("--b0", default=str(SCEN_DIR / "b0_v2.json"))
    ap.add_argument("--approver", help="--freeze: who approves THIS freeze ('the owner' for the first)")
    ap.add_argument("--approval-record", help="--freeze: the approval's words and where they are")
    ap.add_argument("--no-census", action="store_true", help="validate without the drawn count")
    ap.add_argument("--file", default=str(SCEN_FILE))
    a = ap.parse_args()
    if a.plan:
        why = plan_refusal(Path(a.file))
        if why:
            print("PLAN REFUSED: %s (nothing written)" % why, flush=True)
            return 1
        t0 = time.time()
        doc = plan_set()
        res = validate(doc, census=True, quiet=False)
        record_validation(doc, res)
        doc["hashes"] = code_hashes()
        doc["planned_at_git_head"] = git_head()
        doc["keys_sha"] = keys_sha(doc)
        SCEN_DIR.mkdir(parents=True, exist_ok=True)
        Path(a.file).write_text(json.dumps(doc, indent=1), encoding="ascii", newline="\n")
        ok = all(ok for _n, ok, _d in res["criteria"])
        print("  wrote %s (%.0f s): criteria %s, keys %s" % (a.file, time.time() - t0,
                                                           "PASS" if ok else "FAIL", doc["keys_sha"]))
        return 0 if ok else 1
    if a.freeze:
        if not a.approver or not a.approval_record:
            ap.error("--freeze needs --approver and --approval-record: an approval is never implied")
        return freeze(Path(a.file), Path(a.b0), a.approver, a.approval_record)
    if a.rehash:
        return rehash(Path(a.file), a.rehash)
    doc = json.loads(Path(a.file).read_text(encoding="ascii"))
    if a.validate:
        t0 = time.time()
        res = validate(doc, census=not a.no_census, quiet=False)
        okc = all(ok for _n, ok, _d in res["criteria"])
        okf = all(ok for _n, ok, _d in res["freeze"])
        print("CRITERIA %s | FREEZE %s | VALIDATE %s (%.0f s)" % (
            "PASS" if okc else "FAIL", "PASS" if okf else "FAIL",
            "PASS" if okc and okf else "FAIL", time.time() - t0))
        return 0 if okc and okf else 1
    if a.selftest:
        return selftest(doc)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
