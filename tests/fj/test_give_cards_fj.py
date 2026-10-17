"""M8 F4 (doomfj.lootcode): E1M2's new GIVE routines on the real flipjump engine -- `give_6` / `give_13` (the yellow
and red cards), `give_2013` (the soulsphere) and `give_2026` (the computer map), with every other give E1M2 holds, the
very text the emitter splices (`give_lines(stats=True)`, the game tier's) -- against the model's own `combat._touch`
(the reach test passed), record by record in ONE image, on E1M2's World.

combat._touch (p_inter.c P_TouchSpecialThing) is the rule mirrored:
  * a card (P_GiveCard): not held -> bonuscount = BONUSADD (SET, the flash) and the card's cell 1; held -> nothing
    (the card is still taken: P_TouchSpecialThing removes it); then, taken, bonuscount += BONUSADD (saturating at 255,
    the stub's `pk_bonus`, run here as `lootcode._bonus_lines`) -- so a new card ends at 12, a held one adds 6;
  * the soulsphere: health += 100, capped at 200 (deh_soul_health / deh_max_soul), always taken, a COUNTITEM;
  * the computer map: P_GivePower(pw_allmap), refused only when held -- no level holds two (World asserts it): always
    taken, a COUNTITEM, no other effect (no automap: docs/handoff-e1m2.md 3).
Each record pokes the player's cells identically on both sides -- health around 1, 99..101 and 199..200 (the soul's
cap), armor, every card held or not, the bonus count around its cap, the item count -- then gives one kind and runs the
bonus lines when taken. After every record the cells, the three card cells and `gv_ok` are printed.

R9 (MUTANTS), each must part from the model on some record: the yellow card without the flash; the red card writing
the yellow card's cell; a held red card refused; the blue card reading the yellow cell (the shared branch's cell
choice); the soulsphere capped at 100, giving 10, not counted; the computer map refused, not counted.
"""
import random
import re
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import hurtcode as H
from doomfj import lootcode as L
from doomfj import weaponcode as WC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.wad import WadFile
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
MAPWAD = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
N = 400
NEW = (6, 13, 2013, 2026)
CARD = {5: gd.IT_BLUECARD, 6: gd.IT_YELLOWCARD, 13: gd.IT_REDCARD}
CELLS = (("p_hp", 3), ("p_ar", 2), ("p_at", 1), ("am_clip", 3), ("am_shell", 3), ("am_cell", 3), ("am_misl", 3),
         ("p_bp", 1), ("wp_own", 6), ("wp_pend", 1), ("p_str", 4), ("p_bc", 2), ("pcard", 1), ("pcard_y", 1),
         ("pcard_r", 1), ("gv_ok", 1), ("st_item", 2))
needs_map = pytest.mark.skipif(not MAPWAD.exists(), reason="needs tests/fixtures/freedoom_e1m2.wad")


def _world():
    return World(WadFile.from_path(str(MAPWAD)), "E1M2", skill=gd.SK_HARD, monsters="idle", player="fire")


def _records(w):
    """[(pokes, kind, dropped)]: E1M2's every give, the new ones and the blue card more often"""
    rnd = random.Random(0xE12)
    kinds = L.give_kinds(w)
    new = [k for k in kinds if k[0] in NEW + (5,) and not k[1]]         # the blue card's branch too
    out = []
    for r in range(N):
        if r < 4 * len(kinds):
            kind, dropped = kinds[r % len(kinds)]
        else:
            kind, dropped = rnd.choice(new * 3 + kinds)
        bp = rnd.choice((0, 0, 1))
        ammo = []
        for a in range(gd.NUMAMMO):
            cap = gd.MAXAMMO[a] * (2 if bp else 1)
            ammo.append(rnd.choice((0, 0, cap, cap, cap - 1, gd.MAXAMMO[a], rnd.randint(0, cap), 1)))
        owned = {gd.WP_FIST: 1, gd.WP_PISTOL: int(rnd.random() < 0.9), gd.WP_SHOTGUN: rnd.choice((0, 1)),
                 gd.WP_CHAINSAW: rnd.choice((0, 1)), gd.WP_MISSILE: 0, gd.WP_CHAINGUN: 0}
        ready = rnd.choice([x for x in WC.WEAPONS if owned[x]])
        armor = rnd.choice((0, 0, 1, 99, 100, 101, 199, 200, rnd.randint(0, 200)))
        pokes = {"p_health": rnd.choice((1, 1, 50, 99, 100, 101, 150, 199, 200, rnd.randint(1, 200))),
                 "p_armor": armor, "p_armortype": rnd.choice((0, 1, 2)) if armor else 0,
                 "ammo": ammo, "p_backpack": bp, "owned": owned, "p_ready": ready,
                 "p_pending": rnd.choice((gd.WP_NOCHANGE, gd.WP_NOCHANGE, rnd.choice(WC.WEAPONS))),
                 "p_strength": rnd.choice((0, 0, 1, rnd.randint(1, 0xFFFF))),
                 "p_bonuscount": rnd.choice((0, 6, 249, 250, 251, 255, rnd.randint(0, 255))),
                 "cards": [rnd.choice((0, 1)) for _ in CARD],
                 "items": (0, 9, 47, 98, 13)[r % 5]}
        out.append((pokes, kind, dropped))
    return out


