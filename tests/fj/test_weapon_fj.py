"""M7 P4.1 -- the weapon in fj (`doomfj.weaponcode`) against the model's "fire" mode, tic by tic.

The REAL emitted text runs in a loop fed one key byte per tic (fire, the number keys 1..4); after every tic the
program prints every weapon cell and the bar's ammo + arms nibbles, and they must equal `World(player="fire")`'s
fields after the same keys -- the psprite state and tics, the weapon height, the flash, refire, attackdown, both
ammo counts, the pending / ready weapon, the player's stream, the overlay frames and the bar. The script switches
between all four weapons (the shotgun and the chainsaw given at the start), taps and holds the trigger, runs the
pistol dry (so P_CheckAmmo picks the next weapon) and the shotgun dry.

R9: four mutants of the emitted text, each caught (the first differing tic is printed):
  * refire never counted (A_ReFire's increment gone)            -- a held pistol stays accurate: the stream parts
  * the out-of-ammo preference with the pistol before the shotgun -- the weapon picked when the pistol runs dry
  * the accurate shot rolls 3                                    -- the stream
  * the weapon lowers 7 a tic instead of 6                       -- the height, then the switch's timing

M7 P5 (`weapon_lines(hurt=True)`, doomfj.hurtcode): the same loop with the player hurt and killed -- the section at
the end of this file.
"""
import random
import re
import struct

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj import hurtcode as H
from doomfj import weaponcode as WC
from doomfj.combat import half_width_table
from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.reference_model import ReferenceModel
from doomfj.world import KEYS, WEAPON_TICS, TicEvents, World

N = 600
CELLS = (("wp_rdy", 1), ("wp_pend", 1), ("wp_st", 2), ("wp_tics", 1), ("wp_sy", 2), ("fl_st", 2), ("fl_tics", 1),
         ("wp_rf", 2), ("wp_ad", 1), ("am_clip", 3), ("am_shell", 3), ("rng_pl", 2), ("wp_frm", 1), ("fl_frm", 1),
         ("hud_v", 3), ("hud_v + 9*dw", 3), ("wp_pass", 1))   # M7 P6+P7: the tic counter, 0 after every frame


def _script(seed=11):
    rng = random.Random(seed)
    keys, fire = [], False
    for t in range(N):
        if rng.random() < 0.07:
            fire = not fire
        k = {name: False for name in KEYS}
        k["fire"] = fire or rng.random() < 0.05
        if rng.random() < 0.012:                              # rare switches: a switch costs ~32 tics of lower+raise
            k[rng.choice(("w1", "w2", "w3", "w4"))] = True
        keys.append(k)
    return keys


def _world(saw=True):
    """the shotgun given; the chainsaw too, or not -- key 1 is the chainsaw when it is owned, so the fist is only
    ever up in a run without it"""
    w = World(skill=gd.SK_HARD, monsters="idle", player="fire", monster_tics=1)   # M7 P6+P7 E: one DOOM tic
    ws = w.ws
    ws.p_owned[gd.WP_SHOTGUN] = 1
    ws.p_owned[gd.WP_CHAINSAW] = int(saw)
    ws.p_ammo[gd.AM_SHELL] = 4
    ws.p_ammo[gd.AM_CLIP] = 12
    return w


def _start(w):
    ws = w.ws
    return {f: getattr(ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                        "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown", "rng_player")} \
        | {"ammo": list(ws.p_ammo), "owned": list(ws.p_owned)}


MUTS = {
    "norefire": ("hex.inc 2, wp_rf", "hex.inc 0, wp_rf"),
    "pref": ("hex.set 1, wp_pend, %d\n" % gd.WP_SHOTGUN, "hex.set 1, wp_pend, %d\n" % gd.WP_PISTOL),
    "acc3": ("hex.add_constant 2, rng_pl, %d" % WC.DRAWS["pistol_acc"], "hex.add_constant 2, rng_pl, 3"),
    "lower7": ("hex.add_constant 2, wp_sy, %d" % WC.LOWER, "hex.add_constant 2, wp_sy, %d" % (WC.LOWER + 1)),
}


