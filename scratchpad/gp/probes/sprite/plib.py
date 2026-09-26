"""Shared machinery for the sprite-column probe: turn oracle CASES into a standalone fj program
that expands the REAL renderer macros (src/fj/*.fj) over real band lists, a real W1R wall walker,
real V5 step pieces and a real sprite-bank block per case; assemble; run; decode the 0x0B stream.

Nothing here builds the renderer or runs the game binary: the program is fj_consts + the seven
src/fj macro files + one generated main.
"""
import json
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                       # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO                 # noqa: E402
from doomfj.config import Config                                            # noqa: E402
from doomfj.harness import W                                                # noqa: E402
from doomfj.lut_generator import (generate_emit_dispatch_table_fj, generate_bands_walk_fj,   # noqa: E402
                                  generate_w1r_walls_fj)
from doomfj.texturecompiler import _index_nibbles                           # noqa: E402
from doomfj.reference_model import ReferenceModel, WPX_RUN_CAP, STEP_FACE_BASE   # noqa: E402
from doomfj import wall_renderer as wr                                      # noqa: E402
from doomfj.wad import WadFile                                              # noqa: E402

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
cfg = Config()
rm = ReferenceModel(cfg)
H = cfg.VIEW_H
MW = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
COLORMAP = MW.colormap()
CMV = wr.colormap_values(MW, lights=wr.COLORMAP_LIGHTS)
WPXSTRIDE = 2 * WPX_RUN_CAP
BLK = wr.SPR_BLOCK_STRIDE          # 64 ops per bank block (blkshift 6)
PID_MAX = 255                      # PID_NIBBLES = 2


def load_cases():
    return json.loads((HERE / "cases.json").read_text(encoding="utf-8"))


def by_frame(cases):
    fr = OrderedDict()
    for c in cases:
        fr.setdefault((c["scen"], c["vp"]), []).append(c)
    return fr


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


REG_NIBBLES = {"c_x": 2, "c_cexcl": 2, "c_fstart": 2, "c_gnrow": 2, "gnrow2": 2, "gnrow3": 2,
               "c_sprfl": 2, "c_ssy1": 2, "c_ssy2": 2, "c_sy0b": 4, "c_sblk": 4, "c_slr": 2,
               "c_wlit": 2, "c_wlit2": 2, "seg_w1rf": 1, "w1rslv": 1, "seg_litf": 2,
               "c_cbufa": "w/4", "c_cbufd": "w/4", "c_fbufa": "w/4", "c_fbufd": "w/4",
               "ucnt": 2, "lcnt": 2, "c_s": 2}
for _s in ("u", "l"):
    for _k in (1, 2):
        for _f in ("y1", "y2", "cls"):
            REG_NIBBLES["%s%d%s" % (_s, _k, _f)] = 2
        REG_NIBBLES["%s%dbp" % (_s, _k)] = 2 * cfg.PID_BYTES


