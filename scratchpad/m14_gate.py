"""M14 GATE — the binary state wire and the player sim, gated the way deg_gate gates the renderer.

Same map, same tier, same degrade=True oracle as `scratchpad/deg_gate.py`; the differences are
`fed with keys=0. The sim is a no-op with no key
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
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES, ReferenceModel, SimState,
                                    build_scene, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer, write_program_files
from doomfj.wireformat import (BINDING_DIRTY, encode_bindings, encode_feed,
                              encode_feed_mapunits, encode_things, encode_visibility, keys_dict)
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj", "sim.fj")]
# the M14-a certified op counts (dec wire), in VPS order -- the baseline the bin wire is diffed
# against. deg_gate's own header still carries the pre-M14-a numbers.
# ⚠ STALE SINCE A0.1 (2026-08-17): these were measured WITHOUT `bbox_cull`, which A0.1 turned on
# everywhere and which is worth -1.0M..-2.7M per viewpoint on the static tier. The phase-1 delta
# printed against them is therefore NOT "the cost of the bin wire" -- it is that plus the cull's
# saving. Printed as a landmark only; do not quote it. Re-measure both sides to price the wire.
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

RENDER_KW = dict(floor_mode_ft1=True, near_steps=True, things=True, sprite_wad=art, degrade=True)


# ⚠ B0 (2026-08-18): COLLISION IS ON BY DEFAULT, because build.py and walk_e1m1.py now SHIP
# `collide=True` -- and a gate whose default differs from the shipped config certifies a program
# nobody runs. That is the A0.1 failure exactly, re-created one flag over and caught the same day.
# `--no-collide` keeps the old collision-free binary for A/B work; it is not the shipped tier.
COLLIDE = "--no-collide" not in sys.argv
MOVING = "--things" in sys.argv                  # M14-e: the RUNTIME thing table
# ⚠ CR-2026-08 (IN-3, A0.1): `bbox_cull` is part of THE ONE PICTURE now -- build.py ships it, the
# walker shows it and deg_gate certifies it -- but this gate was emitting without it, so the M14
# tier was still a different program from the static tier it is compared against. It is a constant,
# not a flag, for exactly that reason: the whole point of A0.1 is that there is one configuration.
# ⚠ ...and it changes the binary, so it is IN THE CACHE KEY. The pre-A0.1 `m14_bin*.fjm` caches
# were built without the cull and must not be silently reused under the new config.
CACHE = ROOT / ("scratchpad/fjmcache/m14_bin%s%s%s.fjm"
                % ("_coll" if COLLIDE else "", "_things" if MOVING else "",
                   "_cull"))

# M14-e — the drawable things, in the ONE order both mirrors index by: wad order, filtered to the
# types that have art. `thing_rows` (fj side) and `render_wall_frame`'s `_drawable` (oracle side)
# apply that same filter, and the two were checked to select the identical 251 things.
DRAWABLE = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
SPAWN_POS = [(t.x, t.y) for t in DRAWABLE]
# M14.5 — only the RUNTIME half is on the wire; the rest is baked into its leaf's code and cannot
# move. Same SSOT the emitter and the oracle read, so the three cannot drift.
BAKED = baked_thing_mask(rm, scene.cmap, DRAWABLE, MONSTER_TYPES)
RT = [i for i, b in enumerate(BAKED) if not b]
RTPOS = {i: k for k, i in enumerate(RT)}         # drawable index -> its slot on the wire
# M14.5 §3.3: the baked things that can VANISH, each with a 1-nibble flag at a fixed address.
VIS = vanishable_slots(DRAWABLE, BAKED, VANISHABLE_TYPES)      # drawable index -> wire slot
print(f"things: {len(DRAWABLE)} drawable = {sum(BAKED)} BAKED + {len(RT)} runtime; "
      f"{len(VIS)} baked things carry a visibility flag", flush=True)
# ⚠ WHOLE MAP UNITS. fj carries a thing at full 16.16 but the oracle's override takes the integer
# `t.x`/`t.y` a WAD thing has, so a fractional thing would be comparing two different worlds. The
# player is the fractional one (M14-c); things move on the grid until the oracle carries 16.16 too.
THING_DRIFT = 4                                  # map units per tic, +x
# ⚠ Only a SUBSET moves, and that is deliberate. If everything moves every tic, every thing is
# dirty every tic and the binding cache is never exercised -- the gate would pass a build whose
# cache path is broken. DOOM is the same shape: monsters move, decor does not.
# ⚠ ...and they must be things the player can SEE. `i % 8 == 0` picked 31 things spread over the
# whole map, none of them on screen from the spawn trajectory: 22 leaf changes, and the drift
# changed the frame on 0 of 10 tics. The gate caught it and failed, which is the entire point of
# checking pixels as well as bindings. So: the things NEAREST the spawn point.
# ⚠ ...and only a RUNTIME thing can move at all (M14.5), so the mover set is drawn from those.
# ⚠ AND THAT MADE THE OLD SET VACUOUS, which the gate caught: "nearest 30 drawable" crossed 22 leaf
# boundaries, but "nearest 30 RUNTIME" (mostly monsters, standing in big open leaves) crossed ZERO,
# so the re-binding path went untested. So the set is now CHOSEN for the property the gate needs:
# things that both (a) actually change leaf under the scripted drift, and (b) are near the player.
# The host can compute (a) exactly -- it is one point location per candidate per tic.
def _crosses(i, tics=24):
    ss0 = rm.point_in_subsector(scene.cmap, *SPAWN_POS[i])
    return any(rm.point_in_subsector(scene.cmap, SPAWN_POS[i][0] + THING_DRIFT * t,
                                     SPAWN_POS[i][1]) != ss0 for t in range(1, tics + 1))


_near = sorted(RT, key=lambda i: (SPAWN_POS[i][0] - spx) ** 2 + (SPAWN_POS[i][1] - spy) ** 2)
MOVERS = [i for i in _near if _crosses(i)][:20] or _near[:20]
MOVERS = sorted(set(MOVERS) | set(_near[:10]))       # ... plus the nearest, for the PIXEL half
print(f"movers: {len(MOVERS)} runtime things, "
      f"{sum(1 for i in MOVERS if _crosses(i))} of them cross a leaf boundary", flush=True)


def thing_positions(tic):
    """Where every drawable thing stands on tic `tic` -- the host holds this between frames exactly
    as it holds the player's state, because the program is a pure function of stdin (section 2)."""
    m = set(MOVERS)
    return [(x + THING_DRIFT * tic, y) if i in m else (x, y)
            for i, (x, y) in enumerate(SPAWN_POS)]


