"""M7 P6 + P7 (doomfj.lootcode, `weaponcode.weapon_lines(loot=True)`): the "full" player's tic on the real flipjump
engine against the model's own `combat._player_phase`, tic by tic in ONE image.

THE PHASE (`test_the_phase_*`): the frame's player half exactly as the plan's frame order splices it -- `latch`
(p_dd0 = p_dead), `pre` (the alive branch's nukage call), the weapon tic with `loot`, hurtcode's damagecount fade,
`post` (the death think's restart request and the jump past the move, or the strength and bonus tic) and a stand-in
move that only marks that it ran. The harness's `nk_go` hands `dp_go` the damage the script names for that tic -- the
model's `_special_sector` is replaced by the same hit (nukage itself is tests/fj/test_nukage_fj.py's). The script:
  * the chainsaw raised, then BERSERK (p_str poked to 1) -- key 1 now brings up the FIST (the saw is ready and
    strength runs), then key 1 with the fist up brings the saw again; strength grows a tic at a time and saturates
    (poked to 0xFFFE); a bonus count (poked) fades;
  * then hits until one KILLS on a tic whose key 2 is held -- the latch: that tic's keys still run (the pistol goes
    pending, P7-a) -- then dead tics with the number keys, fire and use: the keys change nothing, the move never runs,
    strength and bonus freeze, use asks for the restart (g_rs).
R9 (PHASE_MUTS): the key skip reading the live p_dead (the latch), the dead branch falling into the move, no restart
request, strength not growing, the bonus not fading, the bonus fading while dead, key 1 ignoring berserk.

THE BERSERK FIST (`test_the_berserk_punch_*`): `weapon_lines(shoot=True, hurt=True, loot=True)` with the whole aim
window naming slot 0 and a `dm_go` that prints each hand-off's damage, against the model's `_line_attack` calls (the
damage it is handed, x10 under berserk) with an aim that always names slot 0. R9: the x10 gone.
"""
import random
import re
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj import hurtcode as H
from doomfj import lootcode as L
from doomfj import weaponcode as WC
from doomfj.combat import half_width_table
from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.reference_model import ReferenceModel
from doomfj.world import KEYS, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
CELLS = (("wp_rdy", 1), ("wp_pend", 1), ("wp_st", 2), ("wp_tics", 1), ("wp_sy", 2), ("fl_st", 2), ("wp_rf", 2),
         ("wp_ad", 1), ("rng_pl", 2), ("p_hp", 3), ("p_dc", 2), ("p_dead", 1), ("p_str", 4), ("p_bc", 2),
         ("g_rs", 1), ("mvmark", 1))
TICS = 330


def _world(player="full"):
    w = World(skill=gd.SK_HARD, monsters="idle", player=player)
    ws = w.ws
    ws.p_owned[gd.WP_SHOTGUN] = ws.p_owned[gd.WP_CHAINSAW] = 1
    ws.p_ammo[gd.AM_SHELL], ws.p_ammo[gd.AM_CLIP] = 8, 40
    for m in range(w.layout.nmon):                     # nothing to shoot, nothing that moves
        ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = 0
    return w


def _start(w):
    ws = w.ws
    return {f: getattr(ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                        "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown", "rng_player")} \
        | {"ammo": list(ws.p_ammo), "owned": list(ws.p_owned)}


def _phase_script():
    """[(keys, pokes, dmg)]: pokes bit 0 strength = 1, bit 1 strength = 0xFFFE, bit 2 bonus = 40"""
    rnd = random.Random(23)
    out = []
    for t in range(TICS):
        k = dict.fromkeys(KEYS, False)
        pokes, dmg = 0, 0
        k["w1"] = t in (2, 70, 120)                          # the saw; berserk -> the fist; the fist up -> the saw
        pokes |= 1 if t == 60 else 0
        pokes |= 2 if t == 150 else 0
        pokes |= 4 if t in (100, 175, 235) else 0           # the last one while dead: it must not fade
        k["fire"] = 165 < t < 185 or (t > 240 and rnd.random() < 0.3)
        if 190 <= t < 260 and t % 9 == 0:
            dmg = 30                                         # hits at 198, 207, 216; the 4th (225) kills
        k["w3"] = t == 200 or t in range(230, 330, 11)       # the shotgun up by the kill tic, then dead keys
        k["w2"] = t >= 225 and (t - 225) % 7 == 0            # the KILL tic's key 2 (the latch), then dead keys
        k["use"] = t > 200 and rnd.random() < 0.2
        out.append((k, pokes, dmg))
    return out


