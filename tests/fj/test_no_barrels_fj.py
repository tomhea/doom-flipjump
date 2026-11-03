"""M8 C10: the degenerate barrel package RUNS in fj -- E1M1 without its barrels (tests/fixtures/map_variants.no_barrels):
`bar_phase` (barrelcode.phase_lines: no stub, the lvdone guard, bar_next) is called and returns, the barrel cells are the
dead slot the decls give; `bl_los` (monstersight.blast_los_lines with no spot) returns sl_hit 0 for a static trace
(no barrel ever asks one) and runs the rocket's far LOS (`sl_far`, a stub here that marks its call) when bl_dyn is 1.
The texts assembled are the emitter's own (barrelcode.barrel_parts' pieces on the World).
R9 (MUTANTS): the static path reporting a hit, the dynamic path skipping sl_far, a phase that runs on a frozen
level (its guard dropped: the stub after it counts) -- each must change the output.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import barrelcode as BC
from doomfj.harness import W
from doomfj.monstersight import blast_los_lines
from doomfj.wad import WadFile
from doomfj.world import World
from tests.fixtures.map_variants import no_barrels

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"


@pytest.fixture(scope="module")
def w0():
    return World(no_barrels(WadFile.from_path(FIX), "E1M1"), "E1M1", player="final", monsters="final")


def program(w0, muts=()):
    phase = BC.phase_lines(w0, fight=True)
    los = blast_los_lines(w0, [], 30, fight=True, dyn=True)
    decls = [d for d in BC.decls(w0, 2) if d.split(":")[0] in ("bar_st", "bar_ti", "bar_hp")]
    pr = ["    hex.print_as_digit 1, sl_hit, 0", "    stl.output 32"]
    body = ["stl.startup_and_init_all",
            "hex.set 1, lvdone, 0", "stl.fcall bar_phase, bar_pret", "stl.output 65",
            "hex.set 1, lvdone, 1", "stl.fcall bar_phase, bar_pret", "stl.output 66",
            "hex.set 1, bl_dyn, 0", "hex.set 1, sl_hit, 1", "stl.fcall bl_los, bl_lret", *pr,
            "hex.set 1, bl_dyn, 1", "stl.fcall bl_los, bl_lret", *pr,
            "hex.print_as_digit 2, bar_st, 0", "hex.print_as_digit 1, bar_ti, 0",
            "stl.loop",
            *phase, *los, *BC.tables_fj(),
            "sl_far:", "    hex.set 1, sl_hit, 1", "    stl.output 70", "    stl.fret sf_ret",
            *decls, "lvdone: hex.vec 1", "bl_dyn: hex.vec 1", "sl_hit: hex.vec 1", "sf_ret: hex.vec w/4",
            "mm_x: hex.vec 4", "mm_y: hex.vec 4", "mt_tqx: hex.vec 8", "mt_tqy: hex.vec 8",
            "bl_px: hex.vec 4", "bl_py: hex.vec 4", "bl_qx: hex.vec 8", "bl_qy: hex.vec 8", "bl_lret: hex.vec w/4",
            "bar_pret: hex.vec w/4", "bn_ret: hex.vec w/4", "bw_st: hex.vec 2", "bw_ti: hex.vec 1",
            "bw_fl: hex.vec 1", "bw_n: hex.vec 4", "bar_solid: hex.vec 1"]
    text = "\n".join(body) + "\n"
    for old, new in muts:
        assert old in text, old
        text = text.replace(old, new)
    return text


def _run(tmp, name, text):
    src = tmp / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False, max_ops=10 ** 6) \
        if "max_ops" in fj.run.__code__.co_varnames else \
        fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True)


WANT = b"AB0 F1 000"


def test_the_degenerate_package_runs(tmp_path, w0):
    text = program(w0)
    assert "bp0_" not in text and "bl_ls0" not in text
    assert _run(tmp_path, "nb", text) == WANT


MUTS = {
    "static_hits": [("  bl_lst:\nbl_ldone:\n    stl.fret bl_lret\n", "  bl_lst:\n    hex.set 1, sl_hit, 1\nbl_ldone:\n"
                                                                         "    stl.fret bl_lret\n")],
    "dyn_skips_far": [("    stl.fcall sl_far, sf_ret\n", "")],
    "phase_runs_frozen": [("    hex.if1 1, lvdone, bar_ph_out\n", "    stl.output 90\n")],
}


@pytest.mark.parametrize("mut", sorted(MUTS))
def test_a_broken_degenerate_package_is_caught(tmp_path, w0, mut):
    assert _run(tmp_path, "nb_" + mut, program(w0, MUTS[mut])) != WANT
