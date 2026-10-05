"""M7 P7 -- THE RESTART, run in fj against the model (docs/gp-p67-interface.md 4.4: `test_restart_coverage`'s values
and `test_restart_fj`).

The program under test is the GAME TIER'S OWN restart block for E1M1 -- `wall_renderer.compose_restart` over the
parts the emitter passes it (the doors, the lifts, the runtime things and their lists, every skill's presence, the
monsters' cells (monstercode.p31_parts at the shipped model modes), the bar, the weapon, the aim window, the hurt
cells, the pools, P7's cells) -- placed by `restartcode.routine_lines` and entered by the two call sites the game has:
`restartcode.tic_lines` (the restart on use after death, `g_rs` set) and `restartcode.new_game_lines` (NEW GAME at
`menu_sel`). A harness declares EVERY cell the game tier persists -- `build.persist_labels`, derived, never listed
here, at the widths the standalone restore set carries (scratchpad/m5_setfile.standalone_globals) plus the runtime
things' arrays -- each filled DIRTY, runs one entry for skill k, and prints every nibble of every such cell.

THE CHECKS, for each skill and each entry:
  * COVERAGE (no model needed): the program is assembled twice, from two dirty images that differ in EVERY nibble.
    A cell the restart writes ends the same in both; one it misses still shows its dirt. Every persisted cell except
    KEPT ones (the model's RESTART_KEEP: the skill, the menu and the held keys) and the DEVICE SHADOWS
    (restartcode.DEVICE_SHADOWS: pal_cur, hud_s, hud_full) must be written over its WHOLE extent -- plus the two
    cells that persist by not being in the restore set, thnext and thvis.
  * KEEP: every kept cell and every device shadow ends exactly as dirty as it started (`g_skill` / `menu_sel` as the
    entry set them).
  * VALUES: every cell the model maps -- the view, the doors, the lifts, the exit's, every monster cell
    (MonsterPhase.state), the weapon's (weapon_state), the hurt cells and the pools, P7's -- equals the model's state
    after `World._restart` from a game played to the player's DEATH and a press of use (the model's own path:
    `_death_think` sets `g_restart`, the next tic's start runs the block).
  * the restart on use does NOTHING when `g_rs` is 0.

THE CONTROLS (R9), each assembled through the same harness, each must be caught: a monster cell's line dropped from
every skill's block (values), the bar's line dropped (coverage: no model maps hud_v), a line restoring `pal_cur` (the
P5 restart did exactly this: a death restart would have zeroed it while the device showed red), a line writing
`g_skill`, `g_rs` left set, and the death restart dispatching on `menu_sel` instead of `g_skill`.
"""
import sys
import zlib
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj import restartcode as RC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.selfreset import decl_words

ROOT = Path(__file__).resolve().parents[2]
SRC = [ROOT / "src" / "fj" / "m1_reset.fj"]
M32 = 0xFFFFFFFF
# the model's RESTART_KEEP as the fj's cells (combat.RESTART_KEEP: the skill, the mode, the held keys) + the menu's
# own two (the menu state machine sets them around NEW GAME; the model's menu is outside the World)
KEEP = ("g_skill", "mode", "menu_scr", "menu_sel", "kb_f", "kb_b", "kb_l", "kb_r", "kb_u", "kb_sl", "kb_sr",
        "kb_fi", "kb_w1", "kb_w2", "kb_w3", "kb_w4")
# the persisted cells nothing reads unless a cell the restart DOES write says so: `aim_tz` is read only behind a
# non-zero `aim_sid` the same render wrote (build.AIM_PERSIST) -- free either way
FREE = ("aim_tz",)
# the cells that persist by NOT being in the restore set (test_restore_set_shipped.PERSIST_BY_ABSENCE): world state
# all the same, so the restart owes them their level start
BY_ABSENCE = ("thnext", "thvis")
BYTE_ARRAYS = ("sshead", "thnext")
PATH_DEATH, PATH_NEW_GAME, PATH_IDLE = 0, 1, 2