class Frame:
    """One frame's cases, baked: pid table + band lists, step classes, sprite blocks, registers."""

    def __init__(self, cases):
        self.cases = cases
        vzs = {c["vz"] for c in cases}
        assert len(vzs) == 1, "one frame = one viewz class"
        self.vz = vzs.pop()
        self.pids = OrderedDict()          # (ckey, fkey) -> pid (1-based; 0 = the dummy)
        self.classes = OrderedDict()       # (lightnum, units) -> step class
        self.regs = []
        self.blocks = []
        # THINGS: a thing's columns are adjacent and share its light row, so a new thing starts
        # where x jumps or the light row changes. Its slot holds the thing's top row y0 (the
        # group's lowest y_base) and each column's block header carries r0 = y_base - y0, which
        # is exactly the split the renderer has (y_base = ytop_bucket + r0).
        self.slot_of, self.slot_y0, self.slot_lr = [], [], []
        prev = None
        for c in cases:
            if prev is None or c["x"] != prev["x"] + 1 or c["lr"] != prev["lr"]:
                self.slot_y0.append(c["y_base"])
                self.slot_lr.append(c["lr"])
            s = len(self.slot_y0)                       # 1-based: 0 = no fragment
            self.slot_y0[s - 1] = min(self.slot_y0[s - 1], c["y_base"])
            self.slot_of.append(s)
            prev = c
        assert len(self.slot_y0) < 256
        for i, c in enumerate(cases):
            ckey = (c["ch"], c["lt"], c["cf"])
            fkey = (c["fh"], c["lt"], c["ff"])
            pid = self._pid(ckey, fkey)
            r = OrderedDict()
            r["c_x"] = c["x"]
            r["c_cexcl"] = c["cexcl"]
            r["c_fstart"] = c["fstart"]
            r["c_gnrow"] = c["gnrow"]
            r["gnrow2"] = c["gnrow2"]
            r["gnrow3"] = c["gnrow3"]
            last = c["runs"][-1][0]
            r["c_sprfl"] = 1
            r["c_ssy1"] = clamp(c["y_base"], 0, H)
            r["c_ssy2"] = clamp(c["y_base"] + last, 0, H)
            r["c_sy0b"] = (c["y_base"] + 32768) & 0xFFFF
            r["c_sblk"] = i
            r["c_slr"] = c["lr"]
            r["c_wlit"] = 0x6B
            r["c_wlit2"] = 0x6F
            r["seg_w1rf"] = 0                 # 0 = the W1R PATTERN walker (1 = a flat wall)
            r["w1rslv"] = 0
            r["seg_litf"] = 0x6D
            r["c_cbufa"], r["c_cbufd"], r["c_fbufa"], r["c_fbufd"] = (4 * pid, 4 * pid + 1,
                                                                  4 * pid + 2, 4 * pid + 3)
            for side, pcs in (("u", c["ups"]), ("l", c["los"])):
                r[side + "cnt"] = len(pcs)
                for k in (1, 2):
                    if k <= len(pcs):
                        y1, y2, flight, units, bch, bfh, blt, bct, bft = pcs[k - 1]
                        cls = self._cls(rm.wall_lightnum(flight, 0), units)
                        bp = self._pid((bch, blt, bct), (bfh, blt, bft))
                        r["%s%dy1" % (side, k)], r["%s%dy2" % (side, k)] = y1, y2
                        r["%s%dcls" % (side, k)], r["%s%dbp" % (side, k)] = cls, bp
                    else:
                        for f in ("y1", "y2", "cls", "bp"):
                            r["%s%d%s" % (side, k, f)] = 0
            r["c_s"] = self.slot_of[i]
            self.regs.append(r)
            r0 = c["y_base"] - self.slot_y0[self.slot_of[i] - 1]
            assert 0 <= r0 < 256
            blk = [r0, last, len(c["runs"])] + [v for rr in c["runs"] for v in rr]
            assert len(blk) < BLK
            self.blocks.append(blk)
        assert len(self.pids) + 1 <= PID_MAX, "too many pids for one frame: %d" % len(self.pids)

    def _pid(self, ckey, fkey):
        k = (ckey, fkey)
        if k not in self.pids:
            self.pids[k] = len(self.pids) + 1
        return self.pids[k]

    def _cls(self, ln, units):
        k = (ln, units)
        if k not in self.classes:
            self.classes[k] = len(self.classes)
        return self.classes[k]

    def band_lists(self):
        keys = [(0, 0, 0, "FLAT1"), (0, 0, 0, "FLAT1")]           # pid 0: a dummy pair
        for (ckey, fkey) in self.pids:
            keys.append((ckey[0], ckey[1], 0, ckey[2]))
            keys.append((fkey[0], fkey[1], 0, fkey[2]))
        return wr._band_pair_lists(rm, cfg, MW, [self.vz], keys, True)

    def stepcol(self):
        out = ["stepcol:"]
        for (ln, units) in self.classes:
            row = [0] * wr.STEP_COL_STRIDE
            for h in range(1, H + 1):
                lr = max(0, rm.wall_light_row(ln, h, units) - rm.W1R_BASE_BRIGHTEN)
                row[h] = COLORMAP[lr][STEP_FACE_BASE]
            out += [";%#x * dw" % v for v in row]
        if not self.classes:
            out += [";0 * dw"] * wr.STEP_COL_STRIDE
        return "\n".join(out)

    def bank(self):
        out = ["pad 64", "sprbank:"]          # a block never straddles a 4096-bit (16^3) boundary
        for b in self.blocks:
            out += [";%#x * dw" % v for v in b] + [";0 * dw"] * (BLK - len(b))
        return "\n".join(out)

    def slots(self):
        """the PROPOSED per-thing slots: [y0 biased lo][y0 biased hi][light row][0], slot 0 unused"""
        out = ["gpslot:"] + [";0 * dw"] * 4
        for y0, lr in zip(self.slot_y0, self.slot_lr):
            b = (y0 + 32768) & 0xFFFF
            out += [";%#x * dw" % v for v in (b & 0xFF, b >> 8, lr, 0)]
        return "\n".join(out)

    def setup_stub(self, i, extra=None):
        """hex.set every register this case needs (the harness cost the BASE variant prices)."""
        r = dict(self.regs[i])
        if extra:
            r.update(extra)
        return ["    hex.set %s, %s, %d" % (REG_NIBBLES[name], name, v) for name, v in r.items()]

    def expected_sprite_rows(self, i):
        c = self.cases[i]
        out = {}
        prev = 0
        for rel, tex in c["runs"]:
            for y in range(max(0, c["y_base"] + prev), min(H, c["y_base"] + rel)):
                out[y] = COLORMAP[c["lr"]][tex]
            prev = rel
        return out


