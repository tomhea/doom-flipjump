"""gamespeed_trail.py -- where gamespeed's ten games REALLY go: the game binary, read through the probe.

    python scratchpad/12m/gamespeed_trail.py                        # blocked27, all ten runs
    python scratchpad/12m/gamespeed_trail.py --fjm build/X.fjm --labels <X.labels.tsv.gz> --runs 0 3

`gamespeed.py --validate` reports where the ten speed runs go by stepping the ORACLE, and that
report is quoted as ship evidence. Until fix/gamespeed-validate-doors it stepped a scene whose doors
never open, while the binary opens a door whenever a run holds `use` in its box -- so run 0 was
reported stopped at a door the binary walks through. This tool asks the BINARY.

For each run it plays gamespeed's exact composition on the game binary -- the menu frames, enter,
then the run's 100 frames of keys (`gamespeed.full_script` / `events_for`) -- with
`scratchpad/gp/probe.py` attached, READING (never writing) the player's pose, the game mode and
every door's state at each game frame's present. It compares that trail, frame by frame, with the
record `--validate` itself keeps (`validate_scripts(..., trails=)`: the same function, not a copy):

  TRAIL          --validate's door-aware record equals the binary on every frame of every run --
                 x, y, angle and all 13 door states -- and every run is fully presented.
  CONTROL-POSE   the doors-shut replay (--validate before the fix) must PART from the binary.
  CONTROL-DOORS  a --validate whose doors open on `use` anywhere (the use-box test removed) must be
                 rejected, and on frames where its pose still equals the binary's, so that only the
                 door-state term can be what rejects it.
The two controls are the negative controls (docs/cr-rules.md R9): a comparison the door-blind or
the door-wrong replay could also pass would prove nothing. It prints `gamespeed.BINARY_ENDS` and
`BINARY_DOORS` (doors a run makes passable, from the binary's door states).

Plans the scripts before taking the binary lock (the planner is ~75 s), then holds the lock
(probe.binary_lock) for the runs: one binary at a time (CLAUDE.md rule 1).
"""
import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for q in (HERE, ROOT / "scratchpad" / "gp"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))
import gamespeed as GS                                                      # noqa: E402
import onewalk                                                              # noqa: E402
import probe as P                                                           # noqa: E402


def records(n_runs: int):
    """--validate's per-frame records of runs 0..n_runs-1: door-aware, doors-shut, and door-wrong"""
    doors, shut, wrong = [], [], []
    GS.validate_scripts(n_runs, quiet=True, trails=doors)
    GS.validate_scripts(n_runs, quiet=True, doors=False, trails=shut)
    real = onewalk.in_use_box_fixed
    onewalk.in_use_box_fixed = lambda box, x, y: True       # `use` opens every door, anywhere
    try:
        GS.validate_scripts(n_runs, quiet=True, trails=wrong)
    finally:
        onewalk.in_use_box_fixed = real
    return doors, shut, wrong


def binary_trail(gb, table, orc, run: int, n: int = 100):
    """([(viewx, viewy, viewangle, dstate, mode)] at each game frame's present, frames presented)"""
    import m2_std_gate as gate
    mf = gate.MENU_FRAMES
    per_frame = GS.full_script(run, n)
    p = P.Probe(P.game_cells(orc.ndoors), table, gb.width)
    got = {}

    def present(pr, f):
        if f >= mf:
            c = pr.read_cells(["viewx", "viewy", "viewangle", "dstate", "mode"])
            got[f - mf] = (c["viewx"], c["viewy"], c["viewangle"], c["dstate"], c["mode"])
    p.on_present(present)
    r = gb.run(len(per_frame), GS.events_for(per_frame), p,
               pre_run=lambda pr: pr.verify_known(orc.known_pristine()))
    return [got.get(f) for f in range(n)], len(r.frames) - mf


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fjm", default=str(P.DEFAULT_FJM))
    ap.add_argument("--labels", default=str(P.DEFAULT_LABELS))
    ap.add_argument("--runs", type=int, nargs="*", default=list(range(GS.TOUR_TARGETS)))
    ap.add_argument("--stream", default="gamespeed-trail")
    a = ap.parse_args()
    t = time.time()
    doors, shut, wrong = records(max(a.runs) + 1)
    dsim = onewalk.DoorSim()
    passes = [dsim.passes[si] for si in dsim.order]
    print("  (--validate's records made in %.0f s, outside the binary lock)" % (time.time() - t),
          flush=True)
    ends, opened, trail_ok, pose_parts, door_rejects = [], [], True, [], []
    with P.binary_lock(a.stream):
        orc = P.Oracle()
        table = P.LabelTable.load(Path(a.labels), {c.label for c in P.game_cells(orc.ndoors).values()})
        gb = P.GameBinary(Path(a.fjm))
        print("gamespeed_trail: %s sha256 %s, labels %s" % (Path(a.fjm).name, gb.sha[:16],
                                                          Path(a.labels).name), flush=True)
        for r in a.runs:
            trail, presented = binary_trail(gb, table, orc, r)
            full = [b is not None and b[4] == 0 and b[:4] == d for b, d in zip(trail, doors[r])]
            pose = [b is not None and b[:3] == s[:3] for b, s in zip(trail, shut[r])]
            bad = [b is None or b[4] != 0 or b[:4] != w for b, w in zip(trail, wrong[r])]
            bad_pose_equal = sum(1 for b, w, x in zip(trail, wrong[r], bad)
                                 if x and b is not None and b[:3] == w[:3])
            x, y = trail[-1][0], trail[-1][1]
            ever = [max(b[3][i] for b in trail) for i in range(len(passes))]
            ends.append((x >> 16, y >> 16))
            opened.append(sum(1 for e, ps in zip(ever, passes) if e >= ps))
            trail_ok &= presented == len(doors[r]) and all(full)
            first = next((f for f, e in enumerate(pose) if not e), None)
            if first is not None:
                pose_parts.append(r)
            if bad_pose_equal:
                door_rejects.append(r)
            print("  run %d: the binary ends (%d, %d) [16.16: %d, %d], %d door(s) opened; --validate "
                  "equal on %d/%d frames; doors-shut pose on %d/%d%s; door-wrong rejected on %d "
                  "frames, %d with its pose equal; %d/%d frames presented"
                  % (r, x >> 16, y >> 16, x, y, opened[-1], sum(full), len(full), sum(pose),
                     len(pose), "" if first is None else " (parts at game frame %d)" % first,
                     sum(bad), bad_pose_equal, presented, len(doors[r])), flush=True)
    print("BINARY_ENDS = (%s)" % ", ".join("(%d, %d)" % e for e in ends))
    print("BINARY_DOORS = (%s)" % ", ".join(str(d) for d in opened))
    print("TRAIL         --validate's record equals the binary on every frame of every run: %s"
          % ("PASS" if trail_ok else "FAIL"))
    print("CONTROL-POSE  the doors-shut replay parts from the binary: %s"
          % ("PASS (runs %s)" % pose_parts if pose_parts else
             "FAIL -- no run in this set parts, so the comparison cannot tell a door-blind replay "
             "from the binary (include run 0)"))
    print("CONTROL-DOORS the door-wrong replay is rejected where its pose is right: %s"
          % ("PASS (runs %s)" % door_rejects if door_rejects else
             "FAIL -- only its pose could reject it, so the door states were never tested"))
    return 0 if trail_ok and pose_parts and door_rejects else 1


if __name__ == "__main__":
    sys.exit(main())
