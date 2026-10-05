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

THE SHOT (M7 P4.2a, `shoot=True`; off, the emission is P4.1's to the byte). Each shot reads its outcome from ONE folded
table, `wpo` (D10), indexed like `rng.p_random_outcome` by the stream's state after the shot's FIRST draw. A row
(`shot_row`) is the melee damage (nibbles 0-1: A_Punch's `(a%10+1)<<1`, which is A_Saw's `2*(a%10+1)`), the gun
damage (nibble 2: P_GunShot's `5*(a%3+1)`) and the column INDEX into the aim window (nibbles 3-4: `col(b-c) -
aim_lo`, 0..16), for the shot's three draws a, b, c (`shot_values`; `verify_shot_table` holds every field to
`combat.Sites` at all 256 indices). The pistol's accurate shot draws once and reads only the gun damage: its column
is the window's centre. The stream advances exactly as in "fire": +1 for the accurate shot, +3 for every other
bullet, pellet, punch and saw tooth (the 3-draw leaf `sh_rd3` is `inc`, the lookup, `+2`).
The column reads `aim_sid` (the window's 17 two-nibble cells; column aim_lo + i at `aim_sid + 2*i*dw`; 0 empty, else
1 + the monster slot), and a shot whose cell is not 0 is handed on through the FIXED interface to the damage
machinery: `dm_id` (2 nibbles) = the sid, `dm_dmg` (2) = the damage, `dm_melee` (1) = 1 for the fist and the saw, 0
for bullets, `dm_reach` (2) = 64 for the fist, 65 for the saw (`combat.PUNCH_REACH` / `SAW_REACH`; written for melee
only -- the callee applies the reach test), then `stl.fcall dm_go, dm_ret`. `dm_go` / `dm_ret` are the callee's
labels and `aim_sid` the aim window's; this module declares `dm_id`, `dm_dmg`, `dm_melee`, `dm_reach`, `sh_row` and
`sh_ret` (`shot_decls`) and the `wpo` table (`shot_table_fj`). The window holds monsters only in this rung: a barrel
id (P6) would be handed on like a monster's.

THE NOISE (M7 P4.2b, `noise=True`; off, the emission is P4.2a's to the byte): P_FireWeapon's P_NoiseAlert, an fcall
of `nz_leaf` (doomfj.noisecode) at each fire point once the ammo check passed.

NOT HERE (the model's "fire" mode leaves them out too): the player thing's states, the target, every
effect; p_health <= 0 (nothing hurts the player until P5: `hurt`, weapon_lines) and berserk (P6) -- each marked where
its test belongs.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional

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
    """the FLASH psprite's distinct lumps: `fl_frm` is 1 + the index here, 0 = no flash. Only states that last a tic
    are ever drawn: S_LIGHTDONE (0 tics, straight on to S_NULL) names SHTGE0, which no wad has."""
    out = []
    for s in flash_states():
        if s != gd.S_NULL and gd.STATES[s].tics != 0 and psprite_lump(s) not in out:
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
            f"fl_frm: hex.vec 1, {0 if fst == gd.S_NULL or gd.STATES[fst].tics == 0 else 1 + flash_frames().index(psprite_lump(fst))}",
            "fl_ret: hex.vec w/4", "wp_bcd: hex.vec 3",
            "wp_pass: hex.vec 1"]                         # M7 P6+P7: weapon_lines' tic counter (0 between frames)


def _by_ready(prefix: str, target: Dict[int, str]) -> List[str]:
    """jump to target[w] for the ready weapon w (a 4-way if_flags chain on `wp_rdy`)"""
    out = []
    ws = sorted(target)
    for k, w in enumerate(ws[:-1]):
        out += [f"hex.if_flags wp_rdy, 1<<{w}, {prefix}_n{k}, {prefix}_y{k}",
                f"{prefix}_y{k}:", f";{target[w]}", f"{prefix}_n{k}:"]
    return out + [f";{target[ws[-1]]}"]


def weapon_lines(states: List[str], frames: List[str], shoot: bool = False, noise: bool = False,
                 hurt: bool = False, tics: Optional[int] = None) -> List[str]:
    """the frame's weapon tic: the number keys, then P_MovePsprites (the weapon, then the flash), then the bar's ammo
    and arms. Falls through at `wp_end`. Uses `pkeys` (fire: the high nibble's bit 3) and the held `kb_w1..kb_w4`.
    `shoot` (P4.2a): every shot resolves through `aim_sid` and hands a monster to `dm_go` (the module docstring);
    off, the text is P4.1's and no shot label exists. `noise` (P4.2b, the "hit" mode): P_FireWeapon's P_NoiseAlert --
    every fire point calls `nz_leaf` (doomfj.noisecode); off, the text is P4.2a's. `hurt` (M7 P5, doomfj.hurtcode:
    the player can be hurt and killed): A_WeaponReady lowers at p_hp <= 0, A_ReFire fires only at p_hp > 0, and
    A_Lower keeps a dead player's (p_dead) weapon at the bottom; off, the text is the P4 one to the byte.
    `tics` (M7 P6+P7, the owner's x2 fire rate): P_MovePsprites runs this many times a frame -- the ONE weapon + flash
    block, looped on the scratch counter `wp_pass` (back to 0 when the loop ends), the keys before it and the bar
    after it once; default `world.WEAPON_TICS`, the model's own count (`combat._weapon_tics`). At 1 the text is the
    P5 one to the byte (no loop label, no counter read)."""
    if tics is None:
        from doomfj.world import WEAPON_TICS as tics
    assert 1 <= tics < 16, tics                                      # wp_pass is one nibble
    looped = tics > 1
    after = "wp_ploop" if looped else "wp_bar"                       # where one P_MovePsprites pass ends
    assert shoot or not noise, "the noise is the hit mode's: it comes with the shot"
    idx = {s: i for i, s in enumerate(states)}
    flash_frame = {s: (0 if s == gd.S_NULL or gd.STATES[s].tics == 0 else 1 + flash_frames().index(psprite_lump(s)))
                   for s in flash_states()}
    info = gd.WEAPONINFO
    wen = lambda s: "wen%d" % idx[s]                                   # noqa: E731
    fen = lambda s: "fen%d" % idx[s]                                   # noqa: E731
    out = ["// M7 P4.1 (doomfj.weaponcode): the weapon keys, P_MovePsprites, the bar's ammo + arms"]
    # -- 1. P_PlayerThink's BT_CHANGE: the LOWEST held number key names the weapon; 1 is the chainsaw when owned
    #    (berserk would keep the fist up -- P6); a weapon not owned, or already up, changes nothing
    if hurt:                                                          # M7 P5: a dead player's tic skips the keys
        out += ["hex.if1 1, p_dead, wk_end"]                          # (MonsterPhase.weapon: psprites + p_dc only)
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
    # -- 2. P_MovePsprites, the weapon: tics down, and at 0 its next state's block (M7 P6+P7: `tics` passes from here)
    out += (["wp_ptic:"] if looped else [])
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
        out += _action(st.action, f"a{idx[s]}", wen, fen, flash_frame, shoot, noise, hurt)
        out += [f";{wen(st.next)}" if st.tics == 0 else ";wp_flash"]
    # -- 3. P_MovePsprites, the flash
    out += ["wp_flash:",
            f"hex.if0 2, fl_st, {after}",
            "hex.dec 1, fl_tics",
            "hex.if0 1, fl_tics, fl_next", f";{after}",
            "fl_next:"]
    fls = flash_states()
    out += _dispatch2("fld", "fl_st", {idx[s]: "flc%d" % idx[s] for s in fls if s != gd.S_NULL})
    for s in fls:
        if s != gd.S_NULL:
            out += [f"flc{idx[s]}:", f"stl.fcall {fen(gd.STATES[s].next)}, fl_ret", f";{after}"]
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
    if shoot:                                   # the shot's leaves: out of line, after the flash's last fret
        out += shot_leaves()
    # a state cell holding no state of its psprite: the program's halt (never reached by a fall-through)
    out += ["wp_bad:", ";bad"]
    if looped:                                  # M7 P6+P7: one pass done -- another, or the counter back to 0 and on
        out += ["wp_ploop:", "hex.inc 1, wp_pass",
                f"hex.if_flags wp_pass, 1<<{tics}, wp_ptic, wp_pdone",
                "wp_pdone:", "hex.zero 1, wp_pass"]
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


def _fire_weapon(p: str, wen, noise: bool = False) -> List[str]:
    """P_FireWeapon: the ammo check, then the ready weapon's attack state (a tail jump). `noise` (P4.2b): the shot's
    P_NoiseAlert once the ammo check passed -- the model alerts after the attack state is set, but nothing that state
    runs reads `snd_alert` (only A_Look does, in the monsters' phase), so the order is free"""
    info = gd.WEAPONINFO
    return (_check_ammo(p, wen, f"{p}fok") + [f"{p}fok:"]
            + (["stl.fcall nz_leaf, nz_ret"] if noise else [])
            + _by_ready(f"{p}fa", {w: wen(info[w].atkstate) for w in WEAPONS}))


def _hp_le0(p: str, yes: str) -> List[str]:
    """M7 P5: jump to `yes` when the 3-nibble signed p_hp <= 0 (doomfj.hurtcode's cell), else fall through"""
    return [f"hex.sign 3, p_hp, {yes}, {p}hz", f"{p}hz:", f"hex.if0 3, p_hp, {yes}"]


def _action(action, p: str, wen, fen, flash_frame, shoot: bool = False, noise: bool = False,
            hurt: bool = False) -> List[str]:
    """one state's action, inline; it ends by falling through (no psprite set) or by a tail jump. `shoot`: the fire
    actions resolve their shots (`_shot_*`) instead of only advancing the stream. `hurt` (M7 P5): the health and
    death reads (weapon_lines)."""
    info = gd.WEAPONINFO
    if action in (None, "A_Light0", "A_Light1", "A_Light2"):
        return []                                                        # extralight: dropped (plan section 2, C)
    if action == "A_WeaponReady":
        # a pending weapon -- or (hurt, M7 P5) p_health <= 0 -- lowers; the fire key; else attackdown off and the
        # weapon at the top
        return ([f"hex.if_flags wp_pend, 1<<{NOCHANGE}, {p}pd, {p}np", f"{p}pd:"]
                + _by_ready(f"{p}dn", {w: wen(info[w].downstate) for w in WEAPONS})
                + [f"{p}np:"] + (_hp_le0(p, f"{p}pd") if hurt else [])
                + [f"hex.if_flags pkeys + dw, {KEY_FIRE_MASK:#06x}, {p}nf, {p}f",
                   # "the missile launcher and bfg do not auto fire": E1M1 has neither, so a held key always fires
                   f"{p}f:", "hex.set 1, wp_ad, 1"]
                + _fire_weapon(p, wen, noise)
                + [f"{p}nf:", "hex.zero 1, wp_ad", f"hex.set 2, wp_sy, {TOP}"])
    if action == "A_Lower":
        # (hurt, M7 P5) the dead player keeps it down; p_health <= 0 without death would drop it to S_NULL, which
        # no state reaches (doomfj.hurtcode: p_hp <= 0 <=> p_dead) and is not emitted
        return ([f"hex.add_constant 2, wp_sy, {LOWER}",
                 f"hex.cmp 2, wp_sy, wp_bottom_c, {p}lo, {p}bt, {p}bt", f"{p}bt:"]
                + ([f"hex.if1 1, p_dead, {p}dd"] if hurt else [])
                + ["hex.mov 1, wp_rdy, wp_pend",
                 # _bring_up_weapon: (a pending of NOCHANGE raises the ready weapon again -- unreachable here,
                 # A_Lower runs only after a pending was set, and kept exact anyway)
                 f"hex.if_flags wp_pend, 1<<{NOCHANGE}, {p}bu, {p}bk", f"{p}bk:", "hex.mov 1, wp_pend, wp_rdy",
                 f"{p}bu:", f"hex.set 1, wp_pend, {NOCHANGE}", f"hex.set 2, wp_sy, {BOTTOM}"]
                + _by_ready(f"{p}up", {w: wen(info[w].upstate) for w in WEAPONS})
                + ([f"{p}dd:", f"hex.set 2, wp_sy, {BOTTOM}"] if hurt else [])
                + [f"{p}lo:"])
    if action == "A_Raise":
        return ([f"hex.sub_constant 2, wp_sy, {RAISE}",
                 f"hex.cmp 2, wp_sy, wp_top_c, {p}tp, {p}tp, {p}hi", f"{p}tp:",
                 f"hex.set 2, wp_sy, {TOP}"]
                + _by_ready(f"{p}rd", {w: wen(info[w].readystate) for w in WEAPONS})
                + [f"{p}hi:"])
    if action == "A_ReFire":
        # fire held and no pending (and, hurt -- M7 P5, p_health > 0): refire++ (saturating) and fire; else refire 0,
        # check ammo
        return ([f"hex.if_flags pkeys + dw, {KEY_FIRE_MASK:#06x}, {p}no, {p}fh",
                 f"{p}fh:", f"hex.if_flags wp_pend, 1<<{NOCHANGE}, {p}no, {p}go",
                 f"{p}go:"] + (_hp_le0(p, f"{p}no") if hurt else [])
                + [f"hex.if_flags wp_rf + dw, 1<<15, {p}inc, {p}sat", f"{p}sat:",
                 f"hex.if_flags wp_rf, 1<<15, {p}inc, {p}fire",
                 f"{p}inc:", "hex.inc 2, wp_rf",
                 f"{p}fire:"]
                + _fire_weapon(p, wen, noise)
                + [f"{p}no:", "hex.zero 2, wp_rf"]
                + _check_ammo(p + "r", wen, f"{p}ok") + [f"{p}ok:"])
    if action in ("A_FirePistol", "A_FireShotgun"):
        pistol = action == "A_FirePistol"
        w = gd.WP_PISTOL if pistol else gd.WP_SHOTGUN
        out = [f"hex.sub_constant 3, {AMMO_CELL[info[w].ammo]}, 1",
               f"stl.fcall {fen(info[w].flashstate)}, fl_ret"]
        if shoot:
            return out + (_shot_pistol(p) if pistol else _shot_shotgun(p))
        if pistol:                                                       # accurate = no refire: 1 draw, else 3
            out += [f"hex.if0 2, wp_rf, {p}acc", f"hex.add_constant 2, rng_pl, {DRAWS['gunshot']}", f";{p}drw",
                    f"{p}acc:", f"hex.add_constant 2, rng_pl, {DRAWS['pistol_acc']}", f"{p}drw:"]
        else:
            out += [f"hex.add_constant 2, rng_pl, {(7 * DRAWS['gunshot']) & 0xFF}"]
        return out
    if action == "A_Punch":
        return _shot_melee(p, "punch") if shoot else [f"hex.add_constant 2, rng_pl, {DRAWS['punch']}"]
    if action == "A_Saw":
        return _shot_melee(p, "saw") if shoot else [f"hex.add_constant 2, rng_pl, {DRAWS['saw']}"]
    raise NotImplementedError("%s on an E1M1 psprite" % action)


def weapon_const_decls() -> List[str]:
    return [f"wp_bottom_c: hex.vec 2, {BOTTOM}", f"wp_top_c: hex.vec 2, {TOP}"]


# ---- M7 P4.2a: the shot (the module docstring, THE SHOT) ---------------------------------------------------------
AIM_N = 17                                      # aim_sid's cells: the window's columns aim_lo .. aim_hi
SHOT_PELLETS = 7                                # A_FireShotgun: 7 x P_GunShot (combat._psp_action)
SHOT_ROW_NIBBLES = 5                            # wpo's row: melee damage (0-1), gun damage (2), column index (3-4)
DM_CELLS = (("dm_id", 2), ("dm_dmg", 2), ("dm_melee", 1), ("dm_reach", 2))   # the damage machinery's arguments


def shot_row(melee: int, gun: int, col: int) -> int:
    """one `wpo` row: the melee damage, the gun damage, the column's index in the aim window"""
    assert 0 <= melee < 256 and 0 <= gun < 16 and 0 <= col < AIM_N, (melee, gun, col)
    return melee | gun << 8 | col << 12


def shot_fields(row: int):
    """`shot_row`'s inverse: (melee damage, gun damage, column index)"""
    return row & 0xFF, row >> 8 & 15, row >> 12


@lru_cache(maxsize=None)
def _default_sites():
    from doomfj import combat as C
    from doomfj.reference_model import ReferenceModel
    rm = ReferenceModel()
    return rm, C.Sites(rm)


def shot_window(rm=None, sites=None):
    """(aim_lo, aim_centre, aim_hi): the window's columns, from the model's own definitions (`combat.aim_window`,
    `CombatMixin._combat_init`'s centre). The model's default ReferenceModel unless `rm` is given."""
    from doomfj import combat as C
    if rm is None:
        rm, sites = _default_sites()
    sites = sites or C.Sites(rm)
    lo, hi = C.aim_window(rm, sites)
    centre = rm.angle_to_x(0)
    assert hi - lo + 1 == AIM_N and lo < centre < hi, (lo, centre, hi)
    return lo, centre, hi


def shot_values(rm=None, sites=None, fold=None) -> List[int]:
    """`wpo`: the shot's rows by the stream's state after the shot's first draw (D10, `combat.outcome_table_k` with
    k = 3). `fold` replaces the composition (the tests' negative control)."""
    from doomfj import combat as C
    if rm is None:
        rm, sites = _default_sites()
    sites = sites or C.Sites(rm)
    lo, _c, _h = shot_window(rm, sites)
    f = fold or (lambda a, b, c: shot_row((a % 10 + 1) << 1, 5 * (a % 3 + 1), sites.col(b - c) - lo))
    return C.outcome_table_k(f, 3)


def verify_shot_table(values, rm=None, sites=None) -> List[str]:
    """[] when every field of `values` is `combat.Sites`' outcome at every index: the gun damage and column against
    `gunshot`, the melee damage and column against `punch` and `saw`, the gun damage against `pistol_acc` (one draw:
    its damage is the 3-draw row's first value). Else one line per failed check."""
    from doomfj import combat as C
    if rm is None:
        rm, sites = _default_sites()
    sites = sites or C.Sites(rm)
    lo, _c, _h = shot_window(rm, sites)
    bad = []
    for name, k in (("pistol_acc", 1), ("gunshot", 3), ("punch", 3), ("saw", 3)):
        if getattr(sites, name)[0] != k:
            bad.append("%s draws %d, the leaf draws %d" % (name, getattr(sites, name)[0], k))
    if len(values) != 256:
        return bad + ["%d rows, want 256" % len(values)]
    for n, row in enumerate(values):
        melee, gun, col = shot_fields(row)
        want = {"gunshot": (gun, lo + col), "punch": (melee, lo + col), "saw": (melee, lo + col), "pistol_acc": gun}
        for name, w in want.items():
            if getattr(sites, name)[1][n] != w:
                bad.append("index %d: %s is %r, the row says %r" % (n, name, getattr(sites, name)[1][n], w))
    return bad


def shot_table_fj(rm=None) -> str:
    from doomfj.lut_generator import generate_dispatch_table_fj
    return generate_dispatch_table_fj("wpo", shot_values(rm), index_nibbles=2, result_nibbles=SHOT_ROW_NIBBLES)


def shot_decls() -> List[str]:
    """the shot's cells: the row, the leaves' fcall register, and the damage machinery's four arguments"""
    return [f"sh_row: hex.vec {SHOT_ROW_NIBBLES}", "sh_ret: hex.vec w/4"] + [f"{c}: hex.vec {n}" for c, n in DM_CELLS]


def _col_tree(cell: str) -> List[str]:
    """jump to `shc_c<v>` for the 1-nibble value v of `cell`: a 4-level if_flags tree, one bit a level"""
    out = []
    for b in (3, 2, 1, 0):
        mask = sum(1 << x for x in range(16) if x >> b & 1)
        for v in range(0, 16, 1 << (b + 1)):
            c0, c1 = ((f"shc_c{v}", f"shc_c{v | 1}") if b == 0 else (f"shc_{b - 1}_{v}", f"shc_{b - 1}_{v | 1 << b}"))
            out += [f"shc_{b}_{v}:", f"hex.if_flags {cell}, {mask:#06x}, {c0}, {c1}"]
    return out


def shot_leaves() -> List[str]:
    """the shot's fcall'd leaves (`sh_ret`). `sh_rd3`: a 3-draw shot -- the row at the post-increment state, the
    stream +3 in all -- then `sh_col`: dm_id = aim_sid at the row's column. `sh_gun`: a bullet's hand-off -- when
    dm_id names a target, the gun damage, not melee, and `dm_go`."""
    out = ["// M7 P4.2a: the shot's leaves",
           "sh_rd3:", "hex.inc 2, rng_pl", "wpo.lookup sh_row, rng_pl", "hex.add_constant 2, rng_pl, 2",
           "sh_col:", "hex.if_flags sh_row + 4*dw, 1<<1, shc_3_0, shc_c16"]
    out += _col_tree("sh_row + 3*dw")
    for c in range(AIM_N):
        out += [f"shc_c{c}:", f"hex.mov 2, dm_id, aim_sid + {2 * c}*dw", ";shc_end"]
    out += ["shc_end:", "stl.fret sh_ret",
            "sh_gun:", "hex.if0 2, dm_id, shg_end",
            "hex.zero 1, dm_dmg + dw", "hex.mov 1, dm_dmg, sh_row + 2*dw", "hex.zero 1, dm_melee",
            "stl.fcall dm_go, dm_ret",
            "shg_end:", "stl.fret sh_ret"]
    return out


def _shot_pistol(p: str) -> List[str]:
    """A_FirePistol's P_GunShot: accurate (refire 0) -- one draw, the gun damage, the window's centre -- else a
    3-draw bullet"""
    lo, centre, _hi = shot_window()
    return [f"hex.if0 2, wp_rf, {p}acc",
            "stl.fcall sh_rd3, sh_ret", "stl.fcall sh_gun, sh_ret", f";{p}drw",
            f"{p}acc:", "hex.inc 2, rng_pl", "wpo.lookup sh_row, rng_pl",
            f"hex.mov 2, dm_id, aim_sid + {2 * (centre - lo)}*dw",
            "stl.fcall sh_gun, sh_ret",
            f"{p}drw:"]


def _shot_shotgun(p: str) -> List[str]:
    """A_FireShotgun: SHOT_PELLETS 3-draw bullets, in order"""
    out = []
    for k in range(SHOT_PELLETS):
        out += [f"{p}pel{k}:", "stl.fcall sh_rd3, sh_ret", "stl.fcall sh_gun, sh_ret"]
    return out


def _shot_melee(p: str, site: str) -> List[str]:
    """A_Punch / A_Saw: a 3-draw shot; when the window names a target, the melee damage and the weapon's reach"""
    from doomfj.combat import PUNCH_REACH, SAW_REACH
    reach = {"punch": PUNCH_REACH, "saw": SAW_REACH}[site]
    return ["stl.fcall sh_rd3, sh_ret", f"hex.if0 2, dm_id, {p}sx",
            "hex.mov 2, dm_dmg, sh_row", "hex.set 1, dm_melee, 1", f"hex.set 2, dm_reach, {reach}",
            "stl.fcall dm_go, dm_ret",
            f"{p}sx:"]


# the weapon's PERSISTENT cells (build.WEAPON_PERSIST): the M1 reset must leave them alone -- a weapon restored to the
# level start every frame would never fire. `wp_bcd` (written before it is read) and `fl_ret` (the fcall register) are
# ordinary scratch.
PERSIST = ("wp_rdy", "wp_pend", "wp_st", "wp_tics", "wp_sy", "fl_st", "fl_tics", "wp_rf", "wp_ad", "am_clip",
           "am_shell", "wp_own", "rng_pl", "wp_frm", "fl_frm")


def level_start(map_wad, mapname: str) -> dict:
    """the model's level start for the player's weapon (it does not depend on the skill): the fields
    `weapon_decls` and `restart_lines` bake"""
    from doomfj.world import World
    w = World(map_wad, mapname, gd.SK_HARD, monsters="idle", player="fire")
    ws = w.ws
    return {f: getattr(ws, f) for f in ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy",
                                        "p_flash_state", "p_flash_tics", "p_refire", "p_attackdown", "rng_player")}         | {"ammo": list(ws.p_ammo), "owned": list(ws.p_owned)}


def restart_lines(start: dict, states: List[str], frames: List[str]) -> List[str]:
    """NEW GAME: every persistent weapon cell back to its level-start value (the decls' own values)"""
    out = []
    for decl in weapon_decls(start, states, frames):
        label, _, rest = decl.partition(": hex.vec ")
        if label in PERSIST:
            n, _, v = rest.partition(", ")
            out.append(f"hex.set {n}, {label}, {v or 0}")
    assert len(out) == len(PERSIST), (out, PERSIST)
    return out


def weapon_parts(map_wad, mapname: str, shoot: bool = False, noise: bool = False, hurt: bool = False,
                 tics: Optional[int] = None) -> dict:
    """everything the game tier's emitter splices in for the weapon: `decls` (the cells, the two constants, the ammo
    digit table), `tic` (the frame's weapon lines), `restart` (NEW GAME's values). `shoot` (P4.2a) adds the shot's
    cells to `decls`, the `wpo` table to `tables` and its leaves to `tic`; the program must then also hold `aim_sid`
    (the aim window) and `dm_go` / `dm_ret` (the damage machinery). `noise` (P4.2b, the "hit" mode) calls
    `nz_leaf` at every fire point: the program must then hold the noise's leaf and cells
    (monstercode.p31_parts at a player mode in noisecode.NOISE_PLAYER_MODES). `hurt` (M7 P5, a player mode in
    hurtcode.HURT_PLAYER_MODES) reads the health and death cells: the program must then hold hurtcode's decls.
    `tics` (M7 P6+P7): P_MovePsprites per frame, default `world.WEAPON_TICS` (weapon_lines)."""
    from doomfj.lut_generator import generate_dispatch_table_fj
    start = level_start(map_wad, mapname)
    states, frames = weapon_states(), overlay_frames()
    tables = [generate_dispatch_table_fj("ammobcd", ammo_digit_values(), index_nibbles=3, result_nibbles=3)]
    return {"decls": weapon_decls(start, states, frames) + weapon_const_decls() + (shot_decls() if shoot else []),
            "tables": tables + ([shot_table_fj()] if shoot else []),
            "tic": weapon_lines(states, frames, shoot, noise, hurt, tics),
            "restart": restart_lines(start, states, frames),
            "start": start}
