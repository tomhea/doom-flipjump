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
    play, st, li = _steer(mods, "item:2018")
    st.ITEM_SEEK_HP = knob
    x, y = st.legs[li]["path"][0]
    st.decide(100, _cells(st, x, y, 10))
    if knob:
        assert st.legs[st.li]["to"] == "health", st.legs[st.li]["to"]
        assert st.legs[st.li + 1]["to"] == "item:2018"
    else:
        assert st.legs[st.li]["to"] == "item:2018", "CONTROL: the pickup leg sought health with the rule off"
    st2 = _steer(mods, "item:2018")[1]                      # and at 60 health the rule leaves the leg alone
    st2.decide(100, _cells(st2, x, y, 60))
    assert st2.legs[st2.li]["to"] == "item:2018"


def test_very_low_seek_takes_the_nearest_by_path(mods):
    play, st, li = _steer(mods, "item:2018")
    assert st._seek_health(100, 1768, 920, st.health, "health", most=250, radius=3000)
    assert st.legs[st.li]["to"] == "health" and st.legs[st.li]["goal"] == [816, 1840]
    play, st, li = _steer(mods, "item:2018")
    st.SEEK_FAR = False
    assert not st._seek_health(100, 1768, 920, st.health, "health", most=250, radius=3000), \
        "CONTROL: the three nearest alone found a way (the far rule is not what found it)"
    play, st, li = _steer(mods, "item:2018")
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
    play, st, li = _steer(mods, "item:2018")
    assert st.CHANNEL_SUIT                                     # E1M4's tactic, from MAP_TACTICS
    st.CHANNEL_SUIT = on
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
    assert set(play.Steer.MAP_TACTICS) == {"E1M4"}
