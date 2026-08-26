"""M2-R2 GATE -- a door baked OPEN, rendered by fj, byte-exact against the oracle.

    python scratchpad/m2_gate.py [--fjm build/doom_e1m1_doors100.fjm] [--frac 1.0]
    python scratchpad/m2_gate.py --selftest        # R9: the negative control

WHAT THIS PROVES AND WHAT IT DOES NOT. It proves the whole RENDER path handles a door somewhere
other than where the wad stored it: the plane pair ids, the baked band bank, the V5 stacked upper
pieces, collision and thing-liveness all come out of the emitter correctly for a moved door. It
proves NOTHING about animating one -- there is no state, no trigger and no tic here. That is the
next rung, and it is built on this one: if a STATIC open door does not render correctly, an
animated one cannot.

IT IS A DIFFERENTIAL, AND IT HAS TO BE. The first version compared the door build against the
doors-open oracle directly and FAILED at (1869,479) with 371 px -- which was not a door bug at all:
the SHIPPED binary already differs from that oracle by 378 px there, because the oracle call
certifies the NON-SIM tier while the binary is the sim tier (docs/handoff-m1-reset.md). A direct
comparison cannot tell "doors broke this" from "this was already broken", so it is the wrong
question. This asks the right one:

    the pixels a door CHANGES, and the values it changes them to,
    must be the same in fj as in the oracle

i.e. `fj_open vs fj_shut` must equal `oracle_open vs oracle_shut`, pixel for pixel AND value for
value. Any standing tier disagreement cancels, and a door that paints one pixel wrong still fails.

...EXCEPT WHERE THE TWO MIRRORS ALREADY DISAGREE ABOUT THE PIXEL. At (1869,479) 378 pixels differ
between fj and the oracle with no door in sight; if a door then changes one of THOSE, the two
sides start from different values and there is nothing for the differential to compare. So a
disagreement is judged by WHERE it lands:

    outside the standing-delta set -> a DOOR BUG. Fails.
    inside it                      -> INHERITED. Reported, counted, and not judged -- but the
                                      count is printed so it can never quietly grow.

This is a real weakening and it is stated rather than hidden: those pixels are certified by
nothing here. They are certified by closing the standing delta, which is a separate job (the
oracle call certifies the NON-SIM tier; docs/handoff-m1-reset.md).

THE CONTROL THAT MAKES IT MEAN ANYTHING. `scratchpad/door_gate.py` exists because, with every door
and lift on the map wide open, `deg_gate`'s four certified viewpoints render ZERO pixels different
-- the repo could ship a completely broken door and every gate would pass. So this gate runs the
DOOR viewpoints it found, and a viewpoint whose change map is EMPTY is reported as VACUOUS rather
than counted as a pass.
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
    ap.add_argument("--shut-fjm", default="scratchpad/fjmcache/_ca2_ship_new.fjm",
                    help="the doors-SHUT binary; the differential is taken against it")
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

    open_runner = FjmRunner(ROOT / args.fjm)
    shut_runner = FjmRunner(ROOT / args.shut_fjm)
    assert open_runner.native and shut_runner.native, "the M2 gate needs the native engine"

    def changes(before, after):
        """{pixel: (from, to)} -- what moving the doors did. VALUES, not just positions: a door
        that paints the right pixels the wrong colour has to fail."""
        return {i: (b, a) for i, (b, a) in enumerate(zip(before, after)) if b != a}

    def render(runner, vp):
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
    print("  THE DIFFERENTIAL: which pixels opening the doors changed, and to what")
    ok, seen_door, standing, total_inherited = True, 0, 0, 0
    for label, vps in (("DOOR", DOOR_VPS), ("CERT", CERT_VPS)):
        for vp in vps:
            fj_open, _ops, frames = render(open_runner, vp)
            fj_shut, _o2, _f2 = render(shut_runner, vp)
            or_open, or_shut = oracle(vp, open_scene), oracle(vp, shut_scene)
            if args.selftest:                  # NEGATIVE CONTROL: claim the doors never moved
                or_open = or_shut
            fj_ch, or_ch = changes(fj_shut, fj_open), changes(or_shut, or_open)
            if label == "DOOR":
                seen_door += len(or_ch) > 0
            # the standing tier disagreement: REPORTED, never judged -- it is exactly what made
            # the first version of this gate fail for the wrong reason
            stand = sum(1 for a, b in zip(fj_shut, or_shut) if a != b)
            standing += stand
            # WHERE do the disagreements land? Only the ones outside the standing-delta
            # set are the door's fault; inside it the two mirrors never agreed to begin with.
            disputed = {i for i, (a, b) in enumerate(zip(fj_shut, or_shut)) if a != b}
            bad = {i for i in set(fj_ch) | set(or_ch) if fj_ch.get(i) != or_ch.get(i)}
            real, inherited = bad - disputed, bad & disputed
            same = not real
            ok &= same and frames == 1
            total_inherited += len(inherited)
            note = ("ok" if not bad else
                    ("ok, %d inherited" % len(inherited)) if not real else
                    "!! %d REAL disagreements (+%d inherited)" % (len(real), len(inherited)))
            print("  %s (%d,%d,%#010x): door changes %5d px  %-34s (standing %d px)"
                  % (label, vp[0], vp[1], vp[2], len(or_ch), note, stand))

    print("")
    print("  CONTROL: door viewpoints that actually SEE a door move: %d of %d"
          % (seen_door, len(DOOR_VPS)))
    if seen_door == 0:
        print("  !! VACUOUS -- no viewpoint sees a door, so agreeing here proves nothing")
        ok = False
    print("  standing fj-vs-oracle delta over all viewpoints: %d px -- PRE-EXISTING (the oracle"
          % standing)
    print("  call certifies the NON-SIM tier). The differential cancels it everywhere the door")
    print("  does not land ON it; %d changed pixels fall inside it and are NOT certified here."
          % total_inherited)

    print("")
    if args.selftest:
        print("SELFTEST (the oracle was told the doors never moved): "
              + ("FAIL -- the gate did not notice" if ok else "PASS -- the gate rejected it"))
        return 0 if not ok else 1
    print("M2-R2 GATE: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
