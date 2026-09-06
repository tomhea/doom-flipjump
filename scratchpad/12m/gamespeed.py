"""THE SUCCESS-METRIC INSTRUMENT for the combined-full-game campaign (owner spec, 2026-09-06).

Two measured metrics, and nothing else is the success criterion:

  SPEED  -- play 10 different games of 100 frames each on the FULL game binary (collisions, sim,
            self-reset all included). Each RUN's stat is its total ops / 100 = that run's average
            ops/frame. Report the MEAN run-average and the 80th-PERCENTILE RUN (the run at the
            80%-high mark by average), showing that run's average-per-frame.
  SIZE   -- the game binary's decompressed word count as a PERCENTAGE of the address ceiling.

    python scratchpad/12m/gamespeed.py --fjm build/doom_e1m1_menu.fjm
    python scratchpad/12m/gamespeed.py --validate      # G5: do the 10 games go anywhere? (cheap)
    python scratchpad/12m/gamespeed.py --selftest      # R9 controls (cheap)
    python scratchpad/12m/gamespeed.py --selftest --fjm <path>    # + determinism on a real binary

THE DEVICE IS NOT INVENTED HERE. An earlier draft guessed
`flipjump.interpreter.io_devices.pc_io.PcIO` with `key_script=`/`frame_limit=` kwargs; that module
does not exist and the import was a `ModuleNotFoundError`. The real composition -- the one
`fj --io pc` builds, and therefore the one a human runs -- is `Recording`/`Stopper`/`PcIO`/
`NativeDeviceMemory` in `scratchpad/m2_std_gate.py:run_fj`, and this file IMPORTS it rather than
re-deriving it. If the device changes, both move together.

WHY THE MENU IS SUBTRACTED. The binary boots into the menu, so a run is `MENU_FRAMES` near-free
menu frames (~2,344 ops each) plus one-time startup, then the game. Leaving those in the numerator
DEFLATES the average -- it makes the metric look better for a reason that has nothing to do with
the renderer. So a single calibration run measures `startup + menu` once and every run subtracts
it, and BOTH numbers are printed (raw and menu-subtracted) so the choice is visible rather than
silent. Gap G8, first bullet.

WHY 100 FRAMES IS ASSERTED, NOT ASSUMED. A run that dies early returns a small op total and reads
as a WIN. `run_fj` returns the frames the screen actually presented, and this harness requires that
count to equal what it asked for. Gap G6.
"""
import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT / "scratchpad", ROOT):
    sys.path.insert(0, str(q))

from fjmsize import ceiling_words, read_fjm_size                          # noqa: E402
import m2_std_gate as gate                                                # noqa: E402
from m2_std_gate import ENTER, KeyEvent, MENU_FRAMES, to_events           # noqa: E402
from doomfj.wall_renderer import STANDALONE_POLLS                         # noqa: E402

SPEED_TARGET = 20_000_000          # 80th-percentile RUN's average ops/frame
SIZE_TARGET_PCT = 35.0             # of the address ceiling


# ----------------------------------------------------------------------------------------------
# The 10 games. They must GO SOMEWHERE DIFFERENT (gap G5).
# ----------------------------------------------------------------------------------------------
# The render alone spans 2.96M to 33.4M ops/frame across viewpoints -- 11x -- so the answer is
# dominated by where the ten games go. The first draft blended `(i+seed)%3` forward/turn bits,
# which fans out barely at all: every run leaves the spawn on roughly the same heading. These
# instead spend their opening frames turning by a per-run amount, so the ten runs leave the spawn
# on TEN DIFFERENT HEADINGS and then walk, with a periodic `use` so doors are exercised.
# `--validate` steps the oracle through all ten and prints where each ends up; that is the check
# that this docstring is telling the truth.

def script(seed, n_game=100):
    """run `seed`'s key sequence: fan out to a distinct heading, then walk it."""
    turn_frames = 2 * seed                       # 0, 2, 4 ... 18 frames of turning = 10 headings
    turn_key = "turn_left" if seed % 2 else "turn_right"
    keys = []
    for i in range(n_game):
        k = {}
        if i < turn_frames:
            k[turn_key] = True                   # the fan-out: no two runs face the same way
        else:
            k["forward"] = True
            j = i - turn_frames
            if j % 17 == 16:
                k["use"] = True                  # bump a door/wall now and then
            elif j % 11 == 10:
                k[turn_key] = True               # a small course correction, still per-run distinct
            elif j % 23 == 22:
                k["back"] = True                 # and back off a wall
        keys.append(k)
    return keys