def _program(start, mut=None, tics=None):
    states = WC.weapon_states()
    frames = WC.overlay_frames(states)
    text = "\n".join(WC.weapon_lines(states, frames, tics=tics))
    if mut:
        old, new = MUTS[mut]
        assert old in text, mut
        text = text.replace(old, new)
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, kin",
            # the key byte: bit 0 fire -> pkeys' high nibble bit 3 (wireformat.KEY_FIRE); bits 1..4 the number keys
            "hex.zero 2, pkeys",
            "hex.if_flags kin, 0xAAAA, kf_no, kf_yes", "kf_yes:", "hex.xor_by pkeys + dw, 0x8", "kf_no:",
            "hex.zero 1, kb_w1", "hex.zero 1, kb_w2", "hex.zero 1, kb_w3", "hex.zero 1, kb_w4",
            "hex.if_flags kin, 0xCCCC, k1_no, k1_yes", "k1_yes:", "hex.set 1, kb_w1, 1", "k1_no:",
            "hex.if_flags kin, 0xF0F0, k2_no, k2_yes", "k2_yes:", "hex.set 1, kb_w2, 1", "k2_no:",
            "hex.if_flags kin, 0xFF00, k3_no, k3_yes", "k3_yes:", "hex.set 1, kb_w3, 1", "k3_no:",
            "hex.if_flags kin + dw, 0xAAAA, k4_no, k4_yes", "k4_yes:", "hex.set 1, kb_w4, 1", "k4_no:",
            text,
            *[x for c, n in CELLS for x in ("hex.print_as_digit %d, %s, 0" % (n, c), "stl.output 44")],
            "stl.output 10", ";loop",
            "bad:", "stl.loop", "done:", "stl.loop",
            "rmagic: hex.vec 2", "kin: hex.vec 2", "pkeys: hex.vec 2",
            "kb_w1: hex.vec 1", "kb_w2: hex.vec 1", "kb_w3: hex.vec 1", "kb_w4: hex.vec 1",
            *WC.weapon_decls(start, states, frames), *WC.weapon_const_decls(),
            *hudcode.hud_decls(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))),
            generate_dispatch_table_fj("ammobcd", WC.ammo_digit_values(), index_nibbles=3, result_nibbles=3)]
    return "\n".join(body) + "\n", states, frames


def _model_rows(script, saw=True):
    w = _world(saw)
    rows = []
    for k in script:
        w.tic(k)
        rows.append({f: getattr(w.ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                                   "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown",
                                                   "rng_player")} | {"ammo": tuple(w.ws.p_ammo),
                                                                      "owned": tuple(w.ws.p_owned)})
    return rows


def _want(row, states, frames):
    idx = {gd.STATE_INDEX[s]: i for i, s in enumerate(states)}
    wst, fst = gd.STATE_NAMES[row["p_wpn_state"]], gd.STATE_NAMES[row["p_flash_state"]]
    ammo = {gd.WP_PISTOL: row["ammo"][gd.AM_CLIP], gd.WP_SHOTGUN: row["ammo"][gd.AM_SHELL]}.get(row["p_ready"])
    bar = hudcode.slot_codes(hud.slot_values(ammo=ammo, health=100, armor=0,
                                             owned=(bool(row["owned"][gd.WP_PISTOL]), bool(row["owned"][gd.WP_SHOTGUN]),
                                                    bool(row["owned"][gd.WP_CHAINSAW])), blue=False))
    return [row["p_ready"], row["p_pending"], idx[row["p_wpn_state"]], row["p_wpn_tics"], row["p_wpn_sy"],
            idx[row["p_flash_state"]], row["p_flash_tics"], row["p_refire"], row["p_attackdown"],
            row["ammo"][gd.AM_CLIP], row["ammo"][gd.AM_SHELL], row["rng_player"],
            frames.index(WC.psprite_lump(wst)),
            0 if fst == gd.S_NULL or gd.STATES[fst].tics == 0 else 1 + WC.flash_frames().index(WC.psprite_lump(fst)),
            bar[0] | bar[1] << 4 | bar[2] << 8, bar[9] | bar[10] << 4 | bar[11] << 8, 0]


