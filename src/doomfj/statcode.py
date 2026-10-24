"""P10 (the owner's play-test, 2026-10-12: LEVEL COMPLETE "should have some stats") -- THE LEVEL'S STATS, the program's
side (docs/gp-p10-plan.md). The oracle's side: world.build_schema's P10 fields, combat's counters (`_kill_monster`,
`_touch_specials`, `_special_sector`), and `menu.level_done_*` / `menu.stats_digits` for the picture; `stats_of` below
reads a World into it.

THE CELLS (the schema's P10 fields by their labels; `decls` -- declared with the standalone globals, PERSISTed across
the M1 reset (build.STAT_PERSIST) and zeroed by the restart (`level_start_lines`, restart_common's)):

    st_kill   2 nibbles         p_killcount    + 1 at every monster's death -- damagecode's `dm_kill` (`kill_lines`);
                                               every E1M1 monster is COUNTKILL (asserted), and a single player counts
                                               the deaths the monsters and the barrels cause too
    st_item   2 nibbles         p_itemcount    + 1 at a COUNTITEM pickup taken -- lootcode's give routine's taken exit
                                               (`counts_item`, `item_lines`); no drop is COUNTITEM (asserted)
    st_secn   1 nibble          p_secretcount  + 1 at a secret sector entered (`secret_lines`)
    st_secm   nsecret nibbles   p_secret       secret k entered (`World.secret_sectors` order)

THE SECRETS (`sc_go`, fcall'd every alive tic from lootcode's `pre`, before nukage; combat._special_sector). For each
secret not yet entered, the BOX of its sector -- its lines' vertices' bounds -- against the player's whole-unit
position: outside every box, that is all (a few compares a secret a frame). Inside one, the point location
(`ptloc_walk`, the model's `player_sector`), the leaf's sector (`lfsec`) against each unentered secret, then nukage's
"on the floor" test (`ms_seed_leaf` against `sim.check_cells`' floorz) -> the bit and the count. The box is exact as a
FILTER for every position the player can be at: the collision keeps his centre inside the map's sectors (no box
crosses a one-sided line), and a point inside a sector's lines lies inside their bounds. (A point in the void behind a
wall is placed in SOME leaf by the BSP, possibly outside that leaf's sector's bounds -- no player is there; the fj test
stands him only where the model's check_position takes his box.) The use lines run
before this in fj and after it in the model, which is harmless for the same reason as nukage's: a use press only
REQUESTS a lift or the floor switch (`lreq`, `fswitch`), and the movers act on it in the next frame's mover tic.

LEVEL COMPLETE (`digit_lines`, `frame_lines`): the 13 digit slots (`st_dig`, a nibble each, menu.stats_digits' order)
from the cells, the skill's totals (a block per skill) and the clock -- TIME = lvtime / MAX_FPS seconds, the frame rate
the program asks the window for, so it is the wall-clock time on a machine that keeps up with the cap -- then the
baked frame (menu.level_done_stream), then each slot's records for its digit (menu.level_done_digit_records, chosen by
a `hex.switch` on the slot). Only LEVEL COMPLETE's frames run it: its divisions cost the world frames nothing.
"""
from __future__ import annotations

from typing import List, Tuple

from doomfj import gamedata as gd
from doomfj import screenwire as SW
from doomfj.menu import count_slots

PERSIST = ("st_kill", "st_item", "st_secn", "st_secm")
COUNT_NIBBLES = 2                       # st_kill / st_item: p_killcount / p_itemcount, 8 bits
DIGIT_SLOTS = 13                        # menu.stats_digits: kills 4, items 4, secrets 1, time 4 (two-digit counts)
assert DIGIT_SLOTS == count_slots(2)
TIME_NIBBLES = 5                        # lvtime's (restartcode.LVTIME_NIBBLES); the seconds and minutes fit it too


def count_digits(w) -> int:
    """M8 F1.1 (docs/f1-big-map-widths.md 3): LEVEL COMPLETE's digits per count -- 2, or 3 when the map's monster
    slots or any skill's totals pass 99 (E1M2 129 monsters, E1M5 189, E1M9 135). ONE rule: the program's layout and
    digit split and the oracle's picture (menu, through the slot count) all follow it"""
    big = max([len(w.mon_things)] + [v for sk in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD) for v in level_totals(w, sk)])
    return 2 if big <= 99 else 3


