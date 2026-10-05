"""M7 P6+P7 package E -- THE ACTORS RULE in `frame.thing_record_body`, on the real flipjump engine.

The owner (2026-10-05): "monsters should always be shown", "you must always show the fireballs". The oracle's rule
(reference_model.render_wall_frame `exempt_actors`, the game tier's picture) has two record-side parts the fj takes
from the SHIPPED macro text, switched on by the one equality `dsoftm == monbudget` (wall_renderer passes the hard
MONSTER_BUDGET as the game tier's monster soft count; every other tier DEG_SOFT_MON, and the lines expand to nothing):
  (4) a sprite whose drawn bucket [ytop_b, ytop_b + hb) has no row inside the view [0, VIEW_H) records nothing --
      a thing with a seen flag goes to the seen probe, one without returns;
  (3) an ACTOR (sp_mon != 0) is never B-gated: `ballow` 1 at any bucket height (a scenery thing keeps hb >= sprbminh).

This harness TRANSPLANTS the macro's lines from after `frame.sub8_chain trb_y0, trb_bucket_h` to `bslot_done:`
verbatim into a harness macro, binds them as the emitter binds the game tier and as it binds every other tier, and
runs a grid of (ytop_b, hb, sp_mon, seen) against the oracle's two lines (`_oracle`). R9: a game-tier binding with the
old soft count (a monster dropped by the B-gate again), the exemption line deleted, and both off-view bounds moved by
one row must each part.
"""
import re
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import wall_renderer as wr
from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.reference_model import DEG_SOFT_MON, DEG_SPRB_MINH, MONSTER_BUDGET

ROOT = Path(__file__).resolve().parents[2]
H = GAME_CFG.VIEW_H
_IDENT = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?![\w.(])")
_BUILTIN = {"w", "dw", "k", "i"}
HBS = (8, DEG_SPRB_MINH - 1, DEG_SPRB_MINH, 60)
CASES = [(y0, hb, mon) for hb in HBS for y0 in (-200, -hb - 1, -hb, -hb + 1, 0, H - 1, H, H + 50)
         for mon in (0, 1)]


def _oracle(y0, hb, mon, seen, game) -> str:
    """render_wall_frame's two lines: `if exempt_actors and (ytop_b >= H or ytop_b + hb <= 0): continue` (the seen
    test ran before), then `elif not b_minh or hb >= b_minh or (act and exempt_actors)` -- 'S' / 'R' / ballow"""
    if game and (y0 >= H or y0 + hb <= 0):
        return "S" if seen else "R"
    return "1" if (hb >= DEG_SPRB_MINH or (game and mon)) else "0"


def _section(src):
    a = src.index("    def thing_record_body ")
    body = src[a:src.index("\n    def ", a + 1)]
    params = body[len("    def thing_record_body "):body.index(" \\\n")].split(", ")
    lines = body.split("\n")
    s0 = next(n for n, ln in enumerate(lines) if "frame.sub8_chain trb_y0, trb_bucket_h" in ln) + 1
    s1 = lines.index("      bslot_done:") + 1
    code = "\n".join(ln.split("//")[0].rstrip().replace(" .rec_goto ", " t_goto ")   # the record's gated jump
                     for ln in lines[s0:s1] if ln.split("//")[0].strip())
    labels = set(re.findall(r"^\s*(\w+):", code, re.M))
    used = set(_IDENT.findall(code))
    tail = {"seen_probe", "ret"}
    glob = sorted(used - set(params) - labels - tail - _BUILTIN - {"t_goto"})
    pars = [p for p in params if p in used]
    macro = ("def t_goto dst {\n    ;dst\n}\n"                    # frame.rec_goto's body
             "def t_actor %s @ %s, done < %s {\n%s\n"
             "        hex.print_as_digit 1, ballow, 0\n        ;done\n"
             "      seen_probe:\n        stl.output_char 83\n        ;done\n"
             "      ret:\n        stl.output_char 82\n      done:\n}\n"
             % (", ".join(pars), ", ".join(sorted(labels | tail)), ", ".join(glob), code))
    return pars, macro


