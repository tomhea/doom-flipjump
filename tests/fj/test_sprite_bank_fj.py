"""M7 P1.6 -- the SHIPPED sprite column's P1.6 halves in fj: the fragment derive and both run walkers
drawing native lists through the rowmap, and the record's tier / slot / min_b section.

WALKERS. `stream.frag_derive`, `stream.frag_runs` and `stream.frag_runs_win`
(src/fj/stream_render.fj) run over a bank of native lists (`doomfj.spritebank.bank_list`, laid out by
`wall_renderer.sprite_block_body`) with the real `rowmap` dispatch table
(`wall_renderer.sprite_rowmap_fj`), the real `byte` / `cm` emit tables and a slot table in the
record's layout (`[y0 + 32768 lo][hi][light row][bucket]`). Every case is one column, decoded from
the 0x0B stream and compared, row for row, with `strip_at` drawn at the case's bucket from its bucket
top, clipped to the screen and lit through the colormap:
  * frag_runs: a filler down to the fragment's first row, the fragment's runs, a filler to the
    bottom -- the FAST path (the whole bucket box on screen) and the CLIPPED one (above row 0, past
    the bottom), every bucket from each list's `min_b` up;
  * frag_runs_win: a FAR fragment walked TWICE, as emit_col_lines composes A+B -- over the window
    above a near fragment's rows [a1, a2) and over the window below them. The windows cut runs, sit
    on run boundaries, and (lists whose FIRST run maps to no row) land exactly on that empty first
    run: at the upper window's high row (an empty pair, then the walk stops) and at the lower
    window's low row (skipped). Every column is compared WHOLE: the near rows, the far fragment's
    rows outside them, the fillers.

RECORD. The per-thing section of `frame.thing_record_body` that P1.6 rewrote -- the tier's region
(`hdb`, and SPR-NEAR's `thfar` / `lowh`) and the slot's four bytes (byte 3 = the bucket) -- and its
column loop (block = u + region, the column taken iff bucket >= the block's min_b) are TRANSPLANTED
from the shipped source text, so they cannot drift from it, and run for every bucket, near and far,
with three columns a thing whose blocks put min_b just below, at and just above the bucket (the
pattern differs per region, so a wrong region shows in the columns too). The expectation is the
ORACLE's rule (`reference_model.sprite_tier`) and the emitter's layout (HD at sp_base, MID `dw` on,
LD at sp_base2).

R9: the harnesses must reject a walker that skips the rowmap in the fast, the clipped and the window
loop (a run's end left normalized, as a per-bucket bank would have it), and a record whose HD compare,
slot byte 3, min_b compare or thfar test is broken.
"""
import random
import re
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj
from doomfj.reference_model import (DEG_HD_BUDGET, DEG_SPR_LOWRES_H, DEG_SPR_NEAR_TZ,
                                    DEG_SPRB_MINH, SPRITE_HEIGHT_BUCKETS, SPRITE_RUN_CAP_HD,
                                    sprite_bucket, sprite_tier)
from doomfj.spritebank import bank_list, rowmap_row, strip_at
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
N_LISTS, FILLER, FILLER2 = 18, 7, 9        # FILLER2 paints the near fragment's rows in a window case


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


