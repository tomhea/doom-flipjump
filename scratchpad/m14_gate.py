"""M14 GATE — the binary state wire and the player sim, gated the way deg_gate gates the renderer.

Same map, same tier, same degrade=True oracle as `scratchpad/deg_gate.py`; the differences are
`state_wire="bin"` and `player_sim=True`. Two phases:

  PHASE 1 -- STILL. The four deg_gate viewpoints, fed with keys=0. The sim is a no-op with no key
    pressed (proved exhaustively over all 16 combinations in tests/fj/test_state_wire.py), so every
    frame must still be byte-exact against the oracle, the echoed state must come back unchanged,
    and the op counts should differ from the dec wire only by the input path -- three decimal
    parses (~60k ops) traded for 13 raw bytes (~1k) plus the sim's handful of key tests.

  PHASE 2 -- MOVING, which is the point. One frame proving byte-exact says nothing about state
    drift on frame 200. N tics from the spawn point under a scripted key
    sequence, each tic's echoed state relayed into the next -- exactly the loop the host will run --
    with BOTH the frame and the state compared against the oracle every tic. This is the first gate
    in the repo that is stateful across frames.

⚠ ONE HEAVY BUILD AT A TIME (CLAUDE.md rule 1) -- this assembles a ~12MB binary, so nothing else
may build while it runs.

Usage:  python scratchpad/m14_gate.py [tics]
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer, write_program_files
from doomfj.wireformat import encode_feed, encode_feed_mapunits, encode_things, keys_dict
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj", "sim.fj")]
# the M14-a certified op counts (dec wire), in VPS order -- the baseline the bin wire is diffed
# against. deg_gate's own header still carries the pre-M14-a numbers.
DEC_OPS = (45_664_661, 36_423_780, 43_030_266, 34_119_621)

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(664, 291, 0x18000000),        # the sprite-overlap frame: B-gate + graduated
       (1272, -724, 1073741824),      # stairs: the stack far gate
       (1869, 479, 2147483648),       # the everything frame: sliver + PNEAR + all
       (spx, spy, sp.angle)]

F, B, L, R = 0b0001, 0b0010, 0b0100, 0b1000
# The scripted tics. The first stretch is the M14-c script -- turn, walk, turn while walking, back
# up, and the two cancelling pairs.
#
# ⚠ THE TAIL EXISTS TO MAKE --collide NON-VACUOUS. Under `--collide` both mirrors run collision, so
# a script that never touches a wall passes whether or not the collision works at all. Four turns
# then five steps walks the player INTO one from spawn (found by searching the oracle for the
# shortest colliding script), and `phase2` asserts that at least one tic was actually blocked.
# ...and it goes FIRST, because it only reaches that wall FROM SPAWN. Appended, the player has
# already walked elsewhere by the time it runs and nothing is hit -- which the control caught.
SCRIPT = ([L, L, L, L, F, F, F, F, F]
          + [L, L, F, F, F | L, F | L, F, F | R, B, F | B, L | R, F, F, F | R, R, F])

RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                 near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)


COLLIDE = "--collide" in sys.argv
MOVING = "--things" in sys.argv                  # M14-e: the RUNTIME thing table
# ⚠ the cache key must name EVERY flag that changes the binary -- keying it on one of two would
# hand `--things --collide` the no-collision binary and gate the wrong program.
CACHE = ROOT / ("scratchpad/fjmcache/m14_bin%s%s.fjm"
                % ("_coll" if COLLIDE else "", "_things" if MOVING else ""))

# M14-e — the drawable things, in the ONE order both mirrors index by: wad order, filtered to the
# types that have art. `thing_rows` (fj side) and `render_wall_frame`'s `_drawable` (oracle side)
# apply that same filter, and the two were checked to select the identical 251 things.
DRAWABLE = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
SPAWN_POS = [(t.x, t.y) for t in DRAWABLE]
# ⚠ WHOLE MAP UNITS. fj carries a thing at full 16.16 but the oracle's override takes the integer
# `t.x`/`t.y` a WAD thing has, so a fractional thing would be comparing two different worlds. The
# player is the fractional one (M14-c); things move on the grid until the oracle carries 16.16 too.
THING_DRIFT = 4                                  # map units per tic, every thing, +x


def thing_positions(tic):
    """Where every drawable thing stands on tic `tic` -- the host holds this between frames exactly
    as it holds the player's state, because the program is a pure function of stdin (section 2)."""
    return [(x + THING_DRIFT * tic, y) for x, y in SPAWN_POS]


