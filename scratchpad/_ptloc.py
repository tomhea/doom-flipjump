"""Baked point location vs ReferenceModel.point_in_subsector, + its op cost."""
import struct, sys, tempfile, random
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT/"tests", ROOT/"src", ROOT): sys.path.insert(0, str(q))
import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from doomfj.collision import generate_point_location_fj, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile

wad = WadFile.from_path(str(ROOT/"tests/fixtures/freedoom_e1m1.wad"))
cmap = bake_bsp(wad, "E1M1"); rm = ReferenceModel(Config())
M40 = (1 << 40) - 1
prog = "\n".join([
    "stl.startup_and_init_all",
    "hex.input 1, wmagic", "hex.input 2, inx", "hex.input 2, iny",   # 2 BYTES = 4 nibbles
    # sign-extend the 4-nibble int16 inputs into the 10-nibble signed working width
    "hex.zero 10, ptx", "hex.mov 4, ptx, inx", "hex.sign 4, inx, xn, xp",
    "xn:", "hex.set 6, ptx + 4*dw, 0xFFFFFF", "xp:",
    "hex.zero 10, pty", "hex.mov 4, pty, iny", "hex.sign 4, iny, yn, yp",
    "yn:", "hex.set 6, pty + 4*dw, 0xFFFFFF", "yp:",
    "stl.fcall ptloc_walk, ptloc_ret",
    "hex.print_as_digit 4, ptss, 0", "stl.output 10",
    "stl.loop",
    "wmagic: hex.vec 2", "inx: hex.vec 4", "iny: hex.vec 4",
    *point_location_decls(),
    generate_point_location_fj(cmap),
]) + "\n"
tmp = Path(tempfile.mkdtemp()); src = tmp/"p.fj"; src.write_text(prog, encoding="utf-8")
out = tmp/"p.fjm"
fj.assemble([(ROOT/"src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
print("assembled", f"{out.stat().st_size:,}")
def run(x, y):
    io = FixedIO(bytes([0xD0]) + struct.pack("<hh", x, y))
    t = fj.run(out, io_device=io, print_time=False, print_termination=False)
    return int(io.get_output(allow_incomplete_output=True).decode().split("\n")[0], 16), t.op_counter
rng = random.Random(14)
xs = [v[0] for v in cmap.vertexes]; ys = [v[1] for v in cmap.vertexes]
pts = [(v[0], v[1]) for v in cmap.vertexes[:12]]
pts += [(rng.randint(min(xs), max(xs)), rng.randint(min(ys), max(ys))) for _ in range(38)]
bad = 0; ops = []
for x, y in pts:
    got, o = run(x, y); want = rm.point_in_subsector(cmap, x, y)
    ops.append(o)
    if got != want:
        bad += 1
        if bad <= 5: print(f"  MISMATCH ({x},{y}): fj ss{got} oracle ss{want}")
base = min(ops)
print(f"{len(pts)-bad}/{len(pts)} agree with point_in_subsector")
print(f"ops per lookup: min {min(ops):,} mean {sum(ops)//len(ops):,} max {max(ops):,}")
print(f"=> 251 things/frame ~= {sum(ops)//len(ops)*251:,} ops "
      f"(vs ~730,000,000 for _bsp_descend_code)")