def _zero_first_lists(want=2):
    """[(list, bucket)]: lists whose FIRST run maps to no row at a bucket they are drawn at -- a
    one-row first run just under a transparent top, at a height where its two boundaries round to
    the same screen row"""
    out = []
    for dh in (55, 64, 100):
        for v0 in range(1, dh // 3):
            col = [-1] * v0 + [11] + [22] * (dh // 3) + [33] * (dh // 4)
            bl = bank_list(col + [-1] * (dh - len(col)), dh, SPRITE_RUN_CAP_HD, HEIGHTS)
            for b in range(bl[1], SPRITE_HEIGHT_BUCKETS):
                if rowmap_row(bl[3][0][0], HEIGHTS[b]) == rowmap_row(bl[0], HEIGHTS[b]):
                    out.append((bl, b))
                    break
            if len(out) == want:
                return out
    raise AssertionError("no list with an empty first run: the family above no longer makes one")


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


def _rows(bl, b, y0):
    """the fragment's unclipped rows [first, end) at bucket `b` from bucket top `y0`"""
    r0, runs = strip_at(bl, b, HEIGHTS[b])
    return y0 + r0, y0 + r0 + runs[-1][0]


def _path(lists, case):
    """which loop of stream.frag_runs this case takes: its FAST-path test is on the BUCKET top and
    the fragment's end (0 <= y0 and y0 + rowmap[b][n_last] <= viewh)"""
    i, b, y0, _lr = case
    fast = y0 >= 0 and y0 + rowmap_row(lists[i][2], HEIGHTS[b]) <= H
    return "fast" if fast else "clipped"


def _win_cases(lists, zero_first, seed=13):
    """(list index, bucket, y0, light row, a1, a2): the near fragment covers [a1, a2) and the far one
    (`list index`) is walked over [0, a1) and [a2, H). Per list, one case with the near rows strictly
    INSIDE the far fragment's visible rows (it shows above and below them) and one anywhere; a1 / a2
    fall on a random row or on one of the far fragment's run ends. `zero_first` ((list index,
    bucket) pairs whose first run maps to no row) adds that empty run ON a1 and ON a2."""
    rng = random.Random(seed)
    out = []
    for i, bl in enumerate(lists):
        for inside in (True, False):
            b = rng.randrange(bl[1], SPRITE_HEIGHT_BUCKETS)
            hb = HEIGHTS[b]
            y0 = rng.choice((rng.randrange(0, max(1, H - hb + 1)), -rng.randrange(1, hb + 1),
                             H - rng.randrange(1, hb + 1)))
            r0, runs = strip_at(bl, b, hb)
            ends = [y0 + r0] + [y0 + r0 + e for e, _t in runs]
            lo, hi = max(0, min(H, ends[0])), max(0, min(H, ends[-1]))

            def pick(lo_, hi_):
                on = [e for e in ends if lo_ <= e <= hi_]
                return rng.choice(on) if on and rng.random() < 0.5 else rng.randint(lo_, hi_)
            if inside and hi - lo >= 3:
                a1 = pick(lo + 1, hi - 2)
                a2 = pick(a1 + 1, hi - 1)
            else:
                a1 = pick(lo, hi)
                a2 = pick(a1, max(a1, min(H, ends[-1] + 2)))
            out.append((i, b, y0, rng.randrange(0, 16), a1, a2))
    for i, b in zero_first:
        first = rowmap_row(lists[i][0], HEIGHTS[b])
        y0 = 30 - first                                   # the empty first run lands on row 30
        out.append((i, b, y0, 5, 30, 34))                 # ... the upper window's HIGH row
        out.append((i, b, y0, 6, 26, 30))                 # ... the lower window's LOW row
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


def _win_expected(lists, wcase):
    """the whole column: the near fragment's rows, the far fragment's outside them, fillers"""
    i, b, y0, lr, a1, a2 = wcase
    col = {y: FILLER for y in range(H)}
    col.update({y: c for y, c in _expected(lists, (i, b, y0, lr)).items() if not a1 <= y < a2})
    col.update({y: FILLER2 for y in range(a1, a2)})
    return col


def _program(lists, cases, wcases):
    slots = ["gpslot:"] + [";0 * dw"] * 4                    # slot 0: no fragment
    for _i, b, y0, lr, *_w in list(cases) + list(wcases):
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
    win = "    stream.frag_runs_win gpsb_ybase, gpsb_smidx, gpsb_ptr0, t_wlo, t_whi, gpsb_ridx"
    for j, (i, b, y0, _lr, a1, a2) in enumerate(wcases):
        k = len(cases) + j
        sy1 = max(0, min(H, _rows(lists[i], b, y0)[0]))
        main += ["    stl.output_char %d" % k,
                 "    hex.set 2, t_s, %d" % (k + 1),
                 "    hex.set 4, t_blk, %d" % i,
                 "    stream.frag_derive t_s, t_blk, gpsb_ybase, gpsb_top, gpsb_sy1, gpsb_sy2, "
                 "gpsb_smidx, gpsb_ptr0, gpsb_ridx",
                 # emit_col_lines' order: the region down to where the far fragment starts (or to
                 # the window's end), the far walker over [0, a1), a region to a1, the near rows,
                 # a region to where the far fragment resumes, the far walker over [a2, H)
                 "    stl.output_char %d" % min(a1, sy1), "    stl.output_char %d" % FILLER,
                 "    hex.set 2, t_wlo, 0", "    hex.set 2, t_whi, %d" % a1, win,
                 "    stl.output_char %d" % a1, "    stl.output_char %d" % FILLER,
                 "    stl.output_char %d" % a2, "    stl.output_char %d" % FILLER2,
                 "    stl.output_char %d" % max(a2, sy1), "    stl.output_char %d" % FILLER,
                 "    hex.set 2, t_wlo, %d" % a2, "    hex.set 2, t_whi, %d" % H, win,
                 "    stl.output_char %d" % H, "    stl.output_char %d" % FILLER,
                 "    stl.output_char 0xFF"]
    main += ["    stl.loop",
             "t_s: hex.vec 2", "t_blk: hex.vec 4", "t_wlo: hex.vec 2", "t_whi: hex.vec 2",
             wr.hoisted_scratch_fj(CFG), *slots, *bank, ""]
    return "\n".join(main)


def _assemble_run(tmp, name, text, src):
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


def _faults(world, stream):
    """{"fast" / "clipped" / "window": [faulty cases]} for one run of the walker program"""
    lists, cases, wcases = world
    out = {"fast": [], "clipped": [], "window": []}
    try:
        cols = _decode(stream)
    except AssertionError as e:                 # a stream the device itself would refuse
        return {k: ["undecodable: %s" % (e,)] for k in out}
    for k, case in enumerate(cases):
        want = _expected(lists, case)
        got = {y: c for y, c in cols.get(k, {}).items() if c != FILLER or y in want}
        if got != want:
            out[_path(lists, case)].append((case, sorted(set(got.items()) ^ set(want.items()))[:6]))
    for j, wcase in enumerate(wcases):
        got, want = cols.get(len(cases) + j, {}), _win_expected(lists, wcase)
        if got != want:
            out["window"].append((wcase, sorted(set(got.items()) ^ set(want.items()))[:6]))
    return out


@pytest.fixture(scope="module")
def world():
    lists = _lists()
    zero_first = _zero_first_lists()
    lists_all = lists + [bl for bl, _b in zero_first]
    cases = _cases(lists)
    wcases = _win_cases(lists_all, [(len(lists) + n, b) for n, (_bl, b) in enumerate(zero_first)])
    paths = [_path(lists_all, c) for c in cases]
    assert {"fast", "clipped"} <= set(paths), paths                  # both loops are walked ...
    assert any(y0 < 0 for (_i, _b, y0, _lr), p in zip(cases, paths) if p == "clipped")
    assert any(y0 >= 0 for (_i, _b, y0, _lr), p in zip(cases, paths) if p == "clipped")
    # ... and the far fragment really shows on BOTH sides of the near one in some window cases
    both = [w for w in wcases if max(0, _rows(lists_all[w[0]], w[1], w[2])[0]) < w[4] < w[5]
            < min(H, _rows(lists_all[w[0]], w[1], w[2])[1])]
    assert len(both) >= 8, both
    return lists_all, cases, wcases


@pytest.fixture(scope="module")
def shipped(world, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("walkers")
    return _faults(world, _assemble_run(tmp, "bank", _program(*world), SRC))


def test_the_shipped_walker_draws_what_strip_at_draws(shipped):
    bad = shipped["fast"] + shipped["clipped"]
    assert bad == [], "%d columns differ, first (case, rows) %s" % (len(bad), bad[:2])


def test_the_window_walker_draws_the_far_fragment_outside_the_near_one(shipped):
    bad = shipped["window"]
    assert bad == [], "%d columns differ, first (case, rows) %s" % (len(bad), bad[:2])


def _skip_rowmap(src, macro, label):
    """`src` with the rowmap lookup that first follows `label:` in `stream.<macro>` replaced by a
    copy of the run's NORMALIZED end -- the walker a per-bucket bank would have had"""
    a = src.index("    def %s " % macro)
    b = src.index("\n    def ", a + 1)
    head = "\n      %s:\n" % label
    at = src.index(head, a, b) + len(head)
    k = src.index("rowmap.lookup gps_rel, ridx", at, b)
    assert not re.search(r"^ {6}\w+:", src[at:k], re.M), \
        "re-point this mutant: a label now sits between %s: and its lookup" % label
    return src[:k] + "hex.mov 2, gps_rel, ridx" + src[k + len("rowmap.lookup gps_rel, ridx"):]


@pytest.mark.parametrize("loop,macro,label", [("fast", "frag_runs", "fast_have"),
                                              ("clipped", "frag_runs", "cl_have"),
                                              ("window", "frag_runs_win", "shave")])
def test_a_walker_that_skips_the_rowmap_is_caught(world, tmp_path, loop, macro, label):
    """R9: in each of the three loops, a run's end left NORMALIZED (the rowmap lookup replaced by a
    copy) must fail the check -- in the cases that loop draws"""
    src = (ROOT / "src/fj/stream_render.fj").read_text(encoding="utf-8")
    (tmp_path / "stream_render.fj").write_text(_skip_rowmap(src, macro, label), encoding="utf-8")
    mutated = [s if s.name != "stream_render.fj" else tmp_path / "stream_render.fj" for s in SRC]
    assert _faults(world, _assemble_run(tmp_path, "mut", _program(*world), mutated))[loop]


# ---- the RECORD: frame.thing_record_body's tier / slot section and its column loop, transplanted

_IDENT = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?![\w.(])")
_BUILTIN = {"w", "dw", "k", "i"}                  # the word sizes and the rep variables
DW_REC, N_COLS, NX = 3, 3, 256                   # a thing's width, the columns tried, hot columns
MIN_B_DELTA = {"HD": (-1, 0, 1), "MID": (1, -1, 0), "LD": (0, 1, -1)}   # per region: min_b - bucket


def _record_macros(src):
    """the SHIPPED frame.thing_record_body cut into two harness macros -- `t_rec_thing`, from the
    tier choice after the bucket lookup to the slot write (before the column DDA), and `t_rec_cols`,
    the column loop (`col_loop:` to `set_tstop:`) -- each taking the parameters of the record's own
    list that its code names (fj refuses an unused one) -> ({macro: [parameter names]}, fj text)"""
    a = src.index("    def thing_record_body ")
    body = src[a:src.index("\n    def ", a + 1)]
    params = body[len("    def thing_record_body "):body.index(" \\\n")].split(", ")
    lines = body.split("\n")
    s_a = next(n for n, ln in enumerate(lines) if "sprbkt.lookup trb_bucket, trb_thpx" in ln) + 1
    e_a = next(n for n, ln in enumerate(lines) if ln.startswith("        // the column DDA"))
    s_b = lines.index("      col_loop:")
    e_b = lines.index("      set_tstop:")
    out, pars = [], {}
    for name, part in (("t_rec_thing", lines[s_a:e_a]), ("t_rec_cols", lines[s_b:e_b])):
        code = [ln.split("//")[0].rstrip() for ln in part]
        code = "\n".join(ln for ln in code if ln.strip())
        labels = set(re.findall(r"^\s*(\w+):", code, re.M))
        used = set(_IDENT.findall(code))
        tail = "      ret:\n" if "ret" in used - labels else ""
        loc = sorted(labels | ({"ret"} if tail else set()))
        glob = sorted(used - set(params) - labels - {"ret"} - _BUILTIN)
        pars[name] = [p for p in params if p in used]
        out.append("def %s %s @ %s < %s {\n%s\n%s}" % (name, ", ".join(pars[name]), ", ".join(loc),
                                                       ", ".join(glob), code, tail))
    return pars, "\n".join(out)


def _record_cases():
    """(bucket, thfar, tytop, thpx, light class) for every bucket, near and far: the thing's height
    is the SHORTEST that lands in the bucket, so its top moves by the bucket's height"""
    out = []
    for far in (0, 1):
        for b in range(SPRITE_HEIGHT_BUCKETS):
            thpx = min(h for h in range(1, H + 1) if sprite_bucket(h, H) == b)
            out.append((b, far, (-60, -5, 0, 17, 45)[len(out) % 5], thpx, len(out) % 2))
    return out


def _shade(lt, hb):
    """the stub `sprlight` byte at class `lt`, height `hb`"""
    return (lt * 97 + hb * 7 + 3) & 0xFF


def _record_program(src, cases):
    pars, macros = _record_macros(src)
    # the values the emitter passes (wall_renderer._thing_leaf_body); the sections name no others
    args = dict(hdb=wr.sprite_hd_bucket(CFG), deg=1, sprbminh=DEG_SPRB_MINH,
                spn=1 if DEG_SPR_NEAR_TZ else 0, lowh=DEG_SPR_LOWRES_H,
                slotstride=wr.SPR_SLOT_STRIDE, ltw=1,          # M7 P3.1: a one-byte light class ...
                mir=0, mirf=0, miru=0,                        # ... no mirrored views ...
                seen=0, sa=0, sflag=0, one=0)                 # ... and no seen flags (M7 P3.2a)
    argl = {m: ", ".join(str(args[p]) for p in ps) for m, ps in pars.items()}
    main = ["stl.startup_and_init_all",
            # the renderer's hot-data block, as the emitter places it: a fresh 16^5-bit window, so
            # the column loop's arm5 reads and writes (drawn -> sprflag, spslot -> sprflag) are exact
            ";t_hot_end", "pad 16384",
            "drawn:", *[";0 * dw"] * NX, "sprflag:", *[";0 * dw"] * NX,
            "spslot:", *[";0 * dw"] * (NX * wr.SPR_SLOT_STRIDE),
            "gpslot:", *[";0 * dw"] * (wr.SPR_THING_SLOTS * wr.SPR_THING_SLOT_BYTES),
            "t_hot_end:",
            "    hex.set 2, gps_nslot, 0"]
    for c, (b, far, tytop, thpx, lt) in enumerate(cases):
        main += ["    hex.set 4, trb_bucket, %d" % (HEIGHTS[b] << 8 | b),   # sprbkt's [bucket][hb]
                 "    hex.set 4, sp_base, %d" % (9 * c),
                 "    hex.set 2, sp_dw, %d" % DW_REC,
                 "    hex.set 4, sp_base2, %d" % (9 * c + 2 * DW_REC),
                 "    hex.set 2, sp_lt, %d" % lt,
                 "    hex.set 1, thfar, %d" % far,
                 "    hex.set 8, trb_tytop, %d" % (tytop & 0xFFFFFFFF),
                 "    hex.set 8, trb_thpx, %d" % thpx,
                 "    stl.fcall t_thing_leaf, t_ret"]
        for u in range(N_COLS):
            x = N_COLS * c + u
            main += ["    hex.set 8, trb_col_x, %d" % x, "    hex.set 8, trb_tx2, %d" % x,
                     "    hex.set 8, trb_frac_u, %d" % (u << 16), "    hex.set 8, trb_tistep, 0",
                     "    hex.set 2, trb_dw_max, %d" % (DW_REC - 1),
                     "    hex.set w/4, trb_drawn_b, drawn",
                     "    frame.ptr_index4 trb_drawn_p, trb_drawn_b, trb_col_x",
                     "    hex.set w/4, trb_sprflag_b, sprflag",
                     "    frame.ptr_index4 trb_sprflag_p, trb_sprflag_b, trb_col_x",
                     "    stl.fcall t_col_leaf, t_ret"]
    ncol = N_COLS * len(cases)
    for base, n in (("gpslot", wr.SPR_THING_SLOT_BYTES * (len(cases) + 1)),
                    ("spslot", ncol * wr.SPR_SLOT_STRIDE), ("sprflag", ncol)):
        main += ["    hex.set w/4, t_p, %s" % base, "    hex.set 4, t_n, %d" % n,
                 "    stl.fcall t_dump_leaf, t_ret"]
    bank = wr.sprite_bank_header()
    for c, (b, *_rest) in enumerate(cases):
        for tier in ("HD", "MID", "LD"):
            for u in range(DW_REC):
                min_b = max(0, min(SPRITE_HEIGHT_BUCKETS, b + MIN_B_DELTA[tier][u]))
                body = [0, min_b, 255, 255, 5]
                bank += [";%#x * dw" % v for v in body] + [";0 * dw"] * (wr.SPR_BLOCK_STRIDE - 5)
    main += ["    stl.loop",
             "t_thing_leaf:", "    t_rec_thing %s" % argl["t_rec_thing"],
             "    hex.print_as_digit 8, trb_blk_const, 0", "    stl.output_char 32",
             "    hex.print_as_digit 1, hdfl, 0", "    hex.print_as_digit 1, ballow, 0",
             "    stl.output_char 32", "    hex.print_as_digit 2, trb_shade_row, 0",
             "    stl.output_char 10", "    stl.fret t_ret",
             "t_col_leaf:", "    t_rec_cols %s" % argl["t_rec_cols"], "    stl.fret t_ret",
             "t_dump_leaf:",                               # t_n bytes from t_p, as hex, one line
             "    hex.if0 4, t_n, t_dump_done", "    hex.read_byte_and_inc t_b, t_p",
             "    hex.print_as_digit 2, t_b, 0", "    hex.dec 4, t_n", "    ;t_dump_leaf",
             "t_dump_done:", "    stl.output_char 10", "    stl.fret t_ret",
             macros,
             "t_ret: ;0", "t_p: hex.vec w/4", "t_b: hex.vec 2", "t_n: hex.vec 4",
             "sp_base: hex.vec 4", "sp_dw: hex.vec 2", "sp_base2: hex.vec 4", "sp_lt: hex.vec 2",
             "thfar: hex.vec 1", "hdfl: hex.vec 1", "ballow: hex.vec 1",
             "sprlight:", *[";%#x * dw" % _shade(lt, h) for lt in (0, 1) for h in range(256)],
             wr.hoisted_scratch_fj(CFG), *bank, ""]
    return "\n".join(main)


def _record_faults(cases, out):
    """[(what, case, got, want)] -- the fj record against the oracle's tier rule and the layout"""
    lines = out.decode("ascii").split("\n")
    slot, spslot, sprflag = (bytes.fromhex(ln) for ln in lines[len(cases):len(cases) + 3])
    bad = []
    for c, (b, far, tytop, thpx, lt) in enumerate(cases):
        hb = HEIGHTS[b]
        tier = sprite_tier(hb, bool(far))
        region = {"HD": 9 * c, "MID": 9 * c + DW_REC, "LD": 9 * c + 2 * DW_REC}[tier]
        want = "%08x %d%d %02x" % (region, tier != "LD", hb >= DEG_SPRB_MINH, _shade(lt, hb))
        if lines[c] != want:
            bad.append(("thing", (b, far), lines[c], want))
        yb = (tytop + thpx - hb + 32768) & 0xFFFF
        s = c + 1
        want_slot = bytes((yb & 0xFF, yb >> 8, _shade(lt, hb), b))
        got_slot = slot[4 * s:4 * s + 4]
        if got_slot != want_slot:
            bad.append(("slot", (b, far), got_slot.hex(), want_slot.hex()))
        for u in range(N_COLS):
            x = N_COLS * c + u
            blk = region + u
            take = b >= max(0, min(SPRITE_HEIGHT_BUCKETS, b + MIN_B_DELTA[tier][u]))
            want_col = (bytes((s, blk & 0xFF, blk >> 8)) if take else bytes(3), int(take))
            got_col = (spslot[wr.SPR_SLOT_STRIDE * x:wr.SPR_SLOT_STRIDE * x + 3], sprflag[x])
            if got_col != want_col:
                bad.append(("column", (b, far, u), got_col, want_col))
    return bad


@pytest.fixture(scope="module")
def record_cases():
    assert DEG_HD_BUDGET == 0, "fj's record has no HD budget: OPTION B would need its own test"
    cases = _record_cases()
    hdb = wr.sprite_hd_bucket(CFG)
    tiers = {(b, far): sprite_tier(HEIGHTS[b], bool(far)) for b, far, *_r in cases}
    # the boundary the finding names, both ways, and every tier really reached
    assert tiers[(hdb - 1, 0)] == tiers[(hdb - 1, 1)] == "MID" and tiers[(hdb, 0)] == "HD"
    assert set(tiers.values()) == {"HD", "MID", "LD"}, tiers
    return cases


def test_the_record_takes_the_tier_region_the_slot_and_the_min_b_columns(record_cases, tmp_path):
    src = (ROOT / "src/fj/frame_render.fj").read_text(encoding="utf-8")
    out = _assemble_run(tmp_path, "rec", _record_program(src, record_cases), SRC)
    bad = _record_faults(record_cases, out)
    assert bad == [], "%d faults, first (what, case, got, want) %s" % (len(bad), bad[:3])


RECORD_MUTANTS = {
    "the bucket AT hdb takes MID": ("hex.cmp 2, trb_bucket, trb_climit, mid_base, hd_base, hd_base",
                                    "hex.cmp 2, trb_bucket, trb_climit, mid_base, mid_base, hd_base"),
    "slot byte 3 holds the height": ("hex.write_byte gps_ptr, trb_bucket ",
                                     "hex.write_byte gps_ptr, trb_bucket_h "),
    "a column AT its min_b is dropped": ("hex.cmp 2, trb_bucket, trb_run_last, col_next, do_store, do_store",
                                         "hex.cmp 2, trb_bucket, trb_run_last, col_next, col_next, do_store"),
    "thfar read inverted": ("rep(spn, k) hex.if0 1, thfar, hd_done", "rep(spn, k) hex.if1 1, thfar, hd_done"),
}


@pytest.mark.parametrize("name", sorted(RECORD_MUTANTS))
def test_a_broken_record_is_caught(record_cases, tmp_path, name):
    """R9: each mutation of the shipped record text, transplanted the same way, must fail the check"""
    old, new = RECORD_MUTANTS[name]
    src = (ROOT / "src/fj/frame_render.fj").read_text(encoding="utf-8")
    assert src.count(old) == 1, "re-point this mutant: %r moved" % old
    out = _assemble_run(tmp_path, "recmut", _record_program(src.replace(old, new), record_cases), SRC)
    assert _record_faults(record_cases, out)
