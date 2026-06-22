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


@dataclass(frozen=True)
class WadSeg:
    """A raw SEGS record (the WAD's precompiled BSP segs, baked by the level's node tool)."""
    v1: int          # start vertex index
    v2: int          # end vertex index
    angle: int       # BAM >> 16 (0..0xFFFF), direction v1->v2
    linedef: int     # source linedef index
    direction: int   # 0 = seg runs with the linedef (front), 1 = against it (back)
    offset: int      # distance along the linedef from its start to this seg's start


@dataclass(frozen=True)
class WadSubSector:
    """A raw SSECTORS record: a run of segs forming one convex leaf."""
    numsegs: int
    firstseg: int    # index into the SEGS lump


@dataclass(frozen=True)
class WadNode:
    """A raw NODES record (the partition line + two children; the bounding boxes are skipped).
    A child ref with the 0x8000 bit set points to a subsector (low 15 bits), else a node index."""
    x: int           # partition line start
    y: int
    dx: int          # partition line direction
    dy: int
    right: int       # right (front) child ref
    left: int        # left (back) child ref


@dataclass(frozen=True)
class PatchRef:
    originx: int      # placement of the patch within the texture
    originy: int
    patch: str        # PNAMES patch lump name


@dataclass(frozen=True)
class TextureDef:
    name: str
    width: int
    height: int
    patches: tuple    # tuple[PatchRef, ...]


@dataclass(frozen=True)
class Picture:
    """A decoded DOOM picture (patch/sprite): column-major, with transparency. `columns[x]` is a list
    of (y, palette_index) for the opaque pixels of column x (gaps are transparent)."""
    width: int
    height: int
    leftoffset: int
    topoffset: int
    columns: tuple    # tuple[list[tuple[int, int]], ...], one per column


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

    # ── baked BSP lumps (SEGS/SSECTORS/NODES) — the level's precompiled node tree (H3 bake) ──
    def segs(self, mapname: str) -> list[WadSeg]:
        """The SEGS lump: 12 bytes each (v1, v2, angle, linedef, direction, offset), all uint16."""
        return [WadSeg(*r) for r in _records(self._map_lump(mapname, "SEGS").data, "<6H")]

    def subsectors(self, mapname: str) -> list[WadSubSector]:
        """The SSECTORS lump: 4 bytes each (numsegs, firstseg), uint16."""
        return [WadSubSector(*r) for r in _records(self._map_lump(mapname, "SSECTORS").data, "<2H")]

    def nodes(self, mapname: str) -> list[WadNode]:
        """The NODES lump: 28 bytes each — partition line (x, y, dx, dy: int16), two 4-int16 child
        bounding boxes (skipped), then right/left child refs (uint16, 0x8000 bit = subsector)."""
        data = self._map_lump(mapname, "NODES").data
        out = []
        for off in range(0, len(data) - len(data) % 28, 28):
            x, y, dx, dy = struct.unpack_from("<4h", data, off)
            right, left = struct.unpack_from("<2H", data, off + 24)
            out.append(WadNode(x, y, dx, dy, right, left))
        return out

    # ── graphics lumps (H4 / M8): palette, colormap, textures, patches, flats ──
    def playpal(self, index: int = 0) -> list[tuple[int, int, int]]:
        """One 256-colour RGB palette (PLAYPAL holds 14; index 0 is the game palette)."""
        data = self.get_data("PLAYPAL")
        base = index * 768
        return [(data[base + i * 3], data[base + i * 3 + 1], data[base + i * 3 + 2]) for i in range(256)]

    def colormap(self) -> list[list[int]]:
        """The COLORMAP light tables: a list of maps (34 in DOOM/Freedoom: 32 light levels + invuln +
        all-black); map[i] = the palette index to display for colour i at that light level."""
        data = self.get_data("COLORMAP")
        return [list(data[m * 256:(m + 1) * 256]) for m in range(len(data) // 256)]

    def pnames(self) -> list[str]:
        """The PNAMES patch-name directory (texture patches are referenced by index into this)."""
        data = self.get_data("PNAMES")
        n = struct.unpack_from("<i", data, 0)[0]
        return [_str8(data[4 + i * 8:12 + i * 8]) for i in range(n)]

    def texture_defs(self, lump: str = "TEXTURE1") -> list[TextureDef]:
        """Parse a TEXTUREx lump into texture definitions (name, size, composing patches)."""
        data = self.get_data(lump)
        names = self.pnames()
        count = struct.unpack_from("<i", data, 0)[0]
        offsets = struct.unpack_from(f"<{count}i", data, 4)
        defs: list[TextureDef] = []
        for off in offsets:
            name = _str8(data[off:off + 8])
            _masked, width, height, _coldir, npatch = struct.unpack_from("<ihhih", data, off + 8)
            patches = []
            for p in range(npatch):
                ox, oy, pidx, _step, _cmap = struct.unpack_from("<5h", data, off + 22 + p * 10)
                patches.append(PatchRef(ox, oy, names[pidx]))
            defs.append(TextureDef(name, width, height, tuple(patches)))
        return defs

    def lumps_between(self, start: str, end: str) -> list[Lump]:
        """Lumps strictly between two marker lumps (e.g. F_START/F_END for flats, P_START/P_END)."""
        names = self.names()
        s, e = names.index(start), names.index(end)
        return self._lumps[s + 1:e]

    def flat(self, name: str) -> bytes:
        """A flat (floor/ceiling tile): raw 64x64 palette-index bytes, row-major (no header)."""
        return self.get_data(name)


def decode_picture(data: bytes) -> Picture:
    """Decode the DOOM picture (patch) format: header (w, h, left, top) + per-column posts. Each post
    is topdelta/length/pad + `length` palette-index bytes + pad; 0xFF topdelta ends a column. Gaps
    between posts are transparent."""
    width, height, left, top = struct.unpack_from("<4h", data, 0)
    col_offs = struct.unpack_from(f"<{width}i", data, 8)
    columns = []
    for x in range(width):
        pixels = []
        pos = col_offs[x]
        while data[pos] != 0xFF:
            topdelta = data[pos]
            length = data[pos + 1]
            pos += 3  # topdelta, length, unused pad
            for i in range(length):
                pixels.append((topdelta + i, data[pos + i]))
            pos += length + 1  # pixels + trailing unused pad
        columns.append(pixels)
    return Picture(width, height, left, top, tuple(columns))
