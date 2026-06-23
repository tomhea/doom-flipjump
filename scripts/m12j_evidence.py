"""M12j integration evidence (R2): render the TEXTURED wall frame with the H5 oracle and report it.
Walls are now sampled from their middle texture (one-sided walls only; two-sided openings are skipped
until M13). Renders the square room (STEP4) + the full real E1M1 spawn and writes a PNG of each plus
build/m12j-metrics.json. Reproducible: `python scripts/m12j_evidence.py` (PNG needs Pillow)."""
from __future__ import annotations

import json
from pathlib import Path

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, build_scene, spawn_state, frame_hash
from doomfj.wad import WadFile

ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1 = "tests/fixtures/freedoom_e1m1.wad"


def _save_png(frame, palette, path, cfg, scale=5):
    try:
        from PIL import Image
    except ImportError:
        return False
    img = Image.new("RGB", (cfg.VIEW_W, cfg.VIEW_H))
    img.putdata([palette[b] for b in frame])
    img.resize((cfg.VIEW_W * scale, cfg.VIEW_H * scale), Image.NEAREST).save(path)
    return True


def main() -> dict:
    rm, cfg = ReferenceModel(), Config()
    out = Path("build")
    out.mkdir(parents=True, exist_ok=True)

    room = WadFile.from_path(ROOM)
    asset = WadFile.from_path(ASSET)
    rscene = build_scene(room, asset, "MAP01")
    rframe = rm.render_wall_frame(spawn_state(room, "MAP01"), rscene)
    _save_png(rframe, asset.playpal(0), out / "m12j_square.png", cfg)

    e = WadFile.from_path(E1M1)
    escene = build_scene(e, e, "E1M1")
    eframe = rm.render_wall_frame(spawn_state(e, "E1M1"), escene)
    ebg = rm.render_frame(spawn_state(e, "E1M1"), escene)
    _save_png(eframe, e.playpal(0), out / "m12j_e1m1_spawn.png", cfg)

    metrics = {
        "square_room": {
            "hash": frame_hash(rframe),
            "distinct_palette_indices": len(set(rframe)),
            "wall_texture": room.sidedefs("MAP01")[0].middle,
        },
        "e1m1": {
            "hash": frame_hash(eframe),
            "distinct_palette_indices": len(set(eframe)),
            "wall_pixels": sum(1 for a, b in zip(eframe, ebg) if a != b),
            "total_pixels": len(eframe),
        },
    }
    (out / "m12j-metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    main()
