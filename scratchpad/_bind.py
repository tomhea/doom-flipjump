"""sim.bind_things vs the Python binding, in BOTH cache modes.

COLD = every thss slot is the 0xFFFF dirty sentinel, so all 251 things are point-located (what
the first cut did every single frame). WARM = the true bindings are fed in, as they would arrive
on the wire from the previous frame, so nothing is located.

⚠ THE CONTROL IS TWO-SIDED and that is the point: WARM must produce lists IDENTICAL to COLD
(else the cache is wrong) AND must be far cheaper (else it is not doing anything). Checking only
the ops would pass a build that skipped the work and bound nothing; checking only the lists would
pass one that ignored the cache and re-located everything."""
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

def thpos_vec(name, positions):
    """The runtime position array: a hex.vec of 16 nibbles per thing, which is what the
    shl-by-one-nibble + ptr_index + read_hex accessor addresses (a packed table is one BYTE
    per slot and read_table_packed cannot address this)."""
    out = [name + ":"]
    for x, y in positions:
        out.append("    hex.vec 16, %d" % (((y & 0xFFFFFFFF) << 32) | (x & 0xFFFFFFFF)))
    return chr(10).join(out)


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
    f"hex.input {NT*8}, thss",      # last frame's bindings, 8 wire bytes per thing
    f"sim.bind_things thpos, thss, {NT}, {NSS}",
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
    f"sshead: hex.vec {2*NSS}", f"thnext: hex.vec {2*NT}", f"thss: hex.vec {16*NT}",
    *point_location_decls(),
    generate_point_location_fj(cmap),
    thpos_vec("thpos", positions),
]) + "\n"
tmp = Path(tempfile.mkdtemp()); src = tmp/"b.fj"; src.write_text(prog, encoding="utf-8")
out = tmp/"b.fjm"
fj.assemble([(ROOT/"src/fj/fixed_point.fj").resolve(), (ROOT/"src/fj/sim.fj").resolve(),
             src.resolve()], out, memory_width=W, print_time=False)
print("assembled", f"{out.stat().st_size:,}")
import struct
want = {}
truess = []
for i, t in enumerate(things):
    ss = rm.point_in_subsector(cmap, t.x, t.y)
    truess.append(ss)
    want.setdefault(ss, []).append(i)


def run(thss_vals, tag):
    io_ = FixedIO(bytes([0xD0]) + b"".join(struct.pack("<Q", v) for v in thss_vals))
    term = fj.run(out, io_device=io_, print_time=False, print_termination=False)
    got = {}
    for line in io_.get_output(allow_incomplete_output=True).decode().splitlines():
        if ":" not in line:
            continue
        a, b = line.split(":")
        got.setdefault(int(a, 16), []).append(int(b, 16))
    bad = [k for k in set(got) | set(want) if got.get(k) != want.get(k)]
    print(f"  {tag:5s} {term.op_counter:>12,} ops   leaves fj {len(got)} / python {len(want)}   "
          f"{'LISTS MATCH' if not bad else str(len(bad)) + ' LEAVES DIFFER'}", flush=True)
    return term.op_counter, not bad


cold, ok_c = run([0xFFFF] * NT, "COLD")
warm, ok_w = run(truess, "WARM")
print(f"{chr(10)}WARM saves {cold - warm:,} ops ({100 * (cold - warm) / cold:.1f}%)")
# the bar guards a PROPERTY, not a number: WARM must not be paying for point location, which is
# ~25M of COLD's ~31M. Anything near COLD means the cache is being ignored.
ok = ok_c and ok_w and warm < cold * 0.4
if not ok_c or not ok_w:
    print("!! a mode's lists are WRONG")
elif warm >= cold * 0.4:
    print("!! WARM is not meaningfully cheaper -- the cache is not being taken")
else:
    print("PASS -- identical lists both ways, and the cache is doing the work")
