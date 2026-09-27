"""M7 P1.6 -- the SHIPPED fragment derive and walker, drawing native lists through the rowmap.

`stream.frag_derive` + `stream.frag_runs` (src/fj/stream_render.fj) run over a bank of native lists
(`doomfj.spritebank.bank_list`, laid out by `wall_renderer.sprite_block_body`) with the real
`rowmap` dispatch table (`wall_renderer.sprite_rowmap_fj`), the real `byte` / `cm` emit tables and a
slot table the record's layout (`[y0 + 32768 lo][hi][light row][bucket]`). Every case is one
column: a filler down to the fragment's first row, the fragment's runs, a filler to the bottom --
decoded from the 0x0B stream and compared, row for row, with `strip_at` drawn at the case's bucket
from its bucket top, clipped to the screen and lit through the colormap. Cases cover the FAST path
(the whole column box on screen) and the CLIPPED one (above row 0, past the bottom), every bucket
from each list's `min_b` up.

R9: the same harness over a `stream_render.fj` whose walker SKIPS the rowmap (a run's end is its
normalized row, as a per-bucket bank would have it) must disagree.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj
from doomfj.reference_model import SPRITE_HEIGHT_BUCKETS, SPRITE_RUN_CAP_HD
from doomfj.spritebank import bank_list, strip_at
from doomfj.texturecompiler import _index_nibbles
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
CFG = Config()
H = CFG.VIEW_H
MW = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
COLORMAP = MW.colormap()
CMV = wr.colormap_values(MW, lights=wr.COLORMAP_LIGHTS)
HEIGHTS = wr.sprite_bucket_heights(CFG)
N_LISTS, FILLER = 18, 7


def _lists(seed=7):
    """random columns -> native lists, of every cap the bank uses, never transparent"""
    rng = random.Random(seed)
    out = []
    while len(out) < N_LISTS:
        dh = rng.choice((9, 28, 55, 64, 100))
        top, bot = rng.randrange(0, dh // 3 + 1), rng.randrange(0, dh // 3 + 1)
        col = [-1 if (v < top or v >= dh - bot or rng.random() < 0.15) else rng.randrange(1, 200)
               for v in range(dh)]
        bl = bank_list(col, dh, rng.choice((4, 12, SPRITE_RUN_CAP_HD)), HEIGHTS)
        if bl is not None and bl[1] < SPRITE_HEIGHT_BUCKETS:
            out.append(bl)
    return out


def _cases(lists, seed=11):
    """(list index, bucket, y0, light row): buckets from min_b up; tops on screen, above it, below"""
    rng = random.Random(seed)
    out = []
    for i, bl in enumerate(lists):
        for _ in range(3):
            b = rng.randrange(bl[1], SPRITE_HEIGHT_BUCKETS)
            hb = HEIGHTS[b]
            y0 = rng.choice((rng.randrange(0, max(1, H - hb + 1)),      # the fast path
                             -rng.randrange(1, hb + 1),                   # clipped above
                             H - rng.randrange(1, hb + 1)))               # clipped below
            out.append((i, b, y0, rng.randrange(0, 16)))
    return out


def _expected(lists, case):
    i, b, y0, lr = case
    r0, runs = strip_at(lists[i], b, HEIGHTS[b])
    rows, prev = {}, 0
    for e, t in runs:
        for y in range(y0 + r0 + prev, y0 + r0 + e):
            if 0 <= y < H:
                rows[y] = COLORMAP[lr][t]
        prev = e
    return rows


def _program(lists, cases):
    slots = ["gpslot:"] + [";0 * dw"] * 4                    # slot 0: no fragment
    for _i, b, y0, lr in cases:
        yb = (y0 + 32768) & 0xFFFF
        slots += [";%#x * dw" % v for v in (yb & 0xFF, yb >> 8, lr, b)]
    bank = wr.sprite_bank_header()
    for bl in lists:
        body = wr.sprite_block_body(bl, SPRITE_HEIGHT_BUCKETS)
        bank += [";%#x * dw" % v for v in body] + [";0 * dw"] * (wr.SPR_BLOCK_STRIDE - len(body))
    main = ["stl.startup_and_init_all",
            generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2),
            generate_emit_dispatch_table_fj("cm", CMV, index_nibbles=_index_nibbles(len(CMV)),
                                            over_align=True),
            wr.sprite_rowmap_fj(CFG),
            "    hex.set 4, gps_cvh, %d" % H]
    for k, (i, _b, _y0, _lr) in enumerate(cases):
        main += ["    stl.output_char %d" % k,
                 "    hex.set 2, t_s, %d" % (k + 1),
                 "    hex.set 4, t_blk, %d" % i,
                 "    stream.frag_derive t_s, t_blk, gps_ybase, gps_top, gps_sy1, gps_sy2, "
                 "gps_smidx, gps_ptr, gps_ridx",
                 "    byte.emit gps_sy1",                          # a filler down to the fragment
                 "    stl.output_char %d" % FILLER,
                 "    stream.frag_runs gps_ybase, gps_top, gps_smidx, gps_ptr, gps_ridx",
                 "    stl.output_char %d" % H,                     # ... and one to the bottom
                 "    stl.output_char %d" % FILLER,
                 "    stl.output_char 0xFF"]
    main += ["    stl.loop",
             "t_s: hex.vec 2", "t_blk: hex.vec 4",
             wr.hoisted_scratch_fj(CFG), *slots, *bank, ""]
    return "\n".join(main)


def _run(tmp, name, text, src=SRC):
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    p = tmp / (name + ".fj")
    p.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *[s.resolve() for s in src], p.resolve()], out,
                memory_width=W, print_time=False)
    io = FixedIO(b"")
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    assert "loop" in str(term.termination_cause).lower(), term.termination_cause
    return io.get_output(allow_incomplete_output=True)


def _decode(stream):
    """[column records] -> {x: {row: colour}}, the device's grammar (a run never moves backwards)"""
    cols, i = {}, 0
    while i < len(stream):
        x, row, px = stream[i], 0, {}
        i += 1
        while stream[i] != 0xFF:
            y2, c = stream[i], stream[i + 1]
            i += 2
            assert row <= y2 <= H, (x, row, y2)
            for y in range(row, y2):
                px[y] = c
            row = y2
        i += 1
        cols[x] = px
    return cols