def _run(tmp_path, name, mut=None, saw=True, tics=None):
    script = _script()
    w = _world(saw)
    text, states, frames = _program(_start(w), mut, tics)
    src = tmp_path / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    feed = b"".join(bytes([1, int(k["fire"]) | int(k["w1"]) << 1 | int(k["w2"]) << 2 | int(k["w3"]) << 3
                           | int(k["w4"]) << 4]) for k in script) + bytes([0])
    io = FixedIO(feed)
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = [[int(v, 16) for v in line.split(",")[:len(CELLS)]]
           for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:N]]
    want = [_want(r, states, frames) for r in _model_rows(script, saw)]
    return got, want


def _first_bad(got, want):
    assert len(got) == len(want), "the program printed %d tics of %d" % (len(got), len(want))
    return next((t for t, (g, w) in enumerate(zip(got, want)) if g != w), None)


@pytest.mark.parametrize("saw", [True, False])
def test_the_weapon_is_the_model_tic_by_tic(tmp_path, saw):
    got, want = _run(tmp_path, "wpn", saw=saw)
    bad = _first_bad(got, want)
    names = [c for c, _n in CELLS]
    assert bad is None, "tic %d: %s" % (bad, {names[i]: (got[bad][i], want[bad][i]) for i in range(len(names))
                                             if got[bad][i] != want[bad][i]})
    # the script covers what it claims: every weapon was up, both guns ran dry, the flash ran
    assert {g[0] for g in got} == ({gd.WP_PISTOL, gd.WP_SHOTGUN, gd.WP_CHAINSAW} if saw else
                                   {gd.WP_FIST, gd.WP_PISTOL, gd.WP_SHOTGUN})
    assert any(g[9] == 0 for g in got) and any(g[10] == 0 for g in got) and any(g[5] for g in got)


# M7 P6+P7 (the owner's x2 fire rate): the weapon runs world.WEAPON_TICS DOOM tics a frame -- the model's
# combat._weapon_tics and the fj's ONE P_MovePsprites block looped (weapon_lines' default `tics`). R9: the block run
# once a frame (the P5 text), or three times, against the same model -- each must part.
def test_the_weapon_runs_the_model_s_tics_per_frame(tmp_path):
    assert WEAPON_TICS == 2
    text = "\n".join(WC.weapon_lines(WC.weapon_states(), WC.overlay_frames()))
    assert text.count("wp_ptic:") == 1 and "hex.if_flags wp_pass, 1<<%d, wp_ptic, wp_pdone" % WEAPON_TICS in text
    assert text.count("wp_next:") == 1 and text.count("wp_flash:") == 1   # ONE block, looped -- not unrolled
    once = "\n".join(WC.weapon_lines(WC.weapon_states(), WC.overlay_frames(), tics=1))
    assert "wp_pass" not in once and "wp_ptic" not in once                # tics=1: the P5 text
    # every frame's printed row ends with wp_pass (CELLS): back to 0 after the loop, every frame (_want's last 0)
    got, want = _run(tmp_path, "wpn_tics", tics=WEAPON_TICS)
    assert _first_bad(got, want) is None


@pytest.mark.parametrize("tics", [1, 3])
def test_the_checks_catch_a_weapon_at_the_wrong_tempo(tmp_path, tics):
    got, want = _run(tmp_path, "wpn_t%d" % tics, tics=tics)
    bad = _first_bad(got, want)
    assert bad is not None, "the weapon at %d tics a frame went unnoticed" % tics
    print("tics=%d caught at frame %d" % (tics, bad))


@pytest.mark.parametrize("mut", sorted(MUTS))
def test_the_checks_catch_a_broken_weapon(tmp_path, mut):
    got, want = _run(tmp_path, mut, mut)
    bad = _first_bad(got, want)
    assert bad is not None, "the mutant %s went unnoticed" % mut
    print("mutant %s caught at tic %d" % (mut, bad))