def feed(state, keys, positions=None):
    """The wire: the player's state, then the thing block if this build reads one."""
    b = encode_feed(*state, keys)
    if MOVING:
        b += encode_things([(x << 16, y << 16) for x, y in
                            (SPAWN_POS if positions is None else positions)])
    return b


def build():
    """Assemble once and KEEP the binary. A gate that throws its binary away forces a 25-minute
    rebuild for every follow-up probe, which is how a divergence stays undiagnosed."""
    if CACHE.exists() and "--rebuild" not in sys.argv:
        print(f"cache HIT {CACHE.name} ({CACHE.stat().st_size:,} bytes)", flush=True)
        return CACHE
    parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, over_align=False,
                               floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                               plane_near=True, wall_noise=True, steps=True, stack_steps=True,
                               things=True, sprite_wad=art, deg=True,
                               state_wire="bin", player_sim=True, collide=COLLIDE,
                               moving_things=MOVING)
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    prog = write_program_files(parts, tmp, "e1m1")     # ⚠ order is the contract
    out = tmp / "m14.fjm"
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], *[p.resolve() for p in prog]],
                out, memory_width=W, print_time=False)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_bytes(out.read_bytes())
    print(f"assembled {CACHE.stat().st_size:,} bytes -> {CACHE.name}", flush=True)
    return CACHE


def run(fjm, feed):
    scr = StreamScreen(stdin=feed)
    term = fj.run(fjm, io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=1 << 26)
    return scr, term


def phase1(fjm):
    """⚠ With --things this is also THE PIXEL-NEUTRALITY PROOF. Fed the SPAWN positions, the runtime
    table must reproduce the frames the baked blocks produced -- same pixels, same sprite slots. If
    it does, any divergence phase 2 finds belongs to the moving half and nowhere else."""
    ok = True
    print("\nPHASE 1 -- still (keys=0), against deg_gate's viewpoints", flush=True)
    for i, (vx, vy, va) in enumerate(VPS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene, **RENDER_KW)
        scr, term = run(fjm, feed((vx << 16, vy << 16, va), 0))
        same = bytes(scr.pixel_indices) == bytes(want)
        diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
        echoed = scr.state == (vx << 16, vy << 16, va)
        ok &= same and echoed
        print(f"  ({vx},{vy},{va:#x}): {term.op_counter:,} ops "
              f"(dec wire {DEC_OPS[i]:,}, {term.op_counter - DEC_OPS[i]:+,})  "
              f"{'BYTE-EXACT' if same else f'!! {diff} px DIFFER'}  "
              f"state {'ROUND-TRIPPED' if echoed else f'!! {scr.state}'}", flush=True)
    return ok


