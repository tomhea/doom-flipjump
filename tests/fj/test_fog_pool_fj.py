"""M8 (the owner, 2026-10-18: "if teleport fog is simple and cheap add it"): THE TELEPORT FOG in the EFFECTS POOL on
the real flipjump engine -- projcode's fx_lines(fog=True) (tf_spawn, fx_spawn with A FOG YIELDS, fx_spawn_leaf's fog
branch, fx_phase through pjst) and the shared pool leaves (pool_tic, pw_link / pw_unlink on the real leaf lists),
against the model's `combat._spawn_fx` (kind "fog", "blood", "puff") and `_fx_phase` on an E1M2 World in the game
tier's modes ("final" / "final": the puffs' fxs_kind, the fog's rule teleport.fog_on).

A record is one operation: a FOG spawned at a position (teleportcode's fire branches call tf_spawn so), BLOOD (by the
damage: S_BLOOD1 / 2 / 3) or a PUFF (the fist's: S_PUFF3) spawned at a target with the player around it in some octant,
or 1 .. 72 fx phases (a fog's whole life is 72 tics); weighted so the two slots fill with fogs, with blood and fogs,
and a fog meets a full pool. The point location is stubbed as in test_fx_pool_fj (its query printed, the model's leaf
read from stdin). After every record: both slots (active, x, y, state, tics, the thpos_rt row, the thss_rt leaf) and
rng_fx; every 6th the leaf lists.

R9 (each must part): a fog that evicts as blood does (tf_spawn through fx_spawn), no yield (blood skipped by a fog),
a fog that draws P_Random, a fog of 5 tics, slot 0's fog told by fx_st's LOW nibble (only the fog states whose low
nibble is 0xE / 0xF yield), a fog through the octant step (the branch's jump to fx_pos removed). (The yield without
its unlink is no control here: the stale link makes a cycle and the leaf walk never ends.)
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monsterdecide as MD
from doomfj import projcode as PC
from doomfj.collision import point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl
from doomfj.wad import WadFile
from doomfj.world import FIREBALL_POOL, FX_POOL, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
N = 600
LIST_EVERY = 6
M32 = 0xFFFFFFFF


def _world():
    return World(WadFile.from_path(FIX), "E1M2", skill=gd.SK_HARD, player="final", monsters="final")


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _records():
    rnd = random.Random(0xF06)
    out = []
    for r in range(N):
        u = rnd.random()
        x, y = rnd.randint(-800, 3200), rnd.randint(-2400, 1400)
        if u < 0.27:
            out.append(("fog", x, y))
        elif u < 0.50:
            dx, dy = rnd.randint(-300, 300), rnd.randint(-300, 300)
            px16 = (((x + dx) << 16) | rnd.randrange(1 << 16)) & M32
            py16 = (((y + dy) << 16) | rnd.randrange(1 << 16)) & M32
            if u < 0.42:
                out.append(("blood", x, y, px16, py16, rnd.choice((5, 8, 9, 12, 13, 20))))
            else:
                out.append(("puff", x, y, px16, py16, int(rnd.random() < 0.4)))
        else:
            out.append(("phase", rnd.choice((1, 3, 6, 12, 18, 30, 50, 67, 72))))
    return out


def _apply(w, rec, ev):
    ws = w.ws
    if rec[0] == "fog":
        w._spawn_fx("fog", rec[1] << 16, rec[2] << 16, 0, False, ev)
    elif rec[0] in ("blood", "puff"):
        _k, x, y, px16, py16, arg = rec
        ws.px, ws.py = _s32(px16), _s32(py16)
        if rec[0] == "blood":
            w._spawn_fx_at_target("blood", x, y, arg, False, ev)
        else:
            w._spawn_fx_at_target("puff", x, y, 0, bool(arg), ev)
    else:
        for _ in range(rec[1]):
            w._fx_phase(ev)


def _row(w):
    ws = w.ws
    s = ""
    for k in range(FX_POOL):
        s += "%x%08x%08x%02x%x%08x%08x%03x" % (ws.fx_active[k], ws.fx_x[k] & M32, ws.fx_y[k] & M32, ws.fx_state[k],
                                               ws.fx_tics[k], ws.fx_y[k] & M32, ws.fx_x[k] & M32, ws.fx_leaf[k])
    return s + "%02x" % ws.rng_fx


def _lists(w):
    return "".join("%03x:%s" % (leaf, ",".join("%02x" % k for k in ks)) for leaf, ks in sorted(w.leaf_lists().items()))


def _model(records):
    """-> (the expected output, the stdin feed: the leaves of the point locations)"""
    w = _world()
    log, feed = [], []
    orig = w._leaf16

    def leaf16(x16, y16):
        leaf = orig(x16, y16)
        log.append("p%010x%010x" % ((x16 >> 16) & 0xFFFFFFFFFF, (y16 >> 16) & 0xFFFFFFFFFF))
        feed.append(struct.pack("<H", leaf))
        return leaf
    w._leaf16 = leaf16
    lines = []
    for r, rec in enumerate(records):
        _apply(w, rec, TicEvents(0))
        lines.append("".join(log) + _row(w))
        log.clear()
        if r % LIST_EVERY == LIST_EVERY - 1:
            lines.append(_lists(w))
    return ("\n".join(lines) + "\n").encode(), b"".join(feed)


def leaf_dump_lines(nleaf: int) -> list:
    """test_fx_pool_fj's ll_dump: every leaf with a list, "lll:" then its runtime things"""
    return ["ll_dump:",
            "    hex.zero w/4, dl_i",
            "  dl_next:",
            "    hex.set w/4, ll_base, sshead",
            "    hex.ptr_index ll_p, ll_base, dl_i", "    hex.read_byte ll_v, ll_p",
            "    hex.if0 2, ll_v, dl_end",
            "    hex.print_as_digit 3, dl_i, 0", "    stl.output 58",
            "  dl_loop:",
            "    hex.dec 2, ll_v", "    hex.print_as_digit 2, ll_v, 0",
            "    hex.set w/4, ll_base, thnext", "    hex.zero w/4, ll_idx", "    hex.mov 2, ll_idx, ll_v",
            "    hex.ptr_index ll_p, ll_base, ll_idx", "    hex.read_byte ll_v, ll_p",
            "    hex.if0 2, ll_v, dl_end", "    stl.output 44", "    ;dl_loop",
            "  dl_end:",
            "    hex.inc w/4, dl_i",
            "    hex.set w/4, dl_n, %d" % nleaf,
            "    hex.cmp w/4, dl_i, dl_n, dl_next, dl_done, dl_done",
            "  dl_done:",
            "    stl.output 10", "    stl.fret dump_ret"]


