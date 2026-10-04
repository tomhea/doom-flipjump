"""M7 P4.2b (doomfj.noisecode): the player's NOISE on the real flipjump engine against the model.

THE FLOOD (`nz_flood`, `nz_leaf`): `World.noise_alert` -- P_NoiseAlert over the sound nodes, the doors' and movers'
openings as runtime edges -- for EVERY start sector under several mixes of door, lift and switch states (all shut,
all open, two random mixes), each on top of a random earlier alert, so the OR and the scratch both show. Then
`nz_leaf` itself, the player's sector located from `viewx` / `viewy`, at every monster's spawn point and the start.
R9: one relaxation pass instead of the fixpoint, the flood written straight into `snd_alert` (no scratch: an
earlier alert seeds it), and one edge's open test inverted -- each must part from the model.

THE SOUND BRANCH (monstercode.p32a_slot `hear`, `nz_heard`): the wake tic (World(monsters="wake", sight_rule=
"seen")) with alerts and ambush flags set per frame -- a monster that heard wakes, an ambusher only in the waking
sight (and then with no facing test), and the target is set either way. R9: the ambush flag ignored, and a deaf
branch, must each part.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import noisecode as NZ
from doomfj.collision import generate_point_location_fj, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.world import TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
MIXES = ("shut", "open", "mixed1", "mixed2")


def _lfsec(w) -> str:
    nleaf = len(w.cmap.subsectors)
    return generate_dispatch_table_fj("lfsec", list(w.leaf_sector),
                                      index_nibbles=max(1, ((nleaf - 1).bit_length() + 3) // 4), result_nibbles=2)


def _states(w, mix):
    """(door states, lift states, switch) for a mix"""
    if mix == "shut":
        return [0] * len(w.door_order), [0] * len(w.lift_order), 0
    if mix == "open":
        return ([w.door_nstates[si] - 1 for si in w.door_order], [len(w.lift_stops[si]) - 1 for si in w.lift_order],
                1)
    rnd = random.Random(mix)
    return ([rnd.randrange(w.door_nstates[si]) for si in w.door_order],
            [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order], rnd.randrange(2))


def _apply(w, st):
    ds, ls, sw = st
    for d, v in enumerate(ds):
        w.ws.d_state[d] = v
    for k, v in enumerate(ls):
        w.ws.l_state[k] = v
    w.ws.f_switch = sw
    w._door_phase_scene()


def _cases(w):
    """(mix, the states, start sector or None, (x16, y16) or None, the earlier alert)"""
    rnd = random.Random(0x42B)
    out = []
    for mix in MIXES:
        st = _states(w, mix)
        for s in range(len(w.secs)):
            out.append((mix, st, s, None, [int(rnd.random() < 0.2) for _ in range(w.nsound)]))
    pts = [(w.ws.px, w.ws.py)] + [((w.ws.mon_x[m] << 16) | 0x8000, (w.ws.mon_y[m] << 16) | 0x2000)
                                 for m in range(w.layout.nmon)]
    for i, (x16, y16) in enumerate(pts):
        out.append((MIXES[i % len(MIXES)], _states(w, MIXES[i % len(MIXES)]), None, (x16 & 0xFFFFFFFF,
                                                                                     y16 & 0xFFFFFFFF),
                    [0] * w.nsound))
    return out


def _expected(w, cases) -> bytes:
    lines = []
    real = w.player_sector
    for mix, st, s, xy, prior in cases:
        _apply(w, st)
        for k in range(w.nsound):
            w.ws.snd_alert[k] = prior[k]
        if s is None:
            x16, y16 = xy
            w.ws.px, w.ws.py = (x16 - (1 << 32) if x16 >> 31 else x16), (y16 - (1 << 32) if y16 >> 31 else y16)
            w.player_sector = real
        else:
            w.player_sector = lambda s=s: s
        w.noise_alert()
        lines.append("".join("%x" % w.ws.snd_alert[k] for k in range(w.nsound)))
    w.player_sector = real
    return ("\n".join(lines) + "\n").encode()


def _invert_target(w):
    """the edge the "invert" control breaks: the first whose open test is neither always nor never"""
    for j, (_a, _b, cell, n, mask) in enumerate(NZ.sound_edges(w)):
        if mask != (1 << n) - 1:
            return j, cell, n, mask
    raise AssertionError("no edge has an open test")


def _flood_text(w, mut=None) -> str:
    text = "\n".join(NZ.noise_leaf_lines(w)) + "\n"
    n = w.nsound
    if mut == "onepass":
        old = "    hex.if1 1, nz_ch, nz_pass\n"
        assert text.count(old) == 1
        text = text.replace(old, "")
    elif mut == "noscratch":                          # flood the persisted cells themselves: no scratch, no zeroing
        old = "    hex.zero %d, nz_r\n" % n
        assert text.count(old) == 1
        text = text.replace(old, "").replace("nz_r + ", "snd_alert + ")
    elif mut == "invert":
        j, cell, ns, mask = _invert_target(w)
        old = "    hex.if_flags %s, %#06x, nz_e%dx, " % (cell, mask, j)
        assert text.count(old) == 2, text.count(old)
        text = text.replace(old, "    hex.if_flags %s, %#06x, nz_e%dx, " % (cell, ~mask & ((1 << ns) - 1), j))
    else:
        assert mut is None, mut
    return text


def _srcs(tmp_path, name, prog):
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]


def _flood_run(tmp_path, name, mut=None) -> bool:
    w = World(skill=gd.SK_HARD, monsters="idle")
    cases = _cases(w)
    want = _expected(w, cases)
    nd, nl, n = len(w.door_order), max(1, len(w.lift_order)), w.nsound
    body = ["stl.startup_and_init_all"]
    for mix, (ds, ls, sw), s, xy, prior in cases:
        body += ["hex.set %d, dstate, %d" % (nd, sum(v << (4 * d) for d, v in enumerate(ds))),
                 "hex.set %d, lstate, %d" % (nl, sum(v << (4 * k) for k, v in enumerate(ls))),
                 "hex.set 1, fswitch, %d" % sw,
                 "hex.set %d, snd_alert, %d" % (n, sum(v << (4 * k) for k, v in enumerate(prior)))]
        if s is None:
            body += ["hex.set 8, viewx, %d" % xy[0], "hex.set 8, viewy, %d" % xy[1], "stl.fcall nz_leaf, nz_ret"]
        else:
            body += ["hex.set 2, nz_sec, %d" % s, "stl.fcall nz_flood, nz_ret"]
        body += ["hex.print_as_digit 1, snd_alert + %d*dw, 0" % k for k in range(n)] + ["stl.output 10"]
    body.append("stl.loop")
    decls = (NZ.noise_decls(w) + point_location_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "mt_ms: hex.vec 2",
                "dstate: hex.vec %d" % nd, "lstate: hex.vec %d" % nl, "fswitch: hex.vec 1"])
    prog = "\n".join(body + decls) + "\n" + _flood_text(w, mut) + "\n".join(
        [_lfsec(w), generate_point_location_fj(w.cmap)]) + "\n"
    return fj.assemble_and_run_test_output(_srcs(tmp_path, name, prog), b"", want, memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_model_needs_what_the_controls_break():
    """each flood control has something to break in these cases: a flood that needs a second pass in the emitted
    edge order, an earlier alert with an open way out of it, and the inverted edge deciding some flood"""
    w = World(skill=gd.SK_HARD, monsters="idle")
    edges = NZ.sound_edges(w)
    assert all(st >= w.nsound - len(set(w.door_order) | set(w.mover_order)) for _a, st, *_ in edges), \
        "an edge's second end is not a dynamic node"
    assert len({tuple(e[:2]) for e in edges}) == len(edges)
    need2 = 0
    for mix in MIXES:
        _apply(w, _states(w, mix))
        for s in range(len(w.secs)):
            r = {w.sector_node[s]}
            for a, b, cell, n, mask in edges:                     # one pass in the emitted order
                st = (w.ws.d_state[w.door_order.index(_dyn_sector(w, b))] if cell.startswith("dstate")
                      else w.ws.l_state[w.lift_order.index(_dyn_sector(w, b))] if cell.startswith("lstate")
                      else w.ws.f_switch)
                if (a in r) != (b in r) and mask >> st & 1:
                    r |= {a, b}
            for k in range(w.nsound):
                w.ws.snd_alert[k] = 0
            w.player_sector = lambda s=s: s
            w.noise_alert()
            need2 += r != {k for k in range(w.nsound) if w.ws.snd_alert[k]}
    assert need2, "one pass always reaches the fixpoint: the onepass control would prove nothing"


def _dyn_sector(w, node):
    return next(s for s in list(w.door_order) + list(w.mover_order) if w.sector_node[s] == node)


def test_the_flood_follows_the_model(tmp_path):
    assert _flood_run(tmp_path, "nzflood"), "the fj flood parted from World.noise_alert"


@pytest.mark.parametrize("mut", ["onepass", "noscratch", "invert"])
def test_control_a_broken_flood_is_caught(tmp_path, mut):
    assert not _flood_run(tmp_path, "nzflood_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ---- the sound branch of A_Look ------------------------------------------------------------------------------------
FRAMES = 60


def _wworld():
    return World(monsters="wake", sight_rule="seen")


def _wscript(w):
    """per frame: (player x16, y16, seen slots, alerted nodes, ambush slots)"""
    rnd = random.Random(0x42B2)
    n = w.layout.nmon
    act = [m for m in range(n) if w.ws.mon_active[m]]
    out = []
    for f in range(FRAMES):
        m = act[(f * 11) % len(act)]
        ox, oy = [(40, 20), (-60, 30), (90, -50), (-20, -110), (150, 10), (-30, -40)][f % 6]
        x16, y16 = (w.ws.mon_x[m] + ox) << 16 | 0x4000, (w.ws.mon_y[m] + oy) << 16
        seen = set(rnd.sample(act, 3)) if f % 3 else set()
        alert = set(rnd.sample(range(w.nsound), 2)) if f % 4 else set()
        if f % 2:                                             # the node of the monster the player stands by
            alert.add(w.sector_node[w._mon_sector(m)])
        amb = {q for q in range(n) if rnd.random() < 0.6}
        out.append((x16 & 0xFFFFFFFF, y16 & 0xFFFFFFFF, seen, alert, amb))
    return out


def _wset(w, fr):
    ws = w.ws
    x16, y16, seen, alert, amb = fr
    ws.px, ws.py = x16 - (1 << 32) if x16 >> 31 else x16, y16 - (1 << 32) if y16 >> 31 else y16
    for m in range(w.layout.nmon):
        ws.mon_seen[m] = int(m in seen)
        ws.mon_ambush[m] = int(m in amb)
    for k in range(w.nsound):
        ws.snd_alert[k] = int(k in alert)


def _wexpected(script) -> bytes:
    w = _wworld()
    n, ws = w.layout.nmon, w.ws
    lines = []
    for fr in script:
        _wset(w, fr)
        w._monsters_phase(TicEvents(0))
        lines.append("".join("%02x%x%x%x%x%02x" % (ws.mon_state[m], ws.mon_tics[m], ws.mon_facing[m],
                                                    ws.mon_target[m], ws.mon_reaction[m], ws.mon_threshold[m])
                             for m in range(n)) + "%02x" % ws.sched_cursor)
    return ("\n".join(lines) + "\n").encode()


def test_the_wake_script_exercises_the_sound_branch():
    """the model's own events: wakes by sound of plain monsters and of ambushers, and ambushers that heard and
    stayed asleep -- the two controls below need them"""
    w = _wworld()
    script = _wscript(w)
    plain = amb_woke = amb_slept = 0
    for fr in script:
        _wset(w, fr)
        asleep_heard = {m for m in range(w.layout.nmon) if w.ws.mon_active[m]
                        and gd.STATES[gd.STATE_NAMES[w.ws.mon_state[m]]].action == "A_Look"
                        and w.ws.snd_alert[w.sector_node[w._mon_sector(m)]]}
        ev = TicEvents(0)
        w._monsters_phase(ev)
        for m, how in ev.wakes:
            if how == "sound":
                plain += m not in fr[4]
                amb_woke += m in fr[4]
        amb_slept += sum(1 for m in asleep_heard & fr[4] if all(m != q for q, _ in ev.wakes)
                         and gd.STATES[gd.STATE_NAMES[w.ws.mon_state[m]]].action == "A_Look")
    assert plain >= 3 and amb_woke >= 1 and amb_slept >= 3, (plain, amb_woke, amb_slept)


def _wrun(tmp_path, name, mut=None) -> bool:
    w = _wworld()
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    script = _wscript(w)
    body = ["stl.startup_and_init_all"]
    for x16, y16, seen, alert, amb in script:
        body += ["hex.set 8, viewx, %d" % x16, "hex.set 8, viewy, %d" % y16,
                 "hex.set %d, thseen, %d" % (n, sum(1 << (4 * m) for m in seen)),
                 "hex.set %d, snd_alert, %d" % (w.nsound, sum(1 << (4 * k) for k in alert)),
                 "hex.set %d, mon_ambush, %d" % (n, sum(1 << (4 * m) for m in amb)),
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
    slots = []
    for m in range(n):
        info = w.mon_info[m]
        slots.append(dict(t=m, x=ws.mon_x[m], y=ws.mon_y[m], rj="rj%d" % w._mon_sector(m),
                          see_idx=gd.STATE_INDEX[info.seestate], see_tics=gd.STATES[info.seestate].tics,
                          hear=True, sec=w._mon_sector(m)))
    tables = [generate_dispatch_table_fj("mstate", MC.state_table_values(), index_nibbles=2, result_nibbles=6),
              generate_dispatch_table_fj("mturn", MC.turn_table_values(), index_nibbles=2, result_nibbles=1)]
    for s in sorted({w._mon_sector(m) for m in range(n)}):
        tables.append(generate_dispatch_table_fj("rj%d" % s, [int(w.reject.visible(s, p)) for p in range(w.reject.nsec)],
                                                 index_nibbles=2, result_nibbles=1))
    tables += [_lfsec(w), generate_point_location_fj(w.cmap)]
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS}
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": ws.sched_cursor}, n)
             + MC.MT_DECLS + MC.P32A_SCRATCH + point_location_decls() + NZ.noise_decls(w)
             + [NZ.ambush_decl(n, [0] * n), "mt_ms: hex.vec 2", "dstate: hex.vec %d" % len(w.door_order),
                "lstate: hex.vec %d" % max(1, len(w.lift_order)), "fswitch: hex.vec 1",
                "viewx: hex.vec 8", "viewy: hex.vec 8", "mt_tret: hex.vec w/4"])
    code = "\n".join(["mt_tic_leaf:"] + MC.p32a_tic_lines(schema, n, slots, exit_guard=False)
                     + ["    stl.fret mt_tret"] + MC.p32a_leaves() + NZ.noise_leaf_lines(w)) + "\n"
    if mut == "noambush":                             # every ambusher treated as a plain monster
        k = 0
        for m in range(n):
            old = "    hex.if0 1, mon_ambush + %d*dw, mw%d_wake\n" % (m, m)
            k += code.count(old)
            code = code.replace(old, "    ;mw%d_wake\n" % m)
        assert k == n, k
    elif mut == "deaf":                               # the branch never hears
        old = "    stl.fcall nz_heard, nz_hret\n"
        assert code.count(old) == n
        code = code.replace(old, "    hex.zero 1, nz_h\n")
    else:
        assert mut is None, mut
    prog = "\n".join(body + decls) + "\n" + code + "\n".join(tables) + "\n"
    return fj.assemble_and_run_test_output(_srcs(tmp_path, name, prog), b"", _wexpected(script), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_sound_branch_follows_the_model(tmp_path):
    assert _wrun(tmp_path, "nzwake"), "the fj A_Look sound branch parted from the model's"


@pytest.mark.parametrize("mut", ["noambush", "deaf"])
def test_control_a_broken_sound_branch_is_caught(tmp_path, mut):
    assert not _wrun(tmp_path, "nzwake_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ---- the decide tic hears: the sound branch on the runtime sector (`msec`), and A_FaceTarget clears the ambush -------
def _decide():
    """test_monster_decide_fj's harness, reused whole: its world, script, parts and row"""
    import importlib
    return importlib.import_module("tests.fj.test_monster_decide_fj")