def phase2(fjm, tics):
    """N tics from spawn, relaying each tic's echoed state back in, frame AND state checked."""
    print(f"\nPHASE 2 -- moving: {tics} tics from spawn, scripted keys, state relayed", flush=True)
    ok = True
    state = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
    want_state = state
    blocked_tics = 0
    leaf_changes = moved_frames = 0
    for tic in range(tics):
        keys = SCRIPT[tic % len(SCRIPT)]
        pos = thing_positions(tic) if MOVING else None
        if MOVING:
            # ⚠ THE CONTROL, and it is two-sided. Counting leaf changes alone would pass a build
            # that re-binds correctly and never draws the result; counting changed pixels alone
            # would pass one that moves sprites without re-binding them. Both must happen.
            leaf_changes += sum(rm.point_in_subsector(scene.cmap, x, y)
                                != rm.point_in_subsector(scene.cmap, sx, sy)
                                for (x, y), (sx, sy) in zip(pos, SPAWN_POS))
        scr, term = run(fjm, feed(state, keys, pos))
        # the oracle takes the same tic, then renders from the state that tic produced
        _prev = SimState(want_state[0] & 0xFFFFFFFF, want_state[1] & 0xFFFFFFFF,
                         want_state[2], "E1M1")
        s = rm.step_sim(_prev, keys_dict(keys), scene=scene if COLLIDE else None)
        if COLLIDE:                      # did collision actually change this tic's outcome?
            _free = rm.step_sim(_prev, keys_dict(keys))
            blocked_tics += (_free.x, _free.y) != (s.x, s.y)
        want_state = (_signed(s.x, 32), _signed(s.y, 32), s.angle)
        want = rm.render_wall_frame(SimState(s.x, s.y, s.angle, "E1M1"), scene,
                                    thing_positions=pos, **RENDER_KW)
        if MOVING:
            # ... and did the drift actually reach the SCREEN this tic? Same viewpoint, spawn
            # positions: if that renders identically, this tic proves nothing about moving things.
            _static = rm.render_wall_frame(SimState(s.x, s.y, s.angle, "E1M1"), scene, **RENDER_KW)
            moved_frames += bytes(_static) != bytes(want)
        same = bytes(scr.pixel_indices) == bytes(want)
        diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
        st_ok = scr.state == want_state
        ok &= same and st_ok
        print(f"  tic {tic:3d} keys={keys:04b} -> ({want_state[0] / 65536:9.3f},"
              f"{want_state[1] / 65536:9.3f}) ang={want_state[2]:#010x}  "
              f"{term.op_counter:,} ops  {'BYTE-EXACT' if same else f'!! {diff} px DIFFER'}  "
              f"state {'OK' if st_ok else f'!! fj {scr.state} vs oracle {want_state}'}", flush=True)
        if not (same and st_ok):
            print("  -- stopping: once the trajectories part, later tics compare nothing useful")
            break
        state = scr.state                          # the relay: this tic's output is next tic's input
    if COLLIDE:
        # ⚠ THE CONTROL. With collision on BOTH sides, a script that never hits a wall agrees no
        # matter what the fj does. Refuse to call it a pass unless a wall was actually hit.
        print(f"  collision changed the outcome on {blocked_tics} of {tics} tics", flush=True)
        if not blocked_tics:
            print("  !! VACUOUS: no tic was blocked -- run more tics or fix SCRIPT")
            ok = False
    if MOVING:
        print(f"  things changed leaf {leaf_changes} times; the drift changed the frame on "
              f"{moved_frames} of {tics} tics", flush=True)
        if not leaf_changes:
            print("  !! VACUOUS: nothing ever changed leaf -- raise THING_DRIFT or run more tics")
            ok = False
        if not moved_frames:
            print("  !! VACUOUS: no moved thing was ever ON SCREEN -- the re-binding is untested")
            ok = False
    return ok


def probe(fjm, argv):
    """`--probe vx vy va keys` -- one frame at an arbitrary state, against the oracle. The point is
    to separate "the sim corrupted something" from "the renderer and the oracle disagree at a
    viewpoint no gate has ever visited": feed keys=0 to take the sim out of the picture."""
    vx, vy, va, keys = int(argv[0]), int(argv[1]), int(argv[2], 0), int(argv[3], 0)
    scr, term = run(fjm, feed((vx << 16, vy << 16, va), keys))
    st = scr.state
    want = rm.render_wall_frame(SimState(st[0] & 0xFFFFFFFF, st[1] & 0xFFFFFFFF, st[2], "E1M1"),
                                scene, **RENDER_KW)
    got = bytes(scr.pixel_indices)
    diff = sum(1 for a, b in zip(got, bytes(want)) if a != b)
    print(f"probe ({vx},{vy},{va:#x}) keys={keys:04b} -> state {st} ({st[2]:#010x})  "
          f"{term.op_counter:,} ops  "
          f"{'BYTE-EXACT' if diff == 0 else f'!! {diff} of {len(got)} px DIFFER'}", flush=True)
    return diff == 0


def main():
    if "--probe" in sys.argv:
        i = sys.argv.index("--probe")
        return 0 if probe(build(), sys.argv[i + 1:i + 5]) else 1
    tics = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else 8
    fjm = build()
    ok = phase1(fjm)
    ok &= phase2(fjm, tics)
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
