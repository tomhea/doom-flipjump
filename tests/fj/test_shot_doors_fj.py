"""M8 C3 -- THE SHOT DOORS (GR 46) in fj (`doomfj.shotcode`, the REAL emitted text) against the model's rules:

  * THE RECORD (`shotcode.pre_lines` / `post_lines` / `leaf_lines`, around a GR seg's pass-1 call): a window column
    the seg claims (drawn before 0, after 1) whose `aim_sid` is 0 and whose horizon row (CENTERY) the column's nearer
    pieces leave open takes the line's id -- reference_model.render_wall_frame's rule, `ledge_hidden(ups, los,
    centery, 1)`. Each record pokes the 17 columns' drawn flags before and after, the prior window and the pieces.
  * THE PRESS (`weaponcode.shot_leaves(shots)`' `sh_gun`, `_shot_melee(shots=)`): a gun's id of a shot line sets
    `dreq` of each of its doors at rest (doors.switch_ready) and hands nothing to `dm_go`; any other id goes to
    `dm_go` as before; a swing ignores a shot id (combat._line_attack). E1M9's four GR lines and their doors.
R9: mutants of the emitted text, each caught.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import aimcode as AC
from doomfj import doors as D
from doomfj import shotcode as SC
from doomfj import weaponcode as WC
from doomfj.config import GAME_CFG
from doomfj.doorcode import WAIT_NIBBLES, door_decls
from doomfj.harness import W
from doomfj.reference_model import ledge_hidden
from doomfj.wad import WadFile
from doomfj import wall_renderer as wr

ROOT = Path(__file__).resolve().parents[2]
FJDIR = ROOT / "src" / "fj"
FULL = ROOT / "assets" / "freedoom1.wad"
H, CENTERY = GAME_CFG.VIEW_H, GAME_CFG.CENTERY
STRIDE = GAME_CFG.SLOT_STRIDE
N = 400

pytestmark = pytest.mark.skipif(not FULL.exists(), reason="the full episode wad is not present")


# ---- 1. the record ---------------------------------------------------------------------------------------------------

def _ledge_col(rng):
    """one column's nearer pieces -> (sfflag, sfslot bytes, ups, los): none, or the last upper piece ending / the last
    lower one starting around the horizon row (CENTERY -1 / 0 / +1) or anywhere, with decoys"""
    slot = [rng.randrange(H) for _ in range(STRIDE)]
    if rng.random() < 0.4:
        return rng.choice((0, 0x08, 0x80, 0x88)), slot, [], []
    ucnt, lcnt = rng.choice(((1, 0), (2, 0), (0, 1), (0, 2), (1, 1), (2, 2), (1, 2), (2, 1)))
    uy2 = max(0, min(H - 1, rng.choice((CENTERY - 2, CENTERY - 1, CENTERY, rng.randrange(H)))))
    ly1 = max(0, min(H - 1, rng.choice((CENTERY, CENTERY + 1, CENTERY + 2, rng.randrange(H)))))
    ups = ([(0, slot[1])] if ucnt == 2 else []) + ([(0, uy2)] if ucnt else [])
    los = ([(slot[8], H - 1)] if lcnt == 2 else []) + ([(ly1, H - 1)] if lcnt else [])
    if ucnt:
        slot[1 + 4 * (ucnt - 1)] = uy2
    if lcnt:
        slot[8 + 4 * (lcnt - 1)] = ly1
    return ucnt | (rng.randrange(2) << 3) | (lcnt | (rng.randrange(2) << 3)) << 4, slot, ups, los


def _records(seed=5):
    rng = random.Random(seed)
    out = []
    for _ in range(N):
        k = rng.randrange(4)
        before = [int(rng.random() < 0.3) for _ in range(AC.NCOLS)]
        after = [1 if b else int(rng.random() < 0.6) for b in before]
        sids = [rng.choice([0, 0, 0, rng.randrange(1, 80)]) for _ in range(AC.NCOLS)]
        out.append((k, before, after, sids, [_ledge_col(rng) for _ in range(AC.NCOLS)]))
    return out


def _ref(k, before, after, sids, ledge):
    out = list(sids)
    for c in range(AC.NCOLS):
        if not before[c] and after[c] and not out[c] and not ledge_hidden(ledge[c][2], ledge[c][3], CENTERY, 1):
            out[c] = D.shot_sid(k)
    return out


def _rec_program(leaf):
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, kin",
            *["hex.input 1, t_in\nhex.set w/4, t_p, sfflag + %d*dw\nhex.write_byte t_p, t_in" % (AC.FIRST + c)
              for c in range(AC.NCOLS)],
            *["hex.input 1, t_in\nhex.set w/4, t_p, sfslot + %d*dw\nhex.write_byte t_p, t_in"
              % ((AC.FIRST + c) * STRIDE + o) for c in range(AC.NCOLS) for o in range(STRIDE)],
            *["hex.input 1, din\nhex.mov 1, drawn + %d*dw, din" % (AC.FIRST + c) for c in range(AC.NCOLS)],
            *["hex.input 1, aim_sid + %d*dw" % (2 * c) for c in range(AC.NCOLS)],
            *SC.pre_lines(),
            # the seg's columns claimed (the harness writes them, as seg_pass2_leaf's claim loop does -- pass 1 only
            # reads `drawn`; M8 w2fix: the record sits after PASS 2, wall_renderer.solid_seg_call_lines)
            *["hex.input 1, din\nhex.mov 1, drawn + %d*dw, din" % (AC.FIRST + c) for c in range(AC.NCOLS)]]
    for k in range(4):                                  # post_lines(k), on the record's k
        body += [f"hex.xor_by 1, kin, {k}", f"hex.if0 1, kin, pk{k}", f"hex.xor_by 1, kin, {k}", f";pn{k}",
                 f"pk{k}:", f"hex.xor_by 1, kin, {k}", *SC.post_lines(k), ";pdone", f"pn{k}:"]
    body += ["pdone:",
             *["hex.print_as_digit 2, aim_sid + %d*dw, 0\nstl.output 44" % (2 * c) for c in range(AC.NCOLS)],
             "stl.output 10", ";loop", "done:", "stl.loop", *leaf,
             "rmagic: hex.vec 2", "kin: hex.vec 2", "din: hex.vec 2", "t_in: hex.vec 2", "t_p: hex.vec w/4",
             wr.hoisted_scratch_fj(GAME_CFG),
             "drawn:\n" + "\n".join(";0 * dw" for _ in range(GAME_CFG.VIEW_W)),
             "sfflag:\n" + "\n".join(";0 * dw" for _ in range(GAME_CFG.VIEW_W)),
             "sfslot:\n" + "\n".join(";0 * dw" for _ in range(GAME_CFG.VIEW_W * STRIDE)),
             *AC.decls(False), *SC.decls(CENTERY)]
    return "\n".join(body) + "\n"


def _rec_run(tmp_path, leaf):
    src = tmp_path / "rec.fj"
    src.write_text(_rec_program(leaf), encoding="utf-8")
    out = tmp_path / "rec.fjm"
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), (FJDIR / "fixed_point.fj").resolve(), (FJDIR / "frame_render.fj").resolve(),
                 (FJDIR / "projection.fj").resolve(), src.resolve()], out, memory_width=W, print_time=False)
    recs = _records()
    feed = b""
    for k, before, after, sids, ledge in recs:
        feed += bytes([1, k]) + bytes(lc[0] for lc in ledge) + b"".join(bytes(lc[1]) for lc in ledge)
        feed += bytes(before) + bytes(sids) + bytes(after)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = [[int(v, 16) for v in line.split(",")[:AC.NCOLS]]
           for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:N]]
    return got, [_ref(*r) for r in recs], recs


def test_the_record_is_the_models_rule(tmp_path):
    got, want, recs = _rec_run(tmp_path, SC.leaf_lines())
    bad = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), None)
    assert len(got) == N and bad is None, "record %d: %s != %s" % (bad, got[bad], want[bad])
    # not vacuous: ids written, and the pieces decide some (without them the window differs)
    assert sum(w != r[3] for w, r in zip(want, recs)) > N // 2
    bare = [_ref(r[0], r[1], r[2], r[3], [(0, [], [], [])] * AC.NCOLS) for r in recs]
    assert sum(b != w for b, w in zip(bare, want)) > N // 10


REC_MUTANTS = {
    "a column drawn before is taken": ("hex.if1 1, shr_pre + 3*dw, shrx3", "hex.if1 0, shr_pre + 3*dw, shrx3"),
    "a nearer thing overwritten": ("hex.if0 2, aim_sid + 10*dw, shro5", "hex.if0 0, aim_sid + 10*dw, shro5"),
    "the horizon row's pieces ignored": ("frame.ledge_test ar_cv, ar_colx, shr_ylo1, shr_yhi1, 0, shrx8",
                                         "hex.zero 2, ar_cv"),
}


@pytest.mark.parametrize("mut", sorted(REC_MUTANTS))
def test_a_mutated_record_fails(tmp_path, mut):
    old, new = REC_MUTANTS[mut]
    text = "\n".join(SC.leaf_lines())
    assert text.count(old) == 1, old
    got, want, _ = _rec_run(tmp_path, text.replace(old, new).split("\n"))
    assert got != want, mut


def test_a_control_with_the_ylo_box_one_row_low(tmp_path):
    """the box's rows are CENTERY's (ledge_box's +1 / +2): one row lower must part the window"""
    got, want, _ = _rec_run(tmp_path, SC.leaf_lines())
    import doomfj.shotcode as m
    old = m.decls
    try:
        m.decls = lambda cy: old(cy + 1)
        got2, _, _ = _rec_run(tmp_path, SC.leaf_lines())
    finally:
        m.decls = old
    assert got == want and got2 != want


# ---- 2. the press ----------------------------------------------------------------------------------------------------

def _e1m9(switch=False):
    """E1M9's specs; `switch`: as on a SWITCH_TEX map -- its own switch list (line 890 SW1STON2 is a GR switch)"""
    from doomfj import switches as SW
    mw = WadFile.from_path(str(FULL))
    secs, lds, sds = mw.sectors("E1M9"), mw.linedefs("E1M9"), mw.sidedefs("E1M9")
    sw = SW.map_switches(secs, lds, sds, mw.vertexes("E1M9")) if switch else ()
    return SC.shot_specs(secs, lds, sds, sw), len(D.door_states(secs, lds, sds))


def _press_records(specs, nd, seed=9):
    rng = random.Random(seed)
    lo = D.SHOT_SID_TOP - len(specs) + 1
    out = []
    for _ in range(N):
        sid = rng.choice([0, rng.randrange(1, 80), rng.randrange(lo, 0x100), rng.randrange(lo, 0x100)])
        melee = int(rng.random() < 0.3)
        ds = {d: rng.choice([(0, 0, 0), (0, 1, 0), (0, 2, 0), (3, 0, 0), (3, 0, 5)]) for _s, sl, _w in specs for d in sl}
        out.append((sid, melee, ds, rng.choice([0, 0, 1])))       # the switch cell's start (on a SWITCH_TEX map)
    return out


def _press_ref(specs, rec):
    """combat._line_attack: a gun's shot id -> shot_press (every door of the line at rest: a request); any other
    non-zero id -> the damage call; a swing: a shot id is no target"""
    sid, melee, ds, on = rec
    req, called = set(), 0
    sw = None
    if sid:
        k = D.SHOT_SID_TOP - sid
        if k < len(specs):
            if not melee:
                req = {d for d in specs[k][1] if D.switch_ready((ds[d][0], ds[d][1], 0, ds[d][2]))}
                sw = specs[k][2]
        else:
            called = 1
    # the switch texture (switches.press on the line's cell: set unless on, its countdown BUTTON_FRAMES)
    from doomfj.switches import BUTTON_FRAMES
    cells = [(on, 0)] if any(sp[2] for sp in specs) else []
    if cells and sw is not None and not on:
        cells = [(1, BUTTON_FRAMES)]
    elif cells:
        cells = [(on, 0)]
    return req, called, cells


def _press_program(specs, nd, gun, melee):
    slots = sorted({d for _s, sl, _w in specs for d in sl})
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, dm_id", "hex.input 1, rbyte", "hex.mov 1, mel, rbyte", "hex.input 1, rbyte",
            *([f"hex.mov 1, swpr + {_swk(specs)}*dw, rbyte", f"hex.zero {2 * _swn(specs)[1]}, swtm"]
              if any(sp[2] for sp in specs) else [])]
    for d in slots:
        body += ["hex.input 1, rbyte", f"hex.mov 1, dstate + {d}*dw, rbyte", "hex.input 1, rbyte",
                 f"hex.mov 1, ddir + {d}*dw, rbyte", "hex.input 1, rbyte",
                 f"hex.mov {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw, rbyte"]
    body += [f"hex.zero {nd}, dreq", "hex.zero 1, called", "hex.if1 1, mel, do_mel", "stl.fcall sh_gun, sh_ret",
             ";pr_out", "do_mel:", *melee, "pr_out:"]
    for d in slots:
        body += [f"hex.print_as_digit 1, dreq + {d}*dw, 0"]
    if any(sp[2] for sp in specs):
        j = list(next(sp[2] for sp in specs if sp[2])[1]).index(_swk(specs))
        body += [f"hex.print_as_digit 1, swpr + {_swk(specs)}*dw, 0", f"hex.print_as_digit 2, swtm + {2 * j}*dw, 0"]
    body += ["hex.print_as_digit 1, called, 0", "stl.output 10", ";loop", "done:", "stl.loop",
             *gun,
             "dm_go:", "hex.set 1, called, 1", "stl.fret dm_ret", "dm_ret: hex.vec w/4",
             "rmagic: hex.vec 2", "rbyte: hex.vec 2", "mel: hex.vec 1", "called: hex.vec 1",
             "rng_pl: hex.vec 2", f"aim_sid: hex.vec {2 * AC.NCOLS}",      # the shot leaves' stream and window
             *WC.shot_decls(specs), *door_decls(nd, 1),
             *([f"swpr: hex.vec {_swn(specs)[0]}", f"swtm: hex.vec {2 * _swn(specs)[1]}"]
               if any(sp[2] for sp in specs) else [])]
    return "\n".join(body) + "\n"