def _phase_model(script):
    w = _world()
    ws = w.ws
    rows = []
    for k, pokes, dmg in script:
        if pokes & 1:
            ws.p_strength = 1
        if pokes & 2:
            ws.p_strength = 0xFFFE
        if pokes & 4:
            ws.p_bonuscount = 40
        ev = TicEvents(0)
        dead0 = ws.p_dead
        w._special_sector = (lambda e, d=dmg: w.damage_player(d, ("sector", 0), e) if d else None)
        w._player_phase(k, ev)
        rows.append([ws.p_ready, ws.p_pending, gd.STATE_INDEX[gd.STATE_NAMES[ws.p_wpn_state]], ws.p_wpn_tics,
                     ws.p_wpn_sy, ws.p_flash_state, ws.p_refire, ws.p_attackdown, ws.rng_player, ws.p_health & 0xFFF,
                     ws.p_damagecount, ws.p_dead, ws.p_strength, ws.p_bonuscount, ws.g_restart, 0 if dead0 else 1])
    return rows


PHASE_MUTS = {
    "latch": (r"hex\.if1 1, p_dd0, wk_end", "hex.if1 1, p_dead, wk_end"),
    "dead_moves": (r"lt_dead_out:\n;simmv_done\n", "lt_dead_out:\n"),
    "no_restart": (r"lt_rs:\nhex\.set 1, g_rs, 1\n", "lt_rs:\n"),
    "str_nogrow": (r"hex\.inc 4, p_str\n", ""),
    "bc_nofade": (r"hex\.dec 2, p_bc\n", ""),
    "dead_bc_fades": (r"(hex\.if0 1, p_dd0, lt_alive\n)", r"hex.if0 2, p_bc, lt_xx\nhex.dec 2, p_bc\nlt_xx:\n\1"),
    "saw_berserk": (r"wk_sbk:\nhex\.if0 4, p_str, wk_end\n;wk_fist\n", "wk_sbk:\n;wk_end\n"),
}


def _keybits(lines_pkeys=True):
    """the harness's key byte -> pkeys (fire, use) and kb_w1..kb_w4"""
    return ["hex.zero 2, pkeys",
            "hex.if_flags kin, 0xAAAA, kf_no, kf_yes", "kf_yes:", "hex.xor_by pkeys + dw, 0x8", "kf_no:",
            "hex.if_flags kin + dw, 0xCCCC, ku_no, ku_yes", "ku_yes:", "hex.xor_by pkeys + dw, 0x1", "ku_no:",
            "hex.zero 1, kb_w1", "hex.zero 1, kb_w2", "hex.zero 1, kb_w3", "hex.zero 1, kb_w4",
            "hex.if_flags kin, 0xCCCC, k1_no, k1_yes", "k1_yes:", "hex.set 1, kb_w1, 1", "k1_no:",
            "hex.if_flags kin, 0xF0F0, k2_no, k2_yes", "k2_yes:", "hex.set 1, kb_w2, 1", "k2_no:",
            "hex.if_flags kin, 0xFF00, k3_no, k3_yes", "k3_yes:", "hex.set 1, kb_w3, 1", "k3_no:",
            "hex.if_flags kin + dw, 0xAAAA, k4_no, k4_yes", "k4_yes:", "hex.set 1, kb_w4, 1", "k4_no:"]


def _kbyte(k):
    return (int(k["fire"]) | int(k["w1"]) << 1 | int(k["w2"]) << 2 | int(k["w3"]) << 3 | int(k["w4"]) << 4
            | int(k["use"]) << 5)


def _common_decls(w, states, frames):
    rm = ReferenceModel()
    return (["rmagic: hex.vec 2", "kin: hex.vec 2", "kp: hex.vec 2", "kd: hex.vec 2", "pkeys: hex.vec 2",
             "kb_w1: hex.vec 1", "kb_w2: hex.vec 1", "kb_w3: hex.vec 1", "kb_w4: hex.vec 1", "g_rs: hex.vec 1",
             "mvmark: hex.vec 1"]
            + WC.weapon_decls(_start(w), states, frames) + WC.weapon_const_decls()
            + H.hurt_decls(H.level_start(w)) + L.loot_decls(L.level_start(w)) + H.dp_lines()
            + H.tables_fj(half_width_table(rm.sine))
            + hudcode.hud_decls(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START)))
            + [generate_dispatch_table_fj("ammobcd", WC.ammo_digit_values(), index_nibbles=3, result_nibbles=3)])


def _run_prog(tmp_path, name, text, feed, ncells, nrows):
    src = tmp_path / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed)
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [[int(v, 16) for v in line.split(",")[:ncells] if v]
            for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:nrows]]


