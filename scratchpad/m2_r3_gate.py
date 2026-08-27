"""M2-R3 GATE -- ONE binary, thirteen doors, every position, byte-exact against the oracle.

R2's gate compared two binaries: doors baked shut against doors baked open. This gates the thing
that replaced them -- a single image holding every door's every state, with a nibble per door
choosing which. So the gate WRITES the nibbles and re-renders, which is precisely what R4's state
machine will do at runtime and what nothing before this could do at all.

    python scratchpad/m2_r3_gate.py [--fjm build/doom_e1m1_doors_rt.fjm]
    python scratchpad/m2_r3_gate.py --selftest        # R9: the negative control

WHY IT IS STILL A DIFFERENTIAL. The shipped binary already differs from the oracle by 378 px at
(1869,479) with no door in sight -- the oracle call certifies the NON-SIM tier while the binary is
the sim tier. A direct compare cannot separate "the door is wrong" from "this was already wrong",
so the question asked here is the same one R2 asked:

    the pixels a state change MOVES, and the values it moves them to,
    must be the same in fj as in the oracle

Both sides are now taken from the SAME binary at two different `dstate` vectors, so the standing
delta cancels exactly and no second build is involved.

THREE CONTROLS, because a gate on a runtime door has three distinct ways to pass vacuously:

  C1  STATE 0 IS THE STORED MAP. With every nibble zero the runtime binary must render what the
      doors-less binary renders -- fj against fj, byte for byte, no oracle involved. If it does
      not, the per-state machinery is not free and every later comparison is measuring two things.
  C2  THE NIBBLE MUST ACTUALLY MOVE SOMETHING. A state vector whose change map is EMPTY at every
      viewpoint proves nothing at all -- it is indistinguishable from a poke that landed on the
      wrong address, which is the single most likely way to build a gate that always passes.
      Reported per state, and a state that moves nothing anywhere FAILS.
  C3  THE ORACLE MUST BE READING THE SAME STATE. `--selftest` compares fj at state k against the
      oracle at state 0. The gate must reject it.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj import selfreset                                              # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.doors import (door_states, heights_for_states,               # noqa: E402
                          use_boxes_xy)
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.harness import W                                              # noqa: E402
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

# the three viewpoints door_gate.py found by searching for ones that SEE a door move, then
# deg_gate's four certified ones as the no-regression half
DOOR_VPS = [(461, 2015, 0x40000000), (845, 1631, 0xC0000000), (461, 863, 0x40000000)]
CERT_VPS = [(664, 291, 0x18000000), (1272, -724, 0x40000000),
            (1869, 479, 0x80000000), (-416, 256, 0x0)]

# the eight cardinal/diagonal directions the door-viewpoint search steps back along
COS = [1.0, 0.7071, 0.0, -0.7071, -1.0, -0.7071, 0.0, 0.7071]
SIN = [0.0, 0.7071, 1.0, 0.7071, 0.0, -0.7071, -1.0, -0.7071]

VAL_SHIFT = W.bit_length()      # a hex nibble's value lives in its ODD word, shifted by this
                                # (MEASURED, scratchpad/_m2_pokeprobe.py: hex.vec 4, 0x3B7F ->
                                # words [_,960,_,448,_,704,_,192] = [0xF,7,0xB,3] << 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_doors_rt.fjm")
    ap.add_argument("--gen", default="build/generated_doors_rt")
    ap.add_argument("--base-fjm", default="scratchpad/fjmcache/_ca2_ship_new.fjm",
                    help="C1: the doors-less binary state 0 must match, fj against fj")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default="assets/freedoom1.wad")
    ap.add_argument("--selftest", action="store_true",
                    help="R9/C3: judge every state against the STATE 0 oracle; must FAIL")
    args = ap.parse_args()

    mw = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.asset))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(mw, args.map)
    secs, lds, sds = mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map)
    tbl = door_states(secs, lds, sds)
    order = sorted(tbl)                      # the emitter's own slot order (doors.door_states)
    boxes = use_boxes_xy(secs, lds, sds, cmap.vertexes)

    # ---- the state vectors under test ---------------------------------------------------------
    # Named, because "state 4" means a different height for every door and a gate log that says
    # only "state 4" cannot be read a month later.
    VECTORS = [
        ("all doors OPEN", {si: len(tbl[si]) - 1 for si in order}),
        ("all doors at the walk-through threshold", {si: 4 for si in order}),
        ("all doors one step ajar", {si: 1 for si in order}),
        # one door at a time: a per-door poke that lands on the wrong nibble still moves SOMETHING
        # when every door moves together, and would pass the whole-map vectors above.
        *[("only door sector %d OPEN" % si, {si: len(tbl[si]) - 1}) for si in order],
    ]

    drawable = [t for t in mw.things(args.map) if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    runtime = [t for t, b in zip(drawable, baked) if not b]
    blob_tail = (encode_things([(t.x << 16, t.y << 16) for t in runtime])
                 + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in runtime])
                 + encode_visibility([1] * nvis))

    runner = FjmRunner(ROOT / args.fjm)
    assert runner.native, "the M2 gate needs the native engine"
    # ⚠ capture_labels RE-ASSEMBLES, so it needs the SAME path list build.py used -- consts, the
    # src/fj includes in order, then the generated parts in order. Handing it the generated files
    # alone fails on the first macro they call, and handing it the files in the wrong order would
    # be worse: it would assemble and every address would be a lie.
    from doomfj.build import (_LINES_INCLUDES, _RENDERER_INCLUDES, _SIM_INCLUDES,  # noqa: E402
                              _SRC_FJ)
    gen_dir = ROOT / args.gen
    prog = [gen_dir / f"{args.map.lower()}_{n:02d}_{tag}.fj" for n, tag in
            enumerate(["entry", "tables", "main", "segconsts", "walk", "state", "banks"])]
    missing = [p_ for p_ in prog if not p_.exists()]
    assert not missing, f"generated parts missing: {missing}"
    consts = Config().emit_fj_consts(gen_dir / "fj_consts.fj")
    incs = [ROOT / _SRC_FJ / f for f in
            (_RENDERER_INCLUDES + _LINES_INCLUDES + _SIM_INCLUDES)]
    # ...and CACHED, because that re-assembly is 11 minutes and the gate is going to be re-run for
    # reasons that have nothing to do with the label map. Keyed on the .fjm's mtime, so a rebuilt
    # binary invalidates it rather than silently poking last build's address -- which would land in
    # the middle of the band bank and produce a picture nobody could explain.
    cache = ROOT / "scratchpad/_m2_rt_labels.json"
    stamp = (ROOT / args.fjm).stat().st_mtime_ns
    labels = None
    if cache.exists():
        doc = json.loads(cache.read_text(encoding="utf-8"))
        if doc.get("fjm") == str(args.fjm) and doc.get("mtime_ns") == stamp:
            labels = doc["labels"]
            print("labels: cached (%d)" % len(labels), flush=True)
    if labels is None:
        print("labels: re-assembling to capture them (~11 min) ...", flush=True)
        # ⚠ NOT to `args.fjm`. capture_labels ASSEMBLES, and assembling writes its output: aimed at
        # the built binary it rewrites the very file the gate is about to run, changes its mtime
        # (invalidating this cache on every run) and leaves a truncated image if it is interrupted.
        tmp_out = ROOT / "build" / "_m2_labels_scratch.fjm"
        labels = selfreset.capture_labels([consts] + incs + prog, tmp_out)
        # C0: and that re-assembly must reproduce the binary the gate is about to RUN, byte for
        # byte. Otherwise the addresses come from one image and the pokes land in another -- which
        # is not a hypothetical: the first version of this wrote its re-assembly straight over
        # `args.fjm`, and a poke through a stale label lands in the middle of the band bank.
        same = tmp_out.read_bytes() == (ROOT / args.fjm).read_bytes()
        print("labels: re-assembly reproduces the binary byte for byte: %s"
              % ("yes" if same else "NO"), flush=True)
        assert same, ("the label capture's .fjm differs from %s -- the two are different programs "
                      "and every address below would be wrong" % args.fjm)
        cache.write_text(json.dumps({"fjm": str(args.fjm), "mtime_ns": stamp,
                                     "labels": {k: int(v) for k, v in labels.items()}}),
                         encoding="utf-8")
    assert "dstate" in labels, (
        "no `dstate` label in the built image -- the gate would poke nothing and pass on a picture "
        "it never moved (that is C2's whole point). Build with doors=True.")
    dbase = labels["dstate"] // W
    print("fjm   : %s" % args.fjm)
    print("dstate: word %d, %d doors in sorted-sector order %s" % (dbase, len(order), order))

    def render(vp, states):
        """One frame at one door state vector. The image is rebuilt per render (the program
        self-modifies), so the poke cannot leak from one state into the next."""
        vx, vy, va = vp
        core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
        for seg, n in runner._segments:
            core.add_segment(seg, n)
        for start, vals in runner._runs:
            core.set_words(start, vals)
        for slot, si in enumerate(order):
            k = states.get(si, 0)
            assert 0 <= k < len(tbl[si]), (si, k)
            core.set_words(dbase + 2 * slot + 1, [k << VAL_SHIFT])
        scr = StreamScreen(stdin=encode_feed(vx << 16, vy << 16, va, 0) + blob_tail,
                           n_things=len(runtime))
        scr.attach_memory(NativeDeviceMemory(core, runner.width))
        _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
        out = (bytes(scr.pixel_indices), ops)
        del core, scr
        return out

    base_runner = [None]        # ⚠ HOISTED. Constructing FjmRunner re-reads and decompresses a
                                # 31 MB .fjm; doing it per render made C1 alone a 35-minute job
                                # and the wall clock read as if the renders were slow.

    def render_base(vp):
        vx, vy, va = vp
        if base_runner[0] is None:
            base_runner[0] = FjmRunner(ROOT / args.base_fjm)
        r = base_runner[0]
        core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
        for seg, n in r._segments:
            core.add_segment(seg, n)
        for start, vals in r._runs:
            core.set_words(start, vals)
        scr = StreamScreen(stdin=encode_feed(vx << 16, vy << 16, va, 0) + blob_tail,
                           n_things=len(runtime))
        scr.attach_memory(NativeDeviceMemory(core, r.width))
        core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
        out = bytes(scr.pixel_indices)
        del core, scr
        return out

    def oracle(vp, states):
        vx, vy, va = vp
        hv = heights_for_states(secs, lds, sds, states)
        scene = build_scene(mw, mw, args.map, hv)
        return bytes(rm.render_wall_frame(
            SimState(vx << 16, vy << 16, va, args.map), scene,
            wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
            near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True))

    def changes(before, after):
        return {i: (b, a) for i, (b, a) in enumerate(zip(before, after)) if b != a}

    vps = DOOR_VPS + CERT_VPS
    ok = True

    # ---- C1: state 0 is the stored map, fj against fj -------------------------------------------
    print("")
    print("  C1  state 0 vs the doors-less binary (fj vs fj, no oracle)")
    zero = {}
    base_px = {}
    for vp in vps:
        a = render_base(vp)
        b, _ops = render(vp, zero)
        base_px[vp] = b
        same = a == b
        ok &= same
        print("      (%5d,%5d,0x%08x)  %s" % (*vp, "identical" if same else
                                              "!! %d px DIFFER with every door shut"
                                              % len(changes(a, b))))

    # ---- the STANDING delta, so the differential can be judged -----------------------------------
    # The binary already differs from the oracle where no door is involved: the oracle call
    # certifies the NON-SIM tier while this binary is the sim tier. Those pixels start from
    # different values on the two sides, so a door landing on one has nothing to compare -- they
    # are reported and NOT judged, exactly as R2's gate does. Do not read a PASS as covering them.
    zero_or = {vp: oracle(vp, {}) for vp in vps}
    disputed = {vp: set(changes(base_px[vp], zero_or[vp])) for vp in vps}
    print("")
    print("  standing fj-vs-oracle delta with every door shut: %d px total (%s)"
          % (sum(len(v) for v in disputed.values()),
             ", ".join("%d@(%d,%d)" % (len(disputed[vp]), vp[0], vp[1])
                       for vp in vps if disputed[vp]) or "none"))

    # ---- a viewpoint that SEES each door ----------------------------------------------------------
    # "only door 10 open moves 0 px" is not a pass and not a failure -- it means no gate viewpoint
    # can see that door, so the single-door control was vacuous for it. The oracle renders in 0.03 s,
    # so the honest fix is to go and find a viewpoint per door rather than to drop the control.
    print("")
    print("  finding a viewpoint that SEES each door (oracle search) ...", flush=True)
    door_vp = {}
    for si in order:
        x0, y0, x1, y1 = boxes[si]
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        best = None
        for dist in (80, 160, 240):
            for a in range(8):
                ang = a * (1 << 29)
                px_ = cx - int(dist * COS[a])
                py_ = cy - int(dist * SIN[a])
                shut_px = oracle((px_, py_, ang), {})
                open_px = oracle((px_, py_, ang), {si: len(tbl[si]) - 1})
                n = len(changes(shut_px, open_px))
                if best is None or n > best[0]:
                    best = (n, (px_, py_, ang))
        door_vp[si] = best
        print("      sector %3d: %5d px change at (%6d,%6d,0x%08x)"
              % (si, best[0], *best[1]), flush=True)

    # ---- the differential, per state vector ------------------------------------------------------
    print("")
    print("  THE DIFFERENTIAL: what each state vector moves, in fj and in the oracle")
    for name, states in VECTORS:
        moved_any, real_bad, inherited = 0, 0, 0
        # A single-door vector is judged at the viewpoint found above for THAT door: the fixed
        # seven cannot see most of them, and a control that cannot fail is not a control.
        here = [door_vp[list(states)[0]][1]] if len(states) == 1 else vps
        for vp in here:
            fj_px, _ops = render(vp, states)
            or_px = oracle(vp, {} if args.selftest else states)
            base_fj = base_px.get(vp) or render(vp, {})[0]
            base_or = zero_or.get(vp) or oracle(vp, {})
            dsp = disputed.get(vp) or set(changes(base_fj, base_or))
            dfj = changes(base_fj, fj_px)
            dor = changes(base_or, or_px)
            moved_any += len(dfj)
            bad = {i for i in set(dfj) | set(dor) if dfj.get(i) != dor.get(i)}
            real_bad += len(bad - dsp)
            inherited += len(bad & dsp)
        good = (real_bad == 0)
        ok &= good and moved_any > 0
        print("      %-44s moves %6d px  %s"
              % (name, moved_any,
                 ("ok" + (", %d inherited" % inherited if inherited else ""))
                 if good and moved_any else
                 ("!! VACUOUS -- nothing moved" if not moved_any else
                  "!! %d REAL disagreements (+%d inherited)" % (real_bad, inherited))))

    print("")
    if args.selftest:
        print("SELFTEST (every state judged against the STATE 0 oracle): %s"
              % ("PASS -- the gate rejected it" if not ok else
                 "!! FAIL -- the gate accepted a picture the oracle never rendered"))
        sys.exit(0 if not ok else 1)
    # ⚠ SAY WHAT WAS NOT JUDGED (CR PR#78, R9): an unqualified "byte-exact" would overstate a
    # verdict that excludes the standing non-sim-tier delta.
    print("M2-R3 GATE: %s" % ("PASS -- one binary, every door state, byte-exact on every JUDGED "
                              "pixel (pixels inside the standing non-sim-tier delta are reported "
                              "as `inherited` and NOT judged)" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
