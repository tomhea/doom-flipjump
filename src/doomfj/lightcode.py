"""M8 -- THE SECTOR LIGHT THINKERS in fj (the rules are doomfj.lights; the model is world.World._lights_phase).

THE CELLS (the schema's light fields by their labels; `decls` -- declared at the level start, PERSISTed across the M1
reset (`map_persist`, build._map_persist) and written back by NEW GAME / the restart (`level_start_lines`)):

    ltst    1 nibble a thinker     lt_state    the thinker's light STATE (lights.LightThinker.levels; 0 the stored
                                               light) -- the cell every per-state render block switches on
                                               (wall_renderer: the seg blocks, the leaf's sprite light base, a baked
                                               thing's light class)
    ltct    2 nibbles a thinker    lt_count    tics to its next change; a glow's direction (0 down, 1 up)
    rng_lt  2 nibbles              rng_light   the light stream (rng.STREAM_LIGHT), after the level start's rolls

THE PHASE (`phase_lines`: `lt_phase`, fcall'd from the world tic's loop after `fx_phase` -- world.World._monster_world's
order -- so twice a frame; it skips itself while `lvdone`, as every world phase does). One block a thinker, in sector
order (the order the stream is drawn in):

    glow    down: state K (the last) turns the direction, else state + 1;  up: state 1 turns it, else state - 1
            (T_Glow on the levels: a step that would reach a bound is undone -- `lights._glow_levels`)
    strobe  count - 1; at 0 the state toggles and the count is the new state's time (dark / STROBEBRIGHT)
    flash   count - 1; at 0 one roll, the state toggles, the count is `ltfmin` / `ltfmax`'s outcome at the roll
            ((P_Random & 7) + 1 going dark, (P_Random & 64) + 1 going bright: lights.flash_count_values)
    fire    count - 1; at 0 one roll, the count is 4 and the state is the outcome table of the state it left
            (lights.fire_state_values) -- a constant one (E1M2's sector 194: always its minlight) a plain set

A one-nibble state and a two-nibble count: lights.MAX_LEVELS, lights.COUNT_NIBBLES.
"""
from __future__ import annotations

from typing import List, Sequence

from doomfj import lights as L

PERSIST = ("ltst", "ltct", "rng_lt")
CN = L.COUNT_NIBBLES


def map_persist(map_wad, mapname: str) -> tuple:
    """the map-dependent persisted names (build._map_persist, the game tier's): the light cells on a map whose light
    specials animate -- the reset leaves them to NEW GAME / the restart -- nothing on E1M1 (its image unchanged)"""
    return PERSIST if L.map_thinkers(map_wad, mapname) else ()


def state_cell(k: int) -> str:
    """thinker k's state nibble -- the per-state render blocks' switch cell"""
    return f"ltst + {k}*dw"


def _count_cell(k: int) -> str:
    return f"ltct + {CN * k}*dw"


def _packed(vals: Sequence[int], nib: int) -> int:
    """`hex.vec`'s value for `vals`, `nib` nibbles each, cell 0 the lowest"""
    out = 0
    for k, v in enumerate(vals):
        assert 0 <= v < 16 ** nib, (v, nib)
        out |= v << (4 * nib * k)
    return out


def level_start_values(ths) -> tuple:
    """(ltst value, ltct value, rng_lt value) at the level start -- lights.level_start, packed"""
    states, counts, rng = L.level_start(ths)
    return _packed(states, 1), _packed(counts, CN), rng


def decls(ths) -> List[str]:
    """the three cells at the level start, and the phase's return"""
    assert ths, "no animated light: nothing to declare"
    st, ct, rng = level_start_values(ths)
    n = len(ths)
    return [f"ltst: hex.vec {n}, {st}", f"ltct: hex.vec {CN * n}, {ct}", f"rng_lt: hex.vec 2, {rng}",
            "lt_pret: hex.vec w/4"]


def level_start_lines(ths) -> List[str]:
    """NEW GAME / the restart: every thinker back to its level start (the same at every skill)"""
    st, ct, rng = level_start_values(ths)
    n = len(ths)
    return [f"    hex.set {n}, ltst, {st}", f"    hex.set {CN * n}, ltct, {ct}", f"    hex.set 2, rng_lt, {rng}"]


def _fire_table(k: int, s: int) -> str:
    return f"ltfr{k}_{s}"


def _fire_constant(th, s: int):
    """the one state every roll takes a fire from state `s` to, or None"""
    vals = set(L.fire_state_values(th, s))
    return vals.pop() if len(vals) == 1 else None


def tables(ths) -> List[str]:
    """the outcome tables the phase reads: a flash's two count tables (shared by every flash) and each fire's
    non-constant per-state tables -- dispatch tables, self-guarded data"""
    from doomfj.lut_generator import generate_dispatch_table_fj
    out = []
    if any(th.kind == "flash" for th in ths):
        out.append(generate_dispatch_table_fj("ltfmin", L.flash_count_values(L.FLASH_MINTIME), index_nibbles=2,
                                              result_nibbles=CN))
        out.append(generate_dispatch_table_fj("ltfmax", L.flash_count_values(L.FLASH_MAXTIME), index_nibbles=2,
                                              result_nibbles=CN))
    for k, th in enumerate(ths):
        if th.kind != "fire":
            continue
        for s in range(len(th.levels)):
            if _fire_constant(th, s) is None:
                out.append(generate_dispatch_table_fj(_fire_table(k, s), L.fire_state_values(th, s),
                                                      index_nibbles=2, result_nibbles=1))
    return out