SPAWN_BINDINGS = [rm.point_in_subsector(scene.cmap, *SPAWN_POS[i]) for i in RT]


def feed(state, keys, positions=None, bindings=None, hidden=()):
    """The wire: the player's state, the thing positions, then last frame's BINDINGS.

    `bindings=None` means all-dirty -- a cold start, where fj point-locates all 251. Passing the
    previous frame's echo is the steady state, where it locates only what the host marked dirty."""
    b = encode_feed(*state, keys)
    if MOVING:
        pos = SPAWN_POS if positions is None else positions       # full drawable order
        b += encode_things([(pos[i][0] << 16, pos[i][1] << 16) for i in RT])
        b += encode_bindings([BINDING_DIRTY] * len(RT) if bindings is None else bindings)
        # ... and the visibility block, last: 1 = draw it. Sent EVERY frame -- fj has no state.
        b += encode_visibility([i not in set(hidden) for i in VIS])
    return b


def build():
    """Assemble once and KEEP the binary. A gate that throws its binary away forces a 25-minute
    rebuild for every follow-up probe, which is how a divergence stays undiagnosed."""
    if CACHE.exists() and "--rebuild" not in sys.argv:
        print(f"cache HIT {CACHE.name} ({CACHE.stat().st_size:,} bytes)", flush=True)
        return CACHE
    # the two measurement switches this gate has always had are TIER NAMES now, so the set of
    # programs it can build is enumerable instead of being a product of booleans
    parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, sprite_wad=art,
                               tier=("hosted" if COLLIDE and MOVING else
                                     "hosted-nocollide" if MOVING else "hosted-static"))
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
    scr = StreamScreen(stdin=feed, n_things=len(RT) if MOVING else 0)
    term = fj.run(fjm, io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_MAX_WORDS)
    return scr, term