def _apply(w, pokes):
    ws = w.ws
    for f in ("p_health", "p_armor", "p_armortype", "p_backpack", "p_ready", "p_pending", "p_strength",
              "p_bonuscount"):
        setattr(ws, f, pokes[f])
    for a in range(gd.NUMAMMO):
        ws.p_ammo[a] = pokes["ammo"][a]
    for x in range(gd.NUMWEAPONS):
        ws.p_owned[x] = pokes["owned"].get(x, 0)
    for k, v in zip(CARD, pokes["cards"]):
        ws.p_cards[CARD[k]] = v


def _row(ws, taken, items) -> str:
    own = sum(ws.p_owned[x] << (4 * WC.OWN[x]) for x in WC.WEAPONS)
    vals = [ws.p_health & 0xFFF, ws.p_armor, ws.p_armortype, ws.p_ammo[gd.AM_CLIP], ws.p_ammo[gd.AM_SHELL],
            ws.p_ammo[gd.AM_CELL], ws.p_ammo[gd.AM_MISL], ws.p_backpack, own, ws.p_pending, ws.p_strength,
            ws.p_bonuscount, *(ws.p_cards[CARD[k]] for k in CARD), int(taken), items]
    return "".join("%0*x" % (n, v) for (_c, n), v in zip(CELLS, vals))


def _expected(w, records):
    from doomfj.statcode import counts_item
    lines = []
    for pokes, kind, dropped in records:
        _apply(w, pokes)
        taken = w._touch(kind, dropped, 0, 0)
        lines.append(_row(w.ws, taken, pokes["items"] + int(bool(taken) and counts_item(kind, dropped))))
    return ("\n".join(lines) + "\n").encode()


MUTANTS = {
    "ycard_noflash": (r"(hex\.if1 1, pcard_y, give_6_ok\n)    hex\.set 2, p_bc, 6\n", r"\1"),
    "rcard_ycell": (r"(    hex\.set 2, p_bc, 6\n    hex\.set 1, )pcard_r", r"\1pcard_y"),
    "rcard_held_refused": (r"hex\.if1 1, pcard_r, give_13_ok\n", "hex.if1 1, pcard_r, give_13_no\n"),
    "bcard_ycell": (r"(give_5:\n    hex\.if1 1, )pcard,", r"\1pcard_y,"),
    "soul_cap100": (r"(    hex\.add_constant 3, p_hp, 100\n    hex\.set 3, gv_c, )200", r"\g<1>100"),
    "soul_add10": (r"(give_2013:\n    hex\.add_constant 3, p_hp, )100", r"\g<1>10"),
    "soul_nocount": (r"(  give_2013_ok:\n)    hex\.inc 2, st_item\n", r"\1"),
    "pmap_refused": (r"(give_2026:\n    );give_2026_ok", r"\1;give_2026_no"),
    "pmap_nocount": (r"(  give_2026_ok:\n)    hex\.inc 2, st_item\n", r"\1"),
}


