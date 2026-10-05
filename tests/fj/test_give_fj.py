"""M7 P6 (doomfj.lootcode): every GIVE routine on the real flipjump engine -- `give_<type>` / `give_<type>d` and the
shared P_GiveAmmo leaves `ga<a>`, the very text the emitter splices -- against the model's own `combat._touch`
(the reach test passed: item z == the player's floor), record by record in ONE image.

Each record pokes the player's cells identically on both sides -- health around 100 and 200, armor around 100 and
200 with every armor type, every ammo count at 0, at its cap, one below and at the un-doubled cap with a backpack,
the backpack, the owned weapons, the ready and pending weapon, berserk, the bonus count around its 255 cap and the
blue card -- then gives one of the map's 17 types or a dropped clip / shotgun and runs the stub's bonus lines
(`lootcode._bonus_lines`) when the give says taken. After every record the cells and `gv_ok` are printed.

R9 (MUTANTS): each must part from the model on some record -- the health bonus capped at 100, P_GiveBody refusing only
above 100, the backpack not doubling the caps (amcap), no auto-switch from an empty clip, a backpack that is not
kept, an owned shotgun always taken, a dropped clip that gives a whole one, the bonus count wrapping, a card that
does not set the flash, an armor bonus that leaves no armor type, a chainsaw / berserk that pends nothing.
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
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 700
CELLS = (("p_hp", 3), ("p_ar", 2), ("p_at", 1), ("am_clip", 3), ("am_shell", 3), ("am_cell", 3), ("am_misl", 3),
         ("p_bp", 1), ("wp_own", 4), ("wp_pend", 1), ("p_str", 4), ("p_bc", 2), ("pcard", 1), ("gv_ok", 1))


def _world():
    return World(skill=gd.SK_HARD, monsters="idle", player="fire")


def _records(w):
    """[(pokes {ws field: value}, kind, dropped)]"""
    rnd = random.Random(0x6B)
    kinds = L.give_kinds(w)
    out = []
    for r in range(N):
        kind, dropped = kinds[r % len(kinds)] if r < 4 * len(kinds) else rnd.choice(kinds)
        bp = rnd.choice((0, 0, 1))
        ammo = []
        for a in range(gd.NUMAMMO):
            cap = gd.MAXAMMO[a] * (2 if bp else 1)
            ammo.append(rnd.choice((0, 0, cap, cap, cap - 1, gd.MAXAMMO[a], rnd.randint(0, cap), 1)))
        owned = {gd.WP_FIST: 1, gd.WP_PISTOL: int(rnd.random() < 0.9), gd.WP_SHOTGUN: rnd.choice((0, 1)),
                 gd.WP_CHAINSAW: rnd.choice((0, 1))}
        ready = rnd.choice([x for x in WC.WEAPONS if owned[x]])
        pend = rnd.choice((gd.WP_NOCHANGE, gd.WP_NOCHANGE, gd.WP_NOCHANGE, rnd.choice(WC.WEAPONS)))
        armor = rnd.choice((0, 0, 1, 99, 100, 101, 199, 200, rnd.randint(0, 200)))
        pokes = {"p_health": rnd.choice((1, 50, 99, 100, 100, 101, 150, 199, 200, rnd.randint(1, 200))),
                 "p_armor": armor, "p_armortype": rnd.choice((0, 1, 2)) if armor else rnd.choice((0, 0, 1)),
                 "ammo": ammo, "p_backpack": bp, "owned": owned, "p_ready": ready, "p_pending": pend,
                 "p_strength": rnd.choice((0, 0, 1, rnd.randint(1, 0xFFFF))),
                 "p_bonuscount": rnd.choice((0, 6, 249, 250, 251, 255, rnd.randint(0, 255))),
                 "card": rnd.choice((0, 0, 1))}
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
    ws.p_cards[gd.IT_BLUECARD] = pokes["card"]


def _row(ws, taken) -> str:
    own = sum(ws.p_owned[x] << (4 * WC.OWN[x]) for x in WC.WEAPONS)
    vals = [ws.p_health & 0xFFF, ws.p_armor, ws.p_armortype, ws.p_ammo[gd.AM_CLIP], ws.p_ammo[gd.AM_SHELL],
            ws.p_ammo[gd.AM_CELL], ws.p_ammo[gd.AM_MISL], ws.p_backpack, own, ws.p_pending, ws.p_strength,
            ws.p_bonuscount, ws.p_cards[gd.IT_BLUECARD], int(taken)]
    return "".join("%0*x" % (n, v) for (_c, n), v in zip(CELLS, vals))


def _expected(w, records):
    lines = []
    for pokes, kind, dropped in records:
        _apply(w, pokes)
        taken = w._touch(kind, dropped, 0, 0)
        lines.append(_row(w.ws, taken))
    return ("\n".join(lines) + "\n").encode()


def _amcap_nobp():
    return generate_dispatch_table_fj("amcap", [gd.MAXAMMO[i & 15] if (i & 15) < gd.NUMAMMO else 0 for i in range(32)],
                                      index_nibbles=2, result_nibbles=3)


MUTANTS = {
    "bon_cap100": (r"(    hex\.inc 3, p_hp\n    hex\.set 3, gv_c, )200", r"\g<1>100"),
    "body_ge": (r"hex\.cmp 3, p_hp, gv_c, (give_2012gb), (give_2012_no), (give_2012_no)", r"hex.cmp 3, p_hp, gv_c, \1, \1, \3"),
    "amcap_nobp": None,
    "noswitch": (r"(  ga0_sw:\n)    hex\.set 1, wp_pend, %d\n" % gd.WP_PISTOL, r"\1"),
    "bpak_nobp": (r"(give_8:\n)    hex\.set 1, p_bp, 1\n", r"\1"),
    "shot_owned": (r"(hex\.if0 1, wp_own \+ 2\*dw, give_2001_new\n)    stl\.fret gv_ret", r"\1    ;give_2001_ok"),
    "drop_whole": (r"(give_2007d:\n    hex\.set 3, ga_n, )5", r"\g<1>10"),
    "bc_wrap": (r"(hex\.cmp 2, p_bc, gv_c, hb)ba, hbba, hbbs", r"\1ba, hbba, hbba"),
    "card_noset": (r"(hex\.if1 1, pcard, give_5_ok\n)    hex\.set 2, p_bc, 6\n", r"\1"),
    "bon2_notype": (r"(  give_2015_g:\n)    hex\.set 1, p_at, 1\n", r"\1"),
    "saw_nopend": (r"    hex\.set 1, wp_pend, %d\n" % gd.WP_CHAINSAW, ""),
    "pstr_nofist": (r"(  give_2023_f:\n)    hex\.set 1, wp_pend, 0\n", r"\1"),
}


def _program(w, mut=None):
    gives = []
    for kind, dropped in L.give_kinds(w):
        gives += L.give_lines(kind, dropped)
    for a in range(gd.NUMAMMO):
        gives += L.give_ammo_lines(a)
    bonus = ["hex.if0 1, gv_ok, hb_skip", *L._bonus_lines("hb"), "hb_skip:"]
    text = "\n".join(gives) + "\n"
    btext = "\n".join(bonus) + "\n"
    tables = L.tables_fj(w)
    if mut == "amcap_nobp":
        tables = [t if "ns amcap {" not in t else _amcap_nobp() for t in tables]
    elif mut:
        pat, new = MUTANTS[mut]
        text, n = re.subn(pat, new, text)
        btext, m = re.subn(pat, new, btext)
        assert n + m >= 1, mut
    ws = w.ws
    wstart = WC.level_start(w.mw, "E1M1")
    states, frames = WC.weapon_states(), WC.overlay_frames()
    decls = (L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(wstart, states, frames) + ["pcard: hex.vec 1"])
    return decls, text, btext, tables


def _build(tmp_path, name, mut=None):
    w = _world()
    records = _records(w)
    nib = {"p_health": ("p_hp", 3), "p_armor": ("p_ar", 2), "p_armortype": ("p_at", 1), "p_backpack": ("p_bp", 1),
           "p_ready": ("wp_rdy", 1), "p_pending": ("wp_pend", 1), "p_strength": ("p_str", 4),
           "p_bonuscount": ("p_bc", 2), "card": ("pcard", 1)}
    body = ["stl.startup_and_init_all"]
    for k, (pokes, kind, dropped) in enumerate(records):
        for f, (c, n) in nib.items():
            body.append("hex.set %d, %s, %d" % (n, c, pokes[f]))
        for a in range(gd.NUMAMMO):
            body.append("hex.set 3, %s, %d" % (L.AMMO_CELL[a], pokes["ammo"][a]))
        body.append("hex.set 4, wp_own, %d" % sum(pokes["owned"][x] << (4 * WC.OWN[x]) for x in WC.WEAPONS))
        body += ["hex.set 1, gv_ok, 7",
                 "stl.fcall give_%d%s, gv_ret" % (kind, "d" if dropped else ""),
                 "stl.fcall bonus_leaf, bl_ret"]
        body += ["hex.print_as_digit %d, %s, 0" % (n, c) for c, n in CELLS] + ["stl.output 10"]
    body += ["stl.loop"]
    decls, text, btext, tables = _program(w, mut)
    prog = "\n".join(body + decls + ["bl_ret: hex.vec w/4", "bonus_leaf:"]) + "\n"
    prog += btext + "stl.fret bl_ret\n" + text + "\n".join(tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(_world(), records)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_give():
    """the model's outcomes over the records: every kind both taken and refused where it can be refused, every cap
    binding, every auto-switch, the bonus count saturating, the card's set"""
    w = _world()
    seen = {}
    sat = switch_clip = switch_shell = bc_set = 0
    for pokes, kind, dropped in _records(w):
        _apply(w, pokes)
        before = (list(w.ws.p_ammo), w.ws.p_pending)
        taken = w._touch(kind, dropped, 0, 0)
        seen.setdefault((kind, dropped), set()).add(taken)
        sat += taken and pokes["p_bonuscount"] > 249
        switch_clip += w.ws.p_pending == gd.WP_PISTOL != before[1] and before[0][gd.AM_CLIP] == 0
        switch_shell += w.ws.p_pending == gd.WP_SHOTGUN != before[1] and before[0][gd.AM_SHELL] == 0
        bc_set += kind == 5 and not pokes["card"]
    always = {2014, 2015, 5, 8, 2023}
    for (kind, dropped), outs in seen.items():
        assert outs == ({True} if kind in always else {True, False}), (kind, dropped, outs)
    assert len(seen) == len(L.give_kinds(w))
    assert sat >= 10 and switch_clip >= 5 and switch_shell >= 3 and bc_set >= 5, (sat, switch_clip, switch_shell, bc_set)


def test_the_gives_follow_the_model(tmp_path):
    assert _run(tmp_path, "give"), "the fj gives parted from the model's _touch"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_give_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "give_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
