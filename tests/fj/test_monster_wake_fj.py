"""M7 P3.2a: the WAKE tic (monstercode.p32a_*) on the real flipjump engine against the model's own monster phase in
the wake mode with the seen rule (World(monsters="wake", sight_rule="seen")) -- every slot's state, tics, facing,
target, reaction, threshold and the cursor after every frame. The script moves the player next to sleeping monsters
(the REJECT-within-128 path), sets the seen flags from a pattern (a burst that wakes many at once, so the K = 6
slots defer), and runs long enough for A_Chase's counters and turn. R9: a mutated REJECT row and a mutated turn
table must each fail.

M7 P5 (`hurt`, doomfj.hurtcode): the same script, and the player DIES at frame DEATH (p_dead 1, health 0, poked on
both sides, with a threshold poked on every third slot): from then on A_Chase resets the threshold and sends the
monster back to its spawn state, and A_Look neither sees nor hears (p32a_slot's `hurt`). R9: the target never lost
(the chase's dead test gone), the threshold still counted down, and a look that still sees must each fail.

M8 C2 (docs/c2-slot-ids.md): every test runs on E1M1 AND on E1M6 (tests/fj/wide_maps.py) -- 294 monster slots (3 lost souls among them), so the
scheduler's cursor, mt_fdef and mt_n are THREE nibbles (world.slot_nibbles) and the cursor's dispatch has a third
level; on E1M6 the cursor STARTS at slot 250 (poked on both sides), so the tics run through 255 / 256 and wrap past
the last slot. R9 there: the third level dropped, and mt_n set in two nibbles (294 & 0xFF slots a tic)."""
import re
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj.collision import generate_point_location_fj, point_location_decls
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.world import TicEvents, slot_nibbles
from tests.fj.wide_maps import MAPS, map_world

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FRAMES = 48
DEATH = 24                       # M7 P5: the frame the player dies at (after the burst woke everyone)


WIDE_START = 250                 # M8 C2: the wide map's first cursor -- its tics cross the byte


def _world(mapname="E1M1"):
    w = map_world(mapname, monsters="wake", sight_rule="seen")
    if w.layout.nmon > 255:
        w.ws.sched_cursor = WIDE_START
    return w


WIDE_MUTS = {      # M8 C2: (the wide map's) the cursor's third level dropped; mt_n in two nibbles
    "third_level": lambda code, n: code.replace(
        [ln for ln in code.split("\n") if ln.startswith("    sim.jump16 sched_cursor + 2*dw,")][0], "    ;mt_g0"),
    "mt_n_two": lambda code, n: code.replace("    hex.set 3, mt_n, %d\n" % n, "    hex.set 2, mt_n, %d\n" % (n & 0xFF)),
}


def _script(w):
    """per frame: (player x16, y16, seen slots)"""
    rnd = random.Random(0x32A)
    n = w.layout.nmon
    act = [m for m in range(n) if w.ws.mon_active[m]]
    out = []
    for f in range(FRAMES):
        m = act[(f * 7) % len(act)]
        ox, oy = [(40, 20), (-60, 30), (90, -50), (-20, -110), (150, 10)][f % 5]
        x16, y16 = (w.ws.mon_x[m] + ox) << 16 | 0x4000, (w.ws.mon_y[m] + oy) << 16
        seen = set(rnd.sample(act, 3)) if f % 3 else set()
        if 10 <= f < 14:
            seen = set(act)                                     # a burst: everybody wakes, the slots defer
        out.append((x16 & 0xFFFFFFFF, y16 & 0xFFFFFFFF, seen))
    return out


def _thr_slots(w):
    return [m for m in range(w.layout.nmon) if w.ws.mon_active[m] and m % 3 == 0]


def _expected(script, hurt=False, mapname="E1M1") -> bytes:
    w = _world(mapname)
    n, ws = w.layout.nmon, w.ws
    sn = slot_nibbles(w.layout)
    thr = _thr_slots(w)
    lines = []
    for f, (x16, y16, seen) in enumerate(script):
        ws.px, ws.py = x16 - (1 << 32) if x16 >> 31 else x16, y16 - (1 << 32) if y16 >> 31 else y16
        for m in range(n):
            ws.mon_seen[m] = int(m in seen)
        if hurt and f == DEATH:
            ws.p_dead, ws.p_health = 1, 0
            for m in thr:
                ws.mon_threshold[m] = 7
        w._monsters_phase(TicEvents(0))
        lines.append("".join("%02x%x%x%x%x%02x" % (ws.mon_state[m], ws.mon_tics[m], ws.mon_facing[m],
                                                    ws.mon_target[m], ws.mon_reaction[m], ws.mon_threshold[m])
                             for m in range(n)) + "%0*x" % (sn, ws.sched_cursor))
    return ("\n".join(lines) + "\n").encode()


