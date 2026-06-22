"""M12h integration evidence (R2): render the first 3D wall frame with the H5 oracle and show it as
ASCII art (the renderer is host-only until M12j, so the "frame" is the oracle's W*H byte buffer). Renders
the square room from a few viewpoints + the full real E1M1 spawn, and reports the frame structure. Writes
build/m12h-metrics.json. Reproducible: `python scripts/m12h_evidence.py`."""
from __future__ import annotations

import json
from pathlib import Path

from doomfj.config import Config
from doomfj.reference_model import (
    ReferenceModel, SimState, build_scene, spawn_state, frame_hash, WALL_BG, CEIL_BG, FLOOR_BG,
)
from doomfj.wad import WadFile

ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1 = "tests/fixtures/freedoom_e1m1.wad"
U = 1 << 16


def _ascii(frame, cfg, fills, step=4):
    """Down-sample the frame to ASCII: '#' wall, '.' ceiling, ',' floor, '?' other — one char per `step`
    columns/rows so it fits a PR."""
    wall, ceil, floor = fills
    glyph = {wall: "#", ceil: ".", floor: ","}
    rows = []
    for y in range(0, cfg.VIEW_H, step):
        rows.append("".join(glyph.get(frame[y * cfg.VIEW_W + x], "?")
                            for x in range(0, cfg.VIEW_W, step * 2)))
    return rows


def main() -> dict:
    rm = ReferenceModel()
    cfg = Config()
    room = WadFile.from_path(ROOM)
    asset = WadFile.from_path(ASSET)
    scene = build_scene(room, asset, "MAP01")
    cm = asset.colormap()
    fills = (cm[20][WALL_BG], cm[20][CEIL_BG], cm[20][FLOOR_BG])

    views = {
        "spawn_centre_facing_north": spawn_state(room, "MAP01"),
        "centre_facing_east": SimState(128 * U, 128 * U, 0, "MAP01"),
        "near_east_wall": SimState(200 * U, 128 * U, 0, "MAP01"),
    }
    room_art = {}
    for name, st in views.items():
        frame = rm.render_wall_frame(st, scene)
        room_art[name] = {"hash": frame_hash(frame), "ascii": _ascii(frame, cfg, fills)}
        print(f"\n== square room: {name} ==")
        print("\n".join(room_art[name]["ascii"]))

    e = WadFile.from_path(E1M1)
    escene = build_scene(e, e, "E1M1")
    est = spawn_state(e, "E1M1")
    eframe = rm.render_wall_frame(est, escene)
    ebg = rm.render_frame(est, escene)
    changed = sum(1 for a, b in zip(eframe, ebg) if a != b)
    print(f"\n== E1M1 spawn: {changed} of {len(eframe)} px are walls (rest = bg) ==")

    metrics = {
        "fills": {"wall": fills[0], "ceil": fills[1], "floor": fills[2]},
        "square_room": {k: {"hash": v["hash"]} for k, v in room_art.items()},
        "square_room_spawn_ascii": room_art["spawn_centre_facing_north"]["ascii"],
        "e1m1": {
            "frame_hash": frame_hash(eframe),
            "wall_pixels": changed,
            "total_pixels": len(eframe),
            "spawn_subsector": rm.point_in_subsector(escene.cmap, est.x >> 16, est.y >> 16),
        },
    }
    out = Path("build/m12h-metrics.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    main()