def _phase_run(tmp_path, name, mut=None):
    script = _phase_script()
    w = _world()
    states, frames = WC.weapon_states(), WC.overlay_frames(WC.weapon_states())
    # the emitter's own composition (lootcode.tic_lines: pre, the weapon, the fade or -- dead -- package D's dt_turn,
    # post); dt_turn is stood in for by its no-attacker case (the damage here has no source: p_atk stays 0, and D's
    # leaf then only fades the flash -- the leaf itself is tests/fj/test_death_turn_fj.py's)
    tic = (L.latch_lines() + L.tic_lines(WC.weapon_lines(states, frames, hurt=True, loot=True), H.hp_tic_lines())
           + ["hex.set 1, mvmark, 1", "simmv_done:"]                  # the move's stand-in, and its end label
           + [";dtt_skip", "dt_turn:", "hex.if0 2, p_dc, dtt_z", "hex.dec 2, p_dc", "dtt_z:", "stl.fret dt_tret",
              "dtt_skip:"])
    text = "\n".join(tic) + "\n"
    if mut:
        pat, new = PHASE_MUTS[mut]
        text, n = re.subn(pat, new, text)
        assert n, mut
    body = (["stl.startup_and_init_all",
             "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
             "hex.input 1, kin", "hex.input 1, kp", "hex.input 1, kd"]
            + _keybits()
            + ["hex.if_flags kp, 0xAAAA, kp1_no, kp1_yes", "kp1_yes:", "hex.set 4, p_str, 1", "kp1_no:",
               "hex.if_flags kp, 0xCCCC, kp2_no, kp2_yes", "kp2_yes:", "hex.set 4, p_str, 0xFFFE", "kp2_no:",
               "hex.if_flags kp, 0xF0F0, kp3_no, kp3_yes", "kp3_yes:", "hex.set 2, p_bc, 40", "kp3_no:",
               "hex.zero 1, mvmark",
               text]
            + [x for c, n in CELLS for x in ("hex.print_as_digit %d, %s, 0" % (n, c), "stl.output 44")]
            + ["stl.output 10", ";loop", "bad:", "stl.loop", "done:", "stl.loop",
               # the harness's nukage: the script's damage for this tic
               "nk_go:", "hex.if0 2, kd, nkh_out", "hex.mov 2, dp_dmg, kd", "stl.fcall dp_go, dp_ret",
               "nkh_out:", "stl.fret nk_ret"]
            + _common_decls(w, states, frames))
    feed = b"".join(bytes([1, _kbyte(k), p, d]) for k, p, d in script) + bytes([0])
    got = _run_prog(tmp_path, name, "\n".join(body) + "\n", feed, len(CELLS), TICS)
    want = _phase_model(script)
    want = [[r[0], r[1], {gd.STATE_INDEX[s]: i for i, s in enumerate(states)}[r[2]], r[3], r[4],
             {gd.STATE_INDEX[s]: i for i, s in enumerate(states)}[r[5]], *r[6:]] for r in want]
    return got, want


def _first_bad(got, want):
    assert len(got) == len(want), "the program printed %d tics of %d" % (len(got), len(want))
    return next((t for t, (g, w) in enumerate(zip(got, want)) if g != w), None)


def test_the_phase_script_reaches_its_paths():
    """the saw ready under berserk -> the fist pending; the fist up -> the saw; strength saturated; the bonus
    faded; a kill on a key-2 tic (the pistol pending that tic); dead tics with keys, use and the restart request"""
    script = _phase_script()
    rows = _phase_model(script)
    by = lambda t, i: rows[t][i]                                     # noqa: E731
    t_fist = next(t for t in range(60, 120) if by(t, 1) == gd.WP_FIST)
    assert by(t_fist - 1, 0) == gd.WP_CHAINSAW and by(t_fist, 12) > 0
    assert any(by(t, 1) == gd.WP_CHAINSAW and by(t - 1, 0) == gd.WP_FIST for t in range(120, 200))
    assert max(r[12] for r in rows) == 0xFFFF
    assert any(by(t, 13) == 0 and by(t - 1, 13) == 1 for t in range(101, 190))
    tk = next(t for t, r in enumerate(rows) if r[11])
    assert script[tk][0]["w2"] and by(tk, 1) == gd.WP_PISTOL, "the kill tic's keys must have run"
    assert rows[tk][15] == 1 and all(r[15] == 0 for r in rows[tk + 1:])
    assert any(r[14] for r in rows) and not any(r[14] for r in rows[:tk + 1])
    assert len({r[12] for r in rows[tk:]}) == 1 and len({r[1] for r in rows[tk:]}) == 1


