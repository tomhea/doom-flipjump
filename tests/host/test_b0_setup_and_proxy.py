"""M7 P6+P7 (host, no binary) -- two gaps of scratchpad/gp/b0_scenarios.py found on blocked50's v6 run.

GAP 2, THE SETUP. v6's R0-aftermath starts among three CORPSES (`setup.corpses`: monster slots 21-23 dead, the two
zombiemen's clips lying) -- the set's replay injects them (`scenarios_v2.start_world`), b0 did not: its mirror and the
binary started with the trio alive, so they fought (B0's columns cam 20 / dr 26). b0 now applies the setup to its
mirror (`setup_fn`: the set's own `inject_corpse`) and pokes the binary at the first game frame with hurt_gate's
frame-0 mechanism (`setup_cells`), plus the leaf lists: a lying drop's row must be LINKED in its corpse's leaf
(`hurt_gate.leaf_list_cells`), or the binary never draws it. These tests hold the poke's content, the list model
against the emitter's own level-start lists (`things.skill_level_start`), and -- the R9 control -- that the aftermath
parts from the set WITHOUT the setup and does not with it.

GAP 1, THE PROXY'S VERDICT. The strafe proxy is a COST measurement; since P6 its forward step is not neutral (it
touches what lies at the landing; a wall or a thing can refuse it), so b0 judges each proxy run against ITS OWN
oracle and records "same picture as the normal run" as a note. `judge` is that rule; the R9 control is a proxy run
whose own comparison is broken, which must FAIL.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SET_V6 = ROOT / "scratchpad/gp/scenarios/combat_scenarios_v6.json"
AFTER = "R0-aftermath"
PREFIX = 24          # the aftermath's first frames: the control parts inside them (asserted below)


@pytest.fixture(scope="module", autouse=True)
def v6_modes():
    """M7 P8a: b0's mirror takes the GAME tier's modes (wall_renderer: the binary under test), "final" since the P8a
    flip; v6 is a "full" / "full" set (its B0 ran on blocked51), so these v6 tests pin the game modes to v6's"""
    from doomfj import wall_renderer as WR
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(WR, "PLAYER_MODE", "full")
        mp.setattr(WR, "MONSTER_MODE", "full")
        yield


