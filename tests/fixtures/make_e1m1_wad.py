"""Build the committed fixture tests/fixtures/freedoom_e1m1.wad: the FULL E1M1 level (geometry +
every texture/flat it references + palette + colormap) trimmed from Freedoom (BSD, redistributable —
D8, option B / R0). This is the M10 R0-gate input: the real E1M1 asset footprint, reproducible in CI
without the multi-MB dev Freedoom WAD.

E1M1 references textures spanning BOTH TEXTURE1 and TEXTURE2 (DOOM splits them); they are merged into
one re-indexed TEXTURE1 here so the single-lump texturecompiler/wad path keeps working. The committed
fixture stores full-resolution source art — the 2x D5 downscale (owner decision, R0) happens at compile
time, not in the fixture.

Requires the dev Freedoom WAD (gitignored): `bash scripts/fetch_freedoom.sh` first. Re-run
`python tests/fixtures/make_e1m1_wad.py` to regenerate. The full Freedoom WAD is never committed; the
fixture + tests/fixtures/FREEDOOM_LICENSE keep us redistributable.
"""
from __future__ import annotations
import struct
from pathlib import Path

from doomfj.wad import WadFile

SRC = Path("assets/freedoom1.wad")
DEST = Path(__file__).with_name("freedoom_e1m1.wad")
MAP = "E1M1"
MAP_LUMPS = ["THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SECTORS"]  # we build the BSP ourselves (M7)


def _name8(s: str) -> bytes:
    return s.encode("ascii").ljust(8, b"\x00")[:8]


def _merged_texture_defs(w: WadFile) -> dict:
    """All texture defs across TEXTURE1 + TEXTURE2, keyed by upper-case name (TEXTURE1 wins on a tie)."""
    defs = {}
    for lump in ("TEXTURE1", "TEXTURE2"):
        if lump in w.names():
            for d in w.texture_defs(lump):
                defs.setdefault(d.name.upper(), d)
    return defs


def _e1m1_assets(w: WadFile):
    """The distinct wall textures, flats, and patches E1M1 actually references."""
    defs = _merged_texture_defs(w)
    walls = []
    for s in w.sidedefs(MAP):
        for t in (s.upper, s.lower, s.middle):
            u = t.upper()
            if u and u != "-" and u in defs and u not in walls:
                walls.append(u)
    flats = []
    for s in w.sectors(MAP):
        for f in (s.floor_tex, s.ceil_tex):
            u = f.upper()
            if u and u != "-" and u != "F_SKY1" and u not in flats:
                flats.append(u)
    patches = []
    for name in walls:
        for pr in defs[name].patches:
            if pr.patch not in patches:
                patches.append(pr.patch)
    return defs, walls, flats, patches


def _build_texture1(defs, walls, new_pnames: list[str]) -> bytes:
    """Re-encode the chosen texture defs into one TEXTURE1 lump, remapping patch refs to new_pnames."""
    idx = {n: i for i, n in enumerate(new_pnames)}
    bodies = []
    for name in walls:
        d = defs[name]
        b = _name8(d.name) + struct.pack("<ihhih", 0, d.width, d.height, 0, len(d.patches))
        for pr in d.patches:
            b += struct.pack("<5h", pr.originx, pr.originy, idx[pr.patch], 0, 0)
        bodies.append(b)
    header_len = 4 + 4 * len(bodies)
    offsets, pos = [], header_len
    for b in bodies:
        offsets.append(pos)
        pos += len(b)
    return struct.pack("<i", len(bodies)) + struct.pack(f"<{len(bodies)}i", *offsets) + b"".join(bodies)


def build_e1m1_wad(src_path=SRC) -> bytes:
    w = WadFile.from_path(src_path)
    defs, walls, flats, patches = _e1m1_assets(w)

    lumps: list[tuple[str, bytes]] = [
        (MAP, b""),  # map marker
        *[(n, w._map_lump(MAP, n).data) for n in MAP_LUMPS],
        ("PLAYPAL", w.get_data("PLAYPAL")[:768]),   # the game palette
        ("COLORMAP", w.get_data("COLORMAP")),       # full light tables
        ("PNAMES", struct.pack("<i", len(patches)) + b"".join(_name8(n) for n in patches)),
        ("TEXTURE1", _build_texture1(defs, walls, patches)),
        ("P_START", b""),
        *[(n, w.get_data(n)) for n in patches],
        ("P_END", b""),
        ("F_START", b""),
        *[(n, w.flat(n)) for n in flats],
        ("F_END", b""),
    ]
    header_size = 12
    blob = b"".join(d for _, d in lumps)
    directory = bytearray()
    offset = header_size
    for name, data in lumps:
        directory += struct.pack("<ii8s", offset, len(data), _name8(name))
        offset += len(data)
    infotableofs = header_size + len(blob)
    return b"PWAD" + struct.pack("<ii", len(lumps), infotableofs) + blob + bytes(directory)


if __name__ == "__main__":
    DEST.write_bytes(build_e1m1_wad())
    _w = WadFile.from_path(DEST)
    _defs, _walls, _flats, _patches = _e1m1_assets(WadFile.from_path(SRC))
    print(f"wrote {DEST} ({DEST.stat().st_size} bytes; {len(_walls)} textures, "
          f"{len(_flats)} flats, {len(_patches)} patches, trimmed from {SRC})")