def common_decls():
    """the globals the macros name, beyond wall_renderer.hoisted_scratch_fj()"""
    return ["c_x: hex.vec 2", "c_cexcl: hex.vec 2", "c_fstart: hex.vec 2", "c_gnrow: hex.vec 2",
            "c_sprfl: hex.vec 2", "c_ssy1: hex.vec 2", "c_ssy2: hex.vec 2", "c_sy0b: hex.vec 4",
            "c_sblk: hex.vec 4", "c_slr: hex.vec 2", "c_ssy1b: hex.vec 2", "c_ssy2b: hex.vec 2",
            "c_sy0bb: hex.vec 4", "c_sblkb: hex.vec 4", "c_slrb: hex.vec 2",
            "c_wlit: hex.vec 2", "c_wlit2: hex.vec 2", "c_wstrip: hex.vec w/4",
            "c_cbufa: hex.vec w/4", "c_cbufd: hex.vec w/4", "c_fbufa: hex.vec w/4",
            "c_fbufd: hex.vec w/4", "c_dummy2: hex.vec 2",
            "seg_w1rf: hex.vec 1", "w1rslv: hex.vec 1", "seg_litf: hex.vec 2",
            "gnrow2: hex.vec 2", "gnrow3: hex.vec 2", "vzcbase: hex.vec w/4",
            "wstripbase: hex.vec w/4",
            "ucnt: hex.vec 2", "u1y1: hex.vec 2", "u1y2: hex.vec 2", "u1cls: hex.vec 2",
            "u1bp: hex.vec %d" % (cfg.PID_BYTES * 2), "u2y1: hex.vec 2", "u2y2: hex.vec 2",
            "u2cls: hex.vec 2", "u2bp: hex.vec %d" % (cfg.PID_BYTES * 2),
            "lcnt: hex.vec 2", "l1y1: hex.vec 2", "l1y2: hex.vec 2", "l1cls: hex.vec 2",
            "l1bp: hex.vec %d" % (cfg.PID_BYTES * 2), "l2y1: hex.vec 2", "l2y2: hex.vec 2",
            "l2cls: hex.vec 2", "l2bp: hex.vec %d" % (cfg.PID_BYTES * 2),
            "comp_ret: ;0", "_pcnt: hex.vec 8", "_plim: hex.vec 8",
            # the PROPOSED path's registers (gp_sprite_col.fj)
            "c_s: hex.vec 2", "gps_cur_s: hex.vec 2", "gps_y0: hex.vec 4", "gps_lr: hex.vec 2",
            "gps_sidx: hex.vec w/4", "gps_sbase: hex.vec w/4", "gps_ptr: hex.vec w/4",
            "gps_r0: hex.vec 4", "gps_last: hex.vec 4", "gps_ybase: hex.vec 4",
            "gps_top: hex.vec 4", "gps_sy1: hex.vec 4", "gps_sy2: hex.vec 4",
            "gps_smidx: hex.vec 4", "gps_cvh: hex.vec 4", "gps_rel: hex.vec 4",
            "gps_yabs: hex.vec 4", "gps_boff: hex.vec w/4"]


def emit_tables():
    return "\n".join([
        generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2),
        generate_emit_dispatch_table_fj("cm", CMV, index_nibbles=_index_nibbles(len(CMV)),
                                        over_align=True)])


TODAY_EMIT = ("stream.emit_col_lines %d, %d, 0, 0, 1, %d, 0, 1, 1, 1, 6, 1, 1, 1, c_gnrow, c_x, "
              "c_cexcl, c_fstart, c_dummy2, c_dummy2, c_dummy2, c_dummy2, c_dummy2, c_dummy2, "
              "c_dummy2, c_dummy2, c_sprfl, c_ssy1, c_ssy2, c_sy0b, c_sblk, c_slr, c_ssy1b, "
              "c_ssy2b, c_sy0bb, c_sblkb, c_slrb, c_wlit, c_wlit2, c_wstrip, wstripbase, "
              "c_cbufa, c_cbufd, c_fbufa, c_fbufd" % (cfg.CENTERY, H, WPXSTRIDE))


PROP_EMIT = ("gpspr.emit_col %d, %d, 6, c_gnrow, c_x, c_cexcl, c_fstart, c_sprfl, c_s, c_sblk, "
             "c_wlit, c_wlit2, c_cbufa, c_cbufd, c_fbufa, c_fbufd" % (cfg.CENTERY, H))
