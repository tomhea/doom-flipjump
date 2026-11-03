"""M8 (E1M4 at easy): the bot's health rules for a map whose health lies far apart and whose route is mostly pickups.

THE RULES (scripts/play.py Steer):
  * ITEM_SEEK_HP -- a ROUTE pickup's leg (`item:<type>`, planned by level_route) under ITEM_SEEK_HP health seeks health
    first, as every other leg does. Before it the health block skipped every item leg, and E1M4's armor leg (316 cells,
    item:2018) crossed the map at 1-6 health: the 35-attempt search's best play died on it at world 5489.
    Only a LONG one (ITEM_SEEK_LEN cells planned or more): E1M5's and E1M9's pinned plays died with it on shorter legs.
  * SEEK_FAR -- a very low seek (SEEK_FAR_MOST cells allowed) whose three nearest items (in a straight line) have no
    path tries the nearest BY PATH of the rest (one flood). On the armor leg at (1768, 920) the three nearest have no
    path; the stimpack at (816, 1840) has one.
  * FLOORS_SEEN -- a floor group the game moved to its end (the wide `fswitch` vector) joins the steering's world: E1M4's
    group 0 (sector 43) is lowered by the W1 square round the yellow card -- a KEY leg, so no leg ever put "floor:0"
    in the world, and the medikits behind it (-1344, 720), (-576, 720) were out of every seek's reach.
CONTROLS (R9): ITEM_SEEK_HP 0 -> the same cells keep the pickup leg; SEEK_FAR off -> the same seek finds nothing; a
seek that is not very low (70 cells) does not use the far rule either; FLOORS_SEEN off -> the same cells leave the
world as it was and the seek by the card finds no medikit; group 0 short of its end -> not added.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WAD = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not WAD.exists(), reason="needs assets/freedoom1.wad (E1M4)")


# the route's long pickup leg across the nukage channel (MAP_PICKUPS made it the medikit's at (3264, 1216); before
# them it was the armor's): the leg the long-leg rules are about
LONG = "item:2012"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mods():
    lr = _load("level_route", "scripts/level_route.py")
    return lr, _load("play", "scripts/play.py"), lr.plan("E1M4", "easy")


def _steer(mods, leg_to):
    _lr, play, route = mods
    st = play.Steer(route, log=lambda s: None, seed=0)
    li = next(i for i, g in enumerate(st.legs) if g["to"] == leg_to)
    st.active = {g["to"] for g in st.legs[:li] if g["kind"] != "item" and not g["to"].startswith("key:")}
    st.keys = {g["to"][4:] for g in st.legs[:li] if g["to"].startswith("key:")}
    st._leg(li)
    return play, st, li


def _cells(st, x, y, hp):
    return {"mode": 0, "p_dead": 0, "p_rct": 0, "viewx": (int(x) << 16) & 0xFFFFFFFF,
            "viewy": (int(y) << 16) & 0xFFFFFFFF, "viewangle": 0, "p_hp": hp, "p_ar": 0, "p_rad": 0,
            "am_clip": 50, "am_shell": 10, "wp_own": 0, "dstate": [0] * len(st.dorder),
            "lstate": [0] * len(st.lorder), "aim_sid": ()}


@pytest.mark.parametrize("knob", [30, 0])
def test_route_pickup_leg_seeks_health_when_very_low(mods, knob):
    play, st, li = _steer(mods, LONG)
    st.ITEM_SEEK_HP = knob
    x, y = st.legs[li]["path"][0]
    st.decide(100, _cells(st, x, y, 10))
    if knob:
        assert st.legs[st.li]["to"] == "health", st.legs[st.li]["to"]
        assert st.legs[st.li + 1]["to"] == LONG
    else:
        assert st.legs[st.li]["to"] == LONG, "CONTROL: the pickup leg sought health with the rule off"
    st2 = _steer(mods, LONG)[1]                      # and at 60 health the rule leaves the leg alone
    st2.decide(100, _cells(st2, x, y, 60))
    assert st2.legs[st2.li]["to"] == LONG


def test_very_low_seek_takes_the_nearest_by_path(mods):
    play, st, li = _steer(mods, LONG)
    st.SEEK_AVOID = ()                                         # (SEEK_FAR alone)
    assert st._seek_health(100, 1768, 920, st.health, "health", most=250, radius=3000)
    assert st.legs[st.li]["to"] == "health" and st.legs[st.li]["goal"] == [816, 1840]
    play, st, li = _steer(mods, LONG)
    st.SEEK_AVOID = ()                                         # (SEEK_FAR alone)
    st.SEEK_FAR = False
    assert not st._seek_health(100, 1768, 920, st.health, "health", most=250, radius=3000), \
        "CONTROL: the three nearest alone found a way (the far rule is not what found it)"
    play, st, li = _steer(mods, LONG)
    st.SEEK_AVOID = ()                                         # (SEEK_FAR alone)
    assert not st._seek_health(100, 1768, 920, st.health, "health", most=70, radius=3000), \
        "CONTROL: a seek that is not very low used the far rule"


@pytest.mark.parametrize("on", [True, False])
def test_a_moved_floor_joins_the_world(mods, on):
    play, st, li = _steer(mods, "item:2048")                  # the leg after the yellow card
    st.FLOORS_SEEN = on
    n = st.lv.mp.groups[0].n
    c = _cells(st, -960, 640, 20)
    c["fswitch"] = (n - 2, 0, 0, 0)                            # still moving: not yet
    st._floors_seen(100, c)
    assert "floor:0" not in st.active
    c["fswitch"] = (n - 1, 0, 0, 0)                            # at its end
    if on:
        st._floors_seen(101, c)
        assert "floor:0" in st.active and "floor:1" not in st.active
    else:
        st.decide(101, c)
        assert "floor:0" not in st.active, "CONTROL: the floor joined the world with the rule off"
    st._leg(li)
    got = st._seek_health(102, -960, 640, [(-1344, 720), (-576, 720)], "health", most=70, radius=900)
    assert got == on, "CONTROL: a medikit behind the raised floor was found" if not on else "no medikit found"


def test_a_short_pickup_leg_keeps_the_old_rule(mods):
    """ITEM_SEEK_LEN: E1M4's clip-box leg (62 cells) at 10 health goes on -- the pinned plays' short pickup legs (E1M5,
    E1M9) died when the rule covered them; CONTROL: ITEM_SEEK_LEN 0 on the same cells seeks"""
    for length, want in ((None, "item:2048"), (0, "health")):
        play, st, li = _steer(mods, "item:2048")
        if length is not None:
            st.ITEM_SEEK_LEN = length
        x, y = st.legs[li]["path"][0]
        st.decide(100, _cells(st, x, y, 10))
        assert st.legs[st.li]["to"] == want, (length, st.legs[st.li]["to"])


@pytest.mark.parametrize("window", [120, 0])
def test_a_moved_floor_lets_a_short_pickup_leg_seek(mods, window):
    """FLOOR_SEEK_F: for a while after a moved floor joined the world, a short pickup leg seeks health too -- E1M4's
    yellow card opens the way to two medikits 22-27 cells off, and the clip-box leg after it walked away from them at 1
    health; CONTROL: FLOOR_SEEK_F 0 -> the leg goes on"""
    play, st, li = _steer(mods, "item:2048")
    st.FLOOR_SEEK_F = window
    st.health_taken |= {(-864, 288), (-1056, 288)}           # the two stimpacks by the card: taken on the way
    c = _cells(st, -1000, 600, 10)
    c["fswitch"] = (st.lv.mp.groups[0].n - 1, 0, 0, 0)
    st.decide(100, c)                                          # the floor joins the world on this frame
    st.decide(101, c)
    want = "health" if window else "item:2048"
    assert st.legs[st.li]["to"] == want, "CONTROL: the short leg sought health with no window" if not window else ""
    if window:
        assert st.legs[st.li]["goal"] in ([-1344, 720], [-576, 720])


@pytest.mark.parametrize("on", [True, False])
def test_channel_with_no_health_in_reach_takes_a_suit(mods, on):
    """CHANNEL_SUIT (E1M4's MAP_TACTICS): a long damaging stretch ahead, too little health for it and no health in
    reach -> the radiation suit (912, 1520); an 18-leg play went into the channel at 26 health and died of the floor.
    CONTROL: CHANNEL_SUIT off -> the same cells, no suit leg"""
    play, st, li = _steer(mods, LONG)
    assert st.CHANNEL_SUIT                                     # E1M4's tactic, from MAP_TACTICS
    st.CHANNEL_SUIT = on
    st.SEEK_AVOID = ()                                         # (the near suit is in E1M4's avoided box: this rule alone)
    st.health_taken |= set(st.health)                          # every health item gone
    x, y = 803, 1822
    st.replan(x, y, "test")
    st.decide(100, _cells(st, x, y, 26))
    got = [g["to"] for g in st.legs].count("suit")
    assert got == (1 if on else 0), "CONTROL: a suit leg with the tactic off" if not on else "no suit leg"
    if on:
        assert st.legs[st.li]["to"] == "suit" and st.legs[st.li]["goal"] == [912, 1520]


def test_map_tactics_are_e1m4s_alone():
    """IGN_NEAR and CHANNEL_SUIT are off in the class (every other map's steering unchanged)"""
    play = _load("play", "scripts/play.py")
    assert play.Steer.IGN_NEAR == 0 and play.Steer.CHANNEL_SUIT is False
    # E1M4's knobs are its own: E1M7's entry (SKIP_ITEMS) sets none of them
    assert all(not set(play.Steer.MAP_TACTICS["E1M4"]) & set(t) for m, t in play.Steer.MAP_TACTICS.items() if m != "E1M4")


# ---- AMMO / SAVE_R (E1M4's map tactics): the best plays ran dry for their last 700 frames and died punching -------
def _fight_cells(st, x, y, m, mx, clip, shell=0):
    n = len(st.mtype)
    rows = [0] * (n + len(st.droppers))
    rows[m] = ((int(mx) << 16) & 0xFFFFFFFF) | (((int(y) << 16) & 0xFFFFFFFF) << 32)
    c = _cells(st, x, y, 100)
    c.update({"mon_active": [1 if k == m else 0 for k in range(n)], "mon_health": [60] * n,
              "thseen": [1 if k == m else 0 for k in range(n)], "mon_target": [1] * n, "thpos_rt": rows,
              "p_atk": 0, "am_clip": clip, "am_shell": shell, "aim_sid": (1 + m,) * 17,
              "mdrop": (0,) * len(st.droppers)})
    return c


def test_live_drops_read_the_drop_rows(mods):
    play, st, li = _steer(mods, LONG)
    k = next(i for i, kind in enumerate(st.drop_kind) if kind == 2007)
    c = _fight_cells(st, 0, 0, 0, 0, 10)
    c["thpos_rt"][len(c["thpos_rt"]) - len(st.droppers) + k] = ((300 << 16) & 0xFFFFFFFF) | (((-200 << 16) & 0xFFFFFFFF) << 32)
    c["mdrop"] = tuple(1 if i == k else 0 for i in range(len(st.droppers)))
    assert st._live_drops(c) == [(300, -200)]
    c["mdrop"] = tuple(2 if i == k else 0 for i in range(len(st.droppers)))      # CONTROL: taken -> none
    assert st._live_drops(c) == []


@pytest.mark.parametrize("save", [500, 0])
def test_short_of_ammo_no_far_shot(mods, save):
    play, st, li = _steer(mods, LONG)
    st.SAVE_R, st.AMMO_LOW = save, 20
    st.rt = list(range(len(st.mtype)))
    x, y = st.legs[li]["path"][0]
    kd = st.decide(100, _fight_cells(st, x, y, 3, x + 600, clip=10))
    assert ("fire" in kd) == (not save), "CONTROL: no far shot with SAVE_R off" if not save else "fired far, short"
    st.fired = False
    kd = st.decide(102, _fight_cells(st, x, y, 3, x + 600, clip=60))           # plenty: SAVE_R does not bind
    assert "fire" in kd and st.why.startswith("fight")


@pytest.mark.parametrize("low", [20, 0])
def test_short_of_ammo_on_a_long_leg_fetches_ammo_far_off(mods, low):
    """2 bullets on the armor leg (the dry rule needs 0): AMMO_LOW seeks ammo up to AMMO_FAR_MOST cells off;
    CONTROL: AMMO_LOW 0 -> the leg goes on"""
    play, st, li = _steer(mods, LONG)
    st.AMMO_LOW = low
    st.CROSS_HP = 0                                            # (AMMO_LOW alone: the channel lies ahead from here)
    x, y = 987, 1115
    st.replan(x, y, "test")
    c = _cells(st, x, y, 80)
    c.update({"am_clip": 2, "am_shell": 0})
    st.decide(100, c)
    assert (st.legs[st.li]["to"] == "ammo") == bool(low), st.legs[st.li]["to"]


@pytest.mark.parametrize("on", [True, False])
def test_seeks_avoid_the_imps_round_the_near_suit(mods, on):
    """SEEK_AVOID (E1M4): no detour to the stimpacks (496, 1840), (816, 1840) among the imps; CONTROL: SEEK_AVOID ()
    -> the same seek takes one"""
    play, st, li = _steer(mods, LONG)
    if not on:
        st.SEEK_AVOID = ()
    got = st._seek_health(100, 803, 1700, [(496, 1840), (816, 1840)], "health", most=150, radius=2500)
    assert got == (not on), "CONTROL: no detour with SEEK_AVOID off" if not on else "a detour into the avoided box"


def test_e1m4_route_armor_west_card_before_the_north(mods):
    """level_route.MAP_PICKUPS (E1M4, the route agent): the west armor (-1312, -608) is a route leg before the chaingun
    (before the corridor's imps); no stimpack loop (the soulsphere keeps the player above 100 there); the medikit
    (3264, 1216) then the blue card, with no leg to the far suit / armor in the room's north half. CONTROL: without the
    map's entry the armor's type budget (50) does not reach it, and the far suit and armor are legs again"""
    lr, _play, route = mods
    to = [(g["to"], tuple(g["goal"])) for g in route["legs"]]
    names = [t for t, _g in to]
    assert to.index(("item:2018", (-1312, -608))) < names.index("item:2002")
    assert "item:2011" not in names
    assert names[names.index("item:2012") + 1] == "key:blue"
    assert ("item:2025", (3392, 1728)) not in to and ("item:2018", (3264, 1728)) not in to
    assert all(g.get("must") for g in route["legs"] if g["to"] == "item:2012" or tuple(g["goal"]) == (-1312, -608))
    saved = dict(lr.MAP_PICKUPS)
    try:
        lr.MAP_PICKUPS.clear()
        legs = lr.plan("E1M4", "easy")["legs"]
    finally:
        lr.MAP_PICKUPS.update(saved)
    to0 = [(g["to"], tuple(g["goal"])) for g in legs]
    assert ("item:2018", (-1312, -608)) not in to0, "CONTROL: the west armor a leg with no map entry"
    assert ("item:2025", (3392, 1728)) in to0 and ("item:2018", (3264, 1728)) in to0, "CONTROL: the far suit / armor"
    assert set(lr.MAP_PICKUPS) == {"E1M4"}                     # every other map's route is the type budgets' alone


@pytest.mark.parametrize("on", [True, False])
def test_near_the_end_no_ammo_detour(mods, on):
    """END_NO_AMMO (E1M4): on the exit leg 61 cells from the end, dry -> no ammo detour (a play walked 242 cells back
    for a clip from there and died); CONTROL: END_NO_AMMO off -> the same cells start one"""
    play, st, li = _steer(mods, "exit")
    st.END_NO_AMMO = on
    x, y = -397, 1809
    st.replan(x, y, "test")
    c = _cells(st, x, y, 70)                                  # (70: above the health seek's threshold -- ammo alone)
    c.update({"am_clip": 0, "am_shell": 0})
    st.decide(100, c)
    assert (st.legs[st.li]["to"] == "ammo") == (not on), st.legs[st.li]["to"]


@pytest.mark.parametrize("on", [True, False])
def test_in_the_channel_no_new_detour(mods, on):
    """CHANNEL_COMMIT (E1M4): standing on the nukage at 15 health, no detour starts -- the way on is shorter; CONTROL:
    CHANNEL_COMMIT off -> the same cells start one"""
    play, st, li = _steer(mods, LONG)
    st.CHANNEL_COMMIT = on
    st.SEEK_MAX_BURN = None                                    # (CHANNEL_COMMIT alone)
    x, y = 2537, 1589
    assert st.pl.hurts(st.LR.cell_of(x, y))
    st.replan(x, y, "test")
    n = len(st.legs)
    st.decide(100, _cells(st, x, y, 15))
    added = len(st.legs) - n
    assert added == (0 if on else 1), "CONTROL: no detour with the rule off" if not on else "a detour in the channel"


def test_channel_seeks_take_no_health_beyond_the_stretch(mods):
    """SEEK_MAX_BURN (E1M4: 8): the damaging-stretch rule's health is not the medikit at the channel's far end (135
    cells, through the nukage) -- the seek that sent a 13-health play into the floor; CONTROL: None -> it is taken"""
    play, st, li = _steer(mods, LONG)
    assert st.SEEK_MAX_BURN == 8
    assert not st._seek_health(100, 1787, 897, [(3264, 1216)], "health", most=150, radius=2500, max_burn=8)
    st.retry.clear()
    st.SEEK_MAX_BURN = None
    assert st._seek_health(100, 1787, 897, [(3264, 1216)], "health", most=150, radius=2500), \
        "CONTROL: no path at all (the cap is not what refused it)"


@pytest.mark.parametrize("cap", [8, None])
def test_no_ammo_detour_back_across_the_channel(mods, cap):
    """SEEK_MAX_BURN caps EVERY detour (any `what`, no max_burn passed): a play past the channel crossed it back west
    for ammo and died at (1780, 957). Here the same crossing the other way: an "ammo" detour to a spot beyond the channel
    (135 cells through the nukage) is refused; CONTROL: no cap -> the detour is taken"""
    play, st, li = _steer(mods, LONG)
    st.SEEK_MAX_BURN = cap
    got = st._seek_health(100, 1787, 897, [(3264, 1216)], "ammo", most=400, radius=4000)
    assert got == (cap is None), "CONTROL: no ammo in reach at all" if cap is None else "crossed the channel back"


@pytest.mark.parametrize("cross", [50, 0])
def test_healthy_before_the_channel_no_ammo_detour(mods, cross):
    """CROSS_HP (E1M4: 50): at 80 health with the channel ahead and no ammo, no ammo detour -- go now (a play spent 5,000
    frames on ammo detours west at 93 health and crossed at 13); CONTROL: CROSS_HP 0 -> an ammo detour"""
    play, st, li = _steer(mods, LONG)
    st.CROSS_HP, st.CROSS_AMMO = cross, 0                      # (CROSS_HP alone)
    x, y = 1768, 1096
    st.replan(x, y, "test")
    c = _cells(st, x, y, 80)
    c.update({"am_clip": 0, "am_shell": 0})
    st.decide(100, c)
    assert (st.legs[st.li]["to"] == "ammo") == (not cross), st.legs[st.li]["to"]


@pytest.mark.parametrize("low", [60, 0])
def test_a_dropped_clip_is_taken_with_shells_in_hand(mods, low):
    """DROP_LOW (E1M4: 60): 40 bullets and 5 shells, a zombieman's clip lying a few cells along the way -> a drop
    detour; CONTROL: DROP_LOW 0 -> AMMO_LOW's rule alone (no shells only) leaves it"""
    play, st, li = _steer(mods, "item:2048")
    st.DROP_LOW = low
    k = next(i for i, kind in enumerate(st.drop_kind) if kind == 2007)
    x, y = st.legs[li]["path"][0]
    dx, dy = st.legs[li]["path"][6]
    c = _fight_cells(st, x, y, 0, x, clip=40, shell=5)
    c["mon_active"] = [0] * len(st.mtype)
    c["thpos_rt"][len(c["thpos_rt"]) - len(st.droppers) + k] = (((int(dx) << 16) & 0xFFFFFFFF)
                                                                | (((int(dy) << 16) & 0xFFFFFFFF) << 32))
    c["mdrop"] = tuple(1 if i == k else 0 for i in range(len(st.droppers)))
    st.decide(100, c)
    assert (st.legs[st.li]["to"] == "drop") == bool(low), st.legs[st.li]["to"]


@pytest.mark.parametrize("save_low", [40, 0])
def test_save_r_binds_under_save_low(mods, save_low):
    """SAVE_LOW (E1M4: 40): 30 bullets, a foe 600 off -> no shot (seed 0 emptied 21 bullets at a demon 374..468 off
    and entered the channel dry); CONTROL: SAVE_LOW 0 -> AMMO_LOW's 20 binds, and at 30 it fires"""
    play, st, li = _steer(mods, LONG)
    st.SAVE_R, st.AMMO_LOW, st.SAVE_LOW = 300, 20, save_low
    st.rt = list(range(len(st.mtype)))
    x, y = st.legs[li]["path"][0]
    kd = st.decide(100, _fight_cells(st, x, y, 3, x + 600, clip=30))
    assert ("fire" in kd) == (not save_low)


@pytest.mark.parametrize("low", [60, 0])
def test_a_drop_is_taken_before_the_channel(mods, low):
    """go_now (CROSS_HP) holds back the FAR ammo only: a dropped clip by the channel's mouth is taken (DROP_LOW);
    CONTROL: DROP_LOW 0 -> go_now holds it back too"""
    play, st, li = _steer(mods, LONG)
    st.DROP_LOW = low
    x, y = 1768, 1096
    st.replan(x, y, "test")
    k = next(i for i, kind in enumerate(st.drop_kind) if kind == 2007)
    dx, dy = st.pieces[0][6]
    c = _fight_cells(st, x, y, 0, x, clip=30, shell=0)  # armed: CROSS_HP's go-now holds
    c["p_hp"] = 80
    c["mon_active"] = [0] * len(st.mtype)
    c["thpos_rt"][len(c["thpos_rt"]) - len(st.droppers) + k] = (((int(dx) << 16) & 0xFFFFFFFF)
                                                                | (((int(dy) << 16) & 0xFFFFFFFF) << 32))
    c["mdrop"] = tuple(1 if i == k else 0 for i in range(len(st.droppers)))
    st.decide(100, c)
    assert (st.legs[st.li]["to"] == "drop") == bool(low), st.legs[st.li]["to"]


@pytest.mark.parametrize("cross_ammo", [20, 0])
def test_short_of_ammo_before_the_channel_fetches_first(mods, cross_ammo):
    """CROSS_AMMO (E1M4: 20): at the channel's mouth with 80 health and 6 bullets, the far ammo first (an imp blocks the
    channel: seed 7 went in with 6 and died there); CONTROL: CROSS_AMMO 0 -> CROSS_HP's go-now, no detour"""
    play, st, li = _steer(mods, LONG)
    st.CROSS_AMMO = cross_ammo
    x, y = 1768, 1096
    st.replan(x, y, "test")
    c = _cells(st, x, y, 80)
    c.update({"am_clip": 6, "am_shell": 0})
    st.decide(100, c)
    assert (st.legs[st.li]["to"] == "ammo") == bool(cross_ammo), st.legs[st.li]["to"]


@pytest.mark.parametrize("on", [True, False])
def test_dry_at_the_end_runs_past(mods, on):
    """END_DRY_RUN (E1M4): dry on the exit leg 30 cells from the end, an imp 50 units ahead -> no fist fight, a sidestep
    (seed 7 stood punching it at 28 health and died, (101, 2033)); CONTROL: END_DRY_RUN off -> the fist fight"""
    play, st, li = _steer(mods, "exit")
    st.END_DRY_RUN = on
    st.rt = list(range(len(st.mtype)))
    x, y = 71, 2023
    st.replan(x, y, "test")
    m = next(k for k, t in enumerate(st.mtype) if t == 3001)
    c = _fight_cells(st, x, y, m, x + 50, clip=0, shell=0)
    c["p_hp"] = 28
    kd = st.decide(100, c)
    if on:                                                    # (a punch in passing may stay: the walk goes on)
        assert not st.why.startswith("fight") and "forward" in kd and kd & {"strafe_left", "strafe_right"}, (st.why, kd)
    else:
        assert st.why.startswith("fight") and "fire" in kd, "CONTROL: no fist fight with the tactic off"