def full_script(seed, n_game):
    """the menu frames the binary always boots into, then the game frames we are measuring"""
    return [{} for _ in range(MENU_FRAMES)] + script(seed, n_game)


def events_for(per_frame):
    """key events + the ENTER that leaves the menu, exactly as m2_std_gate composes them"""
    return to_events(per_frame) + [KeyEvent(MENU_FRAMES * STANDALONE_POLLS, True, ENTER),
                                   KeyEvent(MENU_FRAMES * STANDALONE_POLLS + 1, False, ENTER)]


# ----------------------------------------------------------------------------------------------
# SIZE
# ----------------------------------------------------------------------------------------------

def word_pct(fjm_path):
    """Decompressed words as a percent of the address ceiling.

    Delegates to `fjmsize`, which derives the header offset from `segment_num` and the word size
    from `memory_width`. The version this replaced hardcoded `data[64:]` and `// 4`; at w=64 that
    reported TWICE the true word count, i.e. it would have called a failing SIZE a PASS.
    """
    size = read_fjm_size(fjm_path)
    return size.data_words, size.data_pct, size


# ----------------------------------------------------------------------------------------------
# SPEED
# ----------------------------------------------------------------------------------------------

def one_run(fjm, per_frame):
    """play one game; return (total ops, frames presented)."""
    got, ops = gate.run_fj(Path(fjm), events_for(per_frame), len(per_frame))
    return ops, len(got)


def _demand_full_length(per_frame, ops, presented):
    """G6, and it lives HERE rather than in `one_run` on purpose.

    The first version asserted inside `one_run`, so the guarantee held only for the one runner
    that happened to contain it -- the selftest's injected runner sailed straight past and the
    harness happily reported 250 ops/frame for a run that lost a frame. The check belongs on the
    BOUNDARY where a runner's result enters the metric, so no runner can be exempt from it."""
    if presented != len(per_frame):
        raise AssertionError("the program presented %d frames, not %d (%s ops) -- a short run "
                             "reads as a WIN, so it is an error, not a datum"
                             % (presented, len(per_frame), format(ops, ",")))


def measure_speed(fjm_path, n_runs=10, n_frames=100, calibrate=True, runner=one_run):
    """Play n_runs games; return (run_avgs, raw_avgs, menu_ops).

    `runner` is injectable so the selftest can drive the reporting math without a heavy build.
    """
    menu_ops = 0
    if calibrate:
        # startup + the menu frames alone: the constant every run carries and none of it is game
        menu_frames = [{} for _ in range(MENU_FRAMES)]
        menu_ops, presented = runner(fjm_path, menu_frames)
        _demand_full_length(menu_frames, menu_ops, presented)
        print("calibration: startup + %d menu frames = %s ops (subtracted from every run)"
              % (MENU_FRAMES, format(menu_ops, ",")), flush=True)
    run_avgs, raw_avgs = [], []
    for r in range(n_runs):
        per_frame = full_script(r, n_frames)
        ops, presented = runner(fjm_path, per_frame)
        _demand_full_length(per_frame, ops, presented)
        raw = ops / presented
        avg = (ops - menu_ops) / n_frames
        run_avgs.append(avg)
        raw_avgs.append(raw)
        print("  run %2d: %s ops / %d presented -> raw %s, game-only %s ops/frame"
              % (r, format(ops, ","), presented, format(int(raw), ","), format(int(avg), ",")),
              flush=True)
    return run_avgs, raw_avgs, menu_ops


def percentile_run(run_avgs, pct=0.8):
    """the RUN at the pct-high mark, by its average -- not an interpolated value"""
    s = sorted(run_avgs)
    return s[min(len(s) - 1, math.ceil(pct * len(s)) - 1)]