def count_nibbles(w) -> int:
    """M8 C2 (docs/c2-slot-ids.md): st_kill's and st_item's width -- the schema's p_killcount (world.count_bits): 2,
    or 3 on a map whose monsters or pickups pass a byte (E1M6 291, E1M7 281 monsters)"""
    from doomfj.monstercode import cell_nibbles
    nib = cell_nibbles(w.schema, "p_killcount")
    assert nib in (2, 3) and nib == cell_nibbles(w.schema, "p_itemcount"), nib
    return nib


def secret_nibbles(w) -> int:
    """`st_secm`'s width: a nibble a secret sector (one at least: the schema's `max(1, nsecret)`)"""
    return max(1, len(w.secret_sectors))


def decls(w) -> List[str]:
    """the four cells at the level start (0), and the secret check's and LEVEL COMPLETE's scratch and constants"""
    from doomfj.restartcode import LVTIME_NIBBLES
    from doomfj.wall_renderer import MAX_FPS
    assert LVTIME_NIBBLES == TIME_NIBBLES, (LVTIME_NIBBLES, TIME_NIBBLES)
    assert 0 < MAX_FPS < 256, "TIME divides lvtime by the frame-rate cap: %r" % MAX_FPS
    cn = count_nibbles(w)                                                       # M8 C2: 3 past a byte
    return [f"st_kill: hex.vec {cn}, 0", f"st_item: hex.vec {cn}, 0", "st_secn: hex.vec 1, 0",
            f"st_secm: hex.vec {secret_nibbles(w)}, 0",
            # the secret check's scratch
            "sc_bx: hex.vec 4", f"sc_sec: hex.vec {w.sec_nibbles}", "sc_on: hex.vec 1", "sc_ret: hex.vec w/4", "sc_fret: hex.vec w/4",
            # LEVEL COMPLETE's: the slots, the clock's quotients and remainders, the decimal split, its constants
            f"st_dig: hex.vec {count_slots(count_digits(w))}",
            f"lvd_s: hex.vec {TIME_NIBBLES}", "lvd_r: hex.vec 2", f"lvd_m: hex.vec {TIME_NIBBLES}", "lvd_ss: hex.vec 2",
            f"lvd_t: hex.vec {TIME_NIBBLES}", "lvd_v: hex.vec 2", "lvd_q: hex.vec 2", "lvd_o: hex.vec 1",
            *(["lvd_v3: hex.vec 3", "lvd_q3: hex.vec 3"] if cn == 3 else []),          # M8 C2: a 3-nibble count
            "lvd_ret: hex.vec w/4",
            f"lvd_cf: hex.vec 2, {MAX_FPS}", "lvd_c60: hex.vec 2, 60", "lvd_c10: hex.vec 1, 10"]


def level_start_lines(w) -> List[str]:
    """the level start's counters (restart_common's: no skill changes them) -- for compose_restart(p10_common=)"""
    cn = count_nibbles(w)
    return [f"    hex.zero {cn}, st_kill", f"    hex.zero {cn}, st_item",
            "    hex.zero 1, st_secn", f"    hex.zero {secret_nibbles(w)}, st_secm"]


def kill_lines(cn: int = COUNT_NIBBLES) -> List[str]:
    """damagecode's `dm_kill` (P_KillMobj): one more kill. M8 C2: `cn` = count_nibbles"""
    return ["    hex.inc %d, st_kill" % cn]


def counts_item(kind: int, dropped: bool = False) -> bool:
    """is a pickup of `kind` COUNTITEM (P_TouchSpecialThing's itemcount)? No drop is"""
    counted = bool(gd.THING_TYPES[kind].flags & gd.MF_COUNTITEM)
    assert not (counted and dropped), "a dropped COUNTITEM (%d): the drops are clips and weapons" % kind
    return counted


