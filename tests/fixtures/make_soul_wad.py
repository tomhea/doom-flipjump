"""M8 C8 (the lost soul): tests/fixtures/freedoom_e1m1s.wad -- a TEST map, never shipped: E1M1 (the committed fixture's
every lump, the same bytes) with its map renamed E1M1S and three lost souls (3006, every skill) added to its THINGS in
front of the player start. The soul's own maps (E1M6, E1M7) cannot build until their other clusters land; this map is
the one every soul tool runs on before then -- tests/host/test_lostsoul_model.py and tests/fj/test_lostsoul_fj.py build
it in memory, the soul gate (scratchpad/gp/soul_gate.py) and its binary from this file (`DOOMFJ_MAP=E1M1S`).

    python tests/fixtures/make_soul_wad.py            # writes tests/fixtures/freedoom_e1m1s.wad (deterministic)
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "freedoom_e1m1.wad"
DEST = HERE / "freedoom_e1m1s.wad"
MAP, NEW = "E1M1", "E1M1S"
SOULS = [(-250, 240, 180), (-200, 300, 180), (-300, 200, 180)]      # (x, y, angle): facing the start (-416, 256)
SOUL_TYPE, EVERY_SKILL = 3006, 7


def soul_bytes(src: bytes = None, souls=SOULS) -> bytes:
    """the fixture's bytes with the map renamed and the souls appended to its THINGS"""
    data = src if src is not None else SRC.read_bytes()
    magic = data[:4]
    n, dirofs = struct.unpack_from("<ii", data, 4)
    entries = [list(struct.unpack_from("<ii8s", data, dirofs + 16 * i)) for i in range(n)]
    lumps = [(e[2].rstrip(b"\0").decode("ascii"), data[e[0]:e[0] + e[1]]) for e in entries]
    out, in_map, done = [], False, False
    for name, body in lumps:
        if name == MAP:
            name, in_map = NEW, True
        elif in_map and name == "THINGS" and not done:
            body = body + b"".join(struct.pack("<5h", x, y, a, SOUL_TYPE, EVERY_SKILL) for x, y, a in souls)
            done = True
        out.append((name, body))
    assert done, "no THINGS lump after %s" % MAP
    blob, table, pos = bytearray(), [], 12
    for name, body in out:
        table.append(struct.pack("<ii8s", pos, len(body), name.encode("ascii").ljust(8, b"\0")))
        blob += body
        pos += len(body)
    return magic + struct.pack("<ii", len(out), pos) + bytes(blob) + b"".join(table)


def main() -> int:
    DEST.write_bytes(soul_bytes())
    print("wrote %s (%d bytes)" % (DEST, DEST.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
