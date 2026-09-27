"""M7 P1.5 -- check scratchpad/gp/gatestate.py's MECHANICS on a real binary before any P1.5 binary
exists: a pre-P1.5 game binary (no skill menu -- its table lacks menu_scr/menu_sel, which the probe
drops), eight frames: two menu frames, esc on frame 2 (the world from there), forward held from
frame 3. Every read cell but the menu ones must equal the oracle's state after that frame; then a
control: the same reads against an oracle whose frame 5 view is one unit off must disagree exactly
there.

    python scratchpad/gp/gatestate_check.py --fjm <a pre-P1.5 game binary> --labels <its label table>
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scratchpad" / "gp"), str(ROOT / "scratchpad"), str(ROOT / "src")]
import gatestate as GST                                                       # noqa: E402
from doomfj.config import Config                                              # noqa: E402
from doomfj.doors import door_states, initial_states                          # noqa: E402
from doomfj.reference_model import ReferenceModel, build_scene, spawn_state   # noqa: E402
from doomfj.wad import WadFile                                                # noqa: E402
from doomfj.wall_renderer import STANDALONE_POLLS                             # noqa: E402
from flipjump.interpreter.io_devices.KeyboardIO import KeyEvent               # noqa: E402

ESC, K_FWD, FRAMES = 0x1B, 0x77, 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", required=True)
    ap.add_argument("--labels", required=True)
    args = ap.parse_args()
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    order = sorted(door_states(secs, lds, sds))
    init = initial_states(secs, lds, sds)
    doors0 = [init[si] for si in order]
    events = [KeyEvent(2 * STANDALONE_POLLS, True, ESC),
              KeyEvent(2 * STANDALONE_POLLS + 1, False, ESC),
              KeyEvent(3 * STANDALONE_POLLS, True, K_FWD)]
    got, ops, reads = GST.run_reading_state(Path(args.fjm), Path(args.labels), events, FRAMES,
                                            len(order))
    print("ran %d frames, %s ops; cells read: %s" % (len(got), format(ops, ","), sorted(reads[0])))

    rm = ReferenceModel(Config())
    scene = build_scene(mw, mw, "E1M1")
    st = spawn_state(mw, "E1M1")
    wants = []
    for f in range(FRAMES):
        mode = 1 if f < 2 else 0
        if mode == 0:
            st = rm.step_sim(st, {"forward": f >= 3}, scene=scene)
        w = GST.oracle_state(st.x, st.y, st.angle, mode, 0, 0, doors0)
        for k in ("menu_scr", "menu_sel"):            # a pre-P1.5 binary has neither
            w.pop(k)
        wants.append(w)

    bad = [(f, GST.show(GST.diff(reads[f], wants[f]))) for f in range(FRAMES)
           if GST.diff(reads[f], wants[f])]
    moved = len({(w["viewx"], w["viewy"]) for w in wants}) > 1
    print("state equal on every frame: %s; the oracle's view moved: %s"
          % ("yes" if not bad else bad, moved))
    ctl = [dict(w) for w in wants]
    ctl[5]["viewx"] += 1
    cbad = [f for f in range(FRAMES) if GST.diff(reads[f], ctl[f])]
    print("control (frame 5's view one unit off): flagged frames %s -- %s"
          % (cbad, "caught exactly there" if cbad == [5] else "!! NOT caught right"))
    ok = not bad and moved and cbad == [5] and len(got) == FRAMES
    print("GATESTATE CHECK: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
