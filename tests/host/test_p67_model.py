"""M7 P6 / P7 (host) -- the model side of pickups, barrels, death and restart (docs/gp-p67-interface.md 4.1):

  * G2, THE EXIT FRAME: a tic whose player phase presses the exit runs no monster, projectile, barrel or effect
    phase and does not advance `leveltime` (the binary's world phases skip on `lvdone`); the R9 control: the same
    state without the press does advance them;
  * P7-a, THE DEAD LATCH: a nukage kill inside the alive branch still runs that tic's weapon keys and move; the next
    tic is the death think (no move, no keys);
  * monsters.MonsterPhase's player half (`dead_latch`, `nukage`, `weapon`, `move`) IS `combat._player_phase` -- held
    tic by tic over walks that pick up, block, and die in nukage;
  * P7-d, THE RESTART: every schema field but RESTART_KEEP goes back to the skill's level start, the kept ones stay;
    R9: a restart that forgot one array is caught by the same comparison;
  * the frame order's two COMMUTING claims (4.7): the weapon keys and the use lines, in either order, leave the
    same state; no point of the floor switch's use box lies in a damaging sector (so the switch's scene change can
    never meet a nukage test in one tic);
  * the blast's LOS: a target a wall hides takes no damage (R9: with sight forced, it does) -- the rule fight_gate
    cannot reach on E1M1;
  * the barrels' static chain (4.3): the in-range ordered pairs, every one with a clear LOS; R9: a barrel moved
    200 units, and a blocking segment added, each change the table;
  * the new cells' units (`MonsterPhase.state` / `loot_state` / `barrel_state` / `game_state`, `MonsterViews`'
    thvis, the drop rows, the barrels in the aim window), and `combat.window_aim` naming a barrel.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src")]

from doomfj import gamedata as gd                                            # noqa: E402
from doomfj import rng as R                                                  # noqa: E402
from doomfj.world import KEYS, TicEvents, World                              # noqa: E402

ART = ROOT / "assets/freedoom1.wad"
NUKAGE_POSE = (2024, 1310)            # a standing point of sector 23 (special 7) whose box is on its floor


def keys(**kw):
    return {k: bool(kw.get(k)) for k in KEYS}


@pytest.fixture(scope="module")
def world():
    return World(monsters="full", player="full")


def fresh(w, skill=gd.SK_HARD):
    w.reset(skill)
    return w


def exit_pose(w):
    """a standing 16.16 point inside the exit's use box"""
    (x0, y0, x1, y1), = w.exit_boxes
    for x in range(x0 + 4, x1, 8):
        for y in range(y0 + 4, y1, 8):
            if w.rm.check_position(w.scene_c, x << 16, y << 16)[0]:
                return x << 16, y << 16
    raise AssertionError("no standing point in the exit box")


# ---------------------------------------------------------------------------------------------- G2: the exit frame
def test_exit_frame_runs_no_world_phase(world):
    w = fresh(world)
    ws = w.ws
    w.teleport_player(*exit_pose(w))
    ws.p_usedown = 0
    ws.leveltime = 5
    live = [m for m in range(w.layout.nmon) if ws.mon_active[m] and 1 < ws.mon_tics[m] < 15]
    assert live
    snap = ws.copy()
    ev = w.tic(keys(use=True))
    assert ev.level_done and ws.g_leveldone == 1
    assert ws.leveltime == 5, "the exit frame advanced leveltime"
    assert [ws.mon_tics[m] for m in live] == [snap.mon_tics[m] for m in live], "the exit frame ran the monsters"
    assert list(ws.bar_tics) == list(snap.bar_tics), "the exit frame ran the barrels"
    # R9: the same state, no press -- the world phases run (so the assertions above can fail)
    w.ws = snap.copy()
    w._door_phase_scene()
    w.tic(keys())
    assert w.ws.leveltime == 6 and [w.ws.mon_tics[m] for m in live] != [snap.mon_tics[m] for m in live]


