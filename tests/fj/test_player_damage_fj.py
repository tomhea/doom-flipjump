"""M7 P5 (doomfj.hurtcode): P_DamageMobj on the PLAYER on the real flipjump engine -- `dp_go` and `hp_bar`, the very
text the emitter splices, against the model's own `combat.damage_player` / `_kill_player`.

Each record pokes the player's cells identically on both sides -- health (around 0 and the hit's damage, so a hit
leaves exactly 0, and already <= 0), armor and armortype (around the save, so the armor runs out exactly), the
damagecount (around the cap), dead, the player's stream, the ready weapon with one of its states and a height (some
near the bottom, so the kill's A_Lower clamps) -- then hands dp_go a damage (most of them the monsters' real 3..40,
some up to DP_MAX) and runs hp_bar. After every record the cells, the weapon psprite and the bar's health and armor
digits are printed.

R9: the green and blue saves swapped (the table built with /2 and /3 exchanged), `<` for the armor's `<=`, no
damagecount cap, no rng_pl draw, no dead guard, a kill that does not run A_Lower, a bar that shows a killed player's
health as 1 instead of max(0, health) = 0, and a bar without the armor must each part.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj.combat import half_width_table
from doomfj import hurtcode as H
from doomfj import weaponcode as WC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.reference_model import ReferenceModel
from doomfj.world import TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 400
# (fj cell, nibbles) printed after every record
CELLS = (("p_hp", 3), ("p_ar", 2), ("p_at", 1), ("p_dc", 2), ("p_dead", 1), ("rng_pl", 2), ("wp_st", 2),
         ("wp_tics", 1), ("wp_frm", 1), ("wp_sy", 2), ("hud_v + 3*dw", 3), ("hud_v + 6*dw", 3),
         ("p_atk", 2))                    # M7 P7: player->attacker


def _src(r: int) -> int:
    """M7 P7: record r's source -- 0 (none: a caller that sets no dp_src, as sector damage) or 1 + a monster slot,
    1..54 (every hi nibble). Derived from the index, so the records' own draws are P5's unchanged."""
    return (r * 11) % 55


def _world():
    return World(skill=gd.SK_HARD, monsters="idle", player="fire")


def _records():
    """[(pokes {ws field: value}, dmg)]"""
    rnd = random.Random(0x5B)
    states = WC.psprite_states()
    out = []
    for r in range(N):
        dmg = rnd.choice((3, 6, 9, 12, 15, 24, 40, rnd.randint(1, 40), rnd.randint(1, 40), rnd.randint(1, H.DP_MAX)))
        at = rnd.choice((0, 0, 1, 1, 2, 2))
        saved = H.armor_saved(at, dmg)
        armor = rnd.choice((0, saved, saved, saved - 1, saved + 1, 1, rnd.randint(0, 200), 200, 100))
        armor = max(0, min(200, armor))
        eff = dmg - min(saved, armor) if at else dmg
        hp = rnd.choice((100, 100, eff, eff, eff + 1, eff - 1, 1, 0, -3, rnd.randint(1, 200), rnd.randint(1, 60)))
        dc = rnd.choice((0, 0, 100, 99, 100 - eff, 101 - eff, rnd.randint(0, 100)))
        dc = max(0, min(100, dc))
        w = rnd.choice(WC.WEAPONS)
        own = [s for s in states if gd.STATES[s].sprite == gd.STATES[gd.WEAPONINFO[w].readystate].sprite]
        st = rnd.choice(own)
        sy = rnd.choice((32, 32, 60, 121, 122, 123, 125, 128, rnd.randint(32, 128)))
        pokes = {"p_health": hp, "p_armor": armor, "p_armortype": at if armor or rnd.random() < 0.2 else 0,
                 "p_damagecount": dc, "p_dead": int(rnd.random() < 0.06), "rng_player": rnd.randrange(256),
                 "p_ready": w, "p_wpn_state": gd.STATE_INDEX[st], "p_wpn_tics": rnd.randint(1, 8), "p_wpn_sy": sy}
        out.append((pokes, dmg))
    return out


def _want(ws, states, frames) -> str:
    idx = {gd.STATE_INDEX[s]: i for i, s in enumerate(states)}
    bar = hudcode.slot_codes(hud.slot_values(ammo=None, health=max(0, ws.p_health), armor=ws.p_armor,
                                             owned=(False, False, False), blue=False))
    vals = [ws.p_health & 0xFFF, ws.p_armor, ws.p_armortype, ws.p_damagecount, ws.p_dead, ws.rng_player,
            idx[ws.p_wpn_state], ws.p_wpn_tics, frames.index(WC.psprite_lump(gd.STATE_NAMES[ws.p_wpn_state])),
            ws.p_wpn_sy, bar[3] | bar[4] << 4 | bar[5] << 8, bar[6] | bar[7] << 4 | bar[8] << 8, ws.p_attacker]
    return "".join("%0*x" % (n, v) for (_c, n), v in zip(CELLS, vals))


def _apply(w, pokes, dmg, ev, src=1):
    ws = w.ws
    for f, v in pokes.items():
        setattr(ws, f, v)
    w.damage_player(dmg, ("mon", src - 1) if src else ("sector", 0), ev)


def _expected(records) -> bytes:
    w = _world()
    states, frames = WC.weapon_states(), WC.overlay_frames()
    lines = []
    for r, (pokes, dmg) in enumerate(records):
        _apply(w, pokes, dmg, TicEvents(0), _src(r))
        lines.append(_want(w.ws, states, frames))
    return ("\n".join(lines) + "\n").encode()


def _swapped_dpsav():
    vals = [(i & 0xFF) // 2 if i >> 8 == 1 else (i & 0xFF) // 3 if i >> 8 == 2 else 0 for i in range(3 << 8)]
    return generate_dispatch_table_fj("dpsav", vals, index_nibbles=3, result_nibbles=2)


MUTANTS = {
    "swap32": None,                                                               # the table, below
    "armor_lt": ("    hex.cmp 2, p_ar, dp_sv, dp_ex, dp_ex, dp_ar\n", "    hex.cmp 2, p_ar, dp_sv, dp_ex, dp_ar, dp_ar\n"),
    "nocap": ("    hex.set 2, p_dc, %d\n" % H.DC_CAP, ""),
    "nodraw": ("    hex.inc 2, rng_pl\n", ""),
    "nodead": ("    hex.if1 1, p_dead, dp_out\n", ""),
    "nolower": ("    hex.add_constant 2, wp_sy, %d\n" % WC.LOWER, ""),
    # (a bar reading the negative health itself would index ammobcd past its 512 rows: a run-away, not a control)
    "bardead1": ("hb_neg:\nhex.zero 3, hp_v\n", "hb_neg:\nhex.set 3, hp_v, 1\n"),
    "barnoarmor": ("hex.mov 2, hp_v, p_ar\n", ""),
    # M7 P7: the attacker not recorded; a source left over for the next caller (which names none)
    "noatk": ("    hex.mov 2, p_atk, dp_src\n", ""),
    "srcstale": ("    hex.zero 2, dp_src\n", ""),
}


def _program(mut=None):
    w = _world()
    start = H.level_start(w)
    rm = ReferenceModel()
    tables = H.tables_fj(half_width_table(rm.sine))
    if mut == "swap32":
        tables = [t if "ns dpsav {" not in t else _swapped_dpsav() for t in tables]
    text = "\n".join(H.dp_lines() + ["hpb_leaf:"] + H.hp_bar_lines() + ["stl.fret hpb_ret"]) + "\n"
    if mut and MUTANTS[mut]:
        old, new = MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    states, frames = WC.weapon_states(), WC.overlay_frames()
    wstart = WC.level_start(w.mw, "E1M1")
    decls = (H.hurt_decls(start) + WC.weapon_decls(wstart, states, frames) + WC.weapon_const_decls()
             + hudcode.hud_decls(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START)))
             + ["hpb_ret: hex.vec w/4"])
    return decls, text, tables + [generate_dispatch_table_fj("ammobcd", WC.ammo_digit_values(), index_nibbles=3,
                                                             result_nibbles=3)]


def _build(tmp_path, name, mut=None):
    records = _records()
    states, frames = WC.weapon_states(), WC.overlay_frames()
    idx = {gd.STATE_INDEX[s]: i for i, s in enumerate(states)}
    nib = {"p_health": ("p_hp", 3), "p_armor": ("p_ar", 2), "p_armortype": ("p_at", 1),
           "p_damagecount": ("p_dc", 2), "p_dead": ("p_dead", 1), "rng_player": ("rng_pl", 2),
           "p_ready": ("wp_rdy", 1), "p_wpn_tics": ("wp_tics", 1), "p_wpn_sy": ("wp_sy", 2)}
    body = ["stl.startup_and_init_all"]
    for r, (pokes, dmg) in enumerate(records):
        for f, v in pokes.items():
            if f == "p_wpn_state":
                body += ["hex.set 2, wp_st, %d" % idx[v],
                         "hex.set 1, wp_frm, %d" % frames.index(WC.psprite_lump(gd.STATE_NAMES[v]))]
            else:
                c, n = nib[f]
                body.append("hex.set %d, %s, %d" % (n, c, v & (16 ** n - 1)))
        body += ["hex.set 2, dp_src, %d" % _src(r)] if _src(r) else []      # 0: the caller names none
        body += ["hex.set 2, dp_dmg, %d" % dmg, "stl.fcall dp_go, dp_ret", "stl.fcall hpb_leaf, hpb_ret"]
        body += ["hex.print_as_digit %d, %s, 0" % (n, c) for c, n in CELLS]
        body += ["stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = _program(mut)
    prog = "\n".join(body + decls + [text] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(records)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path():
    """the model's outcomes over the records: kills (one leaving exactly 0 health), pains, hits on a dead or
    no-health player (nothing), armor used up exactly and kept, both armor types, the damagecount capped, the kill's
    weapon clamped at the bottom and still lowering, every weapon dropped"""
    w = _world()
    ws = w.ws
    seen = dict(kill=0, kill0=0, pain=0, dead=0, nohp=0, exhausted=0, exact=0, kept=0, green=0, blue=0, cap=0,
                clamp=0, lowering=0)
    dropped = set()
    for pokes, dmg in _records():
        ev = TicEvents(0)
        before_rng = pokes["rng_player"]
        _apply(w, pokes, dmg, ev)
        if pokes["p_dead"]:
            seen["dead"] += 1
            assert ws.rng_player == before_rng
            continue
        if pokes["p_health"] <= 0:
            seen["nohp"] += 1
            assert ws.rng_player == before_rng
            continue
        assert ws.rng_player == (before_rng + 1) & 0xFF, "a hit that lands draws once"
        at = pokes["p_armortype"]
        if at:
            seen["green" if at == 1 else "blue"] += 1
            saved = H.armor_saved(at, dmg)
            if pokes["p_armor"] <= saved:
                seen["exhausted"] += 1
                seen["exact"] += pokes["p_armor"] == saved
            else:
                seen["kept"] += 1
        seen["cap"] += ws.p_damagecount == 100 and pokes["p_damagecount"] + dmg > 100
        if ev.deaths:
            seen["kill"] += 1
            seen["kill0"] += ws.p_health == 0
            dropped.add(pokes["p_ready"])
            if pokes["p_wpn_sy"] + WC.LOWER >= WC.BOTTOM:
                seen["clamp"] += 1
            else:
                seen["lowering"] += 1
        else:
            seen["pain"] += 1
    want = dict(kill=40, kill0=10, pain=100, dead=10, nohp=10, exhausted=20, exact=8, kept=20, green=40, blue=40,
                cap=10, clamp=8, lowering=8)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)
    assert dropped == set(WC.WEAPONS), dropped


def test_the_player_damage_follows_the_model(tmp_path):
    assert _run(tmp_path, "pdamage"), "the fj damage parted from the model's damage_player"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_player_damage_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "pdamage_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
