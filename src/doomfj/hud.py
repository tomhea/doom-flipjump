"""M7 P4.0 -- the game screen's status bar and weapon overlay (docs/gp-combat.md section 2): ONE generator that both
mirrors read. The oracle composes its 160x100 picture with `compose`; the fj emitter bakes the same pixels, column by
column, from `bar_column` and `psprite_columns`.

THE SCREEN (D6, at half resolution): the 3D view is rows [0, VIEW_ROWS) with the horizon at VIEW_ROWS // 2, and the
bar is rows [VIEW_ROWS, H). The view never writes a bar row; the device keeps a row nobody writes.

THE BAR (decision C3, option C): a flat dark bar in the MENU's fonts -- numbers in the 5x7 font, labels in the 3x5
font. Five panels: AMMO, HEALTH, ARMS, ARMOR, KEYS. A number is RIGHT-ALIGNED in a fixed 3-digit field, so each
digit's columns are fixed and the fj side redraws a field by dispatching on one digit at a time; leading zeros are
blank, 0 is drawn as "0". The ready weapon's ammo is blank for the fist and the chainsaw (DOOM's `am_noammo`).

THE WEAPON (decision C4): DOOM's R_DrawPSprite at pspritescale = VIEW_W / 320, the psprite at (sx, sy) = (1, sy),
WEAPONTOP 32 when ready (no bob, D5). Every coordinate is DOOM's fixed point: `x1 = (centerxfrac + tx * scale) >> 16`,
a post's rows `yl = ceil(topscreen)` .. `yh = ceil(bottomscreen) - 1` clipped to the view, its texel `frac >> 16`
stepping by 1 / scale. The overlay is lit as DOOM lights a psprite: `scalelight[lightnum][MAXLIGHTSCALE - 1]` of the
player's sector, which `psprite_light_row` returns.
"""
from __future__ import annotations

import struct
from typing import Dict, List, Optional, Sequence, Tuple

from doomfj.menu import _GLYPHS, _SMALL_GLYPHS, GLYPH_GAP

VIEW_ROWS = 84                 # the game tier's 3D view height (D6: 168 of 200 at half resolution)
BAR_ROWS = 16
WEAPONTOP = 32                 # DOOM's psprite sy when the weapon is up (p_pspr.c)
NATIVE_W = 320
BASEYCENTER = 100              # DOOM's psprite vertical anchor (r_things.c), in native rows
FRACUNIT = 1 << 16

# ------------------------------------------------------------------------------------------------- the bar
# the panels' column extents [x0, x1], left to right; a separator column at each x0 but the first
PANELS = (("AMMO", 0, 30), ("HEALTH", 31, 66), ("ARMS", 67, 94), ("ARMOR", 95, 130), ("KEYS", 131, 159))
NUM_Y, LABEL_Y = 2, 10         # bar rows of the 5x7 numbers and the 3x5 labels
DIGIT_W = 5
FIELD_DIGITS = 3
PERCENT = "##   |##  #|   # |  #  | #   |#  ##|   ##"
# ARMS: the weapons 2, 3, 4 (pistol, shotgun, chainsaw -- E1M1 has no others), yellow when owned (DOOM's STYSNUM)
ARMS_WEAPONS = (2, 3, 4)
ARMS_X0 = 71                   # the first arms digit's column; the next ones every ARMS_PITCH
ARMS_PITCH = 8
CARD_BOX = (142, 2, 6, 7)      # the blue key card: x0, y0, width, height (its four corners left out)


