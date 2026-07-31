"""M13-XTADISP: does routing wall_scale_setup's two xtoviewangle reads through a D4 dispatch table
pay off, and is the frame still byte-exact?

`proj.wall_scale_setup` runs once per in-frustum seg (169 at E1M1 spawn, 202 at the worst sweep
viewpoint) and opens with TWO `hex.read_table_packed 4` reads (~289@ each per the stl's documented
complexities). The same conversion M13-ATANDISP made for tantoangle / slopediv_recip8.

Baseline to beat (measured before the change): 21,736,934 spawn / 26,557,125 at (-309,-44).

Also prices the two kernels the step-face design adds, by DOUBLING them into dead registers so the
frame stays byte-exact (a stub would price itself plus everything downstream -- that mistake cost a
whole handoff revision).
"""
import hashlib
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
import flipjump as fj
from doomfj.config import Config
from doomfj.fastrun import FjmRunner
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
cfg = Config()
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle), (1400, 1200, 0)]   # spawn (no sky) + the courtyard (139 sky cols)
WAS = [21_736_934, 26_557_125]                    # the shipped tier, before M13-XTADISP

# the oracle frames, for the byte-exact gate
rm = ReferenceModel(cfg)
scene = build_scene(mw, mw, "E1M1")
WANT = [bytes(rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"),
                                   scene, wall_mode="WPX", floor_mode_ft1=True, plane_near=True,
                                   wall_noise=True, sky=True))
        for vx, vy, va in VPS]
print("oracle frames rendered:", [hashlib.sha256(w).hexdigest()[:12] for w in WANT], flush=True)

COUNTS = {"projtwice": (160, 160, "column_params_m", "columns"),
          "scaletwice": (169, 202, "wall_scale_setup_m", "in-frustum segs")}
res = {}
for tag in ("baseline",):
    t0 = time.time()
    ab = frozenset() if tag == "baseline" else frozenset({tag})
    main = emit_wall_renderer(mw, "E1M1", cfg, asset_wad=mw, over_align=False, floor_mode="FT1",
                              wall_mode="WPX", raster_mode="lines", plane_near=True, ablate=ab,
                              wall_noise=True, sky=True)
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    (tmp / "m.fj").write_text(main, encoding="utf-8")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
                tmp / "m.fjm", memory_width=W, print_time=False)
    r = FjmRunner(tmp / "m.fjm")
    out = []
    for i, (vx, vy, va) in enumerate(VPS):
        scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
        ops = r.run(scr)
        got = bytes(scr.pixel_indices)
        ok = got == WANT[i]
        out.append((ops, ok))
        if tag == "baseline" and not ok:
            bad = [j for j in range(len(got)) if got[j] != WANT[i][j]]
            print(f"  !! NOT byte-exact @({vx},{vy}): {len(bad)} pixels differ, first at {bad[0]}"
                  f" (col {bad[0] % cfg.VIEW_W}, row {bad[0] // cfg.VIEW_W})", flush=True)
    res[tag] = out
    print(f"{tag:11s}: " + "  ".join(f"{o:,} [{'exact' if k else 'DIFFERS'}]" for o, k in out)
          + f"   (build {time.time() - t0:.0f}s)", flush=True)

print()
for i, (vx, vy, va) in enumerate(VPS):
    now = res["baseline"][i][0]
    print(f"V1+V2       @({vx:5d},{vy:4d}): {WAS[i]:,} -> {now:,}   ({now - WAS[i]:+,})"
          f"   {'BYTE-EXACT' if res['baseline'][i][1] else '!! FRAME CHANGED'}")
print()
for tag in ():
    n_spawn, n_worst, macro, unit = COUNTS[tag]
    for i, ((vx, vy, va), n) in enumerate(zip(VPS, (n_spawn, n_worst))):
        d = res[tag][i][0] - res["baseline"][i][0]
        assert res[tag][i][1], f"{tag} changed the frame -- its delta is not trustworthy"
        print(f"{macro:20s} @({vx:5d},{vy:4d}): {d:11,} ops / {n:4d} {unit:16s}"
              f"= {d / n:8,.0f} each   ({d / res['baseline'][i][0]:5.1%} of the frame)")
