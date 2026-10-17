"""M8 F1.4 (docs/f1-big-map-widths.md section 1, option B -- the owner, 2026-10-17): THE SLOT CAP, on the real engine.

A fragment names its thing by a one-byte slot id (`gps_nslot`, 1..255); a map whose frames could accept more things
caps the frame at `Config.SPR_SLOT_CAP` (E1M2: 255). frame.thing_record_body compares `gps_nslot` against the cap
BEFORE either count budget -- a thing past it returns, or, a monster in the body with a seen flag, takes the seen
probe as a budget-failed one does -- and the oracle (reference_model.render_wall_frame) counts `n_slots` where the fj
increments and ORs the cap into its budget test. DOOM's rule: r_things.c R_NewVisSprite, past MAXVISSPRITES the
overflow sprite (never drawn); the walk is front to back, so only the farthest drop.

THE SCENARIO is the ORACLE's: the one-room map (tests/fixtures/square_room.wad) with 30 things of 15 kinds in front of
the player start -- monsters, items, decor and two barrels -- rendered with the game tier's picture
(`GAME_RENDER_KW`, the seen rule on) at cap 4 and at cap 0. Its `slot_trace` gives, in walk order, every thing the
walk reaches and what happened to it: a slot id, turned away by the cap ("C"), by the art or the projection ("V"), or
by the actors rule's off-view test ("O").

THE FJ: the shipped macro's text, TRANSPLANTED verbatim in three spans -- (A) from the body's first line to
`not_full:` (the seen flag's clear, the CAP COMPARE, both budgets, the full stop), (M) the counters' credit
(`hex.if0 2, sp_mon, inc_scenery` .. `inc_done:`), (B) the slot allocation (`hex.inc 2, gps_nslot` .. the slot
index) -- with the projection's and the off-view test's answers fed from the oracle's trace between them (a thing the
cap or a budget turned away is fed as VISIBLE: if the fj let it through it would take a slot). Each thing prints its
slot id in hex, or the path it left by: R (ret), S (the seen probe), V, O, T (the full stop). The cap and its switch
come from fj_consts.fj (`Config.emit_fj_consts`), as the build's do.

R9 (each must PART from the oracle):
  * the oracle at cap 5 against the fj at cap 4;
  * the fj's compare moved AFTER the increment (the cap counted one thing late: the 4th accepted thing turned away);
  * a capped monster sent to `ret` instead of the seen probe (seen body only).
"""
import re
from dataclasses import replace
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.reference_model import (DEG_SOFT_SCENERY, GAME_RENDER_KW, MONSTER_BUDGET, THING_BUDGET, ReferenceModel,
                                    build_scene, spawn_state)
from doomfj.wad import Thing, WadFile
from doomfj import wall_renderer as wr

