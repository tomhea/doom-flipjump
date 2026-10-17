"""M8 F7 (issue #123 item 4, the `exit-bar-stale` stand-in retired): THE BAR ON THE EXIT FRAME, on the real flipjump
engine, against the model's own exit frame on E1M2.

World.tic's exit frame (docs/gp-p67-interface.md G2): the use press ends the level (`g_leveldone`), and the player phase
still runs after it -- on E1M2 the exit switch's box (line 737) has a health bonus beside it, so ONE frame can press the
exit AND take the bonus. The monsters' world and `leveltime` skip that tic; every later tic is frozen. The bar the
picture shows is the model's health and armor after the tic (`monsters.MonsterPhase.screen_kw`).

The fj side is the game tier's frame tail AFTER the player phase: the monsters' world composed by the REAL
`wall_renderer.world_tic_lines` (the tempo's loop, `MONSTER_TICS_PER_FRAME` tics) around the REAL `p5_tic_lines` --
the pools' phases (stubbed: they skip themselves while `lvdone` and never touch the bar), the `lvdone` guard with
`leveltime`, and hurtcode's `hp_bar` -- at `bar_always`, the setting the emitter takes for E1M2
(`exit_frame_bar_hazards`). Each record is one model frame: the cells the player phase left (p_hp, p_ar, lvdone) and the
tic-start `leveltime` are poked, the tail runs, and `hud_v`'s health and armor digits and `lvtime` must be the model's.
`hud_v` carries over between records, as the binary's does: a stale bar shows.

R9: the guarded bar (`bar_always=False`, E1M1's text -- the stand-in's program) is caught on the exit frame; a guard
that also lets `leveltime` run on the exit frame is caught there too.
"""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj import hurtcode as H
from doomfj import weaponcode as WC
from doomfj import wall_renderer as WR
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.restartcode import LVTIME_NIBBLES
from doomfj.wad import WadFile
from doomfj.world import MONSTER_TICS_PER_FRAME, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
MAPWAD = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
needs_map = pytest.mark.skipif(not MAPWAD.exists(), reason="needs tests/fixtures/freedoom_e1m2.wad")
START = (1888, 1240)          # inside the exit box, on the bonus's floor (-48), 32 units west of the bonus at (1920, 1240)
HEALTH_SLOTS = [hudcode.slot_index("health%d" % k) for k in range(3)] + [hudcode.slot_index("armor%d" % k)
                                                                         for k in range(3)]


def _mw():
    return WadFile.from_path(str(MAPWAD))


def _frames(health=57, armor=3):
    """the model's frames: [(p_health, p_armor, g_leveldone after the tic, leveltime before, leveltime after, bar
    digits)] -- two quiet frames, the exit frame (use + forward: the press, then the bonus), two frozen frames"""
    w = World(_mw(), "E1M2", skill=gd.SK_HARD, monsters="idle", player="final")
    w.teleport_player(START[0] << 16, START[1] << 16, 0)
    w.ws.p_health, w.ws.p_armor, w.ws.p_armortype = health, armor, 1 if armor else 0
    out = []
    for keys in ({}, {}, {"use": 1, "forward": 1}, {"use": 1, "forward": 1}, {}):
        t0 = w.ws.leveltime
        ev = w.tic(keys)
        ws = w.ws
        codes = hudcode.slot_codes(hud.slot_values(ammo=None, health=max(0, ws.p_health), armor=ws.p_armor,
                                                   owned=(False,) * 6, blue=False))
        out.append((ws.p_health, ws.p_armor, ws.g_leveldone, t0, ws.leveltime, [codes[i] for i in HEALTH_SLOTS],
                    ev.pickups))
    return out


def _tail(bar_always: bool):
    pools = WR.p5_tic_lines({"bar": H.hp_bar_lines()}, barrels=False, bar_always=bar_always)
    tic = ["mt_tic:", "  mt_skip:", "    hex.zero 1, thseen"]                  # the monster tic's documented shape
    return WR.world_tic_lines(tic, pools, MONSTER_TICS_PER_FRAME)