def _dscript(D, w):
    """D's per-frame inputs, each with the alerted nodes: two random ones on most frames"""
    rnd = random.Random(0x42B3)
    return [fr + (set(rnd.sample(range(w.nsound), 2)) if f % 3 else set(),) for f, fr in enumerate(D._script())]


def _drow(D, w):
    return D._row(w) + "".join("%x" % w.ws.mon_ambush[m] for m in range(w.layout.nmon))


def _dexpected(D, script) -> bytes:
    w = D._world()
    ws = w.ws
    lines = []
    for *fr, alert in script:
        D._set(w, *fr)
        for k in range(w.nsound):
            ws.snd_alert[k] = int(k in alert)
        w._monsters_phase(TicEvents(0))
        lines.append(_drow(D, w))
        for d in range(len(w.door_order)):
            ws.d_monreq[d] = 0
        for k in range(len(w.lift_order)):
            ws.l_req[k] = 0
    return ("\n".join(lines) + "\n").encode()


def test_the_decide_script_hears_and_faces():
    """the model's own events over the script: sound wakes, and A_FaceTarget clearing an ambusher's flag -- the
    noface control needs it"""
    D = _decide()
    w = D._world()
    script = _dscript(D, w)
    wakes = cleared = 0
    for *fr, alert in script:
        D._set(w, *fr)
        for k in range(w.nsound):
            w.ws.snd_alert[k] = int(k in alert)
        before = list(w.ws.mon_ambush)
        ev = TicEvents(0)
        w._monsters_phase(ev)
        wakes += sum(1 for _m, how in ev.wakes if how == "sound")
        cleared += sum(1 for m in range(w.layout.nmon) if before[m] and not w.ws.mon_ambush[m])
    assert wakes >= 3 and cleared >= 1, (wakes, cleared)


