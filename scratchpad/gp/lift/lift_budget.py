"""S7 lift spike -- plane ids, viewz classes, band lists and per-state seg blocks for the MOVING FLOORS
(lifts 98/103, the floor switch 76/126/129), priced the way M2 priced doors. No build, no render:
map data plus the emitter's OWN pure functions (`_band_pair_lists`, `_sky_pair_lists`,
`seg_marks_in`, `doors.door_states`, `apply_sector_heights`, `rm.v5_side_modes`).

    python scratchpad/gp/lift/lift_budget.py [--fast]
    python scratchpad/gp/lift/lift_budget.py --selftest [--fast]      # R9: the controls have teeth

CONTROL FIRST. The emitter's pid registry and viewz classes are rebuilt with the emitter's own rules
(`_seg_in_walk`, `_seg_secs`, the V5 back-pair registration) and MUST reproduce what the SHIPPED
program says about itself, read from build/generated_doom_e1m1_blocked27/:
  222 pids        the "skypid" dispatch table's entries minus one      (e1m1_01_tables.fj)
  48 classes      the distinct `vzcbase` values the walk sets            (e1m1_04_walk.fj)
  43,392 lists    the bands-as-code header's half-lists                  (e1m1_06_banks.fj)
  9,015 bodies    the same header's unique count                  (full run only; banks header)
  5,326 blocks    the distinct `vpb_pb_<y2>_<colour>` pair blocks (full run only; banks source)
If the control does not reproduce, the projections are not printed. Every projection is a DELTA on
that reproduced base.

Word costs per unit are MEASURED from the shipped label table by label_sizes.py (same directory):
8.0 words per half-list id (thunk), 44.0 per unique body, 336 per distinct pair block, 81.8 per
per-state seg block, 253 per state switch.

--selftest (R9, docs/cr-rules.md): the reproduction control must PASS, and every MUTANT must make it
FAIL -- a control that cannot fail proves nothing. Mutants live in memory only (no file changes):
  P1  the door quantization step 16 -> 32         (a plane-id rule: fewer door states, fewer keys;
      8 is not a legal mutant -- a door would need 17 states, past the nibble doors.py asserts)
  P2  one door sector's height handling: its ceiling ignored, the door baked shut in every state
  P3  the plane key without the sector's light    (keys merge)
  (INFO, not checks: three registry rules are EQUIVALENT mutants on E1M1 -- the V5 back-pair
      registration, the walk's any-state test, the marking test itself: dropping any of them moves
      no count, in the base or in the lifts-q16/instant projection, so the control cannot see them
      and the 243-pid claim does not depend on them. They are printed with their counts.)
  B1  one viewz class's eye raised >= 8 units (full run only): pids, classes and half-lists still
      reproduce -- the cheap checks are blind to it by design -- so the BODY and PAIR-BLOCK counts
      must catch it
  L0  label_sizes.py re-derives the five word costs from the shipped label table and the shipped
      counts (thunk labels = half-lists, body labels = unique bodies, pair-block labels = pair
      blocks) and must reproduce the constants below
  L1  the label stride (bits per word) 32 -> 64   must change the five costs and be caught
  L2  one `vpb_t` label renamed                   must break the thunk count and be caught
  D0  the per-state seg-block model (`seg_units`, the one that prices the movers' blocks), run on the
      DOORS, must reproduce the shipped door blocks: units and blocks from the label table
  D1  that model with the face rule dropped       must be caught
--fast skips the band bodies (B1, and the 9,015 / 5,326 checks): minutes instead of ~10.
Prints PASS/FAIL per check and `SELFTEST PASS` only if every check passed.
"""
import argparse
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(HERE))

from doomfj.config import Config                                          # noqa: E402
from doomfj.doors import door_states, stops                               # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import ReferenceModel, apply_sector_heights   # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import _band_pair_lists, _sky_pair_lists, seg_marks_in  # noqa: E402
import label_sizes as LS                                                   # noqa: E402

