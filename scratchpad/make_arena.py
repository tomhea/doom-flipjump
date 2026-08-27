"""Author a PURPOSE-BUILT arena wad that fits the renderer's op budget.

EXP-12 measured the renderer's floor at 4.69M ops for a 4-seg room, so 15M/frame allows roughly
10M of MAP cost -- and the smallest of the ~77 maps across doom1/freedoom1/freedoom2 is 508 segs,
which costs about twice that. No shipped level fits. One has to be built.

⚠ The obvious blocker -- "the project has no BSP node builder" -- turns out not to apply. A CONVEX
room is a single BSP leaf: `tests/fixtures/square_room.wad` has a **zero-byte NODES lump** and one
SSECTORS record. So a convex polygon arena needs no node building at all, just the geometry lumps.
That is the whole trick, and it is why this is ~100 lines instead of a node tool.

    python scratchpad/make_arena.py                # reproduces the committed fixture byte for byte

Writes tests/fixtures/arena.wad (MAP01). ⚠ The DEFAULTS are the committed fixture's exact recipe
(16 sides, radius 1000, 20 monsters, CEIL3_5 roof -- cmp-verified byte-identical); change any knob
and you are authoring a NEW arena, so point --out somewhere else or expect to re-bless every
arena golden.
"""
import argparse
import math
import struct
import sys
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / "src"))

ap = argparse.ArgumentParser()
ap.add_argument("--sides", type=int, default=16, help="walls in the convex ring")
ap.add_argument("--radius", type=int, default=1000)
ap.add_argument("--monsters", type=int, default=20)
ap.add_argument("--items", type=int, default=8)
ap.add_argument("--ceil", type=int, default=160)
ap.add_argument("--roof", default="CEIL3_5",
                help="ceiling flat. The default matches the COMMITTED tests/fixtures/arena.wad "
                     "(regenerating must reproduce it byte for byte); pass F_SKY1 for an "
                     "OPEN-AIR arena that exercises V2 sky on the shipped path")
ap.add_argument("--light", type=int, default=192)
ap.add_argument("--out", default="tests/fixtures/arena.wad")
args = ap.parse_args()

N = args.sides
R = args.radius
# ── geometry: one convex ring of vertices, walked CLOCKWISE. DOOM's convention is that sidedef 0
#    is the FRONT (right-hand) side of a linedef, so the interior must lie to the RIGHT of every
#    v1->v2 direction. Going counter-clockwise puts it on the left and every wall back-faces --
#    measured: 6% of the frame painted instead of ~100%.
pts = [(round(R * math.cos(-2 * math.pi * i / N)), round(R * math.sin(-2 * math.pi * i / N)))
       for i in range(N)]

VERTEXES = b"".join(struct.pack("<2h", x, y) for x, y in pts)
# linedef i joins vertex i -> i+1; flags 1 = impassable+one-sided, left sidedef 0xFFFF = none
LINEDEFS = b"".join(struct.pack("<7h", i, (i + 1) % N, 1, 0, 0, i, -1) for i in range(N))
SIDEDEFS = b"".join(struct.pack("<2h8s8s8sh", 0, 0, b"\0" * 8, b"\0" * 8,
                                b"STARTAN3".ljust(8, b"\0"), 0) for _ in range(N))
SECTORS = struct.pack("<2h8s8s3h", 0, args.ceil, b"FLOOR4_8".ljust(8, b"\0"),
                      args.roof.encode().ljust(8, b"\0"), args.light, 0, 0)


def bam(x0, y0, x1, y1):
    """SEGS angle: the BAM direction v1->v2, stored as the top 16 bits."""
    a = math.atan2(y1 - y0, x1 - x0) / (2 * math.pi)
    return int(round(a * 65536)) & 0xFFFF


SEGS = b"".join(struct.pack("<6H", i, (i + 1) % N,
                            bam(*pts[i], *pts[(i + 1) % N]), i, 0, 0) for i in range(N))
SSECTORS = struct.pack("<2H", N, 0)      # ONE convex leaf holding every seg
NODES = b""                              # ... and therefore no BSP at all

# ── the scenario: a player in the middle, monsters ringed around, items between them.
MONSTERS = [3004, 3001, 3002, 9]         # zombieman, imp, demon, shotgun guy
ITEMS = [2007, 2008, 2011, 2014, 2015, 2018, 2048, 2046]
things = [(0, 0, 90, 1, 7)]              # player 1 start, facing north
for i in range(args.monsters):
    a = 2 * math.pi * i / max(1, args.monsters)
    r = R * 0.62
    things.append((round(r * math.cos(a)), round(r * math.sin(a)),
                   round(math.degrees(a + math.pi)) % 360, MONSTERS[i % len(MONSTERS)], 7))
for i in range(args.items):
    a = 2 * math.pi * (i + 0.5) / max(1, args.items)
    r = R * 0.30
    things.append((round(r * math.cos(a)), round(r * math.sin(a)), 0,
                   ITEMS[i % len(ITEMS)], 7))
THINGS = b"".join(struct.pack("<5h", *t) for t in things)

LUMPS = [("MAP01", b""), ("THINGS", THINGS), ("LINEDEFS", LINEDEFS), ("SIDEDEFS", SIDEDEFS),
         ("VERTEXES", VERTEXES), ("SEGS", SEGS), ("SSECTORS", SSECTORS), ("NODES", NODES),
         ("SECTORS", SECTORS)]

out = ROOT / args.out
data = b""
dir_entries = []
off = 12
for name, payload in LUMPS:
    dir_entries.append((off, len(payload), name))
    data += payload
    off += len(payload)
header = struct.pack("<4sii", b"PWAD", len(LUMPS), 12 + len(data))
directory = b"".join(struct.pack("<ii8s", o, sz, nm.encode().ljust(8, b"\0"))
                     for o, sz, nm in dir_entries)
out.write_bytes(header + data + directory)
print(f"wrote {out}  {N} walls / {N} segs / 1 subsector / 0 nodes / {len(things)} things "
      f"({args.monsters} monsters)  radius {R}")

# ── prove it loads and renders through the SAME pipeline the renderer uses
from doomfj.config import Config                                          # noqa: E402
from doomfj.reference_model import ReferenceModel, SimState, build_scene  # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

mw = WadFile.from_path(str(out))
art = WadFile.from_path('assets/freedoom1.wad')
cfg = Config()
rm = ReferenceModel(cfg)
scene = build_scene(mw, art, "MAP01")
print(f"parsed back: {len(scene.cmap.segs)} segs, {len(scene.cmap.subsectors)} subsectors, "
      f"{len(mw.things('MAP01'))} things")
fb = rm.render_wall_frame(SimState(x=0, y=0, angle=0, level="MAP01"), scene,
                          wall_mode="WPX", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                          sky=True, near_steps=True, things=True, sprite_wad=art)
nz = sum(1 for b in fb if b)
print(f"ORACLE RENDERS: {nz * 100 // len(fb)}% of the frame painted, "
      f"{len(set(fb))} distinct colours")