# ---- M7 P5 (doomfj.hurtcode): the weapon of a player who can be hurt and killed (`weapon_lines(hurt=True)`) ----------
# The same loop, fed two more bytes a tic: POKES (bit 0: p_health = 0, bit 1: p_dead = 1 -- before the tic, both
# sides) and a DAMAGE (after the weapon tic and the damagecount fade: dp_go, as the monsters' phase hands it on).
# The scripts are generated by stepping the model itself, so a poke lands where it means something:
#   * "kill": hits every ~12 tics (with green armor at the start) until one kills -- dp_go's downstate and its A_Lower
#     -- then 50 tics of the dead player's weapon: A_Lower clamps at the bottom tic after tic, the fire key held;
#   * "ready": health 0 poked while the weapon is READY and up (A_WeaponReady lowers at health <= 0), then dead before
#     the weapon can reach the bottom (A_Lower with health <= 0 and not dead -- an S_NULL psprite -- is a state no
#     game reaches: hurtcode keeps p_hp <= 0 <=> p_dead, and the fj does not emit it);
#   * "refire": health 0 poked mid-volley with the trigger held on (A_ReFire must not fire at health <= 0), then dead
#     (the dead player's psprites still move: A_ReFire, then A_WeaponReady lowering, then A_Lower's clamp).
# R9 (HURT_MUTS): A_WeaponReady's health read gone, A_ReFire's health read gone, A_Lower's dead clamp gone.

HURT_CELLS = CELLS + (("p_hp", 3), ("p_dc", 2), ("p_dead", 1))
HURT_TICS = 260


def _hurt_world():
    w = _world(saw=True)
    w.ws.p_armor, w.ws.p_armortype = 40, 1
    return w


def _hurt_script(kind, seed=5):
    """[(keys, pokes, dmg)] and the model's rows after each tic, from ONE model run"""
    rng = random.Random(seed)
    w = _hurt_world()
    ws = w.ws
    ready = {gd.STATE_INDEX[gd.WEAPONINFO[x].readystate] for x in WC.WEAPONS}
    script, rows, fire, window = [], [], False, None
    for t in range(HURT_TICS):
        k = {name: False for name in KEYS}
        pokes, dmg = 0, 0
        if rng.random() < 0.08:
            fire = not fire
        # "refire": the trigger held from tic 40 until 20 tics into the window -- A_ReFire meets health 0 held
        k["fire"] = fire or (kind == "refire" and t > 40 and (window is None or t - window < 20))
        if window is None and not ws.p_dead and rng.random() < 0.01:
            k[rng.choice(("w1", "w2", "w3"))] = True
        if kind in ("kill", "deadkeys") and not ws.p_dead and t % 12 == 11:
            dmg = rng.choice((3, 6, 9, 12, 15, 24, 40))
        if kind == "ready" and window is None and t > 30 and ws.p_wpn_state in ready and ws.p_wpn_sy == WC.TOP \
                and ws.p_pending == gd.WP_NOCHANGE:
            pokes, window = 1, t
        if kind == "refire" and window is None and t > 40 and ws.p_refire >= 1 and ws.p_wpn_state not in ready:
            pokes, window = 1, t
        if window is not None and not ws.p_dead and t - window == 9 // WEAPON_TICS:
            pokes |= 2                                     # dead before A_Lower can reach the bottom (16 tics: 8 frames at M7 P6+P7 x2)
        if window is not None or (ws.p_dead and kind != "deadkeys"):
            for key in ("w1", "w2", "w3", "w4"):
                k[key] = False
        if kind == "deadkeys" and ws.p_dead and rng.random() < 0.3:   # a dead player's number keys change nothing
            k[rng.choice(("w1", "w2", "w3", "w4"))] = True
        if pokes & 1:
            ws.p_health = 0
        if pokes & 2:
            ws.p_dead = 1
        w.tic(k)
        if dmg:
            w.damage_player(dmg, ("mon", 0), ("mon", 0), TicEvents(0))
        script.append((k, pokes, dmg))
        rows.append({f: getattr(ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                                 "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown",
                                                 "rng_player", "p_health", "p_damagecount", "p_dead")}
                    | {"ammo": tuple(ws.p_ammo), "owned": tuple(ws.p_owned)})
    assert ws.p_dead, (kind, "the script never killed the player")
    return script, rows


