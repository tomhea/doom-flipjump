"""M7 P8a I -- infighting's splice into the game tier, checked WITHOUT a game-tier emission: `monstercode.p31_parts` at
the "final" / "final" modes (test_p5_splice's stand-in anim index and static bank) and the leaves the emitter adds
around it (wall_renderer's call sites: decide_leaves(fight), ncd_leaf_lines(fight), the move's leaves, dp_go), against
the same program at "full" / "full":

  * every identifier the fight program's code READS is DEFINED in it -- or is one the "full" program reads without
    defining too (the emitter's own: viewx, the point location, the leaf lists ...): no fight register goes undeclared;
  * no label is defined twice that the "full" program defines once;
  * the parts say fight (p31's `fight`, mon_target two nibbles a slot in the decls), and "full" says nothing of it.
R9: a fight register dropped from the decls is caught."""
import re
from pathlib import Path

import pytest

from doomfj import monstercode as MC
from doomfj import wall_renderer as WR

ROOT = Path(__file__).resolve().parents[2]
_DEF = re.compile(r"^\s*([A-Za-z_][A-Za-z_0-9.]*)\s*:")
_TOK = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def _parts(mode, player):
    from doomfj.config import Config
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import ReferenceModel
    from doomfj.things import baked_thing_mask, drawable_things
    from doomfj.wad import WadFile
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    rm = ReferenceModel(Config())
    cache = {}
    drawable, draw_idx = drawable_things(rm, mw.things("E1M1"), art, cache)
    baked = baked_thing_mask(rm, bake_bsp(mw, "E1M1"), drawable, WR.MONSTER_TYPES)
    keep = sorted(i for i, b in zip(draw_idx, baked) if not b)
    rt = [mw.things("E1M1")[w] for w in keep]
    patches = WR.anim_patches(art, WR.anim_frames(mw, "E1M1"))
    anim = {k: (0x100 + 64 * i, rm.art_of_lump(art, lump, cache)[2], mir)
            for i, (k, (lump, mir)) in enumerate(sorted(patches.items()))}
    kinds = sorted({t.type for t in drawable_things(rm, mw.things("E1M1"), art, cache)[0]})
    static = ({k: 0x900 + i for i, k in enumerate(kinds)}, {k: 0xA00 + i for i, k in enumerate(kinds)},
              {k: rm.sprite_art(art, k, cache)[2] for k in kinds})
    return MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=WR.BOOT_SKILL, skills=WR.SKILLS,
                        cache=cache, mode=mode, player=player, static_bank=static)


def _program(p31, fight: bool, drop=None):
    """(code lines, decl lines) as the emitter composes the monsters' parts"""
    from doomfj import hurtcode, knockcode, monstermove as MM
    from doomfj.monsterdecide import decide_leaves
    from doomfj.world import CHASE_DEADZONE, NEWCHASEDIR_MAX_TRIES
    kw = {"fight": True} if fight else {}
    knock = bool(p31.get("knock"))
    code = (list(p31["tic_after_eye"]) + list(p31["leaves"]) + list(p31["select"]) + list(p31["rotation"])
            + MM.things_leaf_lines(p31["chase"]["slots_rt"], solid=p31["chase"]["solid"], hurt=True)
            + MM.ncd_leaf_lines(deadzone=CHASE_DEADZONE, max_tries=NEWCHASEDIR_MAX_TRIES, **kw)
            + MM.walk_leaf_lines(max_tries=NEWCHASEDIR_MAX_TRIES) + MM.chase_leaf_lines()
            + decide_leaves(justhit=True, full=True, knock=knock, **kw) + list(p31["decide_lines"])
            + list(p31["proj"]["lines"]) + list(p31["barrel"]["lines"]) + hurtcode.dp_lines(knock))
    # package K's cells and leaves (the merge of p8a-k): their DEFINITIONS count (kb_live, pj_z, pw_z, the slot stubs
    # kbs<m>, kb_go ...); their own reads are test_knock_fj's, not this splice's
    knock_defs = []
    if knock:
        w = p31["world"]
        knock_defs = (knockcode.decls(w.layout.nmon)
                      + knockcode.leaf_lines(knockcode.slots_of(w, [t for t, _r in p31["chase"]["slots_rt"]]),
                                             player_root="kq_proot", mon_root="kq_mroot"))
    decls = (list(p31["decls"]) + list(p31["decls_wake"]) + list(p31["proj"]["decls"]) + list(p31["barrel"]["decls"])
             + knock_defs)
    if drop:
        decls = [d for d in decls if not d.startswith(drop + ":")]
    return code, decls


def _defined(lines):
    out = []
    for ln in lines:
        for part in ln.split("\n"):
            m = _DEF.match(part)
            if m and not part.strip().startswith("//"):
                out.append(m.group(1))
    return out


def _read(code):
    """identifiers in operand position of every instruction line (the macro name and `dw` / `w` excluded)"""
    out = set()
    for ln in code:
        for part in ln.split("\n"):
            s = part.split("//")[0].strip()
            if not s or s.endswith(":") or s.startswith(";"):
                if s.startswith(";"):
                    out.add(s[1:].strip())
                continue
            if _DEF.match(s):
                s = s[s.index(":") + 1:].strip()
                if not s:
                    continue
            head, _sp, rest = s.partition(" ")
            out.update(t for t in _TOK.findall(rest) if t not in ("dw", "w"))
    return out


@pytest.fixture(scope="module")
def both():
    return _parts("full", "full"), _parts("final", "final")


def test_the_parts_say_fight(both):
    full, final = both
    assert final.get("fight") and not full.get("fight")
    decl = next(d for d in final["decls_wake"] if d.startswith("mon_target:"))
    assert decl.startswith("mon_target: hex.vec %d" % (2 * final["nmon"])), decl
    decl = next(d for d in full["decls_wake"] if d.startswith("mon_target:"))
    assert decl.startswith("mon_target: hex.vec %d" % full["nmon"]), decl


def _undefined(p31, fight, drop=None):
    code, decls = _program(p31, fight, drop)
    defined = set(_defined(code + decls))
    tables = set(re.findall(r"ns (\w+) \{", "\n".join(p31["tables"] + [p31["mview"], p31["mrot"]]
                                                       + p31["proj"]["tables"] + p31["barrel"]["tables"])))
    return {t for t in _read(code) if t not in defined and t not in tables}, code, decls


def test_every_fight_register_is_declared(both):
    full, final = both
    ext_full, _c, _d = _undefined(full, False)
    ext_final, _c, _d = _undefined(final, True)
    new = sorted(ext_final - ext_full)
    assert not new, "the fight program reads identifiers nothing defines: %s" % new


def test_no_label_is_defined_twice(both):
    full, final = both
    def dups(p31, fight):
        code, decls = _program(p31, fight)
        names = _defined(code + decls)
        seen, out = set(), set()
        for n in names:
            if n in seen:
                out.add(n)
            seen.add(n)
        return out
    new = sorted(dups(final, True) - dups(full, False))
    assert not new, "defined twice in the fight program: %s" % new


def test_control_a_dropped_register_is_caught(both):
    full, final = both
    ext_full, _c, _d = _undefined(full, False)
    ext, _c, _d = _undefined(final, True, drop="hs_bd")
    assert "hs_bd" in ext - ext_full