def _program(frames, bar_always=True, mutate=None):
    text = "\n".join(_tail(bar_always)) + "\n"
    if mutate is not None:
        new = mutate(text)
        assert new != text, "the mutant no longer matches the emitted text"
        text = new
    w = World(_mw(), "E1M2", skill=gd.SK_HARD, monsters="idle", player="final")
    start = hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))
    body = ["stl.startup_and_init_all"]
    for hp, ar, done, t0, _t1, _bar, _pk in frames:
        body += ["hex.set 3, p_hp, %d" % (hp & 0xFFF), "hex.set 2, p_ar, %d" % ar, "hex.set 1, lvdone, %d" % done,
                 "hex.set %d, lvtime, %d" % (LVTIME_NIBBLES, t0), "stl.fcall tail_leaf, tail_ret"]
        body += ["hex.print_as_digit 1, hud_v + %d*dw, 0" % i for i in HEALTH_SLOTS]
        body += ["hex.print_as_digit %d, lvtime, 0" % LVTIME_NIBBLES, "stl.output 10"]
    body += ["stl.loop"]
    decls = (H.hurt_decls(H.level_start(w)) + hudcode.hud_decls(start)
             + ["lvdone: hex.vec 1", "lvtime: hex.vec %d" % LVTIME_NIBBLES, "thseen: hex.vec 1", "wt_rep: hex.vec 1",
                "pj_pret: hex.vec w/4", "fx_pret: hex.vec w/4", "tail_ret: hex.vec w/4"])
    stubs = ["pj_phase:", "stl.fret pj_pret", "fx_phase:", "stl.fret fx_pret"]
    leaf = ["tail_leaf:", text, "stl.fret tail_ret"]
    tables = [generate_dispatch_table_fj("ammobcd", WC.ammo_digit_values(), index_nibbles=3, result_nibbles=3)]
    return "\n".join(body + decls + stubs + leaf + tables) + "\n"


def _expected(frames) -> bytes:
    return "".join("".join("%x" % d for d in bar) + "%0*x" % (LVTIME_NIBBLES, t1) + "\n"
                   for _hp, _ar, _done, _t0, t1, bar, _pk in frames).encode()


def _run(tmp_path, name, frames, **kw) -> bool:
    p = tmp_path / ("%s.fj" % name)
    p.write_text(_program(frames, **kw), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", _expected(frames), memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


@needs_map
def test_the_model_takes_a_bonus_on_the_exit_frame():
    """the scenario is what it claims: frame 2 presses the exit AND takes the health bonus (+1), the clock stops
    there, and the frozen frames change nothing; E1M2 is a map the emitter runs the bar after the guard on"""
    from doomfj.doors import exit_boxes
    fr = _frames()
    assert [f[2] for f in fr] == [0, 0, 1, 1, 1]
    assert fr[2][0] == fr[1][0] + 1 and ("item", 84, 2014) in [p[:3] for p in fr[2][6]], fr[2]
    assert fr[2][4] == fr[2][3] and fr[3][:2] == fr[4][:2] == fr[2][:2]
    mw = _mw()
    assert WR.exit_frame_bar_hazards(mw, "E1M2", exit_boxes(mw.linedefs("E1M2"), mw.vertexes("E1M2")))["hazards"]


@needs_map
@pytest.mark.parametrize("health, armor", [(57, 3), (100, 0), (99, 200)])
def test_the_exit_frame_bar_is_the_models(tmp_path, health, armor):
    assert _run(tmp_path, "exit_bar_%d_%d" % (health, armor), _frames(health, armor)), \
        "the bar after the exit frame parted from the model's"


@needs_map
@pytest.mark.parametrize("name, kw", [
    ("guarded", dict(bar_always=False)),                 # the stand-in's program: hp_bar inside the lvdone guard
    ("clock_runs", dict(mutate=lambda t: t.replace("hex.if1 1, lvdone, p5_bar_skip\n", "", 1))),
])
def test_control_a_stale_exit_bar_is_caught(tmp_path, name, kw):
    assert not _run(tmp_path, "exit_bar_" + name, _frames(), **kw), "%s passed: the comparison is vacuous" % name
