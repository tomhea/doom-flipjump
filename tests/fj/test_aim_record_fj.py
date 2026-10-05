"""M7 P4.2a -- the aim window's leaf (`doomfj.aimcode`, the REAL emitted text) against the box rule of
docs/gp-aim-window.md 1.3-1.6, stated here independently in Python: P = FixedMul(tx, xscale), Q = r_eff * xscale,
x1 = (centerxfrac + P - Q) >> 16, x2 = ((centerxfrac + P + Q) >> 16) - 1, clipped to 72..88; a column a solid wall drew
is skipped; an empty cell or a strictly nearer integer depth takes the thing; nothing beyond 2048 units.

Each record pokes a thing (tz, tx, xscale, id, radius class), the 17 `drawn` flags and the window's prior cells, runs
the leaf, and prints the window.

R9: four mutants, each caught: the radius one larger; a tie overwriting (>= instead of >); `drawn` ignored; the range
test gone.

M7 P6: the same leaf with BARRELS (`leaf_lines(barrels=True)`): radius class 2 (aimcode.RC_BARREL) reads the third
r_eff, ids reach 76; its control reads class 2 as class 1.
"""
import random
import struct

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import aimcode as AC
from doomfj.config import GAME_CFG
from doomfj.fixedpoint import fixed_mul
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj

M32 = 0xFFFFFFFF
N = 400
CENTERX = GAME_CFG.CENTERX
REFF = (23, 37, 13)                     # fixed r_eff values for the harness (the table is the oracle's business)
MUTS = {
    "r+1": ("hex.mov 2, ar_r16 + 4*dw, aim_rr\n", "hex.mov 2, ar_r16 + 4*dw, aim_rr\nhex.inc 8, ar_r16 + 4*dw\n"),
    "tie": ("hex.cmp 3, ar_tzi, aim_tz + 0*dw, aimw0, aimx0, aimx0", "hex.cmp 3, ar_tzi, aim_tz + 0*dw, aimw0, aimw0, aimx0"),
    "drawn": ("hex.if0 1, drawn + 80*dw, aimo8", "hex.if0 0, drawn + 80*dw, aimo8"),
    "range": ("hex.cmp 8, pth_tz, ar_maxtz, ar_in, ar_in, ar_out", "hex.cmp 8, pth_tz, ar_maxtz, ar_in, ar_in, ar_in"),
}


def _signed(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _ref(tz, tx, xscale, sid, rc, drawn, sids, tzs):
    sids, tzs = list(sids), list(tzs)
    if tz > AC.MAXTZ:
        return sids
    r = REFF[rc]
    p = fixed_mul(tx & M32, xscale & M32, 8, 4)
    q = fixed_mul((r << 16) & M32, xscale & M32, 8, 4)
    x1 = _signed((CENTERX << 16) + p - q) >> 16
    x2 = (_signed((CENTERX << 16) + p + q) >> 16) - 1
    lo, hi = max(x1, AC.FIRST), min(x2, AC.FIRST + AC.NCOLS - 1)
    for x in range(lo, hi + 1):
        c = x - AC.FIRST
        if drawn[c]:
            continue
        if sids[c] == 0 or (tz >> 16) < tzs[c]:
            sids[c], tzs[c] = sid, tz >> 16
    return sids


def _records(seed=3, barrels=False):
    rng = random.Random(seed)
    out = []
    for _ in range(N):
        tz = rng.choice([rng.randrange(16 << 16, 400 << 16), rng.randrange(16 << 16, 2200 << 16)])
        xscale = ((CENTERX << 16) << 16) // tz
        tx = rng.randrange(-(tz >> 4), (tz >> 4) + 1)          # near the centre: most boxes meet the window
        sid, rc = rng.randrange(1, 77 if barrels else 54), rng.randrange(3 if barrels else 2)
        drawn = [int(rng.random() < 0.2) for _ in range(AC.NCOLS)]
        sids = [rng.choice([0, 0, rng.randrange(1, 54)]) for _ in range(AC.NCOLS)]
        tie = rng.random() < 0.35                               # equal depths: a tie must NOT overwrite
        tzs = [(tz >> 16 if tie else rng.randrange(0, 0x800)) if s else 0 for s in sids]
        out.append((tz, tx, xscale, sid, rc, drawn, sids, tzs))
    return out


BARREL_MUTS = {"rc2": ("hex.if_flags sp_rc, %d, ar_r30, ar_r10" % (1 << AC.RC_BARREL),
                       "hex.if_flags sp_rc, %d, ar_r30, ar_r30" % (1 << AC.RC_BARREL))}


def _program(mut=None, barrels=False):
    leaf = "\n".join(AC.leaf_lines(CENTERX, barrels=barrels))
    if mut:
        old, new = {**MUTS, **BARREL_MUTS}[mut]
        assert leaf.count(old) == 1, (mut, leaf.count(old))
        leaf = leaf.replace(old, new)
    nib = lambda n: sum(1 for _ in range(n))                     # noqa: E731
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, pth_tz", "hex.input 4, pth_tx", "hex.input 4, pth_xscale",
            "hex.input 1, sp_sid", "hex.input 1, rcin", "hex.mov 1, sp_rc, rcin",
            *["hex.input 1, din\nhex.mov 1, drawn + %d*dw, din" % (AC.FIRST + c) for c in range(AC.NCOLS)],
            *["hex.input 1, aim_sid + %d*dw" % (2 * c) for c in range(AC.NCOLS)],
            *["hex.input 2, tzin\nhex.mov 3, aim_tz + %d*dw, tzin" % (3 * c) for c in range(AC.NCOLS)],
            "stl.fcall aim_record, aim_ret",
            *["hex.print_as_digit 2, aim_sid + %d*dw, 0\nstl.output 44" % (2 * c) for c in range(AC.NCOLS)],
            "stl.output 10", ";loop",
            "done:", "stl.loop",
            leaf,
            "rmagic: hex.vec 2", "rcin: hex.vec 2", "din: hex.vec 2", "tzin: hex.vec 4",
            "pth_tz: hex.vec 8", "pth_tx: hex.vec 8", "pth_xscale: hex.vec 8",
            "drawn:\n" + "\n".join(";0 * dw" for _ in range(GAME_CFG.VIEW_W)),
            *AC.decls(barrels),
            # the harness's r_eff pair, where the frame's prologue would have looked it up
            ]
    if barrels:
        text = "\n".join(body).replace("aim_rr: hex.vec 6", "aim_rr: hex.vec 6, %d" % (REFF[0] | REFF[1] << 8
                                                                                          | REFF[2] << 16))
    else:
        text = "\n".join(body).replace("aim_rr: hex.vec 4", "aim_rr: hex.vec 4, %d" % (REFF[0] | REFF[1] << 8))
    return text + "\n"


