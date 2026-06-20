"""Builds the minimal hand-built test WAD (the fast-loop R1 bring-up map, D8).

A tiny one-sector square room as PWAD map MAP01. Deterministic: re-running reproduces the exact
committed bytes of tests/fixtures/test.wad (test_wad.py asserts this). Only the editable map lumps
are emitted (THINGS/LINEDEFS/SIDEDEFS/VERTEXES/SECTORS); the BSP lumps (SEGS/SSECTORS/NODES/...) are
produced by the M7 map compiler, not hand-authored here.

Run `python tests/fixtures/make_test_wad.py` to regenerate tests/fixtures/test.wad.
"""
from __future__ import annotations
import struct
from pathlib import Path

# --- the square room geometry (the single source of the fixture's contents) ---
VERTEXES = [(0, 0), (256, 0), (256, 256), (0, 256)]
# v1, v2, flags, special, tag, front_sidedef, back_sidedef  (-1 = one-sided)
LINEDEFS = [(0, 1, 1, 0, 0, 0, -1), (1, 2, 1, 0, 0, 1, -1),
            (2, 3, 1, 0, 0, 2, -1), (3, 0, 1, 0, 0, 3, -1)]
# x_off, y_off, upper, lower, middle, sector
SIDEDEFS = [(0, 0, "-", "-", "STARTAN2", 0)] * 4
# floor_h, ceil_h, floor_tex, ceil_tex, light, special, tag
SECTORS = [(0, 128, "FLOOR4_8", "CEIL3_5", 160, 0, 0)]
# x, y, angle, type, flags  (type 1 = Player 1 start; flags 7 = easy/med/hard)
THINGS = [(128, 128, 90, 1, 7)]


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


def _sectors() -> bytes:
    return b"".join(struct.pack("<hh8s8shhh", f, c, _name8(ft), _name8(ct), li, sp, tg)
                    for (f, c, ft, ct, li, sp, tg) in SECTORS)


def build_test_wad() -> bytes:
    """Return the bytes of the minimal PWAD (header + lump data + directory)."""
    # (name, data) in DOOM map-lump order; MAP01 is the zero-size marker.
    lumps = [
        ("MAP01", b""),
        ("THINGS", _things()),
        ("LINEDEFS", _linedefs()),
        ("SIDEDEFS", _sidedefs()),
        ("VERTEXES", _vertexes()),
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


TEST_WAD = Path(__file__).with_name("test.wad")

if __name__ == "__main__":
    TEST_WAD.write_bytes(build_test_wad())
    print(f"wrote {TEST_WAD} ({TEST_WAD.stat().st_size} bytes)")
