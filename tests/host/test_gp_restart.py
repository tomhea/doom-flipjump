"""S3b: player death and the restart block, the exit switch, nukage, and determinism with combat.

The restart block (plan 6.7) writes every persisted field back to its level-start value for the
current skill, keeping only the menu mode and the held keys; the tests hold it equal to a fresh
World and prove, field by field, that forgetting any one field is caught (R9)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from doomfj import combat as C
from doomfj import gamedata as gd
from doomfj import world as W

ROOT = Path(__file__).resolve().parents[2]

# A scripted fight from the player's start: four monsters put in front of him, awake; he fires in
# bursts, walks into them, switches to the fist and turns. Deterministic by construction.
SCENARIO_SRC = """
def scenario(W, gd, skill=None):
    w = W.World(skill=gd.SK_HARD if skill is None else skill)
    ws = w.ws
    px, py = ws.px >> 16, ws.py >> 16
    for doomednum, dx, dy in ((3004, 160, 0), (3001, 220, 40), (9, 250, -40), (3002, 300, 0)):
        ms = [i for i in range(w.layout.nmon)
              if w.mon_things[i].type == doomednum and ws.mon_active[i]]
        if not ms:
            continue
        m = ms[0]
        w.teleport_monster(m, px + dx, py + dy)
        ws.mon_target[m] = 1
        w._set_state(m, w.mon_info[m].seestate, False, W.TicEvents(0))
    keys = []
    for t in range(300):
        k = {"fire": t % 50 < 40}
        if 120 <= t < 160:
            k["forward"] = True
        if t in (170, 171):
            k["w1"] = True
        if 220 <= t < 232:
            k["turn_left"] = True
        keys.append(k)
    return w, keys
"""
_ns = {}
exec(SCENARIO_SRC, _ns)
scenario = _ns["scenario"]


def _played(skill=gd.SK_HARD):
    w, keys = scenario(W, gd, skill)
    for k in keys:
        w.tic(k)
    return w


# ---- the restart block -----------------------------------------------------------------------
@pytest.mark.parametrize("skill", [gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD])
def test_the_restart_block_equals_a_fresh_level_start(skill):
    w = _played(skill)
    tot = w.event_totals()
    assert tot["fired"] and tot["hits"] and tot["player_hurt"]          # a real game was played
    assert w.digest() != W.World(skill=skill).digest()
    w._restart(W.TicEvents(w.tic_count))
    assert w.digest() == W.World(skill=skill).digest()
    assert w.leaf_lists() == w.leaf_lists_from_scratch()


def test_new_game_runs_the_restart_at_the_next_tic():
    """NEW GAME at another skill: the next tic is the new game's first tic, exactly."""
    w = _played()
    w.new_game(gd.SK_MEDIUM)
    k = {"forward": True, "fire": True}
    ev = w.tic(k)
    fresh = W.World(skill=gd.SK_MEDIUM)
    fresh.tic(k)
    assert ev.restarts == 1 and w.digest() == fresh.digest()


def _perturb(ws):
    for f in ws.schema:
        if f.name in C.RESTART_KEEP:
            continue
        if f.count == 1:
            setattr(ws, f.name, getattr(ws, f.name) ^ 1)
        else:
            arr = getattr(ws, f.name)
            arr[f.count - 1] = arr[f.count - 1] ^ 1


def test_a_restart_that_forgets_any_one_field_is_caught():
    """R9, field by field: with one field dropped from the block, a perturbed state no longer
    restarts to the fresh level; with none dropped it does (the control)."""
    fresh = W.World(skill=gd.SK_HARD).digest()
    w = W.World(skill=gd.SK_HARD)
    full = w.restart_fields
    assert set(full) == {f.name for f in w.schema} - set(C.RESTART_KEEP)
    for name in full:
        _perturb(w.ws)
        w.restart_fields = tuple(n for n in full if n != name)
        w._restart(W.TicEvents(0))
        assert w.digest() != fresh, name
        w.restart_fields = full
        w._restart(W.TicEvents(0))
        assert w.digest() == fresh, name


def test_the_restart_keeps_the_menu_mode_and_the_held_keys():
    w = _played()
    ws = w.ws
    ws.mode, ws.kb_f, ws.kb_u = 1, 1, 1
    w._restart(W.TicEvents(0))
    assert (ws.mode, ws.kb_f, ws.kb_u) == (1, 1, 1)
    assert ws.leveltime == 0 and ws.p_health == 100            # the level state did reset


# ---- player death ----------------------------------------------------------------------------
def test_death_is_doom_shaped_and_use_asks_for_the_restart():
    w = W.World(skill=gd.SK_HARD)
    for _ in range(20):
        w.tic({})
    ws = w.ws
    ev = W.TicEvents(w.tic_count)
    w.damage_player(250, ("test", 0), ev)                     # overkill: health 100 - 250
    assert ev.deaths == 1 and ws.p_dead and ws.p_health == -150
    assert gd.STATE_NAMES[ws.p_mobj_state] == "S_PLAY_XDIE1"  # < -spawnhealth: the gib
    assert gd.STATE_NAMES[ws.p_wpn_state] == "S_PISTOLDOWN"   # P_DropWeapon
    x, y = ws.px, ws.py
    for _ in range(45):                                        # dead: no move, no fire, no restart
        ev = w.tic({"forward": True, "fire": True})
        assert not ev.fired and not ev.restart_requests
    assert (ws.px, ws.py) == (x, y) and ws.p_wpn_sy == 128    # the weapon lowered and stays down
    assert gd.STATE_NAMES[ws.p_mobj_state] == "S_PLAY_XDIE9"
    ev = w.tic({"use": True})
    assert ev.restart_requests == 1 and ws.g_restart and ws.p_dead
    k = {"forward": True}
    ev = w.tic(k)
    fresh = W.World(skill=gd.SK_HARD)
    fresh.tic(k)
    assert ev.restarts == 1 and w.digest() == fresh.digest()


