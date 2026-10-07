"""p8_identity.py -- M7 P8a (package A): the oracle's `view_drop` keyword keeps every existing picture.

    python scratchpad/gp/p8_identity.py [--run R2-barrel-hall] [--frames 60] [--ref 3fab6c1]

p67_identity.py's proof for P8a's keyword (docs/gp-final-plan.md 3.1 row A): one run of the frozen set v6 is replayed
on its own model ("full" / "full": scenarios_v2's replay, its poses checked against the file) and, at the last
`--frames` frames, the game view is rendered with the frame's real game state (monster views and positions, the
mobiles with the drops, the barrels' frames, the removed things):
  OLD    the UNMODIFIED oracle -- `reference_model.py` at the base ref (a commit on main: 3fab6c1, P6 + P7 merged; never
         a branch that can be deleted, #121-15), loaded as its own module -- which has no `view_drop`;
  NEW    this tree's oracle, the same keywords, `view_drop` ABSENT, and once more SPELLED 0;
  SUNK   this tree's oracle at view_drop = d (d cycling 1, 17, 34, 35 over the frames): the dying view.
PASS = NEW == OLD byte for byte on every frame (both spellings), AND the check is not vacuous: SUNK differs from NEW on
at least one frame of every d (R9's control: a keyword that moved nothing would make the identity trivially true).
Every other P8a keyword (package C's) is absent here: this script proves A's keyword alone.
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

BASE_REF = "3fab6c1"                 # main, P6 + P7 merged (m7-extras' base): an oracle without view_drop
DROPS = (1, 17, 34, 35)


def old_oracle_module(ref: str):
    """`reference_model.py` at `ref`, loaded as its own module (p67_identity's loader, without its P6 assert: the
    base here HAS P6's keywords) -- refused if it already knows `view_drop`"""
    import importlib.util
    import subprocess
    import tempfile
    src = subprocess.run(["git", "show", "%s:src/doomfj/reference_model.py" % ref], cwd=ROOT,
                         capture_output=True, check=True).stdout
    assert b"view_drop" not in src, "the base oracle (%s) already has view_drop" % ref
    tmp = Path(tempfile.mkdtemp()) / "reference_model_p8_old.py"
    tmp.write_bytes(src)
    spec = importlib.util.spec_from_file_location("reference_model_p8_old", tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reference_model_p8_old"] = mod      # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default=str(ROOT / "scratchpad/gp/scenarios/combat_scenarios_v6.json"))
    ap.add_argument("--run", default="R2-barrel-hall")     # barrels, drops and removals in view
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
    assert "view_drop" in src.split("def render_wall_frame")[1].split(")")[0], "this tree has no view_drop"
    rm_old = old.ReferenceModel(GAME_CFG)
    mv = MonsterViews(rm_new, w.mw, w.mapname, art, w)
    ph = phase_of(w)
    first = len(run["keys"]) - a.frames
    scenes = {}
    n = same = 0
    moved = dict.fromkeys(DROPS, 0)
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
        kw = dict(sprite_wad=art, thing_views=mv(ph, ws.px, ws.py), thing_positions=mv.positions(ph),
                  mobiles=ph.mobiles(), barrel_views=mv.barrel_views(ph), thing_removed=mv.hidden(ph),
                  **GAME_RENDER_KW)
        p_old = bytes(rm_old.render_wall_frame(st, sc, **kw))
        p_new = bytes(rm_new.render_wall_frame(st, sc, **kw))
        p_zero = bytes(rm_new.render_wall_frame(st, sc, view_drop=0, **kw))
        d = DROPS[n % len(DROPS)]
        p_sunk = bytes(rm_new.render_wall_frame(st, sc, view_drop=d, **kw))
        n += 1
        same += p_old == p_new == p_zero
        dpx = sum(x != y for x, y in zip(p_sunk, p_new))
        moved[d] += dpx > 0
        if p_old != p_new or p_old != p_zero:
            print("  frame %3d: !! DIFFERS (%d px absent, %d px spelled 0)"
                  % (i, sum(x != y for x, y in zip(p_old, p_new)), sum(x != y for x, y in zip(p_old, p_zero))))
        else:
            print("  frame %3d: identical; view_drop %2d moves %d px" % (i, d, dpx))
    ok = same == n and all(moved.values())
    print("P8a VIEW_DROP IDENTITY (%s, frames %d..%d): %d/%d frames identical to the unmodified oracle (%s) with "
          "view_drop absent and 0; the sunk frames that moved, per d: %s -- %s (%.0f s)"
          % (a.run, first, len(run["keys"]) - 1, same, n, a.ref, moved, "PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
