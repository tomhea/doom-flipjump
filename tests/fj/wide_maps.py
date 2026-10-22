"""M8 C2 (docs/c2-slot-ids.md): the maps the slot-id harnesses run on -- E1M1 (75 monster + barrel slots: two-nibble
ids, the text every narrow map keeps) and, when the full episode wad is present, E1M6 (294 monster slots -- its 3 lost
souls among them -- + 7 barrels: THREE-nibble slot ids, world.slot_nibbles 3).

`map_world(mapname, **kw)` is the World the harness's model runs: E1M1 from the default wad, E1M6 from the asset wad.
An fj harness on E1M6 is a HEAVY job (scripts/heavy.py; docs/episode-agent-brief.md rule 1)."""
from pathlib import Path

from doomfj.world import World, slot_nibbles

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "freedoom1.wad"
WIDE_MAP = "E1M6"
MAPS = ("E1M1",) + ((WIDE_MAP,) if ASSET.exists() else ())

_CACHE = {}


def map_world(mapname: str = "E1M1", **kw) -> World:
    """a fresh World of `mapname` (E1M6 from assets/freedoom1.wad); its slot ids are three nibbles exactly when the
    map is the wide one (asserted: a harness meant to run past the byte must not silently run narrow)"""
    if mapname == "E1M1":
        w = World(mapname=mapname, **kw)
    else:
        from doomfj.wad import WadFile
        if "wad" not in _CACHE:
            _CACHE["wad"] = WadFile.from_path(str(ASSET))
        w = World(_CACHE["wad"], mapname, **kw)
    assert slot_nibbles(w.layout) == (3 if mapname == WIDE_MAP else 2), (mapname, w.layout.nmon, w.layout.nbarrel)
    return w
