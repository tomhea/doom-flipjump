"""M8 -- THE SWITCH TEXTURES CHANGE: DOOM's P_ChangeSwitchTexture, the ONE rule both mirrors read (the model:
doomfj.world / combat and the gates' MonsterPhase hooks; the fj: doomfj.switchcode; the picture: reference_model's
`wall_tone_names(pressed=)` and wall_renderer's per-seg switch blocks).

THE RULE (p_switch.c). A switch line -- one whose texture (upper, middle or lower, either side) is a switch name, SW1xxxx
or SW2xxxx -- that a USE starts something on shows its OTHER texture: SW1xxxx as SW2xxxx, SW2xxxx as SW1xxxx. An S1 line
(and the exit) keeps it for good; an SR line swaps back after BUTTONTIME (`BUTTON_FRAMES`). "Starts something" is the
special's EV_* returning 1, each read on the machine's state at the press, in the model's order:

  * a door switch (SR 63 / S1 103, `doors.SWITCH_DOOR_KINDS`): EV_DoDoor -- one of the doors its tag names is at rest
    (`doors.switch_ready`: no thinker). Pressed by the doors' HELD use, in the door phase before the doors tic (the
    phase that presses them: World._doors_phase);
  * an S1 floor line (23 / 71 / 102, `movers.FLOOR_USE_SPECIALS`): EV_DoFloor -- its tag's floor group is not moving
    (its step timer 0: untouched, arrived, or an instant group);
  * an SR lift line (62 / 123, `movers.LIFT_USE_SPECIALS`): EV_DoPlat -- one of its tag's lifts is at rest at the top
    (state 0: `movers.lift_tic`'s rule);
  * the exit (11): always -- and the level is done (`g_leveldone` / fj `lvdone`), which IS its latch.
The floor and lift lines take the use PRESS (P_UseLines' edge: World._use_lines, the fj's `ex_press`), before the exit's
test. A press in the line's box -- the line's extent inflated by USE_RANGE, the box every one of those machines already
tests (`doors.switch_door_triggers`, `movers.use_line_boxes`, `doors.exit_boxes`).

THE STATE: one 0/1 cell per switch line but the exit (`latched`, linedef order: the World's `sw_on`, the fj's `swpr`)
and, for the SR ones, a frame countdown (`sw_time` / `swtm`, BUTTON_NIBBLES nibbles). The countdown runs at the start of
the door phase (before the presses); at 0 the line swaps back. Both persist across the M1 reset; NEW GAME / the
restart zeroes them (the level start: every switch as the map has it).

THE PICTURE: the game picture's wall tones (reference_model.wall_tone_names) -- a switch line wears "#SWITCH" (the exit
"#EXIT") while it shows an SW1 texture and "#SWITCHON" while it shows an SW2 one.

KNOWN SIMPLIFICATIONS: a press on an SR line whose button is still out changes nothing (DOOM swaps the texture back early
and keeps the first button's timer); a tic is a frame, as the doors' WAIT; the exit's latch is the level's, so a map
with two exit switch lines is refused (`map_switches`). A switch line whose special starts nothing here (an unsupported
special, or a tag naming no machine) keeps its texture.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Sequence

from doomfj.doors import USE_RANGE

SWITCH_PREFIXES = ("SW1", "SW2")          # DOOM's switch textures (alphSwitchList's pairs share the suffix)
BUTTON_FRAMES = 35                        # BUTTONTIME (35 tics): a tic is a frame here
BUTTON_NIBBLES = 2                        # the countdown's cell
assert 0 < BUTTON_FRAMES < 16 ** BUTTON_NIBBLES
EXIT_SWITCH_SPECIALS = frozenset({11})    # S1 exit (doors.EXIT_SPECIALS)
DOOR_SWITCH_SPECIALS = frozenset({63, 103, 61, 112, 114, 133})   # doors.SWITCH_DOOR_KINDS (M8 C3: 61 112 114 133)
FLOOR_SWITCH_SPECIALS = frozenset({23, 71, 102, 7, 20})     # movers.FLOOR_USE_SPECIALS (M8 C4: + 7 stairs, 20 plat)
LIFT_SWITCH_SPECIALS = frozenset({62, 123})          # movers.LIFT_USE_SPECIALS
LIGHT_SWITCH_SPECIALS = frozenset({138})             # M8 C4: lights.SWITCH_LIGHT_SPECIALS (EV_LightTurnOn: always)
REPEAT_SPECIALS = frozenset({62, 123, 63, 61, 114, 46, 138})   # SR (and GR 46): the texture comes back after BUTTONTIME
SHOT_SWITCH_SPECIALS = frozenset({46})               # M8 C3: GR 46 (doors.SHOOT_DOOR_KINDS) -- a shot swaps it


@dataclass(frozen=True)
class Switch:
    """one animated switch line. `kind` "exit" / "door" / "floor" / "lift"; `sw2` its level-start texture is an SW2
    one; `box` (x0, y0, x1, y1) map units; `targets` -- a door switch's door SECTORS, a lift line's lift SLOTS (the lifts'
    sector order), a floor line's (group index,); the exit's (); M8 C4 a light switch's ("light") tagged sectors"""
    line: int
    special: int
    kind: str
    repeat: bool
    sw2: bool
    box: tuple
    targets: tuple