def test_the_phase_is_the_model_tic_by_tic(tmp_path):
    got, want = _phase_run(tmp_path, "phase")
    bad = _first_bad(got, want)
    names = [c for c, _n in CELLS]
    assert bad is None, "tic %d: %s" % (bad, {names[i]: (got[bad][i], want[bad][i]) for i in range(len(names))
                                             if got[bad][i] != want[bad][i]})


@pytest.mark.parametrize("mut", sorted(PHASE_MUTS))
def test_the_checks_catch_a_broken_phase(tmp_path, mut):
    got, want = _phase_run(tmp_path, "phase_" + mut, mut)
    assert _first_bad(got, want) is not None, "the mutant %s went unnoticed" % mut


# ---- the berserk fist ----------------------------------------------------------------------------------------------
PUNCH_TICS = 160


def _punch_script():
    """[(keys, pokes)]: the fist up (key 1, no saw owned), fire held; strength on (poke 1) from tic 100"""
    out = []
    for t in range(PUNCH_TICS):
        k = dict.fromkeys(KEYS, False)
        k["w1"] = t == 1
        k["fire"] = t > 40
        out.append((k, 1 if t == 100 else 0))
    return out


def _punch_world():
    w = _world()
    w.ws.p_owned[gd.WP_CHAINSAW] = 0
    w.aim = lambda world, col: ("mon", 0)
    return w


def _punch_model(script):
    w = _punch_world()
    ws = w.ws
    rows = []
    for k, pokes in script:
        if pokes & 1:
            ws.p_strength = 1
        calls = []
        w._line_attack = lambda weapon, col, dmg, reach, ev, calls=calls: calls.append(dmg)
        w._special_sector = lambda e: None
        w._player_phase(k, TicEvents(0))
        rows.append(calls)
    return rows


def _punch_run(tmp_path, name, mut=False):
    script = _punch_script()
    w = _punch_world()
    states, frames = WC.weapon_states(), WC.overlay_frames(WC.weapon_states())
    text = "\n".join(WC.weapon_lines(states, frames, shoot=True, hurt=True, loot=True)) + "\n"
    if mut:
        text, n = re.subn(r"bk10\.lookup dm_dmg, sh_row\n", "", text)
        assert n
    body = (["stl.startup_and_init_all",
             "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
             "hex.input 1, kin", "hex.input 1, kp"]
            + _keybits()
            + ["hex.if_flags kp, 0xAAAA, kp1_no, kp1_yes", "kp1_yes:", "hex.set 4, p_str, 1", "kp1_no:",
               "hex.mov 1, p_dd0, p_dead", text, *H.hp_tic_lines(), *L.post_lines(),
               "simmv_done:", "stl.output 10", ";loop", "bad:", "stl.loop", "done:", "stl.loop",
               # the damage machinery's stand-in: print the damage handed on
               "dm_go:", "hex.print_as_digit 2, dm_dmg, 0", "stl.output 44", "stl.fret dm_ret",
               "dm_ret: hex.vec w/4", "nz_ret: hex.vec w/4",
               "aim_sid: hex.vec %d, %d" % (2 * WC.AIM_N, sum(1 << (8 * i) for i in range(WC.AIM_N)))]
            + WC.shot_decls() + [WC.shot_table_fj(), WC.bk10_table_fj()]
            + _common_decls(w, states, frames))
    feed = b"".join(bytes([1, _kbyte(k), p]) for k, p in script) + bytes([0])
    src = tmp_path / (name + ".fj")
    src.write_text("\n".join(body) + "\n", encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed)
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = [[int(v, 16) for v in line.split(",") if v]
           for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:PUNCH_TICS]]
    return got, _punch_model(script)


def test_the_berserk_punch_script_reaches_its_paths():
    rows = _punch_model(_punch_script())
    plain = [d for r in rows[:100] for d in r]
    hard = [d for r in rows[101:] for d in r]
    assert len(plain) >= 3 and len(hard) >= 3 and max(plain) <= 20 and min(hard) >= 20 and all(d % 10 == 0 for d in hard)


def test_the_berserk_punch_is_the_model(tmp_path):
    got, want = _punch_run(tmp_path, "punch")
    assert got == want, next((t, g, w_) for t, (g, w_) in enumerate(zip(got, want)) if g != w_)


def test_the_berserk_punch_control_is_caught(tmp_path):
    got, want = _punch_run(tmp_path, "punch_nox10", mut=True)
    assert got != want, "the punch without its x10 went unnoticed"
