"""sim.thing_load vs the constants wall_renderer bakes per (subsector, thing)."""
import struct, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT/"tests", ROOT/"src", ROOT): sys.path.insert(0, str(q))
import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_packed_lut_fj
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import (COLORMAP_LIGHTS, DEG_MINH2_MON, DEG_MINH2_SCENERY,
                                    MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, MONSTER_TYPES,
                                    ReferenceModel)
from doomfj.things import THING_ROW_BYTES, THING_ROW_LEN, subsector_tables, thing_rows
from doomfj.wad import WadFile
from doomfj.wall_renderer import _lines_sprite_bank, _lines_sprite_light, _thing_sector

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
things = mw.things("E1M1")
rows, idx = thing_rows(rm, things, art, spr_base, spr_ldbase, spr_dw, MONSTER_TYPES,
                       MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON,
                       deg=True, spr_near=True)
ssflr, sslgt_raw = subsector_tables(rm, cmap, lds, sds, secs)
lns = sorted({rm.wall_lightnum(s.light, 0) for s in secs}); lnpos = {l: k for k, l in enumerate(lns)}
sslgt = [lnpos.get(l, 0) for l in sslgt_raw]
heights = sorted({max(1, r[2]) for r in rows})
sprlt = [spr_cls[(ln, max(1, r[2]))] for ln in lns for r in rows]
def pack(v, ws):
    o = s = 0
    for x, nb in zip(v, ws): o |= (x & ((1 << 8*nb)-1)) << s; s += 8*nb
    return o
NT = len(rows)
prog = "\n".join([
    "stl.startup_and_init_all",
    "hex.input 1, wmagic", "hex.zero w/4, ti", "hex.input 2, ti",
    "hex.zero w/4, ssi", "hex.input 2, ssi",
    "hex.input 4, px", "hex.input 4, py",
    "hex.write_hex 8, thpos_p, px",   # placeholder; positions come from a baked table below
    "hex.print_as_digit 4, ti, 0", "stl.output 10",     # marker: did we get this far?
    "hex.print_as_digit 4, ssi, 0", "stl.output 10",
    "sim.thing_load throw, 4, thpos, ssflr, 4, sslgt, sprlt, ltbase, ti, ssi",
    *[f"hex.print_as_digit {n}, {r}, 0\nstl.output 10" for r, n in
      (("sp_x",8),("sp_y",8),("sp_z",8),("sp_left",8),("sp_w",8),("sp_hh",8),
       ("sp_tzmax",8),("sp_tzmax2",8),("sp_base",4),("sp_base2",4),
       ("sp_mon",2),("sp_dw",2),("sp_lt",2))],
    "stl.loop",
    "wmagic: hex.vec 2", "ti: hex.vec w/4", "ssi: hex.vec w/4", "px: hex.vec 8", "py: hex.vec 8",
    "thpos_p: hex.vec 8",
    "sp_x: hex.vec 8","sp_y: hex.vec 8","sp_z: hex.vec 8","sp_left: hex.vec 8","sp_w: hex.vec 8",
    "sp_hh: hex.vec 8","sp_tzmax: hex.vec 8","sp_tzmax2: hex.vec 8","sp_base: hex.vec 4",
    "sp_base2: hex.vec 4","sp_mon: hex.vec 2","sp_dw: hex.vec 2","sp_lt: hex.vec 2",
    generate_packed_lut_fj("throw", [pack(r, THING_ROW_BYTES) for r in rows], THING_ROW_LEN),
    thpos_vec("thpos", [(((things[t].x << 16) & 0xFFFFFFFF), ((things[t].y << 16) & 0xFFFFFFFF)) for t in idx]),
    generate_packed_lut_fj("ssflr", [f & 0xFFFF for f in ssflr], 2),
    generate_packed_lut_fj("sslgt", sslgt, 1),
    generate_packed_lut_fj("sprlt", sprlt, 1),
    generate_packed_lut_fj("ltbase", [k * NT for k in range(len(lns))], 2),
]) + "\n"
prog = prog.replace("hex.write_hex 8, thpos_p, px\n", "")
tmp = Path(tempfile.mkdtemp()); src = tmp/"t.fj"; src.write_text(prog, encoding="utf-8")
out = tmp/"t.fjm"
fj.assemble([(ROOT/"src/fj/fixed_point.fj").resolve(), (ROOT/"src/fj/sim.fj").resolve(),
             src.resolve()], out, memory_width=W, print_time=False)
print("assembled", f"{out.stat().st_size:,}")
cache = {}
bad = 0
for row_i in list(range(0, len(rows), 17))[:14]:
    t_i = idx[row_i]; t = things[t_i]
    ss = rm.point_in_subsector(cmap, t.x, t.y)
    io = FixedIO(bytes([0xD0]) + struct.pack("<HH", row_i, ss) + b"\0"*8)
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    g = io.get_output(allow_incomplete_output=True).decode().split("\n")
    a = rm.sprite_art(art, t.type, cache); tsec = _thing_sector(rm, cmap, lds, sds, secs, t)
    mon = t.type in MONSTER_TYPES
    want = [(t.x << 16) & 0xFFFFFFFF, (t.y << 16) & 0xFFFFFFFF,
            ((tsec.floor_h + a[6]) << 16) & 0xFFFFFFFF, (a[5] << 16) & 0xFFFFFFFF,
            (a[3] << 16) & 0xFFFFFFFF, (a[4] << 16) & 0xFFFFFFFF,
            rm.sprite_tz_min_size(a[4], MIN_SPRITE_H_MONSTER if mon else MIN_SPRITE_H) & 0xFFFFFFFF,
            rm.sprite_tz_min_size(a[4], DEG_MINH2_MON if mon else DEG_MINH2_SCENERY) & 0xFFFFFFFF,
            spr_base[t.type], spr_ldbase[t.type], 1 if mon else 0, spr_dw[t.type],
            spr_cls[(rm.wall_lightnum(tsec.light, 0), max(1, a[4]))]]
    if len(g) < 15 or not g[0]:
        print('  OUTPUT:', g[:6]); bad += 1; continue
    got = [int(g[k+2], 16) for k in range(13)]
    names = "x y z left w hh tzmax tzmax2 base base2 mon dw lt".split()
    for n, gv, wv in zip(names, got, want):
        if gv != wv:
            bad += 1
            if bad <= 8: print(f"  thing {t_i} ss{ss}: sp_{n} fj {gv:#x} baked {wv:#x}")
print(f"{'ALL FIELDS MATCH' if not bad else str(bad)+' field mismatches'} over 14 things")
