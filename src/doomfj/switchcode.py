"""M8 -- the switch textures in fj (doomfj.switches holds the rules; this is their fj mirror, line for line).

THE CELLS. `swpr`: one nibble per latched switch (`switches.latched`, linedef order), 0 / 1 -- the line shows its other
texture; `swtm`: BUTTON_NIBBLES per SR switch (`switches.repeating`), the frames left before it swaps back. Both are
persisted across the M1 reset (`map_persist`, build._map_persist) and zeroed by NEW GAME / the restart
(`level_start_lines`). The exit has no cell: `lvdone` is its latch. A switch seg's render constants switch on its cell
(wall_renderer's per-seg switch blocks, `cell`).

THE LINES, each the mirror of a `switches` step at the model's place in the frame:
  * `door_phase_lines` -- the door phase's first lines (World.switch_doors): the SR countdown, then, on a held use
    (`duse`) of a living player (`dead`, the tic-start latch), each door switch not already on whose doors include one
    at rest (`ddir` and `dwait` zero: doors.switch_ready) and whose box holds the player;
  * `use_press_lines` -- on a use PRESS, inside the exit's `ex_press` before its boxes (World.switch_uses): each floor
    switch not on whose group is still (its step timer zero; an instant group always) and each lift switch not on with
    a lift of its tag at rest (`lstate` 0), the player in its box.
A switch already on is skipped: an S1 line keeps it for good, and a press on an SR one with its button out changes
nothing (`switches.press`). The box test is the doors' (`doorcode._box_test`, on `dbox`).
"""
from __future__ import annotations

from typing import List, Sequence

from doomfj import switches as SW
from doomfj.doorcode import WAIT_NIBBLES, _box_test
from doomfj.movers import floor_sub_cell

PERSIST = ("swpr", "swtm")
BN = SW.BUTTON_NIBBLES


def cell(k: int) -> str:
    """latched switch k's cell"""
    return "swpr + %d*dw" % k


def time_cell(j: int) -> str:
    """SR switch j's countdown"""
    return "swtm + %d*dw" % (BN * j)


def decls(nlatch: int, nsr: int) -> List[str]:
    """the cells, 0 at boot (the level start)"""
    assert nlatch > 0
    return [f"swpr: hex.vec {nlatch}, 0"] + ([f"swtm: hex.vec {BN * nsr}, 0"] if nsr else [])


def map_persist(map_wad, mapname: str) -> tuple:
    """the map-dependent persisted names (build._map_persist, the game tier's): `swpr` (and `swtm` with an SR switch)
    on a map that animates its switches -- nothing on E1M1 (its image stays byte-identical)"""
    if not SW.switches_on(mapname):
        return ()
    sw = SW.map_switches(map_wad.sectors(mapname), map_wad.linedefs(mapname), map_wad.sidedefs(mapname),
                         map_wad.vertexes(mapname))
    if not SW.latched(sw):
        return ()
    return PERSIST if SW.repeating(sw) else PERSIST[:1]


def level_start_lines(nlatch: int, nsr: int) -> List[str]:
    """NEW GAME / the restart: every switch as the map has it"""
    return [f"    hex.zero {nlatch}, swpr"] + ([f"    hex.zero {BN * nsr}, swtm"] if nsr else [])


def _press(k: int, sr: Sequence[int]) -> List[str]:
    """switches.press on a switch known to be off"""
    out = [f"    hex.set 1, {cell(k)}, 1"]
    if k in sr:
        out.append(f"    hex.set {BN}, {time_cell(list(sr).index(k))}, {SW.BUTTON_FRAMES}")
    return out


def door_phase_lines(switches, door_slot: dict, dead: str | None = None) -> List[str]:
    """the door phase's switch step (World.switch_doors): the SR countdown, then the door switches a held use presses.
    `door_slot` {door sector: its slot in `dstate` / `ddir` / `dwait`}; `dead` the tic-start death cell (p_dd0) or
    None. Labels `swc<j>_` (the countdown), `swd<k>_` (door switch k)"""
    lat, sr = SW.latched(switches), SW.repeating(switches)
    out = ["// == M8: the switch textures' door phase (doomfj.switches: countdown, door_presses) =="]
    for j, k in enumerate(sr):
        t, p = time_cell(j), f"swc{j}"
        out += [f"    hex.if0 {BN}, {t}, {p}_end", f"    hex.dec {BN}, {t}", f"    hex.if0 {BN}, {t}, {p}_off",
                f"    ;{p}_end", f"  {p}_off:", f"    hex.zero 1, {cell(k)}", f"  {p}_end:"]
    doors = [(k, s) for k, s in enumerate(lat) if s.kind == "door"]
    if not doors:
        return out
    out += ["    hex.if0 1, duse, swd_end"]
    if dead is not None:
        out += [f"    hex.if1 1, {dead}, swd_end"]
    for k, s in doors:
        p = f"swd{k}"
        out += [f"    hex.if1 1, {cell(k)}, {p}_no"]
        for t, si in enumerate(s.targets):          # EV_DoDoor: one of its doors at rest (doors.switch_ready)
            d = door_slot[si]
            nxt = f"{p}_t{t + 1}" if t + 1 < len(s.targets) else f"{p}_no"
            out += [f"    hex.if0 1, ddir + {d}*dw, {p}_w{t}", f"    ;{nxt}", f"  {p}_w{t}:",
                    f"    hex.if0 {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw, {p}_box", f"    ;{nxt}"]
            if t + 1 < len(s.targets):
                out += [f"  {nxt}:"]
        out += [f"  {p}_box:", *_box_test(0, s.box, f"{p}_hit", f"{p}_no", tag=f"{p}_b"),
                f"  {p}_hit:", *_press(k, sr), f"  {p}_no:"]
    return out + ["  swd_end:"]


def use_press_lines(switches, groups, wide: bool) -> List[str]:
    """a use press's switch step (World.switch_uses), inside `ex_press` before the exit's boxes. `groups` the floor
    groups (movers.floor_groups), `wide` their layout (movers.floor_wide: the step timers exist). Labels `swu<k>_`"""
    lat, sr = SW.latched(switches), SW.repeating(switches)
    ng = len(groups)
    out = ["// == M8: the switch textures on a use press (doomfj.switches.use_presses), before the exit =="]
    for k, s in enumerate(lat):
        if s.kind not in ("floor", "lift"):
            continue
        p = f"swu{k}"
        out += [f"    hex.if1 1, {cell(k)}, {p}_no"]
        if s.kind == "floor":                       # EV_DoFloor: the group not moving (an instant one never is)
            g = s.targets[0]
            if wide and groups[g].sub:
                out += [f"    hex.if1 1, {floor_sub_cell(g, ng)}, {p}_no"]
        else:                                       # EV_DoPlat: one of its lifts at rest at the top (state 0)
            out += [f"    hex.if0 1, lstate + {slot}*dw, {p}_box" for slot in s.targets] + [f"    ;{p}_no"]
        out += [f"  {p}_box:", *_box_test(0, s.box, f"{p}_hit", f"{p}_no", tag=f"{p}_b"),
                f"  {p}_hit:", *_press(k, sr), f"  {p}_no:"]
    return out