def _rgb_entries(palette_rgb):
    return [tuple(palette_rgb[3 * i:3 * i + 3]) for i in range(len(palette_rgb) // 3)]


def bar_colours(palette_rgb) -> Dict[str, int]:
    """the bar's palette indices, DERIVED from PLAYPAL by nearest colour (no hand-picked index)"""
    entries = _rgb_entries(palette_rgb)

    def nearest(rgb):
        return min(range(len(entries)), key=lambda i: (sum((a - b) ** 2 for a, b in zip(entries[i], rgb)), i))
    return {"bg": nearest((36, 36, 36)), "edge": nearest((110, 110, 110)), "sep": nearest((70, 70, 70)),
            "label": nearest((190, 190, 190)), "num": nearest((220, 30, 30)), "owned": nearest((230, 200, 40)),
            "unowned": nearest((90, 90, 90)), "card": nearest((40, 70, 255))}


def _ink(px, s, x, y, colour, font):
    """`s` drawn into the 16 x 160 bar `px` at (x, y), glyph after glyph; returns the next x"""
    for ch in s:
        rows = font.get(ch, font[" "]).split("|")
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                if cell == "#" and 0 <= y + r < BAR_ROWS and 0 <= x + c < len(px[0]):
                    px[y + r][x + c] = colour
        x += len(rows[0]) + GLYPH_GAP
    return x


def _width(s, font):
    return sum(len(font.get(ch, font[" "]).split("|")[0]) for ch in s) + GLYPH_GAP * max(0, len(s) - 1)


def field_x(panel: str, percent: bool) -> int:
    """the first digit column of a panel's right-aligned 3-digit field (then the % sign, if any)"""
    _n, x0, x1 = next(p for p in PANELS if p[0] == panel)
    w = FIELD_DIGITS * (DIGIT_W + GLYPH_GAP) - GLYPH_GAP + ((DIGIT_W + GLYPH_GAP) if percent else 0)
    return x0 + (x1 - x0 + 1 - w) // 2 + (1 if x0 else 0)


def digits(value: Optional[int]) -> Tuple[Optional[int], ...]:
    """a 3-digit field's digits, most significant first; None = blank (leading zeros, or no value at all)"""
    if value is None:
        return (None,) * FIELD_DIGITS
    v = max(0, min(999, value))
    s = str(v).rjust(FIELD_DIGITS)
    return tuple(None if ch == " " else int(ch) for ch in s)


def bar_pixels(colours: Dict[str, int], *, ammo: Optional[int], health: int, armor: int,
               owned: Sequence[bool], blue: bool) -> List[List[int]]:
    """the bar's 16 x 160 palette indices for these values (`owned` = the ARMS weapons 2, 3, 4; `ammo` None = blank)"""
    px = [[colours["bg"]] * 160 for _ in range(BAR_ROWS)]
    for x in range(160):
        px[0][x] = colours["edge"]
    for _n, x0, _x1 in PANELS[1:]:
        for y in range(2, BAR_ROWS - 1):
            px[y][x0] = colours["sep"]
    for name, x0, x1 in PANELS:
        _ink(px, name, x0 + (x1 - x0 + 1 - _width(name, _SMALL_GLYPHS)) // 2 + (1 if x0 else 0), LABEL_Y,
             colours["label"], _SMALL_GLYPHS)
    for panel, value, pct in (("AMMO", ammo, False), ("HEALTH", health, True), ("ARMOR", armor, True)):
        x = field_x(panel, pct)
        for d in digits(value):
            if d is not None:
                _ink(px, str(d), x, NUM_Y, colours["num"], _GLYPHS)
            x += DIGIT_W + GLYPH_GAP
        if pct:
            _ink(px, "%", x, NUM_Y, colours["num"], {"%": PERCENT, " ": "     "})
    for i, w in enumerate(ARMS_WEAPONS):
        _ink(px, str(w), ARMS_X0 + i * ARMS_PITCH, NUM_Y, colours["owned" if owned[i] else "unowned"], _GLYPHS)
    if blue:
        x0, y0, w, h = CARD_BOX
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if (y in (y0, y0 + h - 1)) and (x in (x0, x0 + w - 1)):
                    continue
                px[y][x] = colours["card"]
    return px


# the bar's DYNAMIC slots: each owns a fixed column range and draws one of a few variants; every other column is static.
# (name, x0, width, variants): a digit slot's variant is None or 0..9, an arms slot's owned False/True, the card's
# present False/True. The fj side redraws a slot's columns by dispatching on its variant.
def bar_slots() -> List[Tuple[str, int, int, tuple]]:
    out = []
    for panel, pct in (("AMMO", False), ("HEALTH", True), ("ARMOR", True)):
        x = field_x(panel, pct)
        for k in range(FIELD_DIGITS):
            out.append(("%s%d" % (panel.lower(), k), x, DIGIT_W, (None,) + tuple(range(10))))
            x += DIGIT_W + GLYPH_GAP
    for i, w in enumerate(ARMS_WEAPONS):
        out.append(("arms%d" % w, ARMS_X0 + i * ARMS_PITCH, DIGIT_W, (False, True)))
    out.append(("card", CARD_BOX[0], CARD_BOX[2], (False, True)))
    return out


def slot_values(*, ammo: Optional[int], health: int, armor: int, owned: Sequence[bool], blue: bool) -> dict:
    """every dynamic slot's variant for these values (the same names as `bar_slots`)"""
    v = {}
    for panel, value in (("ammo", ammo), ("health", health), ("armor", armor)):
        for k, d in enumerate(digits(value)):
            v["%s%d" % (panel, k)] = d
    for i, w in enumerate(ARMS_WEAPONS):
        v["arms%d" % w] = bool(owned[i])
    v["card"] = bool(blue)
    return v


def bar_column(colours: Dict[str, int], x: int, slot_variant=None) -> List[int]:
    """column x of the bar (16 palette indices) with its slot (if any) drawn in `slot_variant`. A column belongs to at
    most one slot (asserted by `test_hud`), so drawing the whole bar with every slot at the variant and reading x is
    the definition."""
    slots = {name: (x0, w, variants) for name, x0, w, variants in bar_slots()}
    owner = [n for n, (x0, w, _v) in slots.items() if x0 <= x < x0 + w]
    vals = {"ammo": None, "health": 0, "armor": 0, "owned": [False] * 3, "blue": False}
    if owner:
        n = owner[0]
        if n.startswith(("ammo", "health", "armor")):
            panel, k = n[:-1], int(n[-1])
            dd = [None] * FIELD_DIGITS
            dd[k] = slot_variant
            # a field whose OTHER digits are blank: reading column x only sees digit k
            num = None if slot_variant is None else slot_variant * 10 ** (FIELD_DIGITS - 1 - k)
            px = bar_pixels(colours, **{**vals, panel: None})
            if slot_variant is not None:
                _ink(px, str(slot_variant), field_x(panel.upper(), panel != "ammo") + k * (DIGIT_W + GLYPH_GAP),
                     NUM_Y, colours["num"], _GLYPHS)
            return [px[y][x] for y in range(BAR_ROWS)]
        if n.startswith("arms"):
            owned = [False] * 3
            owned[ARMS_WEAPONS.index(int(n[4:]))] = bool(slot_variant)
            px = bar_pixels(colours, **{**vals, "owned": owned})
            return [px[y][x] for y in range(BAR_ROWS)]
        px = bar_pixels(colours, **{**vals, "blue": bool(slot_variant)})
        return [px[y][x] for y in range(BAR_ROWS)]
    px = bar_pixels(colours, **vals)
    return [px[y][x] for y in range(BAR_ROWS)]


# --------------------------------------------------------------------------------------------- the weapon
def patch_posts(lump: bytes):
    """a DOOM picture: (width, height, leftoffset, topoffset, columns), each column a list of (topdelta, texels)"""
    w, h, lo, to = struct.unpack_from("<hhhh", lump, 0)
    offs = struct.unpack_from("<%dI" % w, lump, 8)
    cols = []
    for off in offs:
        posts = []
        while lump[off] != 0xFF:
            top, n = lump[off], lump[off + 1]
            posts.append((top, list(lump[off + 3:off + 3 + n])))
            off += n + 4
        cols.append(posts)
    return w, h, lo, to, cols


def _fixed_mul(a: int, b: int) -> int:
    return (a * b) >> 16


def psprite_columns(lump: bytes, *, view_w: int = 160, view_rows: int = VIEW_ROWS, sx: int = 1,
                    sy: int = WEAPONTOP) -> Dict[int, List[Tuple[int, int, int]]]:
    """R_DrawPSprite + R_DrawMaskedColumn for one psprite frame: {screen x: [(y_top, y_end, texel), ...]} -- each
    entry one screen row run [y_top, y_end) of ONE texel, top to bottom; the rows no post covers are transparent"""
    width, _h, leftoffset, topoffset, cols = patch_posts(lump)
    scale = view_w * FRACUNIT // NATIVE_W                        # pspritescale
    iscale = (FRACUNIT * FRACUNIT) // scale                      # xiscale = dc_iscale = FixedDiv(FRACUNIT, scale)
    centerxfrac, centeryfrac = (view_w // 2) << 16, (view_rows // 2) << 16
    tx = (sx << 16) - ((NATIVE_W // 2) << 16) - (leftoffset << 16)
    x1 = (centerxfrac + _fixed_mul(tx, scale)) >> 16
    x2 = ((centerxfrac + _fixed_mul(tx + (width << 16), scale)) >> 16) - 1
    texturemid = (BASEYCENTER << 16) + FRACUNIT // 2 - ((sy << 16) - (topoffset << 16))
    sprtopscreen = centeryfrac - _fixed_mul(texturemid, scale)
    out: Dict[int, List[Tuple[int, int, int]]] = {}
    frac = 0
    lo_x = max(0, x1)
    frac += iscale * (lo_x - x1)
    for x in range(lo_x, min(view_w - 1, x2) + 1):
        texcol = frac >> 16
        frac += iscale
        if not 0 <= texcol < width:
            continue
        rows: List[Tuple[int, int]] = []
        for top, texels in cols[texcol]:
            topscreen = sprtopscreen + scale * top
            bottomscreen = topscreen + scale * len(texels)
            yl = (topscreen + FRACUNIT - 1) >> 16
            yh = (bottomscreen - 1) >> 16
            yl, yh = max(0, yl), min(view_rows - 1, yh)
            dc_texturemid = texturemid - (top << 16)
            for y in range(yl, yh + 1):
                t = (dc_texturemid + (y - (view_rows // 2)) * iscale) >> 16
                rows.append((y, texels[t & 127] if 0 <= (t & 127) < len(texels) else texels[-1]))
        runs: List[Tuple[int, int, int]] = []
        for y, texel in sorted(rows):
            if runs and runs[-1][1] == y and runs[-1][2] == texel:
                runs[-1] = (runs[-1][0], y + 1, texel)
            else:
                runs.append((y, y + 1, texel))
        if runs:
            out[x] = runs
    return out


def psprite_light_row(rm, sector_light: int) -> int:
    """the colormap row DOOM lights a psprite with: `scalelight[lightnum][MAXLIGHTSCALE - 1]` of the player's sector"""
    from doomfj.tables import MAXLIGHTSCALE
    return rm.scalelight[rm.wall_lightnum(sector_light, 0)][MAXLIGHTSCALE - 1]


# --------------------------------------------------------------------------------------------- the picture
def compose(view: List[List[int]], colormap, light_row: int, overlay: Dict[int, List[Tuple[int, int, int]]],
            bar: List[List[int]]) -> List[List[int]]:
    """the game screen: the VIEW_ROWS-row view with the weapon over it, then the bar -- rows x columns of indices"""
    out = [list(row) for row in view[:VIEW_ROWS]]
    for x, runs in overlay.items():
        for y0, y1, texel in runs:
            for y in range(y0, y1):
                out[y][x] = colormap[light_row][texel]
    return out + [list(row) for row in bar]


class GameScreen:
    """THE ORACLE'S GAME SCREEN (M7 P4.0): the view `render_wall_frame` draws at VIEW_ROWS rows, with the weapon over
    it and the bar below -- the 160x100 picture the game binary presents. Every gate that compares a game-tier world
    frame builds one of these and passes the view through `frame` (ONE composition, R6). The weapon and its light row
    are `hudcode.game_hud_parts`' choices (the same frame, the same single row), read from there."""

    def __init__(self, rm, asset_wad, sprite_wad, sectors):
        from doomfj import hudcode
        assert rm.cfg.VIEW_H == VIEW_ROWS, ("the game screen needs the game tier's 84-row config "
                                           "(config.GAME_CFG), not %d rows" % rm.cfg.VIEW_H)
        parts = hudcode.game_hud_parts(rm, asset_wad, sprite_wad, sectors)
        self.cfg = rm.cfg
        self.colours, self.overlay, self.row = parts["colours"], parts["overlay"], parts["colormap_row"]
        self.level_start = dict(hudcode.LEVEL_START)

    def frame(self, view: bytes, *, card: bool = False, values: Optional[dict] = None) -> bytes:
        """the game screen for a rendered view (W x H bytes whose rows >= VIEW_ROWS are unused) and the bar's values"""
        w = self.cfg.W
        rows = [list(view[y * w:(y + 1) * w]) for y in range(VIEW_ROWS)]
        vals = dict(self.level_start if values is None else values, blue=bool(card))
        bar = bar_pixels(self.colours, **vals)
        out = rows
        for x, runs in self.overlay.items():
            for y0, y1, texel in runs:
                for y in range(y0, y1):
                    out[y][x] = self.row[texel]
        return bytes(c for row in out + bar for c in row)
