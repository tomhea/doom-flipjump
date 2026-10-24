"""M8 C2 (docs/c2-slot-ids.md) -- THE SLOT-ID DISPATCH TREE past the byte, run in fj.

`monstercode.id_jump_lines` is the one tree every slot-id dispatch is built from (dm_go on dm_id, kb_go on kb_tg,
mt_load on mm_tg, dt_turn on p_atk, the wake tic on sched_cursor). At three nibbles (world.slot_nibbles 3: E1M6's
294 + 7 slots) it adds a level on nibble 2 first. This runs the tree at 300 targets over ids 0, 1, 15, 16, 255, 256,
257, 271, 299, 300, 0x3FF, 0xFFF: each id below 300 reaches its own stub and prints itself, every other id the `none`
exit. The narrow tree (two nibbles) is run too over 0 .. 255 at 254 targets, the narrow maps' text.

THE CONTROLS (R9): `two_level` (the nibble-2 level dropped: 256 lands on 0's stub) and `swap` (two 256-blocks'
labels swapped in the top level: 256 lands on 0 and 0 on 256) -- each must change the printed ids.
"""
from pathlib import Path

import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.config import Config
from doomfj.harness import W
from doomfj.monstercode import id_jump_lines

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N_WIDE = 300
IDS_WIDE = (0, 1, 15, 16, 255, 256, 257, 271, 299, 300, 0x3FF, 0xFFF)
N_NARROW = 254


def _tree(nib: int, n: int) -> list:
    return id_jump_lines("t_id", nib, n, lambda i: "t_s%d" % i, "t_none", "t_h%d", "t_g%d")


def _prog(nib: int, n: int, ids, tree) -> str:
    body = ["stl.startup_and_init_all"]
    for i in ids:
        body += ["hex.set %d, t_id, %d" % (nib, i), "stl.fcall t_go, t_ret", "stl.output 44"]
    body += ["stl.output 10", "stl.loop", "t_go:", *tree]
    for i in range(n):
        body += ["  t_s%d:" % i, "    hex.set 3, t_v, %d" % i, "    ;t_print"]
    body += ["  t_none:", "    stl.output 45", "    stl.fret t_ret",
             "  t_print:", "    hex.print_as_digit 3, t_v, 0", "    stl.fret t_ret",
             "t_id: hex.vec %d" % nib, "t_v: hex.vec 3", "t_ret: hex.vec w/4"]
    return "\n".join(body) + "\n"


def _run(tmp: Path, name: str, nib: int, n: int, ids, tree) -> list:
    src = tmp / (name + ".fj")
    src.write_text(_prog(nib, n, ids, tree), encoding="utf-8")
    out = tmp / (name + ".fjm")
    files = [Config().emit_fj_consts(tmp / "fj_consts.fj"), FJ / "sim.fj", src]
    fj.assemble([Path(f).resolve() for f in files], out, memory_width=W, print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode(errors="replace").split("\n")[0].split(",")[:len(ids)]


def _want(n: int, ids) -> list:
    return ["%03x" % i if i < n else "-" for i in ids]


def test_the_three_level_tree_reaches_every_id(tmp_path):
    tree = _tree(3, N_WIDE)
    assert tree[0].startswith("    sim.jump16 t_id + 2*dw, t_g0, t_g1, t_none"), tree[0]
    got = _run(tmp_path, "wide", 3, N_WIDE, IDS_WIDE, tree)
    assert got == _want(N_WIDE, IDS_WIDE), got


def test_the_two_level_tree_reaches_every_id(tmp_path):
    ids = tuple(range(256))
    got = _run(tmp_path, "narrow", 2, N_NARROW, ids, _tree(2, N_NARROW))
    assert got == _want(N_NARROW, ids), [g for g, w in zip(got, _want(N_NARROW, ids)) if g != w][:8]


def test_control_the_tree_without_its_third_level_is_caught(tmp_path):
    """two_level: nibble 2 never read -- every id goes straight to 256-block 0 (256 prints 000)"""
    tree = _tree(3, N_WIDE)
    tree = ["    ;t_g0"] + tree[1:]
    got = _run(tmp_path, "two_level", 3, N_WIDE, IDS_WIDE, tree)
    assert got[IDS_WIDE.index(256)] == "000" and got != _want(N_WIDE, IDS_WIDE), got


def test_control_a_swapped_256_block_is_caught(tmp_path):
    """swap: the top level's first two 256-blocks exchanged -- 0 reaches 256's stub, 256 reaches 0's"""
    tree = _tree(3, N_WIDE)
    tree[0] = tree[0].replace("t_g0, t_g1,", "t_g1, t_g0,")
    got = _run(tmp_path, "swap", 3, N_WIDE, IDS_WIDE, tree)
    assert got[IDS_WIDE.index(0)] == "100" and got[IDS_WIDE.index(256)] == "000", got