def _faults(lists, cases, stream):
    try:
        cols = _decode(stream)
    except AssertionError as e:                 # a stream the device itself would refuse
        return ["undecodable: %s" % (e,)]
    bad = []
    for k, case in enumerate(cases):
        got = {y: c for y, c in cols[k].items() if c != FILLER or y in _expected(lists, case)}
        if got != _expected(lists, case):
            bad.append((case, sorted(set(got.items()) ^ set(_expected(lists, case).items()))[:6]))
    return bad


@pytest.fixture(scope="module")
def world():
    lists = _lists()
    cases = _cases(lists)
    kinds = {"fast": 0, "above": 0, "below": 0}
    for _i, b, y0, _lr in cases:
        kinds["above" if y0 < 0 else "below" if y0 + HEIGHTS[b] > H else "fast"] += 1
    assert all(kinds.values()), kinds                          # every path is walked
    return lists, cases


def test_the_shipped_walker_draws_what_strip_at_draws(world, tmp_path):
    lists, cases = world
    assert _faults(lists, cases, _run(tmp_path, "bank", _program(lists, cases))) == []


def test_a_walker_that_skips_the_rowmap_is_caught(world, tmp_path):
    """R9: a run's end left NORMALIZED (the rowmap lookup replaced by a copy) must fail the check"""
    lists, cases = world
    src = (ROOT / "src/fj/stream_render.fj").read_text(encoding="utf-8")
    mut = src.replace("        rowmap.lookup gps_rel, ridx             // M7 P1.6: its row below the bucket top",
                      "        hex.mov 2, gps_rel, ridx", 1)
    assert mut != src, "re-point this mutant: the walker's rowmap lookup moved"
    (tmp_path / "stream_render.fj").write_text(mut, encoding="utf-8")
    mutated = [s if s.name != "stream_render.fj" else tmp_path / "stream_render.fj" for s in SRC]
    assert _faults(lists, cases, _run(tmp_path, "mut", _program(lists, cases), mutated))