def item_lines(cn: int = COUNT_NIBBLES) -> List[str]:
    """a COUNTITEM give routine's taken exit: one more item. M8 C2: `cn` = count_nibbles"""
    return ["    hex.inc %d, st_item" % cn]


def check_world(w) -> None:
    """the emit-time facts the counters lean on: every monster counts as a kill, every count fits two decimal digits
    (LEVEL COMPLETE's slots) and its cell, and the secrets fit one slot"""
    # M8 C8: the lost soul (MT_SKULL) is not COUNTKILL -- damagecode's dm_kill skips the count for it (`dm_sk`)
    assert all(gd.THING_TYPES[t.type].flags & gd.MF_COUNTKILL or t.type == gd.MOBJINFO["MT_SKULL"].doomednum
               for t in w.mon_things), (
        "kill_lines counts every monster death: a non-COUNTKILL monster type needs a test at dm_kill")
    # M8 F1.1: 2 or 3 decimal digits a count (count_digits), in 8-bit cells (p_killcount / p_itemcount) -- M8 C2:
    # 12-bit cells past a byte (count_nibbles); three decimal digits hold 999
    cmax = 16 ** count_nibbles(w) - 1
    assert len(w.mon_things) <= min(cmax, 999), "the kills are a %d-bit cell: %d monster slots" % (
        4 * count_nibbles(w), len(w.mon_things))
    nitems = sum(1 for t in w.pickup_things if counts_item(t.type))
    assert nitems <= min(cmax, 999), "the items are a %d-bit cell: %d COUNTITEM pickups" % (4 * count_nibbles(w), nitems)
    assert len(w.secret_sectors) <= 9, "the secrets are one decimal digit: %d" % len(w.secret_sectors)


# ---- the oracle's side -----------------------------------------------------------------------------------------------
def level_totals(w, skill: int) -> Tuple[int, int]:
    """(totalkills, totalitems) at `skill` -- P_SpawnMapThing's counts of the COUNTKILL and COUNTITEM things the skill
    spawns"""
    bit = gd.skill_bit(skill)
    kills = sum(1 for t in w.mon_things if t.flags & bit and gd.THING_TYPES[t.type].flags & gd.MF_COUNTKILL)
    items = sum(1 for t in w.pickup_things if t.flags & bit and counts_item(t.type))
    return kills, items


def stats_of(w) -> tuple:
    """the oracle's LEVEL COMPLETE numbers for World `w` now, menu.stats_digits' arguments: (kills, total kills,
    items, total items, secrets, seconds) -- seconds = leveltime // MAX_FPS"""
    from doomfj.wall_renderer import MAX_FPS
    ws = w.ws
    tk, ti = level_totals(w, ws.skill)
    return ws.p_killcount, tk, ws.p_itemcount, ti, ws.p_secretcount, ws.leveltime // MAX_FPS


# ---- the secrets ------------------------------------------------------------------------------------------------------
def sector_box(w, sec: int) -> Tuple[int, int, int, int]:
    """(x0, x1, y0, y1): the bounds of the vertices of every line sector `sec` touches -- a point in the sector lies
    inside them"""
    V = w.cmap.vertexes
    xs, ys = [], []
    for ld in w.lds:
        ss = {w.sds[ld.front].sector} | ({w.sds[ld.back].sector} if 0 <= ld.back < len(w.sds) else set())
        if sec in ss:
            xs += [V[ld.v1][0], V[ld.v2][0]]
            ys += [V[ld.v1][1], V[ld.v2][1]]
    return min(xs), max(xs), min(ys), max(ys)