# ⚠ CR-2026-08 (PJ-1 / PJ-2 / PJ-3) -- THE FRACTIONAL VIEWPOINTS, AND WHY THEY EXIST.
# Both PJ-1 (wedge eye terms) and PJ-2 (the absmul identity) were byte-exactness breaks that
# REQUIRE a fractional view position, and every certified viewpoint in this repo -- deg_gate's
# four, this gate's phase 1, every golden -- sits on a WHOLE MAP UNIT, where each bug is
# identically zero. That is not bad luck: the renderer predates M14, when the player could not
# stand between units. The consequence was that NO GATE IN THE REPO COULD FAIL ON EITHER BUG, and
# both were found by hand-written probes instead. This closes that hole.
#
# The offsets are chosen, not arbitrary:
#   0x8000 = exactly half a unit -- and it is PARTLY VACUOUS ON ITS OWN (R17): PJ-2 only diverges
#            there for an ODD seg coefficient, since P mod 2^16 = (a mod 2)*2^15. Kept because it
#            is the offset a reader will reach for, and labelled so nobody trusts it alone.
#   0x5555 = a fraction with bits across the whole low half; diverges for either parity.
#   the (0xC000, 0x5000) pair makes fy < fx AND fx + fy >= 1 simultaneously, which is the only way
#            to arm PJ-1's q=1 borrow and q=3 carry in the same frame.
FRAC_VPS = [(spx, spy, sp.angle, 0x8000, 0x8000, "half unit (R17: partly vacuous alone)"),
            (spx, spy, sp.angle, 0x5555, 0x5555, "0x5555 both axes"),
            (spx, spy, sp.angle, 0xC000, 0x5000, "fy<fx AND fx+fy>=1 (PJ-1 borrow + carry)"),
            (664, 291, 0x18000000, 0x5555, 0xC000, "sprite-overlap frame, fractional"),
            (1272, -724, 0x40000000, 0xC000, 0x5000, "stairs, fractional (va = exact 45x mult)"),
            (1869, 479, 0x80000000, 0x8000, 0x5555, "everything frame, fractional")]


def phase1b(fjm):
    """The bug class the whole certified set is blind to: a view position with a FRACTION.

    ⚠ This proves AGREEMENT, not absence. A frame is byte-exact when the two mirrors compute the
    same thing; PJ-1 and PJ-2 could still be latent at a viewpoint no fixture visits, because both
    need a boundary condition (a bbox corner within 1 unit of a wedge plane; a product whose low 16
    bits are nonzero) on top of the fraction. The PROOF that each is fixed is its probe
    (scratchpad/_pj1_probe.py, _pj2_probe.py), which drives the boundary directly and ships a
    two-sided control. This is the REGRESSION net under them."""
    print(chr(10) + "PHASE 1b -- FRACTIONAL viewpoints (the class every other gate is blind to)",
          flush=True)
    ok = True
    for vx, vy, va, fx, fy, why in FRAC_VPS:
        x16 = ((vx << 16) + fx) & 0xFFFFFFFF
        y16 = ((vy << 16) + fy) & 0xFFFFFFFF
        want = rm.render_wall_frame(SimState(x16, y16, va, "E1M1"), scene, **RENDER_KW, sky=True, near_steps=True, stack_steps=True, bbox_cull=True, degrade=True)
        scr, term = run(fjm, feed((_signed(x16, 32), _signed(y16, 32), va), 0,
                                  bindings=SPAWN_BINDINGS))
        same = bytes(scr.pixel_indices) == bytes(want)
        diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
        ok &= same
        print(f"  ({vx}+{fx:#06x},{vy}+{fy:#06x},{va:#010x}): {term.op_counter:,} ops  "
              f"{'BYTE-EXACT' if same else f'!! {diff} px DIFFER'}   {why}", flush=True)
    return ok