def _swk(specs):
    """the GR switch's latched index (one GR switch line on E1M9)"""
    return next(sp[2] for sp in specs if sp[2])[0]


def _swn(specs):
    """(latched cells, repeating cells) the harness declares: enough for the switch's index and its countdown"""
    k, sr = next(sp[2] for sp in specs if sp[2])
    return max(k + 1, max(sr) + 1), len(sr)


def _gun_text(specs, mut=None):
    text = "\n".join(WC.shot_leaves(specs))
    if mut:
        assert text.count(mut[0]) == 1, mut[0]
        text = text.replace(*mut)
    return text.split("\n")


def _melee_text(specs, mut=None):
    """`_shot_melee`'s text with its 3-draw `sh_rd3` stubbed out (dm_id is the record's)"""
    text = "\n".join(WC._shot_melee("m", "punch", shots=specs)).replace("stl.fcall sh_rd3, sh_ret", "")
    if mut:
        assert text.count(mut[0]) == 1, mut[0]
        text = text.replace(*mut)
    return text.split("\n")


def _press_run(tmp_path, gun_mut=None, mel_mut=None, switch=False):
    specs, nd = _e1m9(switch)
    src = tmp_path / "press.fj"
    src.write_text(_press_program(specs, nd, _gun_text(specs, gun_mut), _melee_text(specs, mel_mut)),
                   encoding="utf-8")
    out = tmp_path / "press.fjm"
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    tab = tmp_path / "wpo.fj"
    tab.write_text(WC.shot_table_fj(), encoding="utf-8")
    fj.assemble([consts.resolve(), (FJDIR / "fixed_point.fj").resolve(), src.resolve(), tab.resolve()], out,
                memory_width=W, print_time=False)
    recs = _press_records(specs, nd)
    slots = sorted({d for _s, sl, _w in specs for d in sl})
    feed = b""
    for sid, melee, ds, on in recs:
        feed += bytes([1, sid, melee, on]) + b"".join(bytes(ds[d]) for d in slots)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = io.get_output(allow_incomplete_output=True).decode().split("\n")[:N]
    want = []
    for r in recs:
        req, called, cells = _press_ref(specs, r)
        want.append("".join(str(int(d in req)) for d in slots) + "".join("%x%02x" % c for c in cells) + str(called))
    return got, want, recs


