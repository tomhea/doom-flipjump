"""M2-R2 GATE -- a door baked OPEN, rendered by fj, byte-exact against the oracle.

    python scratchpad/m2_gate.py [--fjm build/doom_e1m1_doors100.fjm] [--frac 1.0]
    python scratchpad/m2_gate.py --selftest        # R9: the negative control

WHAT THIS PROVES AND WHAT IT DOES NOT. It proves the whole RENDER path handles a door somewhere
other than where the wad stored it: the plane pair ids, the baked band bank, the V5 stacked upper
pieces, collision and thing-liveness all come out of the emitter correctly for a moved door. It
proves NOTHING about animating one -- there is no state, no trigger and no tic here. That is the
next rung, and it is built on this one: if a STATIC open door does not render correctly, an
animated one cannot.

THE CONTROL THAT MAKES IT MEAN ANYTHING. `scratchpad/door_gate.py` exists because, with every door
and lift on the map wide open, `deg_gate`'s four certified viewpoints render ZERO pixels different
-- the repo could ship a completely broken door and every gate would pass. So this gate runs the
DOOR viewpoints it found, and for each one prints how far the doors-shut oracle is from the
doors-open one. A viewpoint that cannot see a door is reported as VACUOUS rather than counted.

The four certified viewpoints ride along as the no-regression half: they see little or nothing of a
door, and must still be byte-exact.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.doors import heights_at                                       # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel, SimState, build_scene)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402
from tests.fj.stream_screen import StreamScreen                                # noqa: E402

# the three viewpoints scratchpad/door_gate.py found by searching for ones that SEE a door move,
# then deg_gate's four certified ones as the no-regression half
DOOR_VPS = [(461, 2015, 0x40000000), (845, 1631, 0xC0000000), (461, 863, 0x40000000)]
CERT_VPS = [(664, 291, 0x18000000), (1272, -724, 0x40000000),
            (1869, 479, 0x80000000), (-416, 256, 0x0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_doors100.fjm")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default="assets/freedoom1.wad")
    ap.add_argument("--frac", type=float, default=1.0)
    ap.add_argument("--quant", type=int, default=16)
    ap.add_argument("--selftest", action="store_true",
                    help="R9: compare against the doors-SHUT oracle; the gate must FAIL")
    args = ap.parse_args()

    mw = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.asset))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(mw, args.map)
    secs, lds, sds = mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map)
    heights = heights_at(secs, lds, sds, args.frac, args.quant)

    open_scene = build_scene(mw, mw, args.map, heights)
    shut_scene = build_scene(mw, mw, args.map, None)
    render_kw = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                     near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)

    print("fjm  : %s" % args.fjm)
    print("doors: frac %.2f, quant %d -> %d sectors, ceilings %s"
          % (args.frac, args.quant, len(heights), sorted(c for _f, c in heights.values())))

    # the wire is unchanged by a door: thing positions/bindings/visibility are properties of the
    # things and the BSP, and the BSP does not move when a ceiling does (build_scene says so).
    drawable = [t for t in mw.things(args.map) if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    runtime = [t for t, b in zip(drawable, baked) if not b]
    blob_tail = (encode_things([(t.x << 16, t.y << 16) for t in runtime])
                 + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in runtime])
                 + encode_visibility([1] * nvis))

    runner = FjmRunner(ROOT / args.fjm)
    assert runner.native, "the M2 gate needs the native engine"

    def render(vp):
        vx, vy, va = vp
        core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
        for seg, n in runner._segments:
            core.add_segment(seg, n)
        for start, vals in runner._runs:
            core.set_words(start, vals)
        scr = StreamScreen(stdin=encode_feed(vx << 16, vy << 16, va, 0) + blob_tail,
                           n_things=len(runtime))
        scr.attach_memory(NativeDeviceMemory(core, runner.width))
        _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
        out = (bytes(scr.pixel_indices), ops, scr.frame_count)
        del core, scr
        return out

    def oracle(vp, scene):
        vx, vy, va = vp
        return bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, va, args.map),
                                          scene, **render_kw))

    print("")
    ok, seen_door = True, 0
    for label, vps in (("DOOR", DOOR_VPS), ("CERT", CERT_VPS)):
        for vp in vps:
            got, ops, frames = render(vp)
            want = oracle(vp, shut_scene if args.selftest else open_scene)
            moved = sum(1 for a, b in zip(oracle(vp, open_scene), oracle(vp, shut_scene))
                        if a != b)
            same = got == want
            ok &= same and frames == 1
            if label == "DOOR":
                seen_door += moved > 0
            diff = sum(1 for a, b in zip(got, want) if a != b)
            print("  %s (%d,%d,%#010x): %-24s  door moves %5d px here%s"
                  % (label, vp[0], vp[1], vp[2],
                     "BYTE-EXACT" if same else "!! %d px DIFFER" % diff, moved,
                     "" if moved or label == "CERT" else "   !! VACUOUS viewpoint"))

    print("")
    print("  CONTROL: door viewpoints that actually SEE a door move: %d of %d"
          % (seen_door, len(DOOR_VPS)))
    if seen_door == 0:
        print("  !! VACUOUS -- no viewpoint sees a door, so byte-exactness here proves nothing")
        ok = False

    print("")
    if args.selftest:
        print("SELFTEST (compared against the doors-SHUT oracle): "
              + ("FAIL -- the gate did not notice" if ok else "PASS -- the gate rejected it"))
        return 0 if not ok else 1
    print("M2-R2 GATE: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
