"""p67_scene_dump.py -- M7 P6+P7 (the integrator): the SCENES some host tests drew from the frozen v5 replay, frozen
as INJECTED STATE (tests/fixtures/p67_scenes.json), so a test that needs a scene builds the scene instead of replaying
to it. v5's replays moved with the owner's 2026-10-05 requests (the monster tempo x2, the tap turn, fire x2), so the
frames those tests named no longer exist in a replay of the current model; the scene each one showed does, as state.

Run it ONCE against a checkout whose model still replays v5 (a model before the tempo / turn / fire changes -- e.g.
the package-B worktree at e8859ec, whose model is b866606's): it replays each scene's run to its frame and writes the
WHOLE WorldState (`as_dict`) and the run's setup. `load_scene` (below, used by the tests) builds a World of the
CURRENT model, applies the setup, and loads every field the current schema shares with the snapshot -- a field the
schema grew since keeps its level-start value.

    PYTHONPATH="<old>/src;<old>/scratchpad/gp" python scratchpad/gp/p67_scene_dump.py <old checkout> [out.json]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "fixtures" / "p67_scenes.json"
# (scene name, the v5 run, the tics replayed): the state AFTER that many tics
SCENES = (("aftermath57", "R0-aftermath", 58),     # test_actors_rule: the player on a corpse (frame 57)
          ("aftermath96", "R0-aftermath", 97))     # test_depth_order: two monsters of one leaf overlapping (frame 96)


def dump(old: Path, out: Path) -> None:
    for p in (old / "src", old / "scratchpad" / "gp"):
        sys.path.insert(0, str(p))
    import scenarios_v2 as S
    doc = json.loads((old / "scratchpad/gp/scenarios/combat_scenarios_v5.json").read_text(encoding="ascii"))
    S.use_sight_rule(doc)
    scenes = {"source": {"set": "combat_scenarios_v5.json", "keys_sha": doc.get("keys_sha"),
                         "sight_rule": doc.get("sight_rule"), "monster_tics": doc.get("monster_tics", 1),
                         "tool": "scratchpad/gp/p67_scene_dump.py",
                         "model_commit": subprocess.run(["git", "-C", str(old), "rev-parse", "--short", "HEAD"],
                                                        capture_output=True, text=True).stdout.strip()},
              "scenes": {}}
    for name, run_name, tics in SCENES:
        run = next(r for r in doc["runs"] if r["name"] == run_name)
        w = S.start_world(run["setup"])
        for k in run["keys"][:tics]:
            w.tic(S.str_to_keys(k))
        scenes["scenes"][name] = {"run": run_name, "tics": tics, "setup": run["setup"], "skill": S.SKILL,
                                  "state": w.ws.as_dict(), "digest": w.ws.digest()}
        print("%s: %s after %d tics, player (%d, %d)" % (name, run_name, tics, w.ws.px >> 16, w.ws.py >> 16))
    out.write_text(json.dumps(scenes, separators=(",", ":"), sort_keys=True) + "\n", encoding="ascii")
    print("wrote", out)


def load_scene(name: str, *, sight_rule: str = "seen", monster_tics: int = 1):
    """a World of the CURRENT model standing in scene `name` (its setup applied, then every shared field loaded)"""
    sys.path.insert(0, str(ROOT / "scratchpad" / "gp"))
    import scenarios_v2 as S
    sc = json.loads(OUT.read_text(encoding="ascii"))["scenes"][name]
    S.use_sight_rule({"sight_rule": sight_rule, "monster_tics": monster_tics})
    try:
        w = S.start_world(sc["setup"])
    finally:
        S.use_sight_rule({})
    have = w.ws.as_dict()
    for k, v in sc["state"].items():
        if k in have and (not isinstance(v, list) or len(v) == len(have[k])):
            have[k] = v
    w.ws.load(have)
    return w


if __name__ == "__main__":
    dump(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else OUT)
