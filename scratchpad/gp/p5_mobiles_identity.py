"""p5_mobiles_identity.py -- M7 P5 (agent A): `render_wall_frame(mobiles=...)` keeps every existing picture.

    python scratchpad/gp/p5_mobiles_identity.py [--run R0-west-hall] [--frames 60]

One run of the frozen set v5 is replayed on the FULL model (scenarios_v2: the set's own replay, its poses checked
against the file) and, at the last `--frames` frames, the game screen's view is rendered three ways:
  OLD   the UNMODIFIED oracle -- `reference_model.py` as it stands at the base ref (git show), loaded as its own
        module -- with the frame's monster views and positions;
  NEW   this tree's oracle, the same keywords, `mobiles=[]` (and once more with `mobiles=None`);
  MOB   this tree's oracle with the frame's real mobiles (`MonsterPhase.mobiles()` on the replay's world).
PASS = NEW == OLD byte for byte on every frame (both spellings), AND the check is not vacuous: some rendered frame
holds a live mobile and MOB differs from NEW on at least one such frame (the mobiles draw -- R9's control: a
`mobiles=` that drew nothing would make the identity trivially true).
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

import json                                                                  # noqa: E402

import scenarios_v2 as S                                                     # noqa: E402
from doomfj.monsters import MonsterPhase, MonsterViews                       # noqa: E402
from doomfj.reference_model import GAME_RENDER_KW, SimState, build_scene    # noqa: E402

# issue #121 item 15: the UNMODIFIED oracle is P5's merge-base on main -- 470e39b, the merge of #118 (= f8dc9e8^1, the
# commit #120 merged onto). It was "m7-p5", the PR's own head, whose oracle already HAS `mobiles` (the signature assert
# below then fails); a commit on main never moves, a merged branch name may
BASE_REF = "470e39b"


def old_oracle_module(ref: str):
    src = subprocess.run(["git", "show", "%s:src/doomfj/reference_model.py" % ref], cwd=ROOT,
                         capture_output=True, check=True).stdout
    tmp = Path(tempfile.mkdtemp()) / "reference_model_old.py"
    tmp.write_bytes(src)
    spec = importlib.util.spec_from_file_location("reference_model_old", tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reference_model_old"] = mod          # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    assert "mobiles" not in src.decode("utf-8", "replace").split("def render_wall_frame")[1].split(")")[0]
    return mod


def base_render_kw(rm_old) -> dict:
    """GAME_RENDER_KW cut to the keywords the BASE oracle accepts (issue #121 item 15): the picture keywords that
    arrived after the base (P6+P7's `exempt_actors`, the actors rule, ...) are dropped on BOTH sides, so OLD and NEW
    render the same rule set and the identity is "nothing else moved since the base". The dropped keys are printed."""
    import inspect
    params = inspect.signature(rm_old.render_wall_frame).parameters
    dropped = sorted(k for k in GAME_RENDER_KW if k not in params)
    if dropped:
        print("  GAME_RENDER_KW keywords newer than the base, dropped on both sides: %s" % dropped)
    return {k: v for k, v in GAME_RENDER_KW.items() if k in params}


def phase_of(world) -> MonsterPhase:
    """a MonsterPhase view of an existing world (the replay's): views / positions / mobiles read it"""
    ph = MonsterPhase.__new__(MonsterPhase)
    from doomfj import gamedata as gd
    ph.world, ph.gd = world, gd
    return ph


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    # issue #121 item 15: v6, the standing frozen set -- v5 no longer replays on the model (the owner's tempo / turn /
    # fire changes moved its poses: "the replay left the set" at frame 2)
    ap.add_argument("--file", default=str(ROOT / "scratchpad/gp/scenarios/combat_scenarios_v6.json"))
    ap.add_argument("--run", default="R0-west-hall")
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
    rm_old = old.ReferenceModel(GAME_CFG)
    GKW = base_render_kw(rm_old)
    mv = MonsterViews(rm_new, w.mw, w.mapname, art, w)
    ph = phase_of(w)
    first = len(run["keys"]) - a.frames
    scenes = {}
    n = same = mob_frames = mob_differs = 0
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
        kw = dict(sprite_wad=art, thing_views=mv(ph, ws.px, ws.py), thing_positions=mv.positions(ph))
        p_old = bytes(rm_old.render_wall_frame(st, sc, **kw, **GKW))
        p_new = bytes(rm_new.render_wall_frame(st, sc, mobiles=[], **kw, **GKW))
        p_none = bytes(rm_new.render_wall_frame(st, sc, mobiles=None, **kw, **GKW))
        mobs = ph.mobiles()
        n += 1
        same += p_old == p_new == p_none
        if mobs:
            mob_frames += 1
            p_mob = bytes(rm_new.render_wall_frame(st, sc, mobiles=mobs, **kw, **GKW))
            d = sum(x != y for x, y in zip(p_mob, p_new))
            mob_differs += d > 0
            print("  frame %3d: %s  mobiles %s -> %d px drawn" % (
                i, "identical" if p_old == p_new == p_none else "!! DIFFERS", mobs, d))
        elif p_old != p_new or p_old != p_none:
            print("  frame %3d: !! DIFFERS (%d px)" % (i, sum(x != y for x, y in zip(p_old, p_new))))
    ok = same == n and mob_frames > 0 and mob_differs > 0
    print("MOBILES IDENTITY (%s, frames %d..%d): %d/%d frames identical to the unmodified oracle (%s) with "
          "mobiles=[] and None; %d frames held a live mobile, on %d of them the mobiles drew -- %s (%.0f s)"
          % (a.run, first, len(run["keys"]) - 1, same, n, a.ref, mob_frames, mob_differs,
             "PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
