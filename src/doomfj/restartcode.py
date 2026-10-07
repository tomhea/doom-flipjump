"""M7 P7 -- THE RESTART (docs/gp-p67-interface.md section 4.4, package D): the game's own cells, the restart block's
ONE definition shared by NEW GAME and the restart on use after death, and the level-start lines of the cells P6 / P7
add.

THE CELLS (section 4.5; declared in `wall_renderer.MENU_STATE_DECLS`, so the standalone restore set re-attaches them
at these widths through `STANDALONE_SCRATCH_DECLS`, as it does `lvdone` / `pusedn`):

    g_skill   1 nibble   the SKILLS index (0 easy, 1 medium, 2 hard) the restart restores to; NEW GAME sets it from
                         `menu_sel` (which cannot serve: the skill screen's up / down move it even when esc backs out).
                         Boots at the boot skill's index. RESTART_KEEP's `skill`: the restart never writes it.
    g_rs      1 nibble   the model's g_restart: the death think sets it on use (package B); the next world frame's
                         start runs the restart, which zeroes it.
    lvtime    4 nibbles  the model's leveltime (16 bits, wraps): +1 at the end of every non-frozen world tic
                         (`lvtime_tic_lines`, inside the frozen-level guard); nukage reads it (package B).

All three PERSIST across the M1 reset (`build.GAME_PERSIST` = `PERSIST`).

THE ONE DEFINITION. `wall_renderer.restart_lines` returns (the shared routine `restart_common`, [each skill's
lines]). `routine_lines` places them as fcall'd routines -- `restart_common` and `rs_skill<k>`, each ending in
`stl.fret rs_ret` -- and `call_lines` is the ONE call sequence: `restart_common`, then a dispatch on `g_skill` into
`rs_skill<k>`. NEW GAME (`wall_renderer.menu_state_lines`) sets `g_skill` from `menu_sel` and runs `call_lines`; the
restart on use runs the same `call_lines` at the world frame's start (`tic_lines`: `if g_rs`), so the two cannot
write different level starts. Model: `World.tic` -- `if g_restart: _restart`, then the tic.

NEVER THE DEVICE SHADOWS: `pal_cur` (the palette the device shows) and `hud_s` / `hud_full` (the bar the device
shows, and the redraw-all flag). A death restart goes world frame -> world frame with no menu frame between (NEW GAME
is safe only because a menu frame forces palette 0 and redraws the bar): zeroed while the device shows red, the
palette would never be re-sent. `DEVICE_SHADOWS` names them; tests/fj/test_restart_fj.py holds both halves.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

# the cells this module owns, and their level-start values (`g_skill` is not restarted: RESTART_KEEP's `skill`)
PERSIST = ("lvtime", "g_rs", "g_skill")
LVTIME_NIBBLES = 4
# the persisted cells the restart must NOT write: what the device shows (docs/gp-p67-interface.md 4.4)
DEVICE_SHADOWS = ("pal_cur", "hud_s", "hud_full")
# the player modes with a death that restarts (P7; the fallback "loot" mode of section 2 has none)
MORTAL_PLAYER_MODES = ("full", "final")    # M7 P8a: "final" is "full" and more


def mortal(player_mode: str) -> bool:
    """M7 P7: does `player_mode` die and restart (the dead branch, the death think, the restart on use)?"""
    return player_mode in MORTAL_PLAYER_MODES


def game_decls(boot_index: int) -> List[str]:
    """the three cells, `g_skill` at the boot skill's SKILLS index (the image boots at that skill's level start)"""
    return [f"g_skill: hex.vec 1, {boot_index}", "g_rs: hex.vec 1, 0", f"lvtime: hex.vec {LVTIME_NIBBLES}, 0"]


def restart_lines() -> List[str]:
    """this module's cells at the level start (restart_common's: no skill changes them). `g_skill` is kept."""
    return [f"    hex.zero {LVTIME_NIBBLES}, lvtime", "    hex.zero 1, g_rs"]


def lvtime_tic_lines() -> List[str]:
    """`leveltime` +1 at the end of a non-frozen world tic (World.tic) -- the caller places it inside the lvdone guard"""
    return [f"hex.inc {LVTIME_NIBBLES}, lvtime"]


def skill_dispatch(prefix: str, cell: str, nskills: int) -> List[str]:
    """jump to `{prefix}k` for the skill index k in the nibble `cell`: an `if0`, then one `if_flags` on bit 1 -- three
    skills by its shape, so it refuses any other number rather than send a fourth to the third's block"""
    assert nskills == 3, "the skill dispatch is written for three skills, not %d" % nskills
    return [f"hex.if0 1, {cell}, {prefix}0", f"hex.if_flags {cell}, 1<<1, {prefix}2, {prefix}1"]