def _hurt_program(start, hstart, mut=None):
    states = WC.weapon_states()
    frames = WC.overlay_frames(states)
    text = "\n".join(WC.weapon_lines(states, frames, hurt=True))
    if mut:
        pat, new = HURT_MUTS[mut]
        text, n = re.subn(pat, new, text)
        assert n, mut
    rm = ReferenceModel()
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, kin", "hex.input 1, kp", "hex.input 1, kd",
            "hex.zero 2, pkeys",
            "hex.if_flags kin, 0xAAAA, kf_no, kf_yes", "kf_yes:", "hex.xor_by pkeys + dw, 0x8", "kf_no:",
            "hex.zero 1, kb_w1", "hex.zero 1, kb_w2", "hex.zero 1, kb_w3", "hex.zero 1, kb_w4",
            "hex.if_flags kin, 0xCCCC, k1_no, k1_yes", "k1_yes:", "hex.set 1, kb_w1, 1", "k1_no:",
            "hex.if_flags kin, 0xF0F0, k2_no, k2_yes", "k2_yes:", "hex.set 1, kb_w2, 1", "k2_no:",
            "hex.if_flags kin, 0xFF00, k3_no, k3_yes", "k3_yes:", "hex.set 1, kb_w3, 1", "k3_no:",
            "hex.if_flags kin + dw, 0xAAAA, k4_no, k4_yes", "k4_yes:", "hex.set 1, kb_w4, 1", "k4_no:",
            "hex.if_flags kp, 0xAAAA, kh_no, kh_yes", "kh_yes:", "hex.zero 3, p_hp", "kh_no:",
            "hex.if_flags kp, 0xCCCC, kx_no, kx_yes", "kx_yes:", "hex.set 1, p_dead, 1", "kx_no:",
            text,
            *H.hp_tic_lines(),
            "hex.if0 2, kd, kd_no", "hex.mov 2, dp_dmg, kd", "stl.fcall dp_go, dp_ret", "kd_no:",
            *[x for c, n in HURT_CELLS for x in ("hex.print_as_digit %d, %s, 0" % (n, c), "stl.output 44")],
            "stl.output 10", ";loop",
            "bad:", "stl.loop", "done:", "stl.loop",
            "rmagic: hex.vec 2", "kin: hex.vec 2", "kp: hex.vec 2", "kd: hex.vec 2", "pkeys: hex.vec 2",
            "kb_w1: hex.vec 1", "kb_w2: hex.vec 1", "kb_w3: hex.vec 1", "kb_w4: hex.vec 1",
            *WC.weapon_decls(start, states, frames), *WC.weapon_const_decls(),
            *H.hurt_decls(hstart), *H.dp_lines(), *H.tables_fj(half_width_table(rm.sine)),
            *hudcode.hud_decls(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))),
            generate_dispatch_table_fj("ammobcd", WC.ammo_digit_values(), index_nibbles=3, result_nibbles=3)]
    return "\n".join(body) + "\n", states, frames


HURT_MUTS = {
    # A_WeaponReady: p_health <= 0 no longer lowers
    "readyhp": (r"(a\d+np:\n)hex\.sign 3, p_hp, a\d+pd, a\d+hz\na\d+hz:\nhex\.if0 3, p_hp, a\d+pd\n", r"\1"),
    # A_ReFire: fires at p_health <= 0
    "refirehp": (r"(a\d+go:\n)hex\.sign 3, p_hp, a\d+no, a\d+hz\na\d+hz:\nhex\.if0 3, p_hp, a\d+no\n", r"\1"),
    # A_Lower: the dead player's weapon goes on to the pending weapon's raise
    "lowerdead": (r"hex\.if1 1, p_dead, a\d+dd\n", ""),
    # P_PlayerThink: a dead player's number keys still change the pending weapon (the P5 pre-review's B1)
    "deadkeys": (r"hex\.if1 1, p_dead, wk_end\n", ""),
}


