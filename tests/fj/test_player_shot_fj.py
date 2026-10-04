"""M7 P4.2a -- the player's shot in fj (`doomfj.weaponcode`, `shoot=True`) against the model, tic by tic.

The REAL emitted text (`weapon_lines(..., shoot=True)`, the `wpo` table, the shot's cells) runs in a loop fed, per
tic, the key byte (fire, the number keys) and a POKED aim window: 17 random sids written straight into `aim_sid`.
`dm_go` is a RECORDER stub: it prints dm_id, dm_dmg, dm_melee and dm_reach and returns. The model is fed the same
keys and, through a stub `aim` that reads the same poked window, the same targets.

WHAT IS COMPARED: the CALLS, BEFORE the reach test. A call is (sid, damage, melee, reach) for every shot whose window
cell is not 0, in order -- the model's `ev.shots` (weapon, column, _, damage) with the poked window at that column.
The reach test (`_line_attack`'s AproxDistance against 64 / 65) is the callee's (`dm_reach` is handed on), so it is
NOT reproduced here; `dm_reach` is compared for melee calls only (bullets do not write it). Every tic also compares
the stream `rng_pl` (and the P4.1 cells), so a shot that draws a different count parts the stream.
The model runs in its "fire" mode, whose `ev.shots` carries each shot's column and damage, and -- when the model
has them -- in its "shoot" and "hit" modes with the stub aim, where the aim must also be asked the same columns in
the same order and every `ev.hits` entry must be one of the calls (the reach test only removes calls). "hit" also
hurts the player (P5's pain roll draws on rng_player), so it is compared up to the first tic the player is hurt.

R9: four mutants of the emitted text, each caught (the first differing tic is printed):
  * column +1: every window read takes the next cell
  * the accurate pistol shot takes the table's column instead of the window's centre
  * the shotgun draws 6 pellets
  * the saw hands on dm_melee = 0
"""
import random
import re

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj import weaponcode as WC
from doomfj.combat import PUNCH_REACH, SAW_REACH
from doomfj.config import GAME_CFG
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.world import KEYS, PLAYER_MODES, World

N = 1500
CELLS = (("wp_rdy", 1), ("wp_st", 2), ("wp_rf", 2), ("am_clip", 3), ("am_shell", 3), ("rng_pl", 2))
MELEE = {"fist": PUNCH_REACH, "chainsaw": SAW_REACH}
MAXSID = 53                                     # E1M1's monster slots (gp-aim-window 1.1): ids 1..53
LO, CENTRE, HI = WC.shot_window()


