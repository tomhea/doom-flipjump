"""The owner's vanishing-sprites repro: (1329,1041,0x40000000) -> one step -> (1329,1065).
Count thing-pipeline populations at both viewpoints under mechanism-isolating variants."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
W = cfg.VIEW_W
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")

C: dict = {}
_o_proj = ReferenceModel.project_thing
_o_strip = ReferenceModel.sprite_strip


def _proj(self, *a):
    r = _o_proj(self, *a)
    C["thproj"] = C.get("thproj", 0) + 1
    C["thacc"] = C.get("thacc", 0) + (r is not None)
    return r


def _strip(*a, **k):
    C["sstrip"] = C.get("sstrip", 0) + 1
    return _o_strip(*a, **k)


ReferenceModel.project_thing = _proj
ReferenceModel.sprite_strip = staticmethod(_strip)

VPS = [(1329, 1041, 0x40000000, "before"), (1329, 1065, 0x40000000, "after")]
VARIANTS = {
    "shipped": dict(bbox_cull=True, degrade=True),
    "no-cull": dict(bbox_cull=False, degrade=True),
    "no-deg": dict(bbox_cull=True, degrade=False),
    "neither": dict(bbox_cull=False, degrade=False),
}

for vx, vy, va, tag in VPS:
    line = f"({vx},{vy}) {tag}: "
    for name, kw in VARIANTS.items():
        C.clear()
        tout: list = []
        rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"),
                             scene, wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                             wall_noise=True, sky=True, near_steps=True, things=True,
                             sprite_wad=art, stack_steps=True, things_out=tout, **kw)
        st = getattr(rm, "_thing_stats", {})
        line += (f"{name}[proj={C.get('thproj',0)} acc={C.get('thacc',0)} "
                 f"strips={C.get('sstrip',0)} ss={st.get('ss_arrived')}/{st.get('ss_total')} "
                 f"arrived={st.get('th_arrived')} claimstop={st.get('th_claim_stopped')}]  ")
    print(line, flush=True)

# where the player is: which subsector, and does it change across the step?
for vx, vy, va, tag in VPS:
    ss = rm.point_in_subsector(scene.cmap, vx, vy)
    print(f"({vx},{vy}) {tag}: subsector {ss}")
