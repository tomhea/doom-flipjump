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
"""
import random
import struct

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj import weaponcode as WC
from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.world import KEYS, World

N = 600
CELLS = (("wp_rdy", 1), ("wp_pend", 1), ("wp_st", 2), ("wp_tics", 1), ("wp_sy", 2), ("fl_st", 2), ("fl_tics", 1),
         ("wp_rf", 2), ("wp_ad", 1), ("am_clip", 3), ("am_shell", 3), ("rng_pl", 2), ("wp_frm", 1), ("fl_frm", 1),
         ("hud_v", 3), ("hud_v + 9*dw", 3))


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
    w = World(skill=gd.SK_HARD, monsters="idle", player="fire")
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


def _program(start, mut=None):
    states = WC.weapon_states()
    frames = WC.overlay_frames(states)
    text = "\n".join(WC.weapon_lines(states, frames))
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
            bar[0] | bar[1] << 4 | bar[2] << 8, bar[9] | bar[10] << 4 | bar[11] << 8]


def _run(tmp_path, name, mut=None, saw=True):
    script = _script()
    w = _world(saw)
    text, states, frames = _program(_start(w), mut)
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


@pytest.mark.parametrize("mut", sorted(MUTS))
def test_the_checks_catch_a_broken_weapon(tmp_path, mut):
    got, want = _run(tmp_path, mut, mut)
    bad = _first_bad(got, want)
    assert bad is not None, "the mutant %s went unnoticed" % mut
    print("mutant %s caught at tic %d" % (mut, bad))
