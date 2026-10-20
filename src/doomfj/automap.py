"""M8 -- THE MAP PAGE (the owner, 2026-10-18: "a fixed menu item (like the help page) with fixed map but a red dot that
shows where the player is"): a main-menu item MAP and the key M open a page of the level's lines, north up, with a
red dot at the player's position. The game is paused while it shows, as it is under the help.

ONE GENERATOR, TWO MIRRORS -- the menu's rule (doomfj.menu). The page is a BAKED FRAME like the help: `band_pixels` is
the oracle's picture of a band, `band_stream` the 0x0B bytes the program prints for it, both from one `_band_bitmap`.
Only the DOT is computed at run time, from `viewx` / `viewy`: `dot` is its oracle side, `fj_lines` its program side,
the same 32-bit arithmetic step for step (an add, a shift, a compare per band boundary, a byte add).

THE SCALE AND THE BANDS. A 160 x 100 screen with a legend column on the right leaves ~116 x 98 px for the map. The
scale (`units` map units a pixel) is the finest of 32, 40, 48, ... (steps of UNITS_STEP from UNITS_MIN) whose map
fits the area's WIDTH: E1M2, 2,968 x 4,952 units, 32 a pixel (93 x 155 px); E1M1, 3,952 x 3,400, 40 a pixel (99 x
86 px, one page -- at 32 it is 124 px wide, at the old power-of-two rule's 64 a 62 x 54 blob). A POWER-OF-TWO scale's
dot is the 16.16 position plus a constant, SHIFTED (`shift`); any other's is the position's whole units times a
fixed-point RECIPROCAL (`recip`: d * M >> 4t equals d // units for EVERY d up to the map's extent -- checked when the
page is built, over the whole extent), one nibble-by-nibble `hex.add_mul` per nibble of M. A map taller than the screen is cut into BANDS -- vertical pages,
each a whole screen of map rows, overlapping, spread evenly -- and the page shown is the band whose middle the
player's row is in: band k from the row `thresholds[k-1]` (the middle of its overlap with band k-1) on. So the dot is
never near a band's top or bottom edge. Every reachable row's dot is ASSERTED on screen (`check`), so a map whose
geometry breaks that stops the emitter instead of drawing off the screen.

WHAT IS DRAWN -- DOOM's automap rules (am_map.c AM_drawWalls), in this screen's colours: a line flagged ML_DONTDRAW is
not drawn; a one-sided line, and a SECRET line (drawn as a wall, as DOOM does), is a WALL (the brightest entry); a
two-sided line is drawn DIM only where the floor or the ceiling changes across it (an invisible subdivision is not
drawn); a locked door's line takes its KEY's colour and an exit line is green, over everything. The legend on the
right names what the page uses; the credit is in its corner, as on every baked screen.

The colours, like the menu's, are DERIVED from the wad's PLAYPAL (nearest entries to fixed targets), never indices.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from doomfj.menu import (_GLYPHS, _SMALL_GLYPHS, END, GLYPH_H, KEEP, SMALL_GLYPH_H, _draw, _draw_credit, _encode,
                         credit_box, palette_colours, text_width)
from doomfj.menu import MAP_KEY

AUTOMAP_KEY = MAP_KEY                  # 'm': the keyboard device's SDL code -- ONE source, the menu's

UNITS_MIN = 32                         # the finest scale: 32 map units a pixel
UNITS_STEP = 8                         # ... then 40, 48, 56, 64, ...
BANDS_MAX = 4                          # a map needing more bands than this at a scale tries the next coarser one
MARGIN_X = 2                           # the screen's left edge to the map area
MARGIN_Y = 1                           # every band leaves this many rows above and below the map
PANEL_W = 36                           # the legend column, right of the map, MARGIN_X from the screen's right edge
PANEL_GAP = 4                          # the map area to the legend column
DOT = 3                                # the dot is DOT x DOT pixels, centred on the player's pixel

ML_SECRET, ML_DONTDRAW = 0x20, 0x80    # DOOM's linedef flags (doomdata.h)
# a locked door's special -> its key (DOOM's 26/27/28 DR and 32/33/34 D1; Boom's 99, 133..137 the locked fast doors)
KEY_DOORS = {26: "blue", 32: "blue", 99: "blue", 133: "blue",
             27: "yellow", 34: "yellow", 136: "yellow", 137: "yellow",
             28: "red", 33: "red", 134: "red", 135: "red"}
EXITS = frozenset({11, 51, 52, 124})   # the exit and secret-exit switches and walk-overs
# the kinds a line is drawn as, in DRAW ORDER (a later kind is drawn over an earlier one where they meet)
KINDS = ("step", "wall", "blue", "yellow", "red", "exit")
# the legend's rows, top to bottom: (kind, its label) -- a row only for a kind the map has ("you" always)
LEGEND = (("you", "YOU"), ("exit", "EXIT"), ("blue", "BLUE"), ("yellow", "YELLOW"), ("red", "RED"))
TITLE = "MAP"
CLOSE_HINT = "M CLOSE"
LEGEND_Y = 30                          # the legend's first row (below the title, the map's name, the page)
LEGEND_PITCH = 8
SWATCH_W = 5                           # a legend row's colour sample, then a gap, then its label
SWATCH_GAP = 3
# the targets the colours are the PLAYPAL's nearest entries to: the keys', the exit's, the dim steps'
_TARGETS = {"blue": (0, 0, 255), "yellow": (255, 255, 0), "red": (155, 0, 0), "exit": (0, 255, 0),
            "step": (96, 96, 96)}


def map_inks(palette_rgb) -> dict:
    """kind -> palette index: the menu's four (background, text = the walls, highlight = the dot and the title,
    credit) and the nearest entries to `_TARGETS`. The dot is the menu's most saturated red; the red DOOR is a darker
    red, so a door beside the player is not the player"""
    background, text, highlight, credit = palette_colours(palette_rgb)
    entries = [tuple(palette_rgb[3 * i:3 * i + 3]) for i in range(len(palette_rgb) // 3)]

    def nearest(rgb):
        return min(range(len(entries)), key=lambda i: sum((a - b) ** 2 for a, b in zip(entries[i], rgb)))
    ink = {k: nearest(rgb) for k, rgb in _TARGETS.items()}
    ink.update(background=background, text=text, wall=text, you=highlight, title=highlight, credit=credit)
    assert ink["red"] != ink["you"], "the red door must not be the dot's colour"
    return ink


@dataclass(frozen=True)
class Pages:
    """THE MAP PAGE's geometry and inks -- everything both mirrors draw from"""
    mapname: str
    width: int                         # the screen
    height: int
    units: int                         # a pixel is this many map units (UNITS_MIN + k * UNITS_STEP)
    minx: int                          # the map's vertex bounding box
    maxx: int
    miny: int
    maxy: int
    x0: int                            # the screen column of map x = minx
    tops: Tuple[int, ...]              # each band's first full-map row
    lines: Tuple[Tuple[str, int, int, int, int], ...]   # (kind, c1, r1, c2, r2): full-map pixels, in draw order
    ink: Tuple[Tuple[str, int], ...]   # map_inks(), as items

    @property
    def inks(self) -> dict:
        return dict(self.ink)

    @property
    def shift(self) -> Optional[int]:
        """log2(units) for a power-of-two scale (the dot SHIFTS), None for any other (the dot multiplies: `recip`)"""
        return self.units.bit_length() - 1 if self.units & (self.units - 1) == 0 else None

    @property
    def wpx(self) -> int:
        return (self.maxx - self.minx) // self.units + 1

    @property
    def hpx(self) -> int:
        return (self.maxy - self.miny) // self.units + 1

    @property
    def band_h(self) -> int:
        return self.height - 2 * MARGIN_Y

    @property
    def nbands(self) -> int:
        return len(self.tops)

    @property
    def thresholds(self) -> Tuple[int, ...]:
        """band k (k >= 1) is shown from full-map row thresholds[k-1] on: the middle of its overlap with band k-1"""
        return tuple((self.tops[k] + self.tops[k - 1] + self.band_h) // 2 for k in range(1, self.nbands))

    @property
    def panel_x(self) -> int:
        return self.width - MARGIN_X - PANEL_W

    @property
    def kinds(self) -> frozenset:
        return frozenset(k for k, *_ in self.lines)


def line_kind(ld, sides, sectors) -> Optional[str]:
    """DOOM's automap rule for one linedef (see the module docstring): its kind, or None when it is not drawn"""
    if ld.flags & ML_DONTDRAW:
        return None
    if ld.special in EXITS:
        return "exit"
    if ld.special in KEY_DOORS:
        return KEY_DOORS[ld.special]
    two = ld.back not in (0xFFFF, -1)
    if not two or ld.flags & ML_SECRET:
        return "wall"
    a, b = sectors[sides[ld.front].sector], sectors[sides[ld.back].sector]
    return "step" if (a.floor_h != b.floor_h or a.ceil_h != b.ceil_h) else None


def build(map_wad, mapname: str, palette_rgb, width: int, height: int) -> Pages:
    """the map page of `mapname` on a `width` x `height` screen (the config's W x H -- `pages_for` passes them; #149,
    R6: no 160 x 100 default of its own): the finest scale (UNITS_MIN, + UNITS_STEP, ...) whose map fits the map area's width
    in at most BANDS_MAX bands, the bands spread evenly over the map's rows, the lines in full-map pixels. CHECKED
    (`check`)"""
    vs, lds = map_wad.vertexes(mapname), map_wad.linedefs(mapname)
    sides, secs = map_wad.sidedefs(mapname), map_wad.sectors(mapname)
    minx, maxx = min(v.x for v in vs), max(v.x for v in vs)
    miny, maxy = min(v.y for v in vs), max(v.y for v in vs)
    area = width - MARGIN_X - PANEL_W - PANEL_GAP - MARGIN_X       # the map area's width
    band_h = height - 2 * MARGIN_Y
    units = UNITS_MIN
    while ((maxx - minx) // units + 1 > area or -(-((maxy - miny) // units + 1) // band_h) > BANDS_MAX):
        units += UNITS_STEP
    wpx, hpx = (maxx - minx) // units + 1, (maxy - miny) // units + 1
    x0 = MARGIN_X + (area - wpx) // 2
    n = -(-hpx // band_h)
    if n == 1:                                       # one band: the map centred in the screen's rows
        tops = (-((band_h - hpx) // 2),)
    else:
        tops = tuple(round(k * (hpx - band_h) / (n - 1)) for k in range(n))

    def px(v):
        return x0 + (v.x - minx) // units, (maxy - v.y) // units
    drawn = []
    for ld in lds:
        kind = line_kind(ld, sides, secs)
        if kind is not None:
            drawn.append((KINDS.index(kind), kind, *px(vs[ld.v1]), *px(vs[ld.v2])))
    lines = tuple(d[1:] for d in sorted(drawn, key=lambda d: d[0]))   # stable: the wad's order within a kind
    p = Pages(mapname.upper(), width, height, units, minx, maxx, miny, maxy, x0, tops, lines,
              tuple(sorted(map_inks(palette_rgb).items())))
    check(p)
    return p


def pages_for(map_wad, mapname: str, palette_rgb, cfg=None) -> Optional[Pages]:
    """the map's page when its MAP_CONFIG turns the page on (config.Config.AUTOMAP), else None -- the ONE switch the
    emitter, the oracle and every gate ask"""
    from doomfj.config import Config, map_cfg
    c = map_cfg(cfg or Config(), mapname)
    return build(map_wad, mapname, palette_rgb, c.W, c.H) if c.AUTOMAP else None


def has_page(mapname: str) -> bool:
    """does `mapname`'s game tier have the map page (config.MAP_CONFIG's AUTOMAP)? -- the rules' switch
    (menu.menu_step's `automap`, menu.menu_keys) for a tool that needs no picture"""
    from doomfj.config import Config, map_cfg
    return bool(map_cfg(Config(), mapname).AUTOMAP)


def shift_bits(p: Pages) -> int:
    """a POWER-OF-TWO scale: the dot's pixel is the 16.16 position (plus a constant) shifted right this many bits"""
    assert p.shift is not None, "a %d-unit scale has no shift: its dot multiplies (recip)" % p.units
    return 16 + p.shift


RECIP_T_MAX = 6                        # the reciprocal's fraction is at most 4 * this many bits


def extent(p: Pages) -> int:
    """the largest whole-unit offset the dot divides: the bounding box's width or height, in map units"""
    return max(p.maxx - p.minx, p.maxy - p.miny)


def recip(units: int, dmax: int) -> Tuple[int, int]:
    """(t, M): the fewest fraction NIBBLES t (>= 2, so the 4-nibble offset fits the t+2-nibble product register) and
    M = ceil(16**t / units) with (d * M) >> 4t == d // units for EVERY d in 0..dmax -- checked here, d by d, so a
    reciprocal is never used past where it is exact"""
    for t in range(2, RECIP_T_MAX + 1):
        m = -(-(16 ** t) // units)
        if all((d * m) >> (4 * t) == d // units for d in range(dmax + 1)):
            return t, m
    raise AssertionError("no reciprocal of %d exact to %d within %d nibbles" % (units, dmax, RECIP_T_MAX))


def recip_of(p: Pages) -> Tuple[int, int]:
    """a NON-power-of-two scale's reciprocal, exact over the map's whole extent (`recip`)"""
    assert p.shift is None
    assert extent(p) < 1 << 16, "the dot's offset is the 4 integer nibbles of a 16.16 position"
    return recip(p.units, extent(p))


def x_base(p: Pages) -> int:
    """a NON-power-of-two scale: added to viewx, (viewx + x_base) >> 16 is the player's whole-unit offset from minx"""
    return (-(p.minx << 16)) & 0xFFFFFFFF


def window(p: Pages) -> Tuple[int, int]:
    """(q, b): the dot's math reads nibbles q, q+1, q+2 of the 8-nibble sum and shifts them right b bits -- then their
    two low nibbles are bits 16+shift .. 23+shift of the sum: the pixel"""
    s = shift_bits(p)
    q, b = s // 4, s % 4
    assert q + 2 <= 7 and b <= 3, (q, b)
    return q, b


def x_const(p: Pages) -> int:
    """added to viewx: (viewx + x_const) >> (16+shift) is the dot's LEFT column -- the player's column less DOT // 2"""
    return (((p.x0 - (DOT // 2)) << shift_bits(p)) - (p.minx << 16)) & 0xFFFFFFFF


def y_const(p: Pages) -> int:
    """viewy is subtracted from it: (y_const - viewy) >> (16+shift) is the player's FULL-MAP row"""
    return (p.maxy << 16) & 0xFFFFFFFF


def band_of_row(p: Pages, row: int) -> int:
    return sum(row >= t for t in p.thresholds)


def top_const(p: Pages, band: int) -> int:
    """added to the full-map row on band `band`: the dot's TOP screen row (mod 256)"""
    return (MARGIN_Y - p.tops[band] - (DOT // 2)) & 0xFF


def _row(p: Pages, viewy: int) -> int:
    """the player's full-map row, the program's way (both scales)"""
    u = (y_const(p) - viewy) & 0xFFFFFFFF
    if p.shift is not None:
        return (u >> shift_bits(p)) & 0xFF
    t, m = recip_of(p)
    return (((u >> 16) * m) >> (4 * t)) & 0xFF


def dot(p: Pages, viewx: int, viewy: int) -> Tuple[int, int, int]:
    """THE ORACLE's dot: (band, left column, top row) from the 16.16 view position -- `fj_lines`' arithmetic, step for
    step: a power-of-two scale's 32-bit sums and shifted bytes; any other's whole-unit offsets times the reciprocal,
    the product's byte at nibble t, the column's constant added; then the band's compares and the byte add"""
    if p.shift is not None:
        col = (((viewx + x_const(p)) & 0xFFFFFFFF) >> shift_bits(p)) & 0xFF
    else:
        t, m = recip_of(p)
        d = ((viewx + x_base(p)) & 0xFFFFFFFF) >> 16
        col = ((((d * m) >> (4 * t)) & 0xFF) + p.x0 - DOT // 2) & 0xFF
    row = _row(p, viewy)
    band = band_of_row(p, row)
    return band, col, (row + top_const(p, band)) & 0xFF


def check(p: Pages) -> None:
    """ASSERTED: the map fits its area, and the dot of EVERY reachable position -- the bounding box's two extreme
    columns, each row in the band the row picks -- lies on the screen, left of the legend, its run's bytes legal
    (top >= 0, top + DOT <= height: the device refuses anything else)"""
    assert 1 <= p.x0 - DOT // 2 and p.x0 + p.wpx + DOT // 2 <= p.panel_x - 1, ("the map does not fit its area", p.x0)
    assert p.hpx <= 0xFF and p.thresholds == tuple(sorted(p.thresholds)), (p.hpx, p.thresholds)
    if p.shift is None:
        recip_of(p)                    # exact over the whole extent, or refused
    for viewx in ((p.minx << 16), (p.maxx << 16) + 0xFFFF):
        _b, col, _t = dot(p, viewx, p.maxy << 16)
        assert 0 <= col and col + DOT <= p.panel_x, ("the dot leaves the map area", viewx, col)
    assert _row(p, p.miny << 16) == p.hpx - 1
    for row in range(p.hpx):
        band = band_of_row(p, row)
        top = (row + top_const(p, band)) & 0xFF
        assert 0 <= row - p.tops[band] < p.band_h, ("row %d is outside its band %d" % (row, band))
        assert top + DOT <= p.height and row + MARGIN_Y - p.tops[band] - DOT // 2 == top, (row, band, top)


def _plot_line(out, width, height, c1, r1, c2, r2, ink, top):
    """Bresenham from (c1, r1) to (c2, r2) in full-map pixels, band `top`'s rows only"""
    dc, dr = abs(c2 - c1), -abs(r2 - r1)
    sc, sr = (1 if c1 < c2 else -1), (1 if r1 < r2 else -1)
    err = dc + dr
    c, r = c1, r1
    while True:
        y = r - top + MARGIN_Y
        if MARGIN_Y <= y < height - MARGIN_Y and 0 <= c < width:
            out[y * width + c] = ink
        if c == c2 and r == r2:
            return
        e2 = 2 * err
        if e2 >= dr:
            err += dr
            c += sc
        if e2 <= dc:
            err += dc
            r += sr


def legend_rows(p: Pages) -> List[Tuple[str, str]]:
    return [(k, label) for k, label in LEGEND if k == "you" or k in p.kinds]


def _band_bitmap(p: Pages, band: int) -> list:
    """band `band`'s picture, no dot: the map's lines in their kinds' inks, the legend column, the credit"""
    ink = p.inks
    w, h = p.width, p.height
    out = [ink["background"]] * (w * h)
    for kind, c1, r1, c2, r2 in p.lines:
        _plot_line(out, w, h, c1, r1, c2, r2, ink[kind], p.tops[band])
    x = p.panel_x
    _draw(out, w, h, TITLE, x, 2, ink["title"], _GLYPHS)
    _draw(out, w, h, p.mapname, x, 2 + GLYPH_H + 3, ink["text"], _SMALL_GLYPHS)
    if p.nbands > 1:
        _draw(out, w, h, "PAGE %d/%d" % (band + 1, p.nbands), x, 2 + GLYPH_H + 3 + SMALL_GLYPH_H + 2,
              ink["credit"], _SMALL_GLYPHS)
    for i, (kind, label) in enumerate(legend_rows(p)):
        y = LEGEND_Y + i * LEGEND_PITCH
        if kind == "you":                                  # the dot itself, DOT x DOT
            for dy in range(DOT):
                for dx in range(DOT):
                    out[(y + 1 + dy) * w + x + 1 + dx] = ink["you"]
        else:                                              # a two-row stroke of the line's ink
            for dy in (2, 3):
                for dx in range(SWATCH_W):
                    out[(y + dy) * w + x + dx] = ink[kind]
        _draw(out, w, h, label, x + SWATCH_W + SWATCH_GAP, y, ink["text"], _SMALL_GLYPHS)
    _cx, cy, _cw, _ch = credit_box(w, h)
    _draw(out, w, h, CLOSE_HINT, x, cy - SMALL_GLYPH_H - 4, ink["credit"], _SMALL_GLYPHS)
    assert text_width(CLOSE_HINT, _SMALL_GLYPHS) <= PANEL_W and all(
        SWATCH_W + SWATCH_GAP + text_width(label, _SMALL_GLYPHS) <= PANEL_W for _k, label in LEGEND)
    _draw_credit(out, w, h, ink["credit"])
    return out


def band_pixels(p: Pages, band: int) -> list:
    """what the ORACLE expects of band `band` before the dot"""
    return _band_bitmap(p, band)


def pixels(p: Pages, viewx: int, viewy: int) -> list:
    """THE ORACLE's map page for a player at (viewx, viewy), 16.16: the band his row picks, the dot over it"""
    band, col, top = dot(p, viewx, viewy)
    out = _band_bitmap(p, band)
    for dx in range(DOT):
        for dy in range(DOT):
            out[(top + dy) * p.width + col + dx] = p.inks["you"]
    return out


def band_stream(p: Pages, band: int) -> bytes:
    """the 0x0B frame that paints exactly `band_pixels`, ending in END"""
    return _encode(_band_bitmap(p, band), p.width, p.height)


def decls(p: Pages) -> List[str]:
    """the page's cells: the two 8-nibble sums and the dot's bottom row -- write-before-read scratch, so the M1 reset
    need not (and does not) restore them -- and one CONSTANT per band threshold (never written). A non-power-of-two
    scale adds the offset and the two products (t+2 nibbles, scratch) and the reciprocal M (a constant)"""
    extra = []
    if p.shift is None:
        t, m = recip_of(p)
        extra = [f"am_d: hex.vec {t + 2}", f"am_px: hex.vec {t + 2}", f"am_py: hex.vec {t + 2}",
                 f"am_m: hex.vec {(m.bit_length() + 3) // 4}, {m}"]
    return (["am_x: hex.vec 8", "am_y: hex.vec 8", "am_y3: hex.vec 2"] + extra
            + [f"am_t{k}: hex.vec 2, {t}" for k, t in enumerate(p.thresholds, 1)])


def _recip_lines(p: Pages, src: str, prod: str) -> List[str]:
    """`prod`[t+2] = (the 4 integer nibbles of `src`) * M: the offset into the zeroed am_d, then one `hex.add_mul`
    per non-zero nibble j of M at nibble j of the product (its width t+2-j: the bits above are never read)"""
    t, m = recip_of(p)
    w = t + 2
    out = [f"    hex.zero {w}, am_d", f"    hex.mov 4, am_d, {src} + 4*dw", f"    hex.zero {w}, {prod}"]
    for j in range((m.bit_length() + 3) // 4):
        if (m >> (4 * j)) & 15:
            out.append(f"    hex.add_mul {w - j}, {prod} + {j}*dw, am_d, am_m + {j}*dw")
    return out


def fj_lines(p: Pages, prefix: str = "am") -> List[str]:
    """THE PROGRAM's map page -- `pixels`' mirror, the same steps: am_x = viewx + x_const and am_y = y_const - viewy
    (8 nibbles); nibbles q..q+2 of each shifted right b bits, so their low byte is the pixel; the band by comparing
    the row with each threshold; that band's baked frame (no END: the menu's shared tail ends the frame); the row
    plus the band's constant is the dot's top row; then the dot as DOT column records drawn OVER the frame --
    [x] [KEEP][top][top+DOT][ink] [END] -- KEEP leaving the frame's rows above it. `byte.emit` prints the run-time
    bytes. Ends falling through: the caller jumps to the frame's tail"""
    ink = p.inks["you"]
    head = [f"// M8 (doomfj.automap): the map page of {p.mapname} -- {p.nbands} band(s) at {p.units} units a "
            f"pixel, the dot from viewx / viewy"]
    if p.shift is not None:                    # a power-of-two scale: add, shift
        q, b = window(p)
        xw, yw = f"am_x + {q}*dw", f"am_y + {q}*dw"
        out = head + ["    hex.mov 8, am_x, viewx",
                      f"    hex.add_constant 8, am_x, {x_const(p)}",
                      *([f"    hex.shr_bit 3, {xw}"] * b),
                      f"    hex.set 8, am_y, {y_const(p)}",
                      "    hex.sub 8, am_y, viewy",
                      *([f"    hex.shr_bit 3, {yw}"] * b)]
    else:                                      # any other: the whole-unit offsets times the reciprocal
        t, _m = recip_of(p)
        xw, yw = f"am_px + {t}*dw", f"am_py + {t}*dw"
        out = head + ["    hex.mov 8, am_x, viewx",
                      f"    hex.add_constant 8, am_x, {x_base(p)}",
                      *_recip_lines(p, "am_x", "am_px"),
                      f"    hex.add_constant 2, {xw}, {p.x0 - DOT // 2}",
                      f"    hex.set 8, am_y, {y_const(p)}",
                      "    hex.sub 8, am_y, viewy",
                      *_recip_lines(p, "am_y", "am_py")]
    # the band: the first threshold the row is below picks the band before it
    for k in range(1, p.nbands):
        nxt = f"{prefix}_c{k + 1}" if k + 1 < p.nbands else f"{prefix}_b{k}"
        out += [f"    hex.cmp 2, {yw}, am_t{k}, {prefix}_b{k - 1}, {nxt}, {nxt}"]
        if k + 1 < p.nbands:
            out += [f"  {prefix}_c{k + 1}:"]
    for k in range(p.nbands):
        data = band_stream(p, k)
        assert data[-1] == END
        out += [f"  {prefix}_b{k}:",
                f"    // band {k}: {len(data) - 1} bytes of 0x0B column run-lists, all constants",
                *("    stl.output_char %d" % v for v in data[:-1]),
                *([f"    hex.add_constant 2, {yw}, {top_const(p, k)}"] if top_const(p, k) else []),
                f"    ;{prefix}_dot"]
    out += [f"  {prefix}_dot:",
            f"    hex.mov 2, am_y3, {yw}",
            f"    hex.add_constant 2, am_y3, {DOT}"]
    for c in range(DOT):
        out += [f"    byte.emit {xw}", f"    stl.output_char {KEEP}", f"    byte.emit {yw}", "    byte.emit am_y3",
                f"    stl.output_char {ink}", f"    stl.output_char {END}"]
        if c + 1 < DOT:
            out += [f"    hex.inc 2, {xw}"]
    return out
