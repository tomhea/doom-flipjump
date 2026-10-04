"""M7 P4.1 -- the player's weapon in fj: the weapon keys and DOOM's psprite machine (P_MovePsprites / P_SetPsprite and
the psprite actions), the model's "fire" mode (`World(player="fire")`, docs/gp-combat.md section 1). The model it
mirrors is `combat.CombatMixin` (`_weapon_keys`, `_move_psprites`, `_set_psprite`, `_a_*`, `_check_ammo`,
`_fire_weapon`, `_a_fire_bullets`, `_a_melee`).

THE SHAPE. Every weapon state s gets one baked block, `wen<s>`: set the state, its tics and its overlay frame, run the
state's action inline, then -- when the state's tics are 0 -- go on to `wen<next(s)>`. An action that sets the
weapon's psprite again (A_WeaponReady lowering or firing, A_Lower's raise, A_Raise's ready, A_ReFire) JUMPS to that
state's block: in the model the nested P_SetPsprite runs to a state with tics, and the outer loop then returns, so a
tail jump is exact. A target that depends on the ready weapon (its down / up / ready / attack / flash state) is a
dispatch on `wp_rdy`. The FLASH is the other psprite: its blocks `fen<s>` are an fcall'd subroutine (`fl_ret`), set
by the fire actions in the middle of the weapon's action and stepped after the weapon each tic, as DOOM orders them.
Every path through the blocks ends at a state with tics (the model asserts the same), so nothing loops.

THE ROLLS. In the "fire" mode a shot's outcome is never read, so the player's stream only ADVANCES: 1 draw for the
pistol's accurate first shot, 3 for every other bullet, pellet, punch and saw tooth (`combat.Sites`: pistol_acc 1,
gunshot 3, punch 3, saw 3). P4.2 reads the outcomes.

NOT HERE (the model's "fire" mode leaves them out too): the player thing's states, the noise alert, the target, every
effect; p_health <= 0 (nothing hurts the player until P5) and berserk (P6) -- each marked where its test belongs.
"""
from __future__ import annotations

from typing import Dict, List

from doomfj import gamedata as gd
from doomfj.wireformat import KEY_FIRE_MASK

# the four E1M1 weapons (WP_*), in the order of `wp_own`'s nibbles; key 4 names the chaingun, which E1M1 never gives
WEAPONS = (gd.WP_FIST, gd.WP_PISTOL, gd.WP_SHOTGUN, gd.WP_CHAINSAW)
OWN = {w: i for i, w in enumerate(WEAPONS)}
NOCHANGE = gd.WP_NOCHANGE                       # 10
TOP, BOTTOM = gd.WEAPONTOP >> 16, gd.WEAPONBOTTOM >> 16
LOWER, RAISE = gd.LOWERSPEED >> 16, gd.RAISESPEED >> 16
AMMO_CELL = {gd.AM_CLIP: "am_clip", gd.AM_SHELL: "am_shell"}
# the stream's draws per shot ("fire" mode: advanced, not read)
DRAWS = {"pistol_acc": 1, "gunshot": 3, "punch": 3, "saw": 3}


def weapon_states() -> List[str]:
    """the psprite states E1M1's weapons can reach, S_NULL first: the LOCAL index `wp_st` / `fl_st` hold"""
    names = set()
    todo = [s for w in WEAPONS for s in (gd.WEAPONINFO[w].upstate, gd.WEAPONINFO[w].downstate,
                                         gd.WEAPONINFO[w].readystate, gd.WEAPONINFO[w].atkstate,
                                         gd.WEAPONINFO[w].flashstate)]
    while todo:
        s = todo.pop()
        if s in names or s == gd.S_NULL:
            continue
        names.add(s)
        todo.append(gd.STATES[s].next)
    return [gd.S_NULL] + sorted(names, key=lambda n: gd.STATE_INDEX[n])


