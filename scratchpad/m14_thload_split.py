"""WHERE inside sim.thing_load do the 68,181 ops go?

Lever B is "make thing_load lazy", and its shape depends entirely on this: if the four
`read_table_packed` / `ptr_index` reads dominate, splitting the ROW is the fix; if the dozen little
`hex.mov`s dominate, splitting it buys nothing and lever B is not worth doing.

Each variant is the same k-sweep as m14_thload_cost.py (marginal cost over k = 1/17/33, so startup
and the table bakes cancel), with one group of the macro's work removed:

  full     everything, as shipped
  norow    minus `read_table_packed 22` and every field derived from the row
  nopos    minus the position accessor (shl + ptr_index + read_hex 16)
  nozlt    minus the sp_z / sp_lt derivation (three more table reads)

⚠ CONTROL: the variants must SUM sensibly -- the three removals should account for close to the
full cost, and each marginal must be linear in k. A group whose removal changes nothing is a group
that was already free, and reporting it as a saving would be wrong.

    python scratchpad/m14_thload_split.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT): sys.path.insert(0, str(q))

import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_packed_lut_fj
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import (DEG_MINH2_MON, DEG_MINH2_SCENERY, MIN_SPRITE_H,
                                    MIN_SPRITE_H_MONSTER, MONSTER_TYPES, ReferenceModel)
from doomfj.things import (THING_ROW_BYTES, THING_ROW_LEN, reachable_lightnums,
                           sprite_light_table, subsector_tables, thing_rows)
from doomfj.wad import WadFile
from doomfj.wall_renderer import _lines_sprite_bank, _lines_sprite_light

cfg = Config(); rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
cmap = bake_bsp(mw, "E1M1")
lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
_b, spr_base, spr_dw, spr_ldbase = _lines_sprite_bank(rm, art, cfg, mw, "E1M1")
_l, spr_cls = _lines_sprite_light(rm, cfg, art, mw, "E1M1", cmap, lds, sds, secs, moving_things=True)
allt = mw.things("E1M1")
rows, idx = thing_rows(rm, allt, art, spr_base, spr_ldbase, spr_dw, MONSTER_TYPES, MIN_SPRITE_H,
                       MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON,
                       deg=True, spr_near=True)
things = [allt[i] for i in idx]
ssflr, sslgt_raw = subsector_tables(rm, cmap, lds, sds, secs)
lns = reachable_lightnums(rm, secs); lnpos = {l: k for k, l in enumerate(lns)}
sslgt = [lnpos.get(l, 0) for l in sslgt_raw]
sprlt = sprite_light_table(spr_cls, rows, lns)
NT, NSS = len(rows), len(cmap.subsectors)
# ⚠ THE INDEX WIDTHS MUST BE THE EMITTER'S. The first run of this probe hard-coded 4 nibbles
# for every read while the emitter passes _index_nibbles(251)=2 and _index_nibbles(682)=3. If
# read_table_packed's cost scales with the index width, that measured a program nobody builds.
from doomfj.texturecompiler import _index_nibbles
NTH, NSSN, NLTI = _index_nibbles(NT), _index_nibbles(NSS), _index_nibbles(len(lns) * NT)
print(f'index widths: n_th={NTH} ssnss={NSSN} sprlt={NLTI}', flush=True)


def pack(v, ws):
    o = s = 0
    for x, nb in zip(v, ws): o |= (x & ((1 << 8 * nb) - 1)) << s; s += 8 * nb
    return o


ROW = [f"hex.read_table_packed 22, row, throw, {NTH}, ti",
       "sim.fix16 sp_left, row", "sim.fix16 sp_w, row + 4*dw", "sim.fix16 sp_hh, row + 8*dw",
       "hex.mov 8, sp_tzmax,  row + 16*dw", "hex.mov 8, sp_tzmax2, row + 24*dw",
       "hex.zero 4, sp_base", "hex.mov 4, sp_base,  row + 32*dw",
       "hex.zero 4, sp_base2", "hex.mov 4, sp_base2, row + 36*dw",
       "hex.zero 2, sp_mon", "hex.mov 2, sp_mon, row + 40*dw",
       "hex.zero 2, sp_dw", "hex.mov 2, sp_dw,  row + 42*dw"]
POS = ["hex.mov w/4, poff, ti", "hex.shl_hex w/4, 1, poff", "hex.set w/4, pbase, thpos",
       "hex.ptr_index pptr, pbase, poff", "hex.read_hex 16, pos, pptr",
       "hex.mov 8, sp_x, pos", "hex.mov 8, sp_y, pos + 8*dw"]
ZLT = [f"hex.read_table_packed 2, zt, ssflr, {NSSN}, ssi", "hex.add 4, zt, row + 12*dw",
       "sim.fix16 sp_z, zt",
       f"hex.read_table_packed 1, zt, sslgt, {NSSN}, ssi",
       "hex.read_table_packed 2, lti, ltbase, 2, zt", "hex.add 4, lti, ti",
       f"hex.read_table_packed 1, sp_lt, sprlt, {NLTI}, lti"]

VARIANTS = {"full": ROW + POS + ZLT, "norow": POS + ZLT, "nopos": ROW + ZLT, "nozlt": ROW + POS}


def build(body, k):
    prog = "\n".join([
        "stl.startup_and_init_all", "hex.input 1, wmagic",
        "hex.zero w/4, ti", "hex.zero w/4, ssi", "hex.set w/4, ssi, 646",
        *[ln for i in range(k) for ln in ([f"hex.set w/4, ti, {i % NT}"] + body)],
        "hex.print_as_digit 8, sp_x, 0", "stl.output 10", "stl.loop",
        "wmagic: hex.vec 2", "ti: hex.vec w/4", "ssi: hex.vec w/4",
        "row: hex.vec 44", "zt: hex.vec 4", "lti: hex.vec 4", "pos: hex.vec 16",
        "poff: hex.vec w/4", "pbase: hex.vec w/4", "pptr: hex.vec w/4",
        "sp_x: hex.vec 8", "sp_y: hex.vec 8", "sp_z: hex.vec 8", "sp_left: hex.vec 8",
        "sp_w: hex.vec 8", "sp_hh: hex.vec 8", "sp_tzmax: hex.vec 8", "sp_tzmax2: hex.vec 8",
        "sp_base: hex.vec 4", "sp_base2: hex.vec 4", "sp_mon: hex.vec 2", "sp_dw: hex.vec 2",
        "sp_lt: hex.vec 2",
        generate_packed_lut_fj("throw", [pack(r, THING_ROW_BYTES) for r in rows], THING_ROW_LEN),
        "thpos:", *[f"    hex.vec 16, {(((t.y << 16) & 0xFFFFFFFF) << 32) | ((t.x << 16) & 0xFFFFFFFF)}"
                    for t in things],
        generate_packed_lut_fj("ssflr", [f & 0xFFFF for f in ssflr], 2),
        generate_packed_lut_fj("sslgt", sslgt, 1),
        generate_packed_lut_fj("sprlt", sprlt, 1),
        generate_packed_lut_fj("ltbase", [j * NT for j in range(len(lns))], 2),
    ]) + "\n"
    tmp = Path(tempfile.mkdtemp()); src = tmp / "t.fj"
    src.write_text(prog, encoding="utf-8")
    out = tmp / "t.fjm"
    fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), (ROOT / "src/fj/sim.fj").resolve(),
                 src.resolve()], out, memory_width=W, print_time=False)
    return fj.run(out, io_device=FixedIO(bytes([0xD0])), print_time=False,
                  print_termination=False).op_counter


res = {}
for name, body in VARIANTS.items():
    o1, o17, o33 = (build(body, k) for k in (1, 17, 33))
    m1, m2 = (o17 - o1) / 16, (o33 - o17) / 16
    drift = abs(m2 - m1) / max(m1, m2) * 100
    res[name] = m2
    print(f"  {name:6s} {m2:>9,.0f} ops/call   (linearity drift {drift:4.1f}%"
          f"{'' if drift < 10 else '  !! NOT LINEAR'})", flush=True)

full = res["full"]
print(f"\n  attributed by removal, against full = {full:,.0f}:")
parts = {"the row read + its 13 fields": full - res["norow"],
         "the position accessor": full - res["nopos"],
         "sp_z / sp_lt (3 table reads)": full - res["nozlt"]}
for k, v in parts.items():
    print(f"    {k:32s} {v:>9,.0f}  ({100*v/full:4.1f}%)")
tot = sum(parts.values())
print(f"    {'sum of the three':32s} {tot:>9,.0f}  ({100*tot/full:4.1f}% of full)")
print(f"\n  projected over ~117 loaded things/frame: {full*117/1e6:.1f}M ops")
