"""M7 P6+P7 package E -- the frame's MONSTER WORLD at the owner's tempo (2026-10-05), on the real flipjump engine.

`wall_renderer.world_tic_lines` wraps the game tier's world tic after the eye -- monstercode's `tic_after_eye`
(P_ChangeSector, the monster tic `mt_tic .. mt_skip`, the seen marks' reset) and `p5_tic_lines` (the pools' fcalls,
the bar) -- so that the monster tic and the pools run `world.MONSTER_TICS_PER_FRAME` times a frame, as the model's
`World._monster_world` does. This harness runs THE EMITTED TEXT (the real composer, the real `p5_tic_lines`) around
stubs in the documented shapes, each of which prints a letter when it runs:

    C  P_ChangeSector (once a frame, before the loop)
    T<s>  the monster tic, with the seen marks it reads (`thseen`, set by "last frame's render" before the tic)
    P  pj_phase    F  fx_phase    (each its own `lvdone` guard, as projcode's)
    Z<s>  after the loop: the marks before they are zeroed     B  the bar (inside the `lvdone` guard)

and checks the per-frame sequence on live frames and on an `lvdone` frame, two frames in a row (the counter must
start again). R9: the tempo 1 composition, the seen reset inside the loop, the bar inside the loop and a loop that
runs the pools once must each part.
"""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import wall_renderer as WR
from doomfj.config import Config
from doomfj.harness import W
from doomfj.world import MONSTER_TICS_PER_FRAME

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FRAMES = (0, 0, 1, 0)                              # lvdone per frame: live, live, a finished level, live again


def _say(ch: str) -> str:
    return "    stl.output %d" % ord(ch)


def _tic() -> list:
    """monstercode's `tic_after_eye` shape: [P_ChangeSector ...] [mt_tic: (its lvdone guard) ... mt_skip:] [zero]"""
    return ["  // P_ChangeSector", _say("C"),
            "mt_tic:", "    hex.if1 1, lvdone, mt_skip", _say("T"), "    hex.print_as_digit 1, thseen, 0",
            "  mt_skip:",
            "    hex.zero 1, thseen"]


def _pools() -> list:
    return WR.p5_tic_lines({"bar": [_say("B")]})


def _leaves() -> list:
    return ["pj_phase:", "    hex.if1 1, lvdone, pj_x", _say("P"), "  pj_x:", "    stl.fret pj_pret",
            "fx_phase:", "    hex.if1 1, lvdone, fx_x", _say("F"), "  fx_x:", "    stl.fret fx_pret"]


def _composed(mut=None) -> list:
    tics = 1 if mut == "onetic" else MONSTER_TICS_PER_FRAME
    out = WR.world_tic_lines(_tic(), _pools(), tics)
    if mut == "seeninloop":                         # the marks zeroed inside the loop: the second tic reads none
        i = out.index("    hex.zero 1, thseen")
        out.insert(out.index("    hex.dec 1, wt_rep"), out.pop(i))
    elif mut == "barinloop":                        # the bar written per tic
        j = out.index(WR._WT_BAR)
        bar = out[j:]
        out = out[:j]
        k = out.index("    hex.dec 1, wt_rep")
        out = out[:k] + bar + out[k:]
    elif mut == "poolsonce":                        # the pools after the loop, not in it
        p = [ln for ln in out if ln.startswith("stl.fcall ")]
        out = [ln for ln in out if not ln.startswith("stl.fcall ")]
        k = out.index("wt_done:") + 1
        out = out[:k] + p + out[k:]
    return out


def _expected() -> bytes:
    """the model's frame (World.tic): P_ChangeSector once; MONSTER_TICS_PER_FRAME x (the monster tic reading the
    last picture's marks, the fireballs, the blood); the marks reset; the bar -- nothing but C and the reset on a
    finished level"""
    lines = []
    for done in FRAMES:
        if done:
            lines.append("CZ5")
        else:
            lines.append("C" + "T5PF" * MONSTER_TICS_PER_FRAME + "Z5B")
    return ("\n".join(lines) + "\n").encode()


def _run(tmp_path, name, mut=None) -> bool:
    body = ["stl.startup_and_init_all"]
    for done in FRAMES:
        body += ["    hex.set 1, lvdone, %d" % done, "    hex.set 1, thseen, 5",      # last frame's render marked
                 "    stl.fcall frame_leaf, fr_ret", "    stl.output 10"]
    body.append("stl.loop")
    code = _composed(mut)
    i = code.index("    hex.zero 1, thseen")
    code = code[:i] + [_say("Z"), "    hex.print_as_digit 1, thseen, 0"] + code[i:]
    leaf = ["frame_leaf:"] + code + ["    stl.fret fr_ret"]
    # M7 P7 (package D): p5_tic_lines advances `lvtime` inside its lvdone guard (restartcode.lvtime_tic_lines)
    decls = WR.WT_DECLS + ["lvdone: hex.vec 1", "thseen: hex.vec 1", "lvtime: hex.vec 4", "pj_pret: hex.vec w/4",
                           "fx_pret: hex.vec w/4", "fr_ret: hex.vec w/4"]
    p = tmp_path / ("%s.fj" % name)
    p.write_text("\n".join(body + leaf + _leaves() + decls) + "\n", encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return fj.assemble_and_run_test_output([consts.resolve(), p.resolve()], b"", _expected(), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_composition_is_the_old_text_at_tempo_one():
    assert WR.world_tic_lines(_tic(), _pools(), 1) == _tic() + _pools()
    with pytest.raises(AssertionError):
        WR.world_tic_lines(_tic(), _pools(), 16)           # wt_rep is one nibble
    with pytest.raises(AssertionError):
        WR.world_tic_lines(_tic()[:-1], _pools(), 2)       # the seen reset is not where the shape says


def test_the_monster_world_runs_the_tempo(tmp_path):
    assert MONSTER_TICS_PER_FRAME == 2
    assert _run(tmp_path, "wt"), "the emitted monster world parted from World._monster_world's order"


@pytest.mark.parametrize("mut", ["onetic", "seeninloop", "barinloop", "poolsonce"])
def test_control_a_broken_tempo_loop_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "wt_" + mut, mut), "%s passed: the comparison is vacuous" % mut
