"""Build the CR units: one diff file per unit under scratchpad/cr/units/, grouped so each is
a coherent, single-context-readable chunk. Prints the unit manifest as JSON."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scratchpad" / "cr" / "units"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "main"


def diff(paths):
    return subprocess.run(["git", "diff", f"{BASE}...HEAD", "--", *paths],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=ROOT).stdout


def files_changed(prefix):
    r = subprocess.run(["git", "diff", "--name-only", f"{BASE}...HEAD", "--", prefix],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    return [f for f in r.stdout.splitlines() if f.strip()]


UNITS = [
    ("fj-frame_render", ["src/fj/frame_render.fj"], "high"),
    ("fj-projection", ["src/fj/projection.fj"], "high"),
    ("fj-stream_render", ["src/fj/stream_render.fj"], "high"),
    ("fj-planes-misc", ["src/fj/plane_bands.fj", "src/fj/plane_render.fj",
                        "src/fj/present.fj", "src/fj/fixed_point.fj"], "high"),
    ("py-reference_model", ["src/doomfj/reference_model.py"], "high"),
    ("py-wall_renderer", ["src/doomfj/wall_renderer.py"], "high"),
    ("py-lut_generator", ["src/doomfj/lut_generator.py"], "high"),
    ("py-map-tools", ["src/doomfj/mapcompiler.py", "src/doomfj/mapsimplify.py",
                      "src/doomfj/nodebuilder.py"], "high"),
    ("py-infra", ["src/doomfj/build.py", "src/doomfj/coarse_cull.py", "src/doomfj/config.py",
                  "src/doomfj/fastrun.py", "src/doomfj/tables.py",
                  "src/doomfj/texturecompiler.py", "src/doomfj/wad.py"], "high"),
    ("scripts", ["scripts/"], "medium"),
    ("docs", ["docs/", "DESIGN.md", "README.md"], "medium"),
]

# tests: group by size into <=2500-line units
tf = files_changed("tests/")
groups, cur, cur_n = [], [], 0
for f in tf:
    n = diff([f]).count("\n")
    if cur and cur_n + n > 2500:
        groups.append(cur)
        cur, cur_n = [], 0
    cur.append(f)
    cur_n += n
if cur:
    groups.append(cur)
for i, g in enumerate(groups):
    UNITS.append((f"tests-{i}", g, "medium"))

# scratchpad: group into <=2500-line units (light effort)
sf = files_changed("scratchpad/")
groups, cur, cur_n = [], [], 0
for f in sf:
    n = diff([f]).count("\n")
    if cur and cur_n + n > 2500:
        groups.append(cur)
        cur, cur_n = [], 0
    cur.append(f)
    cur_n += n
if cur:
    groups.append(cur)
for i, g in enumerate(groups):
    UNITS.append((f"scratchpad-{i}", g, "low"))

manifest = []
for name, paths, prio in UNITS:
    d = diff(paths)
    if not d.strip():
        continue
    p = OUT / f"{name}.diff"
    p.write_text(d, encoding="utf-8")
    manifest.append({"name": name, "diff": str(p), "lines": d.count("\n"),
                     "prio": prio, "paths": paths})
print(json.dumps(manifest, indent=1))