def psprite_states() -> List[str]:
    """the states the WEAPON psprite can hold: the closure of the weapons' up / down / ready / attack states"""
    out, todo = set(), [s for w in WEAPONS for s in (gd.WEAPONINFO[w].upstate, gd.WEAPONINFO[w].downstate,
                                                     gd.WEAPONINFO[w].readystate, gd.WEAPONINFO[w].atkstate)]
    while todo:
        s = todo.pop()
        if s not in out:
            assert s != gd.S_NULL, "a weapon state leads to S_NULL: the weapon psprite would vanish"
            out.add(s)
            todo.append(gd.STATES[s].next)
    return sorted(out, key=lambda n: gd.STATE_INDEX[n])


def flash_states() -> List[str]:
    """the states the FLASH psprite can hold: the closure of the weapons' flash states (and S_NULL)"""
    out, todo = {gd.S_NULL}, [gd.WEAPONINFO[w].flashstate for w in WEAPONS]
    while todo:
        s = todo.pop()
        if s not in out:
            out.add(s)
            todo.append(gd.STATES[s].next)
    return sorted(out, key=lambda n: gd.STATE_INDEX[n])


def overlay_frames(states=None) -> List[str]:
    """the WEAPON psprite's distinct LUMPS (sprite + frame letter + '0', DOOM's rotation-less name): `wp_frm` indexes
    this list (<= 16, one nibble). `states` is unused -- the list is the weapon psprite's, whatever the caller holds."""
    out = []
    for s in psprite_states():
        lump = psprite_lump(s)
        if lump not in out:
            out.append(lump)
    assert len(out) <= 16, out
    return out


def flash_frames() -> List[str]:
    """the FLASH psprite's distinct lumps: `fl_frm` is 1 + the index here, 0 = no flash"""
    out = []
    for s in flash_states():
        if s != gd.S_NULL and psprite_lump(s) not in out:
            out.append(psprite_lump(s))
    assert len(out) <= 15, out
    return out


def psprite_lump(state: str) -> str:
    st = gd.STATES[state]
    return "%s%s0" % (st.sprite, chr(ord("A") + (st.frame & 0x7FFF)))


def ammo_digit_values(n: int = 512) -> List[int]:
    """`ammobcd`: an ammo count -> its three bar digits, packed as `hud_v`'s AMMO slots (hundreds in the low nibble;
    10 = blank). The bar reads `hud.digits`, so this is that function tabled."""
    from doomfj import hud
    from doomfj.hudcode import BLANK
    out = []
    for v in range(n):
        d = [BLANK if x is None else x for x in hud.digits(v)]
        out.append(d[0] | d[1] << 4 | d[2] << 8)
    return out


def weapon_decls(start: dict, states: List[str], frames: List[str]) -> List[str]:
    """the weapon's cells at their level-start values (`start`: the model's ws fields)"""
    idx = {s: i for i, s in enumerate(states)}
    own = sum(int(bool(start["owned"][w])) << (4 * OWN[w]) for w in WEAPONS)
    wst = gd.STATE_NAMES[start["p_wpn_state"]]
    fst = gd.STATE_NAMES[start["p_flash_state"]]
    return [f"wp_rdy: hex.vec 1, {start['p_ready']}", f"wp_pend: hex.vec 1, {start['p_pending']}",
            f"wp_st: hex.vec 2, {idx[wst]}", f"wp_tics: hex.vec 1, {start['p_wpn_tics']}",
            f"wp_sy: hex.vec 2, {start['p_wpn_sy']}",
            f"fl_st: hex.vec 2, {idx[fst]}", f"fl_tics: hex.vec 1, {start['p_flash_tics']}",
            f"wp_rf: hex.vec 2, {start['p_refire']}", f"wp_ad: hex.vec 1, {start['p_attackdown']}",
            f"am_clip: hex.vec 3, {start['ammo'][gd.AM_CLIP]}", f"am_shell: hex.vec 3, {start['ammo'][gd.AM_SHELL]}",
            f"wp_own: hex.vec {len(WEAPONS)}, {own}", f"rng_pl: hex.vec 2, {start['rng_player']}",
            f"wp_frm: hex.vec 1, {frames.index(psprite_lump(wst))}",
            f"fl_frm: hex.vec 1, {0 if fst == gd.S_NULL else 1 + flash_frames().index(psprite_lump(fst))}",
            "fl_ret: hex.vec w/4", "wp_bcd: hex.vec 3"]


