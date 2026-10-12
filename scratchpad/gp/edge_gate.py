"""P10 G2 + G8 + G1 + G3 -- the EDGE gate: the visual tier, byte-exact against the oracle at viewpoints that put a near
floor or ceiling edge OFF the screen (G2: the column BASES, frame.ts_base_store / lines_steps_load2 /
lines_col_plane_ids), a sky region behind a stacked piece (G8: frame.lines_piece_sky / lines_region_ids_c) and a
sprite behind a nearer ledge (G1: frame.rec_clip_read, stream.frag_clip / frag_clamp / frag_runs_cut) and three
sprites in one column (G3: the third fragment slot, frame.thing_record_body / lines_spr_load, stream.emit_region_c),
P11's EXIT sign (doomfj.exitsign: a virtual thing, a built picture, the actor class), plus deg_gate's four viewpoints.
P10 (b): the picture is decoded by tests/fj/stream_screen.StreamScreen, which now REFUSES a run behind the cursor
as the device does (blocked55's gamespeed crash went through it unseen).

    python scratchpad/gp/edge_gate.py            # ~20 min: the visual tier's emission + assembly dominate

WHAT IT CHECKS. Every viewpoint byte-exact (fj vs `render_wall_frame` with deg_gate's keywords), and
R9 -- that the viewpoints EXERCISE what they are here for, decided by the oracle alone, before any fj runs:
  * G2: the views hold column bases (`bases_out`), and the oracle with the base paint disabled (an
    in-memory copy of reference_model, its two `if cbase/fbase[x] is not None` made False) draws a
    DIFFERENT picture at each G2 view -- so a binary without the bases fails here;
  * G1: the oracle without the G1 snapshot (its two `if stack_steps:  # P10 G1` made False) draws a DIFFERENT
    picture at each G1 view;
  * G3: the oracle with only TWO fragment slots (the third slot's early exit put back) draws a DIFFERENT picture
    at each G3 view;
  * G8: the G8 views hold upper pieces whose back ceiling is F_SKY1 (`steps_out`), the case the
    shipped blocked54 drew wrong (60 px at (-416, 128) facing north in the game tier: the binary
    walked the F_SKY1 flat's plane lists where the oracle paints sky).
The op counts are printed; they are the feature's price, not a check.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                        # noqa: E402
from doomfj import reference_model as RM                                     # noqa: E402
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS                      # noqa: E402
from doomfj.fixedpoint import _signed                                        # noqa: E402
from doomfj.harness import W                                                 # noqa: E402
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state   # noqa: E402
from doomfj.wad import WadFile                                               # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer, write_program_files    # noqa: E402
from doomfj.wireformat import encode_feed_mapunits                           # noqa: E402
from tests.fj.stream_screen import StreamScreen                              # noqa: E402

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
# the visual tier's picture keywords; the five every emitter forces are named AT the call (oracle() below), where
# tests/host/test_oracle_calls_in_step.py can see them
KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True, things=True, sprite_wad=art)


def deg(d):
    return int((d % 360) / 360 * (1 << 32)) & 0xFFFFFFFF


# (x, y, angle, kinds): kinds names what the view is here for
VPS = [
    # G2: line 101's nukage edge (sector 173 at -168 beside the courtyard 18 at -160), ~40 units off it
    (1688, 1357, deg(246.8), "G2"),          # on the courtyard, facing the pool: the floor base is NUKAGE1
    (1656, 1283, deg(66.8), "G2"),           # in the pool, facing the courtyard: the base lies past the riser
    (1680, 1345, deg(246.8), "G2"),          # closer still
    # G8 (and G2's ceiling): the start room's window lips onto the sky sector 18
    (spx, spy - 128, deg(90), "G8 G2"),
    (spx + 32, spy - 32, deg(130), "G8"),     # the most sky pieces near the spawn (a scan of its south side)
    (spx, spy - 64, deg(120), "G8"),
    (spx, spy - 96, deg(100), "G8"),
    # G1: a monster behind a nearer ledge (g1_find2: the clip moves 887 / 820 / 295 px here) -- one on the courtyard
    # ledge (floor 24) seen from below (-88), one in the pit (-160) seen from above (48), one from far above (176)
    (2018, 884, 0xEABF52E4, "G1"),
    (1974, 1408, 0x80000000, "G1"),
    (2583, 1087, 0x9556F4D0, "G1"),
    # G3: three map things in one column (g3_find: the third slot moves 144 / 121 px here)
    (2198, -159, 0xFFD64759, "G3"),
    (639, 271, 0x20000000, "G3"),
    # P11 (a): the EXIT sign (doomfj.exitsign) over the exit alcove, from the exit room (this tier has no actors rule:
    # where the room's monster stands before the sign it B-gates it, as it would a monster -- these two keep it in
    # view: the sign moves 430 / 762 px of them)
    (-300, 1296, 0x80000000, "P11a"),
    (-300, 1340, deg(210), "P11a"),
    # deg_gate's four
    (664, 291, 0x18000000, "deg"),
    (1272, -724, 1073741824, "deg"),
    (1869, 479, 2147483648, "deg"),
    (spx, spy, sp.angle, "deg"),
]


def oracle(model, vx, vy, va, **extra):
    return model.render_wall_frame(SimState((vx << 16) & 0xFFFFFFFF, (vy << 16) & 0xFFFFFFFF, va, "E1M1"),
                                   scene, sky=True, near_steps=True, stack_steps=True, bbox_cull=True, degrade=True,
                                   **KW, **extra)


def model_without(lines, name):
    """reference_model with each of `lines` (an `if` condition) made `if False:` (in memory) -- an R9 control's
    oracle: the feature switched off"""
    import types
    src = Path(RM.__file__).read_text(encoding="utf-8")
    for line in lines:
        assert src.count(line) >= 1, line
        src = src.replace(line, "if False:" + line.split(":", 1)[1])
    mod = types.ModuleType(name)                    # a real module: dataclasses look it up
    mod.__file__ = RM.__file__
    sys.modules[mod.__name__] = mod
    exec(compile(src, RM.__file__, "exec"), mod.__dict__)
    return mod.ReferenceModel(cfg)


# R9, decided on the oracle before any fj runs
rm0 = model_without(("if cbase[x] is not None:", "if fbase[x] is not None:"), "doomfj.rm_nobase")
rm1 = model_without(("if stack_steps:                # P10 G1",), "doomfj.rm_nog1")


def two_slot_model():
    """reference_model with the third fragment slot off (in memory): the two-slot early exit"""
    import types
    src = Path(RM.__file__).read_text(encoding="utf-8")
    line = "if drawn[x] or sfrag3[x] is not None:"
    assert src.count(line) == 1, line
    src = src.replace(line, "if drawn[x] or sfrag2[x] is not None:")
    mod = types.ModuleType("doomfj.rm_twoslots")
    mod.__file__ = RM.__file__
    sys.modules[mod.__name__] = mod
    exec(compile(src, RM.__file__, "exec"), mod.__dict__)
    return mod.ReferenceModel(cfg)


rm3 = two_slot_model()
ok = True
for vx, vy, va, kinds in VPS:
    bases, steps = [], []
    want = oracle(rm, vx, vy, va, bases_out=bases, steps_out=steps)
    cb, fbs = bases[0]
    nb = sum(c is not None for c in cb) + sum(f is not None for f in fbs)
    ups = steps[0][0]
    nsky = sum(1 for col in ups for p in col if (p[4].ceil_tex or "").upper() == "F_SKY1")
    if "G2" in kinds:
        plain = oracle(rm0, vx, vy, va)
        moved = sum(1 for a, b in zip(plain, want) if a != b)
        good = nb > 0 and moved > 0
        print("R9 G2 (%d,%d,%#x): %d column bases, %d px the base paint moves  %s"
              % (vx, vy, va, nb, moved, "ok" if good else "!! NOT EXERCISED"), flush=True)
        ok &= good
    if "G1" in kinds:
        plain = oracle(rm1, vx, vy, va)
        moved = sum(1 for a, b in zip(plain, want) if a != b)
        print("R9 G1 (%d,%d,%#x): %d px the ledge clip moves  %s"
              % (vx, vy, va, moved, "ok" if moved else "!! NOT EXERCISED"), flush=True)
        ok &= moved > 0
    if "G3" in kinds:
        plain = oracle(rm3, vx, vy, va)
        moved = sum(1 for a, b in zip(plain, want) if a != b)
        print("R9 G3 (%d,%d,%#x): %d px the third fragment slot moves  %s"
              % (vx, vy, va, moved, "ok" if moved else "!! NOT EXERCISED"), flush=True)
        ok &= moved > 0
    if "P11a" in kinds:
        from doomfj import exitsign as _ES
        _keep, _ES.EXIT_SIGNS = _ES.EXIT_SIGNS, {}
        try:
            plain = oracle(ReferenceModel(cfg), vx, vy, va)
        finally:
            _ES.EXIT_SIGNS = _keep
        moved = sum(1 for a, b in zip(plain, want) if a != b)
        print("R9 P11a (%d,%d,%#x): %d px the EXIT sign moves  %s"
              % (vx, vy, va, moved, "ok" if moved else "!! NOT EXERCISED"), flush=True)
        ok &= moved > 0
    if "G8" in kinds:
        print("R9 G8 (%d,%d,%#x): %d upper pieces with a sky back ceiling  %s"
              % (vx, vy, va, nsky, "ok" if nsky else "!! NOT EXERCISED"), flush=True)
        ok &= nsky > 0

parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, sprite_wad=art, tier="visual")
tmp = Path(tempfile.mkdtemp())
consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
prog = write_program_files(parts, tmp, "e1m1")
out = tmp / "edge.fjm"
fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], *[p.resolve() for p in prog]],
            out, memory_width=W, print_time=False)
print("assembled", flush=True)
for vx, vy, va, kinds in VPS:
    want = bytes(oracle(rm, vx, vy, va))
    scr = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
    term = fj.run(out, io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_MAX_WORDS)
    got = bytes(scr.pixel_indices)
    same = got == want
    ok &= same
    diff = sum(1 for a, b in zip(got, want) if a != b)
    print("%-6s (%d,%d,%#x): %s ops  %s" % (kinds, vx, vy, va, format(term.op_counter, ","),
                                            "BYTE-EXACT" if same else "!! %d px DIFFER" % diff), flush=True)
    if not same:
        bad = [i for i, (a, b) in enumerate(zip(got, want)) if a != b]
        print("   first: %s" % [(i % cfg.VIEW_W, i // cfg.VIEW_W, got[i], want[i]) for i in bad[:10]],
              flush=True)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