ROOT = Path(__file__).resolve().parents[2]
CAP = 4
_KINDS = [3004, 9, 3001, 3002, 58, 2001, 2007, 2028, 2011, 2012, 2014, 2015, 2018, 2019, 2035]
ROOM = [(40 + (i % 10) * 18, 150 + (i // 10) * 30, _KINDS[i % len(_KINDS)]) for i in range(30)]
_IDENT = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?![\w.(])")
_BUILTIN = {"w", "dw", "k", "i"}
TAILS = ("set_tstop", "ret", "seen_probe", "t_vrej", "t_orej", "t_done")
# the game tier's binding of the parameters the spans use (wall_renderer._thing_leaf_body: the runtime body)
DSOFTS = DEG_SOFT_SCENERY | wr.D3B_SOFT_FLAG
DECLS = ["n_thing: hex.vec 2", "n_mon: hex.vec 2", "full: hex.vec 1", "sp_mon: hex.vec 2", "sp_ex: hex.vec 1",
         "trb_climit: hex.vec 2", "gps_nslot: hex.vec 2", "gps_s_rec: hex.vec 2", "trb_seenf: hex.vec 1",
         "t_vis: hex.vec 1", "t_offv: hex.vec 1", "t_ret: hex.vec w/4"]
_TRACES = {}


def oracle_trace(cap: int):
    """render_wall_frame's slot_trace on the room at `cap` (the game tier's picture, the seen rule on)"""
    if cap not in _TRACES:
        mw = WadFile.from_path(ROOT / "tests/fixtures/square_room.wad")
        base = mw.things
        mw.things = lambda name, base=base: base(name) + [Thing(x, y, 0, t, 7) for x, y, t in ROOM]
        scene = build_scene(mw, WadFile.from_path(ROOT / "tests/fixtures/freedoom_assets.wad"), "MAP01")
        trace = []
        ReferenceModel(replace(GAME_CFG, SPR_SLOT_CAP=cap)).render_wall_frame(
            spawn_state(mw, "MAP01"), scene, sprite_wad=WadFile.from_path(ROOT / "assets/freedoom1.wad"),
            seen_out=set(), slot_trace=trace, **GAME_RENDER_KW)
        _TRACES[cap] = tuple(trace)
    return _TRACES[cap]


def expected(trace, seen: int) -> bytes:
    """the fj's print for each traced thing: the slot id (2 hex digits), or the path a turned-away thing leaves by --
    the seen probe for an actor (sp_mon != 0) in the seen body, else ret"""
    out = []
    for _di, act, _ex, how in trace:
        if isinstance(how, int):
            out.append("%02X" % how)
        elif how in ("C", "B"):
            out.append("S" if (seen and act) else "R")
        else:
            out.append(how)
    return (" ".join(out) + " \n").encode()


def _src():
    return (ROOT / "src/fj/frame_render.fj").read_text(encoding="utf-8").replace("\r\n", "\n")


def _clean(lines):
    return [ln.split("//")[0].rstrip().replace(" .rec_goto ", " t_goto ") for ln in lines if ln.split("//")[0].strip()]


def spans(src):
    """the three verbatim spans of frame.thing_record_body, and its parameter list"""
    a = src.index("    def thing_record_body ")
    body = src[a:src.index("\n    def ", a + 1)]
    params = [p.strip() for p in body[len("    def thing_record_body "):body.index(" \\\n")].split(",")]
    lines = body.split("\n")
    a0 = next(n for n, ln in enumerate(lines) if ln.rstrip().endswith("{")) + 1
    a1 = lines.index("      not_full:")
    m0 = next(n for n, ln in enumerate(lines) if ln.split("//")[0].strip() == "hex.if0 2, sp_mon, inc_scenery")
    m1 = lines.index("      inc_done:") + 1
    b0 = next(n for n, ln in enumerate(lines) if ln.split("//")[0].strip() == "hex.inc 2, gps_nslot")
    b1 = next(n for n, ln in enumerate(lines) if ln.strip().startswith("hex.zero w/4 - 2, gps_sidx"))
    assert a0 < a1 < m0 < m1 < b0 < b1, (a0, a1, m0, m1, b0, b1)
    return params, _clean(lines[a0:a1]), _clean(lines[m0:m1]), _clean(lines[b0:b1])


def program(src, trace, seen: int) -> str:
    params, sa, sm, sb = spans(src)
    code = sa + ["        hex.if0 1, t_vis, t_vrej"] + sm + ["        hex.if1 1, t_offv, t_orej"] + sb + [
        "        hex.print_as_digit 2, gps_s_rec, 1", "        stl.output_char 32", "        ;t_done"]
    for lab, ch in (("set_tstop", "T"), ("ret", "R"), ("seen_probe", "S"), ("t_vrej", "V"), ("t_orej", "O")):
        code += ["      %s:" % lab, "        stl.output_char %d" % ord(ch), "        stl.output_char 32",
                 "        ;t_done"]
    code += ["      t_done:"]
    text = "\n".join(code)
    labels = set(re.findall(r"^\s*(\w+):", text, re.M))
    used = set(_IDENT.findall(text))
    consts = set(GAME_CFG.constants())
    binding = dict(budget=THING_BUDGET, monbudget=MONSTER_BUDGET, seen=seen, sflag="trb_seenf", dsofts=DSOFTS)
    pars = [p for p in params if p in used]
    assert set(pars) <= set(binding), "the spans use parameters the harness does not bind: %s" % (set(pars) - set(binding))
    glob = sorted(used - set(params) - labels - _BUILTIN - consts - {"t_goto"})
    macro = ("def t_goto dst {\n    ;dst\n}\n"
             "def t_cap %s @ %s < %s {\n%s\n}\n" % (", ".join(pars), ", ".join(sorted(labels)), ", ".join(glob), text))
    main = ["stl.startup_and_init_all"]
    for _di, act, ex, how in trace:
        main += ["    hex.set 2, sp_mon, %d" % (1 if act else 0), "    hex.set 1, sp_ex, %d" % (1 if ex else 0),
                 "    hex.set 1, t_vis, %d" % (0 if how == "V" else 1),
                 "    hex.set 1, t_offv, %d" % (1 if how == "O" else 0), "    stl.fcall t_leaf, t_ret"]
    main += ["    stl.output_char 10", "    stl.loop",
             "t_leaf:", "    t_cap %s" % ", ".join(str(binding[p]) for p in pars), "    stl.fret t_ret", macro] + DECLS
    return "\n".join(main) + "\n"


def run(tmp_path, name, src, trace, seen, fj_cap) -> bytes:
    """the fj's print over `trace` (fj_consts at `fj_cap`). An fj that does not assemble RAISES: never a catch"""
    p = tmp_path / ("%s.fj" % name)
    p.write_text(program(src, trace, seen), encoding="utf-8")
    consts = replace(GAME_CFG, SPR_SLOT_CAP=fj_cap).emit_fj_consts(tmp_path / ("%s_consts.fj" % name))
    out = tmp_path / ("%s.fjm" % name)
    fj.assemble([consts.resolve(), p.resolve()], out, memory_width=W, warning_as_errors=True, print_time=False)
    io = FixedIO(b"")
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    assert term.termination_cause == fj.TerminationCause.Looping, term.termination_cause
    return io.get_output(allow_incomplete_output=True)


def test_the_scenario_reaches_every_outcome():
    """the cap binds in the room: at cap 4 ids 1..4, then actors AND scenery (a barrel among them) turned away by the
    cap; at cap 0 the same walk hands out more than 4 ids; and both traces hold projection and off-view rejects"""
    capped, free = oracle_trace(CAP), oracle_trace(0)
    assert [h for *_x, h in capped if isinstance(h, int)] == list(range(1, CAP + 1))
    assert {(a, h) for _d, a, _e, h in capped if h == "C"} == {(True, "C"), (False, "C")}
    assert any(e and h == "C" for _d, _a, e, h in capped), "a barrel (the D3 b exemption) turned away by the cap"
    assert max(h for *_x, h in free if isinstance(h, int)) > CAP + 1
    assert {"V", "O"} <= {h for *_x, h in capped} and {"V", "O"} <= {h for *_x, h in free}
    assert not any(h == "B" for *_x, h in capped + free), "the budgets (255) never bind here: the cap alone does"
    assert [d for d, *_x in capped] == [d for d, *_x in free], "the cap changes no walk order"


@pytest.mark.parametrize("cap", [CAP, 0])
@pytest.mark.parametrize("seen", [1, 0])
def test_the_record_caps_its_slots_as_the_oracle(tmp_path, cap, seen):
    trace = oracle_trace(cap)
    got, want = run(tmp_path, "cap%d_s%d" % (cap, seen), _src(), trace, seen, cap), expected(trace, seen)
    assert got == want, "the record parted from the oracle's slot cap (cap %d, seen %d):\n fj     %s\n oracle %s" % (
        cap, seen, got, want)


def test_control_the_oracle_at_another_cap_parts(tmp_path):
    """R9: the oracle at cap 5 against the fj at cap 4"""
    trace5 = oracle_trace(CAP + 1)
    assert expected(trace5, 1) != expected(oracle_trace(CAP), 1)
    assert run(tmp_path, "o5", _src(), trace5, 1, CAP) != expected(trace5, 1)


def _moved_after_the_increment(src):
    a = src.index("        rep(SPR_SLOT_CAP_ON, k) hex.set 2, trb_climit, SPR_SLOT_CAP\n")
    b = src.index("      slot_cap_ok:\n", a) + len("      slot_cap_ok:\n")
    block, src = src[a:b], src[:a] + src[b:]
    at = "        hex.mov 2, gps_s_rec, gps_nslot\n"
    assert src.count(at) == 1
    return src.replace(at, at + block)


def _capped_monster_returns(src):
    old = "        rep(SPR_SLOT_CAP_ON*seen, k) .rec_goto seen_probe\n"
    assert src.count(old) == 1
    return src.replace(old, "        rep(SPR_SLOT_CAP_ON*seen, k) .rec_goto ret\n")


@pytest.mark.parametrize("mutate", [_moved_after_the_increment, _capped_monster_returns])
def test_control_a_mutated_record_parts(tmp_path, mutate):
    """R9: the fj's compare moved after the increment; a capped monster sent to ret, not the seen probe"""
    src = _src()
    mutant = mutate(src)
    assert mutant != src
    trace = oracle_trace(CAP)
    assert run(tmp_path, mutate.__name__, mutant, trace, 1, CAP) != expected(trace, 1), (
        "the mutant %s still matched the oracle" % mutate.__name__)