def _by_ready(prefix: str, target: Dict[int, str]) -> List[str]:
    """jump to target[w] for the ready weapon w (a 4-way if_flags chain on `wp_rdy`)"""
    out = []
    ws = sorted(target)
    for k, w in enumerate(ws[:-1]):
        out += [f"hex.if_flags wp_rdy, 1<<{w}, {prefix}_n{k}, {prefix}_y{k}",
                f"{prefix}_y{k}:", f";{target[w]}", f"{prefix}_n{k}:"]
    return out + [f";{target[ws[-1]]}"]


def weapon_lines(states: List[str], frames: List[str]) -> List[str]:
    """the frame's weapon tic: the number keys, then P_MovePsprites (the weapon, then the flash), then the bar's ammo
    and arms. Falls through at `wp_end`. Uses `pkeys` (fire: the high nibble's bit 3) and the held `kb_w1..kb_w4`."""
    idx = {s: i for i, s in enumerate(states)}
    flash_frame = {s: (0 if s == gd.S_NULL else 1 + flash_frames().index(psprite_lump(s))) for s in flash_states()}
    info = gd.WEAPONINFO
    wen = lambda s: "wen%d" % idx[s]                                   # noqa: E731
    fen = lambda s: "fen%d" % idx[s]                                   # noqa: E731
    out = ["// M7 P4.1 (doomfj.weaponcode): the weapon keys, P_MovePsprites, the bar's ammo + arms"]
    # -- 1. P_PlayerThink's BT_CHANGE: the LOWEST held number key names the weapon; 1 is the chainsaw when owned
    #    (berserk would keep the fist up -- P6); a weapon not owned, or already up, changes nothing
    out += ["hex.if0 1, kb_w1, wk_2",
            "hex.if0 1, wp_own + %d*dw, wk_fist" % OWN[gd.WP_CHAINSAW],
            "hex.if_flags wp_rdy, 1<<%d, wk_saw, wk_end" % gd.WP_CHAINSAW,
            "wk_saw:", "hex.set 1, wp_pend, %d" % gd.WP_CHAINSAW, ";wk_end",
            "wk_fist:", "hex.if0 1, wp_own + %d*dw, wk_end" % OWN[gd.WP_FIST],
            "hex.if_flags wp_rdy, 1<<%d, wk_fset, wk_end" % gd.WP_FIST,
            "wk_fset:", "hex.set 1, wp_pend, %d" % gd.WP_FIST, ";wk_end",
            "wk_2:", "hex.if0 1, kb_w2, wk_3",
            "hex.if0 1, wp_own + %d*dw, wk_end" % OWN[gd.WP_PISTOL],
            "hex.if_flags wp_rdy, 1<<%d, wk_pset, wk_end" % gd.WP_PISTOL,
            "wk_pset:", "hex.set 1, wp_pend, %d" % gd.WP_PISTOL, ";wk_end",
            "wk_3:", "hex.if0 1, kb_w3, wk_end",                      # key 4 names the chaingun: never owned
            "hex.if0 1, wp_own + %d*dw, wk_end" % OWN[gd.WP_SHOTGUN],
            "hex.if_flags wp_rdy, 1<<%d, wk_sset, wk_end" % gd.WP_SHOTGUN,
            "wk_sset:", "hex.set 1, wp_pend, %d" % gd.WP_SHOTGUN,
            "wk_end:"]
    # -- 2. P_MovePsprites, the weapon: tics down, and at 0 its next state's block
    out += ["hex.if0 2, wp_st, wp_flash",                             # S_NULL: not active (not on E1M1)
            "hex.dec 1, wp_tics",
            "hex.if0 1, wp_tics, wp_next", ";wp_flash",
            "wp_next:"]
    wps = psprite_states()
    out += _dispatch2("wpd", "wp_st", {idx[s]: wen(gd.STATES[s].next) for s in wps})
    # -- the weapon blocks
    for s in wps:
        st = gd.STATES[s]
        out += [f"{wen(s)}:", f"hex.set 2, wp_st, {idx[s]}", f"hex.set 1, wp_tics, {st.tics}",
                f"hex.set 1, wp_frm, {frames.index(psprite_lump(s))}"]
        out += _action(st.action, f"a{idx[s]}", wen, fen, flash_frame)
        out += [f";{wen(st.next)}" if st.tics == 0 else ";wp_flash"]
    # -- 3. P_MovePsprites, the flash
    out += ["wp_flash:",
            "hex.if0 2, fl_st, wp_bar",
            "hex.dec 1, fl_tics",
            "hex.if0 1, fl_tics, fl_next", ";wp_bar",
            "fl_next:"]
    fls = flash_states()
    out += _dispatch2("fld", "fl_st", {idx[s]: "flc%d" % idx[s] for s in fls if s != gd.S_NULL})
    for s in fls:
        if s != gd.S_NULL:
            out += [f"flc{idx[s]}:", f"stl.fcall {fen(gd.STATES[s].next)}, fl_ret", ";wp_bar"]
    # -- the flash blocks: an fcall'd chain, every exit a `stl.fret fl_ret`
    for s in fls:
        st = gd.STATES[s] if s != gd.S_NULL else None
        if s == gd.S_NULL:
            out += [f"{fen(s)}:", "hex.zero 2, fl_st", "hex.zero 1, fl_tics", "hex.zero 1, fl_frm", "stl.fret fl_ret"]
            continue
        assert st.action in (None, "A_Light0", "A_Light1", "A_Light2"), (s, st.action)   # extralight: dropped
        out += [f"{fen(s)}:", f"hex.set 2, fl_st, {idx[s]}", f"hex.set 1, fl_tics, {st.tics}",
                f"hex.set 1, fl_frm, {flash_frame[s]}",
                f";{fen(st.next)}" if st.tics == 0 else "stl.fret fl_ret"]
    # -- 4. the bar: the ready weapon's ammo (blank for the fist and the chainsaw) and the owned weapons 2 3 4
    out += ["wp_bar:"]
    out += _by_ready("wpb", {gd.WP_FIST: "wpb_none", gd.WP_PISTOL: "wpb_clip", gd.WP_SHOTGUN: "wpb_shell",
                             gd.WP_CHAINSAW: "wpb_none"})
    out += ["wpb_clip:", "ammobcd.lookup wp_bcd, am_clip", ";wpb_set",
            "wpb_shell:", "ammobcd.lookup wp_bcd, am_shell", ";wpb_set",
            "wpb_none:", "hex.set 3, wp_bcd, %d" % (10 | 10 << 4 | 10 << 8),
            "wpb_set:", "hex.mov 3, hud_v, wp_bcd",
            "hex.mov 1, hud_v + 9*dw, wp_own + %d*dw" % OWN[gd.WP_PISTOL],
            "hex.mov 1, hud_v + 10*dw, wp_own + %d*dw" % OWN[gd.WP_SHOTGUN],
            "hex.mov 1, hud_v + 11*dw, wp_own + %d*dw" % OWN[gd.WP_CHAINSAW],
            "wp_end:"]
    return out


