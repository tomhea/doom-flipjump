"""M8 l12fix (E1M5): the pickup reads a drop at a runtime row PAST 255.

lootcode's `pk_drop` reads dropper k's drop at runtime row `pk_t` (thpos_rt / thss_rt, 16 cells a row). `pk_t` was
2 nibbles at every width, so on a wide-list map (Config.LIST_ID_BITS 12) `hex.set 2, pk_t, 275` kept 0x13 and the
player read row 19: E1M5's m2_std_gate parted at frame 94, the oracle's player taking the drop at row 275 and the fj
one not (p_bc, mdrop, dr_live, thpos_rt[275]). pk_t is now `lootcode.pk_row_nibbles(rows)` wide -- 2 while every
drop row fits a byte (E1M1 / E1M2's text), 3 past it -- in the declaration (loot_parts), the set (pickup_lines) and
the move into the row offset (`_drop_leaf`). tests/host/test_pk_row_width.py holds the emitted text to that width.

RUN: pk_drop on rows 0 .. 299 (255, 256, 275, 299 among them) -- each row's 16.16 position and leaf as planted.
R9: the same program with pk_t at 2 nibbles must read the wrong rows past 255.
"""
import random
import subprocess
import sys
from pathlib import Path

import flipjump as fj

from doomfj import lootcode as L
from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.harness import W

ROOT = Path(__file__).resolve().parents[2]
FJ_NAMES = ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
            "plane_bands.fj", "stream_render.fj")
CFG = wr.tier_cfg(Config(), "game")
NROW = 300
ROWS = [0, 7, 19, 254, 255, 256, 257, 275, 288, 299]
RUNNER = r"""
import sys
import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
io = FixedIO(b"")
term = fj.run(sys.argv[1], io_device=io, print_time=False, print_termination=False)
print(str(term.termination_cause))
print(io.get_output(allow_incomplete_output=True).decode("ascii", "replace").replace(chr(10), "|"))
"""


def _data():
    rnd = random.Random(0x275)
    pos = [(rnd.randrange(1 << 32), rnd.randrange(1 << 32)) for _ in range(NROW)]
    leaf = [rnd.randrange(1, 0x1000) for _ in range(NROW)]
    return pos, leaf


def _program(nib):
    pos, leaf = _data()
    body = ["stl.startup_and_init_all"]
    for t in ROWS:
        body += ["hex.set %d, pk_t, %d" % (nib, t), "stl.fcall pk_drop, pk_dret",
                 "hex.print_as_digit 8, pk_tx, 0", "hex.print_as_digit 8, pk_ty, 0", "hex.print_as_digit 3, ptss, 0",
                 "stl.output 10"]
    body += ["stl.loop",
             "ms_seed_leaf:", "    hex.set 8, cp_seedf, 0", "    stl.fret ms_seed_ret",     # stand-ins: the seed and
             "pk_boxz:", "    stl.fret pk_bret"]                                           # the box are not tested
    body += L._drop_leaf(False, nib)
    decls = ["pk_t: hex.vec %d" % nib, "pk_off: hex.vec w/4", "pk_base: hex.vec w/4", "pk_ptr: hex.vec w/4",
             "pk_pos: hex.vec 16", "pk_tx: hex.vec 8", "pk_ty: hex.vec 8", "pk_tz: hex.vec 8", "ptss: hex.vec w/4",
             "cp_seedf: hex.vec 8", "pk_dret: hex.vec w/4", "ms_seed_ret: hex.vec w/4", "pk_bret: hex.vec w/4"]
    rows = (["thpos_rt:"] + ["hex.vec 16, %d" % (x | y << 32) for x, y in pos]
            + ["thss_rt:"] + ["hex.vec 16, %d" % v for v in leaf])
    return "\n".join(body + decls + [wr.hoisted_scratch_fj(CFG)] + rows) + "\n"


def _want():
    pos, leaf = _data()
    return "|".join("%08x%08x%03x" % (pos[t][0], pos[t][1], leaf[t]) for t in ROWS) + "|"


def _run(tmp, name, nib, timeout=600):
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    files = [(ROOT / "src" / "fj" / f).resolve() for f in FJ_NAMES]
    prog = tmp / (name + ".fj")
    prog.write_text(_program(nib), encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *files, prog.resolve()], out, memory_width=W, print_time=False)
    try:
        r = subprocess.run([sys.executable, "-c", RUNNER, str(out)], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    cause, _, data = r.stdout.strip().partition("\n")
    return data.strip() if "loop" in cause.lower() else None


def test_the_width_follows_the_rows():
    assert L.pk_row_nibbles(ROWS) == 3 and L.pk_row_nibbles([0, 255]) == 2 and L.pk_row_nibbles([]) == 2


def test_the_drop_rows_past_255_read_as_planted(tmp_path):
    assert _run(tmp_path, "wide", L.pk_row_nibbles(ROWS)) == _want()


def test_control_a_two_nibble_row_reads_the_wrong_drop(tmp_path):
    """R9: pk_t at 2 nibbles (the bug) -- rows 256 .. 299 read rows 0 .. 43; rows below 256 still right"""
    got = _run(tmp_path, "narrow", 2, timeout=300)
    assert got is not None and got != _want()
    good = [r for r, (g, w) in zip(ROWS, zip(got.split("|"), _want().split("|"))) if g == w]
    assert good == [r for r in ROWS if r < 256], good
