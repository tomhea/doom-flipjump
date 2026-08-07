"""M13p0 — the procedural-look PNG contact sheet (host-only; NO oracle/fj edits — see the plan's Task
M13p0 step 4). Renders square-room + E1M1 spawn + E1M1 rotated-45 for:
  T  current textured (reference)
  F  flat-colored tier (floor_texturing=False -- already in-tree, M13a)
  P1 per-flat 16-strip: pal = pat[(x ^ y) & 15], pat[i] = flat_texels[4*i]
  P2 checker: 4x4 blocks alternating the flat's texel(0,0) / texel(32*64+32)
  P3 xor-noise: pal = pat[(x ^ (y<<1) ^ (y>>2)) & 15]  (same pat as P1, busier break-up)
  W1 walls: per-seg solid color = the MODE texel of the seg's downscaled texture
  W2 walls: per-seg 16-row vertical band strip from the real texture's column 0
Also renders the OWED #9a+#11 consolidated bless comparison: the CURRENT E1M1/square textured frame
vs the PRE-GEOMETRY-CAMPAIGN frame (rendered in an isolated git worktree at commit 0f1c94b, the
commit before perf #9a) -- a pixel-diff highlight, not just a repeat of the two commits' individual
PNG claims.

Usage: python scripts/bakeoff_planes.py
Needs Pillow (`pip install pillow`) -- silently skips PNG writing if absent (still prints stats).
"""
from __future__ import annotations

import json
from pathlib import Path

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, build_scene, spawn_state, frame_hash
from doomfj.wad import WadFile

ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1 = "tests/fixtures/freedoom_e1m1.wad"
OUT = Path("scratchpad/bakeoff")
PRECAMPAIGN_SQUARE = Path("scratchpad/bakeoff/old_square.bin")   # dumped from the 0f1c94b worktree
PRECAMPAIGN_E1M1 = Path("scratchpad/bakeoff/old_e1m1.bin")


def _save_png(frame, palette, path, cfg, scale=5):
    try:
        from PIL import Image
    except ImportError:
        return False
    img = Image.new("RGB", (cfg.VIEW_W, cfg.VIEW_H))
    img.putdata([palette[b] for b in frame])
    img.resize((cfg.VIEW_W * scale, cfg.VIEW_H * scale), Image.NEAREST).save(path)
    return True


class PatternModel(ReferenceModel):
    """Overrides _render_planes_flat (NOT _plane_pixel -- it never receives x, so it can't host an
    (x,y) pattern) to bake-off the P1/P2/P3 candidates. Keeps the exact distance/zlight math; swaps
    only the flat-base argument per (x,y)."""
    pattern = None  # set per-instance: "P1" | "P2" | "P3"

    def _pattern_pal(self, asset_wad, flatcache, name, x, y):
        texels = self._flat_texels(asset_wad, name, flatcache)  # 64x64 row-major [v*64+u]
        if self.pattern == "P1":
            pat = [texels[4 * i] for i in range(16)]
            return pat[(x ^ y) & 15]
        if self.pattern == "P2":
            base, base2 = texels[0], texels[32 * 64 + 32]
            return base if ((x >> 2) ^ (y >> 2)) & 1 == 0 else base2
        if self.pattern == "P3":
            pat = [texels[4 * i] for i in range(16)]
            return pat[(x ^ (y << 1) ^ (y >> 2)) & 15]
        raise ValueError(self.pattern)

    def _render_planes_flat(self, fb, colormap, asset_wad, flatcache, viewz,
                            ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff):
        cfg = self.cfg
        W, H = cfg.VIEW_W, cfg.VIEW_H
        for x in range(W):
            if ceil_hi[x] >= 0:
                ph, lt = abs((col_ch[x] << 16) - viewz), col_lt[x]
                for y in range(0, ceil_hi[x] + 1):
                    base = self._pattern_pal(asset_wad, flatcache, col_cf[x], x, y)
                    fb[y * W + x] = self._plane_pixel(colormap, ph, lt, base, y)
            if floor_lo[x] < H:
                ph, lt = abs((col_fh[x] << 16) - viewz), col_lt[x]
                for y in range(floor_lo[x], H):
                    base = self._pattern_pal(asset_wad, flatcache, col_ff[x], x, y)
                    fb[y * W + x] = self._plane_pixel(colormap, ph, lt, base, y)


# CR-2026-08: the old WallModel._wall_texture override is GONE -- since M13p4a the oracle
# takes wall_mode natively (render_wall_frame(wall_mode="W1"/"W2") -> _tiny_wall_canvas), with
# the per-mode cache key that the override lacked (it flattened V2 sky's "textured" requests
# too -- the documented cache-poisoning class). The W1/W2 sets below use the shipped mechanism.