def phase1(fjm):
    """⚠ With --things this is also THE PIXEL-NEUTRALITY PROOF. Fed the SPAWN positions, the runtime
    table must reproduce the frames the baked blocks produced -- same pixels, same sprite slots. If
    it does, any divergence phase 2 finds belongs to the moving half and nowhere else."""
    ok = True
    print("\nPHASE 1 -- still (keys=0), against deg_gate's viewpoints", flush=True)
    for i, (vx, vy, va) in enumerate(VPS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene, **RENDER_KW, sky=True, near_steps=True, stack_steps=True, bbox_cull=True, degrade=True)
        scr, term = run(fjm, feed((vx << 16, vy << 16, va), 0,
                                  bindings=SPAWN_BINDINGS))
        same = bytes(scr.pixel_indices) == bytes(want)
        diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
        echoed = scr.state == (vx << 16, vy << 16, va)
        ok &= same and echoed
        if MOVING:
            # ⚠ THE CACHE CONTROL. A warm frame must be pixel-identical to a cold one, and the
            # bindings it echoes must equal the ones it was fed -- otherwise the cache is changing
            # what gets drawn, which is the one thing it must never do.
            cold, cterm = run(fjm, feed((vx << 16, vy << 16, va), 0, bindings=None))
            id_px = bytes(cold.pixel_indices) == bytes(scr.pixel_indices)
            id_bind = cold.bindings == SPAWN_BINDINGS and scr.bindings == SPAWN_BINDINGS
            ok &= id_px and id_bind
            print(f"    cold {cterm.op_counter:,} ops vs warm {term.op_counter:,} "
                  f"({term.op_counter - cterm.op_counter:+,})  "
                  f"{'SAME PIXELS' if id_px else '!! COLD AND WARM DIFFER'}  "
                  f"{'bindings agree' if id_bind else '!! BINDINGS WRONG'}", flush=True)
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
    leaf_changes = moved_frames = bind_errors = 0
    binds = None
    for tic in range(tics):
        keys = SCRIPT[tic % len(SCRIPT)]
        pos = thing_positions(tic) if MOVING else None
        if MOVING:
            # what the host hands back: last frame's echo, with everything it MOVED marked dirty
            if binds is None:
                binds = list(SPAWN_BINDINGS)
            for i in MOVERS:
                binds[RTPOS[i]] = BINDING_DIRTY
            # ⚠ THE CONTROL, and it is two-sided. Counting leaf changes alone would pass a build
            # that re-binds correctly and never draws the result; counting changed pixels alone
            # would pass one that moves sprites without re-binding them. Both must happen.
            leaf_changes += sum(rm.point_in_subsector(scene.cmap, x, y)
                                != rm.point_in_subsector(scene.cmap, sx, sy)
                                for (x, y), (sx, sy) in zip(pos, SPAWN_POS))
        scr, term = run(fjm, feed(state, keys, pos, binds))
        # the oracle takes the same tic, then renders from the state that tic produced
        _prev = SimState(want_state[0] & 0xFFFFFFFF, want_state[1] & 0xFFFFFFFF,
                         want_state[2], "E1M1")
        s = rm.step_sim(_prev, keys_dict(keys), scene=scene if COLLIDE else None)
        if COLLIDE:                      # did collision actually change this tic's outcome?
            _free = rm.step_sim(_prev, keys_dict(keys))
            blocked_tics += (_free.x, _free.y) != (s.x, s.y)
        want_state = (_signed(s.x, 32), _signed(s.y, 32), s.angle)
        want = rm.render_wall_frame(SimState(s.x, s.y, s.angle, "E1M1"), scene,
                                    thing_positions=pos, **RENDER_KW, sky=True, near_steps=True, stack_steps=True, bbox_cull=True, degrade=True)
        if MOVING:
            # ... and did the drift actually reach the SCREEN this tic? Same viewpoint, spawn
            # positions: if that renders identically, this tic proves nothing about moving things.
            _static = rm.render_wall_frame(SimState(s.x, s.y, s.angle, "E1M1"), scene, **RENDER_KW, sky=True, near_steps=True, stack_steps=True, bbox_cull=True, degrade=True)
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
        if MOVING:
            # ⚠ the echoed bindings must equal what the ORACLE derives from the same positions --
            # the independent check that makes a wrong cached binding impossible to hide
            want_b = [rm.point_in_subsector(scene.cmap, *pos[i]) for i in RT]
            if scr.bindings != want_b:
                bind_errors += 1
                n = sum(1 for a, b in zip(scr.bindings or [], want_b) if a != b)
                print(f"  !! {n} BINDINGS disagree with the oracle on tic {tic}")
                ok = False
            binds = list(scr.bindings)             # the relay, exactly as the host would do it
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