# ---------------------------------------------------------------------------------------------- P7-a: the latch
def test_nukage_death_tic_runs_the_alive_branch(world):
    w = fresh(world)
    ws = w.ws
    w.teleport_player(NUKAGE_POSE[0] << 16, NUKAGE_POSE[1] << 16, 0x40000000)
    assert w.secs[w.player_sector()].special == 7
    ws.p_health, ws.leveltime = 5, 0
    x0, y0 = ws.px, ws.py
    ev = w.tic(keys(forward=True, w1=True))
    assert ev.nukage == 1 and ev.deaths == 1 and ws.p_dead
    assert (ws.px, ws.py) != (x0, y0), "the nukage-death tic did not move"
    assert ws.p_pending == gd.WP_FIST, "the nukage-death tic did not read the weapon keys"
    x1, y1, a1 = ws.px, ws.py, ws.pangle
    w.tic(keys(forward=True, turn_left=True, w2=True))
    assert (ws.px, ws.py, ws.pangle) == (x1, y1, a1) and ws.p_pending == gd.WP_FIST, "a dead player moved or keyed"


# ------------------------------------------------------------------------- MonsterPhase's player half IS the model's
PLAYER_ONLY = ("p_usedown", "p_mobj_state", "p_mobj_tics")


def _phase_vs_model(pose, script, setup=None):
    """step the same start two ways -- World._player_phase, and MonsterPhase's dead_latch / nukage / weapon / move --
    and compare every cell after each tic (but the player THING's state and use's edge, the gates' own)"""
    from doomfj.monsters import MonsterPhase
    a = MonsterPhase(mode="full", player="full")
    b = World(monsters="full", player="full")
    for w in (a.world, b):
        w.teleport_player(pose[0] << 16, pose[1] << 16, pose[2])
        if setup:
            setup(w)
    for k in script:
        kd = keys(**k)
        b._player_phase(kd, TicEvents(0))
        ws = a.world.ws
        dead = a.dead_latch()
        a.nukage(dead=dead)
        a.weapon(kd, dead=dead)
        x, y, ang = a.move(kd, ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, ws.pangle, dead=dead)
        assert (x - ws.px) & 0xFFFFFFFF == 0 and (y - ws.py) & 0xFFFFFFFF == 0 and ang == ws.pangle
        for f in a.world.schema:
            if f.name in PLAYER_ONLY:
                continue
            assert getattr(a.world.ws, f.name) == getattr(b.ws, f.name) or \
                list(getattr(a.world.ws, f.name)) == list(getattr(b.ws, f.name)), f.name
        for w in (a.world, b):
            w.ws.leveltime = (w.ws.leveltime + 1) & 0xFFFF
    return a, b


def test_phase_player_half_picks_up_like_the_model():
    a, _b = _phase_vs_model((-160, 112, 0x40000000), [{"forward": True}] * 30)
    assert a.world.ws.p_health == 104 and sum(a.world.ws.pickup_taken) > sum(World(monsters="idle").ws.pickup_taken)


def test_phase_player_half_blocks_like_the_model():
    t = World(monsters="idle").barrel_things[13]
    a, _b = _phase_vs_model((t.x + 64, t.y, 0x80000000), [{"forward": True}] * 8)
    assert (a.world.ws.px >> 16) - t.x >= 26


def test_phase_player_half_dies_in_nukage_like_the_model():
    def hp5(w):
        w.ws.p_health = 5
    a, _b = _phase_vs_model((NUKAGE_POSE[0], NUKAGE_POSE[1], 0x40000000),
                            [{"forward": True, "w1": True}, {"forward": True}, {"use": True}], hp5)
    assert a.world.ws.p_dead and a.world.ws.g_restart == 1 and a.restart_due()


