"""M8 F1.5 (docs/f1-runtime-ids.md, option A1) -- RUNTIME THING IDS PAST 254, run in fj.

A map whose runtime things + pools + drops pass 254 (E1M3 341, E1M4 345, E1M5 370) keeps its per-leaf lists in the
same cells at 12 bits (Config.LIST_ID_BITS = 12) and reads / writes them through flipjump's DUAL decoder table
(`-D hex.pointers.PTR_WIDE_BITS=12`, Config.emit_fj_defines). This RUNS every piece a wide map adds, each in its own
image assembled with that defines file, each against the model's own code -- never a Python model of the fj ops:

  1. the relink (`sim.leaf_link_w` / `sim.leaf_unlink_w`) at NT = 300 -- ids 0 .. 299 with 254 / 255 / 256 / 257
     (encoded 0x0FF / 0x100 / 0x101 / 0x102) linked and unlinked at the head, the middle and the tail of lists that
     straddle 255 / 256 -- against `world.World._list_insert` / `_list_remove`, EVERY cell of both arrays after every
     op (one image: a dirty cell corrupts the next op);
  2. the depth walk (`sim.thing_pass_depth_w`, 7- and 9-parameter forms) on rows 250 .. 262 with the rank threshold
     rk0 at 0xFE and 0x102 -- the drawn order against the oracle's `reference_model.rank_depth_key` /
     `aprox_depth_key`, and every register clear after every leaf;
  3. the row select (`monstercode.select_tree_lines`) at ntm = 300: ids 0, 15, 16, 255, 256, 271, 299 reach their own
     stubs, 300 / 0x3FF / 0xFFF reach `thsel_none`;
  4. the restart's list fragment (`wall_renderer.list_restart_lines` at 12 bits: m1.zerocell12 + 12 raw flips a
     cell) over cells planted with 0xFFF / 0x100 / 0x0FF / 0x123 ..., against `things.spawn_leaf_lists`;
  5. the drop link (`barrelcode.drop_lines(list_bits=12)`: drop_link<k> / drop_take<k> through projcode's own
     pw_link / pw_unlink text) on drop rows d >= 260, against the model's list insert / remove.

THE CONTROLS (R9), each with its named symptom: `nib2` (the relink's id back to 2 nibbles), `narrow` (the relink's
wide reads left read_byte), `rank2` (rank_key_w's compare at 2 nibbles), `rk_set2` (td_rk set at 2 nibbles),
`select2` (the select's third level dropped: 256 prints 0), `zero8` (zerocell12's third xor dropped), `flip8` (a
restart cell's flips past bit 7 dropped), `drt2` (dr_t back to 2 nibbles). tests/host/test_wide_list_twins.py holds
the `_w` macros to their 8-bit twins by rule.
"""
import random
import struct
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import barrelcode as BC
from doomfj import monstercode as MC
from doomfj import projcode as PC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.reference_model import aprox_depth_key, rank_depth_key
from doomfj.things import byte_array_decl, leaf_link_decls, list_macros, list_max, spawn_leaf_lists
from doomfj.wall_renderer import list_restart_lines
from doomfj.world import FIREBALL_POOL, FX_POOL, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
WIDE = replace(Config(), LIST_ID_BITS=12)
MAX = list_max(12)


