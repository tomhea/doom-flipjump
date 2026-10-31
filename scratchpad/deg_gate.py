"""25M-CAP fast gate: stock E1M1 with the full degradation package ON, byte-exact vs the
degrade=True oracle at 4 viewpoints that exercise every lever (graduated things, B-gate,
sliver-flat, stack far gate, PNEAR 96).

    python scratchpad/deg_gate.py

`run(table_pool=...)` is the same gate with flipjump's table pool on (scratchpad/12m/deg_gate_blocked.py): a
callable that takes the emitted program's files and returns a fresh BlockPool for its one assembly. Nothing is
patched -- the pool goes into `flipjump.assemble(table_pool=)`."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                   # noqa: E402
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS                 # noqa: E402
from doomfj.wireformat import encode_feed_mapunits                      # noqa: E402
from doomfj.fixedpoint import _signed                                   # noqa: E402
from doomfj.harness import W                                            # noqa: E402
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state   # noqa: E402
from doomfj.wad import WadFile                                          # noqa: E402
from tests.fj.stream_screen import StreamScreen                         # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer, write_program_files   # noqa: E402

SRC = [ROOT / "src/fj" / f for f in ("projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]


def run(table_pool=None, labels_out=None):
    """the gate: 0 when all four viewpoints are byte-exact, else 1. `table_pool(files) -> BlockPool`: the pool for
    the one assembly (None: no pool); `labels_out`: a dict that receives the assembled labels."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    scene = build_scene(mw, mw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    vps = [(664, 291, 0x18000000),        # the sprite-overlap frame: B-gate + graduated
           (1272, -724, 1073741824),      # stairs: the stack far gate
           (1869, 479, 2147483648),       # the everything frame: sliver + PNEAR + all
           (spx, spy, sp.angle)]

    # ⚠ CR-2026-08 (IN-3, A0.1): `which meant the wedge subtree cull -- a mechanism that changes which marking segs
    # spend budget -- was never covered by the repo's own proof. The four op counts below therefore
    # CHANGED when this landed; that is the intended, one-time cost of unifying the three tiers.
    parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, sprite_wad=art, tier="visual")
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    # the emitted program is written as SEPARATE files (order is load-bearing -- see
    # write_program_files); the huge generated regions no longer share a file with the program.
    prog = write_program_files(parts, tmp, "e1m1")
    print("program parts: " + ", ".join("%s=%s" % (p.name.split("_", 2)[2][:-3],
                                                   format(p.read_text(encoding="utf-8").count(chr(10)) + 1, ","))
                                        for p in prog), flush=True)
    out = tmp / "deg.fjm"
    files = [consts.resolve(), *[s.resolve() for s in SRC], *[p.resolve() for p in prog]]
    labels = fj.assemble(files, out, memory_width=W, show_progress=False,
                         table_pool=None if table_pool is None else table_pool(files))
    if labels_out is not None:
        labels_out.update(labels)
    print("assembled", flush=True)

    ok = True
    for vx, vy, va in vps:
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                    wall_noise=True, near_steps=True, stack_steps=True,
                                    things=True, sprite_wad=art, degrade=True, sky=True, bbox_cull=True)
        scr = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
        term = fj.run(out, io_device=scr, show_progress=False, print_termination=False,
                      flat_max_words=RENDER_FLAT_MAX_WORDS)
        same = bytes(scr.pixel_indices) == bytes(want)
        ok &= same
        diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
        print(f"({vx},{vy},{va:#x}): {term.op_counter:,} ops  "
              f"{'BYTE-EXACT' if same else f'!! {diff} px DIFFER'}", flush=True)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