def _drun(tmp_path, monkeypatch, name, mut=None) -> bool:
    D = _decide()
    orig = MC.p32a_slot
    monkeypatch.setattr(MC, "p32a_slot", lambda m, **kw: orig(m, hear=True, **kw))
    w = D._world()
    n = w.layout.nmon
    script = _dscript(D, w)
    want = _dexpected(D, script)
    body = ["stl.startup_and_init_all"]
    for x16, y16, ang, seen, alert in script:
        body += ["hex.set 8, viewx, %d" % x16, "hex.set 8, viewy, %d" % y16,
                 "hex.set %d, thseen, %d" % (n, sum(1 << (4 * m) for m in seen)),
                 "hex.set %d, snd_alert, %d" % (w.nsound, sum(1 << (4 * k) for k in alert)),
                 "stl.fcall mt_tic_leaf, mt_tret"]
        for m in range(n):
            body += ["hex.print_as_digit 2, mon_state + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_tics + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_facing + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_target + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_reaction + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_threshold + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_movedir + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_movecount + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 2, mon_rng + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_justattacked + %d*dw, 0" % m,
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 4),
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 12),
                     "hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m),
                     "hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * m)]
        body += ["hex.print_as_digit 2, sched_cursor, 0"]
        body += ["hex.print_as_digit 1, mon_ambush + %d*dw, 0" % m for m in range(n)]
        body += ["hex.zero %d, dreq" % (2 * len(w.door_order)), "hex.zero %d, lreq" % (2 * len(w.lift_order)),
                 "stl.output 10"]
    body += ["stl.loop"]
    decls, text = D._parts(w)
    decls = decls + NZ.noise_decls(w) + [NZ.ambush_decl(n, list(w.ws.mon_ambush[:n]))]
    text = text + "\n".join(NZ.noise_leaf_lines(w)) + "\n"
    if mut == "noface":                               # A_FaceTarget leaves MF_AMBUSH alone
        k = 0
        for m in range(n):
            old = "    hex.zero 1, mon_ambush + %d*dw\n" % m
            k += text.count(old)
            text = text.replace(old, "")
        assert k >= n, k
    else:
        assert mut is None, mut
    prog = "\n".join(body + decls + [text]) + "\n"
    return fj.assemble_and_run_test_output(_srcs(tmp_path, name, prog), b"", want, memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_decide_tic_hears_and_faces(tmp_path, monkeypatch):
    assert _drun(tmp_path, monkeypatch, "nzdecide"), "the fj decide tic with the sound branch parted from the model"


def test_control_a_face_target_that_keeps_the_ambush_is_caught(tmp_path, monkeypatch):
    assert not _drun(tmp_path, monkeypatch, "nzdecide_noface", "noface"), "noface passed: the comparison is vacuous"
