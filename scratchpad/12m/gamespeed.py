"""THE SUCCESS-METRIC INSTRUMENT for the combined-full-game campaign (owner spec, 2026-09-06).

⚠ DRAFT -- `measure_speed()` IS NOT RUNNABLE YET. Its `PcIO` import and kwargs are a GUESS;
the real device is the `Recording`/`Stopper`/`PcIO`/`NativeDeviceMemory` composition in
`scratchpad/m2_std_gate.py:run_fj`. It also has no R9 negative control and no assertion that 100
frames were actually presented, so NO NUMBER FROM THIS FILE MAY BE QUOTED AS EVIDENCE YET.
See docs/handoff-fullgame-metrics.md §2 and gaps G5/G6. `word_pct()` alone is finished and correct.

Two measured metrics, and nothing else is the success criterion:

  SPEED  -- play 10 different games of 100 frames each on the FULL game binary (collisions, sim,
            self-reset all included). Each RUN's stat is its total ops / 100 = that run's average
            ops/frame. Report the MEAN run-average and the 80th-PERCENTILE RUN (the run at the
            80%-high mark by average), showing that run's average-per-frame. Target: 80th-pct
            run <= 20,000,000 ops/frame.
  SIZE   -- the game binary's decompressed word count as a PERCENTAGE of 2^27 (the w=32 address
            ceiling, 134,217,728 words). Target: <= 35%.

"10 different games" = 10 deterministic key scripts (fixed seeds -- reproducible, no RNG), each a
100-frame walk/turn/use sequence. The game binary self-resets internally, so one native run()
with a 100-frame keyboard script returns that run's TOTAL ops -- no per-frame capture needed.

    python scratchpad/12m/gamespeed.py --fjm build/doom_e1m1_menu_p105.fjm
"""
import argparse
import lzma
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

CEIL_WORDS = 1 << 27          # 2^27 = 134,217,728 words = the w=32 address ceiling


def word_pct(fjm_path):
    """Decompressed words as a percent of the 2^27 ceiling."""
    data = Path(fjm_path).read_bytes()
    raw = lzma.decompress(data[64:], format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2}])
    words = len(raw) // 4
    return words, 100.0 * words / CEIL_WORDS


# 10 reproducible 100-frame key scripts. Keys are the 4-bit mask the standalone kb uses
# (bit0 forward, bit1 back, bit2 turn-left, bit3 turn-right; use is a separate poll -- see the
# gate). Each script is a deterministic pattern (index-driven, no RNG) exploring a different mix
# of turning / walking / using so the 10 runs span light and heavy frames.
def script(seed, n=100):
    keys = []
    for i in range(n):
        # a per-seed deterministic blend of forward / turn / occasional use
        f = 0b0001 if (i + seed) % 3 else 0
        turn = (0b0100 if (i // (2 + seed % 4)) % 2 else 0b1000) if (i + seed) % 2 else 0
        keys.append(f | turn)
    return keys


def measure_speed(fjm_path, n_runs=10, n_frames=100):
    """Play n_runs games of n_frames each; return each run's average ops/frame."""
    from doomfj.fastrun import FjmRunner
    # the standalone game is driven by a scripted keyboard device that EOFs after n_frames
    # presented frames -- the same PcIO the `fj --io pc` CLI builds (see m5_gate). Import the
    # device the shipped runner uses so this measures the real object.
    from flipjump.interpreter.io_devices.pc_io import PcIO   # adjust import to the repo's device
    runner = FjmRunner(Path(fjm_path))
    print("native engine: %s" % runner.native, flush=True)
    run_avgs = []
    for r in range(n_runs):
        keys = script(r, n_frames)
        io = PcIO(key_script=keys, frame_limit=n_frames)     # scripted keys in, frames out
        total = runner.run(io)
        avg = total / n_frames
        run_avgs.append(avg)
        print("  run %2d: %s ops over %d frames -> %s ops/frame avg"
              % (r, format(total, ","), n_frames, format(int(avg), ",")), flush=True)
    return run_avgs


def report(run_avgs, words, pct):
    run_avgs = sorted(run_avgs)
    mean = sum(run_avgs) / len(run_avgs)
    # 80th-percentile RUN: index ceil(0.8*N)-1 in the sorted run averages
    import math
    p80 = run_avgs[min(len(run_avgs) - 1, math.ceil(0.8 * len(run_avgs)) - 1)]
    print("")
    print("=" * 64)
    print("SPEED  mean run-average   : %s ops/frame" % format(int(mean), ","))
    print("SPEED  80th-pct run avg   : %s ops/frame   (target <= 20,000,000)  %s"
          % (format(int(p80), ","), "PASS" if p80 <= 20_000_000 else "OVER"))
    print("SIZE   words              : %s = %.1f%% of 2^27   (target <= 35%%)  %s"
          % (format(words, ","), pct, "PASS" if pct <= 35.0 else "OVER"))
    print("=" * 64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_menu_p105.fjm")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--frames", type=int, default=100)
    a = ap.parse_args()
    words, pct = word_pct(a.fjm)
    print("SIZE: %s words = %.1f%% of 2^27" % (format(words, ","), pct), flush=True)
    run_avgs = measure_speed(a.fjm, a.runs, a.frames)
    report(run_avgs, words, pct)


if __name__ == "__main__":
    main()
