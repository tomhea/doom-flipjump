"""M8 (the episode): a map's WAD with some THINGS left out, in memory -- the test worlds of features that a map needs
before the rest of that map is supported (C5's monster teleports on E1M4..E1M7, C10's barrel-less map), and E1M1
WITHOUT its barrels (C10: the zero-barrel case on a map every gate knows).

`without_things(wad, mapname, drop)` rewrites only that map's THINGS lump (every other lump, and every other map,
the same bytes); `drop(index, (x, y, angle, type, flags))` says which records go. `episode_wad(wad, mapname)` drops
the thing types gamedata does not know YET (they arrive with other clusters: a type known later is kept, so the world
grows into the real map) and the monsters past `max_monsters` in WAD order (the leaf lists hold a byte of mobiles
until C1's rung) -- a measurement world for one feature's rule, never a certified map.
"""
from __future__ import annotations

import struct

from doomfj import gamedata as gd
from doomfj.wad import Lump, WadFile

ART = "assets/freedoom1.wad"
BARREL = 2035


def without_things(wad: WadFile, mapname: str, drop) -> WadFile:
    names = wad.names()
    start = names.index(mapname)
    lumps = list(wad._lumps)
    for i in range(start + 1, len(lumps)):
        if lumps[i].name == "THINGS":
            d = lumps[i].data
            recs = [d[k:k + 10] for k in range(0, len(d), 10)]
            keep = b"".join(r for k, r in enumerate(recs) if not drop(k, struct.unpack("<5h", r)))
            lumps[i] = Lump("THINGS", 0, len(keep), keep)
            return WadFile(wad.wad_type, lumps)
    raise KeyError("no THINGS for %s" % mapname)


def no_barrels(wad: WadFile, mapname: str) -> WadFile:
    """the map with every barrel (2035) left out"""
    return without_things(wad, mapname, lambda _k, t: t[3] == BARREL)


def episode_wad(wad: WadFile, mapname: str, max_monsters: int = 200) -> WadFile:
    """the thing types gamedata lacks left out, and the monsters past `max_monsters` (in WAD order)"""
    unknown = {t.type for t in wad.things(mapname)} - set(gd.THING_TYPES) - set(gd.NOT_THINGS)
    seen = []

    def drop(_k, t):
        if t[3] in unknown:
            return True
        if t[3] in gd.MONSTER_DOOMEDNUMS:
            seen.append(t)
            return len(seen) > max_monsters
        return False
    return without_things(wad, mapname, drop)
