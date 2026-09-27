"""M7 P1.3 -- the per-move relink IN FJ (`sim.leaf_link` / `sim.leaf_unlink`), against world.py.

The game tier bakes its per-leaf thing lists and keeps them (`things.spawn_leaf_lists`,
`build.THING_PERSIST`); a thing that changes leaf is unlinked from the old list and linked into the
new one, in ASCENDING order. `world.World._list_insert` / `_list_remove` are the model the gameplay
code runs (P3), so this drives the two macros through a scripted sequence of moves and requires the
arrays to equal the model's after EVERY op.

ONE image, every op in sequence (R5's call-twice rule): a macro that left a link or a head dirty
corrupts the NEXT op, which a fresh image per op could not see. The sequence covers linking into an
empty list, at the head, in the middle and at the tail; unlinking the head, a middle link, the tail
and a list's only element; and a round trip within one leaf.

⚠ THE CONTROL: two mutated macros -- a link that always prepends, an unlink that does not clear the
moved thing's link -- are assembled through the same harness and must disagree with the model.
"""
from pathlib import Path
from types import SimpleNamespace

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.config import Config
from doomfj.harness import W
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl, spawn_leaf_lists
from doomfj.world import World

SIM = Path("src/fj/sim.fj")
FIXP = Path("src/fj/fixed_point.fj")
NLEAVES, BINDS = 5, [2, 0, 2, 1, 2, 4, 0, 2]          # thing -> leaf, eight things on five leaves
NT = len(BINDS)
LINK, UNLINK = 1, 2
MOVES = [(2, 2, 3),    # a middle link out; into an EMPTY list
         (0, 2, 3),    # the head out; in at the head
         (7, 2, 3),    # the tail out; in at the tail
         (5, 4, 3),    # a list's ONLY element out; in the middle
         (3, 1, 0),    # the only element out; in the middle
         (6, 0, 4),    # the tail out; into an empty list
         (1, 0, 2),    # the head out; in at the head
         (4, 2, 2)]    # a round trip within one leaf
OPS = [op for t, old, new in MOVES for op in ((UNLINK, t, old), (LINK, t, new))]


def _model():
    """[(sshead, thnext) after each op] -- world.py's own list code on the baked spawn lists"""
    head, nxt = spawn_leaf_lists(BINDS, NLEAVES)
    fake = SimpleNamespace(ws=SimpleNamespace(leaf_head=list(head), mob_next=list(nxt)))
    out = []
    for op, t, leaf in OPS:
        (World._list_insert if op == LINK else World._list_remove)(fake, t, leaf)
        out.append((tuple(fake.ws.leaf_head), tuple(fake.ws.mob_next)))
    return out


def _dump():
    """print every sshead entry, then every thnext entry, as two hex digits each"""
    out = ["ll_dump:"]
    for label, n in (("sshead", NLEAVES), ("thnext", NT)):
        for i in range(n):
            out += [f"    hex.set w/4, ll_base, {label}", f"    hex.set w/4, ll_idx, {i}",
                    "    hex.ptr_index ll_p, ll_base, ll_idx", "    hex.read_byte ll_v, ll_p",
                    "    hex.print_as_digit 2, ll_v, 0"]
    return out + ["    stl.output 10", "    stl.fret dump_ret"]


