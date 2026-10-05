"""p67_identity.py -- M7 P6/P7 (agent A): the oracle's new opt-in keywords keep every existing picture.

    python scratchpad/gp/p67_identity.py [--run R2-barrel-hall] [--frames 60] [--ref m7-p67]

p5_mobiles_identity.py's proof for P6's keywords (docs/gp-p67-interface.md 4.1, 5): one run of the frozen set v5 is
replayed on the FULL model (scenarios_v2: the set's own replay, its poses checked against the file) and, at the last
`--frames` frames, the game view is rendered:
  OLD   the UNMODIFIED oracle -- `reference_model.py` at the base ref (git show), loaded as its own module -- with the
        frame's monster views, positions and P5's mobiles (fireballs, blood: 3-tuples);
  NEW   this tree's oracle, the same keywords, every P6 keyword ABSENT, and once more SPELLED EMPTY
        (`barrel_views={}`, `thing_removed=[]`);
  P6    this tree's oracle with the frame's real P6 state: `barrel_views` (each standing barrel's frame), the drops
        (4-tuples, z 0) among the mobiles, and `thing_removed` (the pickups taken, the barrels gone).
PASS = NEW == OLD byte for byte on every frame (both spellings), AND the check is not vacuous: on at least one frame
P6 differs from NEW (R9's control: keywords that drew nothing would make the identity trivially true).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

import scenarios_v2 as S                                                     # noqa: E402
from p5_mobiles_identity import phase_of                                    # noqa: E402
from doomfj.monsters import MonsterViews                                     # noqa: E402
from doomfj.reference_model import GAME_RENDER_KW, SimState, build_scene    # noqa: E402

BASE_REF = "m7-p67"


def old_oracle_module(ref: str):
    """`reference_model.py` at `ref`, loaded as its own module -- an oracle with no P6 keyword"""
    import importlib.util
    import subprocess
    import tempfile
    src = subprocess.run(["git", "show", "%s:src/doomfj/reference_model.py" % ref], cwd=ROOT,
                         capture_output=True, check=True).stdout
    assert "barrel_views" not in src.decode("utf-8", "replace").split("def render_wall_frame")[1].split(")")[0]
    tmp = Path(tempfile.mkdtemp()) / "reference_model_p67_old.py"
    tmp.write_bytes(src)
    spec = importlib.util.spec_from_file_location("reference_model_p67_old", tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reference_model_p67_old"] = mod      # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default=str(ROOT / "scratchpad/gp/scenarios/combat_scenarios_v5.json"))
    ap.add_argument("--run", default="R2-barrel-hall")     # barrels, a drop and a removal in view
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--ref", default=BASE_REF)
    a = ap.parse_args(argv)
    t0 = time.time()
    doc = json.loads(Path(a.file).read_text())
    S.use_sight_rule(doc)
    run = next(r for r in doc["runs"] if r["name"] == a.run)
    w = S.start_world(run["setup"])
    from doomfj.config import GAME_CFG
    from doomfj.reference_model import ReferenceModel
    from doomfj.wad import WadFile
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    rm_new = ReferenceModel(GAME_CFG)
    old = old_oracle_module(a.ref)
    src = (ROOT / "src/doomfj/reference_model.py").read_text(encoding="utf-8")
    assert "barrel_views" in src.split("def render_wall_frame")[1].split(")")[0], "this tree has no P6 keywords"
    rm_old = old.ReferenceModel(GAME_CFG)
    mv = MonsterViews(rm_new, w.mw, w.mapname, art, w)
    ph = phase_of(w)
    first = len(run["keys"]) - a.frames
    scenes = {}
    n = same = p6_frames = p6_differs = 0
    for i, s in enumerate(run["keys"]):
        w.tic(S.str_to_keys(s))
        ws = w.ws
        assert [ws.px, ws.py, ws.pangle] == list(run["poses"][i]), "frame %d: the replay left the set" % i
        if i < first:
            continue
        key = tuple(sorted(w.heights_now.items()))
        if key not in scenes:
            scenes[key] = build_scene(w.mw, w.mw, w.mapname, dict(w.heights_now))
        sc = scenes[key]
        st = SimState(ws.px, ws.py, ws.pangle, w.mapname)
        mobs = ph.mobiles()
        p5mobs = [m for m in mobs if len(m) == 3]
        kw = dict(sprite_wad=art, thing_views=mv(ph, ws.px, ws.py), thing_positions=mv.positions(ph))
        p_old = bytes(rm_old.render_wall_frame(st, sc, mobiles=p5mobs, **kw, **GAME_RENDER_KW))
        p_new = bytes(rm_new.render_wall_frame(st, sc, mobiles=p5mobs, **kw, **GAME_RENDER_KW))
        p_empty = bytes(rm_new.render_wall_frame(st, sc, mobiles=p5mobs, barrel_views={}, thing_removed=[],
                                                 **kw, **GAME_RENDER_KW))
        p_p6 = bytes(rm_new.render_wall_frame(st, sc, mobiles=mobs, barrel_views=mv.barrel_views(ph),
                                              thing_removed=mv.hidden(ph), **kw, **GAME_RENDER_KW))
        n += 1
        same += p_old == p_new == p_empty
        d = sum(x != y for x, y in zip(p_p6, p_new))
        p6_frames += 1
        p6_differs += d > 0
        if p_old != p_new or p_old != p_empty:
            print("  frame %3d: !! DIFFERS (%d px)" % (i, sum(x != y for x, y in zip(p_old, p_new))))
        elif d:
            print("  frame %3d: identical; the P6 keywords draw %d px (drops %d, barrels %d, removed %d)"
                  % (i, d, len(mobs) - len(p5mobs), len(mv.barrel_views(ph)), len(mv.hidden(ph))))
    ok = same == n and p6_differs > 0
    print("P6 IDENTITY (%s, frames %d..%d): %d/%d frames identical to the unmodified oracle (%s) with the P6 keywords "
          "absent and empty; on %d of %d frames the P6 keywords drew -- %s (%.0f s)"
          % (a.run, first, len(run["keys"]) - 1, same, n, a.ref, p6_differs, p6_frames,
             "PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