def _script(seed, saw):
    """runs of held fire and taps (the pistol's accurate shot is the tap's), weapon switches through every weapon"""
    rng = random.Random(seed)
    keys, fire = [], False
    order = ["w2", "w3", "w1", "w2", "w1", "w3"]
    for t in range(N):
        if rng.random() < (0.03 if fire else 0.08):    # held ~70% of the time, in runs; taps between
            fire = not fire
        k = {name: False for name in KEYS}
        k["fire"] = fire or rng.random() < 0.08
        if t % 80 == 40:                              # a switch every 80 tics: ~32 tics of lower + raise
            k[order[(t // 80) % len(order)]] = True
        keys.append(k)
    return keys


def _windows(seed):
    rng = random.Random(seed * 7919 + 1)
    out = []
    for _t in range(N):
        if rng.random() < 0.15:
            out.append([0] * WC.AIM_N)
        else:
            out.append([rng.randint(1, MAXSID) if rng.random() < 0.6 else 0 for _ in range(WC.AIM_N)])
    return out


def _world(saw, mode="fire", aim=None):
    w = World(skill=gd.SK_HARD, monsters="idle", player=mode, aim=aim)
    ws = w.ws
    ws.p_owned[gd.WP_SHOTGUN] = 1
    ws.p_owned[gd.WP_CHAINSAW] = int(saw)
    ws.p_ammo[gd.AM_SHELL] = 30
    ws.p_ammo[gd.AM_CLIP] = 80
    return w


def _start(w):
    ws = w.ws
    return {f: getattr(ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                        "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown", "rng_player")} \
        | {"ammo": list(ws.p_ammo), "owned": list(ws.p_owned)}


def _col_plus1(text):
    """every window read takes the next cell (the last, column 16, has none: it keeps its own)"""
    last = 2 * (WC.AIM_N - 1)
    new, n = re.subn(r"hex\.mov 2, dm_id, aim_sid \+ (\d+)\*dw\n;shc_end",
                     lambda m: "hex.mov 2, dm_id, aim_sid + %d*dw\n;shc_end" % min(int(m.group(1)) + 2, last), text)
    assert n == WC.AIM_N
    return new


def _six_pellets(text):
    new, n = re.subn(r"(a\d+pel6:)\nstl\.fcall sh_rd3, sh_ret\nstl\.fcall sh_gun, sh_ret\n", r"\1\n", text)
    assert n == 1
    return new


MUTS = {
    "col_plus1": _col_plus1,
    "acc_table_col": lambda t: t.replace("hex.mov 2, dm_id, aim_sid + %d*dw\nstl.fcall sh_gun" % (2 * (CENTRE - LO)),
                                         "stl.fcall sh_col, sh_ret\nstl.fcall sh_gun"),
    "six_pellets": _six_pellets,
    "saw_not_melee": lambda t: t.replace("hex.set 1, dm_melee, 1\nhex.set 2, dm_reach, %d" % SAW_REACH,
                                         "hex.set 1, dm_melee, 0\nhex.set 2, dm_reach, %d" % SAW_REACH),
}


def _program(start, mut=None):
    states = WC.weapon_states()
    frames = WC.overlay_frames(states)
    text = "\n".join(WC.weapon_lines(states, frames, shoot=True)) + "\n"
    if mut:
        new = MUTS[mut](text)
        assert new != text, mut
        text = new
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, kin",
            "hex.input %d, aim_sid" % WC.AIM_N,                        # the poked window
            "hex.zero 2, pkeys",
            "hex.if_flags kin, 0xAAAA, kf_no, kf_yes", "kf_yes:", "hex.xor_by pkeys + dw, 0x8", "kf_no:",
            "hex.zero 1, kb_w1", "hex.zero 1, kb_w2", "hex.zero 1, kb_w3", "hex.zero 1, kb_w4",
            "hex.if_flags kin, 0xCCCC, k1_no, k1_yes", "k1_yes:", "hex.set 1, kb_w1, 1", "k1_no:",
            "hex.if_flags kin, 0xF0F0, k2_no, k2_yes", "k2_yes:", "hex.set 1, kb_w2, 1", "k2_no:",
            "hex.if_flags kin, 0xFF00, k3_no, k3_yes", "k3_yes:", "hex.set 1, kb_w3, 1", "k3_no:",
            "hex.if_flags kin + dw, 0xAAAA, k4_no, k4_yes", "k4_yes:", "hex.set 1, kb_w4, 1", "k4_no:",
            text,
            "stl.output 124",                                           # '|': the calls end, the cells follow
            *[x for c, n in CELLS for x in ("hex.print_as_digit %d, %s, 0" % (n, c), "stl.output 44")],
            "stl.output 10", ";loop",
            # the damage machinery's stub: record the call, return
            "dm_go:",
            "hex.print_as_digit 2, dm_id, 0", "stl.output 46", "hex.print_as_digit 2, dm_dmg, 0", "stl.output 46",
            "hex.print_as_digit 1, dm_melee, 0", "stl.output 46", "hex.print_as_digit 2, dm_reach, 0",
            "stl.output 59", "stl.fret dm_ret",
            "bad:", "stl.loop", "done:", "stl.loop",
            "rmagic: hex.vec 2", "kin: hex.vec 2", "pkeys: hex.vec 2",
            "kb_w1: hex.vec 1", "kb_w2: hex.vec 1", "kb_w3: hex.vec 1", "kb_w4: hex.vec 1",
            "aim_sid: hex.vec %d" % (2 * WC.AIM_N), "dm_ret: hex.vec w/4",
            *WC.weapon_decls(start, states, frames), *WC.weapon_const_decls(), *WC.shot_decls(),
            *hudcode.hud_decls(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))),
            generate_dispatch_table_fj("ammobcd", WC.ammo_digit_values(), index_nibbles=3, result_nibbles=3),
            WC.shot_table_fj()]
    return "\n".join(body) + "\n"


def _model(script, windows, saw, mode):
    """per tic: (the calls before the reach test, the cells); in "shoot" mode also the aim's columns and the hits"""
    cur = {"win": None, "cols": []}

    def stub_aim(world, col):
        cur["cols"].append(col)
        sid = cur["win"][col - LO]
        return ("mon", sid - 1) if sid else None

    w = _world(saw, mode, stub_aim)
    rows = []
    for k, win in zip(script, windows):
        cur["win"], cur["cols"] = win, []
        ev = w.tic(k)
        calls = []
        for weapon, col, _tgt, dmg in ev.shots:
            sid = win[col - LO]
            if sid:
                melee = weapon in MELEE
                calls.append((sid, dmg, int(melee), MELEE.get(weapon)))
        ws = w.ws
        idx = {gd.STATE_INDEX[s]: i for i, s in enumerate(WC.weapon_states())}
        cells = [ws.p_ready, idx[ws.p_wpn_state], ws.p_refire, ws.p_ammo[gd.AM_CLIP], ws.p_ammo[gd.AM_SHELL],
                 ws.rng_player]
        rows.append({"calls": calls, "cells": cells, "shots": list(ev.shots), "cols": list(cur["cols"]),
                     "hits": list(ev.hits), "hurt": bool(ev.player_hurt)})
    return rows


