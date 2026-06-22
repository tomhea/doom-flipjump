"""Builds the pre-baked test room fixture tests/fixtures/square_room.wad (M12i).

A tiny one-sector 256x256 square room (same geometry/sector/spawn as the M3 test.wad) but wound the
DOOM-standard way — each one-sided linedef has the sector on its RIGHT (front) side — and carrying the
**baked** BSP lumps (SEGS/SSECTORS/NODES). Real DOOM levels ship the node tree precomputed; hand-built
WADs do not, so we pre-bake this trivial convex room once and commit it (the bake path / projection
oracle is exercised on real DOOM-wound data, with no winding patches). The room is convex ⇒ one
subsector, four segs, zero nodes; the root child ref is `0x8000` (subsector 0).

Deterministic: re-running reproduces the exact committed bytes (test_square_room_wad asserts this).
Run `python tests/fixtures/make_square_room_wad.py` to regenerate.
"""
from __future__ import annotations
import struct
from pathlib import Path

# Vertices A,B,C,D of the 256x256 square (indices 0..3).
VERTEXES = [(0, 0), (256, 0), (256, 256), (0, 256)]
# CLOCKWISE boundary A->D->C->B->A ⇒ the interior (centre 128,128) is on the RIGHT (front) of each
# directed one-sided linedef (DOOM's standard winding). v1, v2, flags, special, tag, front_sd, back_sd.
LINEDEFS = [(0, 3, 1, 0, 0, 0, -1),   # WEST  wall x=0,    pointing north
            (3, 2, 1, 0, 0, 1, -1),   # NORTH wall y=256,  pointing east
            (2, 1, 1, 0, 0, 2, -1),   # EAST  wall x=256,  pointing south
            (1, 0, 1, 0, 0, 3, -1)]   # SOUTH wall y=0,    pointing west
# x_off, y_off, upper, lower, middle, sector
SIDEDEFS = [(0, 0, "-", "-", "STARTAN2", 0)] * 4
# floor_h, ceil_h, floor_tex, ceil_tex, light, special, tag
SECTORS = [(0, 128, "FLOOR4_8", "CEIL3_5", 160, 0, 0)]
# x, y, angle, type, flags  (type 1 = Player 1 start; flags 7 = easy/med/hard)
THINGS = [(128, 128, 90, 1, 7)]

# The baked BSP (hand-authored: the room is convex, so the node tool would emit exactly this).
# v1, v2, angle(BAM>>16), linedef, direction(0=front), offset — one seg per one-sided linedef.
SEGS = [(0, 3, 0x4000, 0, 0, 0),   # west wall, dir north
        (3, 2, 0x0000, 1, 0, 0),   # north wall, dir east
        (2, 1, 0xC000, 2, 0, 0),   # east wall, dir south
        (1, 0, 0x8000, 3, 0, 0)]   # south wall, dir west
SUBSECTORS = [(4, 0)]              # one subsector: 4 segs from seg 0
NODES: list[tuple] = []           # convex ⇒ no partition nodes (root = subsector 0 = 0x8000)


def _name8(s: str) -> bytes:
    return s.encode("ascii").ljust(8, b"\x00")[:8]


def _things() -> bytes:
    return b"".join(struct.pack("<5h", *t) for t in THINGS)


def _linedefs() -> bytes:
    return b"".join(struct.pack("<7h", *l) for l in LINEDEFS)


def _sidedefs() -> bytes:
    return b"".join(struct.pack("<hh8s8s8sh", x, y, _name8(u), _name8(lo), _name8(m), sec)
                    for (x, y, u, lo, m, sec) in SIDEDEFS)


def _vertexes() -> bytes:
    return b"".join(struct.pack("<2h", x, y) for (x, y) in VERTEXES)


def _segs() -> bytes:
    return b"".join(struct.pack("<6H", *s) for s in SEGS)


def _ssectors() -> bytes:
    return b"".join(struct.pack("<2H", *s) for s in SUBSECTORS)


def _nodes() -> bytes:
    return b"".join(struct.pack("<4h8hHH", *n) for n in NODES)


def _sectors() -> bytes:
    return b"".join(struct.pack("<hh8s8shhh", f, c, _name8(ft), _name8(ct), li, sp, tg)
                    for (f, c, ft, ct, li, sp, tg) in SECTORS)


def build_square_room_wad() -> bytes:
    """Return the bytes of the pre-baked PWAD (header + lump data + directory)."""
    # DOOM map-lump order; MAP01 is the zero-size marker. SEGS/SSECTORS/NODES are baked.
    lumps = [
        ("MAP01", b""),
        ("THINGS", _things()),
        ("LINEDEFS", _linedefs()),
        ("SIDEDEFS", _sidedefs()),
        ("VERTEXES", _vertexes()),
        ("SEGS", _segs()),
        ("SSECTORS", _ssectors()),
        ("NODES", _nodes()),
        ("SECTORS", _sectors()),
    ]
    header_size = 12
    blob = b"".join(data for _, data in lumps)
    directory = bytearray()
    offset = header_size
    for name, data in lumps:
        directory += struct.pack("<ii8s", offset, len(data), _name8(name))
        offset += len(data)
    infotableofs = header_size + len(blob)
    header = b"PWAD" + struct.pack("<ii", len(lumps), infotableofs)
    return header + blob + bytes(directory)


SQUARE_ROOM_WAD = Path(__file__).with_name("square_room.wad")

if __name__ == "__main__":
    SQUARE_ROOM_WAD.write_bytes(build_square_room_wad())
    print(f"wrote {SQUARE_ROOM_WAD} ({SQUARE_ROOM_WAD.stat().st_size} bytes)")