def test_a_plain_death_and_the_monsters_stand_down():
    """A death at health >= -100 is S_PLAY_DIE1; a dead player is no longer solid to monsters."""
    w = W.World(skill=gd.SK_HARD)
    ws = w.ws
    ws.p_health = 10
    w.damage_player(10, ("test", 0), W.TicEvents(0))
    assert ws.p_dead and ws.p_health == 0
    assert gd.STATE_NAMES[ws.p_mobj_state] == "S_PLAY_DIE1"
    m = next(i for i in range(w.layout.nmon) if ws.mon_active[i])
    assert w._thing_blocker(m, ws.px >> 16, ws.py >> 16, 20) != ("player", -1)


# ---- the exit switch ---------------------------------------------------------------------------
def _at_exit(w):
    (x0, y0, x1, y1), = w.exit_boxes
    w.teleport_player(((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16)


def test_the_exit_switch_ends_the_level_on_the_use_press():
    w = W.World(skill=gd.SK_HARD)
    assert len(w.exit_boxes) == 1
    for _ in range(3):
        w.tic({})
    _at_exit(w)
    ev = w.tic({"use": True})
    assert ev.level_done and w.ws.g_leveldone
    frozen = w.digest()
    for _ in range(5):
        ev = w.tic({"forward": True, "fire": True})
        assert ev.frozen
    assert w.digest() == frozen                               # nothing moves after the exit
    w.new_game()
    ev = w.tic({})
    assert ev.restarts == 1 and not ev.frozen and not w.ws.g_leveldone


def test_the_exit_needs_a_fresh_press_and_the_box():
    """Controls: use already held (DOOM's usedown) does not trigger; nor does use outside the box."""
    w = W.World(skill=gd.SK_HARD)
    _at_exit(w)
    assert w.ws.p_usedown == 1                                # G_PlayerReborn: held at start
    assert not w.tic({"use": True}).level_done
    w = W.World(skill=gd.SK_HARD)
    w.tic({})
    assert not w.tic({"use": True}).level_done               # at the start: not in the box


# ---- nukage ------------------------------------------------------------------------------------
NUKAGE_SPOTS = {23: (2008, 1342), 38: (1928, 914), 173: (1272, 1112)}


@pytest.mark.parametrize("sector", sorted(NUKAGE_SPOTS))
def test_nukage_hurts_5_every_32_tics_when_standing_on_it(sector):
    w = W.World(skill=gd.SK_HARD)
    x, y = NUKAGE_SPOTS[sector]
    assert w.secs[sector].special == 7 and w.leaf_sector[
        w.rm.point_in_subsector(w.cmap, x, y)] == sector
    w.teleport_player(x << 16, y << 16)
    ws = w.ws
    ws.leveltime = 63
    assert w.tic({}).nukage == 0 and ws.p_health == 100      # 63 & 31 != 0
    ev = w.tic({})                                            # leveltime 64
    assert ev.nukage == 1 and ws.p_health == 95
    ws.p_armortype, ws.p_armor, ws.leveltime = 1, 100, 96
    w.tic({})
    assert ws.p_health == 95 - 4 and ws.p_armor == 99        # armor takes 5 // 3 = 1


def test_nukage_spares_other_floors():
    w = W.World(skill=gd.SK_HARD)
    w.ws.leveltime = 64
    ev = w.tic({})                                            # the start room: special 0
    assert ev.nukage == 0 and w.ws.p_health == 100


# ---- determinism ---------------------------------------------------------------------------------
RUNNER = SCENARIO_SRC + """
from doomfj import world as W, gamedata as gd
w, keys = scenario(W, gd)
for k in keys:
    w.tic(k)
print(w.digest())
"""


def test_combat_is_deterministic_and_independent_of_the_hash_seed():
    here = _played()
    tot = here.event_totals()
    for k in ("fired", "hits", "kills", "fx_spawns", "mon_shots", "mon_melee", "player_hurt",
              "player_blocked"):
        assert tot[k] > 0, k                                  # vacuity: the run fought
    got = set()
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, "-c", RUNNER], capture_output=True, text=True,
                           cwd=ROOT, env=env, timeout=300)
        assert r.returncode == 0, r.stderr[-2000:]
        got.add(r.stdout.strip())
    assert got == {here.digest()}


def test_the_trajectory_hash_sees_a_changed_combat_rule(monkeypatch):
    """R9 for the determinism check: one changed damage table entry changes the game's hash."""
    base = _played().digest()
    real = C.Sites.__init__

    def patched(self, rm):
        real(self, rm)
        k, table = self.troop_claw
        self.troop_claw = (k, [v + 1 for v in table])
    monkeypatch.setattr(C.Sites, "__init__", patched)
    assert _played().digest() != base