def _src(name: str, mut=None) -> str:
    text = (FJ / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    for old, new, count in (mut or ()):
        assert text.count(old) == count, (name, old, text.count(old))
        text = text.replace(old, new)
    return text


def _assemble(tmp: Path, name: str, prog: str, sim_mut=None, m1_mut=None, wide=True) -> Path:
    """one image: fj_consts, fixed_point, sim (mutated or not), m1_reset (mutated or not), the program -- with the
    wide-list map's defines file (Config.emit_fj_defines at LIST_ID_BITS 12)"""
    files = [Config().emit_fj_consts(tmp / "fj_consts.fj"), FJ / "fixed_point.fj"]
    for fname, mut in (("sim.fj", sim_mut), ("m1_reset.fj", m1_mut)):
        p = tmp / ("%s_%s" % (name, fname))
        p.write_text(_src(fname, mut), encoding="utf-8")
        files.append(p)
    src = tmp / (name + ".fj")
    src.write_text(prog, encoding="utf-8")
    files.append(src)
    out = tmp / (name + ".fjm")
    defs = WIDE.emit_fj_defines(tmp / "fj_defines.fj") if wide else None
    fj.assemble([Path(f).resolve() for f in files], out, memory_width=W, print_time=False,
                **({"defines_file": defs.resolve()} if defs else {}))
    return out


def _run(fjm: Path, feed: bytes) -> list:
    io = FixedIO(feed)
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode(errors="replace").split("\n")


def _dump_loop(label: str, n: int, tag: str) -> list:
    """print every cell of `label` (n cells) as 3 hex digits, through hex.read_cell (a loop: one copy of the read)"""
    return ["%s:" % tag, "    hex.zero w/4, dmp_i",
            "  %s_l:" % tag,
            "    hex.set w/4, ll_base, %s" % label,
            "    hex.ptr_index ll_p, ll_base, dmp_i",
            "    hex.read_cell ll_v, ll_p",
            "    hex.print_as_digit 3, ll_v, 0",
            "    hex.inc w/4, dmp_i",
            "    hex.set w/4, dmp_n, %d" % n,
            "    hex.cmp w/4, dmp_i, dmp_n, %s_l, %s_d, %s_d" % (tag, tag, tag),
            "  %s_d:" % tag, "    stl.fret dump_ret"]


def _cells(line: str, n: int) -> tuple:
    return tuple(int(line[3 * i:3 * i + 3], 16) for i in range(n))


# ---- 1. the relink at NT = 300 ---------------------------------------------------------------------------------------
NT, NLEAVES = 300, 4
PRESENT = (0, 1, 2, 100, 253, 254, 255, 256, 257, 298, 299)
BINDS = [t % NLEAVES for t in range(NT)]
LINK, UNLINK = 1, 2
MOVES = [(255, 3, 0),   # the head (0x100) out; in the middle, between 100 and 256 (0x065 < 0x100 < 0x101)
         (256, 0, 1),   # the tail out; in the middle, between 253 and 257 (0x0FE < 0x101 < 0x102)
         (299, 3, 2),   # a list's only element out; in at the tail
         (0, 0, 3),     # the head out; into an empty list
         (254, 2, 3),   # a middle link (0x0FF) out; in at the tail
         (1, 1, 3),     # the head out; in the middle
         (257, 1, 0),   # the tail out; in at the tail
         (100, 0, 1),   # the head out; in at the head
         (298, 2, 2),   # a round trip within one leaf
         (255, 0, 1)]   # the head out; in the middle, between 253 and 256
OPS = [op for t, old, new in MOVES for op in ((UNLINK, t, old), (LINK, t, new))]


def _lists():
    return spawn_leaf_lists(BINDS, NLEAVES, present=[t in PRESENT for t in range(NT)], max_things=MAX)


def _relink_model():
    head, nxt = _lists()
    fake = SimpleNamespace(ws=SimpleNamespace(leaf_head=list(head), mob_next=list(nxt)))
    out = []
    for op, t, leaf in OPS:
        (World._list_insert if op == LINK else World._list_remove)(fake, t, leaf)
        out.append((tuple(fake.ws.leaf_head), tuple(fake.ws.mob_next)))
    return out


def _relink_prog() -> str:
    head, nxt = _lists()
    mac = list_macros(12)
    return "\n".join([
        "stl.startup_and_init_all",
        "loop:",
        "    hex.input 1, rmagic", "    hex.if0 2, rmagic, done",
        "    hex.input 1, rop",
        "    hex.zero w/4, rt", "    hex.input 2, rt",
        "    hex.zero w/4, rl", "    hex.input 1, rl",
        "    hex.xor_by 1, rop, %d" % LINK, "    hex.if0 1, rop, do_link",
        "    %s rt, rl" % mac["unlink"], "    ;op_done",
        "  do_link:", "    %s rt, rl" % mac["link"],
        "  op_done:",
        "    stl.fcall dump_head, dump_ret", "    stl.fcall dump_next, dump_ret", "    stl.output 10",
        "    ;loop",
        "done:", "    stl.loop",
        *_dump_loop("sshead", NLEAVES, "dump_head"), *_dump_loop("thnext", NT, "dump_next"),
        byte_array_decl("sshead", head, 2 * NLEAVES, bits=12),
        byte_array_decl("thnext", nxt, 2 * NT, bits=12),
        "rmagic: hex.vec 2", "rop: hex.vec 2", "rt: hex.vec w/4", "rl: hex.vec w/4",
        "dump_ret: hex.vec w/4", "dmp_i: hex.vec w/4", "dmp_n: hex.vec w/4",
        *leaf_link_decls(3)]) + "\n"


def _relink_run(tmp, name, sim_mut=None):
    feed = b"".join(bytes([0xD0, op]) + struct.pack("<H", t) + bytes([leaf]) for op, t, leaf in OPS) + b"\x00"
    lines = _run(_assemble(tmp, name, _relink_prog(), sim_mut=sim_mut), feed)
    return [(_cells(ln, NLEAVES), _cells(ln[3 * NLEAVES:], NT)) for ln in lines[:len(OPS)]
            if len(ln) >= 3 * (NLEAVES + NT)]


def test_the_relink_cases_straddle_255_and_256():
    """the sequence visits every link / unlink case, and ids past 254 in them -- classified from the MODEL's state"""
    head, nxt = _lists()
    before = [(tuple(head), tuple(nxt))] + _relink_model()[:-1]
    seen = set()
    for (op, t, leaf), (h, n) in zip(OPS, before):
        chain, cur = [], h[leaf]
        while cur:
            chain.append(cur - 1)
            cur = n[cur - 1]
        if op == LINK:
            case = ("link:empty" if not chain else "link:head" if t < chain[0] else
                    "link:tail" if t > chain[-1] else "link:middle")
        else:
            case = ("unlink:only" if chain == [t] else "unlink:head" if chain[0] == t else
                    "unlink:tail" if chain[-1] == t else "unlink:middle")
        seen.add(case)
        if t >= 255:
            seen.add(case + ">=255")
        if any(c >= 255 for c in chain) and any(c < 255 for c in chain):
            seen.add("straddle:" + case.split(":")[0])
    assert {"link:empty", "link:head", "link:middle", "link:tail", "unlink:only", "unlink:head", "unlink:middle",
            "unlink:tail", "link:middle>=255", "link:tail>=255", "unlink:head>=255", "unlink:tail>=255",
            "unlink:only>=255", "straddle:link", "straddle:unlink"} <= seen, sorted(seen)


def test_the_wide_relink_follows_the_model_through_every_move(tmp_path):
    want = _relink_model()
    got = _relink_run(tmp_path, "relink")
    assert len(got) == len(OPS) == 20, len(got)
    for k, (g, w) in enumerate(zip(got, want)):
        assert g == w, "op %d %s: fj (sshead, thnext) parted from world.py" % (k, OPS[k])


RELINK_MUTS = {
    # the id's width back to 2 nibbles in both macros: 255 encodes as 0x00 (the end of a list)
    "nib2": [("        hex.inc 3, ll_enc\n", "        hex.inc 2, ll_enc\n", 2)],
    # the wide reads left narrow (read_byte at dbit+8: a cell past 0xFF is not decoded)
    "narrow": [("        hex.read_cell ll_nxt, ll_p\n", "        hex.read_byte ll_nxt, ll_p\n", 2)],
}


@pytest.mark.parametrize("mut", sorted(RELINK_MUTS))
def test_control_a_narrow_relink_is_caught(tmp_path, mut):
    """each control with its own symptom: nib2 runs every op and parts from the model at the first (255 encodes as
    0x00); narrow agrees until the first link read of a cell past 0xFF, where the 8-bit decoder cannot land -- the
    run stops there (a wild jump, the reason a wide cell must never be read narrow)"""
    want = _relink_model()
    got = _relink_run(tmp_path, "relink_" + mut, sim_mut=RELINK_MUTS[mut])
    if mut == "nib2":
        assert len(got) == len(OPS) and got[0] != want[0], (mut, len(got))
    else:
        assert 0 < len(got) < len(OPS) and got == want[:len(got)], (mut, len(got))


# ---- 2. the depth walk on rows 250 .. 262 ----------------------------------------------------------------------------
DEPTH_LEAVES = [(250,), (251, 256), (252, 255, 257), (253, 254, 258, 259), (260, 261, 262)]
DT = 263                                              # thpos_rt / thnext rows 0 .. 262; only 250 .. 262 are listed
DBINDS = [0] * DT
for _leaf, _ts in enumerate(DEPTH_LEAVES):
    for _t in _ts:
        DBINDS[_t] = _leaf
DPRESENT = [any(t in ts for ts in DEPTH_LEAVES) for t in range(DT)]
DN = 40
RK0S = (0, 0xFE, 0x102)
REGS = (("sp_x", 8), ("sp_y", 8), ("sp_z", 8), ("sp_left", 8), ("sp_w", 8), ("sp_hh", 8), ("sp_tzmax", 8),
        ("sp_tzmax2", 8), ("sp_mon", 2), ("sp_base", 4), ("sp_base2", 4), ("sp_dw", 2), ("sp_lt", 2))
REGS_EX = REGS + (("sp_ex", 1),)


def _depth_records(rk0):
    rnd = random.Random(0xF15 + rk0)
    out = []
    for k in range(DN):
        px, py = rnd.randint(-900, 2500), rnd.randint(-900, 2500)
        px16 = ((px << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        py16 = ((py << 16) | rnd.choice((0, 0x8000, rnd.randrange(1 << 16)))) & M32
        pos = {}
        for ts in DEPTH_LEAVES:
            for j, t in enumerate(ts):
                if k % 3 == 0 and j % 2 == 1:         # a tie: the previous thing mirrored about the player
                    qx, qy = pos[ts[j - 1]]
                    pos[t] = (2 * px - qx, 2 * py - qy)
                else:
                    pos[t] = (px + rnd.randint(-300, 300), py + rnd.randint(-300, 300))
        out.append((px16, py16, pos))
    return out


def _depth_key(rec, t, rk0):
    px16, py16, pos = rec
    if rk0:
        return rank_depth_key(px16, py16, *pos[t], 0 if t >= rk0 else 1)
    return aprox_depth_key(px16, py16, *pos[t])


def _depth_want(rec, rk0):
    return [sorted(ts, key=lambda t: _depth_key(rec, t, rk0)) for ts in DEPTH_LEAVES]


def _dist_leaf():
    lines = MC.p32a_leaves()
    return lines[:lines.index("mt_psec_leaf:")]


def _depth_prog(rk0):
    head, nxt = spawn_leaf_lists(DBINDS, len(DEPTH_LEAVES), present=DPRESENT, max_things=MAX)
    regs = REGS_EX if rk0 else REGS
    walk = list_macros(12)["depth"] + " throw, 1, thpos_rt, 0, 0, 0, 0" + (", %d, 1" % rk0 if rk0 else "")
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.zero 1, tstop"]
    for ts in DEPTH_LEAVES:
        for t in ts:
            body += ["hex.input 4, thpos_rt + %d*dw" % (16 * t), "hex.input 4, thpos_rt + %d*dw" % (16 * t + 8)]
    for leaf in range(len(DEPTH_LEAVES)):
        body += ["hex.set w/4, cur_ss, %d" % leaf, "hex.set w/4, cur_ssp, sshead + %d*dw" % leaf,
                 "stl.fcall tpd_leaf, tp_ret", "stl.output 124",
                 *["hex.print_as_digit %d, %s, 0" % (n, r) for r, n in regs], "stl.output 59"]
    body += ["stl.output 10", ";loop", "done:", "stl.loop",
             "tpd_leaf:", walk, "stl.fret tp_ret",
             "thing_leaf:", "hex.print_as_digit 3, sp_ti, 0", "stl.output 44",
             *["hex.set %d, %s, %d" % (n, r, 1 if r == "sp_ex" else int(("a5" * n)[:n], 16)) for r, n in regs],
             "stl.fret thing_ret",
             *_dist_leaf(),
             "throw:", *[";0"] * (17 * 16),
             byte_array_decl("sshead", head, len(DEPTH_LEAVES) + 1, bits=12),
             byte_array_decl("thnext", nxt, DT + 1, bits=12),
             "thpos_rt: hex.vec %d" % (16 * DT),
             "rmagic: hex.vec 2", "viewx: hex.vec 8", "viewy: hex.vec 8", "cur_ss: hex.vec w/4",
             "cur_ssp: hex.vec w/4", "tp_ret: ;0", "thing_ret: ;0", "tstop: hex.vec 1", "ss_flr: hex.vec 4",
             "sp_ti: hex.vec w/4",
             *["%s: hex.vec %d" % (r, n) for r, n in regs],
             *MC.p33_decls(MC.td_key_rows(DT)), *(MC.d3_decls(3)[:1] if rk0 else ()),
             "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
             "mt_t: hex.vec 4", "mt_ret: hex.vec w/4"]
    return "\n".join(body) + "\n"


def _depth_run(tmp, name, rk0, sim_mut=None):
    feed = b""
    for px16, py16, pos in _depth_records(rk0):
        feed += bytes([1]) + struct.pack("<II", px16, py16)
        for ts in DEPTH_LEAVES:
            for t in ts:
                x, y = pos[t]
                feed += struct.pack("<II", (x << 16) & M32, (y << 16) & M32)
    lines = _run(_assemble(tmp, name, _depth_prog(rk0), sim_mut=sim_mut), feed + bytes([0]))
    clear = "0" * sum(n for _, n in (REGS_EX if rk0 else REGS))
    order_bad, reg_bad, n = [], [], 0
    for k, (ln, rec) in enumerate(zip(lines, _depth_records(rk0))):
        parts = ln.split(";")
        if len(parts) < len(DEPTH_LEAVES):
            break
        n += 1
        for j, want in enumerate(_depth_want(rec, rk0)):
            order, _, regs = parts[j].partition("|")
            got = [int(v, 16) for v in order.split(",") if v]
            if got != want:
                order_bad.append((k, j, got, want))
            if regs != clear:
                reg_bad.append((k, j, regs))
    return n, order_bad, reg_bad


def test_the_depth_records_need_the_wide_rank():
    """the records are not vacuous: the rank moves the order at both thresholds, ties occur, and some row below
    0x102 has a low byte at or past 0x02 (a 2-nibble rank compare ranks it the other way)"""
    for rk0 in (0xFE, 0x102):
        recs = _depth_records(rk0)
        moved = sum(1 for r in recs for a, b in zip(_depth_want(r, rk0), _depth_want(r, 0)) if a != b)
        assert moved >= 10, (rk0, moved)
    assert any((t & 0xFF) >= (0x102 & 0xFF) and t < 0x102 for ts in DEPTH_LEAVES for t in ts)
    ties = sum(1 for r in _depth_records(0) for ts in DEPTH_LEAVES
               if len({_depth_key(r, t, 0) for t in ts}) < len(ts))
    assert ties >= 10, ties


@pytest.mark.parametrize("rk0", RK0S)
def test_the_wide_walk_draws_nearest_first(tmp_path, rk0):
    n, order_bad, reg_bad = _depth_run(tmp_path, "tpd%d" % rk0, rk0)
    assert n == DN, "%d of %d records" % (n, DN)
    assert not order_bad, "%d (record, leaf) parted, first %s" % (len(order_bad), order_bad[:3])
    assert not reg_bad, "%d (record, leaf) left registers dirty, first %s" % (len(reg_bad), reg_bad[:3])


DEPTH_MUTS = {
    # rank_key_w's compare at 2 nibbles: rows 0xFE / 0xFF against rk0 0x102 rank 0
    "rank2": [("        hex.cmp 3, td_t, td_rk, r1, r0, r0\n", "        hex.cmp 2, td_t, td_rk, r1, r0, r0\n", 1)],
    # td_rk set at 2 nibbles: 0x102 becomes 0x02 and every row but 0, 1 ranks 0
    "rk_set2": [("        rep(rk0>0, k) hex.set 3, td_rk, rk0\n", "        rep(rk0>0, k) hex.set 2, td_rk, rk0\n", 1)],
}


@pytest.mark.parametrize("mut", sorted(DEPTH_MUTS))
def test_control_a_narrow_rank_is_caught(tmp_path, mut):
    n, order_bad, reg_bad = _depth_run(tmp_path, "tpd_" + mut, 0x102, sim_mut=DEPTH_MUTS[mut])
    assert n == DN, "%s: %d of %d records -- the run broke instead of being caught" % (mut, n, DN)
    assert order_bad, "%s passed: the rank comparison is vacuous" % mut
    assert not reg_bad, "%s: registers dirty too -- not the symptom it plants" % mut


# ---- 3. the row select at ntm = 300 ---------------------------------------------------------------------------------
SEL_NTM = 300
SEL_IDS = (0, 15, 16, 255, 256, 271, 299, 300, 0x3FF, 0xFFF)


def _select_prog(sel):
    body = ["stl.startup_and_init_all"]
    for t in SEL_IDS:
        body += ["hex.set w/4, sp_ti, %d" % t, "stl.fcall thsel_leaf, thsel_ret", "stl.output 44"]
    body += ["stl.output 10", "stl.loop", *sel]
    for t in range(SEL_NTM):
        body += ["  thsel_s%d:" % t, "    hex.set w/4, sel_v, %d" % t, "    ;sel_print"]
    body += ["  thsel_none:", "    stl.output 45", "    stl.fret thsel_ret",
             "  sel_print:", "    hex.print_as_digit 3, sel_v, 0", "    stl.fret thsel_ret",
             "sp_ti: hex.vec w/4", "sel_v: hex.vec w/4", "thsel_ret: hex.vec w/4"]
    return "\n".join(body) + "\n"


def _select_run(tmp, name, sel):
    return _run(_assemble(tmp, name, _select_prog(sel), wide=False), b"")[0].split(",")[:len(SEL_IDS)]


def test_the_three_level_select_reaches_every_id(tmp_path):
    sel = MC.select_tree_lines(SEL_NTM)
    assert sel[1].startswith("    sim.jump16 sp_ti + 2*dw, thsel_g0, thsel_g1, thsel_none")
    got = _select_run(tmp_path, "sel", sel)
    assert got == ["%03x" % t if t < SEL_NTM else "-" for t in SEL_IDS], got


def test_control_the_select_without_its_third_level_is_caught(tmp_path):
    """select2: the nibble-2 level dropped (thsel_leaf goes straight to block 0) -- 256 prints 0"""
    sel = MC.select_tree_lines(SEL_NTM)
    sel = [sel[0], "    ;thsel_g0"] + sel[2:]
    got = _select_run(tmp_path, "sel2", sel)
    assert got[SEL_IDS.index(256)] == "000", got
    assert got != ["%03x" % t if t < SEL_NTM else "-" for t in SEL_IDS]


# ---- 4. the restart's list fragment at 12 bits ----------------------------------------------------------------------
RS_LEAVES, RS_NT = 4, 300
PLANT_HEAD = [0xFFF, 0x100, 0x0FF, 0x123]
PLANT_NEXT = [(0xFFF, 0x100, 0x0FF, 0x123, 0x801, 0x010)[t % 6] for t in range(RS_NT)]
RS_PRESENT = [t in (3, 77, 254, 255, 256, 299) or t % 37 == 5 for t in range(RS_NT)]


def _restart_want():
    return spawn_leaf_lists([t % RS_LEAVES for t in range(RS_NT)], RS_LEAVES, present=RS_PRESENT, max_things=MAX)


def _restart_prog(common, skill):
    return "\n".join(["stl.startup_and_init_all", *common, *skill,
                      "    stl.fcall dump_head, dump_ret", "    stl.fcall dump_next, dump_ret", "    stl.output 10",
                      "    stl.loop",
                      *_dump_loop("sshead", RS_LEAVES, "dump_head"), *_dump_loop("thnext", RS_NT, "dump_next"),
                      byte_array_decl("sshead", PLANT_HEAD, 2 * RS_LEAVES, bits=12),
                      byte_array_decl("thnext", PLANT_NEXT, 2 * RS_NT, bits=12),
                      "dump_ret: hex.vec w/4", "dmp_i: hex.vec w/4", "dmp_n: hex.vec w/4", *leaf_link_decls(3)]) + "\n"


def _restart_run(tmp, name, m1_mut=None, flip8=False):
    head, nxt = _restart_want()
    common, skills = list_restart_lines(RS_LEAVES, RS_NT, [(head, nxt, [])], 12)
    skill = skills[0]
    if flip8:                                     # the flips past bit 7 dropped
        skill = [ln for ln in skill if int(ln.split("+ dbit +")[1].strip(" ;")) < 8]
    ln = _run(_assemble(tmp, name, _restart_prog(common, skill), m1_mut=m1_mut), b"")[0]
    return _cells(ln, RS_LEAVES), _cells(ln[3 * RS_LEAVES:], RS_NT)


def test_the_planted_cells_and_lists_need_twelve_bits():
    head, nxt = _restart_want()
    assert max(head + nxt) > 0xFF and max(PLANT_HEAD + PLANT_NEXT) == 0xFFF
    common, skills = list_restart_lines(RS_LEAVES, RS_NT, [(head, nxt, [])], 12)
    assert common == ["    rep(%d, i) m1.zerocell12 sshead + i*dw" % RS_LEAVES,
                      "    rep(%d, i) m1.zerocell12 thnext + i*dw" % RS_NT]
    assert any("+ dbit + 8;" in ln for ln in skills[0])


def test_the_wide_restart_fragment_writes_the_level_start(tmp_path):
    head, nxt = _restart_want()
    assert _restart_run(tmp_path, "rs") == (tuple(head), tuple(nxt))


@pytest.mark.parametrize("mut", ("zero8", "flip8"))
def test_control_a_narrow_restart_is_caught(tmp_path, mut):
    head, nxt = _restart_want()
    m1 = ([("        hex.exact_xor c+dbit+11, c+dbit+10, c+dbit+9, c+dbit+8, hex.pointers.read_byte+2*dw\n", "", 1)]
          if mut == "zero8" else None)
    got = _restart_run(tmp_path, "rs_" + mut, m1_mut=m1, flip8=(mut == "flip8"))
    assert got != (tuple(head), tuple(nxt)), "%s: the narrowed restart wrote the level start anyway" % mut


# ---- 5. the drop link on rows >= 260 --------------------------------------------------------------------------------
DROP_NT = 250                                         # the WAD's runtime things: drop k is row 250 + 10 + k >= 260


def _drop_setup():
    w = World(monsters="full", sight_rule="seen", player="full")
    drops = BC.droppers(w)
    assert drops, "E1M1 has droppers"
    slot_rt = [3 * m for m in range(w.layout.nmon)]             # each monster slot's runtime thing (< DROP_NT)
    leaf = {m: 1 + m % 3 for m in drops}                         # the corpse's leaf (thss_rt of its runtime thing)
    first = DROP_NT + FIREBALL_POOL + FX_POOL
    assert first >= 256 and max(slot_rt) < DROP_NT
    return w, drops, slot_rt, leaf, first


def _drop_prog(drt2=False):
    w, drops, slot_rt, leaf, first = _drop_setup()
    nrow = first + len(drops)
    lines = BC.drop_lines(w, nt=DROP_NT, slot_rt=slot_rt, list_bits=12)
    if drt2:
        lines = [ln.replace("hex.set 3, dr_t,", "hex.set 2, dr_t,").replace("hex.mov 3, pw_t, dr_t",
                                                                             "hex.mov 2, pw_t, dr_t") for ln in lines]
    tic = PC.pool_tic_lines(list_bits=12)
    a, b = tic.index("pw_link:"), tic.index("pw_unlink:")
    relink = tic[a:a + 3] + tic[b:b + 3]
    assert relink[1] == "    sim.leaf_link_w pw_t, pw_leaf" and relink[4] == "    sim.leaf_unlink_w pw_t, pw_leaf"
    body = ["stl.startup_and_init_all"]
    for k, m in enumerate(drops):                  # every dropper dies (link), then the drops are taken in turn
        body += ["hex.set 4, dm_x, %d" % (100 + k), "hex.set 4, dm_y, %d" % (200 + k),
                 "stl.fcall drop_link%d, drl_ret" % k,
                 "stl.fcall dump_head, dump_ret", "stl.fcall dump_next, dump_ret", "stl.output 10"]
    for k in range(len(drops)):
        body += ["stl.fcall drop_take%d, drt_ret" % k,
                 "stl.fcall dump_head, dump_ret", "stl.fcall dump_next, dump_ret", "stl.output 10"]
    rt_leaf = {slot_rt[m]: leaf[m] for m in drops}
    body += ["stl.loop", *lines, *relink,
             *_dump_loop("sshead", 4, "dump_head"), *_dump_loop("thnext", nrow, "dump_next"),
             byte_array_decl("sshead", [0] * 4, 8, bits=12), byte_array_decl("thnext", [0] * nrow, 2 * nrow, bits=12),
             "thss_rt:", *["    hex.vec 16, %d" % rt_leaf.get(rt, 0) for rt in range(nrow)],
             "thpos_rt: hex.vec %d" % (16 * nrow),
             "mdrop: hex.vec %d" % len(drops), "dr_live: hex.vec 2", "dm_x: hex.vec 4", "dm_y: hex.vec 4",
             "dr_t: hex.vec 3", "dr_leaf: hex.vec 3", "pw_t: hex.vec w/4", "pw_leaf: hex.vec w/4",
             "drl_ret: hex.vec w/4", "drt_ret: hex.vec w/4", "pw_lkret: hex.vec w/4", "pw_ulret: hex.vec w/4",
             "dump_ret: hex.vec w/4", "dmp_i: hex.vec w/4", "dmp_n: hex.vec w/4", *leaf_link_decls(3)]
    return "\n".join(body) + "\n", nrow


def _drop_model():
    w, drops, slot_rt, leaf, first = _drop_setup()
    nrow = first + len(drops)
    fake = SimpleNamespace(ws=SimpleNamespace(leaf_head=[0] * 4, mob_next=[0] * nrow))
    out = []
    for k, m in enumerate(drops):
        World._list_insert(fake, first + k, leaf[m])
        out.append((tuple(fake.ws.leaf_head), tuple(fake.ws.mob_next)))
    for k, m in enumerate(drops):
        World._list_remove(fake, first + k, leaf[m])
        out.append((tuple(fake.ws.leaf_head), tuple(fake.ws.mob_next)))
    return out


def _drop_run(tmp, name, drt2=False):
    prog, nrow = _drop_prog(drt2)
    lines = _run(_assemble(tmp, name, prog), b"")
    return [(_cells(ln, 4), _cells(ln[12:], nrow)) for ln in lines if len(ln) >= 3 * (4 + nrow)]


def test_the_drop_link_relinks_rows_past_255(tmp_path):
    want = _drop_model()
    got = _drop_run(tmp_path, "drop")
    assert len(want) >= 4 and len(got) == len(want), (len(got), len(want))
    assert got == want, "the drop rows' links parted from the model"


def test_control_a_two_nibble_drop_row_is_caught(tmp_path):
    """drt2: dr_t back to 2 nibbles -- drop row 0x104 is linked as row 0x04"""
    got, want = _drop_run(tmp_path, "drop_drt2", drt2=True), _drop_model()
    assert len(got) == len(want) and got[0] != want[0], len(got)


# ---- the guard: a wide macro assembled without the dual table ---------------------------------------------------------
def test_a_wide_macro_without_the_wide_table_refuses_to_assemble(tmp_path):
    """without `-D hex.pointers.PTR_WIDE_BITS=12`, hex.read_cell would silently read 8 bits (PTR_WIDE falls back to
    PTR_CELL_BITS): the `_w` macros' and m1.zerocell12's guard makes it an assembly error that names the fix"""
    with pytest.raises(Exception) as e:
        _assemble(tmp_path, "noguard", _relink_prog(), wide=False)
    assert "LIST_WIDE__needs__D_hex_pointers_PTR_WIDE_BITS_12" in str(e.value) + "".join(
        str(a) for a in getattr(e.value, "args", ())), str(e.value)[:400]
    head, nxt = _restart_want()
    common, skills = list_restart_lines(RS_LEAVES, RS_NT, [(head, nxt, [])], 12)
    with pytest.raises(Exception) as e:
        _assemble(tmp_path, "noguard_rs", _restart_prog(common, skills[0]), wide=False)
    assert "zerocell12__needs__D_hex_pointers_PTR_WIDE_BITS_12" in str(e.value), str(e.value)[:400]
