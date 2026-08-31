"""`lut_generator.generate_bands_walk_fj` — the baked band-list walker, tested at the KERNEL level.

It had no test at all. It emits ~78% of the shipped program's text (the `vpb_*` families are 86% of
the banks part, which is 90% of the emission), and the only thing that ever checked it was a
20-minute whole-frame gate. So the M4 change that shares the clamp tail per colour — 12.7% of the
span — would have been proven by nothing cheaper than deg_gate.

THE CONTRACT, read off the two `_cmp3_tree` calls and mirrored in `walk()` below. For each
`[y2, colour]` pair of the list, in order:

  * `y2 <= vq_lo`            skip it (the window starts at or after this band's end)
  * `vq_lo < y2 <  vq_hi`    emit [y2][colour], continue
  * `y2 == vq_hi`            emit [y2][colour] and STOP
  * `y2 >  vq_hi`            emit [vq_hi][colour] and STOP   <- the CLAMP arm, the shared one

`vq_hi` is EXCLUSIVE-bounded in the caller's sense but compared for equality here, so the `==`
case is its own arm and is tested on its own.
"""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_bands_walk_fj

# four lists that between them reach every arm, including two that are BIT-IDENTICAL so the
# handler-sharing path (`owner[k] != k`) is exercised too.
LISTS = [
    [(10, 0x11), (20, 0x22), (30, 0x33)],
    [(10, 0x11), (20, 0x22), (30, 0x33)],      # identical to list 0 -> shares its body
    [(5, 0xAA)],
    [(8, 0x01), (200, 0x02)],
]


def walk(pairs, lo, hi):
    """The oracle: the contract above, in twelve lines."""
    out = bytearray()
    for y2, c in pairs:
        if y2 <= lo:
            continue
        if y2 < hi:
            out += bytes([y2, c])
        elif y2 == hi:
            out += bytes([y2, c])
            break
        else:
            out += bytes([hi, c])
            break
    return bytes(out)


def _run(tmp_path, idx, lo, hi, expected):
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    prog = "\n".join([
        "stl.startup_and_init_all",
        generate_bands_walk_fj(LISTS),
        f"    hex.set 2, tqlo, {lo}",
        f"    hex.set 2, tqhi, {hi}",
        "    vql_load tqlo",
        "    vqh_load tqhi",
        f"    hex.set 4, twid, {idx}",
        "    vpb_walk twid",
        "    stl.loop",
        "tqlo: hex.vec 2",
        "tqhi: hex.vec 2",
        "twid: hex.vec 4",
        "",
    ])
    p = tmp_path / "bands.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [consts.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"list {idx} window [{lo},{hi}): output != {expected!r}"


@pytest.mark.parametrize("idx,lo,hi", [
    (0, 0, 255),      # whole list, nothing clamped
    (0, 0, 30),       # the == arm: the last pair ends exactly at vq_hi
    (0, 0, 25),       # the CLAMP arm: 30 > 25 -> emit [25][0x33] and stop
    (0, 10, 255),     # the skip arm: y2 == vq_lo is skipped
    (0, 19, 255),     # skip one, keep the rest
    (1, 0, 25),       # the SHARED-body list, clamped
    (2, 0, 255),      # a one-pair list
    (2, 5, 255),      # ... whose only pair is skipped: empty output
    (3, 0, 100),      # clamp far below the pair's own y2
    (3, 8, 200),      # skip then hit the == arm
])
def test_walk_matches_the_contract(tmp_path, idx, lo, hi):
    _run(tmp_path, idx, lo, hi, walk(LISTS[idx], lo, hi))


def test_identical_lists_share_one_body(tmp_path):
    """`owner` dedup: lists 0 and 1 are equal, so exactly one `vpb_body` exists for the pair."""
    src = generate_bands_walk_fj(LISTS)
    bodies = [l for l in src.splitlines() if l.startswith("vpb_body")]
    assert len(bodies) == 3, bodies          # lists 0/1 share, 2 and 3 are their own


def test_the_clamp_tail_is_shared_per_colour(tmp_path):
    """M4: one `vpb_cl_<c>` per DISTINCT clamp colour, and every clamp arm is a single jump into
    it. The negative control for the size claim -- if the tails were re-inlined this count would
    track the pair count instead of the colour count."""
    src = generate_bands_walk_fj(LISTS).splitlines()
    tails = [l for l in src if l.startswith("vpb_cl_")]
    colours = {c for pairs in LISTS for _y2, c in pairs}
    assert len(tails) == len(colours), (tails, colours)
    # ... and no pair inlines a raw-byte chain any more
    assert not [l for l in src if "_rb_z0:" in l]
