"""M8 wave 1 (config.Config.THSS_COLD, E1M4): `thss_rt` declared PAST the hot data block. frame.arm5 -- the narrow
pointer arm -- moves only an address's low five hexes, exact only while the LAST arm lies in the same 16^5-bit window;
thss_rt inside the block left lootcode's `pk_drop` (its one game-tier pointer reader) armed in the window, and outside
it would leave a narrow read that follows with the wrong high hexes. RUN: the build's layout (`pad 16384`, a hot byte
array and `thnext` in one window; thpos_rt and thss_rt in the NEXT window), `pk_drop(thss_cold=True)` on random rows,
then a `frame.read_byte5` into the hot array -- the drop's position and leaf and the narrow read all as the data says.

R9 (MUTANT): pk_drop WITHOUT the re-arm (`thss_cold` False) on the same layout must part (the narrow read goes wild --
a wrong byte, a wild jump or no end, all caught: the run is a subprocess with a timeout).
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
NROW, NHOT, N = 24, 64, 60
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
    rnd = random.Random(0x7C)
    pos = [(rnd.randrange(1 << 32), rnd.randrange(1 << 32)) for _ in range(NROW)]
    leaf = [rnd.randrange(1, 0x1000) for _ in range(NROW)]
    hot = [rnd.randrange(256) for _ in range(NHOT)]
    recs = [(rnd.randrange(NROW), rnd.randrange(NHOT)) for _ in range(N)]
    return pos, leaf, hot, recs


def _program(thss_cold):
    pos, leaf, hot, recs = _data()
    body = ["stl.startup_and_init_all"]
    for t, k in recs:
        body += ["hex.set 2, pk_t, %d" % t, "stl.fcall pk_drop, pk_dret",
                 "hex.print_as_digit 8, pk_tx, 0", "hex.print_as_digit 8, pk_ty, 0", "hex.print_as_digit 3, ptss, 0",
                 "hex.set w/4, hp, hb + %d*dw" % k, "frame.read_byte5 hv, hp", "hex.print_as_digit 2, hv, 0",
                 "stl.output 10"]
    body += ["stl.loop",
             "ms_seed_leaf:", "    hex.set 8, cp_seedf, 0", "    stl.fret ms_seed_ret",     # stand-ins: the seed and
             "pk_boxz:", "    stl.fret pk_bret"]                                           # the box are not tested
    body += L._drop_leaf(thss_cold)
    decls = ["pk_t: hex.vec 2", "pk_off: hex.vec w/4", "pk_base: hex.vec w/4", "pk_ptr: hex.vec w/4",
             "pk_pos: hex.vec 16", "pk_tx: hex.vec 8", "pk_ty: hex.vec 8", "pk_tz: hex.vec 8", "ptss: hex.vec w/4",
             "cp_seedf: hex.vec 8", "pk_dret: hex.vec w/4", "ms_seed_ret: hex.vec w/4", "pk_bret: hex.vec w/4",
             "hp: hex.vec w/4", "hv: hex.vec 2"]
    hot_block = (["pad 16384", "hb:"] + [";%d * dw" % b for b in hot]
                 + ["thnext: hex.vec 16"])                                  # the window's base: arm5's
    cold = (["pad 16384",                                                   # the NEXT window
             "thpos_rt:"] + ["hex.vec 16, %d" % (x | y << 32) for x, y in pos]
            + ["thss_rt:"] + ["hex.vec 16, %d" % v for v in leaf])
    return "\n".join(body + decls + [wr.hoisted_scratch_fj(CFG)] + hot_block + cold) + "\n"


def _want():
    pos, leaf, hot, recs = _data()
    return "|".join("%08x%08x%03x%02x" % (pos[t][0], pos[t][1], leaf[t], hot[k]) for t, k in recs) + "|"


def _run(tmp, name, thss_cold, timeout=600):
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    files = [(ROOT / "src" / "fj" / f).resolve() for f in FJ_NAMES]
    prog = tmp / (name + ".fj")
    prog.write_text(_program(thss_cold), encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *files, prog.resolve()], out, memory_width=W, print_time=False)
    try:
        r = subprocess.run([sys.executable, "-c", RUNNER, str(out)], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    cause, _, data = r.stdout.strip().partition("\n")
    return data.strip() if "loop" in cause.lower() else None


def test_the_rows_read_and_the_narrow_arm_stays_exact_after_a_cold_drop(tmp_path):
    assert _run(tmp_path, "cold", True) == _want()


def test_control_without_the_rearm_the_narrow_arm_goes_wild(tmp_path):
    assert _run(tmp_path, "warm", False, timeout=300) != _want(), "no re-arm passed: the layout proves nothing"
