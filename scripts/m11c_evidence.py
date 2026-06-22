"""M11c (R1 gate / D2 bake-off) — the full-WIDTH-scale measurement + the R-2 assemble guard.

Two builds (executing a full 16,000-pixel frame headless is ~24M ops / minutes, and is NOT needed for
the gate):
  1. a SMALL build (run) — golden bit-exact vs the H5 oracle (D12) + per_pixel_ops + storage_mode (flat).
  2. the FULL 160x100 build (assemble only) — the bake-off's assemble_seconds + .fjm size + span (R-4).
ops/frame is extrapolated as per_pixel_ops x (VIEW_W*VIEW_H).

The D2 rule (owner, 2026-06-21): choose full-unroll (b) iff full-frame assemble <= ASSEMBLE_SECONDS_MAX
AND (b) ops/frame <= (a) column-buffer. (b) < (a) by construction (full-unroll = column-buffer minus the
per-pixel pointer-store pass), so the only gate is the assemble ceiling. `.fjm` size has NO limit.
Writes build/metrics.json with the verdict + the `assemble_seconds_max` R-2 CI guard.
"""
import json
from pathlib import Path

from doomfj.build import build_unroll_frame
from doomfj.config import Config, FLAT_MAX_WORDS
from doomfj.reference_model import ReferenceModel, screen_frame_hash
from doomfj.texturecompiler import composite_texture, downscale_canvas, texture_texels
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
TEX, DOWNSCALE = "MC5", 2
LIGHT, STEP, FRAC0 = 20, 327, 0
SMALL_W, SMALL_H = 16, 50              # fast run: golden + per_pixel_ops
ASSEMBLE_SECONDS_MAX = 300            # R-2 CI guard: hard ceiling (owner: 5 min; target ~3 min)
METRICS = Path("build/metrics.json")


def main() -> dict:
    cfg = Config()
    wad = WadFile.from_path(E1M1)
    d = {x.name: x for x in wad.texture_defs()}[TEX]
    texh, texw = d.height // DOWNSCALE, d.width // DOWNSCALE
    texels = texture_texels(downscale_canvas(composite_texture(wad, d), DOWNSCALE))
    rm = ReferenceModel()

    # 1) small build (run): golden bit-exact + per_pixel_ops + storage_mode
    small = build_unroll_frame(E1M1, TEX, light=LIGHT, width=SMALL_W, count=SMALL_H, step=STEP,
                               frac0=FRAC0, out_fjm="build/m11c_small.fjm",
                               generated_dir="build/generated/m11c_small", run=True)
    oracle = rm.render_unroll_frame(texels, texh, texw, wad.colormap(), LIGHT,
                                    width=SMALL_W, count=SMALL_H, frac0=FRAC0, step=STEP)
    palette_rgb = bytes(v for rgb in wad.playpal(0) for v in rgb)
    frame_ok = bytes(small["pixel_indices"]) == oracle
    hash_ok = small["frame_hash"] == screen_frame_hash(oracle, palette_rgb)
    per_pixel_ops = small["per_pixel_ops"]

    # 2) full 160x100 build (assemble only): the bake-off assemble/size/span
    full = build_unroll_frame(E1M1, TEX, light=LIGHT, step=STEP, frac0=FRAC0,
                              out_fjm="build/m11c_full.fjm",
                              generated_dir="build/generated/m11c_full", run=False)
    ops_per_frame = per_pixel_ops * cfg.VIEW_W * cfg.VIEW_H

    assemble_ok = full["assemble_seconds"] < ASSEMBLE_SECONDS_MAX
    flat_ok = small["storage_mode"] == "flat" and full["span_words"] < FLAT_MAX_WORDS
    d2_choice = "full-unroll (b)" if assemble_ok else "FALLBACK: column-buffer (a)"

    metrics = {
        "milestone": "M11c",
        "scale": f"{full['width']}x{full['count']} ({full['pixels']} px, full WIDTH-scale)",
        "renderer": "full-unroll (b), shared fcall leaf + hex.vec2 register framebuffer (0x06)",
        "storage_mode": small["storage_mode"],
        "span_words": full["span_words"],
        "flat_limit": FLAT_MAX_WORDS,
        "headroom": round(FLAT_MAX_WORDS / full["span_words"], 3) if full["span_words"] else None,
        "per_pixel_ops": per_pixel_ops,
        "ops_per_frame": ops_per_frame,
        "assemble_seconds": full["assemble_seconds"],
        "assemble_seconds_max": ASSEMBLE_SECONDS_MAX,
        "fjm_bytes": full["fjm_bytes"],
        "golden_scale": f"{SMALL_W}x{SMALL_H}",
        "golden_bit_exact": frame_ok,
        "golden_hash_match": hash_ok,
        "frame_hash": small["frame_hash"],
        "d2_choice": d2_choice,
    }
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))

    assert flat_ok, f"R4: not flat / over span: {metrics}"
    assert frame_ok and hash_ok, f"D12: golden frame not bit-exact vs oracle: {metrics}"
    assert assemble_ok, f"R-2: assemble {full['assemble_seconds']}s >= ceiling {ASSEMBLE_SECONDS_MAX}s"
    return metrics


if __name__ == "__main__":
    main()
