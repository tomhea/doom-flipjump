"""M8 C6 (the plasma rifle): E1M1 WITH A PLASMA RIFLE -- the test vehicle of the rifle's model and fj harnesses until a
real plasma map (E1M6, E1M9) can be built (both are refused by the runtime-id count, cluster C1). The base wad's E1M1
THINGS lump gains PLASMA_THINGS (every skill, single player), every other lump is the base's own bytes, so the map is
E1M1 with three more pickups -- and `combat.plasma_on` is true on it: key 6, `kb_w6`, the rifle's psprites and its
ball's sprites exist there, as on E1M6 / E1M9."""
import struct

from doomfj.wad import Lump, WadFile

# (x, y, angle, type): the rifle 64 units ahead of the player start (-416, 256, facing east), an energy cell and a cell
# pack beside it
PLASMA_THINGS = ((-352, 256, 0, 2004), (-352, 320, 0, 2047), (-352, 192, 0, 17))
SKILLS_ALL = 7                                  # MTF_EASY | MTF_NORMAL | MTF_HARD, single player


def plasma_e1m1(base: WadFile = None, mapname: str = "E1M1", things=PLASMA_THINGS) -> WadFile:
    """`base` (default: config.DEFAULT_MAP_WAD) with `things` appended to `mapname`'s THINGS lump"""
    if base is None:
        from doomfj.config import DEFAULT_MAP_WAD
        base = WadFile.from_path(DEFAULT_MAP_WAD)
    names = base.names()
    at = names.index(mapname) + names[names.index(mapname):].index("THINGS")
    lumps = list(base._lumps)
    old = lumps[at]
    data = old.data + b"".join(struct.pack("<hhhhh", x, y, a, ty, SKILLS_ALL) for x, y, a, ty in things)
    lumps[at] = Lump(old.name, old.offset, len(data), data)
    return WadFile(base.wad_type, lumps)


def write_wad(wad: WadFile, path) -> None:
    """`wad` as a WAD file at `path` (its lumps in order, then the directory) -- for a build that takes a wad PATH"""
    from pathlib import Path
    body, dirs, off = bytearray(), [], 12
    for lump in wad._lumps:
        dirs.append(struct.pack("<ii8s", off + len(body), len(lump.data), lump.name.encode("ascii")))
        body += lump.data
    head = struct.pack("<4sii", wad.wad_type.encode("ascii"), len(dirs), 12 + len(body))
    Path(path).write_bytes(head + bytes(body) + b"".join(dirs))