# ---- the game tier's restart, composed as the emitter composes it ---------------------------------------------------
def _parts():
    from doomfj import hud, hudcode
    from doomfj import monstercode as MC
    from doomfj import wall_renderer as WR
    from doomfj.doors import door_states, walkover_triggers
    from doomfj.hurtcode import hurt_parts
    from doomfj.mapcompiler import bake_bsp
    from doomfj.movers import lift_states
    from doomfj.reference_model import MONSTER_TYPES, VANISHABLE_TYPES, ReferenceModel, spawn_state
    from doomfj.things import (baked_thing_mask, drawable_things, skill_level_start, thing_pos_value,
                               vanishable_slots)
    from doomfj.wad import WadFile
    from doomfj.weaponcode import weapon_parts
    from doomfj.world import player_resolves
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    rm, cache = ReferenceModel(Config()), {}
    cmap = bake_bsp(mw, "E1M1")
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    things = mw.things("E1M1")
    drawable, draw_idx = drawable_things(rm, things, art, cache)
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    keep = sorted(i for i, b in zip(draw_idx, baked) if not b)
    vis_slots = vanishable_slots(drawable, baked, VANISHABLE_TYPES)
    rt = [things[w] for w in keep]
    binds = [rm.point_in_subsector(cmap, t.x, t.y) for t in rt]
    rt_draw = [draw_idx.index(w) for w in keep]
    nss = len(cmap.subsectors)
    patches = WR.anim_patches(art, WR.anim_frames(mw, "E1M1"))
    anim = {k: (0x100 + 64 * i, rm.art_of_lump(art, lump, cache)[2], mir)
            for i, (k, (lump, mir)) in enumerate(sorted(patches.items()))}
    p31 = MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=WR.BOOT_SKILL, skills=WR.SKILLS,
                       cache=cache, mode=WR.MONSTER_MODE, player=WR.PLAYER_MODE)
    w5 = p31["world"]
    w5.reset(WR.BOOT_SKILL)
    hrt = hurt_parts(w5, sprite_wad=art, boot_wad=mw)
    wpn = weapon_parts(mw, "E1M1", shoot=player_resolves(WR.PLAYER_MODE), hurt=True)
    # M7 P6: the barrels and drops (package C) and the player's loot (package B) -- through the emitter's own
    # composition, p6_restart_parts; the runtime pickups' thvis slots follow the baked vanishable ones
    from doomfj import lootcode
    loot_slots = (lootcode.pickup_slots(w5, rm, mw, "E1M1", art) if lootcode.loot_on(WR.PLAYER_MODE) else None)
    p6_common, p6_skills = WR.p6_restart_parts(w5, p31.get("barrel"), loot_slots)
    nmobile = p31["nmob"] + p31.get("ndrop", 0)
    nd = len(door_states(secs, lds, sds, WR.DOOR_QUANT))
    nwalk = len(walkover_triggers(secs, lds, sds, mw.vertexes("E1M1")))
    nlift = len(lift_states(secs, lds, sds, WR.DOOR_QUANT))
    restart = WR.compose_restart(
        spawn_state(mw, "E1M1"), nd, binds, [thing_pos_value(t) for t in rt], nss,
        [skill_level_start(drawable, rt_draw, binds, nss, vis_slots, sk) for sk in WR.SKILLS],
        nwalk=nwalk, nlift=nlift, monsters=p31["restart"],
        hud_restart=hudcode.hud_restart_lines(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))),
        wpn_restart=wpn["restart"], aim=True, hrt_restart=hrt["restart"], proj_restart=p31["proj"]["restart"],
        nmobile=nmobile, p6_common=p6_common, p6_skills=p6_skills)
    return dict(mw=mw, restart=restart, nt=len(rt), nmob=nmobile, nss=nss,
                nvis=len(vis_slots) + (loot_slots["nextra"] if loot_slots else 0), nd=nd, nwalk=nwalk, nlift=nlift)