def _program(w, mut=None):
    gives = []
    for kind, dropped in L.give_kinds(w):
        gives += L.give_lines(kind, dropped, stats=True)
    for a in range(gd.NUMAMMO):
        gives += L.give_ammo_lines(a)
    text = "\n".join(gives) + "\n"
    if mut:
        pat, new = MUTANTS[mut]
        text, n = re.subn(pat, new, text)
        assert n == 1, "the mutant %s matches the emitted text %d times, not once" % (mut, n)
    wstart = WC.level_start(w.mw, "E1M2")
    decls = (L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(wstart, WC.weapon_states(), WC.overlay_frames())
             + ["pcard: hex.vec 1", "st_item: hex.vec 2"] + L.card_decls(w))
    tables = [generate_dispatch_table_fj("amcap", L.amcap_values(), index_nibbles=2, result_nibbles=3)]
    return decls, text, tables


def _build(tmp_path, name, mut=None):
    w = _world()
    records = _records(w)
    nib = {"p_health": ("p_hp", 3), "p_armor": ("p_ar", 2), "p_armortype": ("p_at", 1), "p_backpack": ("p_bp", 1),
           "p_ready": ("wp_rdy", 1), "p_pending": ("wp_pend", 1), "p_strength": ("p_str", 4),
           "p_bonuscount": ("p_bc", 2)}
    body = ["stl.startup_and_init_all"]
    for pokes, kind, dropped in records:
        for f, (c, n) in nib.items():
            body.append("hex.set %d, %s, %d" % (n, c, pokes[f]))
        for a in range(gd.NUMAMMO):
            body.append("hex.set 3, %s, %d" % (L.AMMO_CELL[a], pokes["ammo"][a]))
        body.append("hex.set %d, wp_own, %d" % (len(WC.WEAPONS),
                                                 sum(pokes["owned"][x] << (4 * WC.OWN[x]) for x in WC.WEAPONS)))
        body += ["hex.set 1, %s, %d" % (L.CARD_CELL[k], v) for k, v in zip(CARD, pokes["cards"])]
        body += ["hex.set 1, gv_ok, 7", "hex.set 2, st_item, %d" % pokes["items"],
                 "stl.fcall give_%d%s, gv_ret" % (kind, "d" if dropped else ""),
                 "stl.fcall bonus_leaf, bl_ret"]
        body += ["hex.print_as_digit %d, %s, 0" % (n, c) for c, n in CELLS] + ["stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = _program(w, mut)
    bonus = ["hex.if0 1, gv_ok, hb_skip", *L._bonus_lines("hb"), "hb_skip:"]
    prog = "\n".join(body + decls + ["bl_ret: hex.vec w/4", "bonus_leaf:"] + bonus + ["stl.fret bl_ret"]) + "\n"
    prog += text + "\n".join(tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(_world(), records)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


@needs_map
def test_the_records_exercise_every_new_give():
    """the model's outcomes: E1M2 holds every new kind (and the blue card); each card both new (the flash SET: 12
    after the bonus) and held (+6 only); the soulsphere capped and not; every new kind always taken"""
    w = _world()
    kinds = {k for k, _d in L.give_kinds(w)}
    assert set(NEW) | {5} <= kinds, kinds
    assert L.card_cells(w) == ("pcard_y", "pcard_r")
    seen = {k: set() for k in NEW + (5,)}
    flash = {k: [0, 0] for k in CARD}
    soul = [0, 0]
    for pokes, kind, dropped in _records(w):
        _apply(w, pokes)
        held = pokes["cards"][list(CARD).index(kind)] if kind in CARD else None
        bc = pokes["p_bonuscount"]
        taken = w._touch(kind, dropped, 0, 0)
        if kind in seen:
            seen[kind].add(taken)
        if kind in CARD:
            flash[kind][held] += 1
            assert w.ws.p_cards[CARD[kind]] == 1
            assert w.ws.p_bonuscount == (min(bc + 6, 255) if held else 12), (kind, held, bc)
        if kind == 2013:
            soul[pokes["p_health"] + 100 > 200] += 1
    assert all(v == {True} for v in seen.values()), seen
    assert all(a >= 5 and b >= 5 for a, b in flash.values()), flash
    assert soul[0] >= 5 and soul[1] >= 5, soul


@needs_map
def test_the_new_gives_follow_the_model(tmp_path):
    assert _run(tmp_path, "give_e1m2"), "the fj gives parted from the model's _touch on E1M2"


@needs_map
@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_give_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "give_e1m2_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
