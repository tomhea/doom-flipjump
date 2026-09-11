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

DEFAULT_WAD = "tests/fixtures/freedoom_e1m1.wad"
DEFAULT_MAP = "E1M1"
UNIT = 1 << 16                      # the sim's fixed-point unit
_ORACLE = {}
_SCRIPTS = {}


def _oracle(wad, mapname):
    """(model, scene, spawn), built once -- doors shut, which is what a walk really sees"""
    key = (wad, mapname)
    if key not in _ORACLE:
        from doomfj.config import Config
        from doomfj.reference_model import ReferenceModel, build_scene, spawn_state
        from doomfj.wad import WadFile
        mw = WadFile.from_path(str(ROOT / wad))
        _ORACLE[key] = (ReferenceModel(Config()), build_scene(mw, mw, mapname),
                        spawn_state(mw, mapname))
    return _ORACLE[key]


TOUR_TARGETS = 10                   # one destination per seed, spread over the whole level


def _reachable(rm, scene, sx, sy):
    """(points, cells) the player can actually stand on, as world coordinates."""
    _path, cells = gate.walkable_cells(rm, scene, sx, sy)
    pts = [(cx * gate.NAV_CELL + gate.NAV_CELL // 2, cy * gate.NAV_CELL + gate.NAV_CELL // 2)
           for cx, cy in cells]
    return pts, cells


def _spread_targets(pts, sx, sy, n):
    """`n` reachable points spread as widely as possible -- farthest-point sampling, seeded at the
    point farthest from spawn. Deterministic: no RNG, and ties break on the list order the BFS
    produced, which is itself deterministic."""
    best = max(pts, key=lambda q: (q[0] - sx) ** 2 + (q[1] - sy) ** 2)
    chosen = [best]
    d2 = [(q[0] - best[0]) ** 2 + (q[1] - best[1]) ** 2 for q in pts]
    while len(chosen) < n:
        k = max(range(len(pts)), key=lambda idx: d2[idx])
        chosen.append(pts[k])
        for idx, q in enumerate(pts):
            nd = (q[0] - pts[k][0]) ** 2 + (q[1] - pts[k][1]) ** 2
            if nd < d2[idx]:
                d2[idx] = nd
    return chosen


_TOUR = {}


def _tour_plan(wad, mapname):
    """(open_scene, targets, door boxes, in-box test) for this map -- built ONCE.

    The reachable set and the destination list do not depend on the seed, and the BFS that finds
    them walks 12,576 cells with a `try_move` at every edge. Computing it inside `script()` ran it
    ten times and made `--validate` look hung."""
    key = (wad, mapname)
    if key in _TOUR:
        return _TOUR[key]
    from doomfj.doors import door_states, heights_for_states, in_use_box_fixed, use_boxes_xy
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import _signed, build_scene
    from doomfj.wad import WadFile

    rm, _scene, sp = _oracle(wad, mapname)
    mw = WadFile.from_path(str(ROOT / wad))
    secs, lds, sds = mw.sectors(mapname), mw.linedefs(mapname), mw.sidedefs(mapname)
    tbl = door_states(secs, lds, sds)
    # PLAN WITH THE DOORS OPEN. The routes must be allowed to cross them; the run then presses
    # `use` on the way, exactly as a player does. Planning against shut doors is what confined the
    # previous generation of scripts to the spawn side of the map -- 2,686 reachable cells instead
    # of 12,576.
    open_scene = build_scene(mw, mw, mapname,
                             heights_for_states(secs, lds, sds,
                                                {si: len(v) - 1 for si, v in tbl.items()}))
    sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    pts, _cells = _reachable(rm, open_scene, sx, sy)
    targets = _spread_targets(pts, sx, sy, TOUR_TARGETS)
    boxes = use_boxes_xy(secs, lds, sds, bake_bsp(mw, mapname).vertexes)
    _TOUR[key] = (open_scene, targets, [boxes[si] for si in sorted(tbl)], in_use_box_fixed)
    return _TOUR[key]


def _waypoints(rm, scene, st, goal, spacing=4):
    """A walkable path from where the player stands to `goal`, thinned to ~1 point per 64 units.

    Thinning matters: the BFS returns one point per 16-unit cell, and steering at every cell makes
    the player weave. Every 4th cell is far enough ahead to aim at."""
    from doomfj.reference_model import _signed
    gx, gy = goal
    tol = max(48.0, gate.NAV_CELL * 1.5)
    path, _seen = gate.walkable_cells(
        rm, scene, _signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16,
        lambda wx, wy: (wx - gx) ** 2 + (wy - gy) ** 2 <= tol * tol)
    if not path:
        return []
    return path[::spacing] + [path[-1]]


def _steer(rm, scene, st, waypoints, budget, boxes, in_box):
    """Drive toward each waypoint HOLDING FORWARD, turning while moving.

    ⚠ THIS IS THE WHOLE POINT, and the first route-based attempt got it wrong. `ANGLE_TURN` is
    41,943,040 BAM, so a 180-degree turn takes **51 frames** -- more than half a 100-frame run. A
    policy that turns to face a waypoint and only then walks spends its budget standing still: that
    version managed 27 moving frames out of 100 and travelled 269 units, WORSE than the random walk
    it replaced. A player does not do that; a player holds forward and steers. So `forward` is
    pressed on every frame and a turn is added only while the heading is off, which keeps ~100 of
    the 100 frames moving."""
    import math

    from doomfj.reference_model import ANGLE_TURN, _signed
    keys, wi, stuck = [], 0, 0
    while len(keys) < budget and wi < len(waypoints):
        tx, ty = waypoints[wi]
        x, y = _signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16
        if (x - tx) ** 2 + (y - ty) ** 2 <= (gate.NAV_CELL * 2) ** 2:
            wi += 1
            continue
        want = int(math.atan2(ty - y, tx - x) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
        err = (want - st.angle) & 0xFFFFFFFF
        if err > (1 << 31):
            err -= 1 << 32                      # signed: which way is shorter
        kd = {"forward": True}
        if err > ANGLE_TURN // 2:
            kd["turn_left"] = True              # turn_left ADDS to the angle (measured)
        elif err < -(ANGLE_TURN // 2):
            kd["turn_right"] = True
        if any(in_box(b, st.x, st.y) for b in boxes):
            kd["use"] = True                    # a player opens the door in front of them
        nxt = rm.step_sim(st, kd, scene=scene)
        if abs(nxt.x - st.x) + abs(nxt.y - st.y) >= UNIT:
            stuck = 0
        else:
            stuck += 1
            if stuck >= 4:                      # this waypoint is not working out; aim past it
                wi += 1
                stuck = 0
        st = nxt
        keys.append(kd)
    return st, keys


def script(seed, n_game=100, wad=DEFAULT_WAD, mapname=DEFAULT_MAP):
    """run `seed`'s key sequence -- a ROUTE ACROSS THE LEVEL, steered against the oracle.

    ⚠ THREE GENERATIONS, AND THE FIRST TWO BOTH LOOKED FINE.

    gen 1 was an open-loop key pattern: all ten runs walked into geometry and stayed there. Caught
    by CR-2026-09-06, which replaced it with a greedy policy -- step forward, turn when the
    geometry refuses -- that is never blocked and therefore satisfied every control the harness had.

    gen 2 was still a RANDOM WALK, and a walk with no destination does not go anywhere. MEASURED
    2026-09-11: eight of the ten runs ended **within 220 units of spawn**, which is 13.7% of the
    area reachable with the doors shut and roughly 3% of what a player can actually reach
    (2,686 cells shut, 12,576 open, on a map 3,952 x 3,400 units). The headline ops/frame was a
    STARTING-ROOM number -- the cheapest geometry on E1M1, measured ten times. Nothing in the
    harness noticed; the owner noticed from how the game FELT, which is not how a metric should be
    caught.

    gen 3 gives each seed its own destination, chosen by farthest-point sampling over everything
    reachable WITH DOORS OPEN, and steers there while holding forward. `use` is pressed inside door
    use boxes, because a run that never opens a door cannot leave the first fifth of the level.

    Deterministic (no RNG anywhere), and `--validate` reports coverage per seed."""
    key = (seed, n_game, wad, mapname)
    if key in _SCRIPTS:
        return _SCRIPTS[key]
    rm, _scene, sp = _oracle(wad, mapname)
    open_scene, targets, boxes, in_box = _tour_plan(wad, mapname)

    keys, st = [], sp
    for k in range(TOUR_TARGETS):
        if len(keys) >= n_game:
            break
        goal = targets[(seed + k) % TOUR_TARGETS]
        wps = _waypoints(rm, open_scene, st, goal)
        if not wps:
            continue
        st, more = _steer(rm, open_scene, st, wps, n_game - len(keys), boxes, in_box)
        if not more:
            continue                            # already there; try the next destination
        keys += more

    # A run that ends early (an unreachable leg, or every destination reached) must not be left
    # standing still -- a stationary frame is a cheap frame counted as play. Fall back to gen 2's
    # forward-or-turn policy, and `--validate` reports how many frames came from it.
    turn = "turn_left" if seed % 2 else "turn_right"
    while len(keys) < n_game:
        kd = {"forward": True}
        nxt = rm.step_sim(st, kd, scene=open_scene)
        if abs(nxt.x - st.x) + abs(nxt.y - st.y) >= UNIT:
            st = nxt
        else:
            kd = {turn: True}
            st = rm.step_sim(st, kd, scene=open_scene)
        keys.append(kd)

    _SCRIPTS[key] = keys[:n_game]
    return _SCRIPTS[key]


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
    from `memory_width`. The version this replaced hardcoded both, and they fail in opposite
    directions: `// 4` at w=64 reports TWICE the words (a false FAIL -- loud), while `data[64:]`
    at segment_num > 1 slices into the segment table and measures ZERO words (a false PASS --
    silent). See `fjmsize` controls C2 and C3.
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


def binding_speed(run_avgs):
    """THE BINDING SPEED METRIC (owner, 2026-09-06): the average of the mean run-average and the
    80th-percentile run.

    The mean alone flatters a binary -- it is dragged down by the cheap viewpoints, and the run
    spread here is ~1.9x. The p80 alone is one specific trajectory, so a change that helps typical
    frames can look like a regression because it did not help THAT run (S1 measured exactly that:
    mean -0.75%, p80 +0.10%). Averaging the two keeps the percentile's protection against a
    flattering mean while not letting a single run decide the verdict.
    """
    return (sum(run_avgs) / len(run_avgs) + percentile_run(run_avgs)) / 2.0


def report(run_avgs, raw_avgs, size):
    mean = sum(run_avgs) / len(run_avgs)
    p80 = percentile_run(run_avgs)
    binding = binding_speed(run_avgs)
    speed_ok, size_ok = binding <= SPEED_TARGET, size.data_pct <= SIZE_TARGET_PCT
    print("")
    print("=" * 78)
    print("SPEED  BINDING (mean+p80)/2: %s ops/frame   (target <= %s)  %s"
          % (format(int(binding), ","), format(SPEED_TARGET, ","),
             "PASS" if speed_ok else "OVER"))
    print("SPEED  mean run-average   : %s ops/frame" % format(int(mean), ","))
    print("SPEED  80th-pct run avg   : %s ops/frame" % format(int(p80), ","))
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

def validate_scripts(n_runs=10, n_frames=100, wad=DEFAULT_WAD, mapname=DEFAULT_MAP, quiet=False):
    """Step the ORACLE through every script and report whether each run actually PLAYS.

    ⚠ The measure here is BLOCKED FRAMES, not distance travelled. The previous version reported
    only end-position spread and total distance, and passed a set of scripts in which nine of ten
    runs were pinned against geometry for the majority of their movement frames -- because a player
    scraping a wall still accumulates distance. A run that presses forward and does not move is
    measuring a stuck viewpoint, and the whole metric is a weighted average of viewpoints.

    Returns [(end_xy, travelled, move_frames, moved_frames)] per run.
    """
    rm, scene, sp = _oracle(wad, mapname)
    out = []
    for r in range(n_runs):
        st, travelled, move_frames, moved_frames = sp, 0, 0, 0
        for kd in script(r, n_frames, wad, mapname):
            prev = (st.x, st.y)
            st = rm.step_sim(st, kd, scene=scene)
            d = abs(st.x - prev[0]) + abs(st.y - prev[1])
            travelled += d
            if kd.get("forward") or kd.get("back"):
                move_frames += 1
                if d >= UNIT:
                    moved_frames += 1
        ex, ey = st.x >> 16, st.y >> 16
        out.append(((ex, ey), travelled >> 16, move_frames, moved_frames))
        if not quiet:
            blocked = 100.0 * (move_frames - moved_frames) / max(1, move_frames)
            print("  run %2d: ends (%6d,%6d)  %5d from spawn  %6d travelled  "
                  "moved on %3d/%3d move-frames (%.0f%% blocked)"
                  % (r, ex, ey,
                     int(((((st.x - sp.x) >> 16) ** 2) + (((st.y - sp.y) >> 16) ** 2)) ** 0.5),
                     travelled >> 16, moved_frames, move_frames, blocked), flush=True)
    ends = [e for e, _t, _m, _mv in out]
    spread = max(max(e[i] for e in ends) - min(e[i] for e in ends) for i in (0, 1))
    if not quiet:
        worst = max(100.0 * (m - mv) / max(1, m) for _e, _t, m, mv in out)
        print("  distinct end cells: %d/%d ; widest spread %d units ; worst run %.0f%% blocked"
              % (len({(x // 64, y // 64) for x, y in ends}), n_runs, spread, worst), flush=True)
    return out, spread


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
    # N4b THE BINDING METRIC: strictly between the mean and the p80, and it MOVES with both.
    xs = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    m, p = sum(xs) / len(xs), percentile_run(xs)
    check("N4b binding is the average of the mean and the p80",
          abs(binding_speed(xs) - (m + p) / 2) < 1e-9, "mean %.1f p80 %.1f -> %.1f"
          % (m, p, binding_speed(xs)))
    check("N4b it lies between them (never outside)", m <= binding_speed(xs) <= p)
    lowered = xs[:-1] + [10.0]                     # make the SLOWEST run fast: mean falls, p80 same
    check("N4b it responds to a change the p80 alone cannot see",
          binding_speed(lowered) < binding_speed(xs),
          "%.1f -> %.1f while p80 stays %.1f"
          % (binding_speed(xs), binding_speed(lowered), percentile_run(lowered)))

    # N5  THE SIZE CONTROL is fjmsize's, and it is a different file -- assert the wiring, and that
    #     the ceiling this file compares against is derived rather than typed.
    check("N5 the ceiling is derived from the width, not a literal",
          ceiling_words(32) == 134_217_728 and ceiling_words(64) != ceiling_words(32))

    # N6  THE SCRIPT CONTROL (gap G5), and the one that failed to do its job the first time.
    #     The old version checked `travelled >= 64` per run, which a player scraping a wall for
    #     95% of a run still satisfies -- so it passed a script set whose 80th-percentile run
    #     moved on 5 of 92 movement frames. The check is now PER FRAME: of the frames that press
    #     forward or back, how many actually displaced the player?
    print("  -- stepping the oracle through the 10 scripts ...", flush=True)
    try:
        rows, spread = validate_scripts(quiet=True)
        ends = [e for e, _t, _m, _mv in rows]
        cells = len({(x // 64, y // 64) for x, y in ends})
        blocked = [100.0 * (m - mv) / max(1, m) for _e, _t, m, mv in rows]
        check("N6 the 10 scripts end in >= 6 distinct 64-unit cells", cells >= 6,
              "%d distinct of 10" % cells)
        check("N6 they spread over >= 256 units", spread >= 256, "%d units" % spread)
        check("N6 EVERY run moves on >= 60%% of its movement frames",
              max(blocked) <= 40.0, "worst run %.0f%% blocked" % max(blocked))
        check("N6 no run is mostly stuck (the old check passed at 95%% blocked)",
              max(blocked) < 95.0, "worst %.0f%%" % max(blocked))
        check("N6 every run travels >= 256 units from where it began",
              min(t for _e, t, _m, _mv in rows) >= 256,
              "min %d units" % min(t for _e, t, _m, _mv in rows))
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
