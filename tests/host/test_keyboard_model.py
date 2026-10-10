"""P9 -- `doomfj.keyboard.frame_keys`, the oracle of the press latch, on its own (tests/fj/test_key_latch.py holds the
program to it). The rule: a frame acts on held-after-its-polls OR pressed-during-them; a release with no press in its
frame takes effect that frame; one event per poll, so a burst spills into the next frame."""
from doomfj import keyboard as KB
from doomfj.menu import MENU_KEYS
from doomfj.wall_renderer import STANDALONE_POLLS as P

FIRE, W2, FWD = 0x85, 0x32, 0x77


def test_a_tap_inside_one_frame_counts_for_that_frame_only():
    fk = KB.frame_keys([(P, True, FIRE), (P + 1, False, FIRE)], 3)
    assert [f.now["fi"] for f in fk] == [False, True, False]
    assert [f.held["fi"] for f in fk] == [False, False, False]
    old = KB.frame_keys([(P, True, FIRE), (P + 1, False, FIRE)], 3, latch=False)
    assert [f.now["fi"] for f in old] == [False, False, False], "the pre-P9 rule (the control) missed it"


def test_a_release_without_a_press_takes_effect_in_its_frame():
    fk = KB.frame_keys([(0, True, FWD), (P + 2, False, FWD)], 3)
    assert [f.now["f"] for f in fk] == [True, False, False]
    fk = KB.frame_keys([(0, True, FWD), (P + 2, False, FWD), (P + 3, True, FWD)], 3)
    assert [f.now["f"] for f in fk] == [True, True, True], "released and pressed again: held"


def test_one_event_a_poll_spills_a_burst_into_the_next_frame():
    burst = [(0, True, c) for c in (0x61, 0x64, 0x2C, 0x2E, 0x65, 0x31, 0x33, 0x34)] + [(0, True, W2), (0, False, W2)]
    fk = KB.frame_keys(burst, 3)
    assert [f.now["w2"] for f in fk] == [False, True, False]


def test_the_menu_events_and_the_names():
    fk = KB.frame_keys([(0, True, 0x0D), (1, False, 0x0D), (2, True, FWD), (3, False, FWD)], 2)
    assert fk[0].menu == {"enter", "up"} and fk[1].menu == frozenset()
    assert fk[0].now["f"] and not fk[0].held["f"]
    assert KB.named(fk[0].now)["forward"] is True and set(KB.named(fk[0].now)) == set(KB.KEY_NAME.values())
    assert set(KB.BINDING.values()) == set(KB.HELD_KEYS) and not set(KB.BINDING) & {0x0D, 0x1B, 0x68}
    assert set(MENU_KEYS) - set(KB.BINDING) == {0x0D, 0x1B, 0x68}     # the event-only keys: enter, esc, h
    assert KB.now_cell("w1") == "kb_now + 8*dw" and KB.NOW_DECL == "kb_now: hex.vec 12"
