"""M14 GATE — the binary state wire, gated the way deg_gate gates the renderer.

Same map, same tier, same four viewpoints and the same degrade=True oracle as `scratchpad/deg_gate.py`;
the ONLY difference is `state_wire="bin"`. So:

  * PIXELS -- every frame must still be byte-exact against the oracle. Since deg_gate proves the dec
    wire byte-exact against that same oracle, a pass here proves bin == dec at the pixel level.
  * ROUND-TRIP -- the state the program echoes back must equal the state fed in. A wire that dropped
    or reordered a word would still render correctly at frame 1 and drift on frame 2, so the echo is
    checked explicitly rather than inferred from the picture.
  * OPS -- reported per viewpoint, to be diffed against deg_gate's certified
    45,208,629 / 35,486,777 / 42,824,933 / 33,547,652. The whole difference should be the input
    path: three decimal parses (~60k ops) traded for 13 raw bytes (~1k).

⚠ ONE HEAVY BUILD AT A TIME (CLAUDE.md rule 1) -- this assembles a ~12MB binary, so nothing else
may build while it runs.

Usage:  python scratchpad/m14_gate.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer, write_program_files
from doomfj.wireformat import encode_feed_mapunits
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
# deg_gate's certified op counts, in VPS order -- the baseline the bin wire is diffed against
DEC_OPS = (45_208_629, 35_486_777, 42_824_933, 33_547_652)

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(664, 291, 0x18000000),        # the sprite-overlap frame: B-gate + graduated
       (1272, -724, 1073741824),      # stairs: the stack far gate
       (1869, 479, 2147483648),       # the everything frame: sliver + PNEAR + all
       (spx, spy, sp.angle)]


def build():
    parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, over_align=False,
                               floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                               plane_near=True, wall_noise=True, steps=True, stack_steps=True,
                               things=True, sprite_wad=art, deg=True, state_wire="bin")
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    prog = write_program_files(parts, tmp, "e1m1")     # ⚠ order is the contract
    out = tmp / "m14.fjm"
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], *[p.resolve() for p in prog]],
                out, memory_width=W, print_time=False)
    print(f"assembled {out.stat().st_size:,} bytes", flush=True)
    return out


def main():
    out = build()
    ok = True
    for i, (vx, vy, va) in enumerate(VPS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                    wall_noise=True, near_steps=True, stack_steps=True,
                                    things=True, sprite_wad=art, degrade=True)
        scr = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
        term = fj.run(out, io_device=scr, print_time=False, print_termination=False,
                      flat_max_words=1 << 26)
        same = bytes(scr.pixel_indices) == bytes(want)
        diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
        echoed = scr.state == (vx << 16, vy << 16, va)
        ok &= same and echoed
        px_note = "BYTE-EXACT" if same else f"!! {diff} px DIFFER"
        st_note = ("ROUND-TRIPPED" if echoed
                   else f"!! echoed {scr.state}, fed {(vx << 16, vy << 16, va)}")
        print(f"({vx},{vy},{va:#x}): {term.op_counter:,} ops "
              f"(dec wire {DEC_OPS[i]:,}, {term.op_counter - DEC_OPS[i]:+,})  "
              f"{px_note}  state {st_note}", flush=True)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