def secret_lines(w, cell_root: str) -> List[str]:
    """`sc_go` (stl.fcall sc_go, sc_ret): combat._special_sector's secrets at the tic-start position (see the module
    docstring). `cell_root`: the player's collision cell routine, as nukage's. Jumps over itself."""
    from doomfj.reference_model import PLAYER_RADIUS
    secrets = list(w.secret_sectors)
    out = ["// P10 (doomfj.statcode): the secrets -- P_PlayerInSpecialSector's special 9, every alive tic", ";sc_end",
           "sc_go:"]
    for k, sec in enumerate(secrets):
        x0, x1, y0, y1 = sector_box(w, sec)
        nxt = f"sc_b{k + 1}"
        out.append(f"    hex.if1 1, st_secm + {k}*dw, {nxt}")                # entered already
        for j, (reg, val, ge) in enumerate((("viewx", x0, True), ("viewx", x1, False),
                                            ("viewy", y0, True), ("viewy", y1, False))):
            tag = f"sc_t{k}_{j}"
            out.append(f"    hex.set 4, sc_bx, {val & 0xFFFF:#x}")
            if ge:                                     # out when the whole-unit position < the bound
                out.append(f"    hex.scmp 4, {reg} + 4*dw, sc_bx, {nxt}, {tag}, {tag}")
            else:                                      # out when it is > the bound
                out.append(f"    hex.scmp 4, {reg} + 4*dw, sc_bx, {tag}, {tag}, {nxt}")
            out.append(f"  {tag}:")
        out += ["    ;sc_walk", f"  {nxt}:"]
    out += ["    ;sc_out",
            "  sc_walk:",                                                    # the model's player_sector
            "    hex.zero 10, ptx", "    hex.mov 4, ptx, viewx + 4*dw", "    hex.sign_extend 10, 4, ptx",
            "    hex.zero 10, pty", "    hex.mov 4, pty, viewy + 4*dw", "    hex.sign_extend 10, 4, pty",
            "    stl.fcall ptloc_walk, ptloc_ret",
            "    lfsec.lookup sc_sec, ptss"]
    nib = w.sec_nibbles                                                     # M8 L1: sc_sec's width
    for k, sec in enumerate(secrets):
        assert 0 <= sec < 16 ** nib, (sec, nib)
        out += [f"    hex.if1 1, st_secm + {k}*dw, sc_w{k}",
                f"    hex.xor_by {nib}, sc_sec, {sec}",                       # sc_sec == sec: zero
                f"    hex.if0 {nib}, sc_sec, sc_f{k}",
                f"    hex.xor_by {nib}, sc_sec, {sec}",
                f"  sc_w{k}:"]
    out += ["    ;sc_out"]
    for k in range(len(secrets)):
        out += [f"  sc_f{k}:",
                "    stl.fcall sc_floor, sc_fret",
                "    hex.if0 1, sc_on, sc_out",
                f"    hex.set 1, st_secm + {k}*dw, 1",
                "    hex.inc 1, st_secn",
                "    ;sc_out"]
    out += ["  sc_floor:",                             # "Falling, not all the way down yet?" -- nukage's test
            "    hex.zero 1, sc_on",
            "    stl.fcall ms_seed_leaf, ms_seed_ret",                          # the sector's floor now (cp_seedf)
            "    hex.mov 8, cpx, viewx", "    hex.mov 8, cpy, viewy",
            "    hex.set 8, cprad, %d" % PLAYER_RADIUS,
            "    sim.check_cells %s" % cell_root,                               # the box's floorz (cp_floor)
            # equality only, as nukage's (lootcode, issue #123 R5a): the two arms that are not "equal" are one label
            "    hex.cmp 8, cp_floor, cp_seedf, sc_fl_out, sc_fl_on, sc_fl_out",
            "  sc_fl_on:", "    hex.set 1, sc_on, 1",
            "  sc_fl_out:", "    stl.fret sc_fret",
            "  sc_out:", "    stl.fret sc_ret",
            "sc_end:"]
    return out


def secret_call_lines() -> List[str]:
    """lootcode's `pre` (alive): the secrets' check"""
    return ["stl.fcall sc_go, sc_ret"]


