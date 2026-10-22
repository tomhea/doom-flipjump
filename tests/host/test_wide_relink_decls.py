"""M8 l12fix -- THE EMITTER declares the relink's scratch at the LIST width.

`sim.leaf_link_w` / `sim.leaf_unlink_w` (src/fj/sim_wide.fj, a wide-list map's relink) move, read and compare `ll_enc`,
`ll_v` and `ll_nxt` at 3 nibbles. `monstercode.p31_parts` emitted `things.LEAF_LINK_DECLS` (2 nibbles) whatever the
map's Config.LIST_ID_BITS, so in E1M1 built at 12 bits each register's third nibble was the next one's first: the
relink compared and indexed through another register's nibble with every id below 256, and the screen device died
~20 walk frames into m2_std_gate (a monster relinking between leaves). tests/fj/test_wide_ids_fj.py RUNS the effect of
the width (and its 2-nibble control); this holds the game tier's emitted declarations to it:

  * at 12 bits every register a `_w` twin operates on at n nibbles -- read off sim_wide.fj's own text (`hex.<op> n,
    reg`, a `hex.read_cell` / `hex.write_cell` operand at the wide table's 3) -- is declared at >= n nibbles in the
    parts p31_parts returns;
  * at 8 bits the declarations are things.LEAF_LINK_DECLS' text, as before (E1M1 / E1M2 unchanged).

CONTROL (R9): things.leaf_link_decls patched back to the 2-nibble one -- what the emitter did -- must fail the check.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
TWINS = ("leaf_link_w", "leaf_unlink_w")


def _twin_widths() -> dict:
    """{register: the widest nibble count the relink twins use it at}, from sim_wide.fj's text"""
    text = (ROOT / "src" / "fj" / "sim_wide.fj").read_text(encoding="utf-8")
    out = {}
    for name in TWINS:
        body = text[text.index("def %s " % name):]
        body = body[:body.index("\n      done:\n")]
        for n, regs in re.findall(r"hex\.\w+ (\d+), ([\w, +*]+)", body):
            for r in regs.split(","):
                r = r.strip()
                if r.startswith("ll_"):
                    out[r] = max(out.get(r, 0), int(n))
        for regs in re.findall(r"hex\.(?:read_cell|write_cell) (\w+), (\w+)", body):
            for r in regs:
                if r in ("ll_v", "ll_nxt", "ll_enc"):
                    out[r] = max(out.get(r, 0), 3)
    assert {"ll_enc", "ll_v", "ll_nxt"} <= set(out), out
    return out


def _decls(obj, acc):
    if isinstance(obj, str):
        for m in re.finditer(r"^\s*(ll_\w+):\s*hex\.vec\s+([\w/]+)", obj, re.MULTILINE):
            acc.setdefault(m.group(1), []).append(m.group(2))
    elif isinstance(obj, dict):
        for v in obj.values():
            _decls(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _decls(v, acc)
    return acc


@pytest.fixture(scope="module")
def emitted():
    if not ART.exists():
        pytest.skip("needs assets/freedoom1.wad (the sprite art)")
    from doomfj import monstercode as MC
    from doomfj import wall_renderer as WR
    from doomfj.config import Config
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import ReferenceModel
    from doomfj.things import baked_thing_mask, drawable_things
    from doomfj.wad import WadFile
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ART))
    rm = ReferenceModel(Config())
    cache = {}
    drawable, draw_idx = drawable_things(rm, mw.things("E1M1"), art, cache)
    baked = baked_thing_mask(rm, bake_bsp(mw, "E1M1"), drawable, WR.MONSTER_TYPES)
    rt = [mw.things("E1M1")[w] for w in sorted(i for i, b in zip(draw_idx, baked) if not b)]
    patches = WR.anim_patches(art, WR.anim_frames(mw, "E1M1"))
    anim = {k: (0x100 + 64 * i, rm.art_of_lump(art, lump, cache)[2], mir)
            for i, (k, (lump, mir)) in enumerate(sorted(patches.items()))}
    kinds = sorted({t.type for t in drawable})
    static = ({k: 0x900 + i for i, k in enumerate(kinds)}, {k: 0xA00 + i for i, k in enumerate(kinds)},
              {k: rm.sprite_art(art, k, cache)[2] for k in kinds})

    def run(list_bits):
        # the game tier's modes (wall_renderer's), as emit_wall_renderer calls it
        return MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=WR.BOOT_SKILL,
                            skills=WR.SKILLS, cache=cache, mode=WR.MONSTER_MODE, player=WR.PLAYER_MODE,
                            static_bank=static, list_bits=list_bits)
    return run


def _check_wide(parts):
    d = _decls(parts, {})
    bad = {}
    for reg, need in _twin_widths().items():
        widths = d.get(reg, [])
        assert len(widths) == 1, (reg, widths, "declared once")
        if widths[0] != "w/4" and int(widths[0]) < need:
            bad[reg] = (widths[0], need)
    return bad


def test_the_wide_relinks_scratch_is_declared_at_its_width(emitted):
    assert _check_wide(emitted(12)) == {}


def test_the_8_bit_relink_scratch_is_unchanged(emitted):
    from doomfj.things import LEAF_LINK_DECLS
    d = _decls(emitted(8), {})
    want = _decls(LEAF_LINK_DECLS, {})
    assert {r: d.get(r) for r in want} == want


def test_control_the_two_nibble_scratch_is_caught(emitted, monkeypatch):
    """R9: the emitter's old declaration (LEAF_LINK_DECLS at any width) fails the check, naming the three registers"""
    import doomfj.things as T
    narrow = T.leaf_link_decls
    monkeypatch.setattr(T, "leaf_link_decls", lambda nib=2: narrow(2))
    assert set(_check_wide(emitted(12))) == {"ll_enc", "ll_v", "ll_nxt"}