def _program(src, game: bool, seen: int, binding=None):
    pars, macro = _section(src)
    args = dict(deg=1, sprbminh=DEG_SPRB_MINH, viewh=H, seen=seen, monbudget=MONSTER_BUDGET,
                dsoftm=MONSTER_BUDGET if game else DEG_SOFT_MON)
    args.update(binding or {})
    main = ["stl.startup_and_init_all"]
    for y0, hb, mon in CASES:
        main += ["    hex.set 8, trb_y0, %d" % (y0 & 0xFFFFFFFF), "    hex.set 8, trb_bucket_h, %d" % hb,
                 "    hex.set 2, sp_mon, %d" % mon, "    stl.fcall t_leaf, t_ret"]
    main += ["    stl.output_char 10", "    stl.loop",
             "t_leaf:", "    t_actor %s" % ", ".join(str(args[p]) for p in pars), "    stl.fret t_ret",
             macro, "t_ret: hex.vec w/4", "trb_y0: hex.vec 8", "trb_bucket_h: hex.vec 8", "trb_cbound: hex.vec 8",
             "trb_climit: hex.vec 2", "ballow: hex.vec 1", "sp_mon: hex.vec 2"]
    return "\n".join(main) + "\n"


def _expected(game, seen) -> bytes:
    return ("".join(_oracle(y0, hb, mon, seen, game) for y0, hb, mon in CASES) + "\n").encode()


def _run(tmp_path, name, src, game, seen, binding=None, want=None) -> bool:
    p = tmp_path / ("%s.fj" % name)
    p.write_text(_program(src, game, seen, binding), encoding="utf-8")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    return fj.assemble_and_run_test_output([consts.resolve(), p.resolve()], b"",
                                           _expected(game, seen) if want is None else want, memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def _src():
    return (ROOT / "src/fj/frame_render.fj").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_grid_reaches_every_outcome():
    for game in (0, 1):
        for seen in (0, 1):
            got = set(_expected(game, seen).decode().strip())
            assert {"0", "1"} <= got, (game, seen, got)
            if game:
                assert ("S" if seen else "R") in got


@pytest.mark.parametrize("game,seen", [(1, 0), (1, 1), (0, 0), (0, 1)])
def test_the_record_follows_the_actors_rule(tmp_path, game, seen):
    assert _run(tmp_path, "act_%d%d" % (game, seen), _src(), bool(game), seen), (
        "the transplanted record parted from the oracle's actors rule (game tier %d, seen %d)" % (game, seen))


def test_the_game_tier_binds_the_switch():
    """the emitter passes MONSTER_BUDGET as the game tier's dsoftm, read from GAME_RENDER_KW's one key"""
    import inspect
    src = inspect.getsource(wr.emit_wall_renderer)
    assert '_DSOFTM = MONSTER_BUDGET if (_p31 and _GRK.get("exempt_actors")) else DEG_SOFT_MON' in src
    assert "f\"{_DSOFTM}, {DEG_SPRB_MINH}" in src
    from doomfj.reference_model import GAME_RENDER_KW, HOSTED_RENDER_KW
    assert GAME_RENDER_KW["exempt_actors"] is True and HOSTED_RENDER_KW["exempt_actors"] is False


MUTANTS = {
    "the exemption line deleted": ("        rep(deg*(dsoftm==monbudget), k) hex.if0 2, sp_mon, bslot_gate\n", ""),
    "off-view below at H + 1": ("hex.scmp 8, trb_y0, trb_cbound, offv_top, offv_out, offv_out",
                                "hex.scmp 8, trb_y0, trb_cbound, offv_top, offv_top, offv_out"),
    "off-view above one row early": ("        rep(dsoftm==monbudget, k) hex.dec 8, trb_cbound\n", ""),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_control_a_broken_rule_is_caught(tmp_path, name):
    old, new = MUTANTS[name]
    src = _src()
    assert src.count(old) == 1, "re-point this mutant: %r moved" % old
    assert not _run(tmp_path, "actm", src.replace(old, new), True, 1), "%s passed: the comparison is vacuous" % name


def test_control_the_old_soft_count_drops_the_actors(tmp_path):
    """R9: the game tier bound with blocked48's dsoftm (DEG_SOFT_MON) -- the switch off, a short monster B-gated
    again behind a nearer sprite -- must part from the game rule"""
    assert not _run(tmp_path, "actold", _src(), True, 1, binding={"dsoftm": DEG_SOFT_MON})
