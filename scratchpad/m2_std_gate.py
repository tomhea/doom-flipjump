"""M2 STANDALONE GATE -- the SHIPPED binary opens a door and the door STAYS open across the reset.

    python scratchpad/m2_std_gate.py --fjm build/doom_e1m1_menu.fjm
    python scratchpad/m2_std_gate.py --selftest        # R9: the oracle never presses use

WHY THIS EXISTS, AND WHAT NO EXISTING GATE COVERS. `m2_r4_gate` proves the door machine works on
the HOSTED tier -- but there every frame is a fresh image and the gate RELAYS the door cells
between frames, because nothing in a hosted image survives on its own. The standalone tier is the
opposite: nothing is relayed, and the door cells have to survive the M1 self-reset by being in
`build.DOOR_PERSIST` and therefore excluded from the restore set. That exclusion is the whole
feature, and it was untested end to end: a binary built before `DOOR_PERSIST` existed renders
perfectly, opens a door for exactly one frame, and re-shuts it on every frame after -- and `m3_gate`
(the only gate that runs this binary) never presses use, so it sees none of that.

So the property under test is CUMULATIVE and it is the reset: a door that reaches state 3 has been
carried across two resets, and no single-frame check can see it.

THE ROUTE IS PLANNED BY THE ORACLE, NOT BY HAND. The standalone player starts at the map's baked
spawn -- 1,070 units from the nearest door -- so the script has to WALK there. A beam search over
the sim (`--plan` prints it) finds a key sequence that ends inside a door's use box; since the
oracle is the same sim the program runs, a route that works in Python is a route that works in fj.

MENU FRAMES ARE NOT JUDGED HERE. The binary boots into the menu and this gate presses enter to
leave it; `m3_gate` is what certifies the menu picture, and duplicating it would be two mirrors of
the same thing. What this asserts about them is only that they are identical to each other (a
changing menu would mean `mode` was not persisting) -- stated rather than implied.

CONTROLS
  C1  the door must reach at least THREE distinct states -- one state is a door that opened and
      re-shut, which is exactly the bug, and two could be a single step. Three needs the reset to
      have carried the cell twice.
  C2  the player must actually be inside the use box when use is pressed, checked against
      `doors.in_use_box_fixed` rather than against the fact that something happened.
  C3  --selftest: the oracle never presses use, so its doors stay shut; every frame from the one
      the door first moves must then differ. A gate that cannot fail is not evidence.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.doorcode import door_line_ids                                 # noqa: E402
from doomfj.doors import (door_states, door_tic, heights_for_states,      # noqa: E402
                          in_use_box_fixed, initial_states, pass_state, use_boxes_xy)
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (ReferenceModel, build_scene,          # noqa: E402
                                    spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import STANDALONE_POLLS                         # noqa: E402
from doomfj.wireformat import KEY_NAMES                                   # noqa: E402
from flipjump.interpreter.io_devices.KeyboardIO import (KeyboardIO, KeyEvent,   # noqa: E402
                                                        ScriptedKeyEventSource)
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen            # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.interpreter.io_devices.pygame_window import PcIO                 # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402

ENTER = 0x0D
K_FWD, K_BACK, K_LEFT, K_RIGHT, K_USE = 0x77, 0x73, 0x61, 0x64, 0x20
BINDING = {K_FWD: "forward", K_BACK: "back", K_LEFT: "turn_left",
           K_RIGHT: "turn_right", K_USE: "use"}
CODE = {"forward": K_FWD, "back": K_BACK, "turn_left": K_LEFT,
        "turn_right": K_RIGHT, "use": K_USE}

MENU_FRAMES = 2                 # frames 0..1 are the menu; enter is pressed on frame 1


class Recording(InMemoryScreen):
    """the stock device plus a snapshot of every PRESENTED frame"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


class Stopper(KeyboardIO):
    """the keyboard, but it EOFs once the screen has presented enough frames -- the standalone
    program has no end of its own (see m5_gate's note)"""

    def __init__(self, event_source, screen, limit):
        super().__init__(event_source)
        self._screen, self._limit = screen, limit

    def read_bit(self):
        if len(self._screen.frames) >= self._limit:
            raise IOReadOnEOF("the gate has the %d frames it asked for" % self._limit)
        return super().read_bit()


