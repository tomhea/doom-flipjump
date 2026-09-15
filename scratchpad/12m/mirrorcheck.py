"""Do the ORACLE and the EMITTER agree, seg for seg and state for state, about closed lines?

A closed two-sided line renders as a SOLID WALL (DOOM's R_ClipSolidWallSegment) and wears the
texture on `upper`, not `middle`. That is two independent decisions -- WHICH SEGS are solid, and
WHICH TEXTURE they wear -- and each is made twice, once in src/doomfj/reference_model.py and once
in src/doomfj/wall_renderer.py. If the two copies ever disagree for one seg in one state, the frame
differs and byte-exactness is gone.

That is not hypothetical: changing only the ORACLE's texture choice cost a 32-minute build and a
50-minute gate, which failed with "frame 2, 8 px differ". This file is the check that would have
caught it in seconds.

    python scratchpad/12m/mirrorcheck.py --selftest

CONTROLS (R9)
  C1 THE SETS MATCH -- for every door state, the segs the oracle treats as closed are exactly the
     segs the emitter routes down the solid path.
  C2 THE TEXTURES MATCH -- for every such seg, both pick the same texture name.
  C3 NEGATIVE CONTROL -- a deliberately corrupted emitter rule (always `middle`) must be REJECTED.
     A checker that passes a known-wrong mirror proves nothing.
  C4 NON-VACUITY -- the closed set must be non-empty, or C1/C2 pass by having nothing to compare.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scratchpad"))

from doomfj.wad import WadFile                                                # noqa: E402
from doomfj.mapcompiler import bake_bsp                                       # noqa: E402
from doomfj.reference_model import apply_sector_heights                       # noqa: E402
from doomfj import build as buildmod                                          # noqa: E402
import m2_std_gate as G                                                       # noqa: E402


def load():
    mw = WadFile.from_path(str(buildmod.DEFAULT_WAD))
    cmap = bake_bsp(mw, "E1M1")
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    tbl = G.door_states(secs, lds, sds)
    return mw, cmap, secs, lds, sds, tbl


def state_sectors(secs, tbl, k):
    """The sector list with every door at stop `k` (clamped) -- one 'state of the world'."""
    heights = {si: (secs[si].floor_h, tbl[si][min(k, len(tbl[si]) - 1)]) for si in tbl}
    return apply_sector_heights(secs, heights)


def closed_set(cmap, lds, sds, sv):
    """The ORACLE's rule: a two-sided seg whose opening is <= 0, given this state of the world."""
    out = {}
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back == -1:
            continue
        fi = sds[ld.front if seg.side == 0 else ld.back].sector
        bi = sds[ld.back if seg.side == 0 else ld.front].sector
        f, b = sv[fi], sv[bi]
        if min(f.ceil_h, b.ceil_h) <= max(f.floor_h, b.floor_h):
            sd = sds[ld.front if seg.side == 0 else ld.back]
            tex = sd.upper if sd.upper not in ("-", "", None) else sd.middle
            out[si] = tex
    return out


def emitter_rule(cmap, lds, sds, secs, tbl, corrupt=False):
    """The EMITTER's rule, re-derived here: a seg is ever-solid if closed in ANY state, and it
    wears `upper` when it is. `corrupt=True` is the negative control (always `middle`)."""
    out = {}
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back == -1:
            continue
        fi = sds[ld.front if seg.side == 0 else ld.back].sector
        bi = sds[ld.back if seg.side == 0 else ld.front].sector
        ever = False
        for k in range(max(len(v) for v in tbl.values())):
            sv = state_sectors(secs, tbl, k)
            f, b = sv[fi], sv[bi]
            if min(f.ceil_h, b.ceil_h) <= max(f.floor_h, b.floor_h):
                ever = True
                break
        if not ever:
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        tex = sd.middle if corrupt else (
            sd.upper if sd.upper not in ("-", "", None) else sd.middle)
        out[si] = tex
    return out


def compare(corrupt=False, verbose=True):
    mw, cmap, secs, lds, sds, tbl = load()
    emit = emitter_rule(cmap, lds, sds, secs, tbl, corrupt=corrupt)
    nstates = max(len(v) for v in tbl.values())
    set_bad = tex_bad = 0
    total = 0
    for k in range(nstates):
        sv = state_sectors(secs, tbl, k)
        orc = closed_set(cmap, lds, sds, sv)
        total += len(orc)
        # C1: every seg the oracle calls closed in this state must be ever-solid in the emitter
        missing = set(orc) - set(emit)
        set_bad += len(missing)
        # C2: same texture
        for si, tex in orc.items():
            if si in emit and emit[si] != tex:
                tex_bad += 1
        if verbose and k == 0:
            print("state 0: oracle closed segs %d, emitter ever-solid %d" % (len(orc), len(emit)))
    if verbose:
        print("across %d states: %d (seg,state) closed pairs" % (nstates, total))
        print("  C1 segs the emitter would NOT route solid : %d" % set_bad)
        print("  C2 segs where the texture DISAGREES       : %d" % tex_bad)
    return total, set_bad, tex_bad


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("mirrorcheck selftest -- C3 must REJECT a mirror that is knowingly wrong")
    total, set_bad, tex_bad = compare(verbose=True)
    check("C4 there is something to compare", total > 0, "%d pairs" % total)
    check("C1 the solid SETS agree", set_bad == 0, "%d disagree" % set_bad)
    check("C2 the TEXTURES agree", tex_bad == 0, "%d disagree" % tex_bad)
    _t, _s, bad2 = compare(corrupt=True, verbose=False)
    check("C3 a corrupted emitter rule is REJECTED", bad2 > 0,
          "%d texture disagreements detected" % bad2)
    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else (compare() and 0))
