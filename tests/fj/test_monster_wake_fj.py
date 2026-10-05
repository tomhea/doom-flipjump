"""M7 P3.2a: the WAKE tic (monstercode.p32a_*) on the real flipjump engine against the model's own monster phase in
the wake mode with the seen rule (World(monsters="wake", sight_rule="seen")) -- every slot's state, tics, facing,
target, reaction, threshold and the cursor after every frame. The script moves the player next to sleeping monsters
(the REJECT-within-128 path), sets the seen flags from a pattern (a burst that wakes many at once, so the K = 6
slots defer), and runs long enough for A_Chase's counters and turn. R9: a mutated REJECT row and a mutated turn
table must each fail.

M7 P5 (`hurt`, doomfj.hurtcode): the same script, and the player DIES at frame DEATH (p_dead 1, health 0, poked on
both sides, with a threshold poked on every third slot): from then on A_Chase resets the threshold and sends the
monster back to its spawn state, and A_Look neither sees nor hears (p32a_slot's `hurt`). R9: the target never lost
(the chase's dead test gone), the threshold still counted down, and a look that still sees must each fail."""
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
from doomfj.world import TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FRAMES = 48
DEATH = 24                       # M7 P5: the frame the player dies at (after the burst woke everyone)


def _world():
    return World(monsters="wake", sight_rule="seen")


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


def _expected(script, hurt=False) -> bytes:
    w = _world()
    n, ws = w.layout.nmon, w.ws
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
                             for m in range(n)) + "%02x" % ws.sched_cursor)
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
                          see_idx=gd.STATE_INDEX[info.seestate],
                          see_tics=gd.STATES[info.seestate].tics,
                          **({"hurt": dict(sp=gd.STATE_INDEX[info.spawnstate],
                                           spt=gd.STATES[info.spawnstate].tics)} if hurt else {})))
    tables = [generate_dispatch_table_fj("mstate", MC.state_table_values(), index_nibbles=2, result_nibbles=6)]
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
        tables.append(generate_dispatch_table_fj("rj%d" % s, vals, index_nibbles=2, result_nibbles=1))
    nleaf = len(w.cmap.subsectors)
    tables.append(generate_dispatch_table_fj("lfsec", list(w.leaf_sector), index_nibbles=max(1, ((nleaf - 1).bit_length() + 3) // 4),
                                             result_nibbles=2))
    tables.append(generate_point_location_fj(w.cmap))
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS}
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": ws.sched_cursor}, n)
             + MC.MT_DECLS + MC.P32A_SCRATCH + point_location_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "mt_tret: hex.vec w/4"]
             + (["p_dead: hex.vec 1, 0"] if hurt else []))
    code = ["mt_tic_leaf:"] + MC.p32a_tic_lines(schema, n, slots, exit_guard=False) + ["    stl.fret mt_tret"]
    return decls, code + MC.p32a_leaves(), tables


def _run(tmp_path, name, hurt=False, hurt_mut=None, **mut) -> bool:
    w = _world()
    n = w.layout.nmon
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
        body += ["hex.print_as_digit 2, sched_cursor, 0", "stl.output 10"]
    body.append("stl.loop")
    decls, code, tables = _parts(w, hurt=hurt, **mut)
    code = "\n".join(code) + "\n"
    if hurt_mut:
        pat, new = HURT_MUTS[hurt_mut]
        code, k = re.subn(pat, new, code)
        assert k == n, (hurt_mut, k, n)
    prog = "\n".join(body + decls + [code] + tables) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    from doomfj.config import Config
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", _expected(script, hurt), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_wake_tic_follows_the_model(tmp_path):
    assert _run(tmp_path, "mwake"), "the fj wake tic parted from the model's wake mode"


@pytest.mark.parametrize("mut", ["rj_mutate", "turn_mutate"])
def test_control_a_mutated_table_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mwake_" + mut, **{mut: True}), "%s passed: the comparison is vacuous" % mut


def test_the_hurt_script_loses_its_targets():
    """the model after the death: awake monsters return to their spawn state, a poked threshold is reset, and
    nobody wakes again -- each control needs its path"""
    w = _world()
    n, ws = w.layout.nmon, w.ws
    script = _script(w)
    thr = _thr_slots(w)
    spawn = {m: gd.STATE_INDEX[w.mon_info[m].spawnstate] for m in range(n)}
    look = {m: {spawn[m], gd.STATE_INDEX[gd.STATES[w.mon_info[m].spawnstate].next]} for m in range(n)}
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
