"""M2-R4 -- the fj door machine read back as a PROGRAM, not as text.

`doomfj/doorcode.py` is a hand transliteration of `doors.door_tic` and `doors.in_use_box_fixed`
into fj, and until this file nothing host-side compared the two: the only thing that ever ran the
emitted text was a 10-45 minute build gate. `tests/host/test_doorcode.py` covers the collision
address, the declarations and the use-key wire bits; it never executes a single emitted op, and
`_cross`, `_box_test` and the body of `door_tic_lines` are measured as entirely uncovered.

So this file pins five kinds of property, in descending order of what they would cost to find the
other way:

* THE MIRROR. A small interpreter of the nine-op vocabulary the emitter actually uses
  (`hex.if0/set/zero/xor_by/inc/dec/scmp`, `wflip`, `;label`) runs the emitted text frame by frame
  and must produce exactly the `(state, dir, sub, wait)` tuple `doors.door_tic` produces from the
  same key schedule -- for every (nstates, pass_state) shape the nine maps produce. A drift here is
  a door that is in a different place in the two mirrors, which is the failure this repo has
  already paid for three times.
* THE ONE BIT (the M2-R4 collision claim, "the same constant does both, because xor"). Seeded from
  the BAKED value (BLOCKING set) and toggled on every emitted `wflip`, a door line's blocking bit
  must be clear exactly on the frames where `state >= pass_state` -- through open, WAIT, close and
  a press that reverses a closing door. This is the half a picture gate cannot see: a door that
  animates open while staying solid looks perfect in every screenshot.
* THE TRIGGER BOX. The four `hex.scmp` compares must decide hit/miss identically to
  `doors.in_use_box_fixed`, including at the corners, one unit either side of them, and at negative
  map coordinates. `m5_gate` is CUMULATIVE, so a one-frame difference in when a door triggers parts
  the trajectory and every later frame differs.
* STATIC FACTS AN ASSEMBLER WOULD OTHERWISE FIND. Label closure (fj top-level labels are global, so
  a duplicate or a dangling one is an assembler error discovered minutes into a heavy build), cell
  offsets inside their declared vectors, op WIDTHS, and no reference to a cell `door_decls` does not
  declare. The width property needs its own textual test because the interpreter models registers
  as unbounded Python ints and therefore does NOT notice a `dwait` op narrowed from WAIT_NIBBLES
  nibbles to one -- which would wrap WAIT=32 at 16 and shut the door in the player's face.
* THE DEAD BRANCHES. `pass_state` 0, `pass_state >= nstates` and a caller that forgot to thread
  `lines` are unreachable from every fixture (all 13 E1M1 doors have pass_state 5 with 6..12
  states), so they could be deleted today without any existing test failing.

R9: the interpreter is a verification tool, so it ships negative controls --
`test_the_mirror_catches_a_broken_door_machine` mutates the emitted text four ways and requires
every one to be caught, and the width and label checks each mutate the text too. Honest limit: this
is an INTERPRETATION of the text, not an assembly of it. It cannot prove the program assembles, it
cannot count fj ops (the currency), and it cannot see nibble overflow. Those stay the build gate's.
"""
from __future__ import annotations

import collections
import random
import re

import pytest

from doomfj import doorcode, doors
from doomfj.doorcode import WAIT_NIBBLES, door_decls, door_tic_lines
from doomfj.doors import IDLE, SPEED, WAIT

E1M1_LITE = "tests/fixtures/e1m1_lite.wad"

# `dstate + 3*dw`, or a bare `duse`. The emitter writes exactly these two address forms.
_ADDR = re.compile(r"^([A-Za-z_]\w*)(?: \+ (\d+)\*dw)?$")

# The externs the door machine legitimately reads: the player's 16.16 position and the packed
# linedef table it patches. Everything else it names must come out of `door_decls`.
_EXTERNS = {"viewx", "viewy", "lnrow"}


# ---------------------------------------------------------------------------------------------
# The interpreter. Nine ops, because that is all `door_tic_lines` and `_box_test` emit -- an
# unknown op raises rather than being skipped, so a new op in the emitter fails here loudly instead
# of being quietly ignored by the mirror.
# ---------------------------------------------------------------------------------------------

def _cell(addr: str) -> str:
    """`dwait + 2*dw` -> `dwait2`: one register per (vector, offset) pair, which is what makes a
    stride bug (door d writing door d+1's slot) show up as a state divergence."""
    m = _ADDR.match(addr)
    assert m, f"unparseable address {addr!r}"
    return f"{m.group(1)}{m.group(2) or 0}"


def _signed(v: int, nibbles: int) -> int:
    """How `hex.scmp n` reads its operand: two's complement over 4*n bits. The whole point of
    `_box_test`'s `& 0xFFFFFFFF` is that this is the inverse of it."""
    bits = 4 * nibbles
    return v - (1 << bits) if v >> (bits - 1) else v


def _load(lines):
    """Strip comments and labels; return (label -> op index, ops)."""
    labels, prog = {}, []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        if s.endswith(":") and " " not in s:
            assert s[:-1] not in labels, f"duplicate label {s[:-1]}"
            labels[s[:-1]] = len(prog)
            continue
        prog.append(s)
    return labels, prog


