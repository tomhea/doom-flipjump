"""What does ONE sim.thing_load cost? A k-sweep, with the linearity control.

The M14-e adder decomposes as bind_things (measured 27.18M standalone by `_bind.py`) plus the
per-thing register load that replaced the baked xor-involution block. That second term has never
been measured on its own, and it decides whether the binding lever alone reaches the target.

METHOD (the M14-0 wire probe's, reused): assemble the same program at k = 1/17/33 calls and take
the MARGINAL cost, so the fixed startup and the table bakes cancel.
⚠ CONTROL: the marginal cost must be LINEAR in k -- if it is not, the number is measuring
something other than the call (a table read whose cost grows with the loop, say) and must not be
quoted. Reported explicitly, not asserted silently.

    python scratchpad/m14_thload_cost.py
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


def pack(v, ws):
    o = s = 0
    for x, nb in zip(v, ws): o |= (x & ((1 << 8 * nb) - 1)) << s; s += 8 * nb
    return o


def build(k):
    prog = "\n".join([
        "stl.startup_and_init_all",
        "hex.input 1, wmagic",
        "hex.zero w/4, ti", "hex.zero w/4, ssi", "hex.set w/4, ssi, 646",
        # k calls, each on a different thing so no cache-like effect can flatter it
        *[f"hex.set w/4, ti, {i % NT}\nsim.thing_load throw, 4, thpos, ssflr, 4, sslgt, sprlt, "
          "ltbase, ti, ssi" for i in range(k)],
        "hex.print_as_digit 8, sp_x, 0", "stl.output 10",
        "stl.loop",
        "wmagic: hex.vec 2", "ti: hex.vec w/4", "ssi: hex.vec w/4",
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
    term = fj.run(out, io_device=FixedIO(bytes([0xD0])), print_time=False,
                  print_termination=False)
    return term.op_counter


KS = (1, 17, 33)
ops = {}
for k in KS:
    ops[k] = build(k)
    print(f"  k={k:3d}: {ops[k]:,} ops", flush=True)

m1 = (ops[17] - ops[1]) / 16
m2 = (ops[33] - ops[17]) / 16
drift = abs(m2 - m1) / max(m1, m2) * 100
print(f"\nmarginal cost of ONE sim.thing_load:")
print(f"  k 1->17 : {m1:,.0f} ops/call")
print(f"  k 17->33: {m2:,.0f} ops/call")
print(f"  LINEARITY CONTROL: the two marginals differ by {drift:.1f}%")
print("  -> LINEAR, the number is a per-call cost" if drift < 10 else
      "  -> !! NOT LINEAR: this is not a per-call cost, do not quote it")
print(f"\nprojected for {NT} things/frame: {m2 * NT / 1e6:,.1f}M ops")
