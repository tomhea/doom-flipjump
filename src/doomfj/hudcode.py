"""M7 P4.0 -- the fj side of the game screen's bar and weapon overlay (docs/gp-combat.md section 2). Every byte comes
from `doomfj.hud`, the generator the oracle composes with, so the two mirrors cannot drift.

THE FRAME (decisions C3/C4): after the view's 160 column records, before the frame's closing 0xFF --
  1. the WEAPON: one record per covered column, `[x][0xFC][y0]` (keep the world above it), then per run of one texel
     `[y_end][colour]`, with `[0xFC][y]` over a transparent gap, and `[0xFF]`. Every colour is a constant: E1M1's
     sectors all light a psprite with one colormap row (asserted at emit time), so nothing is looked up at runtime;
  2. the BAR: rows [VIEW_ROWS, H) of a column, `[x][0xFC][VIEW_ROWS][pairs][0xFF]`, ONLY for columns that changed.
     Each dynamic slot (`hud.bar_slots`) has a value cell in `hud_v` and a shadow in `hud_s` (what the screen shows);
     a slot whose value differs from its shadow is redrawn and the shadow copied. `hud_full` -- set by every menu
     frame and at boot -- redraws the static columns and invalidates every shadow (to SHADOW_STALE, which no variant
     uses), so the whole bar is redrawn once after the menu covered it.
A menu frame jumps to `frame_end` and draws neither.

THE VALUE CELLS (`hud_v`, one nibble per slot, in `hud.bar_slots` order): a digit slot holds 0..9 or BLANK; an arms or
card slot 0 / 1. P4.0's values are the level start's and never change; the rungs that change health, armor, ammo and
the owned weapons write these cells (a value -> digits table).
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from doomfj import hud

BLANK = 10                     # a digit slot's "no digit" (a leading zero, or no ammo)
SHADOW_STALE = 15              # a shadow value no variant uses: forces a redraw


def _variant_code(v) -> int:
    """a slot variant's nibble in `hud_v`"""
    if v is None:
        return BLANK
    if isinstance(v, bool):
        return int(v)
    return int(v)


def slot_codes(values: dict) -> List[int]:
    """`hud_v`'s nibbles for a `hud.slot_values` dict, in `hud.bar_slots` order"""
    return [_variant_code(values[name]) for name, _x0, _w, _v in hud.bar_slots()]


def _bar_record(x: int, column: Sequence[int], view_rows: int) -> List[str]:
    """one bar column: keep the view, then the bar's rows as constant (y2, colour) pairs"""
    out = [f"stl.output_char {x}", "stl.output_char 0xFC", f"stl.output_char {view_rows}"]
    y = 0
    while y < len(column):
        c = column[y]
        e = y + 1
        while e < len(column) and column[e] == c:
            e += 1
        out += [f"stl.output_char {view_rows + e}", f"stl.output_char {c}"]
        y = e
    return out + ["stl.output_char 0xFF"]


def weapon_record_lines(overlay: Dict[int, list], colormap_row: Sequence[int]) -> List[str]:
    """the overlay as constant records: `hud.psprite_columns` runs, coloured through ONE colormap row"""
    out = []
    for x in sorted(overlay):
        runs = overlay[x]
        out += [f"stl.output_char {x}", "stl.output_char 0xFC", f"stl.output_char {runs[0][0]}"]
        cursor = runs[0][0]
        for y0, y1, texel in runs:
            if y0 > cursor:
                out += ["stl.output_char 0xFC", f"stl.output_char {y0}"]
            out += [f"stl.output_char {y1}", f"stl.output_char {colormap_row[texel]}"]
            cursor = y1
        out.append("stl.output_char 0xFF")
    return out


def _frame_dispatch(prefix: str, cell: str, blocks: List[List[str]], end: str) -> List[str]:
    """draw blocks[v] for the nibble v in `cell`, then jump to `end`"""
    assert len(blocks) <= 16, len(blocks)
    out = []
    for v, block in enumerate(blocks):
        out += [f"hex.if_flags {cell}, 1<<{v}, {prefix}_n{v}, {prefix}_y{v}", f"{prefix}_y{v}:", *block,
                f";{end}", f"{prefix}_n{v}:"]
    return out + [f";{end}"]


def hud_decls(level_start: Sequence[int]) -> List[str]:
    n = len(hud.bar_slots())
    assert len(level_start) == n
    return [f"hud_v: hex.vec {n}, {sum(v << (4 * i) for i, v in enumerate(level_start))}",
            f"hud_s: hex.vec {n}, {sum(SHADOW_STALE << (4 * i) for i in range(n))}",
            "hud_full: hex.vec 1, 1"]


def hud_restart_lines(level_start: Sequence[int]) -> List[str]:
    """the level start's values (NEW GAME / the restart block); the menu frame before it already set `hud_full`"""
    return [f"hex.set {len(level_start)}, hud_v, {sum(v << (4 * i) for i, v in enumerate(level_start))}"]


# a slot whose value already lives in a game cell reads THAT cell, not a copy in `hud_v` (the blue card is the doors'
# `pcard`, P2a.1): a copy would be one more thing to keep in step
VALUE_CELLS = {"card": "pcard"}