def _run(labels, prog, regs, flips):
    """One frame: execute from the top until control falls off the end. Returns the executed ops as
    (head, raw text), so a test can assert about STRUCTURE -- how many compares an idle door pays --
    and not only about the state it lands in."""
    pc = 0
    executed = []
    while pc < len(prog):
        s = prog[pc]
        pc += 1
        if len(executed) > 40000:
            raise AssertionError("runaway: the emitted text has a cycle")
        if s.startswith(";"):
            tgt = s[1:].strip()
            executed.append((";", tgt))
            pc = labels[tgt]
            continue
        head, rest = s.split(" ", 1)
        a = [x.strip() for x in rest.split(",")]
        executed.append((head, s))
        if head == "hex.if0":
            if regs[_cell(a[1])] == 0:
                pc = labels[a[2]]
        elif head == "hex.set":
            regs[_cell(a[1])] = int(a[2], 0)
        elif head == "hex.zero":
            regs[_cell(a[1])] = 0
        elif head == "hex.xor_by":
            regs[_cell(a[1])] ^= int(a[2], 0)
        elif head == "hex.inc":
            regs[_cell(a[1])] += 1
        elif head == "hex.dec":
            regs[_cell(a[1])] -= 1
        elif head == "hex.scmp":
            n = int(a[0])
            av, bv = regs[_cell(a[1])], _signed(regs[_cell(a[2])], n)
            pc = labels[a[3] if av < bv else (a[4] if av == bv else a[5])]
        elif head == "wflip":
            flips.append(a[0])
        else:
            raise AssertionError(f"the interpreter does not model {head!r}: {s}")
    return executed


def _fresh(ndoors: int) -> dict:
    """The registers as `door_decls` bakes them: every door shut, idle, no timers."""
    r = {"duse0": 0, "dbox0": 0, "viewx0": 0, "viewy0": 0}
    for d in range(ndoors):
        r[f"dstate{d}"] = r[f"ddir{d}"] = r[f"dsub{d}"] = 0
        r[f"dwait{WAIT_NIBBLES * d}"] = 0
    return r


def _tuple_of(regs, d: int) -> tuple:
    return (regs[f"dstate{d}"], regs[f"ddir{d}"], regs[f"dsub{d}"],
            regs[f"dwait{WAIT_NIBBLES * d}"])


def _flip_addresses(lis):
    """`{wflip operand: linedef}` for a door's lines, built with the emitter's OWN helper so the
    mapping cannot drift from the text being interpreted."""
    out = {}
    for li, ln in zip(lis, doorcode._unblock_lines(lis)):
        out[ln.strip().split(" ", 1)[1].split(",")[0].strip()] = li
    assert len(out) == len(lis)
    return out


# ---------------------------------------------------------------------------------------------
# Key schedules. THE SILENT STRETCH IS LOAD-BEARING: `door_tic` only ever closes a door that has
# been left alone for WAIT frames, and the use key is level-triggered (see doorcode's header), so a
# press-heavy random schedule re-opens the door every few frames and never exercises the closing
# path at all -- which is exactly where the `shuts` crossing and the `_shut` -> IDLE branch live.
# ---------------------------------------------------------------------------------------------