def _dispatch2(prefix: str, cell: str, targets: Dict[int, str]) -> List[str]:
    """jump to targets[v] for the 2-nibble value of `cell` (v < 64): a tree on the high nibble, then a chain on the low"""
    out, his = [], sorted({v >> 4 for v in targets})
    for h in his:
        out += [f"hex.if_flags {cell} + dw, 1<<{h}, {prefix}_hn{h}, {prefix}_h{h}", f"{prefix}_hn{h}:"]
    out += [";wp_bad"]
    for h in his:
        out.append(f"{prefix}_h{h}:")
        los = sorted(v & 15 for v in targets if v >> 4 == h)
        for lo in los:
            out += [f"hex.if_flags {cell}, 1<<{lo}, {prefix}_{h}n{lo}, {prefix}_{h}y{lo}",
                    f"{prefix}_{h}y{lo}:", f";{targets[h << 4 | lo]}", f"{prefix}_{h}n{lo}:"]
        out.append(";wp_bad")
    return out


def _check_ammo(p: str, wen, ok: str) -> List[str]:
    """P_CheckAmmo: enough for one shot -> `ok`; else the next weapon by DOOM's preference and the ready weapon's
    downstate (a tail jump). E1M1 owns no plasma, chaingun, launcher or BFG, so the preference is: the shotgun with
    shells, the pistol with bullets, the chainsaw, the fist."""
    info = gd.WEAPONINFO
    out = _by_ready(f"{p}ca", {gd.WP_FIST: ok, gd.WP_PISTOL: f"{p}cp", gd.WP_SHOTGUN: f"{p}cs", gd.WP_CHAINSAW: ok})
    out += [f"{p}cp:", f"hex.if0 3, am_clip, {p}cx", f";{ok}",
            f"{p}cs:", f"hex.if0 3, am_shell, {p}cx", f";{ok}",
            f"{p}cx:",
            f"hex.if0 1, wp_own + {OWN[gd.WP_SHOTGUN]}*dw, {p}cx1", f"hex.if0 3, am_shell, {p}cx1",
            f"hex.set 1, wp_pend, {gd.WP_SHOTGUN}", f";{p}cdn",
            f"{p}cx1:", f"hex.if0 3, am_clip, {p}cx2", f"hex.set 1, wp_pend, {gd.WP_PISTOL}", f";{p}cdn",
            f"{p}cx2:", f"hex.if0 1, wp_own + {OWN[gd.WP_CHAINSAW]}*dw, {p}cx3",
            f"hex.set 1, wp_pend, {gd.WP_CHAINSAW}", f";{p}cdn",
            f"{p}cx3:", f"hex.set 1, wp_pend, {gd.WP_FIST}",
            f"{p}cdn:"]
    return out + _by_ready(f"{p}cd", {w: wen(info[w].downstate) for w in WEAPONS})


