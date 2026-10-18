"""M8 (special 48): run from the repo root with PYTHONPATH=src. Prototype of the PROPOSAL (oracle only, monkeypatched; not the implementation): on a special-48 line's seg the
W1R pattern key becomes x + w1r_xoff + scroll. How many pixels does scroll = 1, 2, 5 move?  Also: COMPBLUE's two
W1R texels, and which lines wear COMPBLUE."""
from pathlib import Path
from doomfj.wad import WadFile
from doomfj import reference_model as R
from doomfj.config import GAME_CFG, map_cfg

w = WadFile.from_path(Path("tests/fixtures/freedoom_e1m2.wad"))
cfg = map_cfg(GAME_CFG, "E1M2")
rm = R.ReferenceModel(cfg)
sc = R.build_scene(w, w, "E1M2", {})
lds, sds = w.linedefs("E1M2"), w.sidedefs("E1M2")
print("lines wearing COMPBLUE:", [i for i, ld in enumerate(lds)
      if any((getattr(sds[s], t) or "").upper() == "COMPBLUE" for s in (ld.front, ld.back) if 0 <= s < len(sds)
             for t in ("upper", "middle", "lower"))])
print("COMPBLUE W1R canvas:", rm._wall_texture(w, "COMPBLUE", {}, wall_mode="W1R"))
state = {"on": False, "k": 0}
orig_tex, orig_runs = rm._wall_texture, R.ReferenceModel.w1r_runs
SCROLLV = {((736, -1240), (896, -1240)), ((896, -1544), (736, -1544))}
orig_fc, orig_planes = rm.wall_fake_contrast, rm._render_planes_flat
def tex(asset, name, cache, *, wall_mode="textured"):
    state["on"] = False
    return orig_tex(asset, name, cache, wall_mode=wall_mode)
def fc(v1, v2):
    state["on"] = (tuple(v1), tuple(v2)) in SCROLLV
    return orig_fc(v1, v2)
def planes(*a, **k):
    state["on"] = False
    return orig_planes(*a, **k)
rm.wall_fake_contrast, rm._render_planes_flat = fc, planes
def runs(wlen, x):
    return orig_runs(wlen, x + (state["k"] if state["on"] else 0))
rm._wall_texture, rm.w1r_runs = tex, runs
ANG90 = 0x40000000
KW = dict(R.GAME_RENDER_KW); KW["things"] = False
for (x, y, a) in [(816, -1300, ANG90), (816, -1480, 3 * ANG90), (700, -1392, ANG90 // 2)]:
    st = R.SimState(x << 16, y << 16, a, "E1M2")
    fr = []
    for k in (0, 1, 2, 5):
        state["k"] = k
        fr.append(rm.render_wall_frame(st, sc, **KW))
    print("view", (x, y, hex(a)), "pixels moved by scroll 1,2,5:", [sum(p != q for p, q in zip(fr[0], f)) for f in fr[1:]])
