"""P11 (a) -- THE EXIT SIGN (the owner, 2026-10-12: make the exit switch "super clear that it's exit"; option (a), a
floating EXIT sign in DOOM's red, chosen 2026-10-13).

A VIRTUAL decoration: `WadFile.things` appends it after the THINGS lump's own things, so no wad index moves, and
only when the map's exit line is the one it was placed against (`EXIT_SIGNS`: the linedef index, its special and
its two vertexes) -- another wad's map of the same name gets none. Everything that draws things sees it through that
one list (the oracle, the emitter's sprite bank and leaf lists, the node builder's thing boxes); the WORLD drops its
type (`gamedata.NOT_THINGS`), so it is neither solid nor a pickup, and the seen / aim rules never consider it (a
decoration).

WHERE (Freedoom's E1M1): the exit switch is the back wall of a 32-wide, 16-deep alcove (sector 67, floor -120,
ceiling -56) that opens east into the exit room (sector 66, floor -128, ceiling 8) at x = -384. The sign hangs in
the room 4 units in front of that opening, centred on it (y 1296), its lower edge 2 units above the alcove's ceiling
-- an EXIT sign over a door, DOOM's own convention (its EXITSIGN texture sits over exit doors). Inside the alcove it
would be drawn over the alcove's side walls seen at an angle: a thing beats the walls of its own leaf here.

THE PICTURE is built, not read from a wad: Freedoom's EXITSIGN texture is a running man beside 5-row letters, which
the sprite bank's 2:1 column sampling (`ReferenceModel.downscale`) and the low tiers' 2:1 rows would erase at the
game's 160x84 view. So the word is a 5x7 font drawn at TWICE its size -- each font pixel 2x2 -- in PLAYPAL's pure
red on a dark plate inside a lighter rim: 48 x 20 map units (a sprite pixel is one).
"""
from __future__ import annotations

from doomfj.gamedata import EXIT_SIGN_TYPE
from doomfj.reference_model import DRAW_ACTOR_TYPES
from doomfj.wad import Picture, Thing

assert EXIT_SIGN_TYPE in DRAW_ACTOR_TYPES, "the sign is drawn in the actor class"

RED, PLATE, RIM = 176, 108, 100            # PLAYPAL: (255, 0, 0), (55, 55, 55), (107, 107, 107)
SCALE, PAD = 3, 2                          # each font pixel SCALE x SCALE; PAD plate pixels inside the rim
WORD = "EXIT"
FONT = {                                   # 5x7 (I: 3x7), '#' = a letter pixel
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "X": ("#...#", "##.##", ".###.", "..#..", ".###.", "##.##", "#...#"),   # bold diagonals: 2:1 sampling thins them
    "I": ("###", ".#.", ".#.", ".#.", ".#.", ".#.", "###"),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
}
GAP = 1                                    # font columns between letters

# map -> (exit linedef, its special, its v1, its v2, the sign's (x, y), the sign's floor, the opening's top): the
# geometry the sign was placed against -- `virtual_things` checks the first four and `exit_sign_picture`'s top
# offset is derived from the last two (the room's floor, the alcove's ceiling)
EXIT_SIGNS = {"E1M1": (407, 11, (-400, 1280), (-400, 1312), (-380, 1296), -128, -56)}
LIFT = 2                                   # map units between the opening's top and the sign's lower edge


def sign_grid() -> list:
    """the picture's rows: palette indices, rim / plate / red letters"""
    cols = sum(len(FONT[c][0]) for c in WORD) + GAP * (len(WORD) - 1)
    w, h = cols * SCALE + 2 * (PAD + 1), 7 * SCALE + 2 * (PAD + 1)
    grid = [[PLATE] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if y in (0, h - 1) or x in (0, w - 1):
                grid[y][x] = RIM
    fx = 0
    for c in WORD:
        glyph = FONT[c]
        for gy, row in enumerate(glyph):
            for gx, ch in enumerate(row):
                if ch == "#":
                    for dy in range(SCALE):
                        for dx in range(SCALE):
                            grid[1 + PAD + gy * SCALE + dy][1 + PAD + (fx + gx) * SCALE + dx] = RED
        fx += len(glyph[0]) + GAP
    return grid


def exit_sign_picture(mapname: str = "E1M1") -> Picture:
    """the sign as a DOOM picture: centred on its thing (left offset w // 2), its TOP `LIFT` + its height above the
    alcove's ceiling, measured from the floor its thing stands on (the top offset)"""
    grid = sign_grid()
    h, w = len(grid), len(grid[0])
    *_, floor, opening_top = EXIT_SIGNS[mapname.upper()]
    top = opening_top + LIFT + h - floor
    return Picture(w, h, w // 2, top, tuple([(y, grid[y][x]) for y in range(h)] for x in range(w)))


def virtual_things(wad, mapname: str) -> list:
    """the virtual things `WadFile.things` appends for this map: the EXIT sign when the exit line is the one it was
    placed against, else none"""
    spec = EXIT_SIGNS.get(mapname.upper())
    if spec is None:
        return []
    li, special, a, b, at, _floor, _top = spec
    lds, vs = wad.linedefs(mapname), wad.vertexes(mapname)
    if li >= len(lds):
        return []
    ld = lds[li]
    if (ld.special, (vs[ld.v1].x, vs[ld.v1].y), (vs[ld.v2].x, vs[ld.v2].y)) != (special, a, b):
        return []
    return [Thing(at[0], at[1], 0, EXIT_SIGN_TYPE, 7)]       # every skill (MTF_EASY | NORMAL | HARD), not MP-only
