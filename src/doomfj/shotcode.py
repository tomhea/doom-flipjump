"""M8 C3 -- THE SHOT DOORS (GR 46: P_ShootSpecialLine -> EV_DoDoor(open)) in fj. The rules: doomfj.doors
(`shot_lines`, `shot_sid`); the model: reference_model.render_wall_frame (the record) and combat (`window_aim` reading
("shot", k), `_line_attack` -> `shot_press`).

THE RECORD (the picture). A GR line is one-sided, so a bullet that reaches it ends there: "the shot reaches the line"
is "the aim window's nearest target in the shot's column is that wall". The binary records it where the picture
decides it: around a GR seg's pass-1 call (`seg_pass1_leaf`, which claims the columns the wall wins -- `drawn`), the
window's 17 `drawn` flags are copied before (`pre_lines`), and after it the shared leaf `shot_rec` writes the line's
id (`doors.shot_sid`: from 0xFF down) into each window column the seg just claimed whose `aim_sid` is still 0 (no
nearer thing recorded) and whose horizon row (CENTERY) the nearer pieces leave open (`frame.ledge_test`, the aim
leaf's own test; the oracle's `ledge_hidden(ups[x], los[x], centery, 1)`). Things later in the walk find the column
drawn and record nothing there, as behind any wall.

THE PRESS (the weapon). `weaponcode`'s shot leaves read `aim_sid` into `dm_id` as before; a GUN's (`sh_gun`) id at or
above the lowest shot id is a shot line: each door its tag names that is at rest (`ddir`, `dwait` 0:
doors.switch_ready) gets `dreq` -- the next door tic presses it (`press_lines`). A MELEE swing (`_shot_melee`) treats
a shot id as no target (the record has no depth: combat._line_attack's rule).

KNOWN SIMPLIFICATIONS (the model's too): the horizon row stands for the bullet's height (DOOM's shootz is 5 units
under the eye); no range on the wall (MISSILERANGE is the things'); a monster's hitscan presses no GR line; the line's
switch texture does not change (doomfj.switches has no shot kind).
"""
from __future__ import annotations

from typing import List

from doomfj.aimcode import FIRST, NCOLS
from doomfj.doorcode import WAIT_NIBBLES
from doomfj.doors import SHOT_SID_TOP, shot_sid


def decls(centery: int) -> List[str]:
    """the record's cells: the window's drawn flags before the seg, the id, the fcall register, and the horizon row's
    box as frame.ledge_box makes it for y0 = CENTERY, hb = 1 (ylo1 = y0 + 1, yhi1 = y0 + 2)"""
    assert 0 <= centery and centery + 2 < 0x100
    return [f"shr_pre: hex.vec {NCOLS}", "shr_sid: hex.vec 2", "shr_ret: hex.vec w/4",
            f"shr_ylo1: hex.vec 2, {centery + 1}", f"shr_yhi1: hex.vec 2, {centery + 2}"]


def pre_lines() -> List[str]:
    """before a GR seg's pass-1 call: the window's drawn flags"""
    return [f"    hex.mov 1, shr_pre + {c}*dw, drawn + {FIRST + c}*dw" for c in range(NCOLS)]


def post_lines(k: int) -> List[str]:
    """after it: shot line k's record"""
    return [f"    hex.set 2, shr_sid, {shot_sid(k)}", "    stl.fcall shot_rec, shr_ret"]


def leaf_lines() -> List[str]:
    """`shot_rec:` ... `stl.fret shr_ret` (uses the aim leaf's scratch ar_fp / ar_cv / ar_colx)"""
    out = ["shot_rec:"]
    for c in range(NCOLS):
        x = FIRST + c
        out += [f"hex.if1 1, shr_pre + {c}*dw, shrx{c}",                    # drawn before the seg: not its column
                f"hex.if0 1, drawn + {x}*dw, shrx{c}",                      # still open: the seg did not claim it
                f"hex.if0 2, aim_sid + {2 * c}*dw, shro{c}", f";shrx{c}",     # a nearer thing recorded: it stays
                f"shro{c}:",
                f"hex.set w/4, ar_fp, sfflag + {x}*dw",
                "hex.read_byte ar_cv, ar_fp",
                f"hex.set 2, ar_colx, {x}",
                f"frame.ledge_test ar_cv, ar_colx, shr_ylo1, shr_yhi1, 0, shrx{c}",   # the horizon row hidden
                f"hex.mov 2, aim_sid + {2 * c}*dw, shr_sid",
                f"shrx{c}:"]
    return out + ["stl.fret shr_ret"]


def press_lines(shots, p: str, done: str) -> List[str]:
    """`dm_id` holds a shot id (>= the lowest, tested by the caller): EV_DoDoor(open) on its doors at rest -- each
    door's `dreq` -- and, on a SWITCH_TEX map, the line's switch texture (switches.shot_presses / press: its cell
    `swpr + k` set unless already, an SR-style countdown). `shots` [(id, (door slot, ...), switch)] with `switch`
    None or (latched index k, the repeating list); labels `<p>`; every path on to `done`"""
    from doomfj import switchcode as SWC
    out = []
    for j, spec in enumerate(shots):
        out += [f"hex.xor_by 2, dm_id, {spec[0]}", f"hex.if0 2, dm_id, {p}h{j}", f"hex.xor_by 2, dm_id, {spec[0]}"]
    out += [f";{done}"]
    for j, spec in enumerate(shots):
        sid, slots, sw = spec[0], spec[1], (spec[2] if len(spec) > 2 else None)
        out += [f"{p}h{j}:", f"hex.xor_by 2, dm_id, {sid}"]
        for i, d in enumerate(slots):
            q = f"{p}h{j}d{i}"
            out += [f"hex.if0 1, ddir + {d}*dw, {q}a", f";{q}n", f"{q}a:",
                    f"hex.if0 {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw, {q}b", f";{q}n", f"{q}b:",
                    f"hex.set 1, dreq + {d}*dw, 1", f"{q}n:"]
        if sw is not None:
            k, sr = sw
            out += [f"hex.if1 1, {SWC.cell(k)}, {done}", *(ln.strip() for ln in SWC._press(k, sr))]
        out += [f";{done}"]
    return out


def is_shot_lines(shots, cell: str, yes: str, no: str, tmp: str = "sh_t") -> List[str]:
    """`cell` (2 nibbles) holds a shot id -> `yes`, else `no` (unsigned: every id >= the lowest shot id is one)"""
    lo = SHOT_SID_TOP - len(shots) + 1
    return [f"hex.set 2, {tmp}, {lo}", f"hex.cmp 2, {cell}, {tmp}, {no}, {yes}, {yes}"]


def shot_specs(secs, lds, sds, switches=()) -> list:
    """the weapon's [(id, (door slot, ...), switch)]: doors.shot_lines with each door's slot in sorted(door sectors)
    (the door cells' order, World.door_order), and -- `switches` the map's switches.map_switches on a SWITCH_TEX map --
    the line's (latched index, repeating list), else None. [] on a map without GR lines (E1M1, E1M2)"""
    from doomfj import switches as SW
    from doomfj.doors import door_states, shot_lines
    order = sorted(door_states(secs, lds, sds))
    lat, sr = SW.latched(switches), SW.repeating(switches)
    out = []
    for k, (li, ts) in enumerate(shot_lines(secs, lds, sds)):
        ks = SW.shot_presses(lat, li)
        assert len(ks) <= 1, ks
        out.append((shot_sid(k), tuple(order.index(si) for si in ts), (ks[0], tuple(sr)) if ks else None))
    return out