# ---- LEVEL COMPLETE ---------------------------------------------------------------------------------------------------
def _split_lines(src: str, slot: int, blank: bool, nd: int = 2, cn: int = 2) -> List[str]:
    """st_dig[slot], st_dig[slot + 1] = the two decimal digits of the 2-nibble `src` (<= 99) through `lvd_dec` (ONE
    shared division); the tens a DIGIT_BLANK when 0 and `blank`. M8 F1.1 (`nd` 3, a count <= 255): three slots --
    the ones first, then the quotient (<= 25) divided again for the hundreds and the tens; with `blank` the hundreds
    a blank when 0 and the tens too when both are (menu.count_codes). M8 C2 (`cn` 3, a 3-nibble count <= 999): the
    first division is a 3-nibble one, inline (lvd_v3 / lvd_q3: LEVEL COMPLETE's frames only), its quotient <= 99"""
    from doomfj.menu import DIGIT_BLANK
    assert cn == 2 or nd == 3, (cn, nd)
    if nd == 3:
        first = ([f"    hex.mov 2, lvd_v, {src}", "    stl.fcall lvd_dec, lvd_ret"] if cn == 2 else
                 [f"    hex.mov 3, lvd_v3, {src}", "    hex.div 3, 1, lvd_q3, lvd_o, lvd_v3, lvd_c10, lvd_div0",
                  "    hex.mov 2, lvd_q, lvd_q3"])
        out = first + [f"    hex.mov 1, st_dig + {slot + 2}*dw, lvd_o",
               "    hex.mov 2, lvd_v, lvd_q", "    stl.fcall lvd_dec, lvd_ret",
               f"    hex.mov 1, st_dig + {slot}*dw, lvd_q", f"    hex.mov 1, st_dig + {slot + 1}*dw, lvd_o"]
        if blank:
            out += [f"    hex.if0 2, lvd_q, lvd_b{slot}", f"    ;lvd_nb{slot}",
                    f"  lvd_b{slot}:", f"    hex.set 1, st_dig + {slot}*dw, {DIGIT_BLANK}",
                    f"    hex.if0 1, lvd_o, lvd_bt{slot}", f"    ;lvd_nb{slot}",
                    f"  lvd_bt{slot}:", f"    hex.set 1, st_dig + {slot + 1}*dw, {DIGIT_BLANK}",
                    f"  lvd_nb{slot}:"]
        return out
    assert nd == 2, nd
    out = [f"    hex.mov 2, lvd_v, {src}", "    stl.fcall lvd_dec, lvd_ret",
           f"    hex.mov 1, st_dig + {slot}*dw, lvd_q", f"    hex.mov 1, st_dig + {slot + 1}*dw, lvd_o"]
    if blank:
        out += [f"    hex.if0 2, lvd_q, lvd_b{slot}", f"    ;lvd_nb{slot}",
                f"  lvd_b{slot}:", f"    hex.set 1, st_dig + {slot}*dw, {DIGIT_BLANK}",
                f"  lvd_nb{slot}:"]
    return out


def _digit_set_lines(slot: int, value: int, blank: bool, nd: int = 2) -> List[str]:
    """a constant's `nd` digits into st_dig[slot ..] (a skill's totals) -- menu.count_codes, the oracle's own rule
    (at 2 digits the text of P10's tens-then-ones pair)"""
    from doomfj.menu import count_codes
    assert blank, "a skill's totals are blanked as the oracle's"
    return [f"    hex.set 1, st_dig + {slot + k}*dw, {c}" for k, c in enumerate(count_codes(value, nd))]


