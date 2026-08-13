"""sim.bind_things vs the Python binding (point_in_subsector + ascending-order per-leaf lists)."""
import struct, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT/"tests", ROOT/"src", ROOT): sys.path.insert(0, str(q))
import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from doomfj.collision import generate_point_location_fj, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_packed_lut_fj
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ReferenceModel, THING_SPRITE
from doomfj.wad import WadFile

cfg = Config(); rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT/"tests/fixtures/freedoom_e1m1.wad"))
cmap = bake_bsp(mw, "E1M1")
things = [t for t in mw.things("E1M1") if THING_SPRITE.get(t.type) is not None]
NT, NSS = len(things), len(cmap.subsectors)
def pack(v, ws):
    o = s = 0
    for x, nb in zip(v, ws): o |= (x & ((1 << 8*nb)-1)) << s; s += 8*nb
    return o
positions = [((t.x << 16) & 0xFFFFFFFF, (t.y << 16) & 0xFFFFFFFF) for t in things]
prog = "\n".join([
    "stl.startup_and_init_all",
    "hex.input 1, wmagic",
    "hex.set 2, mk, 0x11", "hex.print_as_digit 2, mk, 0", "stl.output 10",
    f"sim.bind_things thpos, 4, {NT}, {NSS}",
    "hex.set 2, mk, 0x99", "hex.print_as_digit 2, mk, 0", "stl.output 10",
    # dump every leaf's list, ascending, as "ss:t,t,t"
    "hex.zero w/4, ds", "hex.set w/4, dn, %d" % NSS,
    "dl:", "hex.cmp w/4, ds, dn, dbody, ddone, ddone",
    "dbody:", "hex.set w/4, dq, sshead", "hex.ptr_index dp, dq, ds",
    "hex.zero w/4, dh", "hex.read_byte dh, dp",   # read_byte fills only 2 nibbles
    "wl:", "hex.set w/4, dc, 0xFF", "hex.cmp w/4, dh, dc, wbody, wdone, wbody",
    "wbody:", "hex.print_as_digit 4, ds, 0", "stl.output 58", "hex.print_as_digit 2, dh, 0",
    "stl.output 10",
    "hex.set w/4, dq, thnext", "hex.ptr_index dp, dq, dh",
    "hex.zero w/4, dh", "hex.read_byte dh, dp", ";wl",
    "wdone:", "hex.inc w/4, ds", ";dl",
    "ddone:", "stl.loop",
    "wmagic: hex.vec 2", "mk: hex.vec 2", "ds: hex.vec w/4", "dn: hex.vec w/4", "dh: hex.vec w/4", "dc: hex.vec w/4",
    "dp: hex.vec w/4", "dq: hex.vec w/4",
    f"sshead: hex.vec {2*NSS}", f"thnext: hex.vec {2*NT}",
    *point_location_decls(),
    generate_point_location_fj(cmap),
    generate_packed_lut_fj("thpos", [pack(p, (4, 4)) for p in positions], 8),
]) + "\n"
tmp = Path(tempfile.mkdtemp()); src = tmp/"b.fj"; src.write_text(prog, encoding="utf-8")
out = tmp/"b.fjm"
fj.assemble([(ROOT/"src/fj/fixed_point.fj").resolve(), (ROOT/"src/fj/sim.fj").resolve(),
             src.resolve()], out, memory_width=W, print_time=False)
print("assembled", f"{out.stat().st_size:,}")
io = FixedIO(bytes([0xD0]))
term = fj.run(out, io_device=io, print_time=False, print_termination=False)
got = {}
raw = io.get_output(allow_incomplete_output=True).decode()
print("RAW[:160]:", repr(raw[:160]))
for line in io.get_output(allow_incomplete_output=True).decode().split("\n"):
    if ":" not in line: continue
    a, b = line.split(":"); got.setdefault(int(a, 16), []).append(int(b, 16))
want = {}
for i, t in enumerate(things):
    want.setdefault(rm.point_in_subsector(cmap, t.x, t.y), []).append(i)
print(f"ops {term.op_counter:,}   leaves with things: fj {len(got)}, python {len(want)}")
bad = [(k, got.get(k), want.get(k)) for k in set(got) | set(want) if got.get(k) != want.get(k)]
print(f"{'ALL LEAF LISTS MATCH (ascending order preserved)' if not bad else str(len(bad))+' leaves differ'}")
for k, g, w in bad[:5]: print(f"  ss{k}: fj {g} python {w}")