def _mutate(text, mut):
    def sub(old, new, cnt=1):
        assert text.count(old) == cnt, (mut, old, text.count(old))
        return text.replace(old, new)
    if mut == "fog_evicts":
        return sub("tf_spawn:\n", "tf_spawn:\n    ;fx_spawn\n")
    if mut == "no_yield":
        return sub(", %d, fx_q" % PC.FOG_FLAGS, ", 0, fx_q", FX_POOL)
    if mut == "fog_rolls":
        return sub("  fx_fog:\n", "  fx_fog:\n    hex.inc 2, rng_fx\n")
    if mut == "fog_tics":
        return sub("    hex.set 1, pw_ti, 6\n    ;fx_pos\n", "    hex.set 1, pw_ti, 5\n    ;fx_pos\n")
    if mut == "wrong_nibble":
        return sub("hex.if_flags fx_st + 1*dw, %d" % PC.FOG_FLAGS, "hex.if_flags fx_st + 0*dw, %d" % PC.FOG_FLAGS)
    if mut == "fog_octant":
        return sub("    ;fx_pos\n  fx_nfog:\n", "  fx_nfog:\n")
    raise ValueError(mut)


MUTANTS = ("fog_evicts", "no_yield", "fog_rolls", "fog_tics", "wrong_nibble", "fog_octant")


