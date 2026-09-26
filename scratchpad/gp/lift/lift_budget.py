"""S7 lift spike -- plane ids, viewz classes, band lists and per-state seg blocks for the MOVING FLOORS
(lifts 98/103, the floor switch 76/126/129), priced the way M2 priced doors. No build, no render:
map data plus the emitter's OWN pure functions (`_band_pair_lists`, `_sky_pair_lists`,
`seg_marks_in`, `doors.door_states`, `apply_sector_heights`, `rm.v5_side_modes`).

    python scratchpad/gp/lift/lift_budget.py [--fast]

CONTROL FIRST. The emitter's pid registry and viewz classes are rebuilt with the emitter's own rules
(`_seg_in_walk`, `_seg_secs`, the V5 back-pair registration) and MUST reproduce what the SHIPPED
program says about itself -- 222 pids (skypid has 223 entries), 43,392 half-lists, 9,015 unique --
read from build/generated_doom_e1m1_blocked27/. If the control does not reproduce, the projections
are not printed. Every projection is a DELTA on that reproduced base.

Word costs per unit are MEASURED from the shipped label table by label_sizes.py (same directory):
8.0 words per half-list id (thunk), 44.0 per unique body, 336 per distinct pair block, 81.8 per
per-state seg block, 253 per state switch.
"""
import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config                                          # noqa: E402
from doomfj.doors import door_states, stops                               # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import ReferenceModel, apply_sector_heights   # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import _band_pair_lists, _sky_pair_lists, seg_marks_in  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--gen", default="build/generated_doom_e1m1_blocked27")
ap.add_argument("--fast", action="store_true", help="skip the band-body projection (minutes)")
args = ap.parse_args()

W_ID, W_BODY, W_PB, W_BLK, W_SW = 8.0, 44.0, 336.0, 81.8, 253.0   # MEASURED, label_sizes.py
MAX_STATES, PID_CAP = 16, 255

cfg = Config(); rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))   # map AND asset wad (E1M1)
M = "E1M1"
secs, lds, sds = mw.sectors(M), mw.linedefs(M), mw.sidedefs(M)
cmap = bake_bsp(mw, M)
_fb = {}


def flatval(name):
    return rm._flat_base(mw, name, _fb)                      # the emitter's _flatval, verbatim


def plane_keys(sec):
    return ((sec.ceil_h, sec.light & 0xFF, flatval(sec.ceil_tex), sec.ceil_tex.upper()),
            (sec.floor_h, sec.light & 0xFF, flatval(sec.floor_tex), sec.floor_tex.upper()))


def sides(seg):
    ld = lds[seg.linedef]
    f = sds[ld.front if seg.side == 0 else ld.back].sector
    b = sds[ld.back if seg.side == 0 else ld.front].sector if ld.back != -1 else None
    return f, b


nb = {}
for ld in lds:
    f = sds[ld.front].sector if ld.front != 0xFFFF and ld.front < len(sds) else None
    b = sds[ld.back].sector if ld.back != 0xFFFF and ld.back < len(sds) else None
    if f is not None and b is not None and f != b:
        nb.setdefault(f, set()).add(b); nb.setdefault(b, set()).add(f)


def lowest_surrounding(si):                                    # P_FindLowestFloorSurrounding
    return min([secs[n].floor_h for n in nb.get(si, ())] + [secs[si].floor_h])


# ---- the shipped program's own numbers (ground truth) -----------------------------------------
gen = ROOT / args.gen
tables = (gen / "e1m1_01_tables.fj").read_text(encoding="utf-8", errors="replace")
banks_head = (gen / "e1m1_06_banks.fj").read_text(encoding="utf-8", errors="replace")
SHIP_PIDS = int(re.search(r'dispatch table "skypid": (\d+) entries', tables).group(1)) - 1
m = re.search(r"bands-as-code: (\d+) half-lists \((\d+) unique, pad (\d+)\)", banks_head)
SHIP_LISTS, SHIP_UNIQ, SHIP_PAD = (int(g) for g in m.groups())
print("SHIPPED (%s): %d pids, %d half-lists, %d unique, pad %d" % (args.gen, SHIP_PIDS, SHIP_LISTS,
                                                                  SHIP_UNIQ, SHIP_PAD))

