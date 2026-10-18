"""M8 C9 -- THE EXITS a map adds, in fj (doomfj.doors holds the rules: EXIT_SPECIALS, SECRET_EXIT_SPECIALS,
WALK_EXIT_SPECIALS; the model: combat._use_lines / combat._walkover). E1M1 and E1M2 have one S1 exit (11) and no 51 /
52, so nothing here is emitted there: their text is unchanged.

  * THE SECRET EXIT (51, E1M3): an exit switch like 11 -- `wall_renderer.exit_lines` tests its box with the others --
    and its press also sets `lvsec` (the model's g_secretexit), which LEVEL COMPLETE reads to draw SECRET EXIT under
    its title (statcode.frame_lines, menu.level_done_secret_records). The episode plan's G11: a level's binary ends at
    LEVEL COMPLETE whichever exit ended it. `lvsec` is declared, persisted across the M1 reset and zeroed by the
    restart only on a map with a 51 (`decls`, `map_persist`, `level_start_lines`).
  * TWO EXIT SWITCH LINES (E1M3's 11 + 51, E1M7's two 11s) on a map whose switches animate: each its own `swpr` cell
    (switches.latched) -- the pressed line's is set by its box's hit (`hit_lines`), so only it swaps.
  * THE W1 EXIT (52, E1M8): `walk_lines` -- in the walk's (and the knock move's) after_accept, as the walk-over
    doors: a crossing either way (`doors.crossed` on the fused segments of doors.exit_walk_triggers) ends the level
    exactly as the switch does (`lvdone` 1, `mode` 1, `menu_scr` LEVEL_DONE_ENTER: LEVEL COMPLETE from the next frame);
    the world phases after the player's skip themselves on `lvdone`, as on the press frame. No latch: the level is
    over. Monsters never fire it (52 is not on P_CrossSpecialLine's monster list).
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from doomfj import doors as D

PERSIST = ("lvsec",)


def secret_exit_on(lds) -> bool:
    """the map has a secret exit line (51)"""
    return any(D.secret_exits(lds))


def decls(lds) -> List[str]:
    return ["lvsec: hex.vec 1, 0"] if secret_exit_on(lds) else []


def map_persist(map_wad, mapname: str) -> tuple:
    """build._map_persist's: `lvsec` on a map with a secret exit (the reset leaves it to NEW GAME / the restart)"""
    return PERSIST if secret_exit_on(map_wad.linedefs(mapname)) else ()


def level_start_lines(lds) -> List[str]:
    """NEW GAME / the restart: no exit used"""
    return ["    hex.zero 1, lvsec"] if secret_exit_on(lds) else []


def hit_lines(lds, latched: Sequence = ()) -> Dict[int, List[str]]:
    """{exit box k: the lines its press runs before the shared `ex_hit`} -- the secret exit's `lvsec`, and the pressed
    line's own switch cell when the exit switches are latched (`latched`: switches.latched of the map's switches).
    {} on a map with one plain exit (E1M1, E1M2: exit_lines' text unchanged)"""
    from doomfj.switchcode import cell
    out: Dict[int, List[str]] = {}
    sec = D.secret_exits(lds)
    lat_lines = [s.line for s in latched]
    for k, line in enumerate(D.exit_lines(lds)):
        extra = (["hex.set 1, lvsec, 1"] if sec[k] else []) + (
            [f"hex.set 1, {cell(lat_lines.index(line))}, 1"] if line in lat_lines else [])
        if extra:
            out[k] = extra
    return out


def walk_lines(trigs, radius: int, fire: Sequence[str], prefix: str = "xw") -> List[str]:
    """the W1 exit lines (doors.exit_walk_triggers) after an accepted player move (cm_ox, cm_oy) -> (viewx, viewy):
    a crossing of any -> `fire` (the level ends), then on. [] on a map without one"""
    from doomfj.doorcode import _crossed_d_lines, _crossed_lines
    if not trigs:
        return []
    out = ["  // M8 C9: the W1 exit (doomfj.doors.exit_walk_triggers, combat._walkover)"]
    for k, trig in enumerate(trigs):
        p = f"{prefix}{k}"
        go = [f"    ;{prefix}_fire"]
        out += (_crossed_d_lines(p, trig[2:], radius, go) if trig[1] == "d"
                else _crossed_lines(p, *trig[1:], radius, go))
    out += [f"    ;{prefix}_end", f"  {prefix}_fire:", *[f"    {ln}" for ln in fire], f"  {prefix}_end:"]
    return out
