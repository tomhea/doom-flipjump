"""Feasibility probe 0: can a standalone program expand stream.sprite_runs from the real sources?

Assembles fj_consts + the 7 src/fj files + a tiny main (byte/cm emit tables, a 2-block sprite bank,
the hoisted scratch registers) and runs one sprite_runs call. Prints the op count and output bytes.
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                   # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO             # noqa: E402
from doomfj.config import Config                                        # noqa: E402
from doomfj.harness import W                                            # noqa: E402
from doomfj.lut_generator import generate_emit_dispatch_table_fj        # noqa: E402
from doomfj.texturecompiler import _index_nibbles                       # noqa: E402
from doomfj import wall_renderer as wr                                  # noqa: E402
from doomfj.wad import WadFile                                          # noqa: E402

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]


def main():
    cfg = Config()
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    cmv = wr.colormap_values(mw, lights=wr.COLORMAP_LIGHTS)
    tables = "\n".join([
        generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2),
        generate_emit_dispatch_table_fj("cm", cmv, index_nibbles=_index_nibbles(len(cmv)),
                                        over_align=True)])
    # a 2-block bank: [r0][last][n][(rel,tex)...] padded to 64
    blocks = [[0, 30, 3, 10, 0x40, 20, 0x50, 30, 0x60], [0, 5, 1, 5, 0x70]]
    bank = ["sprbank:"]
    for b in blocks:
        bank += [";%#x * dw" % v for v in b] + [";0 * dw"] * (64 - len(b))
    prog = "\n".join([
        "stl.startup_and_init_all",
        tables,
        "    hex.set 4, t_sblk, 0",
        "    hex.set 4, t_sy0b, %d" % (32768 + 20),
        "    hex.set 2, t_slr, 5",
        "    stream.sprite_runs t_sblk, t_sy0b, t_slr, 100, 6",
        "    stl.loop",
        "t_sblk: hex.vec 4",
        "t_sy0b: hex.vec 4",
        "t_slr: hex.vec 2",
        wr.hoisted_scratch_fj(cfg),
        *bank,
        "",
    ])
    p = tmp / "feas0.fj"
    p.write_text(prog, encoding="utf-8")
    out = tmp / "feas0.fjm"
    t0 = time.time()
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()], out,
                memory_width=W, print_time=False)
    t1 = time.time()
    io = FixedIO(b"")
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    print("assemble %.1fs  run %.2fs  ops %d" % (t1 - t0, time.time() - t1, term.op_counter))
    print("output", list(io.get_output(allow_incomplete_output=True)))


if __name__ == "__main__":
    main()