def test_move_puts_back_the_walkovers():
    """the gates' DoorPhase / MoverPhase own the walk-overs: `move` leaves w_fired, d_monreq, l_req as it found them"""
    from doomfj.monsters import MonsterPhase
    a = MonsterPhase(mode="full", player="full")
    w = a.world
    trig = w.walk_triggers[0]
    _si, axis, coord, lo, hi = trig
    mid = (lo + hi) // 2
    for side in (-1, 1):
        x, y = (mid, coord + side * 24) if axis == "y" else (coord + side * 24, mid)
        if w.rm.check_position(w.scene_c, x << 16, y << 16)[0]:
            break
    ang = (0x40000000 if side < 0 else 0xC0000000) if axis == "y" else (0 if side < 0 else 0x80000000)
    pose = [x << 16, y << 16, ang]
    for _ in range(4):
        pose = list(a.move({"forward": True}, *pose))
    assert not any(w.ws.w_fired) and not any(w.ws.d_monreq)
    b = World(monsters="full", player="full")
    b.teleport_player(x << 16, y << 16, ang)
    for _ in range(4):
        b._player_move(keys(forward=True), TicEvents(0))
    assert any(b.ws.w_fired), "the walk never crossed its trigger: the test is vacuous"


# ---------------------------------------------------------------------------------------------- P7-d: the restart
def _messy(w):
    ws = w.ws
    ws.skill = gd.SK_MEDIUM
    ws.mode, ws.kb_f = 1, 1
    ws.p_health, ws.p_dead, ws.p_bonuscount, ws.p_strength, ws.leveltime = -20, 1, 30, 400, 777
    ws.pickup_taken[3] = 1 - ws.pickup_taken[3]
    ws.bar_state[2] = ws.bar_tics[2] = ws.bar_solid[2] = 0
    ws.mon_drop[9] = 1
    ws.rng_world, ws.rng_player = (ws.rng_world + 9) & R.STATE_MASK, (ws.rng_player + 3) & R.STATE_MASK
    ws.px += 5 << 16
    ws.d_state[0] = 3
    ws.g_restart = 1


def test_restart_covers_every_field_but_the_kept():
    from doomfj.combat import RESTART_KEEP
    w = World(monsters="full", player="full")
    _messy(w)
    kept = {k: getattr(w.ws, k) for k in RESTART_KEEP}
    w.tic(keys())                                       # the restart, then this tic
    ls = w.level_start(gd.SK_MEDIUM)
    w2 = World(monsters="full", player="full")
    w2.reset(gd.SK_MEDIUM)
    w2.ws.mode, w2.ws.kb_f = 1, 1
    w2.tic(keys())                                      # a level start at medium, then the same tic
    for f in w.schema:
        if f.name in RESTART_KEEP:
            assert getattr(w.ws, f.name) == kept[f.name], f.name
        else:
            a, b = getattr(w.ws, f.name), getattr(w2.ws, f.name)
            assert (a == b) if not f.array else list(a) == list(b), f.name
    assert ls.skill == gd.SK_MEDIUM and w.ws.g_restart == 0


def test_restart_control_a_forgotten_array_is_caught():
    """R9: a restart that leaves `pickup_taken` alone differs from the level start in exactly that field"""
    w = World(monsters="full", player="full")
    _messy(w)
    w.restart_fields = tuple(f for f in w.restart_fields if f != "pickup_taken")
    w._restart(TicEvents(0))
    ls = w.level_start(gd.SK_MEDIUM)
    bad = [f.name for f in w.schema if f.array and f.name not in ("kb_f",)
           and list(getattr(w.ws, f.name)) != list(getattr(ls, f.name))]
    assert bad == ["pickup_taken"], bad


# ---------------------------------------------------------------------------------------------- 4.7: commuting
def test_weapon_keys_and_use_lines_commute(world):
    """the model runs the weapon keys before the use lines, the binary after (4.7): either order, the same state"""
    w = fresh(world)
    boxes = [w.exit_boxes[0]] + [b for _t, b in w.lift_use] + list(w.switch_boxes)
    for box in boxes:
        x, y = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        for kd in (keys(w1=True), keys(w2=True), keys(w3=True)):
            outs = []
            for keys_first in (True, False):
                fresh(w)
                w.teleport_player(x << 16, y << 16)
                w.ws.p_owned[gd.WP_SHOTGUN] = 1
                if keys_first:
                    w._weapon_keys(kd)
                w._use_lines(TicEvents(0))
                if not keys_first:
                    w._weapon_keys(kd)
                outs.append(w.ws.digest())
            assert outs[0] == outs[1]