def test_the_press_is_the_models_rule(tmp_path):
    specs, _nd = _e1m9()
    assert [s for s, _, _w in specs] == [0xFF, 0xFE, 0xFD, 0xFC] and len({d for _s, sl, _w in specs for d in sl}) == 2
    got, want, recs = _press_run(tmp_path)
    bad = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), None)
    assert len(got) == N and bad is None, "record %d: %s != %s (%s)" % (bad, got[bad], want[bad], recs[bad])
    assert sum("1" in w[:-1] for w in want) > N // 10 and sum(w[-1] == "1" for w in want) > N // 10


PRESS_MUTANTS = {
    "gun: a shot id handed to dm_go": (("hex.cmp 2, dm_id, sh_t, shg_mon, shg_gr, shg_gr",
                                        "hex.cmp 2, dm_id, sh_t, shg_mon, shg_mon, shg_mon"), None),
    "gun: a moving door pressed": (("hex.if0 1, ddir + %d*dw, shg_ph0d0a", "hex.if0 0, ddir + %d*dw, shg_ph0d0a"), None),
    "melee: a shot id handed to dm_go": (None, ("hex.cmp 2, dm_id, sh_t, msm, msx, msx",
                                                "hex.cmp 2, dm_id, sh_t, msm, msm, msm")),
}


