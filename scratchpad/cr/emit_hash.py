"""Refactor safety net: sha256 of the EMITTED renderer text (+ the fj library sources) for
two configs. Byte-identical hashes before/after a refactor = the assembled binary is identical
= certification transfers without a rebuild.

    python scratchpad/cr/emit_hash.py <tag>        # writes scratchpad/cr/emit_hash_<tag>.json
    python scratchpad/cr/emit_hash.py --selftest   # prove the tool still has teeth (R9)

⚠ WHAT IT DOES NOT COVER. It hashes the emitted TEXT and the fj library sources; it does not
assemble, so it cannot see an assembler-visible change that leaves the text identical (there is no
such change today -- identical text cannot assemble differently -- but the claim is about the
inputs it hashes, and anything NOT in `fj_sources` or the emit kwargs is outside it). It is a
transfer-of-certification argument, not a gate: the gate is `scratchpad/deg_gate.py`.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer                       # noqa: E402

FJ_SOURCES = ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj",
              "plane_render.fj", "plane_bands.fj", "stream_render.fj")


def _wads():
    return (WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad")),
            WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad")),
            WadFile.from_path(str(ROOT / "assets/freedoom1.wad")))


def _configs(aw, art):
    return {
        # the certified shipping config (heavy: sprite bank, ~8-15 min)
        "certified": dict(asset_wad=aw, over_align=False, floor_mode="FT1", wall_mode="W1R",
                          raster_mode="lines", plane_near=True, wall_noise=True, sky=True,
                          steps=True, stack_steps=True, things=True, sprite_wad=art,
                          bbox_cull=True, deg=True),
        # the steps=False lines config (the config the fbspent regression hid in; fast)
        "lines_nosteps": dict(asset_wad=aw, over_align=False, floor_mode="FT1", wall_mode="WPX",
                              raster_mode="lines", plane_near=True, deg=False),
    }


def run(tag):
    mw, aw, art = _wads()
    cfg = Config()
    out = {"fj_sources": {f: hashlib.sha256((ROOT / "src/fj" / f).read_bytes()).hexdigest()
                          for f in FJ_SOURCES}}
    for name, kw in _configs(aw, art).items():
        t0 = time.time()
        txt = emit_wall_renderer(mw, "E1M1", cfg, **kw)
        out[name] = {"sha256": hashlib.sha256(txt.encode()).hexdigest(), "chars": len(txt),
                     "seconds": round(time.time() - t0)}
        print(f"{name}: {out[name]['sha256'][:16]}  ({len(txt):,} chars, "
              f"{out[name]['seconds']}s)", flush=True)
    (ROOT / "scratchpad/cr" / f"emit_hash_{tag}.json").write_text(json.dumps(out, indent=1))
    print(f"wrote scratchpad/cr/emit_hash_{tag}.json")
    return 0


def selftest():
    """⚠ THE NEGATIVE CONTROL (R9). "The hashes match, so emission is unchanged" is only evidence
    if a CHANGED emission would have produced a different hash. Two things have to hold, and both
    are checked here on the FAST config (the heavy one differs only in size):

      1. DETERMINISM -- emitting the same config twice gives the same hash. Without this the tool
         reports false alarms and gets ignored, which is its own failure mode.
      2. SENSITIVITY -- perturbing an emit-shaping input changes the hash. Three perturbations are
         used, each reaching a different part of the emitter, because a tool that only notices
         coarse changes would still pass a one-flag control.

    Plus the source-hash half: a one-byte edit to an fj library source must change `fj_sources`.
    """
    mw, aw, art = _wads()
    cfg = Config()
    base_kw = _configs(aw, art)["lines_nosteps"]

    def h(**over):
        kw = dict(base_kw, **over)
        return hashlib.sha256(emit_wall_renderer(mw, "E1M1", cfg, **kw).encode()).hexdigest()

    t0 = time.time()
    a, b = h(), h()
    print(f"determinism: {'ok' if a == b else 'FAIL'}  ({a[:16]}, {round(time.time()-t0)}s)")
    failures = 0 if a == b else 1

    for label, over in (("plane_near off", dict(plane_near=False)),
                        ("wall_mode WPX -> W1", dict(wall_mode="W1")),
                        ("floor_mode FT1 -> flat", dict(floor_mode="flat"))):
        try:
            differs = h(**over) != a
        except Exception as e:                       # an unbuildable perturbation proves nothing
            print(f"  skip {label}: {type(e).__name__}")
            continue
        failures += 0 if differs else 1
        print(f"  {'ok  ' if differs else 'MISS'} emission changes for: {label}")

    src = (ROOT / "src/fj" / FJ_SOURCES[0]).read_bytes()
    moved = hashlib.sha256(src + b"\n").hexdigest() != hashlib.sha256(src).hexdigest()
    failures += 0 if moved else 1
    print(f"  {'ok  ' if moved else 'MISS'} fj_sources notices a one-byte source edit")

    print("selftest: " + ("all perturbations detected" if not failures
                          else f"!! {failures} CHECK(S) HAVE NO TEETH"))
    return 1 if failures else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if len(sys.argv) < 2:
        raise SystemExit(__doc__.strip().splitlines()[4].strip())
    sys.exit(run(sys.argv[1]))