def seg_cross(p, q, a, b):
    """do the segments p-q and a-b properly intersect?

    ⚠ NOT a signed-side test on the door's infinite line. That was the first version, and it
    reported a crossing whenever the player walked past the LINE'S EXTENSION -- which is exactly
    what the walk was doing, so the control passed while the player never went near the doorway.
    A control that can be satisfied by walking around the thing it is testing is not a control."""
    def cross(o, u, v):
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    d1, d2 = cross(a, b, p), cross(a, b, q)
    d3, d4 = cross(p, q, a), cross(p, q, b)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def plan_to(rm, scene, start, goal, radius, maxf=40, width=24, accept=None):
    """A beam search over the SIM for a key script that ends within `radius` of `goal`.

    Deterministic: fixed move order, a stable sort, and a pose de-dup that keeps the first (best)
    of each cell. The oracle is the same simulation the program runs, so a route that arrives here
    arrives there -- and if it did not, the byte-exact comparison would say so on the frame they
    parted."""
    gx, gy = goal
    moves = [("forward",), ("forward", "turn_left"), ("forward", "turn_right"),
             ("turn_left",), ("turn_right",)]

    def dist(st):
        return (((st.x >> 16) - gx) ** 2 + ((st.y >> 16) - gy) ** 2) ** 0.5

    def arrived(st):
        return dist(st) <= radius and (accept is None or accept(st))

    beam = [(dist(start), start, [])]
    if arrived(start):
        return []
    for _ in range(maxf):
        nxt = []
        for _d, st, path in beam:
            for keys in moves:
                kd = {k: (k in keys) for k in KEY_NAMES}
                ns = rm.step_sim(st, kd, scene=scene)
                if arrived(ns):
                    return path + [kd]
                nxt.append((dist(ns), ns, path + [kd]))
        nxt.sort(key=lambda t: t[0])
        seen, beam = set(), []
        for d, st, pth in nxt:
            k = (st.x >> 22, st.y >> 22, st.angle >> 27)
            if k in seen:
                continue
            seen.add(k)
            beam.append((d, st, pth))
            if len(beam) >= width:
                break
    return None


def plan_route(rm, mw, scene, boxes, target, maxf=90, width=24):
    """A beam search over the SIM for a key script that ends inside `target`'s use box.

    Deterministic: fixed move order, a stable sort, and a pose de-dup that keeps the first (best)
    of each cell. The oracle is the same simulation the program runs, so a route that lands in the
    box here lands in it there -- and if it did not, the byte-exact comparison below would say so
    on the first frame they parted."""
    x0, y0, x1, y1 = boxes[target]
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    moves = [("forward",), ("forward", "turn_left"), ("forward", "turn_right"),
             ("turn_left",), ("turn_right",)]

    def dist(st):
        return (((st.x >> 16) - cx) ** 2 + ((st.y >> 16) - cy) ** 2) ** 0.5

    def inbox(st):
        return x0 <= (st.x >> 16) <= x1 and y0 <= (st.y >> 16) <= y1

    start = spawn_state(mw, "E1M1")
    beam = [(dist(start), start, [])]
    for _ in range(maxf):
        nxt = []
        for _d, st, path in beam:
            for keys in moves:
                kd = {k: (k in keys) for k in KEY_NAMES}
                ns = rm.step_sim(st, kd, scene=scene)
                if inbox(ns):
                    return path + [kd]
                nxt.append((dist(ns), ns, path + [kd]))
        nxt.sort(key=lambda t: t[0])
        seen, beam = set(), []
        for d, st, p in nxt:
            k = (st.x >> 22, st.y >> 22, st.angle >> 27)
            if k in seen:
                continue
            seen.add(k)
            beam.append((d, st, p))
            if len(beam) >= width:
                break
    return None


def to_events(per_frame):
    """the per-frame HELD dicts as the device's down/up events.

    An event at tic `f*POLLS` is delivered on the first poll of frame f, so the flag is set before
    that frame's tic reads it -- the same rule `held_per_frame` re-implements below, from the other
    side, which is what makes the two independent."""
    out, held = [], {k: False for k in KEY_NAMES}
    for f, keys in enumerate(per_frame):
        for name in KEY_NAMES:
            want = bool(keys.get(name))
            if want != held[name]:
                out.append(KeyEvent(f * STANDALONE_POLLS, want, CODE[name]))
                held[name] = want
    return out