def _assemble(tmp: Path, sim_text: str, name: str) -> Path:
    head, nxt = spawn_leaf_lists(BINDS, NLEAVES)
    prog = "\n".join([
        "stl.startup_and_init_all",
        "loop:",
        "    hex.input 1, rmagic",
        "    hex.if0 2, rmagic, done",
        "    hex.input 1, rop",
        "    hex.zero w/4, rt", "    hex.input 1, rt",
        "    hex.zero w/4, rl", "    hex.input 1, rl",
        f"    hex.xor_by 1, rop, {LINK}",               # rop == LINK -> 0
        "    hex.if0 1, rop, do_link",
        "    sim.leaf_unlink rt, rl",
        "    ;op_done",
        "  do_link:",
        "    sim.leaf_link rt, rl",
        "  op_done:",
        "    stl.fcall ll_dump, dump_ret",
        "    ;loop",
        "done:",
        "    stl.loop",
        *_dump(),
        byte_array_decl("sshead", head, 2 * NLEAVES),
        byte_array_decl("thnext", nxt, 2 * NT),
        "rmagic: hex.vec 2", "rop: hex.vec 2", "rt: hex.vec w/4", "rl: hex.vec w/4",
        "dump_ret: hex.vec w/4",
        *LEAF_LINK_DECLS,
    ]) + "\n"
    src = tmp / f"{name}.fj"
    src.write_text(prog, encoding="utf-8")
    sim = tmp / f"{name}_sim.fj"
    sim.write_text(sim_text, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")          # sim.fj's pad constants
    out = tmp / f"{name}.fjm"
    fj.assemble([consts.resolve(), FIXP.resolve(), sim.resolve(), src.resolve()], out,
                memory_width=W, print_time=False)
    return out


def _run(fjm: Path):
    feed = b"".join(bytes([0xD0, op, t, leaf]) for op, t, leaf in OPS) + b"\x00"
    io = FixedIO(feed)
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    lines = io.get_output(allow_incomplete_output=True).decode().split("\n")
    got = []
    for ln in lines[:len(OPS)]:
        vals = [int(ln[2 * i:2 * i + 2], 16) for i in range(NLEAVES + NT)]
        got.append((tuple(vals[:NLEAVES]), tuple(vals[NLEAVES:])))
    return got


@pytest.fixture(scope="module")
def sim_text():
    return SIM.read_text(encoding="utf-8")


def test_the_relink_follows_the_model_through_every_move(tmp_path, sim_text):
    want = _model()
    got = _run(_assemble(tmp_path, sim_text, "relink"))
    for k, (g, w) in enumerate(zip(got, want)):
        assert g == w, f"op {k} {OPS[k]}: fj (sshead, thnext) {g} != world.py {w}"
    assert len(got) == len(OPS) == 16
    # the sequence really visits every case the docstring claims, classified from the MODEL's own
    # state before each op (so a harmless-looking reorder of MOVES cannot quietly drop one)
    head, nxt = spawn_leaf_lists(BINDS, NLEAVES)
    before = [(tuple(head), tuple(nxt))] + want[:-1]
    seen = set()
    for (op, t, leaf), (h, n) in zip(OPS, before):
        chain = []
        cur = h[leaf]
        while cur:
            chain.append(cur - 1)
            cur = n[cur - 1]
        if op == LINK:
            seen.add("link:empty" if not chain else "link:head" if t < chain[0] else
                     "link:tail" if t > chain[-1] else "link:middle")
        else:
            seen.add("unlink:only" if chain == [t] else "unlink:head" if chain[0] == t else
                     "unlink:tail" if chain[-1] == t else "unlink:middle")
    assert seen == {"link:empty", "link:head", "link:middle", "link:tail", "unlink:only",
                    "unlink:head", "unlink:middle", "unlink:tail"}, sorted(seen)


@pytest.mark.parametrize("name,old,new", [
    ("always prepends", "        hex.cmp 2, ll_v, ll_enc, scan, scan, at_head     // cur > enc: t goes first",
     "        hex.cmp 2, ll_v, ll_enc, at_head, at_head, at_head"),
    ("the moved thing keeps its link", "      head:                                    // sshead[leaf] = thnext[t];  thnext[t] = 0\n"
     "        hex.set w/4, ll_base, thnext\n        hex.ptr_index ll_q, ll_base, t\n"
     "        hex.read_byte ll_nxt, ll_q\n        hex.write_byte ll_p, ll_nxt\n        hex.zero 2, ll_nxt\n"
     "        hex.write_byte ll_q, ll_nxt\n",
     "      head:\n        hex.set w/4, ll_base, thnext\n        hex.ptr_index ll_q, ll_base, t\n"
     "        hex.read_byte ll_nxt, ll_q\n        hex.write_byte ll_p, ll_nxt\n"),
])
def test_a_broken_relink_is_caught(tmp_path, sim_text, name, old, new):
    """R9: the same harness must SAY NO to a relink that is wrong in a way a picture could miss."""
    assert sim_text.count(old) == 1, f"{name}: the mutation no longer matches src/fj/sim.fj"
    got = _run(_assemble(tmp_path, sim_text.replace(old, new), "mutant"))
    assert got != _model(), f"{name}: the mutated relink agreed with the model on every op"
