"""Capture what the shipped game draws, without the binary: replay a frozen combat run (v10) on the
oracle through b0_scenarios.drive(gb=None) -- the SAME oracle-only path B0 uses -- and record every
picture orc.render() returns plus the palette index the mirror's world shows that frame.
B0 proved blocked63 state- and pixel-exact to this oracle on every frame of all 11 v10 runs
(docs/ship-gate.md section 1), so these frames ARE the binary's frames.

usage: python scratchpad/gp/render_frames.py <run-name> [<run-name> ...]   (cwd must be the repo root)
writes build/frames/<run>/f000.png ... (4x nearest) and build/frames/<run>.gif (3x nearest, 78 ms a frame)
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "frames"
for q in (ROOT / "scratchpad" / "gp", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", ROOT / "tests", ROOT / "src", ROOT):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))

from PIL import Image  # noqa: E402

import b0_scenarios as B  # noqa: E402
import scenarios_v2 as S  # noqa: E402
from doomfj import monsters as M  # noqa: E402
from doomfj.wad import WadFile  # noqa: E402

W, H = 160, 100
SET = os.environ.get("SET", "v10")     # the frozen set to replay (v10 since P11; blocked63 is pixel-exact on it)
DOC = ROOT / "scratchpad" / "gp" / "scenarios" / ("combat_scenarios_%s.json" % SET)
ART = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
PALS = {}


def playpal(idx: int):
    if idx not in PALS:
        flat = []
        for r, g, b in ART.playpal(idx):
            flat += [r, g, b]
        PALS[idx] = flat
    return PALS[idx]


# stash the live MonsterPhase so the render wrapper can read the frame's palette index
_live = {}
_orig_init = M.MonsterPhase.__init__


def _init(self, *a, **k):
    _orig_init(self, *a, **k)
    _live["mph"] = self


M.MonsterPhase.__init__ = _init


def capture(run_name: str, doc: dict):
    run = next(r for r in doc["runs"] if r["name"] == run_name)
    frames = B.model_frames(run)
    orc = B.GameOracle()
    pics = []
    orig_render = orc.render

    def rec(*a, **k):
        out = orig_render(*a, **k)
        mph = _live.get("mph")
        pics.append((bytes(out), mph.palette() if mph is not None else 0))
        return out

    orc.render = rec
    t0 = time.time()
    res = B.drive(None, None, orc, frames, pixel_every=1)
    dt = time.time() - t0
    assert all(len(p) == W * H for p, _ in pics), {len(p) for p, _ in pics}
    print("%s: %d pictures in %.1f s (%.2f s/frame); cam parts %d, dead frames %s"
          % (run_name, len(pics), dt, dt / max(1, len(pics)), res["cam_parts"], res["dead"]), flush=True)
    return pics


def to_image(pix: bytes, pal_idx: int) -> Image.Image:
    im = Image.frombytes("P", (W, H), pix)
    im.putpalette(playpal(pal_idx))
    return im


def write(run_name: str, pics):
    d = OUT / run_name
    d.mkdir(parents=True, exist_ok=True)
    ims = []
    for i, (pix, pal) in enumerate(pics):
        im = to_image(pix, pal)
        ims.append(im)
        if i % 5 == 0 or i == len(pics) - 1:
            im.resize((W * 4, H * 4), Image.NEAREST).convert("RGB").save(d / ("f%03d.png" % i))
    scale = int(os.environ.get("SCALE", "3"))
    big = [im.resize((W * scale, H * scale), Image.NEAREST) for im in ims]
    gif = OUT / (run_name + ("" if scale == 3 else "_%dx" % scale) + ".gif")
    big[0].save(gif, save_all=True, append_images=big[1:], duration=70, loop=0, optimize=False, disposal=1)
    # a contact sheet: frames 0, 20, 40, 60, 80, 99 at 2x
    sheet = Image.new("RGB", (W * 2 * 3, H * 2 * 2))
    for j, i in enumerate([0, 20, 40, 60, 80, len(pics) - 1]):
        sheet.paste(ims[i].resize((W * 2, H * 2), Image.NEAREST).convert("RGB"), ((j % 3) * W * 2, (j // 3) * H * 2))
    sheet.save(OUT / (run_name + "_sheet.png"))
    print("  wrote %s (%.1f MB), %s, stills in %s" % (gif.name, gif.stat().st_size / 1e6, run_name + "_sheet.png", d))


if __name__ == "__main__":
    doc = json.loads(DOC.read_text(encoding="ascii"))
    S.use_sight_rule(doc)
    names = sys.argv[1:] or ["R0-imp-court"]
    for n in names:
        write(n, capture(n, doc))
