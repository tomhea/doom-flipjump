"""Build the committed graphics fixture tests/fixtures/freedoom_assets.wad by TRIMMING Freedoom
(BSD-licensed, redistributable — D8). A tiny, deterministic subset for the M8 texture compiler:
the game palette + the full COLORMAP + two textures (A-YELLOW 16x8 single-patch, STEP4 32x16
two-patch — exercises compositing) + their patches + two flats. PNAMES/TEXTURE1 are re-indexed to
the trimmed patch set.

Requires the dev Freedoom WAD (gitignored): `bash scripts/fetch_freedoom.sh` first. Re-run
`python tests/fixtures/make_assets_wad.py` to regenerate the fixture. The COMMITTED fixture is the
artifact the tests read (test_texturecompiler.py); it is not rebuilt in CI because Freedoom is not
committed. The fixture + tests/fixtures/FREEDOOM_LICENSE keep us redistributable; the full Freedoom
WAD is never committed.
"""
from __future__ import annotations
import struct
from pathlib import Path

from doomfj.wad import WadFile

SRC = Path("assets/freedoom1.wad")
DEST = Path(__file__).with_name("freedoom_assets.wad")
TEXTURES = ["A-YELLOW", "STEP4"]   # single-patch + two-patch (composite)
FLATS = ["CEIL1_2", "FLOOR4_8"]    # two 64x64 flats


def _name8(s: str) -> bytes:
    return s.encode("ascii").ljust(8, b"\x00")[:8]


def _build_texture1(defs, new_pnames: list[str]) -> bytes:
    """Re-encode chosen texture defs into a TEXTURE1 lump, remapping patch refs to new_pnames order."""
    idx = {n: i for i, n in enumerate(new_pnames)}
    bodies = []
    for d in defs:
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


def build_assets_wad(src_path=SRC) -> bytes:
    w = WadFile.from_path(src_path)
    defs = {d.name: d for d in w.texture_defs()}
    chosen = [defs[t] for t in TEXTURES]
    patch_names: list[str] = []
    for d in chosen:
        for pr in d.patches:
            if pr.patch not in patch_names:
                patch_names.append(pr.patch)

    lumps: list[tuple[str, bytes]] = [
        ("PLAYPAL", w.get_data("PLAYPAL")[:768]),       # one palette (the game palette)
        ("COLORMAP", w.get_data("COLORMAP")),           # full light tables
        ("PNAMES", struct.pack("<i", len(patch_names)) + b"".join(_name8(n) for n in patch_names)),
        ("TEXTURE1", _build_texture1(chosen, patch_names)),
        ("P_START", b""),
        *[(n, w.get_data(n)) for n in patch_names],
        ("P_END", b""),
        ("F_START", b""),
        *[(n, w.flat(n)) for n in FLATS],
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
    DEST.write_bytes(build_assets_wad())
    print(f"wrote {DEST} ({DEST.stat().st_size} bytes; trimmed from {SRC})")