# M7 P5: (pattern, replacement) over the slot code, applied to EVERY slot
HURT_MUTS = {
    "nolose": (r"    hex\.if0 1, p_dead, (mw\d+_next)\n", r"    ;\1\n"),     # the target never lost
    "thrcount": (r"    hex\.if1 1, p_dead, mw\d+_thz\n", ""),                # the threshold still counts down
    "looksees": (r"    hex\.if1 1, p_dead, mw\d+_next\n", ""),               # A_Look still sees a dead player
}


def _parts(w, rj_mutate=False, turn_mutate=False, hurt=False):
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    secs = sorted({w._mon_sector(m) for m in range(n)})
    slots = []
    for m in range(n):
        info = w.mon_info[m]
        slots.append(dict(t=m, x=ws.mon_x[m], y=ws.mon_y[m], rj="rj%d" % w._mon_sector(m),
                          see_idx=gd.THING_STATE_INDEX[info.seestate],
                          see_tics=gd.STATES[info.seestate].tics,
                          **({"hurt": dict(sp=gd.THING_STATE_INDEX[info.spawnstate],
                                           spt=gd.STATES[info.spawnstate].tics)} if hurt else {})))
    tables = [generate_dispatch_table_fj("mstate", MC.state_table_values(MC.map_monster_types(mi.name for mi in w.mon_info)), index_nibbles=2, result_nibbles=6)]
    turn = MC.turn_table_values()
    if turn_mutate:
        turn = list(turn)
        for f in range(8):                                         # movedir EAST (every awake monster's in the
            turn[(0 << 4) | f] = f                                 # wake mode): no turn at all
    tables.append(generate_dispatch_table_fj("mturn", turn, index_nibbles=2, result_nibbles=1))
    for s in secs:
        vals = [int(w.reject.visible(s, p)) for p in range(w.reject.nsec)]
        if rj_mutate:
            vals = [1 - v for v in vals]
        tables.append(generate_dispatch_table_fj("rj%d" % s, vals, index_nibbles=w.sec_nibbles, result_nibbles=1))
    nleaf = len(w.cmap.subsectors)
    tables.append(generate_dispatch_table_fj("lfsec", list(w.leaf_sector), index_nibbles=max(1, ((nleaf - 1).bit_length() + 3) // 4),
                                             result_nibbles=w.sec_nibbles))
    tables.append(generate_point_location_fj(w.cmap))
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS}
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": ws.sched_cursor}, n, w.sec_nibbles)
             + MC.MT_DECLS + MC.p32a_scratch(slot_nibbles(w.layout)) + point_location_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "mt_tret: hex.vec w/4"]
             + (["p_dead: hex.vec 1, 0"] if hurt else []))
    code = ["mt_tic_leaf:"] + MC.p32a_tic_lines(schema, n, slots, exit_guard=False, nib=w.sec_nibbles) + ["    stl.fret mt_tret"]
    return decls, code + MC.p32a_leaves(), tables


def _run(tmp_path, name, hurt=False, hurt_mut=None, mapname="E1M1", wide_mut=None, **mut) -> bool:
    w = _world(mapname)
    n = w.layout.nmon
    sn = slot_nibbles(w.layout)
    script = _script(w)
    thr = _thr_slots(w)
    body = ["stl.startup_and_init_all"]
    for f, (x16, y16, seen) in enumerate(script):
        if hurt and f == DEATH:
            body += ["hex.set 1, p_dead, 1"] + ["hex.set 2, mon_threshold + %d*dw, 7" % (2 * m) for m in thr]
        body += ["hex.set 8, viewx, %d" % x16, "hex.set 8, viewy, %d" % y16,
                 "hex.set %d, thseen, %d" % (n, sum(1 << (4 * m) for m in seen)),
                 "stl.fcall mt_tic_leaf, mt_tret"]
        for m in range(n):
            body += ["hex.print_as_digit 2, mon_state + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_tics + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_facing + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_target + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_reaction + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_threshold + %d*dw, 0" % (2 * m)]
        body += ["hex.print_as_digit %d, sched_cursor, 0" % sn, "stl.output 10"]
    body.append("stl.loop")
    decls, code, tables = _parts(w, hurt=hurt, **mut)
    code = "\n".join(code) + "\n"
    if wide_mut:
        bad = WIDE_MUTS[wide_mut](code, n)
        assert bad != code, wide_mut
        code = bad
    if hurt_mut:
        pat, new = HURT_MUTS[hurt_mut]
        code, k = re.subn(pat, new, code)
        assert k == n, (hurt_mut, k, n)
    prog = "\n".join(body + decls + [code] + tables) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    from doomfj.config import Config
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", _expected(script, hurt, mapname), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