def thinker_lines(k: int, th) -> List[str]:
    """one tic of thinker k (`th`): the block the phase runs, ending at `lt{k}_end`"""
    p, S, C = f"lt{k}", state_cell(k), _count_cell(k)
    if th.kind == "switch":                 # M8 C4: a light switch's sector never tics (the use press sets its state)
        return []
    if th.kind == "glow":
        last = len(th.levels) - 1
        assert last >= 1, th
        return [f"  // ---- light {k}: sector {th.sector} glow, {len(th.levels)} states ----",
                f"    hex.if0 1, {C}, {p}_dn",
                f"    hex.dec 1, {S}",                         # up: state - 1 ...
                f"    hex.if0 1, {S}, {p}_top",
                f"    ;{p}_end",
                f"  {p}_top:",                                 # ... but state 1 stays (maxlight is not shown again)
                f"    hex.inc 1, {S}",
                f"    hex.xor_by 1, {C}, 1",                   # and turns down
                f"    ;{p}_end",
                f"  {p}_dn:",
                f"    hex.xor_by 1, {S}, {last}",
                f"    hex.if0 1, {S}, {p}_bot",
                f"    hex.xor_by 1, {S}, {last}",
                f"    hex.inc 1, {S}",                         # down: state + 1 ...
                f"    ;{p}_end",
                f"  {p}_bot:",
                f"    hex.xor_by 1, {S}, {last}",              # ... but the last state stays (minlight is not shown)
                f"    hex.xor_by 1, {C}, 1",                   # and turns up
                f"  {p}_end:"]
    head = [f"  // ---- light {k}: sector {th.sector} {th.kind}, {len(th.levels)} states ----",
            f"    hex.dec {CN}, {C}",
            f"    hex.if0 {CN}, {C}, {p}_go",
            f"    ;{p}_end",
            f"  {p}_go:"]
    if th.kind == "strobe":
        assert len(th.levels) == 2, th
        return head + [f"    hex.xor_by 1, {S}, 1",                 # max <-> min
                       f"    hex.if0 1, {S}, {p}_br",
                       f"    hex.xor_by {CN}, {C}, {th.darktime}",  # now dark (the count is 0 here)
                       f"    ;{p}_end",
                       f"  {p}_br:",
                       f"    hex.xor_by {CN}, {C}, {L.STROBEBRIGHT}",
                       f"  {p}_end:"]
    if th.kind == "flash":
        assert len(th.levels) == 2, th
        return head + ["    hex.inc 2, rng_lt",
                       f"    hex.xor_by 1, {S}, 1",                 # max <-> min
                       f"    hex.if0 1, {S}, {p}_br",
                       f"    ltfmin.lookup {C}, rng_lt",            # now min: (P_Random & 7) + 1
                       f"    ;{p}_end",
                       f"  {p}_br:",
                       f"    ltfmax.lookup {C}, rng_lt",            # now max: (P_Random & 64) + 1
                       f"  {p}_end:"]
    assert th.kind == "fire", th
    n = len(th.levels)
    out = head + ["    hex.inc 2, rng_lt", f"    hex.xor_by {CN}, {C}, {L.FIRE_COUNT}"]
    consts = [_fire_constant(th, s) for s in range(n)]
    if all(c is not None for c in consts) and len(set(consts)) == 1:
        return out + [f"    hex.set 1, {S}, {consts[0]}", f"  {p}_end:"]
    labs = [f"{p}_s{s}" for s in range(n)]
    out.append(f"    sim.jump16 {S}, " + ", ".join(labs + [labs[-1]] * (16 - n)))
    for s in range(n):
        out += [f"  {labs[s]}:",
                (f"    hex.set 1, {S}, {consts[s]}" if consts[s] is not None
                 else f"    {_fire_table(k, s)}.lookup {S}, rng_lt"),
                f"    ;{p}_end"]
    return out + [f"  {p}_end:"]


def phase_lines(ths) -> List[str]:
    """`lt_phase` (fcall'd with `lt_pret`): one tic of every thinker in sector order, skipped while `lvdone` -- a leaf,
    placed where nothing falls in"""
    out = ["// == M8: the sector light thinkers, one tic (doomfj.lights.tic_all) ==========",
           "lt_phase:",
           "    hex.if1 1, lvdone, lt_out"]
    for k, th in enumerate(ths):
        out += thinker_lines(k, th)
    return out + ["  lt_out:", "    stl.fret lt_pret"]


def switch_use_lines(uses) -> List[str]:
    """M8 C4: a use PRESS (inside `ex_press`, with the lifts' and floors' use lines): each light-switch line's box
    holding the player sets its sectors' thinkers to the bright state (1) -- again and again for an SR line, a no-op
    once lit. `uses` = `lights.light_switch_uses`. Labels `lsw<j>_`"""
    from doomfj.doorcode import _box_test
    out = ["// == M8 C4: the light switches (lights.SWITCH_LIGHT_SPECIALS: EV_LightTurnOn) on a use press =="] if uses else []
    for j, (box, ks) in enumerate(uses):
        out += _box_test(0, box, f"lsw{j}_hit", f"lsw{j}_miss", tag=f"lsw{j}_b")
        out += [f"  lsw{j}_hit:", *[f"    hex.set 1, {state_cell(k)}, 1" for k in ks], f"  lsw{j}_miss:"]
    return out


TIC_CALL = "stl.fcall lt_phase, lt_pret"