def report(run_avgs, raw_avgs, size):
    mean = sum(run_avgs) / len(run_avgs)
    p80 = percentile_run(run_avgs)
    speed_ok, size_ok = p80 <= SPEED_TARGET, size.data_pct <= SIZE_TARGET_PCT
    print("")
    print("=" * 78)
    print("SPEED  mean run-average   : %s ops/frame" % format(int(mean), ","))
    print("SPEED  80th-pct run avg   : %s ops/frame   (target <= %s)  %s"
          % (format(int(p80), ","), format(SPEED_TARGET, ","), "PASS" if speed_ok else "OVER"))
    print("SPEED  spread lo..hi      : %s .. %s ops/frame"
          % (format(int(min(run_avgs)), ","), format(int(max(run_avgs)), ",")))
    print("SPEED  raw (menu included): mean %s, 80th-pct %s ops/frame"
          % (format(int(sum(raw_avgs) / len(raw_avgs)), ","),
             format(int(percentile_run(raw_avgs)), ",")))
    print("SIZE   words              : %s = %.2f%% of 2^%d   (target <= %.0f%%)  %s"
          % (format(size.data_words, ","), size.data_pct, size.ceiling.bit_length() - 1,
             SIZE_TARGET_PCT, "PASS" if size_ok else "OVER"))
    print("SIZE   span / file        : %s words (%.2f%%) / %s bytes"
          % (format(size.span_words, ","), size.span_pct, format(size.file_bytes, ",")))
    print("=" * 78)
    return speed_ok and size_ok


# ----------------------------------------------------------------------------------------------
# G5: are the ten games actually different games? (cheap -- the oracle, no fj)
# ----------------------------------------------------------------------------------------------