W_ID, W_BODY, W_PB, W_BLK, W_SW = 8.0, 44.0, 336.0, 81.8, 253.0   # MEASURED, label_sizes.py
W_PREC = (1, 1, 0, 1, 0)                                           # the decimals each is stated to
MAX_STATES, PID_CAP = 16, 255
DOOR_QUANT = 16
LIFTS = (98, 103)
FSWITCH = (76, 126, 129)
CONFIGS = [("lifts q16, switch instant", 16, "instant"),
           ("lifts q32, switch instant", 32, "instant"),
           ("lifts q16, switch q32", 16, 32),
           ("lifts q16, switch q16", 16, 16)]

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
def shipped(gen: Path) -> dict:
    tables = (gen / "e1m1_01_tables.fj").read_text(encoding="utf-8", errors="replace")
    banks = (gen / "e1m1_06_banks.fj").read_text(encoding="utf-8", errors="replace")
    walk = (gen / "e1m1_04_walk.fj").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"bands-as-code: (\d+) half-lists \((\d+) unique, pad (\d+)\)", banks)
    lists, uniq, pad = (int(g) for g in m.groups())
    return {"pids": int(re.search(r'dispatch table "skypid": (\d+) entries', tables).group(1)) - 1,
            "classes": len(set(re.findall(r"hex\.set w/4, vzcbase, (\d+)", walk))),
            "lists": lists, "uniq": uniq, "pad": pad,
            "pairs": len(re.findall(r"^vpb_pb_\d+_\d+:", banks, re.M))}


# ---- the emitter's registry, rebuilt with the emitter's rules ----------------------------------
def door_secs_list(doors):
    dmax = max(len(v) for v in doors.values())
    return [apply_sector_heights(secs, {si: (secs[si].floor_h, st[min(k, len(st) - 1)])
                                        for si, st in doors.items()}) for k in range(dmax)]


DOORS = door_states(secs, lds, sds, DOOR_QUANT)                # {sector: [shut .. open]}
DSECS = door_secs_list(DOORS)


def registry(movers, *, doors=None, dsecs=None, keyfn=None, backpair=True, walk_any_state=True,
             marks=None):
    """(pids, keys-in-bank-order, vz classes, seg_secs, in_walk) with `movers` = {sector: [(floor,
    ceil) per state]} added the way `_seg_secs` adds door states: a seg touching a mover bakes one
    block per state. `doors`/`dsecs`/`keyfn`/`backpair`/`walk_any_state`/`marks` default to the
    emitter's rules; the selftest's mutants override them."""
    marks = seg_marks_in if marks is None else marks
    doors = DOORS if doors is None else doors
    dsecs = DSECS if dsecs is None else dsecs
    keyfn = plane_keys if keyfn is None else keyfn
    mmax = max([len(v) for v in movers.values()] + [1])
    msecs = [apply_sector_heights(secs, {si: st[min(k, len(st) - 1)] for si, st in movers.items()})
             for k in range(mmax)]

    def seg_secs(seg):
        f, b = sides(seg)
        if f in doors or (b is not None and b in doors):
            d = f if f in doors else b
            return dsecs[:len(doors[d])]
        if f in movers or (b is not None and b in movers):
            mv = f if f in movers else b
            return msecs[:len(movers[mv])]
        return [secs]

    def touched(seg):
        f, b = sides(seg)
        return f in doors or f in movers or (b is not None and (b in doors or b in movers))

    def closed_static(seg):
        ld = lds[seg.linedef]
        if ld.back == -1 or touched(seg):
            return False
        f, b = sides(seg)
        return min(secs[f].ceil_h, secs[b].ceil_h) <= max(secs[f].floor_h, secs[b].floor_h)

    def in_walk(seg):
        ld = lds[seg.linedef]
        states = seg_secs(seg) if walk_any_state else seg_secs(seg)[:1]
        return (ld.back == -1 or closed_static(seg)
                or any(marks(lds, sds, seg, sv) for sv in states))
    pids = {}
    for seg in cmap.segs:
        if not in_walk(seg):
            continue
        for sv in seg_secs(seg):
            pids.setdefault(keyfn(rm._seg_sector(lds, sds, sv, seg)), len(pids) + 1)
            if backpair and lds[seg.linedef].back != -1:          # V5 back pair (stack_flag)
                pids.setdefault(keyfn(sv[sides(seg)[1]]), len(pids) + 1)
    vz = {}
    for ss in cmap.subsectors:
        vz.setdefault(rm.view_z(rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg]).floor_h), len(vz))
    for si, st in movers.items():                                # the eye can ride a mover
        for (fl, ce) in st:
            if ce - fl >= 56:
                vz.setdefault(rm.view_z(fl), len(vz))
    keys = [k for pair in pids for k in pair]
    return pids, keys, vz, seg_secs, in_walk


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


def door_table(doors):
    """the doors as a mover table: {sector: [(floor, ceil) per state]}, state 0 = shut"""
    return {si: [(secs[si].floor_h, c) for c in st] for si, st in doors.items()}


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