def switch_texture(lds, sds, i: int):
    """linedef i's switch texture name (upper, middle, lower; the front side first), or None"""
    ld = lds[i]
    sides = [sds[ld.front]] + ([sds[ld.back]] if 0 <= ld.back < len(sds) else [])
    for sd in sides:
        for t in (sd.upper, sd.middle, sd.lower):
            t = (t or "").upper()
            if t.startswith(SWITCH_PREFIXES):
                return t
    return None


def switches_on(mapname: str) -> bool:
    """the map animates its switches (config.MAP_CONFIG's SWITCH_TEX; never on E1M1)"""
    from doomfj.config import Config, map_cfg
    return bool(map_cfg(Config(), mapname).SWITCH_TEX)


def _xy(v):
    return (v.x, v.y) if hasattr(v, "x") else (v[0], v[1])


def map_switches(secs, lds, sds, verts, rng: int = USE_RANGE) -> List[Switch]:
    """every switch line a use can change, in linedef order (see the module docstring)"""
    from doomfj import movers as MV
    from doomfj.doors import door_sectors
    doors = door_sectors(secs, lds, sds)
    lift_order = sorted(MV.lift_states(secs, lds, sds))
    lift_slots = MV.lift_slots_of_tag(secs, lift_order)
    groups = MV.floor_groups(secs, lds, sds)
    group_of = {g.tag: k for k, g in enumerate(groups)}
    out = []
    for i, ld in enumerate(lds):
        tex = switch_texture(lds, sds, i)
        sp = ld.special
        if tex is None:
            continue
        if sp in EXIT_SWITCH_SPECIALS:
            kind, targets = "exit", ()
        elif sp in DOOR_SWITCH_SPECIALS and ld.tag:
            kind, targets = "door", tuple(si for si, sec in enumerate(secs) if sec.tag == ld.tag and si in doors)
        elif sp in SHOT_SWITCH_SPECIALS and ld.tag:
            # M8 C3: P_ShootSpecialLine's 46 changes its texture on EVERY shot that reaches it (no EV_* test)
            kind, targets = "shot", tuple(si for si, sec in enumerate(secs) if sec.tag == ld.tag and si in doors)
        elif sp in FLOOR_SWITCH_SPECIALS and ld.tag in group_of:
            kind, targets = "floor", (group_of[ld.tag],)
        elif sp in LIFT_SWITCH_SPECIALS and ld.tag:
            kind, targets = "lift", tuple(lift_slots.get(ld.tag, ()))
        elif sp in LIGHT_SWITCH_SPECIALS and ld.tag:
            # M8 C4: P_UseSpecialLine 138 -- EV_LightTurnOn, then P_ChangeSwitchTexture(line, 1) whatever it found
            kind, targets = "light", tuple(si for si, sec in enumerate(secs) if sec.tag == ld.tag)
        else:
            continue                                   # no special a use starts here: the texture stays
        if kind != "exit" and not targets:
            continue
        (ax, ay), (bx, by) = _xy(verts[ld.v1]), _xy(verts[ld.v2])
        out.append(Switch(i, sp, kind, sp in REPEAT_SPECIALS, tex.startswith("SW2"),
                          (min(ax, bx) - rng, min(ay, by) - rng, max(ax, bx) + rng, max(ay, by) + rng), targets))
    assert sum(s.kind == "exit" for s in out) <= 1, (
        "two exit switch lines: the exit's latch is the level's (lvdone), one line's")
    return out