def _cells(P):
    """{label: (kind, units)} for every cell the harness declares and prints: the standalone set's globals at its
    widths (m5_setfile.standalone_globals -- the list the re-key adds), the runtime things' rows and lists and the
    vanishable flags. kind "hex" (units = nibbles) or "byte" (units = bytes)."""
    sys.path.insert(0, str(ROOT / "scratchpad"))
    import m5_setfile
    out = {}
    for d in m5_setfile.standalone_globals(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"):
        name, words = decl_words(d)
        out.setdefault(name, ("hex", words // 2, d))
    rows = P["nt"] + P["nmob"]
    # ... and the hosted program's cells the game tier persists: the view (16.16, BAM), the things' rows and lists
    out.update({"viewx": ("hex", 8, None), "viewy": ("hex", 8, None), "viewangle": ("hex", 8, None)})
    out.update({"thpos_rt": ("hex", 16 * rows, None), "thss_rt": ("hex", 16 * rows, None),
                "thvis": ("hex", 2 * P["nvis"], None), "sshead": ("byte", P["nss"], None),
                "thnext": ("byte", rows, None)})
    # only the cells the checks classify are dirtied and printed; the rest is scratch at its own pristine value
    # (`rs_ret` above all: an fcall register the fret leaves ZERO -- dirty, every return would land elsewhere)
    written, kept = _classes(out)
    checked = set(written) | set(kept) | set(FREE)
    return {n: v for n, v in out.items() if n in checked}, [v[2] for n, v in out.items() if n not in checked]


def _dirt(label, i, pattern, bits):
    """the dirty value of unit i of `label` in `pattern` (0/1): never the same in the two patterns"""
    v = (zlib.crc32(("%s:%d" % (label, i)).encode()) % ((1 << bits) - 1)) + 1
    return v ^ ((1 << bits) - 1) if pattern else v


def _program(P, cells, pattern, common_extra=(), drop=(), tic=None):
    cells, scratch = cells
    from doomfj.wall_renderer import SKILLS
    common, skills = P["restart"]
    if drop or common_extra:
        common = [ln for ln in common[:-1] if not any(d in ln for d in drop)] + list(common_extra) + [common[-1]]
        skills = [[ln for ln in s if not any(d in ln for d in drop)] for s in skills]
    tic = RC.tic_lines(len(SKILLS)) if tic is None else tic
    decls = list(scratch)
    for label, (kind, n, _d) in cells.items():
        if kind == "hex":
            v = sum(_dirt(label, i, pattern, 4) << (4 * i) for i in range(n))
            decls.append(f"{label}: hex.vec {n}, {v}")
        else:
            decls += [f"{label}:"] + [f";{_dirt(label, i, pattern, 8)} * dw" for i in range(n)]
    dump = []
    for label, (kind, n, _d) in cells.items():
        if kind == "hex":
            dump += [f"hex.print_as_digit 1, {label} + {i}*dw, 0" for i in range(n)]
        else:
            for i in range(n):
                dump += [f"hex.set w/4, tm_base, {label}", f"hex.set w/4, tm_idx, {i}",
                         "hex.ptr_index tm_p, tm_base, tm_idx", "hex.read_byte tm_v, tm_p",
                         "hex.print_as_digit 2, tm_v, 0"]
        dump.append("stl.output_char 32")
    body = [
        "stl.startup_and_init_all",
        "hex.input 1, tm_in",                          # nibble 0 the skill index, nibble 1 the entry
        "hex.if0 1, tm_in + dw, tm_death",
        "hex.if_flags tm_in + dw, 1<<1, tm_idle, tm_new",
        "tm_death:", "hex.mov 1, g_skill, tm_in", "hex.set 1, g_rs, 1", ";tm_tic",
        "tm_idle:", "hex.mov 1, g_skill, tm_in", "hex.zero 1, g_rs",
        "tm_tic:", *tic, ";tm_dump",
        "tm_new:", "hex.mov 1, menu_sel, tm_in", *RC.new_game_lines(len(SKILLS)),
        "tm_dump:", *dump, "stl.output 10", "stl.loop",
        *RC.routine_lines((common, skills)),
        "tm_in: hex.vec 2", "tm_base: hex.vec w/4", "tm_idx: hex.vec w/4", "tm_p: hex.vec w/4", "tm_v: hex.vec 2",
        *decls]
    return "\n".join(body) + "\n"


def _assemble(tmp, name, text):
    src = tmp / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()], out, memory_width=W,
                print_time=False)
    return out


def _run(fjm, cells, skill_index, path):
    cells = cells[0]
    io = FixedIO(bytes([skill_index | path << 4]))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    words = io.get_output(allow_incomplete_output=True).decode("ascii").split("\n")[0].split(" ")
    out = {}
    for (label, (kind, n, _d)), word in zip(cells.items(), words):
        if kind == "hex":
            assert len(word) == n, (label, len(word), n)
            out[label] = [int(c, 16) for c in word]                     # nibble i first
        else:
            assert len(word) == 2 * n, (label, len(word), n)
            out[label] = [int(word[2 * i:2 * i + 2], 16) for i in range(n)]
    assert len(out) == len(cells), "the dump printed %d cells of %d" % (len(out), len(cells))
    return out


# ---- the model's side ----------------------------------------------------------------------------------------------
def _model_after_death_restart(skill):
    """the model's World played (a fight from the player's start), killed, `use` pressed while dead, and then the
    restart block (`World._restart`, what the next tic's start runs) -- the state the fj restart must write"""
    from doomfj import wall_renderer as WR
    from doomfj.monsters import MonsterPhase
    from doomfj.world import TicEvents
    mp = MonsterPhase(None, "E1M1", skill, mode=WR.MONSTER_MODE, player="full")
    w = mp.world
    for t in range(60):
        w.tic({"fire": t % 20 < 12, "forward": 20 <= t < 40, "turn_left": 40 <= t < 50})
    ev = TicEvents(w.tic_count)
    w.damage_player(250, ("test", 0), ev)
    assert w.ws.p_dead and ev.deaths == 1
    ev = w.tic({"use": True})
    assert ev.restart_requests == 1 and w.ws.g_restart == 1
    assert w.ws.p_dead
    w._restart(TicEvents(w.tic_count))
    return mp


def _units(vals, n):
    """cell values (each `n // len(vals)` nibbles) -> nibbles, nibble 0 first"""
    vals = list(vals) if isinstance(vals, (list, tuple)) else [vals]
    per = n // len(vals)
    assert per * len(vals) == n, (vals, n)
    return [(v >> (4 * i)) & 0xF for v in vals for i in range(per)]


def _model_cells(mp, cells) -> dict:
    """{label: nibbles} for every cell the model maps (the gates' own units: MonsterPhase.state / weapon_state, the
    probe's door and mover cells, restartcode.p6_cell_values)"""
    from doomfj.doorcode import WAIT_NIBBLES
    w = mp.world
    ws = w.ws
    want = {"viewx": ws.px & M32, "viewy": ws.py & M32, "viewangle": ws.pangle & M32,
            "lvdone": ws.g_leveldone, "pusedn": ws.p_usedown, "pcard": ws.p_cards[gd.IT_BLUECARD],
            "dstate": list(ws.d_state), "ddir": list(ws.d_dir), "dsub": list(ws.d_sub),
            "dwait": [v for v in ws.d_wait], "dreq": [0] * len(ws.d_state), "wfired": list(ws.w_fired),
            "lstate": list(ws.l_state), "ldir": list(ws.l_dir), "lsub": list(ws.l_sub), "lwait": list(ws.l_wait),
            "lreq": list(ws.l_req), "fswitch": ws.f_switch}
    assert cells[0]["dwait"][1] == WAIT_NIBBLES * len(ws.d_wait)
    want.update(mp.state())
    want.update(mp.weapon_state())
    want.update({k: v for k, v in RC.p6_cell_values(w).items() if k in cells[0]})
    return {k: _units(v, cells[0][k][1]) for k, v in want.items() if k in cells[0]}


# ---- the fixtures --------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def P():
    return _parts()


@pytest.fixture(scope="module")
def cells(P):
    return _cells(P)


@pytest.fixture(scope="module")
def shipped(P, cells, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("restart")
    return [_assemble(tmp, "restart%d" % p, _program(P, cells, p)) for p in (0, 1)]


def _classes(cells):
    """(must be written, must be kept) -- from build.persist_labels, every label of it classified"""
    from doomfj.build import persist_labels
    from doomfj.wall_renderer import TIERS
    persist = persist_labels(standalone=True, doors=True, moving_things=TIERS["game"]["moving_things"])
    missing = [n for n in persist if n not in cells]
    assert not missing, "persisted cells the harness does not declare: %s" % missing
    kept = set(KEEP) | set(RC.DEVICE_SHADOWS)
    assert kept <= set(persist), sorted(kept - set(persist))
    written = [n for n in persist if n not in kept and n not in FREE] + list(BY_ABSENCE)
    return written, sorted(kept)


def _check(runs, cells, skill_index, path, want_model=None):
    """-> [problems] for one entry's runs: [pattern 0's] or [pattern 0's, pattern 1's] (coverage needs both)"""
    a = runs[0]
    cells = cells[0]
    written, kept = _classes(cells)
    bad = []
    for n in (written if len(runs) == 2 and path != PATH_IDLE else []):
        miss = [i for i, (x, y) in enumerate(zip(a[n], runs[1][n])) if x != y]
        if miss:
            bad.append("%s: %d of %d units not written (first %d)" % (n, len(miss), len(a[n]), miss[0]))
    for p, run in enumerate(runs):
        for n in kept + (written if path == PATH_IDLE else []):
            kind, units, _d = cells[n]
            dirty = [_dirt(n, i, p, 4 if kind == "hex" else 8) for i in range(units)]
            if n == "g_skill" or (n == "menu_sel" and path == PATH_NEW_GAME):
                dirty = [skill_index]
            if n == "g_rs" and path == PATH_IDLE:
                dirty = [0]
            if run[n] != dirty:
                bad.append("pattern %d: %s changed (%s -> %s)" % (p, n, dirty, run[n]))
    for n, nib in (want_model or {}).items():
        if a[n] != nib:
            k = next(i for i, (x, y) in enumerate(zip(a[n], nib)) if x != y)
            bad.append("%s: nibble %d is %x, the model's level start %x" % (n, k, a[n][k], nib[k]))
    return bad


SKILL_ENTRIES = [(k, path) for k in range(3) for path in (PATH_DEATH, PATH_NEW_GAME)]


@pytest.mark.parametrize("skill_index,path", SKILL_ENTRIES)
def test_the_restart_writes_every_persisted_cell_to_the_models_level_start(P, cells, shipped, skill_index, path):
    from doomfj.wall_renderer import SKILLS
    runs = [_run(f, cells, skill_index, path) for f in shipped]
    want = _model_cells(_model_after_death_restart(SKILLS[skill_index]), cells)
    assert len(want) >= 60, sorted(want)                          # the value half is not vacuous
    bad = _check(runs, cells, skill_index, path, want)
    assert not bad, "\n".join(bad[:20])


def test_the_restart_on_use_does_nothing_while_g_rs_is_0(P, cells, shipped):
    runs = [_run(f, cells, 1, PATH_IDLE) for f in shipped]
    bad = _check(runs, cells, 1, PATH_IDLE)
    assert not bad, "\n".join(bad[:20])


def test_the_harness_classifies_every_persisted_cell(P, cells):
    """vacuity: the written set holds every rung's cells, the kept set the device shadows and the inputs"""
    written, kept = _classes(cells[0])
    for name in ("viewx", "dstate", "lstate", "sshead", "thpos_rt", "mon_state", "mon_health", "snd_alert",
                 "hud_v", "wp_rdy", "aim_sid", "p_hp", "pj_act", "fx_act", "rng_fx", "lvtime", "g_rs", "mh_prev",
                 "bar_solid", "thnext", "thvis"):
        assert name in written, name
    for name in ("p_bc", "p_str", "p_bp", "am_misl", "am_cell", "mdrop", "dr_live", "bar_st", "rng_wd"):  # M7 P6
        assert name in written, name
    assert {"pal_cur", "hud_s", "hud_full", "g_skill", "mode", "kb_u"} <= set(kept)


# ---- R9 ------------------------------------------------------------------------------------------------------------
# each mutant runs ONE dirty pattern (the value and keep halves see it) unless only the coverage half can (`two`)
MUTANTS = {
    # a monster cell's line dropped from every skill's block: slot 0's health
    "mon_health dropped": dict(drop=("mon_health + 0*dw",)),
    # the bar's level start dropped: no model maps hud_v, so only the coverage half can see it
    "hud_v dropped": dict(drop=("hud_v",), two=True),
    # the P5 restart's own line: pal_cur restored while the device may show red
    "pal_cur restored": dict(common_extra=("    hex.zero 1, pal_cur",)),
    "g_skill written": dict(common_extra=("    hex.zero 1, g_skill",)),
    "g_rs left set": dict(drop=("g_rs",)),
    # M7 P6 (package B's cells, through p6_restart_parts): the bonus count's level start dropped (the value half:
    # p6_cell_values maps it), and the first RUNTIME pickup's thvis slot left as it was (coverage: thvis persists by
    # absence, slot nvis + 0 is the extra slot lootcode.extra_vis sets per skill)
    "p_bc dropped": dict(drop=("p_bc",)),
    "rt pickup thvis dropped": dict(drop=("thvis + 105*2*dw",), two=True),
    # the restart on use dispatching on the menu's highlight instead of the skill being played
    "dispatch on menu_sel": dict(tic=[ln.replace("g_skill", "menu_sel") if "if" in ln else ln
                                      for ln in RC.tic_lines(3)]),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_broken_restart_is_caught(P, cells, tmp_path, name):
    from doomfj.wall_renderer import SKILLS
    kw = dict(MUTANTS[name])
    two = kw.pop("two", False)
    if "tic" in kw:
        assert kw["tic"] != RC.tic_lines(3)
    fjms = [_assemble(tmp_path, "mut%d" % p, _program(P, cells, p, **kw)) for p in ((0, 1) if two else (0,))]
    caught = []
    for k, path in ((0, PATH_DEATH), (1, PATH_NEW_GAME)):
        runs = [_run(f, cells, k, path) for f in fjms]
        if _check(runs, cells, k, path, _model_cells(_model_after_death_restart(SKILLS[k]), cells)):
            caught.append((k, path))
    assert caught, "a restart with %r passed" % name
