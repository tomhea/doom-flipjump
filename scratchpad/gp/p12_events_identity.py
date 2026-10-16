"""A recorded key-event list (e.g. the gameplay video's, docs/media/p12/doom_e1m1_gameplay.events.json: the bot that
reads the binary live) replayed into TWO binaries through m2_std_gate.run_fj (the composition `fj --run ... --io pc`
builds): every presented frame's pixels and palette must be identical (a class S rung), and the ops are compared.
PYTHONPATH="src;scratchpad;scratchpad/12m;scratchpad/gp" python scratchpad/gp/p12_events_identity.py EVENTS.json A.fjm B.fjm
    [--frames 1750]"""
import argparse
import json
import sys

sys.path[:0] = ["scratchpad", "scratchpad/12m", "scratchpad/gp", "src"]
import m2_std_gate as gate  # noqa: E402
from flipjump.interpreter.io_devices.KeyboardIO import KeyEvent  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--frames", type=int, default=1750)
    args = ap.parse_args()
    evs = [KeyEvent(t, d, c) for t, d, c in json.load(open(args.events))]
    n = gate.MENU_FRAMES + args.frames
    out = []
    for fjm in (args.a, args.b):
        rec = {}

        def fac():
            rec["s"] = gate.Recording()
            return rec["s"]
        fr, ops = gate.run_fj(fjm, evs, n, screen_factory=fac)
        out.append((fr, rec["s"].palettes, ops))
        print("%s: %d frames, %s ops" % (fjm, len(fr), format(ops, ",")), flush=True)
    (a, pa, oa), (b, pb, ob) = out
    diff = [k for k in range(min(len(a), len(b))) if a[k] != b[k] or pa[k] != pb[k]]
    same = not diff and len(a) == len(b) == n
    print("%d frames: %s; ops %+.2f%%" % (len(a), "EVERY FRAME IDENTICAL (pixels + palette)" if same
                                          else "DIFFER at %s" % diff[:3], 100.0 * (ob - oa) / oa))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