def seg_units(tbl, seg_secs, in_walk, *, faces=True):
    """per-state block units a mover seg carries, by the emitter's block kinds (MEASURED on doors:
    render_consts on every touched seg that reaches the solid body, attrib + face on marking segs).
    `faces=False` is the selftest's mutant D1."""
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
            if faces and (um or lm):
                face += 1
                blocks += n
    return render, attrib, face, blocks, odd_gate


def half_lists(vz, keys, n_sky):
    return len(vz) * len(keys) * 2 + n_sky


def bodies(vz, keys):
    """(unique band bodies, distinct (y2, colour) pair blocks) -- the emitter's own producer"""
    bl = _band_pair_lists(rm, cfg, mw, vz, keys, True) + _sky_pair_lists(rm, mw, cfg)
    uniq = {tuple(map(tuple, p)) for p in bl}
    return uniq, {pr for p in uniq for pr in p}


def main_run(args):
    ship = shipped(ROOT / args.gen)
    print("SHIPPED (%s): %d pids, %d half-lists, %d unique, pad %d; %d viewz classes, %d pair blocks"
          % (args.gen, ship["pids"], ship["lists"], ship["uniq"], ship["pad"], ship["classes"],
             ship["pairs"]))
    t0 = time.perf_counter()
    base_pids, base_keys, base_vz, _, base_in_walk = registry({})
    n_sky = len(_sky_pair_lists(rm, mw, cfg))
    base_lists_n = half_lists(base_vz, base_keys, n_sky)
    print("CONTROL registry: %d pids (shipped %d), %d viewz classes (shipped %d), %d half-lists"
          " (shipped %d), sky %d" % (len(base_pids), ship["pids"], len(base_vz), ship["classes"],
                                      base_lists_n, ship["lists"], n_sky))
    ok = (len(base_pids) == ship["pids"] and len(base_vz) == ship["classes"]
          and base_lists_n == ship["lists"])
    print("CONTROL: %s" % ("REPRODUCED" if ok else "!! DOES NOT REPRODUCE -- projections withheld"))
    if not ok:
        return 1

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

    # ---- projections ---------------------------------------------------------------------------
    base_uniq = None
    base_pairs = None
    if not args.fast:
        t = time.perf_counter()
        base_uniq, base_pairs = bodies(base_vz, base_keys)
        print("\nCONTROL bodies: %d unique (shipped %d), %d distinct (y2, colour) pair blocks (shipped"
              " %d), %.0f s" % (len(base_uniq), ship["uniq"], len(base_pairs), ship["pairs"],
                               time.perf_counter() - t))
        if len(base_uniq) != ship["uniq"] or len(base_pairs) != ship["pairs"]:
            print("  !! bodies or pair blocks do not reproduce -- body/word projections are UNVERIFIED")

    print("\nPROJECTIONS (deltas on the reproduced base):")
    for name, lq, fsm in CONFIGS:
        tbl = mover_table(lq, fsm)
        states_ok = all(len(v) <= MAX_STATES for v in tbl.values())
        pids, keys, vz, seg_secs, in_walk = registry(tbl)
        npid, nvz = len(pids) - len(base_pids), len(vz) - len(base_vz)
        lists_n = half_lists(vz, keys, n_sky)
        pad = 1 << max(1, (lists_n - 1).bit_length())
        r, a, fc, blocks, odd = seg_units(tbl, seg_secs, in_walk)
        units = r + a + fc
        words_blk = blocks * W_BLK + units * W_SW
        print("  %-28s states %s%s" % (name, {k: len(v) for k, v in tbl.items()},
                                         "" if states_ok else "  !! > 16 states: not one nibble"))
        print("      pids %d (+%d) -> %s;  viewz classes %d (+%d);  half-lists %d (+%d), pad %d%s"
              % (len(pids), npid, "FITS the byte" if len(pids) <= PID_CAP else "OVER 255: needs PID_NIBBLES 3/4",
                 len(vz), nvz, lists_n, lists_n - base_lists_n, pad,
                 "" if pad <= ship["pad"] else "  (BAND_NIBBLES 5, pad doubles)"))
        print("      per-state seg blocks: %d units (render %d, attrib %d, face %d), %d blocks -> ~%.0fK words"
              " (MEASURED per-unit door costs)%s" % (units, r, a, fc, blocks, words_blk / 1e3,
                                                     "" if not odd else "  !! closed in a non-prefix of states: %s" % odd[:3]))
        words = (lists_n - base_lists_n) * W_ID + max(0, pad - ship["pad"]) * 2
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
    return 0


