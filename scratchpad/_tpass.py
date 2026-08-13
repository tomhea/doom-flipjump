"""sim.thing_pass: does each leaf visit exactly its things, in ascending index order?
A stub `thing_leaf` prints the loaded sp_base + the thing's x, so the walk is observable."""
import sys, tempfile
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
from doomfj.reference_model import (DEG_MINH2_MON, DEG_MINH2_SCENERY, MIN_SPRITE_H,
                                    MIN_SPRITE_H_MONSTER, MONSTER_TYPES, ReferenceModel,
                                    THING_SPRITE)
from doomfj.things import THING_ROW_BYTES, THING_ROW_LEN, subsector_tables, thing_rows
from doomfj.wad import WadFile
from doomfj.wall_renderer import _lines_sprite_bank, _lines_sprite_light

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
art = WadFile.from_path(str(ROOT/"assets/freedoom1.wad"))
cmap = bake_bsp(mw, "E1M1"); lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
_b, spr_base, spr_dw, spr_ldbase = _lines_sprite_bank(rm, art, cfg, mw, "E1M1")
_l, spr_cls = _lines_sprite_light(rm, cfg, art, mw, "E1M1", cmap, lds, sds, secs, moving_things=True)
allt = mw.things("E1M1")
rows, idx = thing_rows(rm, allt, art, spr_base, spr_ldbase, spr_dw, MONSTER_TYPES, MIN_SPRITE_H,
                       MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON, deg=True, spr_near=True)
things = [allt[i] for i in idx]
ssflr, sslgt_raw = subsector_tables(rm, cmap, lds, sds, secs)
lns = sorted({rm.wall_lightnum(s.light, 0) for s in secs}); lnpos = {l: k for k, l in enumerate(lns)}
sslgt = [lnpos.get(l, 0) for l in sslgt_raw]
sprlt = [spr_cls[(ln, max(1, r[2]))] for ln in lns for r in rows]
NT, NSS = len(rows), len(cmap.subsectors)
def pack(v, ws):
    o = s = 0
    for x, nb in zip(v, ws): o |= (x & ((1 << 8*nb)-1)) << s; s += 8*nb
    return o
prog = "\n".join([
    "stl.startup_and_init_all",
    "hex.input 1, wmagic", "hex.input 2, want_ss",
    f"sim.bind_things thpos, {NT}, {NSS}",
    "hex.zero w/4, cur_ss", "hex.mov 4, cur_ss, want_ss",
    "hex.zero 1, tstop",
    "sim.thing_pass throw, 4, thpos, ssflr, 4, sslgt, sprlt, ltbase",
    "stl.loop",
    # the stub leaf: print the thing's x (16.16) so the visit ORDER is observable
    "thing_leaf:", "hex.print_as_digit 8, sp_x, 0", "stl.output 10", "stl.fret thing_ret",
    "wmagic: hex.vec 2", "want_ss: hex.vec 4", "cur_ss: hex.vec w/4", "tstop: hex.vec 1",
    "thing_ret: hex.vec w/4",
    "sp_x: hex.vec 8","sp_y: hex.vec 8","sp_z: hex.vec 8","sp_left: hex.vec 8","sp_w: hex.vec 8",
    "sp_hh: hex.vec 8","sp_tzmax: hex.vec 8","sp_tzmax2: hex.vec 8","sp_base: hex.vec 4",
    "sp_base2: hex.vec 4","sp_mon: hex.vec 2","sp_dw: hex.vec 2","sp_lt: hex.vec 2",
    f"sshead: hex.vec {2*NSS}", f"thnext: hex.vec {2*NT}",
    *point_location_decls(),
    generate_point_location_fj(cmap),
    generate_packed_lut_fj("throw", [pack(r, THING_ROW_BYTES) for r in rows], THING_ROW_LEN),
    thpos_vec("thpos", [((t.x << 16) & 0xFFFFFFFF, (t.y << 16) & 0xFFFFFFFF) for t in things]),
    generate_packed_lut_fj("ssflr", [f & 0xFFFF for f in ssflr], 2),
    generate_packed_lut_fj("sslgt", sslgt, 1),
    generate_packed_lut_fj("sprlt", sprlt, 1),
    generate_packed_lut_fj("ltbase", [k * NT for k in range(len(lns))], 2),
]) + "\n"
tmp = Path(tempfile.mkdtemp()); src = tmp/"t.fj"; src.write_text(prog, encoding="utf-8")
out = tmp/"t.fjm"
fj.assemble([(ROOT/"src/fj/fixed_point.fj").resolve(), (ROOT/"src/fj/sim.fj").resolve(),
             src.resolve()], out, memory_width=W, print_time=False)
print("assembled", f"{out.stat().st_size:,}", flush=True)
import struct
want = {}
for i, t in enumerate(things):
    want.setdefault(rm.point_in_subsector(cmap, t.x, t.y), []).append(i)
bad = 0
targets = sorted(want, key=lambda s: -len(want[s]))[:4] + [s for s in sorted(want)][:2]
for ss in targets:
    io = FixedIO(bytes([0xD0]) + struct.pack("<H", ss))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = [int(v, 16) for v in io.get_output(allow_incomplete_output=True).decode().split("\n") if v]
    exp = [(things[i].x << 16) & 0xFFFFFFFF for i in want[ss]]
    ok = got == exp
    bad += not ok
    print(f"  ss{ss}: {len(want[ss])} things  {'OK' if ok else f'!! fj {got} want {exp}'}", flush=True)
print("ALL LEAVES VISIT THEIR THINGS IN ORDER" if not bad else f"{bad} leaves wrong")