@pytest.fixture(scope="module")
def b0s():
    spec = importlib.util.spec_from_file_location("gp_b0_scenarios_setup", ROOT / "scratchpad/gp/b0_scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc(b0s):
    d = json.loads(SET_V6.read_text(encoding="ascii"))
    saved = (b0s.S.SIGHT_RULE, b0s.S.MONSTER_TICS)
    b0s.S.use_sight_rule(d)
    yield d
    b0s.S.SIGHT_RULE, b0s.S.MONSTER_TICS = saved


@pytest.fixture(scope="module")
def orc(b0s):
    return b0s.GameOracle()


def _run(doc, name):
    return next(r for r in doc["runs"] if r["name"] == name)


# ---- GAP 2: which runs have a setup, and what it pokes -------------------------------------------------------------
def test_only_the_aftermath_has_a_setup_beyond_the_pose(b0s, doc):
    """every v6 setup is a pose plus corpses; the aftermath alone has corpses -- no other run's setup is dropped"""
    with_setup = [r["name"] for r in doc["runs"] if b0s.setup_fn(r["setup"]) is not None]
    assert with_setup == [AFTER]
    assert all(set(r["setup"]) <= {"pose", "corpses"} for r in doc["runs"])
    with pytest.raises(AssertionError, match="a setup field b0 does not inject"):
        b0s.setup_fn({"pose": [0, 0, 0], "corpses": [], "armor": 100})


def test_the_aftermath_poke_kills_the_trio_and_lays_and_links_two_clips(b0s, doc, orc):
    from doomfj.monsters import droppers
    setup = _run(doc, AFTER)["setup"]
    before, poke = b0s.setup_poke(orc, setup)
    assert set(poke) == {"mon_state", "mon_tics", "mon_health", "mon_shootable", "mon_solid", "mdrop", "dr_live",
                         "thpos_rt", "thss_rt", "thnext"}, sorted(poke)
    slots = [c["slot"] for c in setup["corpses"]]
    for k in ("mon_health", "mon_shootable", "mon_solid"):
        assert [m for m, (a, b) in enumerate(zip(before[k], poke[k])) if a != b] == slots
        assert all(poke[k][m] == 0 for m in slots)
    assert poke["dr_live"] == 2 and before["dr_live"] == 0
    from doomfj.monsters import MonsterPhase
    from doomfj.wall_renderer import BOOT_SKILL, MONSTER_MODE, PLAYER_MODE
    ph = MonsterPhase(orc.mw, orc.mapname, BOOT_SKILL, rm=orc.rm, mode=MONSTER_MODE, player=PLAYER_MODE)
    mv = orc._mv(ph.world)
    dk = droppers(ph.world)
    lying = [k for k, v in enumerate(poke["mdrop"]) if v == 1]
    assert [dk[k] for k in lying] == [c["slot"] for c in setup["corpses"] if c["drop"] is not None]
    # each lying drop's row is reachable from its leaf's head, after every row below it in that leaf
    import hurt_gate as H
    lists = {"sshead": poke.get("sshead", before.get("sshead")), "thnext": poke["thnext"]}
    if lists["sshead"] is None:                       # the leaves were not empty: sshead did not move
        lists["sshead"] = H.leaf_list_cells(orc, ph, BOOT_SKILL)["sshead"]
    nmob = len(poke["thss_rt"]) - mv.nrt - len(dk)
    for k in lying:
        row = mv.nrt + nmob + k
        leaf = poke["thss_rt"][row]
        walk, cur = [], lists["sshead"][leaf]
        while cur:
            walk.append(cur - 1)
            cur = lists["thnext"][cur - 1]
        assert row in walk and walk == sorted(walk), (k, row, leaf, walk)


def test_the_level_start_lists_are_the_restart_blocks_own(b0s, orc):
    """leaf_list_cells at the level start == things.skill_level_start, which the emitter bakes into the boot image and
    every skill's restart block (wall_renderer: `_MT_HEAD, _MT_NEXT`), the mobile and drop rows unlinked"""
    import hurt_gate as H
    from doomfj.monsters import MonsterPhase
    from doomfj.things import skill_level_start
    from doomfj.wall_renderer import BOOT_SKILL, MONSTER_MODE, PLAYER_MODE
    ph = MonsterPhase(orc.mw, orc.mapname, BOOT_SKILL, rm=orc.rm, mode=MONSTER_MODE, player=PLAYER_MODE)
    mv = orc._mv(ph.world)
    binds = orc.monster_rt(ph)["thss_rt"][:mv.nrt]
    head, nxt, _vis = skill_level_start(mv.drawable, mv.rt_drawable, binds, len(mv.cmap.subsectors),
                                        mv.vis_slots, BOOT_SKILL)
    got = H.leaf_list_cells(orc, ph, BOOT_SKILL)
    assert got["sshead"] == tuple(head)
    assert got["thnext"][:mv.nrt] == tuple(nxt) and not any(got["thnext"][mv.nrt:])
    assert any(head), "the lists are empty: the comparison is vacuous"


def test_without_lists_the_poke_would_not_link_the_drops(b0s, doc, orc):
    """R9 for the list half: hurt_gate's poke WITHOUT `lists` (what fight_gate's setups use) moves the drop rows but
    not their links -- the binary would hold two lying clips no leaf list reaches"""
    from types import SimpleNamespace
    import hurt_gate as H
    from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
    fn = b0s.setup_fn(_run(doc, AFTER)["setup"])
    bare = H.poke_cells(SimpleNamespace(orc=orc, dsim=orc), fn, mmode=MONSTER_MODE, pmode=PLAYER_MODE)
    assert "thss_rt" in bare and "mdrop" in bare and "thnext" not in bare and "sshead" not in bare


# ---- GAP 2: the oracle-only effect, and its R9 control -------------------------------------------------------------
def test_the_aftermath_reproduces_with_its_setup_and_parts_without_it(b0s, doc, orc):
    run = dict(_run(doc, AFTER))
    run["keys"], run["poses"] = run["keys"][:PREFIX], run["poses"][:PREFIX]
    frames = b0s.model_frames(run)
    good = b0s.drive(None, None, orc, frames)
    assert (good["cam_parts"], good["door_parts"], good["dead"]) == (0, 0, [])
    ctl = b0s.drive(None, None, orc, frames, inject_setup=False)
    assert ctl["cam_parts"] + ctl["door_parts"] > 0, "R9: without the corpses the aftermath must part from the set"


# ---- GAP 1: the proxy's verdict -----------------------------------------------------------------------------------
def _res(name, **kw):
    r = {"name": name, "state_ok": [True] * 3, "pix_ok": [True] * 3, "presented": 5, "pal_ok": [True] * 5,
         "dead": [], "setup_pre": []}
    r.update(kw)
    return r


def test_a_proxy_run_is_judged_against_its_own_oracle(b0s):
    ok = _res("R", proxy=_res("R"), proxy_same_picture=False)
    assert b0s.judge([ok], proxy=True) == [], "a proxy whose pictures differ from the normal run's is a NOTE"
    broken = _res("R", proxy=_res("R", pix_ok=[True, False, True]), proxy_same_picture=True)
    assert b0s.judge([broken], proxy=True) == ["R(proxy)"], "R9: a proxy run its own oracle rejects FAILS"
    for kw, why in (({"state_ok": [False, True, True]}, ""), ({"pal_ok": [True] * 4 + [False]}, "(palette)"),
                    ({"dead": [7]}, "(dead at [7])"), ({"presented": 4}, "")):
        assert b0s.judge([_res("R", proxy=_res("R", **kw))], proxy=True) == ["R(proxy)" + why], kw
    assert b0s.judge([_res("R", setup_pre=["mdrop"])], proxy=False) == [
        "R(setup: ['mdrop'] held other values before the poke)"]


def test_proxy_note_names_a_pickup_and_a_refused_step(b0s):
    def tr(pose=(0, 0, 0), loot=None, taken=(), bar=None, pic="a"):
        return {"pose": pose, "doors": (), "picture": pic, "bar": bar or {"values": {"health": 50}},
                "loot": loot or {"p_bc": 0, "mdrop": (1, 0)}, "taken": taken}
    frames = [{"strafe_only": True}, {"strafe_only": False}]
    a = {"trace": [tr(), tr()], "cam_frames": []}
    b = {"trace": [tr(), tr(loot={"p_bc": 6, "mdrop": (2, 0)}, pic="b")], "cam_frames": [], "refusers": {}}
    n = b0s.proxy_note(a, b, frames, frames)
    assert n["first"] == 1 and "the DROP of dropper 0" in n["cause"] and n["refused"] == []
    c = {"trace": [tr(pose=(1, 2, 0), pic="c"), tr()], "cam_frames": [0], "refusers": {0: "a wall or step (try_move)"}}
    n = b0s.proxy_note(a, c, frames, frames)
    assert n["refused"] == [0] and "REFUSED step, by a wall or step" in n["cause"]
    assert b0s.proxy_note(a, {"trace": a["trace"], "cam_frames": []}, frames, frames)["first"] is None