def _build(tmp_path, name, mut=None):
    w = _world()
    n, nleaf, ws = w.layout.nmon, len(w.cmap.subsectors), w.ws
    nt = n
    nthings = nt + FIREBALL_POOL + FX_POOL
    records = _records()
    want, feed = _model(records)
    code = "\n".join(MD.octant_leaf_lines() + PC.fx_lines(nt=nt, puffs=True, fog=True) + PC.pool_tic_lines()) + "\n"
    if mut:
        code = _mutate(code, mut)
    head, nxt = [0] * nleaf, [0] * nthings
    for leaf, ks in w.leaf_lists().items():
        head[leaf] = ks[0] + 1
        for a, b in zip(ks, ks[1:] + [-1]):
            nxt[a] = b + 1
    kinds = PC.FX_KINDS
    body = ["stl.startup_and_init_all"]
    for r, rec in enumerate(records):
        if rec[0] == "fog":
            body += ["hex.set 4, fxs_x, %d" % (rec[1] & 0xFFFF), "hex.set 4, fxs_y, %d" % (rec[2] & 0xFFFF),
                     "hex.set 1, fxs_kind, %d" % kinds["fog"], "stl.fcall tf_spawn, fx_sret"]
        elif rec[0] in ("blood", "puff"):
            _k, x, y, px16, py16, arg = rec
            kind = kinds["blood"] if rec[0] == "blood" else kinds["fistpuff" if arg else "puff"]
            body += ["hex.set 8, viewx, %d" % px16, "hex.set 8, viewy, %d" % py16,
                     "hex.set 4, fxs_x, %d" % (x & 0xFFFF), "hex.set 4, fxs_y, %d" % (y & 0xFFFF),
                     "hex.set 2, fxs_dmg, %d" % (arg if rec[0] == "blood" else 0), "hex.set 1, fxs_kind, %d" % kind,
                     "stl.fcall fx_spawn, fx_sret"]
        else:
            body += ["stl.fcall fx_phase, fx_pret"] * rec[1]
        body += ["stl.fcall rec_dump, dump_ret"]
        if r % LIST_EVERY == LIST_EVERY - 1:
            body += ["stl.fcall ll_dump, dump_ret"]
    body += ["stl.loop"]
    dump = ["rec_dump:"]
    for s in range(FX_POOL):
        t = nt + FIREBALL_POOL + s
        dump += ["    hex.print_as_digit 1, fx_act + %d*dw, 0" % s,
                 "    hex.print_as_digit 8, fx_x + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, fx_y + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 2, fx_st + %d*dw, 0" % (2 * s),
                 "    hex.print_as_digit 1, fx_ti + %d*dw, 0" % s,
                 "    hex.print_as_digit 16, thpos_rt + %d*dw, 0" % (16 * t),
                 "    hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * t)]
    dump += ["    hex.print_as_digit 2, rng_fx, 0", "    stl.output 10", "    stl.fret dump_ret"]
    stubs = ["ptloc_walk:", "    stl.output 112", "    hex.print_as_digit 10, ptx, 0",
             "    hex.print_as_digit 10, pty, 0", "    hex.zero w/4, ptss", "    hex.input 2, ptss",
             "    stl.fret ptloc_ret"]
    decls = (MD.context_decls() + PC.pool_decls(puffs=True) + point_location_decls() + LEAF_LINK_DECLS
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "lvdone: hex.vec 1",
                "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4",   # mm_octant's
                "dump_ret: hex.vec w/4", "dl_i: hex.vec w/4", "dl_n: hex.vec w/4",
                "thpos_rt: hex.vec %d, %d" % (16 * nthings, sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32)
                                                                 << 32) << (64 * m) for m in range(n))),
                "thss_rt: hex.vec %d, %d" % (16 * nthings, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * nthings)])
    prog = "\n".join(body + decls + dump + leaf_dump_lines(nleaf) + stubs + [code]
                     + PC.tables_fj(puffs=True, fog=True)) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, feed, want


def _run(tmp_path, name, mut=None) -> bool:
    srcs, feed, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, feed, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path():
    """the model's own events: fogs spawned and skipped (a full pool), blood and puffs spawned into a free slot and
    into a fog's (the yield), blood or a puff skipped (two live blood / puff slots), every fog state walked, fogs
    removed at the end of their life, two fogs at once"""
    w = _world()
    ws = w.ws
    seen = dict(fog=0, fog_skipped=0, fx_free=0, fx_yield=0, fx_skipped=0, two_fogs=0, fog_removed=0)
    states = set()
    for rec in _records():
        before = [(ws.fx_active[s], w._fx_is_fog(s)) for s in range(FX_POOL)]
        ev = TicEvents(0)
        _apply(w, rec, ev)
        if rec[0] == "fog":
            seen["fog"] += len(ev.fx_spawns)
            seen["fog_skipped"] += ev.fx_skipped
        elif rec[0] != "phase":
            for slot, _kind in ev.fx_spawns:
                seen["fx_yield" if before[slot][0] else "fx_free"] += 1
            seen["fx_skipped"] += ev.fx_skipped
        else:
            seen["fog_removed"] += sum(1 for s in range(FX_POOL) if before[s][1] and not ws.fx_active[s])
        seen["two_fogs"] += all(w._fx_is_fog(s) for s in range(FX_POOL))
        states |= {gd.STATE_NAMES[ws.fx_state[s]] for s in range(FX_POOL) if w._fx_is_fog(s)}
    want = dict(fog=60, fog_skipped=20, fx_free=30, fx_yield=15, fx_skipped=10, two_fogs=15, fog_removed=15)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)
    assert len(states) == 12, sorted(states)


def test_the_fog_pool_follows_the_model(tmp_path):
    assert _run(tmp_path, "fogpool"), "the fj effects pool with the fog parted from the model's"


@pytest.mark.parametrize("mut", MUTANTS)
def test_control_a_broken_fog_pool_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "fogpool_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