def _run(tmp_path, name, mut=None, barrels=False):
    src = tmp_path / (name + ".fj")
    src.write_text(_program(mut, barrels), encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    from pathlib import Path
    fjdir = Path(__file__).resolve().parents[2] / "src" / "fj"
    fj.assemble([consts.resolve(), (fjdir / "fixed_point.fj").resolve(), (fjdir / "frame_render.fj").resolve(),
                 (fjdir / "projection.fj").resolve(), src.resolve()], out, memory_width=W, print_time=False)
    recs = _records(barrels=barrels)
    feed = b""
    for tz, tx, xs, sid, rc, drawn, sids, tzs in recs:
        feed += bytes([1]) + struct.pack("<III", tz & M32, tx & M32, xs & M32) + bytes([sid, rc])
        feed += bytes(drawn) + bytes(sids) + b"".join(struct.pack("<H", t) for t in tzs)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = [[int(v, 16) for v in line.split(",")[:AC.NCOLS]]
           for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:N]]
    want = [_ref(*r) for r in recs]
    return got, want, recs


def test_the_leaf_is_the_box_rule(tmp_path):
    got, want, recs = _run(tmp_path, "aim")
    bad = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), None)
    assert len(got) == N and bad is None, "record %d: %s != %s" % (bad, got[bad], want[bad])
    # vacuity: boxes landed, some on closed columns, some over earlier cells, some beyond the range
    changed = sum(1 for g, r in zip(got, recs) if g != r[6])
    assert changed > N // 4, changed
    assert any(r[0] > AC.MAXTZ for r in recs)


@pytest.mark.parametrize("mut", sorted(MUTS))
def test_the_checks_catch_a_broken_leaf(tmp_path, mut):
    got, want, _ = _run(tmp_path, mut, mut)
    assert got != want, "the mutant %s went unnoticed" % mut


def test_the_leaf_with_barrels_is_the_box_rule(tmp_path):
    got, want, recs = _run(tmp_path, "aimb", barrels=True)
    bad = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), None)
    assert len(got) == N and bad is None, "record %d: %s != %s" % (bad, got[bad], want[bad])
    assert sum(1 for r in recs if r[4] == AC.RC_BARREL) > N // 5 and max(r[3] for r in recs) > 53


@pytest.mark.parametrize("mut", sorted(BARREL_MUTS) + ["r+1"])
def test_the_checks_catch_a_broken_barrel_leaf(tmp_path, mut):
    got, want, _ = _run(tmp_path, "b" + mut, mut, barrels=True)
    assert got != want, "the mutant %s went unnoticed" % mut


def test_the_barrel_table_carries_the_third_radius():
    from doomfj.combat import BARREL_R, CombatMixin
    from doomfj.reference_model import ReferenceModel
    rm = ReferenceModel(GAME_CFG)
    old, new = AC.reff_values(rm), AC.reff_values(rm, barrels=True)
    assert [v & 0xFFFF for v in new] == old
    assert [v >> 16 for v in new] == [CombatMixin.aim_radius(rm, i << 24, BARREL_R) for i in range(256)]