def test_no_switch_box_point_is_in_a_damaging_sector(world):
    """the floor switch is the one use line that changes this tic's scene; a press needs the player in its box, and
    nukage needs him in a damaging sector -- no point is both, so their order in the frame cannot matter"""
    from doomfj.combat import SECTOR_HURT
    w = fresh(world)
    assert w.switch_boxes
    for x0, y0, x1, y1 in w.switch_boxes:
        for x in range(x0, x1 + 1, 4):
            for y in range(y0, y1 + 1, 4):
                sec = w.leaf_sector[w.rm.point_in_subsector(w.cmap, x, y)]
                assert w.secs[sec].special not in SECTOR_HURT, (x, y, sec)


# ---------------------------------------------------------------------------------------------- the blast's LOS
def test_a_blast_does_not_reach_through_a_wall(world, monkeypatch):
    w = fresh(world)
    found = None
    for b, t in enumerate(w.barrel_things):
        for dx in range(-110, 111, 10):
            for dy in range(-110, 111, 10):
                x, y = t.x + dx, t.y + dy
                if (w.rm.check_position(w.scene_c, x << 16, y << 16)[0]
                        and not w.los_points((x << 16, y << 16), (t.x << 16, t.y << 16))):
                    found = (b, x, y)
                    break
            if found:
                break
        if found:
            break
    assert found, "no standing point near a barrel that a wall hides"
    b, x, y = found
    w.teleport_player(x << 16, y << 16)
    hp = w.ws.p_health
    w._radius_attack(b, TicEvents(0))
    assert w.ws.p_health == hp
    monkeypatch.setattr(World, "los_points", lambda self, p, q: True)    # R9: sight forced -- he is hurt
    w._radius_attack(b, TicEvents(0))
    assert w.ws.p_health < hp


# ---------------------------------------------------------------------------------------------- 4.3: the chain table
def chain_pairs(w, barrels, walls=()):
    """(b, c, damage) for every ordered pair whose blast reaches the other barrel, and whether every one has a clear
    LOS through the static walls and EVERY door / mover segment (at any height) plus `walls`"""
    from doomfj.combat import BARREL_R, BOMB_DAMAGE
    from doomfj.world import segments_touch
    segs = [s for s in w._sight_walls] + [s for s, _f, _b in w._sight_doors] + list(walls)
    out, clear = [], True
    for b, (bx, by) in enumerate(barrels):
        for c, (cx, cy) in enumerate(barrels):
            if b == c:
                continue
            d = max(0, max(abs(bx - cx), abs(by - cy)) - BARREL_R)
            if d < BOMB_DAMAGE:
                out.append((b, c, BOMB_DAMAGE - d))
                p, q = (cx << 16, cy << 16), (bx << 16, by << 16)
                clear &= not any(segments_touch(p, q, s[0], s[1]) for s in segs)
    return out, clear


def test_barrel_chain_table(world):
    w = fresh(world)
    xy = [(t.x, t.y) for t in w.barrel_things]
    pairs, clear = chain_pairs(w, xy)
    assert len(pairs) == 96 and clear                  # MEASURED (the plan, 4.3): 96 pairs, all in clear sight
    moved = list(xy)
    moved[14] = (xy[14][0] + 200, xy[14][1])          # R9: a barrel moved 200 units changes the table
    assert chain_pairs(w, moved)[0] != pairs
    b, c, _d = pairs[0]                                # R9: a segment across a pair's line blocks it
    (bx, by), (cx, cy) = xy[b], xy[c]
    mx, my = (bx + cx) << 15, (by + cy) << 15
    wall = ((mx - (8 << 16), my - (8 << 16)), (mx + (8 << 16), my + (8 << 16)))
    if (bx - cx) * (by - cy) > 0:
        wall = ((mx - (8 << 16), my + (8 << 16)), (mx + (8 << 16), my - (8 << 16)))
    assert not chain_pairs(w, xy, walls=[wall])[1]