@pytest.mark.parametrize("mapname", MAPS)
def test_the_wake_tic_follows_the_model(tmp_path, mapname):
    assert _run(tmp_path, "mwake", mapname=mapname), "the fj wake tic parted from the model's wake mode"


def test_the_wide_cursor_crosses_the_byte():
    """M8 C2: on E1M6 the model's cursor takes values on both sides of 256 and wraps past the last slot -- the
    dispatch's third level and the wrap are exercised"""
    from tests.fj.wide_maps import ASSET, WIDE_MAP
    if not ASSET.exists():
        pytest.skip("needs assets/freedoom1.wad")
    w = _world(WIDE_MAP)
    n, ws = w.layout.nmon, w.ws
    cur = [ws.sched_cursor]
    for x16, y16, seen in _script(w):
        ws.px, ws.py = x16 - (1 << 32) if x16 >> 31 else x16, y16 - (1 << 32) if y16 >> 31 else y16
        for m in range(n):
            ws.mon_seen[m] = int(m in seen)
        w._monsters_phase(TicEvents(0))
        cur.append(ws.sched_cursor)
    assert min(cur) < 256 <= max(cur) and len(set(cur)) >= 5, cur


@pytest.mark.parametrize("mut", ["rj_mutate", "turn_mutate"])
@pytest.mark.parametrize("mapname", MAPS)
def test_control_a_mutated_table_is_caught(tmp_path, mut, mapname):
    assert not _run(tmp_path, "mwake_" + mut, mapname=mapname, **{mut: True}), "%s passed: the comparison is vacuous" % mut


@pytest.mark.parametrize("mut", sorted(WIDE_MUTS))
def test_control_a_narrow_scheduler_is_caught_on_the_wide_map(tmp_path, mut):
    """M8 C2's R9: the scheduler at two nibbles' text on E1M6 parts from the model"""
    from tests.fj.wide_maps import ASSET, WIDE_MAP
    if not ASSET.exists():
        pytest.skip("needs assets/freedoom1.wad")
    assert not _run(tmp_path, "mwake_w_" + mut, mapname=WIDE_MAP, wide_mut=mut), "%s passed: vacuous" % mut


def test_the_hurt_script_loses_its_targets():
    """the model after the death: awake monsters return to their spawn state, a poked threshold is reset, and
    nobody wakes again -- each control needs its path"""
    w = _world()
    n, ws = w.layout.nmon, w.ws
    script = _script(w)
    thr = _thr_slots(w)
    spawn = {m: gd.THING_STATE_INDEX[w.mon_info[m].spawnstate] for m in range(n)}
    look = {m: {spawn[m], gd.THING_STATE_INDEX[gd.STATES[w.mon_info[m].spawnstate].next]} for m in range(n)}
    lost, reset, awake_at_death = 0, 0, 0
    for f, (x16, y16, seen) in enumerate(script):
        ws.px, ws.py = x16 - (1 << 32) if x16 >> 31 else x16, y16 - (1 << 32) if y16 >> 31 else y16
        for m in range(n):
            ws.mon_seen[m] = int(m in seen)
        if f == DEATH:
            awake_at_death = sum(1 for m in range(n) if ws.mon_active[m] and ws.mon_state[m] not in look[m])
            ws.p_dead, ws.p_health = 1, 0
            for m in thr:
                ws.mon_threshold[m] = 7
        before = list(ws.mon_state)
        w._monsters_phase(TicEvents(0))
        if f >= DEATH:
            lost += sum(1 for m in range(n) if before[m] not in look[m] and ws.mon_state[m] == spawn[m])
            if f == DEATH:
                reset = sum(1 for m in thr if ws.mon_threshold[m] == 0)
            assert not any(before[m] in look[m] and ws.mon_state[m] not in look[m] for m in range(n)), (
                "a monster woke after the death")
    assert awake_at_death >= 10 and lost >= awake_at_death and reset >= 3, (awake_at_death, lost, reset)


def test_the_wake_tic_loses_the_dead_player(tmp_path):
    assert _run(tmp_path, "mwake_hurt", hurt=True), "the fj wake tic (hurt) parted from the model"


@pytest.mark.parametrize("mut", sorted(HURT_MUTS))
def test_control_a_broken_target_loss_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mwake_hurt_" + mut, hurt=True, hurt_mut=mut), "%s passed: vacuous" % mut