@pytest.mark.parametrize("mut", sorted(PRESS_MUTANTS))
def test_a_mutated_press_fails(tmp_path, mut):
    g, m = PRESS_MUTANTS[mut]
    if g and "%d" in g[0]:
        specs, _ = _e1m9()
        d = specs[0][1][0]
        g = (g[0] % d, g[1] % d)
    got, want, _ = _press_run(tmp_path, g, m)
    assert got != want, mut


def test_the_press_swaps_the_lines_switch_texture(tmp_path):
    """on a SWITCH_TEX map (switches.map_switches: line 890, SW1STON2, is a GR switch): a gun's shot on it sets its
    cell and the button's countdown unless it is already out (switches.press) -- the other lines have no switch"""
    specs, _nd = _e1m9(True)
    assert [sp[2] is not None for sp in specs] == [False, False, True, False]
    got, want, recs = _press_run(tmp_path, switch=True)
    bad = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), None)
    assert len(got) == N and bad is None, "record %d: %s != %s (%s)" % (bad, got[bad], want[bad], recs[bad])
    from doomfj.switches import BUTTON_FRAMES
    assert sum(("1%02x" % BUTTON_FRAMES) in w for w in want) > 5


def test_control_the_switch_pressed_while_its_button_is_out(tmp_path):
    specs, _nd = _e1m9(True)
    k = specs[2][2][0]
    got, want, _ = _press_run(tmp_path, ("hex.if1 1, swpr + %d*dw, shg_end" % k, "hex.if1 0, swpr + %d*dw, shg_end" % k),
                              switch=True)
    assert got != want