# ---------------------------------------------------------------------------------------------- the cells' units
def test_state_carries_the_p67_groups_in_full_only():
    from doomfj.monsters import MonsterPhase, droppers
    full, fx = MonsterPhase(mode="full", player="full"), MonsterPhase(mode="full", player="fx")
    st = full.state()
    for k in ("p_bc", "p_str", "p_bp", "am_misl", "am_cell", "mdrop", "dr_live", "bar_st", "bar_ti", "bar_hp",
              "bar_solid", "rng_wd", "lvtime", "g_rs", "g_skill"):
        assert k in st and k not in fx.state(), k
    w = full.world
    assert len(st["mdrop"]) == len(droppers(w)) == 25 and len(st["bar_st"]) == w.layout.nbarrel == 22
    assert set(st["bar_st"]) == {gd.STATE_INDEX["S_BAR1"]} and all(v == 20 for v in st["bar_hp"])
    assert st["g_skill"] == 2 and st["rng_wd"] == (R.stream_seed(R.STREAM_WORLD) + 22) & R.STATE_MASK
    w.ws.bar_health[0] = -128
    assert full.state()["bar_hp"][0] == 0x80
    w.ws.mon_drop[droppers(w)[3]] = 1
    assert full.state()["dr_live"] == 1 and full.state()["mdrop"][3] == 1


def test_leveltime_and_strength_tick_in_the_phase():
    from doomfj.monsters import MonsterPhase
    ph = MonsterPhase(mode="full", player="full")
    ph.world.ws.p_strength = 1
    ph.weapon({})
    ph.tic()
    assert ph.world.ws.p_strength == 2 and ph.world.ws.leveltime == 1


def test_window_aim_names_a_barrel():
    from doomfj.combat import CombatMixin
    w = World(monsters="idle", player="full")
    n = w.layout.nmon
    w.ws.aim_sid[0] = 1 + n + 5
    assert CombatMixin.window_aim(w, w.aim_lo) == ("bar", 5)
    w.ws.aim_sid[0] = n
    assert CombatMixin.window_aim(w, w.aim_lo) == ("mon", n - 1)


@pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad (the sprite art)")
def test_views_aim_vis_and_drop_rows():
    from doomfj.monsters import MonsterPhase, MonsterViews, droppers, drop_rows
    from doomfj.things import skill_absent
    from doomfj.wad import WadFile
    art = WadFile.from_path(str(ART))
    ph = MonsterPhase(mode="full", player="full")
    w = ph.world
    mv = MonsterViews(w.rm, w.mw, w.mapname, art, w)
    # the aim window: every live barrel, sid 1 + nmon + b, radius 10
    at = mv.aim_things(ph)
    for b, di in enumerate(mv.bdi):
        assert at[di] == (1 + w.layout.nmon + b, 10)
    # thvis at each skill's level start: the baked slots as the emitter bakes them (things.skill_level_start), then
    # the runtime pickups
    for skill in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD):
        ph.reset(skill)
        absent = skill_absent(mv.drawable, skill)
        want = [0 if di in absent else 1 for di in sorted(mv.vis_slots, key=mv.vis_slots.get)]
        want += [0 if di in absent else 1 for di in mv.rt_pickups]
        assert list(mv.vis_state(ph)["thvis"]) == want
    ph.reset(gd.SK_HARD)
    assert len(mv.vis_state(ph)["thvis"]) == mv.nvis == 115 and not mv.hidden(ph)
    # a pickup taken and a barrel gone: removed, and their slots 0
    i = next(i for i, t in enumerate(w.pickup_things) if t.flags & gd.skill_bit(gd.SK_HARD) and mv.pdi[i] in mv.vis_slots)
    w.ws.pickup_taken[i] = 1
    w.ws.bar_state[0] = 0
    assert mv.hidden(ph) == sorted([mv.pdi[i], mv.bdi[0]])
    assert mv.vis_state(ph)["thvis"][mv.vis_slots[mv.pdi[i]]] == 0 == mv.vis_state(ph)["thvis"][mv.vis_slots[mv.bdi[0]]]
    assert 0 not in {b for b in ph.barrel_lumps()} and ph.barrel_lumps()[1] in ("BAR1A0", "BAR1B0")
    # the drop rows: after the mobiles, one per dropper; a lying drop is its corpse's row and leaf, and a mobile at z 0
    m = droppers(w)[0]
    w.ws.mon_drop[m] = 1
    rt = mv.rt_state(ph)
    k = mv.nrt + 10
    assert len(rt["thpos_rt"]) == mv.nrows(ph) == mv.nrt + 10 + drop_rows(w) == 103
    assert rt["thpos_rt"][k] == ((w.ws.mon_x[m] << 16) & 0xFFFFFFFF) | (((w.ws.mon_y[m] << 16) & 0xFFFFFFFF) << 32)
    assert rt["thss_rt"][k] == w.ws.mon_leaf[m] and rt["thpos_rt"][k + 1] == 0
    assert ph.mobiles()[-1] == (w.ws.mon_x[m], w.ws.mon_y[m], "CLIPA0", 0)
    # before P6 no drop row, no thvis in the rows
    fx = MonsterPhase(mode="full", player="fx")
    assert drop_rows(fx.world) == 0 and "thvis" not in mv.rt_state(fx) and mv.nrows(fx) == mv.nrt + 10