def routine_lines(restart) -> List[str]:
    """the restart block as fcall'd routines: `restart_common` (already a routine) and `rs_skill<k>` per skill, each
    returning through `rs_ret`. Fcall'd only -- the caller places them where nothing falls in."""
    common, skills = restart
    out = list(common)
    for k, block in enumerate(skills):
        out += [f"rs_skill{k}:", *block, "    stl.fret rs_ret"]
    return out


def call_lines(prefix: str, nskills: int) -> List[str]:
    """THE ONE RESTART SEQUENCE: every persisted cell back to skill `g_skill`'s level start -- the shared routine,
    then that skill's. `prefix` keys the dispatch's labels (one call site each: NEW GAME's, the restart on use's)."""
    out = ["stl.fcall restart_common, rs_ret", *skill_dispatch(prefix, "g_skill", nskills)]
    for k in range(nskills):
        out += [f"{prefix}{k}:", f"stl.fcall rs_skill{k}, rs_ret"] + ([f";{prefix}_done"] if k < nskills - 1 else [])
    return out + [f"{prefix}_done:"]


def new_game_lines(nskills: int) -> List[str]:
    """NEW GAME at the highlighted skill: `g_skill` = `menu_sel`, then the restart (the model's `new_game(skill)`)"""
    return ["hex.mov 1, g_skill, menu_sel", *call_lines("mn_r", nskills)]


def tic_lines(nskills: int) -> List[str]:
    """the restart on use after death, at the world frame's START (before the frozen-level guard and the door tic):
    `if g_rs: restart(g_skill)` -- the model's `World.tic`. The restart zeroes `g_rs`."""
    return ["hex.if0 1, g_rs, rs_live", *call_lines("rs_d", nskills), "rs_live:"]


# ---- the P6 cells' level start (packages B and C declare them; the restart is this package's) -------------------
# (label, nibbles a cell, the model's value per cell) -- docs/gp-p67-interface.md section 4.5's units. THE ONE
# DEFINITION of the units is package A's MonsterPhase.loot_state / barrel_state / game_state; this transcribes the
# table, and tests/host/test_restart_coverage.py holds it equal to A's once those exist (INTEGRATION HOOK).
def p6_cell_values(w, ws=None) -> Dict[str, list]:
    """the P6 / P7 cells' values for World `w`'s state `ws` (default its own; the restart reads a level start), each a
    list of cell values in the cells' units"""
    from doomfj import gamedata as gd
    ws = w.ws if ws is None else ws
    drops = [m for m in range(w.layout.nmon) if w.dropper[m] is not None]
    mdrop = [ws.mon_drop[m] for m in drops]
    nb = w.layout.nbarrel
    return {"p_bc": [ws.p_bonuscount], "p_str": [ws.p_strength], "p_bp": [ws.p_backpack],
            "am_misl": [ws.p_ammo[gd.AM_MISL]], "am_cell": [ws.p_ammo[gd.AM_CELL]],
            "mdrop": mdrop, "dr_live": [sum(1 for v in mdrop if v == 1)],
            "bar_st": [ws.bar_state[b] for b in range(nb)], "bar_ti": [ws.bar_tics[b] for b in range(nb)],
            "bar_hp": [ws.bar_health[b] & 0xFF for b in range(nb)], "rng_wd": [ws.rng_world],
            "lvtime": [ws.leveltime & 0xFFFF], "g_rs": [ws.g_restart]}


P6_NIBBLES = {"p_bc": 2, "p_str": 4, "p_bp": 1, "am_misl": 3, "am_cell": 3, "mdrop": 1, "dr_live": 2,
              "bar_st": 2, "bar_ti": 1, "bar_hp": 2, "rng_wd": 2, "lvtime": LVTIME_NIBBLES, "g_rs": 1}
# the groups, by the package that declares them (build.LOOT_PERSIST / BARREL_PERSIST once B and C land)
P6_LOOT = ("p_bc", "p_str", "p_bp", "am_misl", "am_cell", "mdrop", "dr_live")
P6_BARREL = ("bar_st", "bar_ti", "bar_hp", "rng_wd")


def level_start_lines(world, skills: Sequence[int], names: Sequence[str]):
    """-> (common lines, [each skill's lines]): `names` (of P6_NIBBLES) at each skill's level start
    (`World.level_start`) -- a cell whose value is the same on every skill goes into the common routine, the rest
    into the skills' blocks. A zero value is a `hex.zero`, else a `hex.set` per cell."""
    per = [p6_cell_values(world, world.level_start(sk)) for sk in skills]

    def lines(name, vals):
        nib = P6_NIBBLES[name]
        if not any(vals):
            return [f"    hex.zero {nib * len(vals)}, {name}"]
        return [f"    hex.set {nib}, {name} + {nib * i}*dw, {v & (16 ** nib - 1)}" for i, v in enumerate(vals)]

    common, skill_out = [], [[] for _ in skills]
    for name in names:
        vals = [p[name] for p in per]
        if all(v == vals[0] for v in vals):
            common += lines(name, vals[0])
        else:
            for k, v in enumerate(vals):
                skill_out[k] += lines(name, v)
    return common, skill_out
