"""M8 (the owner, 2026-10-29): every level's speed set is its own playthrough -- playthrough_gate.speed_windows /
speed_record: SPEED_WINDOWS windows of SPEED_FRAMES world frames spread evenly from NEW GAME to LEVEL COMPLETE, the
binding gamespeed's (mean + p80) / 2 over the windows. Control (R9): a set from the play's first windows only reads a
different binding on a play whose frames grow heavier -- the spread is what the set measures."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scripts", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", ROOT / "scratchpad" / "gp"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))

import gamespeed as GS                    # noqa: E402
import playthrough_gate as PG             # noqa: E402


def _play(menu=5, world=3000, after=10):
    """frame_ops: menu frames (cheap), world frames growing heavier, the LEVEL COMPLETE screen (cheap)"""
    return [1000] * menu + [10_000_000 + 1000 * f for f in range(world)] + [500] * after


def test_the_windows_spread_from_new_game_to_level_complete():
    ops = _play()
    win = PG.speed_windows(ops, 5, 3005)
    assert len(win) == PG.SPEED_WINDOWS
    assert win[0][0] == 5 and win[-1][0] == 3005 - PG.SPEED_FRAMES          # the first and the last 100 world frames
    gaps = {b[0] - a[0] for a, b in zip(win, win[1:])}
    assert max(gaps) - min(gaps) <= 1                                         # evenly spread
    assert all(v > 1e7 for _s, v in win)                                      # no menu or LEVEL COMPLETE frame in one


def test_a_short_play_overlaps_its_windows():
    win = PG.speed_windows(_play(world=499), 5, 504)                         # E1M1's 499 world frames
    assert len(win) == PG.SPEED_WINDOWS and win[-1][0] + PG.SPEED_FRAMES == 504


def test_the_binding_is_gamespeeds_over_the_windows():
    ops = _play()
    rec = PG.speed_record(ops, 5, 3005)
    avgs = [v for _s, v in PG.speed_windows(ops, 5, 3005)]
    assert rec["binding"] == GS.binding_speed(avgs) and rec["p80"] == GS.percentile_run(avgs)
    assert rec["world_frames"] == 3000 and rec["target"] == GS.SPEED_TARGET


def test_control_the_first_windows_alone_read_another_binding():
    ops = _play()
    first = [sum(ops[5 + 100 * k:5 + 100 * k + 100]) / 100 for k in range(PG.SPEED_WINDOWS)]
    assert GS.binding_speed(first) < PG.speed_record(ops, 5, 3005)["binding"] - 1e5


def test_the_creator_reads_the_speed_and_holds_it_to_cap_22():
    import build_episode as BE
    step = next(s for s in BE.plan_map(BE.REGISTRY["E1M3"], ROOT / "build" / "episode") if s.name == "playthrough")
    assert "--speed-json" in step.argv
    ok = ("PLAYTHROUGH GATE PASS -- E1M3 LEVEL COMPLETE at frame 3147 (world 3143) at easy, ...\n"
          "PLAYTHROUGH SPEED binding (mean + p80)/2 over 11 windows of 100 world frames: 15,123,456 ops/frame (...) PASS\n")
    st, met, _why = BE.judge(step, BE.REGISTRY["E1M3"], 0, ok)
    assert st == "PASS" and met["speed_binding"] == 15_123_456
    # CONTROL: over CAP-22 the step FAILS though the gate's own line says PASS
    over = ok.replace("15,123,456", "23,000,000")
    st, met, why = BE.judge(step, BE.REGISTRY["E1M3"], 0, over)
    assert st == "FAIL" and "CAP-22" in why