# ---- the emitter's registry, rebuilt with the emitter's rules ----------------------------------
DOORS = door_states(secs, lds, sds, 16)                        # {sector: [shut .. open]}


def door_secs_list():
    dmax = max(len(v) for v in DOORS.values())
    return [apply_sector_heights(secs, {si: (secs[si].floor_h, st[min(k, len(st) - 1)])
                                        for si, st in DOORS.items()}) for k in range(dmax)]


DSECS = door_secs_list()


def registry(movers):
    """(pids, keys-in-bank-order, vz classes) with `movers` = {sector: [(floor, ceil) per state]}
    added the way `_seg_secs` adds door states: a seg touching a mover bakes one block per state."""
    mmax = max([len(v) for v in movers.values()] + [1])
    msecs = [apply_sector_heights(secs, {si: st[min(k, len(st) - 1)] for si, st in movers.items()})
             for k in range(mmax)]

    def seg_secs(seg):
        f, b = sides(seg)
        if f in DOORS or (b is not None and b in DOORS):
            d = f if f in DOORS else b
            return DSECS[:len(DOORS[d])]
        if f in movers or (b is not None and b in movers):
            mv = f if f in movers else b
            return msecs[:len(movers[mv])]
        return [secs]

    def touched(seg):
        f, b = sides(seg)
        return f in DOORS or f in movers or (b is not None and (b in DOORS or b in movers))

    def closed_static(seg):
        ld = lds[seg.linedef]
        if ld.back == -1 or touched(seg):
            return False
        f, b = sides(seg)
        return min(secs[f].ceil_h, secs[b].ceil_h) <= max(secs[f].floor_h, secs[b].floor_h)

    def in_walk(seg):
        ld = lds[seg.linedef]
        return (ld.back == -1 or closed_static(seg)
                or any(seg_marks_in(lds, sds, seg, sv) for sv in seg_secs(seg)))
    pids = {}
    for seg in cmap.segs:
        if not in_walk(seg):
            continue
        for sv in seg_secs(seg):
            pids.setdefault(plane_keys(rm._seg_sector(lds, sds, sv, seg)), len(pids) + 1)
            if lds[seg.linedef].back != -1:                       # V5 back pair (stack_flag)
                pids.setdefault(plane_keys(sv[sides(seg)[1]]), len(pids) + 1)
    vz = {}
    for ss in cmap.subsectors:
        vz.setdefault(rm.view_z(rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg]).floor_h), len(vz))
    for si, st in movers.items():                                # the eye can ride a mover
        for (fl, ce) in st:
            if ce - fl >= 56:
                vz.setdefault(rm.view_z(fl), len(vz))
    keys = [k for pair in pids for k in pair]
    return pids, keys, vz, seg_secs, in_walk


t0 = time.perf_counter()
base_pids, base_keys, base_vz, _, base_in_walk = registry({})
n_sky = len(_sky_pair_lists(rm, mw, cfg))
base_lists_n = len(base_vz) * len(base_keys) * 2 + n_sky
print("CONTROL registry: %d pids (shipped %d), %d viewz classes, %d half-lists (shipped %d), sky %d"
      % (len(base_pids), SHIP_PIDS, len(base_vz), base_lists_n, SHIP_LISTS, n_sky))
ok = (len(base_pids) == SHIP_PIDS and base_lists_n == SHIP_LISTS)
print("CONTROL: %s" % ("REPRODUCED" if ok else "!! DOES NOT REPRODUCE -- projections withheld"))
if not ok:
    sys.exit(1)

# ---- the movers --------------------------------------------------------------------------------
LIFTS = (98, 103)
FSWITCH = (76, 126, 129)


