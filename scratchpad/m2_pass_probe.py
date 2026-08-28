"""M2-R4 -- CAN YOU WALK THROUGH THE DOOR? Asked once per state, of the program itself.

The R4 gate checks the blocking BIT against `doors.pass_state` on every frame, and door 0 visits
all nine states, so the bit is covered. What it does NOT check is the CONSEQUENCE: it only ever
walks the player through a fully-open door and (in its selftest) into a fully-shut one. States
1..3 must refuse and 4..8 must admit, and nothing had ever asked the binary either question.

So this walks the player INTO the door with the key held down, one frame at a time, while the door
opens under them:

    frame 0   press use, hold forward -- the door steps to state 1, the player shoves at it
    frame k   the door is at state k, and the player either moved or did not

and the answer per state is the y delta. The threshold is not an input here: the probe records
where the player first got through and compares it to `pass_state` afterwards.

    python scratchpad/m2_pass_probe.py

CONTROLS
  C1  the ORACLE runs the same script, and every frame must be byte-exact AND land the player on
      the same position -- otherwise "fj refused the move" might just be fj rendering a different
      world. (This is the control the gate was missing until fj's echoed state was compared.)
  C2  the door must actually pass through every state below the threshold with the player pressed
      against it. A run where the player is nowhere near the door would report "blocked" for every
      state and prove nothing, so the probe requires at least one BLOCKED state and one ADMITTED
      state, and prints the states it never observed.
  C3  --frozen holds the door SHUT for the whole run (no use key) and requires every state to
      refuse: the negative control for "the player just walks forward regardless".
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj import selfreset                                              # noqa: E402
from doomfj.collision import FLAGS_REST_BYTE, LINE_REST_LEN               # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.doorcode import WAIT_NIBBLES, door_line_ids                   # noqa: E402
from doomfj.doors import (door_states, door_tic, heights_for_states,      # noqa: E402
                          in_use_box_fixed, initial_states, pass_state, use_boxes_xy)
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel, SimState, build_scene)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility, keys_byte, keys_dict)
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402
from tests.fj.stream_screen import StreamScreen                                # noqa: E402

VAL_SHIFT = W.bit_length()


def _s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_doors_rt.fjm")
    ap.add_argument("--gen", default="build/generated_doors_rt")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default="assets/freedoom1.wad")
    ap.add_argument("--door", type=int, default=None, help="door SECTOR (default: the first)")
    ap.add_argument("--frames", type=int, default=14)
    ap.add_argument("--frozen", action="store_true",
                    help="C3: never press use -- every state must refuse")
    ap.add_argument("--wait", type=int, default=0,
                    help="hold use WITHOUT forward for N frames first, so the door is already "
                         "high when the player shoves at it -- the only way to observe the top "
                         "states, which a player pressed against the door walks past too early")
    args = ap.parse_args()

    mw = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.asset))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(mw, args.map)
    secs, lds, sds = mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map)
    tbl = door_states(secs, lds, sds)
    order = sorted(tbl)
    tgt = args.door if args.door is not None else order[0]
    boxes = use_boxes_xy(secs, lds, sds, cmap.vertexes)
    lines_of = door_line_ids(secs, lds, sds, tbl)
    passes = {si: pass_state(secs, lds, sds, si) for si in order}
    nstates = {si: len(v) for si, v in tbl.items()}
    open_h = {si: (secs[si].floor_h, tbl[si][-1]) for si in order}

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
    if labels is None:
        print("labels: re-assembling (~11 min) ...", flush=True)
        tmp_out = ROOT / "build" / "_m2_labels_scratch.fjm"
        labels = selfreset.capture_labels([consts] + incs + prog, tmp_out)
        assert tmp_out.read_bytes() == (ROOT / args.fjm).read_bytes()
        cache.write_text(json.dumps({"mtime_ns": stamp,
                                     "labels": {k: int(v) for k, v in labels.items()}}),
                         encoding="utf-8")
    base = {n: labels[n] // W for n in ("dstate", "ddir", "dsub", "dwait", "lnrow")}

    WORDS = []
    for d in range(len(order)):
        WORDS += [base["dstate"] + 2 * d + 1, base["ddir"] + 2 * d + 1, base["dsub"] + 2 * d + 1]
        WORDS += [base["dwait"] + 2 * (WAIT_NIBBLES * d + k) + 1 for k in range(WAIT_NIBBLES)]
    for si in order:
        for li in lines_of.get(si, ()):
            WORDS.append(base["lnrow"] + 2 * (li * LINE_REST_LEN + FLAGS_REST_BYTE) + 1)

    drawable = [t for t in mw.things(args.map) if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    runtime = [t for t, b in zip(drawable, baked) if not b]
    blob_tail = (encode_things([(t.x << 16, t.y << 16) for t in runtime])
                 + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in runtime])
                 + encode_visibility([1] * nvis))

    runner = FjmRunner(ROOT / args.fjm)
    assert runner.native

    def run_frame(state, keys, carry):
        core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
        for seg, n in runner._segments:
            core.add_segment(seg, n)
        for st_, vals in runner._runs:
            core.set_words(st_, vals)
        for w, v in zip(WORDS, carry):
            core.set_words(w, [v])
        scr = StreamScreen(stdin=encode_feed(state.x, state.y, state.angle, keys) + blob_tail,
                           n_things=len(runtime))
        scr.attach_memory(NativeDeviceMemory(core, runner.width))
        core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
        out = (bytes(scr.pixel_indices), scr.state, [core.get_word(w) for w in WORDS])
        del core, scr
        return out

    x0, y0, x1, y1 = boxes[tgt]
    near_y, far_y = y0 + 64, y1 - 64          # the door's own lines
    start = SimState(((x0 + x1) // 2) << 16, (y0 + 8) << 16, 0x40000000, args.map)

    _core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        _core.add_segment(seg, n)
    for st_, vals in runner._runs:
        _core.set_words(st_, vals)
    # the image's OWN initial values -- state 0 everywhere and the baked blocking bits. Each
    # run starts from a copy, so one run's opened door cannot leak into the next.
    carry0 = [_core.get_word(w) for w in WORDS]
    del _core

    print("door sector %d: %d states %s, pass_state %d, its lines at y %d..%d"
          % (tgt, nstates[tgt], tbl[tgt], passes[tgt], near_y, far_y))
    print("")

    def one_run(frozen=False, wait=0):
      print("  player at (%d,%d) facing +y, holding FORWARD%s"
            % (start.x >> 16, start.y >> 16, "" if frozen else " and USE"))
      print("  frame  door state   player y   moved?   verdict"
            + ("        (frames 0..%d: standing, letting the door climb)" % (wait - 1)
               if wait else ""))

      dstates = initial_states(secs, lds, sds)
      state = start
      carry = list(carry0)
      ok, seen = True, {}
      for f in range(args.frames):
          # the wait phase presses USE only: the door climbs while the player stands still, so the
          # shove that follows lands at a state the "hold everything" run is through before reaching
          keys = ({"use": True} if f < wait else
                  ({"forward": True} if frozen else {"forward": True, "use": True}))
          kb = keys_byte(keys)
          prev_y = _s32(state.y)
          px, echoed, carry = run_frame(state, kb, carry)

          kd = keys_dict(kb)
          used = bool(kd.get("use"))
          dstates = {si: door_tic(dstates[si], nstates[si],
                                  used and in_use_box_fixed(boxes[si], state.x, state.y))
                     for si in order}
          blocked = frozenset(li for si in order if dstates[si][0] < passes[si]
                              for li in lines_of.get(si, ()))
          csc = build_scene(mw, mw, args.map, open_h, blocked)
          state = rm.step_sim(state, kd, scene=csc)
          rsc = build_scene(mw, mw, args.map,
                            heights_for_states(secs, lds, sds, {si: dstates[si][0] for si in order}))
          want = bytes(rm.render_wall_frame(state, rsc, wall_mode="W1R", floor_mode_ft1=True,
                                            plane_near=True, wall_noise=True, near_steps=True,
                                            stack_steps=True, things=True, sprite_wad=art,
                                            degrade=True))
          # C1: the two mirrors must agree on BOTH the picture and where the player ended up
          agree = (px == want) and (echoed == (_s32(state.x), _s32(state.y), state.angle))
          ok &= agree

          k = dstates[tgt][0]                 # the state collision actually saw this frame
          y_now = _s32(state.y) >> 16
          moved = y_now > (prev_y >> 16)
          if f >= wait:                 # only the shove frames answer the question
              seen.setdefault(k, moved)
          want_admit = k >= passes[tgt]
          # a state below the threshold must NOT let the player advance; at or above it must
          right = ((moved == want_admit) if y_now < far_y or not moved else True)
          if f < wait:
              right = True                   # standing still proves nothing either way
          ok &= right and agree
          print("  %5d  %10d   %8d   %-6s   %s"
                % (f, k, y_now, "yes" if moved else "NO",
                   ("ok -- %s" % ("admitted" if moved else "refused"))
                   if (right and agree) else
                   ("!! MIRRORS DISAGREE" if not agree else
                    "!! state %d should have %s" % (k, "admitted" if want_admit else "refused"))),
                flush=True)
          if y_now > far_y:
              print("         (through the doorway -- later frames no longer test the door)")
              break

      print("")
      blocked_states = sorted(k for k, m in seen.items() if not m)
      admitted = sorted(k for k, m in seen.items() if m)
      print("  states observed REFUSING : %s" % (blocked_states or "none"))
      print("  states observed ADMITTING: %s" % (admitted or "none"))
      print("  pass_state = %d, so 0..%d must refuse and %d..%d must admit"
            % (passes[tgt], passes[tgt] - 1, passes[tgt], nstates[tgt] - 1))
      missing = [k for k in range(nstates[tgt]) if k not in seen]
      if missing:
          print("  !! never observed at all: %s" % missing)
      print("")
      return ok, seen


    ok, cover = run_matrix(one_run, nstates[tgt], passes[tgt])
    holes = [k for k in range(nstates[tgt]) if k not in cover]
    wrong = [k for k, moved in sorted(cover.items()) if moved != (k >= passes[tgt])]
    print("== the union over every run ==")
    for k in range(nstates[tgt]):
        v = cover.get(k)
        print("  state %d (ceiling %4d): %s   %s"
              % (k, tbl[tgt][k],
                 "NEVER OBSERVED" if v is None else ("ADMITTED " if v else "REFUSED  "),
                 "" if v is None else
                 ("ok" if v == (k >= passes[tgt]) else
                  "!! pass_state=%d says it should %s"
                  % (passes[tgt], "admit" if k >= passes[tgt] else "refuse"))))
    print("")
    good = ok and not holes and not wrong
    print("PASSABILITY PROBE: %s"
          % ("PASS -- all %d states observed, and each refuses or admits exactly as pass_state=%d "
             "says" % (nstates[tgt], passes[tgt]) if good else
             "FAIL -- %s%s" % ("holes at %s; " % holes if holes else "",
                               "wrong at %s" % wrong if wrong else "see above")))
    sys.exit(0 if good else 1)


def run_matrix(one_run, nst, thresh):
    """ONE run cannot see every state: a player pressed against a door walks through the moment it
    opens far enough, so the top states are never tested, and state 0 never happens once use is
    pressed. So the probe runs a MATRIX -- the frozen door for state 0, then the shove delayed by
    0..n frames so each run lands its first push at a different height -- and the verdict is over
    the union. A state nothing observed is reported as a hole, not quietly rounded into a pass."""
    cover, ok = {}, True
    for tag, kw in ([("door frozen shut", dict(frozen=True))]
                    + [("shove after %d idle frames" % w, dict(wait=w)) for w in range(nst)]):
        print("== %s ==" % tag, flush=True)
        good, seen = one_run(**kw)
        ok &= good
        for k, moved in seen.items():
            if k in cover and cover[k] != moved:
                print("  !! state %d both refused and admitted across runs" % k)
                ok = False
            cover[k] = moved
        print("")
    return ok, cover


if __name__ == "__main__":
    main()