def hud_tail_lines(colours: Dict[str, int], overlay: Dict[int, list], colormap_row: Sequence[int],
                   view_rows: int = hud.VIEW_ROWS, value_cells: Dict[str, str] = VALUE_CELLS) -> List[str]:
    """the world frame's tail before `frame_end`: the weapon, then the bar's changed columns"""
    slots = hud.bar_slots()
    owned_cols = {x for _n, x0, w, _v in slots for x in range(x0, x0 + w)}
    out = ["// M7 P4.0 (doomfj.hudcode): the weapon overlay, then the bar's changed columns"]
    if isinstance(overlay, dict):
        out += weapon_record_lines(overlay, colormap_row)
    else:
        # M7 P4.1: one overlay per weapon frame, chosen by `wp_frm`; then the flash's, by `fl_frm` (0 = none) -- the
        # psprites in DOOM's order, the flash's records after the weapon's (the device draws a later record over)
        weapons, flashes = overlay
        out += _frame_dispatch("hwf", "wp_frm", [weapon_record_lines(o, colormap_row) for o in weapons], "hwf_end")
        out += ["hwf_end:"]
        out += _frame_dispatch("hff", "fl_frm", [[]] + [weapon_record_lines(o, colormap_row) for o in flashes],
                               "hff_end")
        out += ["hff_end:"]
    # the full redraw: the static columns, and every shadow stale
    out += ["hex.if0 1, hud_full, hud_slots"]
    for x in range(hud.SCREEN_W):
        if x not in owned_cols:
            out += _bar_record(x, hud.bar_column(colours, x), view_rows)
    out += [f"hex.set {len(slots)}, hud_s, {sum(SHADOW_STALE << (4 * i) for i in range(len(slots)))}",
            "hex.zero 1, hud_full",
            "hud_slots:"]
    for i, (name, x0, w, variants) in enumerate(slots):
        v, s = value_cells.get(name, f"hud_v + {i}*dw"), f"hud_s + {i}*dw"
        out += [f"hex.cmp 1, {v}, {s}, hud_d{i}, hud_n{i}, hud_d{i}",
                f"hud_d{i}:"]
        for k, var in enumerate(variants):
            code = _variant_code(var)
            out.append(f"hex.if_flags {v}, 1<<{code}, hud_d{i}_{k + 1}, hud_d{i}_v{k}")
            out.append(f"hud_d{i}_v{k}:")
            for x in range(x0, x0 + w):
                out += _bar_record(x, hud.bar_column(colours, x, var), view_rows)
            out += [f";hud_c{i}", f"hud_d{i}_{k + 1}:"]
        out += [f";hud_c{i}",                                 # a value no variant uses: nothing to draw
                f"hud_c{i}:",
                f"hex.mov 1, {s}, {v}",
                f"hud_n{i}:"]
    return out


# the level start's bar (the model's `level_start`: 100 health, no armor, the pistol up with 50 bullets, the fist and
# the pistol owned -- ARMS shows 2 lit). The card slot is `pcard`'s, so its value here is never read.
LEVEL_START = dict(ammo=50, health=100, armor=0, owned=(True, False, False), blue=False)
READY_WEAPON = "PISGA0"        # P4.0 draws the ready pistol; P4.1's weapon state machine picks the frame


def game_hud_parts(rm, asset_wad, sprite_wad, sectors) -> dict:
    """everything the game tier's emitter splices in: `decls` (state cells), `restart` (NEW GAME's values), `menu` (the
    line every menu frame runs: the bar is redrawn after it) and `tail` (the world frame's weapon and bar, before
    `frame_end`). ONE colormap row lights the weapon on every sector of the map (asserted: a map with darker sectors
    needs the row chosen at runtime, which P4.0 does not emit)."""
    palette = bytes(b for rgb in asset_wad.playpal(0) for b in rgb)
    colours = hud.bar_colours(palette)
    rows = {hud.psprite_light_row(rm, s.light) for s in sectors}
    assert len(rows) == 1, ("the weapon is lit by %d colormap rows on this map (%s); P4.0 bakes one -- a darker map "
                            "needs the row selected per frame" % (len(rows), sorted(rows)))
    row = asset_wad.colormap()[rows.pop()]
    start = slot_codes(hud.slot_values(**LEVEL_START))
    # M7 P4.1: every weapon frame (`wp_frm` indexes weaponcode.overlay_frames) and every flash frame (`fl_frm` - 1)
    from doomfj import weaponcode as WC

    def cols(lump):
        return hud.psprite_columns(sprite_wad.get_data(lump), view_w=rm.cfg.VIEW_W, view_rows=rm.cfg.VIEW_H)
    overlay = ([cols(lump) for lump in WC.overlay_frames()], [cols(lump) for lump in WC.flash_frames()])
    return {"decls": hud_decls(start), "restart": hud_restart_lines(start), "menu": ["hex.set 1, hud_full, 1"],
            "tail": hud_tail_lines(colours, overlay, row, view_rows=rm.cfg.VIEW_H), "colours": colours,
            "overlay": overlay, "colormap_row": row}