def latched(switches: Sequence[Switch]) -> List[Switch]:
    """the switches with a cell of their own (all but the exit), in order: switch k is cell `swpr + k*dw`"""
    return [s for s in switches if s.kind != "exit"]


def repeating(switches: Sequence[Switch]) -> List[int]:
    """the latched indices of the SR switches, in order: SR switch j counts down in `swtm + BUTTON_NIBBLES*j*dw`"""
    return [k for k, s in enumerate(latched(switches)) if s.repeat]


def in_box_fixed(box, x16: int, y16: int) -> bool:
    """doors.in_use_box_fixed (the doors' inclusive 16.16 test)"""
    from doomfj.doors import in_use_box_fixed
    return in_use_box_fixed(box, x16, y16)


def countdown(on: list, time: list, sr: Sequence[int]) -> None:
    """the door phase's first step, in place: each SR button out counts down a frame; at 0 its line swaps back"""
    for j, k in enumerate(sr):
        if time[j]:
            time[j] -= 1
            if not time[j]:
                on[k] = 0


def press(on: list, time: list, sr: Sequence[int], k: int) -> None:
    """latched switch k's EV_* returned 1: its texture swaps -- an SR one only while its button is in (then
    BUTTON_FRAMES frames out); an S1 one for good"""
    if on[k]:
        return
    on[k] = 1
    if k in sr:
        time[list(sr).index(k)] = BUTTON_FRAMES


def door_presses(lat: Sequence[Switch], used: bool, x16: int, y16: int, ready: Callable[[int], bool],
                 has_card: Callable[[str], bool] | None = None) -> List[int]:
    """the door switches a held use presses this tic (`used`: the use key, the player alive): EV_DoDoor finds one of
    the line's doors at rest (`ready(sector)`, the tic-start state) and the player stands in the line's box. M8 C3: a
    LOCKED switch (doors.SWITCH_DOOR_CARDS: S1 133) also needs its card -- `has_card(colour)` (EV_DoLockedDoor returns
    0 without it: no texture change)"""
    if not used:
        return []
    from doomfj.doors import SWITCH_DOOR_CARDS
    return [k for k, s in enumerate(lat) if s.kind == "door"
            and (s.special not in SWITCH_DOOR_CARDS or has_card(SWITCH_DOOR_CARDS[s.special]))
            and any(ready(si) for si in s.targets) and in_box_fixed(s.box, x16, y16)]


def use_presses(lat: Sequence[Switch], x16: int, y16: int, lift_rest: Callable[[int], bool],
                floor_still: Callable[[int], bool]) -> List[int]:
    """the floor and lift switches a use PRESS changes: EV_DoFloor finds the line's group not moving
    (`floor_still(g)`), EV_DoPlat one of its lifts at rest at the top (`lift_rest(slot)`), and the player stands in
    the line's box -- read BEFORE the press fires them (P_UseSpecialLine's order: the EV_* call returns, then the
    texture)"""
    out = []
    for k, s in enumerate(lat):
        if s.kind == "floor":
            ok = floor_still(s.targets[0])
        elif s.kind == "lift":
            ok = any(lift_rest(t) for t in s.targets)
        elif s.kind == "light":                  # M8 C4: EV_LightTurnOn's switch always changes
            ok = True
        else:
            continue
        if ok and in_box_fixed(s.box, x16, y16):
            out.append(k)
    return out


def shot_presses(lat: Sequence[Switch], line: int) -> List[int]:
    """M8 C3: the latched switches a gun's shot on GR line `line` swaps (doors.shot_lines; combat.shot_press)"""
    return [k for k, s in enumerate(lat) if s.kind == "shot" and s.line == line]


def pressed_lines(switches: Sequence[Switch], on: Sequence[int], leveldone: bool) -> frozenset:
    """the linedefs showing their other texture: each latched switch whose cell is set, and the exit once the level
    is done"""
    lat = latched(switches)
    out = {s.line for k, s in enumerate(lat) if on[k]}
    if leveldone:
        out |= {s.line for s in switches if s.kind == "exit"}
    return frozenset(out)