def _centre(box):
    x0, y0, x1, y1 = box
    return ((x0 + x1) // 2, (y0 + y1) // 2)


def _schedules(box, frames=150):
    """[(name, [(pressed, x, y), ...])] -- deterministic first, then two seeded ones."""
    cx, cy = _centre(box)
    out = [("one tap then silence", [(f == 0, cx, cy) for f in range(frames)])]

    # A press during WAIT restarts it; a press at 60 lands on a CLOSING door for the wide shapes
    # (11 steps up + WAIT=32 -> closing from ~43) and on a shut one for the narrow ones.
    out.append(("hold, silence, re-press",
                [(f < 4 or 60 <= f < 62, cx, cy) for f in range(frames)]))

    rng = random.Random(20260911)
    out.append(("noisy, then 90 quiet frames",
                [((f < 30 or f >= 120) and rng.random() < 0.25, cx, cy) for f in range(frames)]))

    # ...and the same with the player wandering in and out of the box, so `used` is the AND of the
    # key and the box test and a miscompiled corner shows up as a state divergence.
    rng = random.Random(7)
    x0, y0, x1, y1 = box
    out.append(("wandering in and out of the box",
                [((f < 30 or f >= 120) and rng.random() < 0.35,
                  rng.randint(x0 - 3, x1 + 3), rng.randint(y0 - 3, y1 + 3))
                 for f in range(frames)]))
    return out


def _first_divergence(lines, nstates, pw, box, lis, schedule, track_bit=True):
    """Step the emitted text and `doors.door_tic` together. Returns a description of the first frame
    they disagree on, or None.

    `track_bit=False` watches ONLY the (state, dir, sub, wait) tuple, so the state mirror and the
    collision mirror stay separable -- a threshold moved on the `shuts` crossing corrupts no state
    at all (`_cross` restores `dstate` on both arms by construction) and must be reported as the
    collision failure it is, not as a state failure.

    The bit is seeded to True, THE BAKED VALUE, rather than starting to watch at the first observed
    flip: the whole up-crossing window (shut..pass_state) is before that flip, so a harness that
    starts there silently cannot see a door that opens its doorway early."""
    labels, prog = _load(lines)
    addr_of = _flip_addresses(lis) if lis else {}
    regs = _fresh(1)
    py = (0, IDLE, 0, 0)
    bits = {li: True for li in lis}
    patched = track_bit and bool(lis) and pw is not None and 0 < pw < nstates
    for f, (pressed, x, y) in enumerate(schedule):
        regs["duse0"] = 1 if pressed else 0
        regs["viewx0"], regs["viewy0"] = x << 16, y << 16
        flips = []
        _run(labels, prog, regs, flips)
        used = bool(pressed) and doors.in_use_box_fixed(box, x << 16, y << 16)
        py = doors.door_tic(py, nstates, used)
        got = _tuple_of(regs, 0)
        if got != py:
            return (f"frame {f}: fj (state,dir,sub,wait)={got} but door_tic={py} "
                    f"(nstates={nstates} pass_state={pw} pressed={pressed} at {x},{y})")
        if patched:
            for tgt in flips:
                assert tgt in addr_of, f"frame {f}: wflip at {tgt} hits no door line"
                bits[addr_of[tgt]] = not bits[addr_of[tgt]]
            want = py[0] < pw
            bad = {li: b for li, b in bits.items() if b != want}
            if bad:
                return (f"frame {f}: state={py[0]} pass_state={pw} so blocking should be {want}, "
                        f"but lines {bad} disagree")
    return None


# ---------------------------------------------------------------------------------------------
# Synthetic door shapes. The nine E1 maps produce 6..12 states with pass_state 5; these bracket
# that and add the edge shapes (a two-state door, a door passable at state 1).
# ---------------------------------------------------------------------------------------------

SHAPES = [(6, 3), (6, 1), (6, 5), (12, 5), (2, 1), (7, 5), (11, 5)]
BOX = (-10, -20, 30, 40)
LIS = [5, 9]
SECTOR = 7          # an arbitrary sector id, deliberately NOT the slot index (which is 0)


def _emit(n, pw, box=BOX, lis=LIS):
    return door_tic_lines([SECTOR], {SECTOR: n}, {SECTOR: box},
                          {} if pw is None else {SECTOR: pw},
                          {} if lis is None else {SECTOR: lis})


@pytest.fixture(scope="module")
def e1m1():
    """The real 13 doors. `e1m1_lite.wad` carries the same doors as the full fixture and the whole
    door pipeline on it runs in well under a tenth of a second."""
    from doomfj.mapcompiler import bake_bsp
    from doomfj.wad import WadFile
    w = WadFile.from_path(E1M1_LITE)
    secs, lds, sds = w.sectors("E1M1"), w.linedefs("E1M1"), w.sidedefs("E1M1")
    verts = bake_bsp(w, "E1M1").vertexes
    dst = doors.door_states(secs, lds, sds)
    slots = sorted(dst)
    nstates = {si: len(v) for si, v in dst.items()}
    boxes = doors.use_boxes_xy(secs, lds, sds, verts)
    passes = {si: doors.pass_state(secs, lds, sds, si) for si in dst}
    dlines = doorcode.door_line_ids(secs, lds, sds, dst)
    return dict(slots=slots, nstates=nstates, boxes=boxes, passes=passes, lines=dlines,
                text=door_tic_lines(slots, nstates, boxes, passes, dlines))


# ---------------------------------------------------------------------------------------------
# 1. THE MIRROR
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("n,pw", SHAPES)
def test_the_emitted_tic_walks_the_same_state_machine_as_door_tic(n, pw):
    """`door_tic` is the specification and this text is the only place it is written twice. Nothing
    host-side compared them before; the fj half's only reader was a multi-minute build gate, so a
    transliteration slip cost a build to find and a build to confirm the fix.

    STATE ONLY -- the collision bit is the next test's subject, so the two report separately."""
    lines = _emit(n, pw)
    for name, sched in _schedules(BOX):
        bad = _first_divergence(lines, n, pw, BOX, LIS, sched, track_bit=False)
        assert bad is None, f"[{name}] {bad}"


@pytest.mark.parametrize("n,pw", SHAPES)
def test_the_blocking_bit_is_clear_exactly_while_the_door_is_passable(n, pw):
    """M2-R4's claim in full: one bit, toggled on two frames of the animation, and `state >=
    pass_state` on every frame in between -- including on a press that REVERSES a closing door,
    which is the path where the two crossings can fire in the wrong order.

    A door that animates open while staying solid, or that opens its doorway one state early, is
    invisible to every picture gate: the pixels are identical either way."""
    lines = _emit(n, pw)
    for name, sched in _schedules(BOX):
        bad = _first_divergence(lines, n, pw, BOX, LIS, sched)
        assert bad is None, f"[{name}] {bad}"


def test_thirteen_real_doors_step_independently_in_one_emitted_frame(e1m1):
    """The synthetic cases run one door; the shipped text runs thirteen back to back out of one
    `duse`. Pressing inside door 0's box must move door 0 and NOTHING else -- the property a
    slot-index bug (`si` where the label prefix or the vector offset wants `d`) breaks."""
    labels, prog = _load(e1m1["text"])
    slots = e1m1["slots"]
    regs = _fresh(len(slots))
    boxes = [e1m1["boxes"][si] for si in slots]
    cx, cy = _centre(boxes[0])
    inside = [d for d, b in enumerate(boxes) if doors.in_use_box(b, cx, cy)]
    assert inside == [0], f"the probe point is inside doors {inside}, not door 0 alone"
    py = [(0, IDLE, 0, 0)] * len(slots)
    for f in range(110):
        regs["duse0"] = 1 if f == 0 else 0
        regs["viewx0"], regs["viewy0"] = cx << 16, cy << 16
        _run(labels, prog, regs, [])
        for d, si in enumerate(slots):
            py[d] = doors.door_tic(py[d], e1m1["nstates"][si], f == 0 and d == 0)
            assert _tuple_of(regs, d) == py[d], (
                f"frame {f}, door {d} (sector {si}): fj={_tuple_of(regs, d)} door_tic={py[d]}")
    assert py[0] == (0, IDLE, SPEED, 0), "the tap never ran a full open/WAIT/close cycle"
    assert all(t == (0, IDLE, 0, 0) for t in py[1:]), "a door moved that was never pressed"


def test_the_mirror_catches_a_broken_door_machine():
    """R9 -- the negative control for everything above. Four mutations of the emitted text, each a
    defect a careless edit to `door_tic_lines` would actually produce, and every one must be caught.
    Each mutation asserts the exact line it replaces, so a change to the emitter's text breaks this
    test loudly instead of silently mutating nothing and reporting a clean pass."""
    n, pw = 6, 3
    base = _emit(n, pw)
    st = "dstate + 0*dw"

    def cross_threshold(lines, tag, old, new):
        """The `_cross` idiom xors the threshold in three times; move all three together, which is
        what a wrong `pw`/`pw-1` does -- the door then opens (or re-solidifies) a state early."""
        out = list(lines)
        i = out.index(f"    hex.if0 1, {st}, dr0_{tag}")
        for j in (i - 1, i + 1, out.index(f"  dr0_{tag}:") + 1):
            assert out[j] == f"    hex.xor_by 1, {st}, {old}", out[j]
            out[j] = f"    hex.xor_by 1, {st}, {new}"
        return out

    def drop_after(lines, label, expect):
        out = list(lines)
        i = out.index(label) + 1
        assert out[i] == expect, out[i]
        del out[i]
        return out

    def swap_x0_arms(lines):
        old = "    hex.scmp 8, viewx, dbox, dr0_moved, dub0_0, dub0_0"
        new = "    hex.scmp 8, viewx, dbox, dub0_0, dub0_0, dr0_moved"
        assert old in lines
        return [new if ln == old else ln for ln in lines]

    # `by` is which half MUST see it: "bit" means the state machine is untouched and only the
    # collision mirror can tell -- which is precisely the class of defect a picture gate is blind
    # to, so it is worth stating rather than letting "something failed" stand in for it.
    mutants = [
        # the doorway opens one state early -- animation identical, collision wrong
        ("opens threshold pw -> pw+1", "bit", cross_threshold(base, "opens", pw, pw + 1)),
        # ...and the down-crossing: the door is still solid on its way back to shut
        ("shuts threshold pw-1 -> pw", "bit", cross_threshold(base, "shuts", pw - 1, pw)),
        # the restoring xor inside the taken branch: dstate is left corrupted to 0, so the
        # renderer's switch dispatches this door to the wrong height
        ("opens cross loses its restoring xor", "state",
         drop_after(base, "  dr0_opens:", f"    hex.xor_by 1, {st}, {pw}")),
        # `>=` becomes `<=` on one corner: the two mirrors trigger on different frames
        ("x0 compare lt/gt swapped", "state", swap_x0_arms(base)),
        # dsub is never reloaded, so after the first step the door runs a state every frame forever
        ("step forgets to reload dsub", "state",
         drop_after(base, "  dr0_step:", f"    hex.set 1, dsub + 0*dw, {SPEED}")),
    ]
    for name, by, lines in mutants:
        assert lines != base, f"{name} mutated nothing"
        state_saw = any(_first_divergence(lines, n, pw, BOX, LIS, s, track_bit=False)
                        for _nm, s in _schedules(BOX))
        bit_saw = any(_first_divergence(lines, n, pw, BOX, LIS, s)
                      for _nm, s in _schedules(BOX))
        assert bit_saw, f"NOT CAUGHT AT ALL: {name} -- the mirror proves nothing"
        if by == "state":
            assert state_saw, f"{name} should be a state divergence and is not"
        else:
            assert not state_saw, (
                f"{name} moved the state machine too -- it is no longer the collision-only "
                f"control this test needs it to be")


# ---------------------------------------------------------------------------------------------
# 2. THE TRIGGER BOX
# ---------------------------------------------------------------------------------------------

def _box_decision(lines, x, y):
    """Run only the trigger half: with `duse` set, does control reach `dr0_press`?"""
    labels, prog = _load(lines)
    regs = _fresh(1)
    regs["duse0"] = 1
    regs["viewx0"], regs["viewy0"] = x << 16, y << 16
    return any(kind == ";" and text == "dr0_press" for kind, text in _run(labels, prog, regs, []))


@pytest.mark.parametrize("box", [(-10, -20, 30, 40), (0, 0, 1, 1), (-300, -400, -290, -390)])
def test_the_four_compares_decide_the_same_box_as_in_use_box_fixed(box):
    """`hex.scmp n, a, b, lt, eq, gt` takes its arms in that order and `_box_test` writes two
    different triples (`miss, tag, tag` for >=, `tag, tag, miss` for <=). Swapping one, or turning
    an inclusive edge exclusive, makes the two mirrors trigger on different frames -- and `m5_gate`
    is cumulative, so one frame of difference parts the trajectory and every later frame differs.

    Negative coordinates are in the grid on purpose: the corners are masked `& 0xFFFFFFFF` and read
    back by a SIGNED 8-nibble compare, so that is where the two's complement round trip has to
    hold."""
    lines = _emit(6, 3, box=box)
    x0, y0, x1, y1 = box
    xs = sorted({x0 - 1, x0, x0 + 1, (x0 + x1) // 2, x1 - 1, x1, x1 + 1, 0, -1})
    ys = sorted({y0 - 1, y0, y0 + 1, (y0 + y1) // 2, y1 - 1, y1, y1 + 1, 0, -1})
    checked = 0
    for x in xs:
        for y in ys:
            want = doors.in_use_box_fixed(box, x << 16, y << 16)
            assert _box_decision(lines, x, y) is want, (
                f"box={box} point=({x},{y}): the emitted compares say {not want}, "
                f"in_use_box_fixed says {want}")
            checked += 1
    assert checked == len(xs) * len(ys) >= 16   # a 1x1 box collapses the grid to 4x4
    # the grid has to contain both answers, or "they agree" is vacuous
    outcomes = {doors.in_use_box_fixed(box, x << 16, y << 16) for x in xs for y in ys}
    assert outcomes == {True, False}, f"box={box}: the grid is entirely {outcomes}"


def test_an_idle_door_runs_no_compare_and_a_miss_exits_on_the_first_failing_corner(e1m1):
    """The structure the cost comment claims: the four signed 32-bit compares sit BEHIND the use
    key, so thirteen idle doors are three interpreted ops each and not eleven. A reordering that
    made the trigger unconditional paints identical pixels and would surface only as op-count drift
    in a build. Honest rating: a structure guard, not a budget guard -- the absolute saving is small
    against a 20M ops/frame budget."""
    labels, prog = _load(e1m1["text"])
    ndoors = len(e1m1["slots"])

    regs = _fresh(ndoors)
    regs["duse0"] = 0
    ops = _run(labels, prog, regs, [])
    assert not [o for o in ops if o[0] == "hex.scmp"], "an idle door ran a box compare"
    assert not [o for o in ops if o[0] == "hex.set" and "8, dbox," in o[1]], \
        "an idle door loaded a box constant"
    assert len(ops) == 3 * ndoors, \
        f"an idle door costs {len(ops) / ndoors} interpreted ops, not the 3 the comment claims"

    # ...and a press far to the west of every box gives up after the FIRST compare of each door.
    regs = _fresh(ndoors)
    regs["duse0"] = 1
    regs["viewx0"], regs["viewy0"] = -1_000_000 << 16, 0
    ops = _run(labels, prog, regs, [])
    assert len([o for o in ops if o[0] == "hex.scmp"]) == ndoors, \
        "an out-of-box press ran more than one compare per door"


def test_every_baked_box_constant_is_its_corner_shifted_and_fits_signed_32(e1m1):
    """The corners are masked `& 0xFFFFFFFF` and compared as SIGNED 8 nibbles, so the mask must be
    exactly two's complement; and a map whose inflated corner passed 32767 would wrap to a huge
    negative and INVERT the trigger box. Nothing else in the repo would say so, and M4's nine levels
    are 14.8x E1M1 -- this test is the thing that speaks up when a bigger map loses the margin."""
    pairs, pending = [], None
    for ln in e1m1["text"]:
        s = ln.strip()
        if s.startswith("hex.set 8, dbox,"):
            pending = int(s.split(",")[2], 0)
        elif s.startswith("hex.scmp 8,"):
            assert pending is not None, f"a compare with no constant loaded: {s}"
            a = [x.strip() for x in s.split(" ", 1)[1].split(",")]
            pairs.append((a[1], a[4], pending))     # (viewx|viewy, the dub<d>_<k> arm, constant)
            pending = None
    assert len(pairs) == 4 * len(e1m1["slots"]), f"{len(pairs)} compares, want 4 per door"
    for reg, tag, raw in pairs:
        m = re.fullmatch(r"dub(\d+)_(\d+)", tag)
        assert m, f"the eq arm {tag!r} is not this corner's own label"
        d, k = int(m.group(1)), int(m.group(2))
        box = e1m1["boxes"][e1m1["slots"][d]]
        assert reg == ("viewx" if k < 2 else "viewy"), f"{tag} compares the wrong axis"
        want = box[(0, 2, 1, 3)[k]]                 # emission order is x0, x1, y0, y1
        assert 0 <= raw <= 0xFFFFFFFF, f"{tag} constant {raw:#x} is not 8 nibbles"
        assert _signed(raw, 8) == want << 16, (
            f"{tag}: baked {_signed(raw, 8)} but the corner is {want} << 16 = {want << 16}")
        assert -(1 << 31) <= want << 16 < (1 << 31), (
            f"{tag}: corner {want} does not fit signed 32 bits once shifted -- this map's trigger "
            f"box would invert")
    assert any(_signed(raw, 8) < 0 for _r, _t, raw in pairs), \
        "no negative corner on this map, so the two's complement half of this test is vacuous"


# ---------------------------------------------------------------------------------------------
# 3. STATIC FACTS AN ASSEMBLER WOULD OTHERWISE FIND, MINUTES INTO A BUILD
# ---------------------------------------------------------------------------------------------

def _label_report(lines):
    """(how often each label is DEFINED, how often each is a jump TARGET, unreachable op indexes)."""
    defined = collections.Counter()
    labels, prog = {}, []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        if s.endswith(":") and " " not in s:
            defined[s[:-1]] += 1
            labels.setdefault(s[:-1], len(prog))
            continue
        prog.append(s)

    targets = collections.Counter()
    succ = {}
    for j, s in enumerate(prog):
        if s.startswith(";"):
            t = s[1:].strip()
            targets[t] += 1
            succ[j] = ([t], False)
            continue
        head, rest = s.split(" ", 1)
        a = [x.strip() for x in rest.split(",")]
        if head == "hex.if0":
            targets[a[2]] += 1
            succ[j] = ([a[2]], True)
        elif head == "hex.scmp":
            for t in a[3:6]:
                targets[t] += 1
            succ[j] = (list(a[3:6]), False)
        else:
            succ[j] = ([], True)

    seen, stack = set(), [0]
    while stack:
        j = stack.pop()
        if j in seen or j >= len(prog):
            continue
        seen.add(j)
        tgts, falls = succ[j]
        stack += [labels[t] for t in tgts if t in labels]
        if falls:
            stack.append(j + 1)
    return defined, targets, sorted(set(range(len(prog))) - seen)


def test_every_jump_target_is_defined_once_and_nothing_is_orphaned(e1m1):
    """fj top-level labels are GLOBAL. A duplicate or a dangling one is an assembler error found
    10-45 minutes into a heavy build, and the obvious way to make one is a slot-index bug -- using
    the sector id `si` where the label prefix wants the slot `d`. An orphan is the same bug seen
    from the other side: a label defined in text that no branch can reach."""
    defined, targets, unreachable = _label_report(e1m1["text"])
    assert [k for k, v in defined.items() if v > 1] == [], "a label is defined twice"
    assert sorted(set(targets) - set(defined)) == [], "a jump names a label nothing defines"
    assert sorted(set(defined) - set(targets)) == [], "a label is defined and never jumped to"
    assert unreachable == [], f"ops {unreachable[:5]} cannot be reached from the top of the frame"
    # ...and it really did walk every door's labels: each label belongs to a slot that exists, and
    # every slot has some. (A count would only restate the emitter; this says what the count is
    # FOR -- that `dr13_*` on a 13-door map, the slot-index bug, has nowhere to hide.)
    slots = {int(re.match(r"(?:dr|dub)(\d+)", k).group(1)) for k in defined}
    assert slots == set(range(len(e1m1["slots"]))), \
        f"labels name slots {sorted(slots)} for {len(e1m1['slots'])} doors"


def test_a_slot_index_collision_would_be_caught_by_the_label_check(e1m1):
    """R9 for the check above: give two doors the same label prefix -- what emitting `dr{si}_` for
    one door and `dr{d}_` for another does -- and it must report the duplicate."""
    hacked = [ln.replace("dr1_", "dr0_") for ln in e1m1["text"]]
    assert hacked != list(e1m1["text"]), "the mutation changed nothing"
    defined, _targets, _unreachable = _label_report(hacked)
    assert [k for k, v in defined.items() if v > 1], "the label check cannot see a duplicate"


def _ops(lines):
    """(head, width, [addresses], raw) for every emitted op; comments and labels dropped."""
    out = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("//") or s.startswith(";") or (s.endswith(":") and " " not in s):
            continue
        head, rest = s.split(" ", 1)
        a = [x.strip() for x in rest.split(",")]
        if head == "wflip":
            out.append((head, None, [], s))
            continue
        out.append((head, int(a[0]), [a[1]] if head != "hex.scmp" else [a[1], a[2]], s))
    return out


_WANT_WIDTH = {"duse": 1, "dbox": 8, "viewx": 8, "viewy": 8,
               "dstate": 1, "ddir": 1, "dsub": 1, "dwait": WAIT_NIBBLES}


def _width_violations(lines):
    return [raw for _h, width, addrs, raw in _ops(lines)
            for ad in addrs
            if width != _WANT_WIDTH.get(_ADDR.match(ad).group(1), width)]


def test_every_op_addresses_its_cell_at_the_declared_width(e1m1):
    """WAIT=32 does not fit one nibble, so a `hex.dec 1, dwait` wraps at 16 and the door shuts in
    the player's face -- the failure the WAIT comment in `doors.py` records having already been paid
    for once.

    This needs its OWN textual test: the interpreter above models registers as unbounded Python
    ints, so narrowing every `dwait` op passes the whole mirror untouched (asserted below). Only the
    text says how wide an op is."""
    assert _width_violations(e1m1["text"]) == []
    seen = {_ADDR.match(ad).group(1) for _h, _w, addrs, _r in _ops(e1m1["text"]) for ad in addrs}
    assert seen == set(_WANT_WIDTH), f"the text never addressed {sorted(set(_WANT_WIDTH) - seen)}"
    # and the widths are what make the counters big enough for the constants they hold
    assert WAIT < 1 << (4 * WAIT_NIBBLES) and 0 < SPEED < 16


def test_a_narrowed_wait_counter_is_caught_by_the_width_check_and_only_by_it(e1m1):
    """R9 for the check above, and the reason it has to exist as its own test: the same mutation is
    invisible to the interpreter, so without the textual width check nothing host-side sees `dwait`
    lose a nibble. If the second half of this test ever fails, the interpreter grew width semantics
    and this file's claim about what it cannot see needs rewriting -- not deleting."""
    def narrow(lines):
        out = []
        for ln in lines:
            for op in ("if0", "dec", "zero", "set"):
                ln = ln.replace(f"hex.{op} {WAIT_NIBBLES}, dwait", f"hex.{op} 1, dwait")
            out.append(ln)
        return out

    narrowed = narrow(e1m1["text"])
    assert narrowed != list(e1m1["text"]), "the mutation changed nothing"
    assert _width_violations(narrowed), "the width check cannot see a narrowed dwait"
    # ...and the mirror is INDIFFERENT to it -- stated as "narrowing changes nothing the
    # interpreter sees", so this half stays true (and keeps saying what it means) even when some
    # other defect is making the mirror report a divergence of its own.
    lines, sched = _emit(6, 3), _schedules(BOX)[0][1]
    assert _first_divergence(narrow(lines), 6, 3, BOX, LIS, sched) == \
        _first_divergence(lines, 6, 3, BOX, LIS, sched), (
        "narrowing dwait changed what the interpreter sees: it grew width semantics, so this "
        "file's claim about what only the textual check can catch needs rewriting, not deleting")


def test_every_cell_offset_lies_inside_the_vector_door_decls_declares(e1m1):
    """`dstate`/`ddir`/`dsub` stride by 1 but `dwait` strides by WAIT_NIBBLES, and the stride is
    written independently in `door_decls` and in `door_tic_lines` -- the exact fan-out hazard rule 5
    names. If WAIT_NIBBLES moved in one place only, door d's wait counter would alias door d+1's and
    a door would close because its NEIGHBOUR's timer expired, which no still picture shows."""
    ndoors = len(e1m1["slots"])
    sizes = {d.split(":")[0]: int(d.split()[2].rstrip(",")) for d in door_decls(ndoors)}
    used = collections.defaultdict(set)
    for _head, width, addrs, raw in _ops(e1m1["text"]):
        for ad in addrs:
            m = _ADDR.match(ad)
            name, off = m.group(1), int(m.group(2) or 0)
            if name in _EXTERNS:
                continue
            assert name in sizes, f"{raw} addresses undeclared cell {name}"
            assert 0 <= off < sizes[name], (
                f"{raw}: offset {off} is outside `{name}: hex.vec {sizes[name]}`")
            assert off + width <= sizes[name], (
                f"{raw}: a {width}-nibble op at offset {off} runs off `{name}` ({sizes[name]})")
            used[name].add(off)
    for name in ("dstate", "ddir", "dsub"):
        assert sorted(used[name]) == list(range(ndoors)), \
            f"{name} slots are {sorted(used[name])}, not one per door"
    assert sorted(used["dwait"]) == [WAIT_NIBBLES * d for d in range(ndoors)], \
        "dwait slots are not WAIT_NIBBLES apart -- door d's timer aliases door d+1's"


def test_the_text_names_no_cell_the_declarations_do_not(e1m1):
    """A typo'd or renamed cell is a static fact that costs milliseconds to find here and a failed
    multi-minute assembly to find otherwise -- the argument `tests/host/test_no_undefined_names.py`
    makes for Python names, which never looks at emitted fj text. Rule 4 freezes these names, so
    this pins the emitter ABI too."""
    declared = {d.split(":")[0] for d in door_decls(len(e1m1["slots"]))}
    named = set()
    for head, _w, addrs, raw in _ops(e1m1["text"]):
        named |= {_ADDR.match(ad).group(1) for ad in addrs}
        if head == "wflip":
            m = re.fullmatch(r"wflip (\w+) \+ \d+\*dw \+ w, 0x[0-9a-fA-F]+\*dw", raw)
            assert m, f"a wflip the ABI does not recognise: {raw}"
            named.add(m.group(1))
    assert named - declared == _EXTERNS, (
        f"the text reads {sorted(named - declared - _EXTERNS)}, which nothing declares")
    assert declared <= named, f"declared but never addressed: {sorted(declared - named)}"


# ---------------------------------------------------------------------------------------------
# 4. THE DEAD BRANCHES -- unreachable from every fixture, so nothing else pins them
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("pw,why", [
    (0, "passable even when shut"),
    (6, "pass_state == nstates, i.e. never passable"),
    (9, "pass_state past the last state"),
    (None, "no entry in `passes` at all"),
])
def test_a_door_that_never_crosses_its_threshold_emits_no_collision_patch(pw, why):
    """`if not pw or pw >= n` is dead in every existing test -- all 13 E1M1 doors have pass_state 5
    with 6..12 states -- and could be deleted today without one failing. Emitting a crossing for a
    door that is passable even when shut would toggle a bit that is ALREADY correct, turning an open
    doorway solid; emitting only one of the two leaves the bit stuck after a single cycle."""
    lines = _emit(6, pw)
    assert not [ln for ln in lines if "wflip" in ln], f"a door {why} emitted a collision patch"
    assert not [ln for ln in lines if "_opens" in ln or "_shuts" in ln], \
        f"a door {why} emitted a crossing test"
    # ...and it still runs the state machine: only the collision half is dropped.
    assert _first_divergence(lines, 6, pw, BOX, LIS, _schedules(BOX)[0][1]) is None


def test_a_caller_that_forgets_to_thread_lines_emits_no_collision_patch_either():
    """`lines=None` is a DEFAULT, so a caller that forgot the argument gets a door that animates
    perfectly and never stops being a wall -- exactly the shape of the M4 per-map fan-out edit.
    Pinned so the silence is documented behaviour rather than an accident nobody has looked at."""
    assert not [ln for ln in _emit(6, 3, lis=None) if "wflip" in ln]
    assert [ln for ln in _emit(6, 3) if "wflip" in ln], "the control case emits nothing either"


@pytest.mark.parametrize("n,pw", [(6, 3), (12, 5), (2, 1)])
def test_an_in_range_threshold_emits_exactly_two_flips_per_line(n, pw):
    """One on the `opens` crossing and one on the `shuts` crossing. One flip leaves the bit stuck
    after a single cycle; three leaves it inverted. And both crossings must flip the SAME addresses,
    which is the "one constant does both, because xor" claim in one line."""
    flips = [ln for ln in _emit(n, pw) if "wflip" in ln]
    assert len(flips) == 2 * len(LIS)
    assert len(set(flips)) == len(LIS), "the two crossings flip different addresses"


# ---------------------------------------------------------------------------------------------
# 5. `door_line_ids` -- the two branches no wad reaches
# ---------------------------------------------------------------------------------------------

class _LD:
    def __init__(self, front, back):
        self.front, self.back = front, back


class _SD:
    def __init__(self, sector):
        self.sector = sector


@pytest.mark.parametrize("back", [-1, 0xFFFF, 2, 99])
def test_a_one_sided_line_is_never_listed_under_any_sentinel(back):
    """A listed one-sided line means `_unblock_lines` emits a wflip that clears FLAG_BLOCKING on a
    door's solid TRACK wall -- a hole in the map the player walks through. The line's FRONT sidedef
    belongs to the door here, which is the case a front-only guard would let through.

    Honest caveat: `WadFile` parses sidedefs as signed shorts, so every real wad yields -1 and the
    0xFFFF clause is subsumed by the `>= len(sds)` guard. This pins the STATED contract -- and would
    catch a reader switched to unsigned -- not a currently live path."""
    sds = [_SD(40), _SD(41)]                       # len 2, so back=2 and back=99 are past the table
    assert doorcode.door_line_ids(None, [_LD(0, back)], sds, {40}) == {}, \
        f"back={back} was treated as a real sidedef"


def test_a_line_with_the_same_door_sector_on_both_sides_is_listed_once():
    """Without the `li not in out.get(si, ())` guard the id is listed twice, `_unblock_lines` emits
    the same wflip twice, the two toggles CANCEL, and the door animates open while staying solid
    forever -- invisible to every picture gate and findable only by walking into it in a multi-minute
    playthrough gate. No fixture reaches it: E1M1 has 7 same-sector linedefs and none is a door."""
    assert doorcode.door_line_ids(None, [_LD(0, 1)], [_SD(40), _SD(40)], {40}) == {40: [0]}
    # the ordinary case still lists one line under BOTH of its door sectors
    assert doorcode.door_line_ids(None, [_LD(0, 1)], [_SD(40), _SD(41)], {40, 41}) == \
        {40: [0], 41: [0]}


def test_the_dedupe_is_what_keeps_it_to_one_entry():
    """R9 for the test above: the single entry is only evidence of a dedupe if a sector CAN collect
    more than one line. Two distinct linedefs on the same door sector must give two entries."""
    assert doorcode.door_line_ids(None, [_LD(0, 1), _LD(1, 0)], [_SD(40), _SD(41)], {40}) == \
        {40: [0, 1]}