def mover_table(lift_q, fs_mode):
    """{sector: [(floor, ceil) per state]}, state 0 = the STORED (up) position, like a door's shut."""
    out = {}
    for si in LIFTS:
        lo, hi = lowest_surrounding(si), secs[si].floor_h
        out[si] = [(h, secs[si].ceil_h) for h in reversed(stops(lo, hi, lift_q))]
    for si in FSWITCH:
        lo, hi = lowest_surrounding(si), secs[si].floor_h
        hs = [hi, lo] if fs_mode == "instant" else list(reversed(stops(lo, hi, fs_mode)))
        out[si] = [(h, secs[si].ceil_h) for h in hs]
    return out


print("\nMOVERS (state 0 = stored/up; lowest surrounding floor = DOOM's low/dest):")
for si in LIFTS + FSWITCH:
    lo, hi = lowest_surrounding(si), secs[si].floor_h
    print("  sector %3d %-12s floor %4d -> %4d (travel %3d) ceil %4d; stops at quant 8/12/16/24/32: %s"
          % (si, "lift" if si in LIFTS else "floor switch", hi, lo, hi - lo, secs[si].ceil_h,
             "/".join(str(len(stops(lo, hi, q))) for q in (8, 12, 16, 24, 32))))

# segs / leaves / lines per mover, and the one-dimensional-switch assumption
print("\nSEGS, LEAVES, LINES per mover (door machinery: one nibble switch per seg, one mover per seg):")
bad = []
for si in LIFTS + FSWITCH:
    own = [i for i, s in enumerate(cmap.segs) if sides(s)[0] == si]
    look = [i for i, s in enumerate(cmap.segs) if sides(s)[1] == si]
    leaves = [k for k, ss in enumerate(cmap.subsectors)
              if ss.numsegs and sides(cmap.segs[ss.firstseg])[0] == si]
    lines = sorted({s.linedef for s in (cmap.segs[i] for i in own + look)})
    for i in own + look:
        f, b = sides(cmap.segs[i])
        other = b if f == si else f
        if other is not None and (other in DOORS or other in LIFTS + FSWITCH):
            bad.append((i, f, b))
    print("  sector %3d: own segs %2d, looking-at segs %2d, leaves %d, lines %2d %s"
          % (si, len(own), len(look), len(leaves), len(lines), lines))
print("  segs with a door or another mover on the OTHER side (need a 2-D switch): %d %s"
      % (len(bad), bad[:6]))


def closed_states(seg, tbl):
    f, b = sides(seg)
    if b is None:
        return None
    mv = f if f in tbl else b
    out = []
    for k, st in enumerate(tbl[mv]):
        sv = apply_sector_heights(secs, {mv: st})
        if min(sv[f].ceil_h, sv[b].ceil_h) <= max(sv[f].floor_h, sv[b].floor_h):
            out.append(k)
    return out


def seg_units(tbl, seg_secs, in_walk):
    """per-state block units a mover seg carries, by the emitter's block kinds (MEASURED on doors:
    render_consts on every touched seg that reaches the solid body, attrib + face on marking segs)."""
    render = attrib = face = 0
    blocks = 0
    odd_gate = []
    for i, seg in enumerate(cmap.segs):
        f, b = sides(seg)
        mv = f if f in tbl else (b if b is not None and b in tbl else None)
        if mv is None or not in_walk(seg):
            continue
        n = len(tbl[mv])
        ld = lds[seg.linedef]
        cs = closed_states(seg, tbl)
        dual = ld.back != -1 and bool(cs) and len(cs) < n
        if dual and cs != list(range(len(cs))):
            odd_gate.append((i, cs))                       # closed somewhere other than a prefix
        if ld.back == -1 or dual:
            render += 1
            blocks += n
        if ld.back != -1 and any(seg_marks_in(lds, sds, seg, sv) for sv in seg_secs(seg)):
            attrib += 1
            blocks += n
            um = lm = 0
            for sv in seg_secs(seg):
                a_, c_ = rm.v5_side_modes(sv[f], sv[b], True)
                um, lm = um or a_, lm or c_
            if um or lm:
                face += 1
                blocks += n
    return render, attrib, face, blocks, odd_gate