def digit_lines(w, skills) -> List[str]:
    """`st_dig` from the cells: menu.stats_digits(kills, total kills, items, total items, secrets, seconds) in fj --
    tests/fj/test_level_done_fj.py runs exactly these lines. `skills`: wall_renderer.SKILLS (g_skill's indices). The
    routine `lvd_dec` and the unreachable `lvd_div0` (every divisor is a non-zero constant) are `routine_lines`'"""
    from doomfj.menu import TIME_CAP
    from doomfj.restartcode import skill_dispatch
    check_world(w)
    nd = count_digits(w)                                                         # M8 F1.1: 2 or 3 a count
    out = ["// P10 (doomfj.statcode): LEVEL COMPLETE's digit slots"]
    cn = count_nibbles(w)                                                        # M8 C2: 2 or 3 nibbles a counter
    out += _split_lines("st_kill", 0, True, nd, cn)                              # kills
    out += skill_dispatch("lvt", "g_skill", len(skills))                         # the skill's totals
    for k, sk in enumerate(skills):
        tk, ti = level_totals(w, sk)
        out += [f"lvt{k}:", *_digit_set_lines(nd, tk, True, nd), *_digit_set_lines(3 * nd, ti, True, nd),
                ";lvt_done"]
    out += ["lvt_done:"]
    out += _split_lines("st_item", 2 * nd, True, nd, cn)                         # items
    out += [f"    hex.mov 1, st_dig + {4 * nd}*dw, st_secn"]                      # secrets
    # the clock: seconds = lvtime / MAX_FPS, then minutes and seconds, capped at 99:59 (menu.TIME_CAP)
    mm_cap, ss_cap = divmod(TIME_CAP, 60)
    out += [f"    hex.div {TIME_NIBBLES}, 2, lvd_s, lvd_r, lvtime, lvd_cf, lvd_div0",
            f"    hex.div {TIME_NIBBLES}, 2, lvd_m, lvd_ss, lvd_s, lvd_c60, lvd_div0",
            f"    hex.set {TIME_NIBBLES}, lvd_t, {mm_cap}",
            f"    hex.cmp {TIME_NIBBLES}, lvd_m, lvd_t, lvd_tok, lvd_tok, lvd_tcap",
            "  lvd_tcap:", f"    hex.set {TIME_NIBBLES}, lvd_m, {mm_cap}", f"    hex.set 2, lvd_ss, {ss_cap}",
            "  lvd_tok:"]
    out += _split_lines("lvd_m", 4 * nd + 1, True)                               # minutes: no leading zero
    out += _split_lines("lvd_ss", 4 * nd + 3, False)                             # seconds: a leading zero
    return out


def routine_lines() -> List[str]:
    """`lvd_dec` (stl.fcall lvd_dec, lvd_ret): lvd_q, lvd_o = divmod(lvd_v, 10); and `lvd_div0`, which no constant
    divisor reaches (a halt under its own label, as P9's `mn_exit`). Fcall'd / unreachable only: the caller places
    them where nothing falls in"""
    return ["lvd_dec:",
            "    hex.div 2, 1, lvd_q, lvd_o, lvd_v, lvd_c10, lvd_div0",
            "    stl.fret lvd_ret",
            "lvd_div0: stl.loop"]


def frame_lines(width: int, height: int, colours, w, label: str = "menu_level_done") -> List[str]:
    """LEVEL COMPLETE's frame after `digit_lines`: the baked frame (no END_CMD: the menu's shared tail ends it), then each
    slot's records for its digit -- a `hex.switch` on the slot, a block per digit, nothing for a blank"""
    from doomfj.menu import DIGIT_BLANK, level_done_digit_records, level_done_layout, level_done_stream
    nsec = len(w.secret_sectors)
    nd = count_digits(w)                                                         # M8 F1.1
    nslot = count_slots(nd)
    data = SW.strip_frame_tail(level_done_stream(width, height, colours, nsec, nd))
    _lines, _sel, _rows, slots = level_done_layout(width, height, nsec, nd)
    assert len(slots) == nslot, len(slots)
    assert DIGIT_BLANK >= 10, "a blank slot jumps past the ten digits' blocks"
    out = ["// P10 (doomfj.statcode): the baked LEVEL COMPLETE frame (%d bytes), then the digit slots"
           % len(data), f"{label}:"]
    out += ["    stl.output_char %d" % b for b in data]
    for i in range(nslot):
        p = f"lvd{i}"
        targets = [f"{p}_{d}" for d in range(10)] + [f"{p}_x"] * 6
        out.append(f"    hex.switch st_dig + {i}*dw, " + ", ".join(targets))
        for d in range(10):
            out.append(f"  {p}_{d}:")
            out += ["    stl.output_char %d" % b
                    for b in level_done_digit_records(width, height, colours, nsec, i, d, nd)]
            out.append(f"    ;{p}_x")
        out.append(f"  {p}_x:")
    if getattr(w.layout, "secexit", 0):             # M8 C9: the secret exit used -> SECRET EXIT under the title
        from doomfj.menu import level_done_secret_records
        out += ["    hex.if0 1, lvsec, lvd_sx"]
        out += ["    stl.output_char %d" % b for b in level_done_secret_records(width, height, colours, nsec, nd)]
        out += ["  lvd_sx:"]
    return out
