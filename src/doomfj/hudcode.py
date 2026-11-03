"""M7 P4.0 -- the fj side of the game screen's bar and weapon overlay (docs/gp-combat.md section 2). Every byte comes
from `doomfj.hud`, the generator the oracle composes with, so the two mirrors cannot drift.

THE FRAME (decisions C3/C4): after the view's 160 column records, before the frame's closing END_CMD (doomfj.screenwire
holds the tokens: KEEP 0xFE, END 0xFF) --
  1. the WEAPON: one record per covered column, `[x][KEEP][y0]` (keep the world above it), then per run of one texel
     `[y_end][colour]`, with `[KEEP][y]` over a transparent gap, and `[END]`. Every colour is a constant: E1M1's
     sectors all light a psprite with one colormap row, so nothing is looked up at runtime. M8 (E1M9's dark sector):
     a map of several rows bakes one weapon drawing per row, picked by the nibble the view's leaf sets
     (`weapon_row_lines`); the flashes are FF_FULLBRIGHT, drawn once at hud.FULLBRIGHT_ROW;
  2. the BAR: rows [VIEW_ROWS, H) of a column, `[x][KEEP][VIEW_ROWS][pairs][END]`, ONLY for columns that changed.
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

from typing import Dict, List, Optional, Sequence

from doomfj import hud
from doomfj import screenwire as SW

BLANK = 10                     # a digit slot's "no digit" (a leading zero, or no ammo)
SHADOW_STALE = 15              # a shadow value no variant uses: forces a redraw


def _variant_code(v) -> int:
    """a slot variant's nibble in `hud_v`"""
    if v is None:
        return BLANK
    if isinstance(v, bool):
        return int(v)
    return int(v)


def slot_codes(values: dict, cards: Sequence[str] = ()) -> List[int]:
    """`hud_v`'s nibbles for a `hud.slot_values` dict, in `hud.bar_slots(cards)` order (M8 F4: `cards`, the map's
    extra key icons)"""
    return [_variant_code(values[name]) for name, _x0, _w, _v in hud.bar_slots(cards)]


def _bar_record(x: int, column: Sequence[int], view_rows: int) -> List[str]:
    """one bar column: keep the view, then the bar's rows as constant (y2, colour) pairs, down to the screen's last
    row, then END"""
    height = view_rows + len(column)
    assert height == hud.VIEW_ROWS + hud.BAR_ROWS, (view_rows, len(column))
    return SW.fj_lines(SW.column(x, [("keep", view_rows)] + SW.runs(column, view_rows), height))


def weapon_record_lines(overlay: Dict[int, list], colormap_row: Sequence[int]) -> List[str]:
    """the overlay as constant records: `hud.psprite_columns` runs, coloured through ONE colormap row"""
    out = []
    for x in sorted(overlay):
        runs = overlay[x]
        items = [("keep", runs[0][0])]
        cursor = runs[0][0]
        for y0, y1, texel in runs:
            if y0 > cursor:
                items.append(("keep", y0))
            items.append(("fill", y1, colormap_row[texel]))
            cursor = y1
        out += SW.fj_lines(SW.column(x, items, hud.VIEW_ROWS + hud.BAR_ROWS))
    return out


def _frame_dispatch(prefix: str, cell: str, blocks: List[List[str]], end: str) -> List[str]:
    """draw blocks[v] for the nibble v in `cell`, then jump to `end`"""
    assert len(blocks) <= 16, len(blocks)
    out = []
    for v, block in enumerate(blocks):
        out += [f"hex.if_flags {cell}, 1<<{v}, {prefix}_n{v}, {prefix}_y{v}", f"{prefix}_y{v}:", *block,
                f";{end}", f"{prefix}_n{v}:"]
    return out + [f";{end}"]