def _fire_weapon(p: str, wen) -> List[str]:
    """P_FireWeapon: the ammo check, then the ready weapon's attack state (a tail jump)"""
    info = gd.WEAPONINFO
    return (_check_ammo(p, wen, f"{p}fok") + [f"{p}fok:"]
            + _by_ready(f"{p}fa", {w: wen(info[w].atkstate) for w in WEAPONS}))


def _action(action, p: str, wen, fen, flash_frame) -> List[str]:
    """one state's action, inline; it ends by falling through (no psprite set) or by a tail jump"""
    info = gd.WEAPONINFO
    if action in (None, "A_Light0", "A_Light1", "A_Light2"):
        return []                                                        # extralight: dropped (plan section 2, C)
    if action == "A_WeaponReady":
        # (p_health <= 0 also lowers -- P5 brings damage); the fire key; else attackdown off and the weapon at the top
        return ([f"hex.if_flags wp_pend, 1<<{NOCHANGE}, {p}pd, {p}np", f"{p}pd:"]
                + _by_ready(f"{p}dn", {w: wen(info[w].downstate) for w in WEAPONS})
                + [f"{p}np:", f"hex.if_flags pkeys + dw, {KEY_FIRE_MASK:#06x}, {p}nf, {p}f",
                   # "the missile launcher and bfg do not auto fire": E1M1 has neither, so a held key always fires
                   f"{p}f:", "hex.set 1, wp_ad, 1"]
                + _fire_weapon(p, wen)
                + [f"{p}nf:", "hex.zero 1, wp_ad", f"hex.set 2, wp_sy, {TOP}"])
    if action == "A_Lower":
        # (the dead player keeps it down -- P7; p_health <= 0 drops it -- P5)
        return ([f"hex.add_constant 2, wp_sy, {LOWER}",
                 f"hex.cmp 2, wp_sy, wp_bottom_c, {p}lo, {p}bt, {p}bt", f"{p}bt:",
                 "hex.mov 1, wp_rdy, wp_pend",
                 # _bring_up_weapon: (a pending of NOCHANGE raises the ready weapon again -- unreachable here,
                 # A_Lower runs only after a pending was set, and kept exact anyway)
                 f"hex.if_flags wp_pend, 1<<{NOCHANGE}, {p}bu, {p}bk", f"{p}bk:", "hex.mov 1, wp_pend, wp_rdy",
                 f"{p}bu:", f"hex.set 1, wp_pend, {NOCHANGE}", f"hex.set 2, wp_sy, {BOTTOM}"]
                + _by_ready(f"{p}up", {w: wen(info[w].upstate) for w in WEAPONS})
                + [f"{p}lo:"])
    if action == "A_Raise":
        return ([f"hex.sub_constant 2, wp_sy, {RAISE}",
                 f"hex.cmp 2, wp_sy, wp_top_c, {p}tp, {p}tp, {p}hi", f"{p}tp:",
                 f"hex.set 2, wp_sy, {TOP}"]
                + _by_ready(f"{p}rd", {w: wen(info[w].readystate) for w in WEAPONS})
                + [f"{p}hi:"])
    if action == "A_ReFire":
        # fire held and no pending (and p_health > 0 -- P5): refire++ (saturating) and fire; else refire 0, check ammo
        return ([f"hex.if_flags pkeys + dw, {KEY_FIRE_MASK:#06x}, {p}no, {p}fh",
                 f"{p}fh:", f"hex.if_flags wp_pend, 1<<{NOCHANGE}, {p}no, {p}go",
                 f"{p}go:", f"hex.if_flags wp_rf + dw, 1<<15, {p}inc, {p}sat", f"{p}sat:",
                 f"hex.if_flags wp_rf, 1<<15, {p}inc, {p}fire",
                 f"{p}inc:", "hex.inc 2, wp_rf",
                 f"{p}fire:"]
                + _fire_weapon(p, wen)
                + [f"{p}no:", "hex.zero 2, wp_rf"]
                + _check_ammo(p + "r", wen, f"{p}ok") + [f"{p}ok:"])
    if action in ("A_FirePistol", "A_FireShotgun"):
        pistol = action == "A_FirePistol"
        w = gd.WP_PISTOL if pistol else gd.WP_SHOTGUN
        out = [f"hex.sub_constant 3, {AMMO_CELL[info[w].ammo]}, 1",
               f"stl.fcall {fen(info[w].flashstate)}, fl_ret"]
        if pistol:                                                       # accurate = no refire: 1 draw, else 3
            out += [f"hex.if0 2, wp_rf, {p}acc", f"hex.add_constant 2, rng_pl, {DRAWS['gunshot']}", f";{p}drw",
                    f"{p}acc:", f"hex.add_constant 2, rng_pl, {DRAWS['pistol_acc']}", f"{p}drw:"]
        else:
            out += [f"hex.add_constant 2, rng_pl, {(7 * DRAWS['gunshot']) & 0xFF}"]
        return out
    if action == "A_Punch":
        return [f"hex.add_constant 2, rng_pl, {DRAWS['punch']}"]
    if action == "A_Saw":
        return [f"hex.add_constant 2, rng_pl, {DRAWS['saw']}"]
    raise NotImplementedError("%s on an E1M1 psprite" % action)


def weapon_const_decls() -> List[str]:
    return [f"wp_bottom_c: hex.vec 2, {BOTTOM}", f"wp_top_c: hex.vec 2, {TOP}"]