# ================================================================================================
# --selftest: the reproduction control, and mutants it must catch (R9)
# ================================================================================================
def selftest(args):
    t0 = time.perf_counter()
    ship = shipped(ROOT / args.gen)
    n_sky = len(_sky_pair_lists(rm, mw, cfg))
    results = []

    def check(name, ok, detail):
        results.append(ok)
        print("  %-4s %-66s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)

    def reproduces(pids, vz, keys, body=None):
        """the control's verdict and its numbers: (all equal?, 'got/shipped ...')"""
        got = {"pids": len(pids), "classes": len(vz), "lists": half_lists(vz, keys, n_sky)}
        if body is not None:
            got["uniq"], got["pairs"] = len(body[0]), len(body[1])
        eq = all(got[k] == ship[k] for k in got)
        return eq, " ".join("%s %d/%d" % (k, got[k], ship[k]) for k in got)

    print("SELFTEST lift_budget.py%s -- shipped (%s): %d pids, %d classes, %d half-lists, %d bodies,"
          " %d pair blocks" % (" --fast" if args.fast else "", args.gen, ship["pids"], ship["classes"],
                              ship["lists"], ship["uniq"], ship["pairs"]), flush=True)

    # R0 -- the reproduction control itself (it must PASS)
    pids, keys, vz, seg_secs0, in_walk0 = registry({})
    body = None if args.fast else bodies(vz, keys)
    eq, det = reproduces(pids, vz, keys, body)
    check("R0 reproduction control (the emitter's rules)", eq,
          det + ("" if body is not None else "  [bodies/pair blocks skipped: --fast]"))

    # P1-P4 -- mutated plane-id rules: the reproduction must FAIL
    dq = door_states(secs, lds, sds, 32)       # 8 would overflow the 16-state nibble (doors.py asserts)
    p, k_, v, _, _ = registry({}, doors=dq, dsecs=door_secs_list(dq))
    eq, det = reproduces(p, v, k_)
    check("P1 mutant: door quantization 16 -> 32 must be caught", not eq, det)
    d0 = max(DOORS, key=lambda s: (len(DOORS[s]), -s))
    dm = dict(DOORS)
    dm[d0] = [DOORS[d0][0]] * len(DOORS[d0])
    p, k_, v, _, _ = registry({}, doors=dm, dsecs=door_secs_list(dm))
    eq, det = reproduces(p, v, k_)
    check("P2 mutant: door sector %d's ceiling ignored (shut in all %d states)"
          % (d0, len(DOORS[d0])), not eq, det)

    def no_light(sec):
        return ((sec.ceil_h, 0, flatval(sec.ceil_tex), sec.ceil_tex.upper()),
                (sec.floor_h, 0, flatval(sec.floor_tex), sec.floor_tex.upper()))
    p, k_, v, _, _ = registry({}, keyfn=no_light)
    eq, det = reproduces(p, v, k_)
    check("P3 mutant: the plane key without the sector's light must be caught", not eq, det)
    # NOT controls: three registry rules whose mutants are EQUIVALENT on E1M1 -- no count can see
    # them, in the base OR in the headline projection, so they cannot move the 243-pid claim either.
    # Reported so the control's blind spots are on the record, not counted as checks.
    q16 = mover_table(16, "instant")
    head = len(registry(q16)[0])
    for label, kw in (("the V5 back-pair registration dropped", {"backpair": False}),
                      ("the walk tests only the STORED state", {"walk_any_state": False}),
                      ("every two-sided seg marks", {"marks": lambda *_a: True})):
        p, k_, v, _, _ = registry({}, **kw)
        eq, det = reproduces(p, v, k_)
        print("  INFO equivalent mutant, not a check -- %s: %s; lifts-q16/instant projection %d pids"
              " (%d with the rule)" % (label, det, len(registry(q16, **kw)[0]), head), flush=True)

    # B1 -- one viewz class moved: invisible to the counts, visible to the bodies
    if args.fast:
        print("  SKIP B1 mutant: one viewz class's eye +8 units (band bodies: not with --fast)")
    else:
        j = len(vz) // 2
        vj = next(val for val, i in vz.items() if i == j)
        up = next(d for d in range(8, 64) if vj + (d << 16) not in vz)     # no merge with a class
        vzm = {(val + (up << 16) if i == j else val): i for val, i in vz.items()}
        eq_c, det_c = reproduces(pids, vzm, keys)
        bm = bodies(vzm, keys)
        eq_b, det_b = reproduces(pids, vzm, keys, bm)
        check("B1 mutant: viewz class %d's eye +%d units -- counts blind, bodies must catch" % (j, up),
              eq_c and not eq_b, det_b + ("" if eq_c else "  (!! the counts moved too)"))

    # L0-L2 -- label_sizes.py: the five word costs and their cross-source counts
    top = LS.load(str(ROOT / args.labels))

    def costs(tbl, word_bits=LS.WORD_BITS):
        """(the five costs, the three cross-source counts) derived from label_sizes' groups"""
        g, (nblk, nunit, _spu) = LS.measure(tbl, word_bits)
        grp = list(g.values())       # thunks, bodies, pair blocks, clamps, state blocks, switches
        nt, wt = grp[0]
        wb, wp, ws, wd = grp[1][1], grp[2][1], grp[4][1], grp[5][1]
        nbody = sum(1 for _a, n in tbl if re.fullmatch(r"vpb_body\d+", n))
        npair = len({n for _a, n in tbl if re.fullmatch(r"vpb_pb_\d+_\d+", n)})
        five = (wt / max(1, nt), wb / max(1, ship["uniq"]), wp / max(1, ship["pairs"]),
                ws / max(1, nblk), wd / max(1, nunit))
        return five, (nt, nbody, npair), (nblk, nunit)

    def costs_ok(five, counts):
        want = (W_ID, W_BODY, W_PB, W_BLK, W_SW)
        eq5 = all(round(x, p) == w for x, p, w in zip(five, W_PREC, want))
        eqc = counts == (ship["lists"], ship["uniq"], ship["pairs"])
        det = ("costs %s (constants %s); labels: thunks %d/%d bodies %d/%d pair blocks %d/%d"
               % ("/".join("%.*f" % (p, x) for x, p in zip(five, W_PREC)),
                  "/".join("%.*f" % (p, w) for w, p in zip(want, W_PREC)),
                  counts[0], ship["lists"], counts[1], ship["uniq"], counts[2], ship["pairs"]))
        return eq5 and eqc, det
    five, counts, (nblk, nunit) = costs(top)
    ok, det = costs_ok(five, counts)
    check("L0 label_sizes reproduces the five word costs + shipped counts", ok, det)
    five, counts, _ = costs(top, word_bits=64)
    ok, det = costs_ok(five, counts)
    check("L1 mutant: label stride 32 -> 64 bits per word must be caught", not ok, det)
    i = next(i for i, (_a, n) in enumerate(top) if re.fullmatch(r"vpb_t\d+", n))
    topm = list(top)
    topm[i] = (top[i][0], "vpb_x" + top[i][1][5:])
    five, counts, _ = costs(topm)
    ok, det = costs_ok(five, counts)
    check("L2 mutant: one vpb_t label (%s) renamed must be caught" % top[i][1], not ok, det)

    # D0-D1 -- the per-state seg-block model on the DOORS vs the shipped door blocks
    r, a, fc, blocks, _odd = seg_units(door_table(DOORS), seg_secs0, in_walk0)
    check("D0 seg_units on the doors reproduces the shipped door blocks",
          (r + a + fc, blocks) == (nunit, nblk),
          "units %d/%d (render %d attrib %d face %d), blocks %d/%d" % (
              r + a + fc, nunit, r, a, fc, blocks, nblk))
    r, a, fc, blocks, _odd = seg_units(door_table(DOORS), seg_secs0, in_walk0, faces=False)
    check("D1 mutant: seg_units without the face rule must be caught",
          (r + a + fc, blocks) != (nunit, nblk),
          "units %d/%d, blocks %d/%d" % (r + a + fc, nunit, blocks, nblk))

    n_ok = sum(results)
    print("SELFTEST %s: %d/%d checks passed (%.0f s)" % (
        "PASS" if n_ok == len(results) else "FAIL", n_ok, len(results), time.perf_counter() - t0))
    return 0 if n_ok == len(results) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", default="build/generated_doom_e1m1_blocked27")
    ap.add_argument("--labels", default=LS.DEFAULT, help="the shipped label table (selftest L0-L2, D0)")
    ap.add_argument("--fast", action="store_true", help="skip the band-body projection (minutes)")
    ap.add_argument("--selftest", action="store_true", help="R9: the control and its mutants")
    args = ap.parse_args()
    return selftest(args) if args.selftest else main_run(args)


if __name__ == "__main__":
    sys.exit(main())
