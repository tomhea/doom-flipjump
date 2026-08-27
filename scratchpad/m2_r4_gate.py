"""M2-R4 GATE -- a door the PLAYER opens, over many frames, byte-exact every frame.

R3 proved the renderer can draw a door at any state when something writes the nibble. This proves
the program writes it ITSELF: a scripted run presses use near a door and the door opens, waits,
closes, and the player walks through the opening -- with the oracle stepping the SAME state machine
from the same keys and the two frames compared byte for byte.

    python scratchpad/m2_r4_gate.py
    python scratchpad/m2_r4_gate.py --selftest       # R9: the oracle never presses use

WHY THE HARNESS RELAYS THE DOOR CELLS. This is the HOSTED tier, which has no self-reset: every
frame is a fresh image, so nothing in it survives on its own -- that is why the player's own
position round-trips through the wire. The door's cells are world state in exactly the same sense,
so the gate reads them out after each frame and writes them back before the next, which is the
hosted tier's whole contract. (The STANDALONE tier keeps them across the M1 reset instead, which is
what `build.STANDALONE_PERSIST` is for -- a different rung.)

⚠ `lnrow`'s patched blocking bits are relayed too, and they are the reason collision works: the
program clears them with a `wflip` when a door reaches `doors.pass_state`. Reading them back also
CHECKS them -- the gate asserts the bit the program flipped is the bit the threshold says it
should have flipped, so "the door opened" and "the door became walkable" are two separate claims
with two separate pieces of evidence.

CONTROLS
  C1  the door must actually MOVE during the run (a script that never triggers is vacuous), and
      the player must actually CROSS the doorway (a run that never tests collision proves the
      render half only).
  C2  the blocking bits must be SET while the door is below `pass_state` and CLEAR above it, on
      every frame -- checked against `doors.pass_state`, not against what the program did.
  C3  --selftest steps the oracle's doors with the use key held OFF while fj gets the real script.
      Every frame after the door starts moving must then differ.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj import selfreset                                              # noqa: E402
from doomfj.collision import FLAGS_REST_BYTE, FLAG_BLOCKING, LINE_REST_LEN  # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.doorcode import WAIT_NIBBLES, door_line_ids                   # noqa: E402
from doomfj.doors import (door_states, door_tic, heights_for_states,      # noqa: E402
                          in_use_box_fixed, initial_states, pass_state, use_boxes_xy)
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel, SimState, build_scene, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (KEY_USE, encode_bindings, encode_feed,     # noqa: E402
                               encode_things, encode_visibility, keys_dict, keys_byte)
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402
from tests.fj.stream_screen import StreamScreen                                # noqa: E402

VAL_SHIFT = W.bit_length()      # a hex nibble's value is its ODD word, shifted (see m2_r3_gate)


def _signed32(v: int) -> int:
    """the echoed wire value is SIGNED 16.16 (`decode_state`), so the oracle's masked x/y have to
    be read the same way before they are compared"""
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_doors_rt.fjm")
    ap.add_argument("--gen", default="build/generated_doors_rt")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default="assets/freedoom1.wad")
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    mw = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.asset))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(mw, args.map)
    secs, lds, sds = mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map)
    tbl = door_states(secs, lds, sds)
    order = sorted(tbl)
    boxes = use_boxes_xy(secs, lds, sds, cmap.vertexes)
    lines_of = door_line_ids(secs, lds, sds, tbl)
    passes = {si: pass_state(secs, lds, sds, si) for si in order}
    nstates = {si: len(v) for si, v in tbl.items()}
    open_h = {si: (secs[si].floor_h, tbl[si][-1]) for si in order}

    # ---- labels -----------------------------------------------------------------------------
    from doomfj.build import (_LINES_INCLUDES, _RENDERER_INCLUDES, _SIM_INCLUDES, _SRC_FJ)
    gen_dir = ROOT / args.gen
    prog = [gen_dir / f"{args.map.lower()}_{n:02d}_{tag}.fj" for n, tag in
            enumerate(["entry", "tables", "main", "segconsts", "walk", "state", "banks"])]
    consts = Config().emit_fj_consts(gen_dir / "fj_consts.fj")
    incs = [ROOT / _SRC_FJ / f for f in (_RENDERER_INCLUDES + _LINES_INCLUDES + _SIM_INCLUDES)]
    cache = ROOT / "scratchpad/_m2_r4_labels.json"
    stamp = (ROOT / args.fjm).stat().st_mtime_ns
    labels = None
    if cache.exists():
        doc = json.loads(cache.read_text(encoding="utf-8"))
        if doc.get("mtime_ns") == stamp:
            labels = doc["labels"]
            print("labels: cached (%d)" % len(labels), flush=True)
    if labels is None:
        print("labels: re-assembling to capture them (~11 min) ...", flush=True)
        tmp_out = ROOT / "build" / "_m2_labels_scratch.fjm"
        labels = selfreset.capture_labels([consts] + incs + prog, tmp_out)
        assert tmp_out.read_bytes() == (ROOT / args.fjm).read_bytes(), (
            "the label capture's .fjm differs from the binary under test")
        cache.write_text(json.dumps({"mtime_ns": stamp,
                                     "labels": {k: int(v) for k, v in labels.items()}}),
                         encoding="utf-8")
    for name in ("dstate", "ddir", "dsub", "dwait", "lnrow"):
        assert name in labels, f"no `{name}` label -- this binary is not a doors build"
    base = {n: labels[n] // W for n in ("dstate", "ddir", "dsub", "dwait", "lnrow")}

    # every word the gate relays between frames: the four door registers, and the flag BYTE of
    # each door line (an op, so its value is in the odd word)
    def door_words():
        out = []
        for d in range(len(order)):
            out += [base["dstate"] + 2 * d + 1, base["ddir"] + 2 * d + 1, base["dsub"] + 2 * d + 1]
            out += [base["dwait"] + 2 * (WAIT_NIBBLES * d + k) + 1 for k in range(WAIT_NIBBLES)]
        for si in order:
            for li in lines_of.get(si, ()):
                out.append(base["lnrow"] + 2 * (li * LINE_REST_LEN + FLAGS_REST_BYTE) + 1)
        return out

    WORDS = door_words()

    # ---- the world blob (things never move in this script) -------------------------------------
    drawable = [t for t in mw.things(args.map) if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    runtime = [t for t, b in zip(drawable, baked) if not b]
    blob_tail = (encode_things([(t.x << 16, t.y << 16) for t in runtime])
                 + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in runtime])
                 + encode_visibility([1] * nvis))

    runner = FjmRunner(ROOT / args.fjm)
    assert runner.native, "this gate needs the native engine"

    def run_frame(state, keys, carry):
        """One frame: build the image, restore the relayed door words, feed the state, run."""
        core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
        for seg, n in runner._segments:
            core.add_segment(seg, n)
        for start, vals in runner._runs:
            core.set_words(start, vals)
        for w, v in zip(WORDS, carry):
            core.set_words(w, [v])
        scr = StreamScreen(stdin=encode_feed(state.x, state.y, state.angle, keys) + blob_tail,
                           n_things=len(runtime))
        scr.attach_memory(NativeDeviceMemory(core, runner.width))
        _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
        px = bytes(scr.pixel_indices)
        out_state = scr.state           # the echoed (x, y, angle)
        new_carry = [core.get_word(w) for w in WORDS]
        del core, scr
        return px, out_state, new_carry, ops

    # ---- the script -------------------------------------------------------------------------
    # Start in front of door sector 10 (the one the R3 search found a clean view of), walk at it,
    # press use, let it open, walk through, and stand while it shuts again.
    tgt = order[0]
    x0, y0, x1, y1 = boxes[tgt]
    start = SimState(((x0 + x1) // 2) << 16, (y0 - 40) << 16, 0x40000000, args.map)
    # ⚠ WALK INTO THE BOX BEFORE PRESSING. The first version pressed use on frame 0, from 40 units
    # OUTSIDE the trigger box, and both mirrors agreed the door stayed shut -- 10 byte-exact frames
    # of nothing happening. That is what the vacuity control is for, and it is why the control
    # counts DISTINCT STATES rather than "did the frames match".
    SCRIPT = ([{"forward": True}] * 2 + [{"use": True}] * 3 + [{}] * 10
              + [{"forward": True}] * 10 + [{}] * 15)[:args.frames]

    print("fjm    : %s" % args.fjm)
    print("doors  : %d, thresholds %s" % (len(order), {si: passes[si] for si in order[:3]}))
    print("start  : (%d,%d) angle 0x%08x, %d frames"
          % (start.x >> 16, start.y >> 16, start.angle, len(SCRIPT)))
    print("relayed: %d words (%d door registers + %d line flag bytes)"
          % (len(WORDS), 5 * len(order), sum(len(v) for v in lines_of.values())))

    # ---- run both mirrors -----------------------------------------------------------------------
    dstates = initial_states(secs, lds, sds)
    state = start
    carry = [0] * len(WORDS)
    # the image's own initial values for the relayed words (state 0 + the baked blocking bits)
    _core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        _core.add_segment(seg, n)
    for st_, vals in runner._runs:
        _core.set_words(st_, vals)
    carry = [_core.get_word(w) for w in WORDS]
    del _core

    ok, moved, ops_total = True, 0, 0
    ys = []
    near_y, far_y = y0 + 64, y1 - 64          # the door's own lines, before the box inflation
    seen_states = set()
    print("")
    print("  frame  keys      door0 state  fj px vs oracle        blocking")
    for f, keys in enumerate(SCRIPT):
        kb = keys_byte(keys)
        px, echoed, carry, ops = run_frame(state, kb, carry)
        ops_total += ops

        # the oracle: doors first, then the player -- the emitted order
        kd = keys_dict(kb)
        used = bool(kd.get("use")) and not args.selftest
        nxt = {}
        for si in order:
            nxt[si] = door_tic(dstates[si], nstates[si],
                               used and in_use_box_fixed(boxes[si], state.x, state.y))
        dstates = nxt
        blocked = frozenset(li for si in order if dstates[si][0] < passes[si]
                            for li in lines_of.get(si, ()))
        # collision sees the door sectors OPEN and the not-yet-open doors as walls -- the same two
        # facts the emitted program bakes and patches
        csc = build_scene(mw, mw, args.map, open_h, blocked)
        state = rm.step_sim(state, kd, scene=csc)
        want_state = (_signed32(state.x), _signed32(state.y), state.angle)
        rsc = build_scene(mw, mw, args.map,
                          heights_for_states(secs, lds, sds, {si: dstates[si][0] for si in order}))
        want = bytes(rm.render_wall_frame(state, rsc, wall_mode="W1R", floor_mode_ft1=True,
                                          plane_near=True, wall_noise=True, near_steps=True,
                                          stack_steps=True, things=True, sprite_wad=art,
                                          degrade=True))
        # C1c: fj's OWN collision answer, not just its picture. The gate feeds the oracle's
        # position in each frame, so without this the fj side's blocking bits could be wrong in
        # both directions and every frame would still be byte-exact -- it would be rendering the
        # oracle's walk. The program echoes the state it computed; it must be the same state.
        same = px == want
        ok &= same
        pos_ok = (echoed is None) or (tuple(echoed) == want_state)
        ok &= pos_ok
        d0 = dstates[tgt][0]
        seen_states.add(d0)
        moved += 1 if d0 else 0
        # C2: the bits the program holds must be the ones the threshold says
        want_blocked = {li: (dstates[si][0] < passes[si])
                        for si in order for li in lines_of.get(si, ())}
        got_blocked = {}
        for i, si in enumerate(order):
            pass
        bidx = 5 * len(order)
        for si in order:
            for li in lines_of.get(si, ()):
                v = carry[bidx] >> VAL_SHIFT
                got_blocked[li] = bool(v & FLAG_BLOCKING)
                bidx += 1
        bits_ok = got_blocked == want_blocked
        ok &= bits_ok
        # C1b: did the player actually get THROUGH the doorway? The first version asked whether
        # they had moved more than 48 units from the start, which is true from frame 0 and counted
        # 40 of 40 -- a control that cannot fail. The door's own lines run between these two y
        # values, so passing from below the near one to above the far one is the real crossing.
        if echoed is not None:
            ys.append(echoed[1] >> 16)
        print("  %5d  %-8s  %6d      %-22s %s"
              % (f, "".join(k[0] for k in sorted(keys)) or "-", d0,
                 ("BYTE-EXACT" if same else
                  "!! %d px differ" % sum(a != b for a, b in zip(px, want))),
                 ("ok" if (bits_ok and pos_ok) else
                  ("!! wrong blocking bits" if not bits_ok else
                   "!! fj walked elsewhere: %s vs %s" % (echoed, want_state)))), flush=True)

    print("")
    crossed = bool(ys) and min(ys) < near_y and max(ys) > far_y
    print("  CONTROL: door 0 reached %d distinct states (%s); frames past shut: %d"
          % (len(seen_states), sorted(seen_states), moved))
    print("  CONTROL: the player walked THROUGH the doorway (y %d -> %d across the door's lines "
          "at %d..%d): %s" % (min(ys or [0]), max(ys or [0]), near_y, far_y,
                              "yes" if crossed else "NO -- collision was never tested"))
    vac = (len(seen_states) < 3) or moved == 0 or not crossed
    if vac:
        print("  !! VACUOUS -- the door never really moved, so this proves the render half only")
    print("  %s ops over %d frames" % (format(ops_total, ","), len(SCRIPT)))
    print("")
    if args.selftest:
        print("SELFTEST (the oracle never presses use): %s"
              % ("PASS -- the gate rejected it" if not ok else "!! FAIL -- it accepted"))
        sys.exit(0 if not ok else 1)
    print("M2-R4 GATE: %s" % ("PASS -- the program opens its own doors, byte-exact every frame"
                              if (ok and not vac) else "FAIL"))
    sys.exit(0 if (ok and not vac) else 1)


if __name__ == "__main__":
    main()