# ---- projections -------------------------------------------------------------------------------
base_uniq = None
base_pairs = None
if not args.fast:
    t = time.perf_counter()
    bl = _band_pair_lists(rm, cfg, mw, base_vz, base_keys, True) + _sky_pair_lists(rm, mw, cfg)
    base_uniq = {tuple(map(tuple, p)) for p in bl}
    base_pairs = {pr for p in base_uniq for pr in p}
    print("\nCONTROL bodies: %d unique (shipped %d), %d distinct (y2, colour) pair blocks, %.0f s"
          % (len(base_uniq), SHIP_UNIQ, len(base_pairs), time.perf_counter() - t))
    if len(base_uniq) != SHIP_UNIQ:
        print("  !! unique count does not reproduce -- body/word projections are UNVERIFIED")

CONFIGS = [("lifts q16, switch instant", 16, "instant"),
           ("lifts q32, switch instant", 32, "instant"),
           ("lifts q16, switch q32", 16, 32),
           ("lifts q16, switch q16", 16, 16)]
print("\nPROJECTIONS (deltas on the reproduced base):")
for name, lq, fsm in CONFIGS:
    tbl = mover_table(lq, fsm)
    states_ok = all(len(v) <= MAX_STATES for v in tbl.values())
    pids, keys, vz, seg_secs, in_walk = registry(tbl)
    npid, nvz = len(pids) - len(base_pids), len(vz) - len(base_vz)
    lists_n = len(vz) * len(keys) * 2 + n_sky
    pad = 1 << max(1, (lists_n - 1).bit_length())
    r, a, fc, blocks, odd = seg_units(tbl, seg_secs, in_walk)
    units = r + a + fc
    words_blk = blocks * W_BLK + units * W_SW
    print("  %-28s states %s%s" % (name, {k: len(v) for k, v in tbl.items()},
                                     "" if states_ok else "  !! > 16 states: not one nibble"))
    print("      pids %d (+%d) -> %s;  viewz classes %d (+%d);  half-lists %d (+%d), pad %d%s"
          % (len(pids), npid, "FITS the byte" if len(pids) <= PID_CAP else "OVER 255: needs PID_NIBBLES 3/4",
             len(vz), nvz, lists_n, lists_n - base_lists_n, pad,
             "" if pad <= SHIP_PAD else "  (BAND_NIBBLES 5, pad doubles)"))
    print("      per-state seg blocks: %d units (render %d, attrib %d, face %d), %d blocks -> ~%.0fK words"
          " (MEASURED per-unit door costs)%s" % (units, r, a, fc, blocks, words_blk / 1e3,
                                                 "" if not odd else "  !! closed in a non-prefix of states: %s" % odd[:3]))
    words = (lists_n - base_lists_n) * W_ID + max(0, pad - SHIP_PAD) * 2
    if base_uniq is not None:
        t = time.perf_counter()
        new_vz = {v: i for v, i in vz.items() if v not in base_vz}
        bk = set(base_keys)
        new_keys = [k for k in dict.fromkeys(keys) if k not in bk]
        lists = []
        if new_vz:
            lists += _band_pair_lists(rm, cfg, mw, new_vz, list(dict.fromkeys(keys)), True)
        if new_keys:
            lists += _band_pair_lists(rm, cfg, mw, base_vz, new_keys, True)
        uniq = base_uniq | {tuple(map(tuple, p)) for p in lists}
        pairs = {pr for p in uniq for pr in p}
        nb_, np_ = len(uniq) - len(base_uniq), len(pairs) - len(base_pairs)
        words += nb_ * W_BODY + np_ * W_PB
        print("      band bodies +%d (+%.1f%%), pair blocks +%d, %.0f s" % (
            nb_, 100.0 * nb_ / len(base_uniq), np_, time.perf_counter() - t))
    print("      WORDS (bank ids%s + seg blocks): ~%.0fK = %.3f%% of 2^27" % (
        " + bodies + pair blocks" if base_uniq is not None else "", (words + words_blk) / 1e3,
        100.0 * (words + words_blk) / (1 << 27)))
print("\ntotal %.0f s" % (time.perf_counter() - t0))