def _run_fj(tmp_path, name, script, windows, saw, mut=None):
    w = _world(saw)
    text = _program(_start(w), mut)
    src = tmp_path / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp_path / (name + ".fjm")
    consts = GAME_CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    feed = b"".join(bytes([1, int(k["fire"]) | int(k["w1"]) << 1 | int(k["w2"]) << 2 | int(k["w3"]) << 3
                           | int(k["w4"]) << 4] + win) for k, win in zip(script, windows)) + bytes([0])
    io = FixedIO(feed)
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    rows = []
    for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:N]:
        calls_txt, _, cells_txt = line.partition("|")
        calls = []
        for c in filter(None, calls_txt.split(";")):
            sid, dmg, melee, reach = (int(v, 16) for v in c.split("."))
            calls.append((sid, dmg, melee, reach if melee else None))
        rows.append({"calls": calls, "cells": [int(v, 16) for v in cells_txt.split(",")[:len(CELLS)]]})
    return rows


def _first_bad(got, want):
    assert len(got) == len(want), "the program printed %d tics of %d" % (len(got), len(want))
    return next((t for t, (g, w) in enumerate(zip(got, want))
                 if g["calls"] != w["calls"] or g["cells"] != w["cells"]), None)


CASES = [(True, 1), (True, 2), (False, 3), (False, 4)]       # (the chainsaw owned, the seed)
# each skipped when the model lacks it. "hit" (P4.2's full player) also HURTS the player -- a monster the shots woke
# fires back, and the pain roll draws on rng_player (P5's, not the shot's) -- so it is compared up to the first tic
# the player is hurt.
MODES = ["fire", "shoot", "hit"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("saw,seed", CASES)
def test_the_shot_is_the_model_tic_by_tic(tmp_path, saw, seed, mode):
    if mode not in PLAYER_MODES:
        pytest.skip("the model has no %r mode on this branch (PLAYER_MODES = %s)" % (mode, PLAYER_MODES))
    script, windows = _script(seed, saw), _windows(seed)
    want = _model(script, windows, saw, mode)
    got = _run_fj(tmp_path, "shot", script, windows, saw)
    assert len(got) == len(want), "the program printed %d tics of %d" % (len(got), len(want))
    cut = next((t for t, r in enumerate(want) if r["hurt"]), N) if mode == "hit" else N
    want, got = want[:cut], got[:cut]
    bad = _first_bad(got, want)
    assert bad is None, "tic %d: fj %s, model %s" % (bad, got[bad], want[bad])
    if mode != "fire":
        for t, r in enumerate(want):                  # the aim is asked the shots' own columns, in order ...
            assert r["cols"] == [c for _w, c, _t, _d in r["shots"]], t
            calls = [(sid - 1, dmg) for sid, dmg, _m, _r in r["calls"]]
            for weapon, kind, i, dmg in r["hits"]:     # ... and the reach test only removes calls
                if weapon in ("pistol", "shotgun", "fist", "chainsaw"):
                    assert kind == "mon" and (i, dmg) in calls, (t, r["hits"], r["calls"])
    # vacuity: what the run claims to cover, it covered
    shots = [s for r in want for s in r["shots"]]
    calls = [c for r in want for c in r["calls"]]
    weapons = {s[0] for s in shots}
    assert weapons == ({"pistol", "shotgun", "chainsaw"} if saw else {"pistol", "shotgun", "fist"}), weapons
    assert any(s[0] == "pistol" and s[1] == CENTRE for s in shots)                  # an accurate shot
    assert any(s[0] == "pistol" and s[1] != CENTRE for s in shots)                  # a refire bullet
    assert {c[2] for c in calls} == {0, 1} and len(calls) > 25
    assert len({s[1] for s in shots}) >= 12                                         # most columns drawn
    print("%s saw=%s seed=%d: %d tics, %d shots, %d calls (%s)" % (mode, saw, seed, cut, len(shots), len(calls),
                                                                   sorted(weapons)))


@pytest.mark.parametrize("mut", sorted(MUTS))
def test_the_checks_catch_a_broken_shot(tmp_path, mut):
    saw = mut == "saw_not_melee"
    seed = 1 if saw else 3
    script, windows = _script(seed, saw), _windows(seed)
    want = _model(script, windows, saw, "fire")
    got = _run_fj(tmp_path, mut, script, windows, saw, mut)
    bad = _first_bad(got, want)
    assert bad is not None, "the mutant %s went unnoticed" % mut
    print("mutant %s caught at tic %d: fj %s, model %s" % (mut, bad, got[bad], want[bad]))
