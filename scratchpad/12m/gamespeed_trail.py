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
oracle stepped two ways:
  doors  `onewalk.DoorSim` (the M2 gate's order: doors tic, then the player) -- what `--validate`
         steps now; compared on x, y, angle and all 13 door states;
  shut   every door shut, what `--validate` stepped before; compared on x, y and angle.
TRAIL PASS needs the door-aware replay equal to the binary on every frame of every run, and every
run fully presented. CONTROL PASS needs the doors-shut replay to PART from the binary somewhere:
that is the negative control (docs/cr-rules.md R9) -- a comparison the old, door-blind replay could
also pass would prove nothing. The ends it prints are `gamespeed.BINARY_ENDS`.

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
import probe as P                                                           # noqa: E402


def replays(run: int, n: int = 100):
    """(door-aware [(x, y, angle, doors)], doors-shut [(x, y, angle)]), one entry per game frame"""
    from onewalk import DoorSim
    rm, scene, sp = GS._oracle(GS.DEFAULT_WAD, GS.DEFAULT_MAP)
    dsim = DoorSim()
    st, sh = dsim.reset(), sp
    doors, shut = [], []
    for kd in GS.script(run, n):
        st = dsim.step(st, kd)
        sh = rm.step_sim(sh, kd, scene=scene)
        doors.append((st.x, st.y, st.angle, tuple(dsim.ds[si][0] for si in dsim.order)))
        shut.append((sh.x, sh.y, sh.angle))
    return doors, shut


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
    want = {r: replays(r) for r in a.runs}
    print("  (scripts planned and replayed in %.0f s, outside the binary lock)" % (time.time() - t),
          flush=True)
    ends, trail_ok, parted = [], True, []
    with P.binary_lock(a.stream):
        orc = P.Oracle()
        table = P.LabelTable.load(Path(a.labels), {c.label for c in P.game_cells(orc.ndoors).values()})
        gb = P.GameBinary(Path(a.fjm))
        print("gamespeed_trail: %s sha256 %s, labels %s" % (Path(a.fjm).name, gb.sha[:16],
                                                          Path(a.labels).name), flush=True)
        for r in a.runs:
            trail, presented = binary_trail(gb, table, orc, r)
            doors, shut = want[r]
            eq_d = [b is not None and b[:4] == d and b[4] == 0 for b, d in zip(trail, doors)]
            eq_s = [b is not None and b[:3] == s for b, s in zip(trail, shut)]
            first = next((f for f, e in enumerate(eq_s) if not e), None)
            x, y = trail[-1][0], trail[-1][1]
            ends.append((x >> 16, y >> 16))
            trail_ok &= presented == len(doors) and all(eq_d)
            if first is not None:
                parted.append(r)
            print("  run %d: the binary ends (%d, %d) [16.16: %d, %d]; door-aware replay equal on "
                  "%d/%d frames; doors-shut on %d/%d%s; %d/%d frames presented"
                  % (r, x >> 16, y >> 16, x, y, sum(eq_d), len(doors), sum(eq_s), len(shut),
                     "" if first is None else " (parts at game frame %d)" % first, presented,
                     len(doors)), flush=True)
    print("BINARY_ENDS = (%s)" % ", ".join("(%d, %d)" % e for e in ends))
    print("TRAIL   the door-aware replay equals the binary on every frame of every run: %s"
          % ("PASS" if trail_ok else "FAIL"))
    print("CONTROL the doors-shut replay parts from the binary: %s"
          % ("PASS (runs %s)" % parted if parted else
             "FAIL -- no run in this set parts, so the comparison cannot tell a door-blind replay "
             "from the binary (include run 0)"))
    return 0 if trail_ok and parted else 1


if __name__ == "__main__":
    sys.exit(main())