def _hurt_run(tmp_path, name, kind, mut=None):
    script, rows = _hurt_script(kind)
    w = _hurt_world()
    text, states, frames = _hurt_program(_start(w), H.level_start(w), mut)
    src = tmp_path / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    feed = b"".join(bytes([1, int(k["fire"]) | int(k["w1"]) << 1 | int(k["w2"]) << 2 | int(k["w3"]) << 3
                           | int(k["w4"]) << 4, p, d]) for k, p, d in script) + bytes([0])
    io = FixedIO(feed)
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = [[int(v, 16) for v in line.split(",")[:len(HURT_CELLS)]]
           for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:HURT_TICS]]
    want = [_want(r, states, frames) + [r["p_health"] & 0xFFF, r["p_damagecount"], r["p_dead"]] for r in rows]
    return got, want


def test_the_hurt_scripts_reach_their_paths():
    """each script reaches what it is for: a kill by damage (the weapon then held at the bottom), the ready weapon
    lowered by health 0, a refire refused at health 0"""
    _s, rows = _hurt_script("kill")
    dead = [r for r in rows if r["p_dead"]]
    assert len(dead) >= 30 and dead[-1]["p_wpn_sy"] == WC.BOTTOM and dead[0]["p_health"] <= 0
    for kind in ("ready", "refire"):
        script, rows = _hurt_script(kind)
        t0 = next(t for t, (_k, p, _d) in enumerate(script) if p & 1)
        before, after = rows[t0 - 1], rows[t0 + 3]
        assert after["p_wpn_sy"] > before["p_wpn_sy"] or after["p_wpn_state"] != before["p_wpn_state"], kind
        assert rows[-1]["p_wpn_sy"] == WC.BOTTOM and rows[-1]["p_dead"]
    script, rows = _hurt_script("deadkeys")
    td = next(t for t, r in enumerate(rows) if r["p_dead"])
    pressed = [t for t in range(td + 1, len(rows)) if any(script[t][0][x] for x in ("w1", "w2", "w3"))]
    assert len(pressed) >= 10, len(pressed)                           # keys naming owned weapons, after the death
    assert all(rows[t]["p_pending"] == rows[td]["p_pending"] for t in range(td, len(rows)))   # ... change nothing
    script, rows = _hurt_script("refire")
    t0 = next(t for t, (_k, p, _d) in enumerate(script) if p & 1)
    tr = next(t for t in range(t0, t0 + 20) if gd.STATES[gd.STATE_NAMES[rows[t]["p_wpn_state"]]].action == "A_ReFire")
    assert all(script[t][0]["fire"] for t in range(t0, t0 + 20))        # held on through A_ReFire ...
    assert rows[tr]["p_refire"] == 0 and rows[t0 + 19]["ammo"] == rows[tr]["ammo"]     # ... which refused


@pytest.mark.parametrize("kind", ["kill", "ready", "refire", "deadkeys"])
def test_the_hurt_weapon_is_the_model_tic_by_tic(tmp_path, kind):
    got, want = _hurt_run(tmp_path, "wpnh_" + kind, kind)
    bad = _first_bad(got, want)
    names = [c for c, _n in HURT_CELLS]
    assert bad is None, "tic %d: %s" % (bad, {names[i]: (got[bad][i], want[bad][i]) for i in range(len(names))
                                             if got[bad][i] != want[bad][i]})


@pytest.mark.parametrize("mut,kind", [("readyhp", "ready"), ("refirehp", "refire"), ("lowerdead", "kill"),
                                      ("deadkeys", "deadkeys")])
def test_the_checks_catch_a_broken_hurt_weapon(tmp_path, mut, kind):
    got, want = _hurt_run(tmp_path, "wpnh_" + mut, kind, mut)
    bad = _first_bad(got, want)
    assert bad is not None, "the mutant %s went unnoticed" % mut
    print("mutant %s caught at tic %d" % (mut, bad))
