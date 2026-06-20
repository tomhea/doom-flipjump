"""H1 — WAD parser.

Reads the IWAD/PWAD container (12-byte header + 16-byte-per-entry lump directory) and exposes raw
lumps plus typed DOOM map records (VERTEXES/LINEDEFS/SIDEDEFS/SECTORS/THINGS). Map lumps are
positional: a map marker (ExMy / MAPxx, size 0) is followed by its component lumps, so the typed
accessors take a map name and scope the search to that map's block. Texture/colormap/palette
accessors land at M8; this is the container + map-geometry bring-up (S5.2 / H1).
"""
from __future__ import annotations
import re
import struct
from dataclasses import dataclass
from pathlib import Path

_MAP_MARKER = re.compile(r"^(E\dM\d|MAP\d\d)$")


def _str8(raw: bytes) -> str:
    """Decode an 8-byte null-padded lump/texture name."""
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace")


@dataclass(frozen=True)
class Lump:
    name: str
    offset: int
    size: int
    data: bytes


@dataclass(frozen=True)
class Vertex:
    x: int
    y: int


@dataclass(frozen=True)
class Linedef:
    v1: int
    v2: int
    flags: int
    special: int
    tag: int
    front: int
    back: int


@dataclass(frozen=True)
class Sidedef:
    x_off: int
    y_off: int
    upper: str
    lower: str
    middle: str
    sector: int


@dataclass(frozen=True)
class Sector:
    floor_h: int
    ceil_h: int
    floor_tex: str
    ceil_tex: str
    light: int
    special: int
    tag: int


@dataclass(frozen=True)
class Thing:
    x: int
    y: int
    angle: int
    type: int
    flags: int


def _records(data: bytes, fmt: str):
    """Yield struct-unpacked tuples for each fixed-size record packed in data."""
    size = struct.calcsize(fmt)
    for off in range(0, len(data) - len(data) % size, size):
        yield struct.unpack_from(fmt, data, off)


class WadFile:
    def __init__(self, wad_type: str, lumps: list[Lump]):
        self.wad_type = wad_type
        self._lumps = lumps

    # ── container ──
    @classmethod
    def from_bytes(cls, data: bytes) -> "WadFile":
        if len(data) < 12:
            raise ValueError("not a WAD: file shorter than the 12-byte header")
        magic = data[:4].decode("ascii", "replace")
        if magic not in ("IWAD", "PWAD"):
            raise ValueError(f"not a WAD: bad magic {magic!r} (expected IWAD/PWAD)")
        numlumps, infotableofs = struct.unpack_from("<ii", data, 4)
        lumps: list[Lump] = []
        for i in range(numlumps):
            filepos, size, name = struct.unpack_from("<ii8s", data, infotableofs + i * 16)
            lumps.append(Lump(_str8(name), filepos, size, data[filepos:filepos + size]))
        return cls(magic, lumps)

    @classmethod
    def from_path(cls, path) -> "WadFile":
        return cls.from_bytes(Path(path).read_bytes())

    def __len__(self) -> int:
        return len(self._lumps)

    def names(self) -> list[str]:
        return [lump.name for lump in self._lumps]

    def get(self, name: str) -> Lump:
        for lump in self._lumps:
            if lump.name == name:
                return lump
        raise KeyError(name)

    def get_data(self, name: str) -> bytes:
        return self.get(name).data

    # ── map-scoped lump lookup ──
    def _map_lump(self, mapname: str, name: str) -> Lump:
        """Return the `name` lump belonging to map `mapname` (positional: after the marker,
        before the next map marker)."""
        names = self.names()
        try:
            start = names.index(mapname)
        except ValueError as exc:
            raise KeyError(f"no such map marker {mapname!r}") from exc
        for lump in self._lumps[start + 1:]:
            if _MAP_MARKER.match(lump.name):
                break  # reached the next map; not found in this one
            if lump.name == name:
                return lump
        raise KeyError(f"{name!r} not found in map {mapname!r}")

    # ── typed map records ──
    def vertexes(self, mapname: str) -> list[Vertex]:
        return [Vertex(*r) for r in _records(self._map_lump(mapname, "VERTEXES").data, "<2h")]

    def linedefs(self, mapname: str) -> list[Linedef]:
        return [Linedef(*r) for r in _records(self._map_lump(mapname, "LINEDEFS").data, "<7h")]

    def sidedefs(self, mapname: str) -> list[Sidedef]:
        out = []
        for x, y, up, lo, mid, sec in _records(self._map_lump(mapname, "SIDEDEFS").data, "<hh8s8s8sh"):
            out.append(Sidedef(x, y, _str8(up), _str8(lo), _str8(mid), sec))
        return out

    def sectors(self, mapname: str) -> list[Sector]:
        out = []
        for f, c, ft, ct, li, sp, tg in _records(self._map_lump(mapname, "SECTORS").data, "<hh8s8shhh"):
            out.append(Sector(f, c, _str8(ft), _str8(ct), li, sp, tg))
        return out

    def things(self, mapname: str) -> list[Thing]:
        return [Thing(*r) for r in _records(self._map_lump(mapname, "THINGS").data, "<5h")]