# ---------------------------------------------------------------------------------------------- 8.3: gamespeed
def test_gamespeed_route_prediction():
    """risk 3 (MEASURED in the plan, re-measured at the integration on the RE-RECORDED keys -- O3: the turn's tap rule
    re-planned every route, tests/fixtures/gamespeed_recorded_keys.json): gamespeed's run 0, on the full model (the
    "los" sight rule), is held up by monsters -- 49 refused candidates, it ends at (763, 367); run 1 is not touched.
    R9: with `player_blocking` off the same keys land elsewhere, (872, 494). (The binary's own ends -- the "seen"
    rule, gamespeed.GameSim -- are gamespeed.BINARY_ENDS; test_gamespeed_validate holds those.)"""
    import json
    keys_by_run = json.loads((ROOT / "tests/fixtures/gamespeed_recorded_keys.json").read_text())
    ends = {}
    for blocking in (True, False):
        for run in ("0", "1"):
            w = World(monsters="full", player="full", sight_rule="los", player_blocking=blocking)
            blocked = sum(w.tic({n: bool(k.get(n)) for n in KEYS}).player_blocked for k in keys_by_run[run])
            ends[blocking, run] = (w.ws.px >> 16, w.ws.py >> 16, blocked)
    assert ends[True, "0"] == (763, 367, 49) and ends[False, "0"] == (872, 494, 0)
    assert ends[True, "1"] == ends[False, "1"] == (-296, 120, 0)


# ------------------------------------------------------------------- the still candidate (the coordinator's fix)
def _touches(w, monkeypatch, pose, angle):
    """the candidates `combat._player_move` touches for one forward tic from `pose` (whole units) at `angle`, with
    every P_TryMove refused (so all three candidates are reached)"""
    seen = []
    monkeypatch.setattr(w, "_touch_specials", lambda cx, cy, z, ev: seen.append((cx, cy)))
    monkeypatch.setattr(w.rm, "try_move", lambda *a, **k: False)
    w.ws.px, w.ws.py, w.ws.pangle = pose[0] << 16, pose[1] << 16, angle
    w.ws.p_turnheld = 0
    w._player_move(keys(forward=True), TicEvents(0))
    return seen


@pytest.mark.parametrize("pose", [(-416, 256), (-640, -512), (416, 256)])
def test_the_still_candidate_is_skipped_at_every_coordinate(world, monkeypatch, pose):
    """a candidate equal to where the player stands is never touched nor tried -- compared like with like. North
    (ANG90): the step's x is exactly 0, so the x-only candidate IS the position; at a NEGATIVE x (the player's own
    start, x -416) the old compare (a masked candidate against the signed position) let it through. R9: that old
    compare names exactly these negative poses as the ones it would have touched."""
    w = fresh(world)
    seen = _touches(w, monkeypatch, pose, 0x40000000)
    here = (pose[0] << 16, pose[1] << 16)
    assert here not in seen and len(seen) == 2, (seen, here)
    # the control: the old compare, `((x + dx) & M32, y) == (x, y)`, fails for a negative x -- the quirk this fixes
    M32 = 0xFFFFFFFF
    old_skips = ((here[0] + 0) & M32, here[1]) == here
    assert old_skips == (pose[0] >= 0)
