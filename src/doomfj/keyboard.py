"""P9 -- THE KEYBOARD, frame by frame: the oracle side of src/fj/input.fj's `kb.poll` and the game tier's input
prologue (`wall_renderer.standalone_key_lines`), and the names both sides share.

THE DEVICE (flipjump's KeyboardIO): one poll = one tic of its clock; at most ONE event is delivered per poll, the next
due one (`event.tic <= tic`), so a burst spills into later polls -- and past the frame's last poll into the next frame.
A standalone frame runs `wall_renderer.STANDALONE_POLLS` polls, so frame f's polls are tics [f*P, (f+1)*P).

THE KEYS THE FRAME ACTS ON (the owner's play-test, 2026-10-10: "a key pressed since the last input check must
count"). Each HELD key -- move, turn, strafe, use, fire, the number keys -- has a persisted flag `kb_<key>` that its
down event sets and its up event clears ("this key is held"; build.STANDALONE_PERSIST). Until P9 the frame acted on
the flag as the polls left it, so a TAP whose down AND up both landed in one frame's polls did nothing at all. Now
the frame acts on

    now[key] = held[key] after this frame's polls  OR  the key went DOWN at least once during them

-- the nibble `kb_now + i*dw` (i = HELD_KEYS.index(key)): zeroed before the frame's polls, set by a down event
(input.fj), then OR-ed with the held flag (`now_lines`), and read by everything that used to read the flags -- the
`pkeys` byte the sim, the doors, the exit, the restart on use and the weapon's fire read, and the weapon's number keys
(weaponcode). A release in a frame with no press still takes effect that frame (held 0, no press: 0). The menu's
EVENTS (enter, esc, up, down, help -- `menu.MENU_KEYS`) were latched already (`ev_*`) and are unchanged.

`kb_now` is per-frame scratch: written (zeroed) before every read, every frame, so it is NOT persisted -- it is a
standalone global like `ev_*` (wall_renderer.STANDALONE_SCRATCH_DECLS) and the M1 restore set carries it as ordinary
residue (it needs no restoring, and restoring it is harmless).
"""
from __future__ import annotations

from typing import Dict, FrozenSet, List, NamedTuple, Optional

# the held keys, in kb.poll's parameter order and `kb_now`'s nibble order -- forward, back, turn left / right (the
# arrows), use (space, e), strafe left / right, fire (ctrl), the number keys 1..5 (P9: 5, the launcher)
HELD_KEYS = ("f", "b", "l", "r", "u", "sl", "sr", "fi", "w1", "w2", "w3", "w4", "w5")   # P9: 5, the launcher
KEY_NOW = "kb_now"
NOW_DECL = f"{KEY_NOW}: hex.vec {len(HELD_KEYS)}"

# keycode -> held key: src/fj/input.fj's table (the SDL codes pygame_window delivers)
BINDING = {0x77: "f", 0x80: "f", 0x73: "b", 0x81: "b", 0x82: "l", 0x83: "r", 0x20: "u", 0x65: "u",
           0x61: "sl", 0x2C: "sl", 0x64: "sr", 0x2E: "sr", 0x85: "fi",
           0x31: "w1", 0x32: "w2", 0x33: "w3", 0x34: "w4", 0x35: "w5"}
# held key -> wireformat.KEY_NAMES' name (the dicts the sim and the gates use); the number keys keep theirs
KEY_NAME = {"f": "forward", "b": "back", "l": "turn_left", "r": "turn_right", "u": "use",
            "sl": "strafe_left", "sr": "strafe_right", "fi": "fire",
            "w1": "w1", "w2": "w2", "w3": "w3", "w4": "w4", "w5": "w5"}


def flag(key: str) -> str:
    """the persisted held flag's label"""
    assert key in HELD_KEYS, key
    return "kb_" + key


def now_cell(key: str) -> str:
    """the fj operand of `key`'s nibble of KEY_NOW -- what the frame acts on"""
    return f"{KEY_NOW} + {HELD_KEYS.index(key)}*dw"


def now_lines(prefix: str = "kn") -> List[str]:
    """after the polls: kb_now[key] |= the held flag, for every held key (both are 0 or 1, so a held key SETS it).
    One `if0` per key, and a `set` per key held."""
    out = []
    for key in HELD_KEYS:
        out += [f"hex.if0 1, {flag(key)}, {prefix}_{key}", f"hex.set 1, {now_cell(key)}, 1", f"{prefix}_{key}:"]
    return out


class FrameKeys(NamedTuple):
    held: Dict[str, bool]          # the persisted flags after the frame's polls (kb_<key>)
    now: Dict[str, bool]           # what the frame acts on (kb_now): held OR went down during the polls
    menu: FrozenSet[str]           # the menu's events: menu.MENU_KEYS names whose key went DOWN during the polls


def frame_keys(events, frames: int, polls: Optional[int] = None, binding=None, menu_keys=None,
               latch: bool = True) -> List[FrameKeys]:
    """THE ORACLE: `events` (flipjump KeyEvents, or (tic, is_down, keycode) triples) delivered by the device's rule,
    one per poll, `polls` a frame -> each frame's FrameKeys, the dicts keyed by HELD_KEYS (binding=None) or by
    `binding`'s values. `latch=False` is the pre-P9 rule (now = held) -- kept ONLY as the negative control of the
    tests that hold the program to this one."""
    if polls is None:
        from doomfj.wall_renderer import STANDALONE_POLLS as polls
    if menu_keys is None:
        from doomfj.menu import MENU_KEYS as menu_keys
    from doomfj.menu import ANY_KEY_EVENT
    binding = BINDING if binding is None else binding
    names = sorted(set(binding.values()), key=lambda n: (HELD_KEYS.index(n) if n in HELD_KEYS else 99, n))
    pending = sorted((tuple(e) for e in events), key=lambda e: e[0])
    held = {n: False for n in names}
    out, i = [], 0
    for f in range(frames):
        pressed, menu = set(), set()
        for tic in range(f * polls, (f + 1) * polls):
            if i < len(pending) and pending[i][0] <= tic:
                _t, is_down, code = pending[i]
                i += 1
                if is_down and code in menu_keys:
                    menu.add(menu_keys[code])
                if is_down:
                    menu.add(ANY_KEY_EVENT)          # P10: every key's down edge (input.fj's ev_any)
                name = binding.get(code)
                if name is not None:
                    held[name] = bool(is_down)
                    if is_down:
                        pressed.add(name)
        now = {n: held[n] or (latch and n in pressed) for n in names}
        out.append(FrameKeys(dict(held), now, frozenset(menu)))
    return out


def named(keys: Dict[str, bool]) -> Dict[str, bool]:
    """a HELD_KEYS-keyed dict as wireformat's names (forward, back, ..., fire) plus w1..w4"""
    return {KEY_NAME[k]: v for k, v in keys.items()}