PROP_FJ = HERE / "gp_sprite_col.fj"
PROP2_EMIT = ("gpspr.emit_col2 %d, %d, c_gnrow, c_x, c_cexcl, c_fstart, c_sprfl, c_s, c_sblk, "
              "c_wlit, c_wlit2, c_cbufa, c_cbufd, c_fbufa, c_fbufd" % (cfg.CENTERY, H))


def program(frame, leaf_body, passes, extra_text="", per_case_extra=None, only=None,
            pre_loop=(), lite=False, hot_text="", prefilled_slots=True, shift_pre=0, shift_leaf=0):
    """Main: startup, tables, then `passes` x (for each case: setup stub; fcall the leaf).
    `leaf_body` is the component under test (fj lines), expanded ONCE as a shared leaf.
    `lite` leaves out the emit tables, the band walkers and the W1R walkers (record/load probes).
    `hot_text` is placed right after the startup behind a jump guard -- the renderer's own hot-data
    block, which the narrow 5-nibble pointer arm (frame.arm5) of the slot loaders requires.
    `shift_pre` / `shift_leaf` insert that many DEAD ops (jumped over / unreachable) before the
    pre-loop code / before the leaf: a LAYOUT-NOISE control -- the same logic at other addresses."""
    idx = list(range(len(frame.cases))) if only is None else list(only)
    tables = ([emit_tables()] if lite == "emit" else [] if lite else
              [emit_tables(),
               generate_bands_walk_fj(frame.band_lists(), index_nibbles=cfg.BAND_NIBBLES),
               generate_w1r_walls_fj(rm.W1R_TIER_BOUNDS, rm.W1R_PATTERNS)])
    hot = [";_hot_end", hot_text, "_hot_end:"] if hot_text else []
    lines = ["stl.startup_and_init_all", *hot, *tables,
             "    hex.set w/4, vzcbase, 0",
             *([";_shp_end", "rep(%d, i) stl.fj 0, 0" % shift_pre, "_shp_end:"] if shift_pre else []),
             *pre_loop,
             "    hex.set 8, _pcnt, 0",
             "    hex.set 8, _plim, %d" % passes,
             "_ploop:",
             "    hex.cmp 8, _pcnt, _plim, _pbody, _pdone, _pdone",
             "_pbody:"]
    for i in idx:
        lines += frame.setup_stub(i, (per_case_extra or {}).get(i))
        lines.append("    stl.fcall comp_leaf, comp_ret")
    lines += ["    hex.inc 8, _pcnt",
              "    ;_ploop",
              "_pdone:",
              "    stl.loop",
              *(["rep(%d, i) stl.fj 0, 0" % shift_leaf] if shift_leaf else []),
              "comp_leaf:"]
    lines += ["    " + ln for ln in leaf_body]
    lines += ["    stl.fret comp_ret"]
    slots = frame.slots() if prefilled_slots else "\n".join(["gpslot:"] + [";0 * dw"] * (4 * 256))
    lines += common_decls() + [wr.hoisted_scratch_fj(cfg), frame.stepcol(), frame.bank(),
                               slots, extra_text, ""]
    return "\n".join(lines)


def assemble_run(text, name, extra_fj=(), tmp=None, want_output=True):
    tmp = Path(tmp or tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    p = tmp / (name + ".fj")
    p.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC],
                 *[Path(e).resolve() for e in extra_fj], p.resolve()], out,
                memory_width=W, print_time=False)
    io = FixedIO(b"")
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    cause = str(term.termination_cause)
    # a run that did not end in the program's own `stl.loop` is not a price (a bad pointer ends
    # the run early with FEWER ops -- which reads as a saving)
    assert "loop" in cause.lower(), "%s ended with %s after %d ops" % (name, cause, term.op_counter)
    return term.op_counter, (io.get_output(allow_incomplete_output=True) if want_output else b"")


def decode(stream):
    """0x0B column records -> list of (x, {row: colour}) in stream order."""
    cols = []
    i = 0
    n = len(stream)
    while i < n:
        x = stream[i]
        i += 1
        if i < n and stream[i] == 0xFE:
            cols.append((x, "DITTO"))
            i += 1
            continue
        px = {}
        row = 0
        while True:
            y2 = stream[i]
            i += 1
            if y2 == 0xFF:
                break
            c = stream[i]
            i += 1
            assert y2 >= row, "non-monotone pair at x=%d: %d < %d" % (x, y2, row)
            for y in range(row, y2):
                px[y] = c
            row = y2
        cols.append((x, px))
    return cols
