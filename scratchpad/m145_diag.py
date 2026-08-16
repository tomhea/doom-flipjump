"""M14.5 — WHICH HALF MOVED THE PIXELS? No rebuild; reuses the cached --things binary.

`m145_check.py` proved the ORACLE's frame is byte-identical with and without the split, so the
25/29 px phase-1 divergence is the fj side. This narrows it to one of two things in two runs per
viewpoint, by using the visibility flag as an ABLATION:

  A. all baked things SHOWN   -> the frame the gate compared (differs)
  B. all baked things HIDDEN  -> the same fj program with the baked call sites skipped

If B is byte-exact against the oracle rendered with the same things hidden, then everything except
the baked drawing agrees, and the fault is IN the baked thing block (its constants, its leaf, its
light) -- not in the runtime table, the split of the wire, or the walk.

It also prints WHERE the pixels differ, because a sprite-shaped cluster and a scattered dusting are
different bugs.

    python scratchpad/m145_diag.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

# ⚠ m14_gate reads sys.argv AT IMPORT to decide whether the build takes a thing block. Without
# this the feed is 14 bytes, the program halts on the missing block after ~3k ops, and every
# comparison below reads a blank screen -- which is exactly what the first run of this script did.
sys.argv = [sys.argv[0], "--things"]
import m14_gate as G                                                      # noqa: E402
assert G.MOVING, "m14_gate did not arm the thing wire"

cfg = Config()
VIEW_W, VIEW_H = cfg.VIEW_W, cfg.VIEW_H
FJM = ROOT / "scratchpad/fjmcache/m14_bin_things.fjm"
print(f"binary {FJM.name} ({FJM.stat().st_size:,} bytes)")
print(f"{len(G.VIS)} vanishable baked slots; baked things = "
      f"{[i for i, b in enumerate(G.BAKED) if b]}")


def run(st, hidden=()):
    scr = StreamScreen(stdin=G.feed(st, 0, bindings=G.SPAWN_BINDINGS, hidden=hidden),
                       n_things=len(G.RT))
    term = fj.run(str(FJM), io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=1 << 26)
    return bytes(scr.pixel_indices), term.op_counter


def oracle(vp, hidden=()):
    from doomfj.reference_model import SimState
    return bytes(G.rm.render_wall_frame(SimState(vp[0] << 16, vp[1] << 16, vp[2], "E1M1"),
                                        G.scene, thing_hidden=list(hidden), **G.RENDER_KW))


def where(a, b):
    d = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if not d:
        return "none"
    cols = sorted({i % VIEW_W for i in d})
    rows = sorted({i // VIEW_W for i in d})
    return (f"{len(d)} px, x {cols[0]}..{cols[-1]} ({len(cols)} cols), "
            f"y {rows[0]}..{rows[-1]} ({len(rows)} rows)")


ALL = list(G.VIS)
for vp in G.VPS:
    st = (vp[0] << 16, vp[1] << 16, vp[2])
    shown, ops_s = run(st)
    hid, ops_h = run(st, ALL)
    print(f"\n({vp[0]},{vp[1]},{vp[2]:#x})")
    print(f"  A shown  {ops_s:,} ops   vs oracle: {where(shown, oracle(vp))}")
    print(f"  B hidden {ops_h:,} ops   vs oracle: {where(hid, oracle(vp, ALL))}")
    print(f"  A vs B (what the baked things drew): {where(shown, hid)}")