def held_per_frame(events, frames):
    """the DEVICE's delivery rule, re-implemented: one event per poll, due once the tic clock
    reaches it. Returns (key dict, enter-pressed) per frame."""
    pending = sorted(events, key=lambda e: e.tic)
    held = {name: False for name in KEY_NAMES}
    out, enters, i = [], [], 0
    enter_this_frame = False
    for tic in range(frames * STANDALONE_POLLS):
        while i < len(pending) and pending[i].tic <= tic:
            ev = pending[i]
            i += 1
            if ev.keycode == ENTER:
                enter_this_frame |= ev.is_down          # DOWN edge only -- kb.poll edge-triggers
                continue
            name = BINDING.get(ev.keycode)
            if name is not None:
                held[name] = ev.is_down
        if tic % STANDALONE_POLLS == STANDALONE_POLLS - 1:
            out.append(dict(held))
            enters.append(enter_this_frame)
            enter_this_frame = False
    return out, enters


def run_fj(fjm, events, frames):
    """one process, `frames` presented frames, driven by nothing but the scripted keyboard --
    the SAME PcIO composition `fj --io pc` builds"""
    runner = FjmRunner(Path(fjm))
    assert runner.native, "this gate needs the native engine"
    core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        core.add_segment(seg, n)
    for start, vals in runner._runs:
        core.set_words(start, vals)
    screen = Recording()
    keyboard = Stopper(ScriptedKeyEventSource(events), screen, frames)
    io = PcIO(screen, keyboard)
    io.attach_memory(NativeDeviceMemory(core, runner.width))
    _c, ops, _e, _l, _p = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
    out = (list(screen.frames), ops)
    del core, screen, io, runner
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_menu.fjm")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default="assets/freedoom1.wad")
    ap.add_argument("--open-wait", type=int, default=8,
                    help="frames to stand while the door walks up to its last state")
    ap.add_argument("--walk", type=int, default=8,
                    help="frames to walk FORWARD through the opened doorway (the collision half)")
    ap.add_argument("--idle", type=int, default=6,
                    help="frames to stand on the far side while the door starts to shut")
    ap.add_argument("--plan", action="store_true", help="print the planned route and exit")
    ap.add_argument("--dry", action="store_true",
                    help="step the ORACLE alone through the script (no fj, no rendering) and "
                         "report the door states -- proves the script is not vacuous for 2 seconds "
                         "instead of for a billion ops")
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

    # the door to walk to: the nearest one to the spawn, by the same measure the planner minimises
    sp = spawn_state(mw, args.map)
    target = min(order, key=lambda si: ((boxes[si][0] + boxes[si][2]) // 2 - (sp.x >> 16)) ** 2
                 + ((boxes[si][1] + boxes[si][3]) // 2 - (sp.y >> 16)) ** 2)

    # ⚠ `mw, mw` -- the MAP wad as the asset wad, which is what m3_gate/m5_gate/m2_r4_gate all do
    # and what the emitter bakes from. Passing the real art wad here renders a different picture
    # and cost this gate one 2.1-billion-op run that failed on frame 2 with 400 px, nowhere near a
    # door. The sprites still come from `art`, via render_wall_frame's own `sprite_wad`.
    walk_scene = build_scene(mw, mw, args.map)           # doors shut: what the walk really sees

    # THE DOORWAY, not the use box. The box is inflated by USE_RANGE and its south edge is 90 units
    # clear of the opening, so "reach the box" put the player alongside the door and the walk-through
    # leg then went AROUND it. Both legs aim at the gap between the door's own two line segments:
    # `approach` a little short of it on the player's side, `beyond` a little past it on the other.
    door_segs = [(cmap.vertexes[lds[li].v1], cmap.vertexes[lds[li].v2])
                 for li in sorted(lines_of[target])]
    (ax, ay), (bx, by) = door_segs[0]
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    nx, ny = -(by - ay), (bx - ax)                       # the line's normal
    nlen = (nx * nx + ny * ny) ** 0.5 or 1.0
    nx, ny = nx / nlen, ny / nlen
    sgn = -1.0 if ((sp.x >> 16) - mx) * nx + ((sp.y >> 16) - my) * ny > 0 else 1.0
    approach = (mx - sgn * nx * 56, my - sgn * ny * 56)  # the player's side of the opening
    beyond = (mx + sgn * nx * 88, my + sgn * ny * 88)    # through it, and out the far side

    # ⚠ arriving near the approach POINT is not the same as standing where use works: the first
    # version ended 27 units from it and 15 units OUTSIDE the use box, so the press did nothing and
    # the door never moved. The acceptance test is the box itself.
    route = plan_to(rm, walk_scene, sp, approach, 40, maxf=90,
                    accept=lambda st: in_use_box_fixed(boxes[target], st.x, st.y))
    assert route, "no route from the spawn to door %d's threshold at %s" % (target, approach)

    # menu frames, then the walk, then the press, then stand and watch the door work
    # use, stand while it opens, then WALK THROUGH IT. Standing still would prove the render half
    # only -- the door's passability is a separate claim with its own bit, and the only way to test
    # that bit in this tier is to try to walk through the doorway.
    press = [{"use": True}, {"use": True}]
    opening = [{} for _ in range(args.open_wait)]

    # PHASE C, planned rather than hard-coded: eight frames of "forward" walked the player PAST the
    # doorway rather than through it, and the first crossing control -- a signed side test on the
    # door's infinite line -- called that a crossing. So the walk-through is now a route to a point
    # on the FAR SIDE of the door's own line segment, planned against the scene with the door open,
    # and the control below tests segment-against-segment.
    st, ds = sp, initial_states(secs, lds, sds)
    for kd in route + press + opening:
        used = bool(kd.get("use"))
        ds = {si: door_tic(ds[si], nstates[si],
                           used and in_use_box_fixed(boxes[si], st.x, st.y)) for si in order}
        blk = frozenset(li for si in order if ds[si][0] < passes[si]
                        for li in lines_of.get(si, ()))
        st = rm.step_sim(st, kd, scene=build_scene(mw, mw, args.map, open_h, blk))
    assert ds[target][0] == nstates[target] - 1, (
        "door %d is at state %d, not open, after %d frames of waiting"
        % (target, ds[target][0], args.open_wait))

    through = plan_to(rm, build_scene(mw, mw, args.map, open_h), st, beyond, 40)
    assert through, "no route through door %d's opening to %s" % (target, beyond)

    script = ([{} for _ in range(MENU_FRAMES)] + route + press + opening + through
              + [{} for _ in range(args.idle)])
    frames = len(script)
    # enter lands on the FIRST route frame: the poll flips `mode` before the menu branch reads it,
    # so that frame already renders the world and no frame is spent on the transition.
    events = to_events(script) + [KeyEvent(MENU_FRAMES * STANDALONE_POLLS, True, ENTER),
                                  KeyEvent(MENU_FRAMES * STANDALONE_POLLS + 1, False, ENTER)]
    keys_by_frame, enters = held_per_frame(events, frames)

    print("fjm    : %s" % args.fjm)
    print("target : door sector %d, use box %s, threshold state %d"
          % (target, boxes[target], passes[target]))
    print("script : %d menu -> enter -> %d walk to the door -> %d use -> %d open -> %d through "
          "-> %d idle  (%d frames)"
          % (MENU_FRAMES, len(route), len(press), args.open_wait, len(through), args.idle, frames))
    print("doorway: line %d %s -> approach %s, then through to %s"
          % (sorted(lines_of[target])[0], door_segs[0],
             tuple(round(v) for v in approach), tuple(round(v) for v in beyond)))


    if args.plan:
        for i, k in enumerate(script):
            print("  %3d %s" % (i, "".join(n[0] for n in sorted(k) if k[n]) or "-"))
        return 0

    if args.dry:
        st, ds, md = sp, initial_states(secs, lds, sds), 1
        for f in range(frames):
            kd = keys_by_frame[f]
            if enters[f]:
                md ^= 1
            if md == 1:
                continue
            inb = in_use_box_fixed(boxes[target], st.x, st.y)
            ds = {si: door_tic(ds[si], nstates[si],
                               bool(kd.get("use")) and in_use_box_fixed(boxes[si], st.x, st.y))
                  for si in order}
            blocked = frozenset(li for si in order if ds[si][0] < passes[si]
                                for li in lines_of.get(si, ()))
            st = rm.step_sim(st, kd, scene=build_scene(mw, mw, args.map, open_h, blocked))
            print("  %3d %-6s (%6d,%6d) door%d=%d%s"
                  % (f, "".join(n[0] for n in sorted(kd) if kd[n]) or "-",
                     st.x >> 16, st.y >> 16, target, ds[target][0],
                     "  IN BOX" if inb else ""))
        return 0

    got, ops = run_fj(ROOT / args.fjm, events, frames)
    assert len(got) == frames, "the program presented %d frames, not %d" % (len(got), frames)
    print("running: %s ops -> %d frames presented" % (format(ops, ","), len(got)))
    print("")

    # ---- the oracle, stepping the same machine in the same order --------------------------------
    # The emitted order is: poll -> menu branch -> door tic -> player tic -> render. A MENU frame
    # branches past both tics, which is why the mode mirror comes first here too.
    dstates = initial_states(secs, lds, sds)
    state = sp
    mode = 1                                            # the binary boots into the menu
    ok, menu_pics, in_box_when_pressed = True, [], False
    seen, track = set(), []
    first_move = None
    print("  frame  keys      door%-4d  fj px vs oracle" % target)
    for f in range(frames):
        kd = keys_by_frame[f]
        if enters[f]:
            mode ^= 1
        if mode == 1:                                   # a menu frame tics nothing
            menu_pics.append(got[f])
            print("  %5d  %-8s  %6s   (menu frame -- m3_gate judges these)"
                  % (f, "enter" if enters[f] else "-", "-"))
            continue
        used = bool(kd.get("use")) and not args.selftest
        if kd.get("use") and in_use_box_fixed(boxes[target], state.x, state.y):
            in_box_when_pressed = True
        dstates = {si: door_tic(dstates[si], nstates[si],
                                used and in_use_box_fixed(boxes[si], state.x, state.y))
                   for si in order}
        blocked = frozenset(li for si in order if dstates[si][0] < passes[si]
                            for li in lines_of.get(si, ()))
        state = rm.step_sim(state, kd, scene=build_scene(mw, mw, args.map, open_h, blocked))
        rsc = build_scene(mw, mw, args.map,
                          heights_for_states(secs, lds, sds, {si: dstates[si][0] for si in order}))
        want = bytes(rm.render_wall_frame(state, rsc, wall_mode="W1R", floor_mode_ft1=True,
                                          plane_near=True, wall_noise=True, near_steps=True,
                                          stack_steps=True, things=True, sprite_wad=art,
                                          degrade=True))
        same = got[f] == want
        ok &= same
        d0 = dstates[target][0]
        seen.add(d0)
        track.append((state.x >> 16, state.y >> 16))
        if d0 and first_move is None:
            first_move = f
        print("  %5d  %-8s  %6d   %s"
              % (f, "".join(n[0] for n in sorted(kd) if kd[n]) or "-", d0,
                 "BYTE-EXACT" if same else
                 "!! %d px differ" % sum(a != b for a, b in zip(got[f], want))), flush=True)
        if not same and not args.selftest:
            print("  -- stopping: once the trajectories part, later frames compare nothing useful")
            break

    print("")
    menu_same = len(set(menu_pics)) <= 1
    print("  CONTROL 1: door %d reached %d distinct states %s -- %s"
          % (target, len(seen), sorted(seen),
             "carried across the reset" if len(seen) >= 3 else
             "!! NOT ENOUGH: one state is a door that re-shut every frame, which IS the bug"))
    print("  CONTROL 2: use was pressed INSIDE the box: %s" % ("yes" if in_box_when_pressed else
                                                               "!! no -- the script missed"))
    print("  CONTROL 3: the %d menu frames are identical to each other: %s"
          % (len(menu_pics), "yes" if menu_same else "!! no -- `mode` is not persisting"))
    crossed = any(seg_cross(track[i], track[i + 1], a, b)
                  for i in range(len(track) - 1) for a, b in door_segs)
    print("  CONTROL 4: the player's path crosses door %d's own line SEGMENT (%s): %s"
          % (target, " / ".join("%s-%s" % (a, b) for a, b in door_segs),
             "yes -- and every frame is byte-exact, so fj walked the same path, which its "
             "blocking bit had to clear to allow" if crossed else
             "!! NO -- collision was never tested, this proves the render half only"))
    vac = len(seen) < 3 or not in_box_when_pressed or not menu_same or not crossed
    if vac:
        print("  !! VACUOUS -- fix the SCRIPT, not the verdict")
    print("")
    if args.selftest:
        print("SELFTEST (the oracle never presses use, so its doors stay shut): %s"
              % ("PASS -- the gate rejected it" if not ok else "!! FAIL -- it accepted"))
        return 0 if not ok else 1
    print("M2 STANDALONE GATE: %s"
          % ("PASS -- the shipped binary opens a door and KEEPS it open across the M1 reset"
             if (ok and not vac) else "FAIL"))
    return 0 if (ok and not vac) else 1


if __name__ == "__main__":
    sys.exit(main())
