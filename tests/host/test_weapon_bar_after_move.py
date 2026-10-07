"""M7 P6+P7 -- the bar's weapon slots (the ready weapon's ammo digits, the owned weapons) are copied AFTER the
player's move: the move's pickups change the ammo and the owned weapons, and DOOM and the oracle draw the bar from
the tic's end. Copied in the weapon phase (before the move) the bar lagged a frame -- blocked49's m2 gate, frame 212:
the shotgun picked up at easy, wp_own right, ARMS 3 still grey (14 px).

The end-to-end proof is m2_std_gate's walk at easy (it picks the shotgun up); this pins the order the emitter
composes, with its control.
"""
from doomfj import wall_renderer as WR
from doomfj import weaponcode as WC


def _states():
    states = WC.weapon_states()
    return states, WC.overlay_frames(states)


def test_with_loot_the_weapon_tic_writes_no_bar_slot():
    states, frames = _states()
    tic = WC.weapon_lines(states, frames, hurt=True, loot=True)          # the loot player is the hurt one
    assert not any("hud_v" in ln for ln in tic), "the weapon phase still copies the bar (before the move)"
    bar = WC.bar_lines()
    assert any(ln.startswith("hex.mov 3, hud_v,") for ln in bar)
    assert sum("hud_v + " in ln for ln in bar) == 3                       # owned 2, 3, 4


def test_without_loot_the_bar_stays_in_the_weapon_tic():
    states, frames = _states()
    tic = WC.weapon_lines(states, frames)
    assert any(ln.startswith("hex.mov 3, hud_v,") for ln in tic)        # P4/P5's text unchanged: no pickups


def test_the_frame_copies_the_bar_after_the_move_and_before_the_monsters():
    lines = WR._standalone_input_lines(True, menu=["MENU"], monster_tic=["MONSTERS"], weapon=["WEAPON"],
                                       weapon_bar=["BAR"], exit_boxes_=())
    assert lines.index("WEAPON") < lines.index("simmv_done:") < lines.index("BAR") < lines.index("MONSTERS")


def test_control_the_order_test_sees_a_bar_before_the_move():
    """R9: the same check on a composition that puts the bar in the weapon phase must fail"""
    lines = WR._standalone_input_lines(True, menu=["MENU"], monster_tic=["MONSTERS"], weapon=["WEAPON", "BAR"],
                                       exit_boxes_=())
    assert not (lines.index("simmv_done:") < lines.index("BAR"))
