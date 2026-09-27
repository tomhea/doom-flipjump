"""M7 P1.5 review -- the host-side numbers docs/gp-skill-menu.md quotes, regenerated with a log.

No fj, no build. The committed output is docs/ship-evidence/p15_skill_census.log.

  A. the thing universe per skill on E1M1 -- the design's section 1 table (things / pickups /
     monsters / decor / barrels) for the drawable list as it was before the rung (art only), the
     multiplayer-only things, the single-player union (`things.drawable_things`), and each skill;
     which things change with the skill; which monsters hard does not spawn.
  B. the review's finding 3 -- under the list the hosted drivers built BY HAND (art only, no
     `single_player`), is any multiplayer-only thing a RUNTIME thing (a monster, or in a monster's
     leaf: `baked_thing_mask`), and does any carry a visibility slot? Those two decide what a
     hand-built list does to the hosted wire now that the emitter's list is the single-player one:
     the runtime block (positions + bindings) and the visibility block.
  C. `--pixels`: the three skills' NEW GAME frames in the oracle, pairwise pixel differences -- the
     frame m3_gate renders for each (the spawn view, the shut scene, GAME_RENDER_KW, the skill's
     `skill_hidden`). The only part that renders (three oracle frames).

Run from the repo root:  PYTHONPATH=src python scratchpad/gp/p15_skill_census.py [--pixels]
"""
import argparse
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config                                          # noqa: E402
from doomfj.gamedata import SKILL_NAMES                                   # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (GAME_RENDER_KW, MONSTER_TYPES,        # noqa: E402
                                    VANISHABLE_TYPES, ReferenceModel, build_scene, spawn_state)
from doomfj.things import (baked_thing_mask, drawable_things, single_player,  # noqa: E402
                           skill_absent, skill_hidden, vanishable_slots)
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import BOOT_SKILL, SKILLS                       # noqa: E402

BARREL = 2035
CLASSES = ("pickups", "monsters", "decor", "barrels")
NAME = {v: k for k, v in SKILL_NAMES.items()}


def cls(t) -> str:
    """the design's classes: monsters, the barrel, the other vanishable types (pickups), the rest"""
    if t.type in MONSTER_TYPES:
        return "monsters"
    if t.type == BARREL:
        return "barrels"
    return "pickups" if t.type in VANISHABLE_TYPES else "decor"


def row(label, things) -> str:
    n = {c: sum(1 for t in things if cls(t) == c) for c in CLASSES}
    return "| %s | %d | %s |" % (label, len(things), " | ".join(str(n[c]) for c in CLASSES))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--art", default="assets/freedoom1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--pixels", action="store_true", help="part C: render the three NEW GAME frames")
    args = ap.parse_args()
    mw = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.art))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(mw, args.map)
    allt = mw.things(args.map)
    print("wad %s, art %s, map %s; skills %s, boot %s"
          % (args.wad, args.art, args.map, [NAME[s] for s in SKILLS], NAME[BOOT_SKILL]))

    # -- A: the table -------------------------------------------------------------------------------
    # the list BEFORE the rung, computed the old way ON PURPOSE (art only): it is what this reports
    arted = [t for t in allt if rm.sprite_art(art, t.type, {}) is not None]
    drawable, _idx = drawable_things(rm, allt, art)
    mp_only = [t for t in arted if not single_player(t)]
    assert len(arted) - len(mp_only) == len(drawable), "the union is not art-only minus MP-only"
    absent = {s: skill_absent(drawable, s) for s in SKILLS}
    print("\nA. the thing universe (docs/gp-skill-menu.md section 1)")
    print("| | things | %s |" % " | ".join(CLASSES))
    print("|---|---|%s" % ("---|" * len(CLASSES)))
    print(row("drawable before the rung (art only)", arted))
    print(row("multiplayer-only (leave the image)", mp_only))
    print(row("the single-player union (the image)", drawable))
    for s in SKILLS:
        print(row(NAME[s], [t for i, t in enumerate(drawable) if i not in absent[s]]))
    print("(classes: monsters = MONSTER_TYPES, barrels = type %d, pickups = the other "
          "VANISHABLE_TYPES, decor = the rest)" % BARREL)
    mp_types = {}
    for t in mp_only:
        mp_types[t.type] = mp_types.get(t.type, 0) + 1
    print("multiplayer-only things by type: %s" % dict(sorted(mp_types.items())))
    varies = frozenset().union(*absent.values()) - frozenset.intersection(*absent.values())
    by = {c: sum(1 for i in varies if cls(drawable[i]) == c) for c in CLASSES}
    mons = [i for i, t in enumerate(drawable) if t.type in MONSTER_TYPES]
    print("things that change with the skill: %d -- %s" % (len(varies), by))
    print("monsters on every skill: %d of %d" % (sum(1 for i in mons if i not in varies), len(mons)))
    for s in SKILLS:
        gone = sorted({drawable[i].type for i in absent[s] if drawable[i].type in MONSTER_TYPES})
        print("monsters %s does not spawn: %d, types %s"
              % (NAME[s], sum(1 for i in absent[s] if drawable[i].type in MONSTER_TYPES), gone))

    # -- B: a hand-built (art-only) list against the emitter's --------------------------------------
    print("\nB. the hosted wire under a hand-built (art-only) drawable list, against the emitter's")
    baked_old = baked_thing_mask(rm, cmap, arted, MONSTER_TYPES)
    baked_new = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    rt_old = [t for t, b in zip(arted, baked_old) if not b]
    rt_new = [t for t, b in zip(drawable, baked_new) if not b]
    vis_old = vanishable_slots(arted, baked_old, VANISHABLE_TYPES)
    vis_new = vanishable_slots(drawable, baked_new, VANISHABLE_TYPES)
    mp_ids = {id(t) for t in mp_only}
    mp_runtime = [t for t in rt_old if id(t) in mp_ids]
    mp_flagged = [arted[i] for i in vis_old if id(arted[i]) in mp_ids]
    print("multiplayer-only things that are RUNTIME under the hand-built list: %d %s"
          % (len(mp_runtime), [(t.type, t.x, t.y) for t in mp_runtime]))
    print("multiplayer-only things with a VISIBILITY slot under it: %d (types %s)"
          % (len(mp_flagged), sorted({t.type for t in mp_flagged})))
    print("runtime things: hand-built %d, emitter %d; the same things in the same order: %s"
          % (len(rt_old), len(rt_new), [id(t) for t in rt_old] == [id(t) for t in rt_new]))
    print("visibility slots: hand-built %d, emitter %d" % (len(vis_old), len(vis_new)))
    kinds_all = {t.type for t in arted}
    kinds_sp = {t.type for t in drawable}
    print("sprite types on the map only among multiplayer-only things: %s"
          % sorted(kinds_all - kinds_sp))

    # -- C: the NEW GAME frames ---------------------------------------------------------------------
    if args.pixels:
        print("\nC. the NEW GAME frame at each skill (the spawn view; m3_gate's oracle render)")
        scene = build_scene(mw, mw, args.map)
        spawn = spawn_state(mw, args.map)
        pics = {}
        for s in SKILLS:
            hid = skill_hidden(rm, allt, art, s)
            pics[s] = bytes(rm.render_wall_frame(spawn, scene, sprite_wad=art, thing_hidden=hid,
                                                 **GAME_RENDER_KW))
            print("%-6s hides %d drawable things" % (NAME[s], len(hid)))
        for a, b in combinations(SKILLS, 2):
            print("%s / %s: %d px differ" % (NAME[a], NAME[b],
                                             sum(p != q for p, q in zip(pics[a], pics[b]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
