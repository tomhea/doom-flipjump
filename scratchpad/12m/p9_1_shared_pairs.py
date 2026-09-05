"""P9-1: SHARED PAIR-BLOCKS for the vpb bands bank -- the S2 size mechanism, prototyped.

THE MEASUREMENT THAT MOTIVATES IT (banks census, 2026-09-05): the bank emits 40,567 (y2,c)
pair-blocks but only 5,326 are DISTINCT (mean reuse 7.6x), and each block is ~172 static ops --
two 8-level bit.if compare trees whose exact_xor wflips are ~85% of region D's 5.47 MB of file.
Emit each distinct block ONCE, and have bodies CALL it.

THE MECHANISM: a 3-outcome fcall. stl.fcall's landing op IS the disarm (`ret: wflip reg+w, ret`),
so if the callee flips bit 6 or 7 of the return cell's JUMP FIELD before fret, it lands 1 or 2
ops later. With `pad 4` making `ret` 4-op aligned, those bits start 0 and the flips mean +dw/+2dw:

    body, per pair:                              shared block pb_{y2}_{c}:
        wflip pb_x+w, ret, pb_Y_C   // call          lo-tree (bit.if x8, verbatim)
        pad 4                                        hi-tree (bit.if x8, verbatim)
      ret:    wflip pb_x+w, ret,     CLAMP_C         _em: output y2,c ; -> continue
      ret+dw: wflip pb_x+w, ret+dw,  FIN             _ls: output y2,c ; -> stop
      ret+2dw:wflip pb_x+w, ret+2dw  // fallthrough  _cl:              -> clamp
        (next pair)                                  clamp:            ;pb_x        (lane 0)
                                                     stop:  pb_x+w+6;  then ;pb_x  (lane 1)
                                                     cont:  pb_x+w+7;  then ;pb_x  (lane 2)

    Every lane disarms with ITS OWN armed value (ret ^ flipped bits), so pb_x returns to zero on
    all three paths -- checked below by running MANY calls in sequence through one cell.

WHAT THIS FILE PROVES, in order:
  1. EQUIVALENCE: the shared emitter produces byte-identical OUTPUT to today's emitter (both
     re-derived here verbatim from lut_generator's _cmp3_tree) over windows covering every arc:
     full emit, skip-then-emit, stop-at-eq (_ls), clamp (_cl), all-skip, and SEQUENCES of walks
     (pb_x reuse). The bytes are the pixels: identical bytes = identical frame.
  2. NEGATIVE CONTROL (R9): swapping two lanes in one pair must break the output.
  3. COST: space and executed ops per walk, both shapes, at reuse 3x -- the inputs to the
     region-D projection.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare, price                                         # noqa: E402

NL = chr(10)


# ---- today's emitter, verbatim from lut_generator._cmp3_tree / generate_bands_walk_fj ----

def bit3(cell, b):
    return "%s + %d*dw" % (cell, b)


def cmp3_tree(cell, k, lt, eq, gt, tag):
    out = []
    for b in range(7, -1, -1):
        nxt = eq if b == 0 else "%s_b%d" % (tag, b - 1)
        if (k >> b) & 1:
            out.append("    bit.if %s, %s, %s" % (bit3(cell, b), lt, nxt))
        else:
            out.append("    bit.if %s, %s, %s" % (bit3(cell, b), nxt, gt))
        if b:
            out.append("%s_b%d:" % (tag, b - 1))
    return out


def emit_old(bodies):
    """bodies: list of list of (y2,c). Emitted exactly as generate_bands_walk_fj does today,
    minus the index dispatch (bodies are fcall'd directly -- the dispatch is not under test)."""
    out = []
    for k, pairs in enumerate(bodies):
        out.append("vpo_body%d:" % k)
        for j, (y2, c) in enumerate(pairs):
            t = "vpo_%d_%d" % (k, j)
            nxt = "%s_nx" % t
            out += cmp3_tree("vq_lo", y2, "%s_in" % t, nxt, nxt, "%s_lo" % t)
            out.append("%s_in:" % t)
            out += cmp3_tree("vq_hi", y2, "%s_cl" % t, "%s_ls" % t, "%s_em" % t, "%s_hi" % t)
            out.append("%s_em:" % t)
            out += ["    stl.output_char %d" % ch for ch in (y2, c)]
            out.append("    ;%s" % nxt)
            out.append("%s_ls:" % t)
            out += ["    stl.output_char %d" % ch for ch in (y2, c)]
            out.append("    ;vpo_fin%d" % k)
            out.append("%s_cl:" % t)
            out.append("    ;vpo_cl_%d" % c)
            out.append("%s:" % nxt)
        out += ["vpo_fin%d:" % k, "    stl.fret vpo_x"]
    for c in sorted({c for pairs in bodies for _, c in pairs}):
        # the real clamp tail raw-byte-outs vq_hi; for the prototype a marker byte is enough --
        # the ARC is what is under test, and both emitters share this same tail
        out += ["vpo_cl_%d:" % c, "    stl.output_char 33", "    stl.output_char %d" % c,
                "    stl.fret vpo_x"]
    out.append("vpo_x: ;0")
    return out


# ---- the shared emitter -----------------------------------------------------------------

def emit_new(bodies, sabotage=False):
    out = []
    distinct = sorted({p for pairs in bodies for p in pairs})
    for k, pairs in enumerate(bodies):
        out.append("vpn_body%d:" % k)
        for j, (y2, c) in enumerate(pairs):
            t = "vpn_%d_%d" % (k, j)
            cl_t, fin_t = "vpn_cl_%d" % c, "vpn_fin%d" % k
            if sabotage and (k, j) == (0, 1):
                cl_t, fin_t = fin_t, cl_t          # the R9 break: clamp and stop lanes swapped
            out += ["    wflip pbx+w, %s_r, pb_%d_%d" % (t, y2, c),
                    "    pad 4",
                    "%s_r:" % t,
                    "    wflip pbx+w, %s_r, %s" % (t, cl_t),
                    "    wflip pbx+w, %s_r+dw, %s" % (t, fin_t),
                    "    wflip pbx+w, %s_r+2*dw" % t]
        out += ["vpn_fin%d:" % k, "    stl.fret vpn_x"]
    for (y2, c) in distinct:
        t = "pb_%d_%d" % (y2, c)
        out.append("%s:" % t)
        out += cmp3_tree("vq_lo", y2, "%s_in" % t, "%s_ct" % t, "%s_ct" % t, "%s_lo" % t)
        out.append("%s_in:" % t)
        out += cmp3_tree("vq_hi", y2, "%s_cl" % t, "%s_ls" % t, "%s_em" % t, "%s_hi" % t)
        out.append("%s_em:" % t)
        out += ["    stl.output_char %d" % ch for ch in (y2, c)]
        out.append("    ;%s_ct" % t)
        out.append("%s_ls:" % t)
        out += ["    stl.output_char %d" % ch for ch in (y2, c)]
        # stop = lane 1: flip bit 6 of pbx's jump field, return
        out += ["    pbx+w+6;", "    ;pbx"]
        # clamp = lane 0: return with nothing flipped
        out += ["%s_cl:" % t, "    ;pbx"]
        # continue = lane 2: flip bit 7
        out += ["%s_ct:" % t, "    pbx+w+7;", "    ;pbx"]
    for c in sorted({c for pairs in bodies for _, c in pairs}):
        out += ["vpn_cl_%d:" % c, "    stl.output_char 33", "    stl.output_char %d" % c,
                "    stl.fret vpn_x"]
    out += ["vpn_x: ;0", "pbx: ;0"]
    return out


# ---- the harness ------------------------------------------------------------------------

# three bodies sharing pairs heavily; ASCII-range values so the console never mangles them
BODIES = [[(50, 65), (80, 66), (110, 67)],
          [(50, 65), (80, 66), (120, 68)],
          [(60, 69), (80, 66), (110, 67)]]

WINDOWS = [("full emit", 0, 200), ("skip first", 55, 200), ("stop at eq 80", 0, 80),
           ("clamp at 100", 0, 100), ("all skip", 150, 255), ("clamp at once", 0, 40)]


def program(emitter, walks, sabotage=False):
    body = []
    for (lo, hi, k) in walks:
        body += ["bit.zero 8, vq_lo", "bit.zero 8, vq_hi",
                 "bit.xor 8, vq_lo, c_lo%d" % lo, "bit.xor 8, vq_hi, c_hi%d" % hi,
                 "stl.fcall %s_body%d, %s_x" % (("vpn" if emitter is emit_new else "vpo"), k,
                                                ("vpn" if emitter is emit_new else "vpo"))]
    consts = []
    for lo in sorted({w[0] for w in walks}):
        consts.append("c_lo%d: bit.vec 8, %d" % (lo, lo))
    for hi in sorted({w[1] for w in walks}):
        consts.append("c_hi%d: bit.vec 8, %d" % (hi, hi))
    tail = emitter(BODIES, sabotage=sabotage) if emitter is emit_new else emitter(BODIES)
    return body, ["vq_lo: bit.vec 8", "vq_hi: bit.vec 8"] + consts + tail


def run(emitter, walks, sabotage=False):
    if emitter is emit_new:
        body, data = program(emit_new, walks, sabotage)
    else:
        body, data = program(emit_old, walks)
    # printer must be NON-EMPTY or compare() skips the value run entirely and returns None
    # digits -- which makes every equality vacuous (None == None). The '.' is a shared marker.
    rows = compare([("p", body)], data=data, prelude="", quiet=True,
                   printer=["stl.output_char 46"])
    got = rows[0][3]
    assert got is not None and got.endswith("."), "digits capture is vacuous -- refuse to compare"
    return got, rows[0][1], rows[0][2]


print("=== P9-1  shared pair-blocks: 3-outcome fcall lanes ===")
print()
print("STEP 1 -- EQUIVALENCE, window by window, then all windows in ONE RUN (pb_x reuse)")
allw = []
bad = 0
for name, lo, hi in WINDOWS:
    for k in range(len(BODIES)):
        allw.append((lo, hi, k))
for name, lo, hi in WINDOWS:
    walks = [(lo, hi, k) for k in range(len(BODIES))]
    o, _, _ = run(emit_old, walks)
    n, _, _ = run(emit_new, walks)
    ok = o == n
    bad += 0 if ok else 1
    print("  %-14s old=%-30r new=%-30r %s"
          % (name, o[:28], n[:28], "ok" if ok else "!! DIFFER"))
o, oex, osp = run(emit_old, allw)
n, nex, nsp = run(emit_new, allw)
seq_ok = o == n
bad += 0 if seq_ok else 1
print("  %-14s %d walks through one cell: %s" % ("SEQUENCE", len(allw),
                                                 "identical" if seq_ok else "!! DIFFER"))
print()
print("EQUIVALENCE: %s" % ("every window and the full sequence byte-identical"
                           if not bad else "!! %d MISMATCHES -- do not proceed" % bad))
print()
print("STEP 2 -- NEGATIVE CONTROL: lanes swapped in one pair must break the output")
ns, _, _ = run(emit_new, allw, sabotage=True)
ctl = ns != n
print("  sabotaged output %s the honest one -- %s" % ("differs from" if ctl else "EQUALS",
      "control PASS" if ctl else "!! CONTROL FAIL: the test cannot detect a broken lane"))
print()
if not bad and ctl:
    print("STEP 3 -- COST over the %d-walk sequence" % len(allw))
    print("  old (inline blocks) : %9.1f executed   %7d space" % (oex, osp))
    print("  new (shared blocks) : %9.1f executed   %7d space" % (nex, nsp))
    print("  delta               : %+9.1f executed   %+7d space (%d bodies, %d distinct of %d pairs)"
          % (nex - oex, nsp - osp, len(BODIES),
             len({p for b in BODIES for p in b}), sum(len(b) for b in BODIES)))
    print()
    print("  NOTE the space delta here UNDERSTATES the real win: this prototype has reuse 9/7,")
    print("  the bank has 40,567/5,326 = 7.6x, and chain popcounts here are ~4 not ~11.")