def _viewpoints(wad_path, mapname):
    wad = WadFile.from_path(wad_path)
    sp = spawn_state(wad, mapname)
    from doomfj.fixedpoint import _signed
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    return wad, [("spawn", spx, spy, sp.angle), ("rot45", spx, spy, A45)]


def render_set(label, wad_path, mapname, asset_path, model_factory, floor_texturing=None, cfg=None,
               **render_kwargs):
    cfg = cfg or Config()
    wad, vps = _viewpoints(wad_path, mapname)
    asset = WadFile.from_path(asset_path) if asset_path else wad
    scene = build_scene(wad, asset, mapname)
    stats = {}
    for tag, vx, vy, va in vps:
        rm = model_factory()
        from doomfj.reference_model import SimState
        state = SimState(vx << 16, vy << 16, va, mapname)
        kwargs = {} if floor_texturing is None else {"floor_texturing": floor_texturing}
        frame = rm.render_wall_frame(state, scene, **kwargs, **render_kwargs)
        name = f"{label}_{Path(wad_path).stem}_{tag}"
        _save_png(frame, asset.playpal(0), OUT / f"{name}.png", cfg)
        stats[name] = {"hash": frame_hash(frame), "distinct_palette_indices": len(set(frame))}
    return stats


def diff_report(label, old_bytes, new_frame, palette, cfg):
    diffs = [(i, o, n) for i, (o, n) in enumerate(zip(old_bytes, new_frame)) if o != n]
    deltas = [abs(o - n) for _, o, n in diffs]
    if diffs:
        try:
            from PIL import Image
            W, H = cfg.VIEW_W, cfg.VIEW_H
            img = Image.new("RGB", (W, H))
            px = [palette[b] for b in new_frame]
            for i, _, _ in diffs:
                px[i] = (255, 0, 255)   # magenta highlight over the current frame
            img.putdata(px)
            img.resize((W * 5, H * 5), Image.NEAREST).save(OUT / f"{label}_diff_highlight.png")
        except ImportError:
            pass
    return {
        "changed_px": len(diffs), "total_px": len(new_frame),
        "changed_pct": round(100 * len(diffs) / len(new_frame), 2),
        "max_delta": max(deltas) if deltas else 0,
        "mean_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    results = {}

    # T (reference) + F (already-in-tree flat tier)
    results["T"] = render_set("T", ROOM, "MAP01", ASSET, ReferenceModel, cfg=cfg)
    results["T"].update(render_set("T", E1M1, "E1M1", None, ReferenceModel, cfg=cfg))
    results["F"] = render_set("F", ROOM, "MAP01", ASSET, ReferenceModel, floor_texturing=False, cfg=cfg)
    results["F"].update(render_set("F", E1M1, "E1M1", None, ReferenceModel, floor_texturing=False, cfg=cfg))

    # P1/P2/P3 floor patterns
    for p in ("P1", "P2", "P3"):
        def factory(p=p):
            m = PatternModel(cfg); m.pattern = p; return m
        results[p] = render_set(p, ROOM, "MAP01", ASSET, factory, floor_texturing=False, cfg=cfg)
        results[p].update(render_set(p, E1M1, "E1M1", None, factory, floor_texturing=False, cfg=cfg))

    # W1/W2 wall candidates (textured floors kept, only the wall texture swapped) -- the
    # oracle's native wall_mode tier (see the note where WallModel used to be)
    for w in ("W1", "W2"):
        results[w] = render_set(w, ROOM, "MAP01", ASSET, ReferenceModel, cfg=cfg, wall_mode=w)
        results[w].update(render_set(w, E1M1, "E1M1", None, ReferenceModel, cfg=cfg, wall_mode=w))

    # the owed #9a+#11 consolidated bless: current vs pre-campaign (0f1c94b), spawn viewpoint only
    if PRECAMPAIGN_SQUARE.exists() and PRECAMPAIGN_E1M1.exists():
        rm = ReferenceModel(cfg)
        room_wad, asset_wad = WadFile.from_path(ROOM), WadFile.from_path(ASSET)
        rscene = build_scene(room_wad, asset_wad, "MAP01")
        rframe = rm.render_wall_frame(spawn_state(room_wad, "MAP01"), rscene)
        results["bless_square"] = diff_report("bless_square", PRECAMPAIGN_SQUARE.read_bytes(),
                                              rframe, asset_wad.playpal(0), cfg)
        e_wad = WadFile.from_path(E1M1)
        escene = build_scene(e_wad, e_wad, "E1M1")
        eframe = rm.render_wall_frame(spawn_state(e_wad, "E1M1"), escene)
        results["bless_e1m1"] = diff_report("bless_e1m1", PRECAMPAIGN_E1M1.read_bytes(),
                                            eframe, e_wad.playpal(0), cfg)
    else:
        results["bless"] = "SKIPPED -- old_square.bin/old_e1m1.bin not found (dump via a pre-campaign worktree first)"

    (OUT / "bakeoff-metrics.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
