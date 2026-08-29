"""V4 — the THINGS gate, with a BINARY CACHE and a stream TRACER.

A build is ~10 minutes, so guess-and-rebuild is the wrong loop. This caches the assembled `.fjm`
keyed on a hash of (every fj source, the emitter, the flags), so re-running a diagnosis against an
unchanged binary is instant -- and `--trace` decodes the 0x0B byte stream the renderer emits and
reports the FIRST structural anomaly (a row byte past VIEW_H, a non-monotone pair, an odd-length
column), which is what actually pins a malformed-stream bug.

    python scratchpad/v4_check.py --emit            # the gate (oracle draws sprites too)
    python scratchpad/v4_check.py --emit --trace    # ... plus the stream anomaly report
"""
import hashlib
import sys
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
EMIT = "--emit" in sys.argv
NOTHINGS = "--nothings" in sys.argv   # build WITHOUT things: the V3 baseline at every viewpoint
TRACE = "--trace" in sys.argv
RECONLY = "--reconly" in sys.argv   # keep the RECORD half, disable the emit: prices record alone
cfg = Config()
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
art = WadFile.from_path('assets/freedoom1.wad')
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle, "spawn"), (1400, 1200, 0, "courtyard"),
       (2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst")]
WAS = [26_545_502, 27_604_046, None, 32_137_393]     # V1+V2+V3, before V4

TTWICE = "--thingtwice" in sys.argv   # price ALL project_thing calls by DOUBLING them
ABL = (frozenset({"sprnoemit"}) if RECONLY else
       frozenset({"thingtwice"}) if TTWICE else frozenset())
FLAGS = dict(floor_mode="FT1", wall_mode="WPX", raster_mode="lines", plane_near=True,
             wall_noise=True, sky=True, steps=True, things=not NOTHINGS)


class TraceScreen(StreamScreen):
    """StreamScreen + a decoder-level log of the 0x0B stream, so a malformed frame names itself."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.anomalies: list = []
        self.cols_seen = 0
        self._pairs = 0

    def _handle_collines_byte(self, byte: int) -> None:
        if self._cl_active and self._cl_x is None and byte != 0xFF:
            self.cols_seen += 1
            self._pairs = 0
        if self._cl_active and self._cl_x is not None and self._cl_pend is not None:
            y2 = self._cl_pend
            if y2 > self.height:
                self.anomalies.append(f"col {self._cl_x}: row byte {y2} > VIEW_H {self.height}"
                                      f" (pair #{self._pairs})")
            elif y2 < self._cl_y:
                self.anomalies.append(f"col {self._cl_x}: NON-MONOTONE pair {self._cl_y} -> {y2}"
                                      f" (pair #{self._pairs})")
            self._pairs += 1
        super()._handle_collines_byte(byte)


def build():
    key = hashlib.sha256()
    for p in SRC + [ROOT / "src/doomfj/wall_renderer.py", ROOT / "src/doomfj/reference_model.py"]:
        key.update(p.read_bytes())
    key.update(repr(sorted(FLAGS.items())).encode()); key.update(repr(sorted(ABL)).encode())
    tag = key.hexdigest()[:16]
    cache = ROOT / "scratchpad" / "fjmcache"
    cache.mkdir(exist_ok=True)
    fjm = cache / f"v4_{tag}.fjm"
    if fjm.exists():
        print(f"cache HIT {fjm.name}", flush=True)
        return fjm
    t0 = time.time()
    main = emit_wall_renderer(mw, "E1M1", cfg, asset_wad=mw, sprite_wad=art, ablate=ABL, **FLAGS)
    print(f"emitted {len(main):,} chars ({time.time() - t0:.0f}s)", flush=True)
    consts = cfg.emit_fj_consts(cache / "fj_consts.fj")
    mp = cache / f"v4_{tag}.fj"
    mp.write_text(main, encoding="utf-8")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], mp.resolve()],
                fjm, memory_width=W, print_time=False)
    mp.unlink()
    print(f"assembled ({time.time() - t0:.0f}s)  -> {fjm.name}", flush=True)
    return fjm


rm = ReferenceModel(cfg)
scene = build_scene(mw, mw, "E1M1")
WANT = [bytes(rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"),
                                   scene, wall_mode="WPX", floor_mode_ft1=True, plane_near=True,
                                   wall_noise=True, sky=True, near_steps=True,
                                   things=EMIT and not NOTHINGS and not RECONLY,
                                   sprite_wad=art))
        for vx, vy, va, _ in VPS]
print("oracle frames:", [hashlib.sha256(w).hexdigest()[:12] for w in WANT], flush=True)

r = FjmRunner(build())
for i, (vx, vy, va, tag) in enumerate(VPS):
    cls = TraceScreen if TRACE else StreamScreen
    scr = cls(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    try:
        ops = r.run(scr)
    except Exception as e:                                   # a malformed stream can crash the device
        print(f"{tag:10s}: DEVICE ERROR {type(e).__name__}: {e}", flush=True)
        ops = -1
    got = bytes(scr.pixel_indices)
    ok = got == WANT[i]
    d = f"({ops - WAS[i]:+11,} vs V3)" if WAS[i] and ops > 0 else "(no V3 baseline)"
    line = f"{tag:10s} ({vx:5d},{vy:5d}): {ops:11,} ops   {d:24s} {'BYTE-EXACT' if ok else 'DIFFERS'}"
    if not ok:
        bad = [j for j in range(len(got)) if got[j] != WANT[i][j]]
        cols = sorted({j % cfg.VIEW_W for j in bad})
        line += (f"  -- {len(bad)} px, first at (col {bad[0] % cfg.VIEW_W}, "
                 f"row {bad[0] // cfg.VIEW_W}), {len(cols)} columns: {cols[:12]}")
    print(line, flush=True)
    if TRACE:
        print(f"           columns decoded {scr.cols_seen}/{cfg.VIEW_W}, "
              f"anomalies {len(scr.anomalies)}", flush=True)
        for a in scr.anomalies[:8]:
            print("           !! " + a, flush=True)