def validate_scripts(n_runs=10, n_frames=100, wad="tests/fixtures/freedoom_e1m1.wad",
                     mapname="E1M1", quiet=False):
    """Step the ORACLE through all ten scripts and report where each ends up.

    A script that walks into a wall for 100 frames measures a cheap corner and the metric is
    dominated by that. This is the control on the claim that the ten scripts explore.
    """
    from doomfj.config import Config
    from doomfj.reference_model import ReferenceModel, build_scene, spawn_state
    from doomfj.wad import WadFile

    mw = WadFile.from_path(str(ROOT / wad))
    rm = ReferenceModel(Config())
    scene = build_scene(mw, mw, mapname)
    sp = spawn_state(mw, mapname)
    ends, dists = [], []
    for r in range(n_runs):
        st = sp
        travelled = 0
        for kd in script(r, n_frames):
            prev = (st.x, st.y)
            st = rm.step_sim(st, kd, scene=scene)
            travelled += abs(st.x - prev[0]) + abs(st.y - prev[1])
        ex, ey = st.x >> 16, st.y >> 16
        ends.append((ex, ey))
        dists.append(travelled >> 16)
        if not quiet:
            print("  run %2d: ends at (%6d,%6d)  %5d units from spawn, %6d travelled"
                  % (r, ex, ey,
                     int(((((st.x - sp.x) >> 16) ** 2) + (((st.y - sp.y) >> 16) ** 2)) ** 0.5),
                     travelled >> 16), flush=True)
    spread = max(max(e[i] for e in ends) - min(e[i] for e in ends) for i in (0, 1))
    if not quiet:
        print("  distinct end cells: %d/%d ; widest spread %d units ; %d run(s) never moved"
              % (len({(x // 64, y // 64) for x, y in ends}), n_runs, spread,
                 sum(1 for d in dists if d < 64)), flush=True)
    return ends, dists, spread


# ----------------------------------------------------------------------------------------------
# R9: the negative controls
# ----------------------------------------------------------------------------------------------

def selftest(fjm=None):
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("gamespeed selftest -- a metric that cannot fail is not a metric", flush=True)

    # N1  THE VACUITY CONTROL. A short run returns a small op total and reads as a WIN. Drive the
    #     harness with a runner that presents fewer frames than asked and require it to RAISE.
    def short(_f, per_frame):
        return 1_000, len(per_frame) - 1                  # one frame missing, tiny op count

    try:
        measure_speed("x", n_runs=1, n_frames=4, calibrate=False, runner=short)
        check("N1 a short run is REJECTED, not reported as a win", False, "it returned a number!")
    except AssertionError as e:
        check("N1 a short run is REJECTED, not reported as a win", "presented" in str(e))

    def exact(_f, per_frame):
        return 1_000, len(per_frame)

    try:
        measure_speed("x", n_runs=1, n_frames=4, calibrate=False, runner=exact)
        check("N1 a full-length run is ACCEPTED (the control is not just always-raise)", True)
    except AssertionError:
        check("N1 a full-length run is ACCEPTED (the control is not just always-raise)", False)

    # N2  THE MENU-SUBTRACTION CONTROL. The menu ops must actually leave the numerator.
    per_op = 7_000

    def linear(_f, per_frame):
        return 500_000 + per_op * len(per_frame), len(per_frame)      # 500k startup + per frame

    avgs, raws, menu = measure_speed("x", n_runs=1, n_frames=100, calibrate=True, runner=linear)
    want = per_op                                          # startup+menu removed -> exactly per_op
    check("N2 menu+startup is measured", menu == 500_000 + per_op * MENU_FRAMES,
          "menu_ops=%s" % format(menu, ","))
    check("N2 game-only average removes it exactly", abs(avgs[0] - want) < 1e-9,
          "got %.1f, want %d" % (avgs[0], want))
    check("N2 the RAW average still contains it (so the two differ)", raws[0] > avgs[0],
          "raw %.1f > game-only %.1f" % (raws[0], avgs[0]))

    # N3  THE SENSITIVITY CONTROL. The per-frame figure must be independent of how many frames we
    #     ran -- if it drifts with the frame count it is measuring the harness, not the game.
    a100, _, _ = measure_speed("x", n_runs=1, n_frames=100, calibrate=True, runner=linear)
    a200, _, _ = measure_speed("x", n_runs=1, n_frames=200, calibrate=True, runner=linear)
    check("N3 the metric is per-frame (2x frames -> same per-frame cost)",
          abs(a100[0] - a200[0]) < 1e-6, "%.1f vs %.1f" % (a100[0], a200[0]))

    # N4  THE PERCENTILE CONTROL. It must pick a RUN, and the right one.
    check("N4 80th-pct of 1..10 is the 8th run", percentile_run(list(range(1, 11))) == 8,
          "got %s" % percentile_run(list(range(1, 11))))
    check("N4 it returns a member of the set, never an interpolation",
          percentile_run([1.0, 5.0, 9.0]) in (1.0, 5.0, 9.0))
    check("N4 it is order-independent",
          percentile_run([10, 3, 7, 1]) == percentile_run([1, 3, 7, 10]))

    # N5  THE SIZE CONTROL is fjmsize's, and it is a different file -- assert the wiring, and that
    #     the ceiling this file compares against is derived rather than typed.
    check("N5 the ceiling is derived from the width, not a literal",
          ceiling_words(32) == 134_217_728 and ceiling_words(64) != ceiling_words(32))

    # N6  THE SCRIPT CONTROL (gap G5). The ten games must go to ten different places.
    print("  -- stepping the oracle through the 10 scripts ...", flush=True)
    try:
        ends, dists, spread = validate_scripts(quiet=True)
        cells = len({(x // 64, y // 64) for x, y in ends})
        check("N6 the 10 scripts end in >= 6 distinct 64-unit cells", cells >= 6,
              "%d distinct of 10" % cells)
        check("N6 every run actually moves (none walks into a wall for 100 frames)",
              min(dists) >= 64, "min travelled %d units" % min(dists))
        check("N6 they spread over >= 256 units", spread >= 256, "%d units" % spread)
    except Exception as e:                                             # noqa: BLE001
        check("N6 the oracle can step the 10 scripts", False, "%s: %s" % (type(e).__name__, e))

    # N7  DETERMINISM, on a real binary if one was given. Heavy, so it is opt-in.
    if fjm:
        print("  -- N7 needs two real runs of %s ..." % fjm, flush=True)
        o1, _ = one_run(fjm, full_script(0, 10))
        o2, _ = one_run(fjm, full_script(0, 10))
        check("N7 the same script twice gives the SAME op count", o1 == o2,
              "%s vs %s" % (format(o1, ","), format(o2, ",")))
        o3, _ = one_run(fjm, full_script(1, 10))
        check("N7 a DIFFERENT script gives a different op count", o1 != o3,
              "%s vs %s" % (format(o1, ","), format(o3, ",")))
    else:
        print("  (N7 determinism skipped -- pass --fjm <path> to run it)", flush=True)

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_menu.fjm")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--frames", type=int, default=100)
    ap.add_argument("--no-calibrate", action="store_true",
                    help="do not measure/subtract the menu+startup constant")
    ap.add_argument("--validate", action="store_true",
                    help="G5: step the oracle through the 10 scripts and show where they go")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest(a.fjm if ("--fjm" in sys.argv and Path(a.fjm).exists()) else None)
    if a.validate:
        validate_scripts(a.runs, a.frames)
        return 0

    size = read_fjm_size(a.fjm)
    print("SIZE: %s" % size, flush=True)
    run_avgs, raw_avgs, _ = measure_speed(a.fjm, a.runs, a.frames, calibrate=not a.no_calibrate)
    ok = report(run_avgs, raw_avgs, size)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