def phase3(fjm):
    """M14.5 §7b.4 — THE VISIBILITY CONTROL, and it must be TWO-SIDED.

    M14.5 has no pickup logic, so nothing in the gate's own play ever clears a flag: a build whose
    guard is never read, or read at the wrong nibble, would pass phases 1 and 2 unchanged. So hide
    every vanishable baked thing explicitly and require all three of:

      * fj and the oracle agree BYTE-EXACT with them hidden (the flag does the same thing on both
        sides -- not merely 'something changed');
      * the frame actually CHANGED at some viewpoint (or the things hidden were all off screen and
        the control proves nothing -- the mistake handoff-perf.md section 11.2 records);
      * it changes BACK when they are restored (a guard that hides permanently is not a guard).
    """
    print(f"\nPHASE 3 -- visibility: hiding all {len(VIS)} vanishable baked things", flush=True)
    if not VIS:
        print("  !! VACUOUS: no thing carries a flag")
        return False
    ok, changed = True, 0
    hide = list(VIS)
    for vx, vy, va in VPS:
        st = (vx << 16, vy << 16, va)
        shown, _ = run(fjm, feed(st, 0, bindings=SPAWN_BINDINGS))
        hid, term = run(fjm, feed(st, 0, bindings=SPAWN_BINDINGS, hidden=hide))
        back, _ = run(fjm, feed(st, 0, bindings=SPAWN_BINDINGS))
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    thing_hidden=hide, **RENDER_KW, sky=True, near_steps=True, stack_steps=True, bbox_cull=True, degrade=True)
        same = bytes(hid.pixel_indices) == bytes(want)
        moved = bytes(hid.pixel_indices) != bytes(shown.pixel_indices)
        restored = bytes(back.pixel_indices) == bytes(shown.pixel_indices)
        changed += moved
        ok &= same and restored
        print(f"  ({vx},{vy},{va:#x}): {term.op_counter:,} ops  "
              f"{'BYTE-EXACT vs oracle' if same else '!! HIDDEN FRAME DIFFERS FROM ORACLE'}  "
              f"{'frame changed' if moved else 'no visible change here'}  "
              f"{'restored' if restored else '!! DID NOT COME BACK'}", flush=True)
    if not changed:
        print("  !! VACUOUS: hiding them changed no pixel at any viewpoint -- the flag is untested")
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
                                scene, **RENDER_KW, sky=True, near_steps=True, stack_steps=True, bbox_cull=True, degrade=True)
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
    # ⚠ tics is POSITIONAL and may appear anywhere. It used to be read from sys.argv[1] only, so
    # `m14_gate.py --things 20` silently ran EIGHT tics -- the 20 was parsed as the flag's neighbour
    # and dropped. That matters because phase 2's --collide vacuity control needs enough tics to
    # actually reach a wall: the run reported "0 of 8 tics blocked" and FAILED, and the failure
    # looked like a collision bug rather than a mis-parsed argument.
    tics = next((int(a) for a in sys.argv[1:] if not a.startswith("-") and a.isdigit()), 8)
    fjm = build()
    ok = phase1(fjm)
    ok &= phase1b(fjm)          # CR-2026-08: the fractional class -- see FRAC_VPS
    ok &= phase2(fjm, tics)
    if MOVING:
        ok &= phase3(fjm)
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