def _frame_dispatch2(prefix: str, cell: str, blocks: List[List[str]], end: str) -> List[str]:
    """P9: draw blocks[v] for the TWO-nibble v in `cell` (the launcher made the weapon's frames 17), then jump to `end`
    -- a chain on the high nibble, then `_frame_dispatch` on the low one; a value with no block draws nothing"""
    assert len(blocks) <= 256, len(blocks)
    out = []
    groups = [blocks[h * 16:(h + 1) * 16] for h in range((len(blocks) + 15) // 16)]
    for h, grp in enumerate(groups):
        out += [f"hex.if_flags {cell} + dw, 1<<{h}, {prefix}_hn{h}, {prefix}_h{h}", f"{prefix}_h{h}:"]
        out += _frame_dispatch(f"{prefix}{h}", cell, grp, end)
        out += [f"{prefix}_hn{h}:"]
    return out + [f";{end}"]


def hud_decls(level_start: Sequence[int], cards: Sequence[str] = ()) -> List[str]:
    n = len(hud.bar_slots(cards))
    assert len(level_start) == n
    return [f"hud_v: hex.vec {n}, {sum(v << (4 * i) for i, v in enumerate(level_start))}",
            f"hud_s: hex.vec {n}, {sum(SHADOW_STALE << (4 * i) for i in range(n))}",
            "hud_full: hex.vec 1, 1"]


def hud_restart_lines(level_start: Sequence[int]) -> List[str]:
    """the level start's values (NEW GAME / the restart block); the menu frame before it already set `hud_full`"""
    return [f"hex.set {len(level_start)}, hud_v, {sum(v << (4 * i) for i, v in enumerate(level_start))}"]


# a slot whose value already lives in a game cell reads THAT cell, not a copy in `hud_v` (the blue card is the doors'
# `pcard`, P2a.1): a copy would be one more thing to keep in step. M8 F4: the yellow and red cards' slots read
# lootcode's `pcard_y` / `pcard_r` (lootcode.CARD_CELL), present only on a map that holds the card
VALUE_CELLS = {"card": "pcard", "card_y": "pcard_y", "card_r": "pcard_r"}


def hud_tail_lines(colours: Dict[str, int], overlay: Dict[int, list], colormap_row: Sequence[int],
                   view_rows: int = hud.VIEW_ROWS, value_cells: Dict[str, str] = VALUE_CELLS,
                   dead_cell: Optional[str] = None, cards: Sequence[str] = (), shadow=None,
                   flash_row: Optional[Sequence[int]] = None, weapon_rows=None) -> List[str]:
    """the world frame's tail before `frame_end`: the weapon, then the bar's changed columns.
    P10 (the owner's play-test, 2026-10-12): with `dead_cell` (the game tier's `p_dead`), a dead player draws no weapon
    and no flash -- DOOM's P_DropWeapon lowers the weapon out of view; the overlays are baked at WEAPONTOP, so the
    picture hides it at once (hud.NO_PSPRITE is the oracle's side).
    M8 F4: `cards` -- the map's extra key icons (hud.bar_slots(cards)), their slots reading `value_cells`' card cells.
    M8 C6: `shadow` -- (weapons, flashes, colour row) of the SHADOW weapon (hud.shadow_columns, a map holding partial
    invisibility): drawn instead while `p_inv` shows (powercode.shadow_lines); None (E1M1): the text is as before.
    M8 (E1M9's dark sector): `flash_row` -- the flashes' colours (hud.FULLBRIGHT_ROW's; None: `colormap_row`, the old
    call); `weapon_rows` -- None (one row: `colormap_row` lights the weapon, the text as before), or [(lit row, shadow
    row or None)] per distinct sector row: one baked weapon drawing per row, picked by the nibble `WEAPON_ROW_CELL`
    that the view's descend leaf sets (`weapon_row_lines`); the shadow flash keeps `shadow`'s row"""
    slots = hud.bar_slots(cards)
    owned_cols = {x for _n, x0, w, _v in slots for x in range(x0, x0 + w)}
    out = ["// M7 P4.0 (doomfj.hudcode): the weapon overlay, then the bar's changed columns"]
    if dead_cell is not None:
        out.append(f"hex.if1 1, {dead_cell}, hff_end      // P10: a dead player's hands are empty")
    if isinstance(overlay, dict):
        out += weapon_record_lines(overlay, colormap_row)
    else:
        # M7 P4.1: one overlay per weapon frame, chosen by `wp_frm`; then the flash's, by `fl_frm` (0 = none) -- the
        # psprites in DOOM's order, the flash's records after the weapon's (the device draws a later record over)
        weapons, flashes = overlay
        frow = colormap_row if flash_row is None else flash_row

        def wdraw(prefix, frames, row_, end):
            return _frame_dispatch2(prefix, "wp_frm", [weapon_record_lines(o, row_) for o in frames], end)

        def wrows(prefix, frames, rows_, end):
            """M8: the weapon's drawing per light row, on `WEAPON_ROW_CELL` (one row: the old single drawing)"""
            if weapon_rows is None:
                return wdraw(prefix, frames, rows_, end)
            return _frame_dispatch(prefix + "r", WEAPON_ROW_CELL,
                                   [wdraw(f"{prefix}{k}x", frames, r_, end) for k, r_ in enumerate(rows_)], end)
        if shadow is not None:                       # M8 C6: an invisible player's psprites, R_DrawPSprite's shadow
            from doomfj.powercode import shadow_lines
            sw, sf, srow = shadow
            out += shadow_lines("hsd_on", "hsd_off") + ["hsd_on:"]
            out += wrows("hsw", sw, srow if weapon_rows is None else [s_ for _r, s_ in weapon_rows], "hsw_end")
            out += ["hsw_end:"]
            out += _frame_dispatch("hsf", "fl_frm", [[]] + [weapon_record_lines(o, srow) for o in sf], "hff_end")
            out += ["hsd_off:"]
        out += wrows("hwf", weapons, colormap_row if weapon_rows is None else [r_ for r_, _s in weapon_rows], "hwf_end")
        out += ["hwf_end:"]
        out += _frame_dispatch("hff", "fl_frm", [[]] + [weapon_record_lines(o, frow) for o in flashes],
                               "hff_end")
        out += ["hff_end:"]
    # the full redraw: the static columns, and every shadow stale
    out += ["hex.if0 1, hud_full, hud_slots"]
    for x in range(hud.SCREEN_W):
        if x not in owned_cols:
            out += _bar_record(x, hud.bar_column(colours, x, cards=cards), view_rows)
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
                out += _bar_record(x, hud.bar_column(colours, x, var, cards=cards), view_rows)
            out += [f";hud_c{i}", f"hud_d{i}_{k + 1}:"]
        out += [f";hud_c{i}",                                 # a value no variant uses: nothing to draw
                f"hud_c{i}:",
                f"hex.mov 1, {s}, {v}",
                f"hud_n{i}:"]
    return out


# the level start's bar (the model's `level_start`: 100 health, no armor, the pistol up with 50 bullets, the fist and
# the pistol owned -- ARMS shows 2 lit). The card slot is `pcard`'s, so its value here is never read.
# P9: `owned` is the six ARMS digits 2..7 (hud.arms_owned): the pistol's 2 lit
LEVEL_START = dict(ammo=50, health=100, armor=0, owned=(True, False, False, False, False, False), blue=False)


def slot_index(name: str) -> int:
    """the nibble of `hud_v` / `hud_s` that slot `name` (hud.bar_slots) holds -- what a writer of `hud_v` addresses
    (weaponcode.bar_lines), so no caller restates the slot order"""
    return [n for n, _x0, _w, _v in hud.bar_slots()].index(name)
READY_WEAPON = "PISGA0"        # P4.0 draws the ready pistol; P4.1's weapon state machine picks the frame


def game_hud_parts(rm, asset_wad, sprite_wad, sectors, cards: Sequence[str] = (), shadow: bool = False,
                   plasma: bool = False) -> dict:
    """everything the game tier's emitter splices in: `decls` (state cells), `restart` (NEW GAME's values), `menu` (the
    line every menu frame runs: the bar is redrawn after it) and `tail` (the world frame's weapon and bar, before
    `frame_end`). ONE colormap row lights the weapon on every sector of the map (asserted: a map with darker sectors
    needs the row chosen at runtime, which P4.0 does not emit). M8 F4: `cards` -- the map's extra key icons
    (lootcode.hud_cards: "yellow" / "red"; E1M1 none), slots after every other one. M8 C6: `plasma` -- the map's rifle
    (combat.plasma_on): its frames PLSGA0 / PLSGB0 and flashes PLSFA0 / PLSFB0 join the overlays (none elsewhere)."""
    palette = bytes(b for rgb in asset_wad.playpal(0) for b in rgb)
    colours = hud.bar_colours(palette)
    # M8 (E1M9): the weapon's light rows -- one per distinct row the map's sectors give (one: E1M1..E1M8, the text as
    # it was); the flash is FULLBRIGHT (gamedata's FF_FULLBRIGHT, asserted below), so it bakes once
    light_rows, sector_rows = hud.weapon_light_rows(rm, sectors)
    cmap_ = asset_wad.colormap()
    row = cmap_[light_rows[0]]
    bright = cmap_[hud.FULLBRIGHT_ROW]
    start = slot_codes(hud.slot_values(**LEVEL_START, cards=cards), cards)
    # M7 P4.1: every weapon frame (`wp_frm` indexes weaponcode.overlay_frames) and every flash frame (`fl_frm` - 1)
    from doomfj import weaponcode as WC

    def cols(lump):
        return hud.psprite_columns(sprite_wad.get_data(lump), view_w=rm.cfg.VIEW_W, view_rows=rm.cfg.VIEW_H)
    overlay = ([cols(lump) for lump in WC.overlay_frames(plasma=plasma)], [cols(lump) for lump in WC.flash_frames(plasma)])
    _fb = WC.frames_fullbright(plasma)
    assert not any(_fb[0]) and all(_fb[1]), ("M8: the weapon frames are lit by the sector and the flashes FULLBRIGHT "
                                             "(R_DrawPSprite) -- a frame broke the rule", _fb)
    from doomfj.wall_renderer import PLAYER_MODE
    from doomfj.world import player_mortal
    # M8 C6 (`shadow`, a map holding partial invisibility): the shadow weapon's frames (hud.shadow_columns)
    shd = ([hud.shadow_columns(o) for o in overlay[0]], [hud.shadow_columns(o) for o in overlay[1]],
           hud.shadow_row(cmap_, bright)) if shadow else None
    # M8: several rows -- each its lit row and (with the shadow weapon) its shadow row, hud.shadow_row of it
    # (E1M1..E1M8: the one row IS the fullbright one, so the weapon, the flash and their shadows share it -- the text as
    # it was; a one-row map off it takes the per-row drawing with one row, its cell always 0)
    wrows_ = None if _one_row(light_rows) else [
        (cmap_[r], hud.shadow_row(cmap_, cmap_[r]) if shadow else None) for r in light_rows]
    return {"decls": hud_decls(start, cards) + ([f"{WEAPON_ROW_CELL}: hex.vec 1"] if wrows_ else []),
            "restart": hud_restart_lines(start), "menu": ["hex.set 1, hud_full, 1"],
            "tail": hud_tail_lines(colours, overlay, row, view_rows=rm.cfg.VIEW_H,
                                   dead_cell="p_dead" if player_mortal(PLAYER_MODE) else None, cards=cards,
                                   shadow=shd, flash_row=bright if wrows_ else None, weapon_rows=wrows_),
            "colours": colours,
            "overlay": overlay, "colormap_row": row,
            "light_rows": light_rows, "sector_rows": sector_rows}


# M8 (E1M9): the nibble that picks the weapon's light row -- the index into hud.weapon_light_rows' rows of the player's
# sector, set by the view's descend leaf every frame (`weapon_row_lines`); declared on a map of several rows only
WEAPON_ROW_CELL = "hud_lrow"


def _one_row(light_rows) -> bool:
    """the weapon's row needs no runtime pick: the map's one row, and it is the flash's (fullbright) one"""
    return tuple(light_rows) == (hud.FULLBRIGHT_ROW,)


def weapon_row_lines(parts: Optional[dict], sector: int) -> List[str]:
    """the view's descend leaf in `sector`: set WEAPON_ROW_CELL to its row index -- nothing on a one-row map (or
    without the game screen)"""
    if parts is None or _one_row(parts["light_rows"]):
        return []
    return [f"    hex.set 1, {WEAPON_ROW_CELL}, {parts['sector_rows'][sector]}"]
