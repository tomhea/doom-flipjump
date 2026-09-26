"""S6 -- the fj micro-probes of docs/plan-gameplay.md sections 4, 13, 14 and D10 (phase 0).

    python scratchpad/gp/probes/s6/probes.py            # every probe, plain + pool, verified
    python scratchpad/gp/probes/s6/probes.py rng d4     # only the named groups
    python scratchpad/gp/probes/s6/fjprobe.py --selftest

Every number printed is MEASURED by that command (exact executed-op deltas; see fjprobe.py for
the method and the controls). Each probe is ALSO run with its output checked against a Python
model (`ok`), so a probe that computed the wrong thing cannot report a cost.

Groups: calib (the plan's in-game MEASURED primitives, re-measured here), rng, idx, win, d4,
line, cell, ptloc, octant, dist, aim.
"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fjprobe as F                                                        # noqa: E402
from fjprobe import Probe                                                  # noqa: E402

ROOT = F.ROOT
from doomfj.lut_generator import generate_dispatch_table_fj, generate_packed_lut_fj  # noqa: E402

FIXED = ROOT / "src" / "fj" / "fixed_point.fj"
SIM = ROOT / "src" / "fj" / "sim.fj"


def _consts():
    """the build's generated fj_consts.fj (HOT_PAD etc., which sim.fj names), from the SSOT"""
    import tempfile
    from doomfj.config import Config
    return Config().emit_fj_consts(Path(tempfile.mkdtemp(prefix="gpconsts_")) / "fj_consts.fj")


CONSTS = _consts()
M40 = (1 << 40) - 1
M32 = (1 << 32) - 1


def d4(label, values, idx_n, res_n):
    """doomfj's own D4 per-entry dispatch table (lut_generator), as the game would emit it."""
    return generate_dispatch_table_fj(label, values, index_nibbles=idx_n,
                                      result_nibbles=res_n).splitlines()


def le_bytes(v, n):
    return bytes((v >> (8 * i)) & 0xFF for i in range(n))


# =============================================================================================
# 1. RNG (plan D10): DOOM's table two dispatches, the COMPOSED per-site table, a generated RNG
# =============================================================================================
# DOOM's m_random.c rndtable (id Software, GPL). The S3 stream's rng.py is the source of truth
# for the game; a cost probe depends only on the outcome values' nibble popcounts.
RNDTABLE = [
    0, 8, 109, 220, 222, 241, 149, 107, 75, 248, 254, 140, 16, 66,
    74, 21, 211, 47, 80, 242, 154, 27, 205, 128, 161, 89, 77, 36,
    95, 110, 85, 48, 212, 140, 211, 249, 22, 79, 200, 50, 28, 188,
    52, 140, 202, 120, 68, 145, 62, 70, 184, 190, 91, 197, 152, 224,
    149, 104, 25, 178, 252, 182, 202, 182, 141, 197, 4, 81, 181, 242,
    145, 42, 39, 227, 156, 198, 225, 193, 219, 93, 122, 175, 249, 0,
    175, 143, 70, 239, 46, 246, 163, 53, 163, 109, 168, 135, 2, 235,
    25, 92, 20, 145, 138, 77, 69, 166, 78, 176, 173, 212, 166, 113,
    94, 161, 41, 50, 239, 49, 111, 164, 70, 60, 2, 37, 171, 75,
    136, 156, 11, 56, 42, 146, 138, 229, 73, 146, 77, 61, 98, 196,
    135, 106, 63, 197, 195, 86, 96, 203, 113, 101, 170, 247, 181, 113,
    80, 250, 108, 7, 255, 237, 129, 226, 79, 107, 112, 166, 103, 241,
    24, 223, 239, 120, 198, 58, 60, 82, 128, 3, 184, 66, 143, 224,
    145, 224, 81, 206, 163, 45, 63, 90, 168, 114, 59, 33, 159, 95,
    28, 139, 123, 98, 125, 196, 15, 70, 194, 253, 54, 14, 109, 226,
    71, 17, 161, 93, 186, 87, 244, 138, 20, 52, 123, 251, 26, 36,
    17, 46, 52, 231, 232, 76, 31, 221, 84, 37, 216, 165, 212, 106,
    197, 242, 98, 43, 39, 175, 254, 145, 190, 84, 118, 222, 187, 136,
    120, 163, 236, 249]
assert len(RNDTABLE) == 256


def f_dmg(r):          # P_PosAttack: damage = ((P_Random()%5)+1)*3  -> 3..15, ONE nibble
    return ((r % 5) + 1) * 3


def f_col(r):          # a pellet's aim column 72..88 (plan 6.4) -> TWO nibbles
    return 72 + (r % 17)


def xs16(x):           # xorshift16 (7, 9, 8), period 65535
    x ^= (x << 7) & 0xFFFF
    x ^= x >> 9
    x ^= (x << 8) & 0xFFFF
    return x


def lfsr16(x):         # Galois LFSR, taps 0xB400 (period 65535) -- ONE new bit per step
    return (x >> 1) ^ (0xB400 if x & 1 else 0)


XS_SEED = 0xACE1
XS_BODY = [            # the xorshift step in hex ops, exactly xs16() above
    "hex.mov 4, gp_t5, gp_xs",
    "hex.zero gp_t5+4*dw",
    "hex.shl_hex 5, 2, gp_t5",          # x << 8, kept to 20 bits
    "hex.shr_bit 5, gp_t5",             # (x << 7), bits 7..18
    "hex.xor 4, gp_xs, gp_t5",          # x ^= (x << 7) & 0xffff
    "hex.mov 2, gp_t2, gp_xs+2*dw",     # x >> 8
    "hex.shr_bit 2, gp_t2",             # x >> 9
    "hex.xor 2, gp_xs, gp_t2",          # x ^= x >> 9
    "hex.xor 2, gp_xs+2*dw, gp_xs",     # x ^= (x << 8) & 0xffff
]
LFSR_BODY = [
    "hex.if_flags gp_xs, 0xAAAA, gp_lf_e, gp_lf_o",
    "gp_lf_e:",
    "hex.shr_bit 4, gp_xs",
    ";gp_lf_d",
    "gp_lf_o:",
    "hex.shr_bit 4, gp_xs",
    "hex.xor_by 4, gp_xs, 0xB400",
    "gp_lf_d:",
]
RNG_DATA = ["gp_ri: hex.vec 2", "gp_rv: hex.vec 2", "gp_ro: hex.vec 2",
            "gp_xs: hex.vec 4, 0x%x" % XS_SEED, "gp_t5: hex.vec 5", "gp_t2: hex.vec 2"]


def rng_probes():
    out = []
    for oname, f, rn in (("dmg", f_dmg, 1), ("col", f_col, 2)):
        site = [f(r) for r in range(256)]                  # outcome of the RANDOM VALUE
        comp = [f(RNDTABLE[i]) for i in range(256)]        # outcome of the RNG INDEX (D10's fold)
        tab_site = d4("gp_s", site, 2, rn)
        exp_doom = (lambda f_=f: lambda n: bytes(f_(RNDTABLE[(k + 1) & 255]) for k in range(n)))()

        def exp_gen(n, f_=f, step=xs16):
            x, o = XS_SEED, []
            for _ in range(n):
                x = step(x)
                o.append(f_(x & 0xFF))
            return bytes(o)

        out.append(Probe(
            "rng_%s a: DOOM table, 2 dispatches" % oname,
            body=["hex.inc 2, gp_ri", "gp_rnd.lookup gp_rv, gp_ri", "gp_s.lookup gp_ro, gp_rv"],
            tables=d4("gp_rnd", RNDTABLE, 2, 2) + tab_site, data=RNG_DATA,
            verify=["hex.print gp_ro"], expected=exp_doom,
            note="index++ ; rndtable[i] (D4 256x2n) ; site[r] (D4 256x%dn)" % rn))
        out.append(Probe(
            "rng_%s b: composed per-site table, 1 dispatch" % oname,
            body=["hex.inc 2, gp_ri", "gp_c.lookup gp_ro, gp_ri"],
            tables=d4("gp_c", comp, 2, rn), data=RNG_DATA,
            verify=["hex.print gp_ro"], expected=exp_doom,
            note="index++ ; outcome[i] = f(rndtable[i]) (D4 256x%dn)" % rn))
        out.append(Probe(
            "rng_%s c: xorshift16 + site table" % oname,
            body=XS_BODY + ["gp_s.lookup gp_ro, gp_xs"],
            tables=tab_site, data=RNG_DATA,
            verify=["hex.print gp_ro"], expected=exp_gen,
            note="xorshift16 (7,9,8) in hex ops ; site[x & 0xff]"))
        if oname == "dmg":
            out.append(Probe(
                "rng_%s c2: LFSR16 1 step + site table" % oname,
                body=LFSR_BODY + ["gp_s.lookup gp_ro, gp_xs"],
                tables=tab_site, data=RNG_DATA,
                verify=["hex.print gp_ro"],
                expected=lambda n, f_=f: exp_gen(n, f_, lfsr16),
                note="ONE Galois step (1 fresh bit/call -- a quality floor, not a candidate)"))
    return out


# =============================================================================================
# 2. indexed access: ptr_index + read/write vs a jump through a table into per-entity stubs
# =============================================================================================
def _plant(e):
    return (e * 167 + 13) & 0xFF


def _plant4(e):
    return (e * 40503 + 0x1234) & 0xFFFF


PRELUDE_JCALL = [
    "ns gp {",
    "    // a jump through a table on the index into per-entity stubs (the D4 dispatch mechanism",
    "    // with CODE handlers): xor the index into the dispatch op, jump through it, return via",
    "    // hex.tables.ret after the stock clean-table undoes the index",
    "    def jcall idx, dsp @ return < hex.tables.ret {",
    "        rep(2, i) hex.xor dsp + 4*i, idx + i*dw",
    "        wflip hex.tables.ret+w, return, dsp",
    "      return:",
    "        wflip hex.tables.ret+w, return",
    "    }",
    "}",
]


def stub_table(label, n, stub):
    """per-entity stubs behind a pad-n table. stub(e) -> lines of entity e's stub."""
    t = [";%s_end" % label, "%s_dsp: ;%s_sw" % (label, label), "pad %d" % n, "%s_sw:" % label]
    t += [";%s_s%d" % (label, e) for e in range(n)]
    for e in range(n):
        t += ["%s_s%d:" % (label, e)] + ["    " + ln for ln in stub(e)] + \
             ["    ;%s_clean + %d*dw" % (label, e)]
    t += ["%s_clean:" % label,
          "    hex.tables.clean_table_entry__table %d, %s_dsp, hex.tables.ret" % (n, label),
          "%s_end:" % label]
    return t


def _eidx_pre(n):
    pre = ["hex.inc 2, gp_ei"]
    if n == 64:
        pre += ["hex.if_flags gp_ei+dw, 0x0010, gp_ewk, gp_ewz", "gp_ewz:",
                "hex.zero gp_ei+dw", "gp_ewk:"]
    return pre


def idx_probes(mutate_stub=False):
    out = []
    for n in (64, 256):
        pre = _eidx_pre(n)
        seq = lambda k, n_=n: (k + 1) % n_                        # noqa: E731 -- eidx at the body
        for pay in ("byte", "4nib"):
            nb = 1 if pay == "byte" else 2
            pv = _plant if pay == "byte" else _plant4
            for op in ("read", "write"):
                wpre = ["hex.mov %d, gp_ws, _mcnt" % (2 * nb)] if op == "write" else []

                def exp_read(k_n, pv=pv, nb=nb, seq=seq):
                    return b"".join(le_bytes(pv(seq(k)), nb) for k in range(k_n))

                def final_vals(k_n, pv=pv, nb=nb, seq=seq, n=n):
                    v = {e: pv(e) for e in range(n)}
                    for k in range(k_n):
                        v[seq(k)] = k & (0xFF if nb == 1 else 0xFFFF)
                    return v

                # ---- today: ptr_index + read_byte/write_byte (1 cell per byte), or a 16-cell
                # record read with read_hex/write_hex after a x16 index (bind_things' pattern)
                if pay == "byte":
                    data = ["gp_arr:"] + [";%d*dw" % _plant(e) for e in range(n)] + \
                           ["gp_base: hex.vec 8, gp_arr"]
                    idxl = ["hex.ptr_index gp_p, gp_base, gp_ei"]
                    acc = ["hex.read_byte gp_rb, gp_p"] if op == "read" else \
                          ["hex.write_byte gp_p, gp_ws"]

                    def mchk(mem, k_n, fv=final_vals, n=n):
                        want = fv(k_n)
                        bad = [e for e in range(n) if mem.byte_cell("gp_arr", e) != want[e]]
                        return (not bad), "entities wrong: %s" % bad[:5]
                else:
                    data = ["gp_arr:"] + ["hex.vec 16, 0x%x" % _plant4(e) for e in range(n)] + \
                           ["gp_base: hex.vec 8, gp_arr"]
                    idxl = ["hex.mov 8, gp_off, gp_ei", "hex.shl_hex 8, 1, gp_off",
                            "hex.ptr_index gp_p, gp_base, gp_off"]
                    acc = ["hex.read_hex 4, gp_rb, gp_p"] if op == "read" else \
                          ["hex.write_hex 4, gp_p, gp_ws"]

                    def mchk(mem, k_n, fv=final_vals, n=n):
                        want = fv(k_n)
                        bad = [e for e in range(n) if mem.hexv("gp_arr", 4, 16 * e) != want[e]]
                        return (not bad), "entities wrong: %s" % bad[:5]
                data += ["gp_ei: hex.vec 8", "gp_p: hex.vec 8", "gp_off: hex.vec 8",
                         "gp_rb: hex.vec 4", "gp_ws: hex.vec 4"]
                pr = ["hex.print %d, gp_rb" % nb] if op == "read" else []
                out.append(Probe(
                    "idx %s %s E=%d ptr" % (op, pay, n), body=idxl + acc, pre=pre + wpre,
                    data=data, verify=pr, expected=exp_read if op == "read" else None,
                    mem_check=None if op == "read" else mchk,
                    note="today: ptr_index + %s" % acc[0].split()[0]))

                # ---- the jump: a table on the index into per-entity stubs on FIXED cells
                w = 2 * nb

                def stub(e, op=op, w=w):
                    src = e + 1 if (mutate_stub and e == 5) else e
                    return (["hex.mov %d, gp_rb, gp_je%d" % (w, src)] if op == "read"
                            else ["hex.mov %d, gp_je%d, gp_ws" % (w, e)])

                jdata = ["gp_je%d: hex.vec %d, 0x%x" % (e, w, pv(e)) for e in range(n)] + \
                        ["gp_je%d: hex.vec %d" % (n, w)] + \
                        ["gp_ei: hex.vec 8", "gp_rb: hex.vec 4", "gp_ws: hex.vec 4"]

                def jchk(mem, k_n, fv=final_vals, n=n, w=w):
                    want = fv(k_n)
                    bad = [e for e in range(n) if mem.hexv("gp_je%d" % e, w) != want[e]]
                    return (not bad), "entities wrong: %s" % bad[:5]
                out.append(Probe(
                    "idx %s %s E=%d jump" % (op, pay, n), body=["gp.jcall gp_ei, gp_jt_dsp"],
                    pre=pre + wpre, prelude=PRELUDE_JCALL, tables=stub_table("gp_jt", n, stub),
                    data=jdata, verify=pr, expected=exp_read if op == "read" else None,
                    mem_check=None if op == "read" else jchk,
                    note="jump on the index into %d stubs (hex.mov %d on a fixed cell)" % (n, w)))
    return out


def window_probes():
    """plan 6.1: a heavy act copies the monster's ~27 state nibbles into a fixed window and back
    (modelled ~3K). Both mechanisms, E=64, 27 nibbles each way."""
    n, w = 64, 27
    pre = _eidx_pre(n)
    seq = lambda k: (k + 1) % n                                             # noqa: E731
    val = lambda e: (e * 0x9E3779B97F4A7C15 + 0x123456789ABCDEF) & ((1 << (4 * w)) - 1)  # noqa: E731
    exp = lambda k_n: b"".join(le_bytes(val(seq(k)), 14) for k in range(k_n))           # noqa: E731

    def fin(k_n):
        v = {e: val(e) for e in range(n)}
        for k in range(k_n):
            v[seq(k)] = (val(seq(k)) ^ 0x5) & ((1 << (4 * w)) - 1)
        return v
    out = []
    # the jump: stub e copies its fixed 27-nibble block into / out of the window
    for op in ("in", "out"):
        def stub(e, op=op):
            return (["hex.mov %d, gp_win, gp_we%d" % (w, e)] if op == "in"
                    else ["hex.mov %d, gp_we%d, gp_win" % (w, e)])
        data = ["gp_we%d: hex.vec %d, 0x%x" % (e, w, val(e)) for e in range(n)] +                ["gp_ei: hex.vec 8", "gp_win: hex.vec 28"]
        if op == "in":
            out.append(Probe("window copy-in 27 nibbles E=64 jump", body=["gp.jcall gp_ei, gp_jt_dsp"],
                             pre=pre, prelude=PRELUDE_JCALL, tables=stub_table("gp_jt", n, stub),
                             data=data, verify=["hex.print 14, gp_win"], expected=exp,
                             note="stub: hex.mov 27 from the monster's fixed cells"))
        else:
            def jchk(mem, k_n):
                want = fin(k_n)
                bad = [e for e in range(n) if mem.hexv("gp_we%d" % e, w) != want[e]]
                return (not bad), "entities wrong: %s" % bad[:5]
            out.append(Probe("window copy-out 27 nibbles E=64 jump", body=["gp.jcall gp_ei, gp_jt_dsp"],
                             pre=pre + ["gp_wv.lookup gp_win, gp_ei"],
                             prelude=PRELUDE_JCALL, tables=stub_table("gp_jt", n, stub) +
                             d4("gp_wv", [val(e) ^ 0x5 for e in range(n)], 2, w),
                             data=data, mem_check=jchk, note="stub: hex.mov 27 into the fixed cells"))
    # today's way: ptr_index on a 32-cell record + read_hex / write_hex 27
    data = ["gp_arr:"] + ["hex.vec 32, 0x%x" % val(e) for e in range(n)] +            ["gp_base: hex.vec 8, gp_arr", "gp_ei: hex.vec 8", "gp_p: hex.vec 8", "gp_off: hex.vec 8",
            "gp_win: hex.vec 28"]
    idxl = ["hex.mov 8, gp_off, gp_ei", "hex.shl_hex 8, 1, gp_off", "hex.shl_bit 8, gp_off",
            "hex.ptr_index gp_p, gp_base, gp_off"]
    out.append(Probe("window copy-in 27 nibbles E=64 ptr", body=idxl + ["hex.read_hex %d, gp_win, gp_p" % w],
                     pre=pre, data=data, verify=["hex.print 14, gp_win"], expected=exp,
                     note="ptr_index + read_hex 27"))

    def pchk(mem, k_n):
        want = fin(k_n)
        bad = [e for e in range(n) if mem.hexv("gp_arr", w, 32 * e) != want[e]]
        return (not bad), "entities wrong: %s" % bad[:5]
    out.append(Probe("window copy-out 27 nibbles E=64 ptr", body=idxl + ["hex.write_hex %d, gp_p, gp_win" % w],
                     pre=pre + ["gp_wv.lookup gp_win, gp_ei"],
                     tables=d4("gp_wv", [val(e) ^ 0x5 for e in range(n)], 2, w),
                     data=data, mem_check=pchk, note="ptr_index + write_hex 27"))
    return out


def mutated_stub_probe():
    p = [q for q in idx_probes(mutate_stub=True) if q.name == "idx read byte E=64 jump"][0]
    p.note = "a stub table whose stub 5 reads entity 6"
    return p


# =============================================================================================
# 3. D4 lookup: 1, 2, 4 result nibbles from a 1- or 2-nibble index
# =============================================================================================
def d4_probes(mutate=False):
    out = []
    rnd = random.Random(4)
    for idx_n in (1, 2):
        for res_n in (1, 2, 4):
            vals = [rnd.randrange(16 ** res_n) for _ in range(16 ** idx_n)]
            used = list(vals)
            if mutate:
                used[3] ^= 1
            nb = 1 if res_n <= 2 else 2
            mask = 16 ** idx_n - 1
            out.append(Probe(
                "d4 idx%d -> res%d" % (idx_n, res_n), body=["gp_t.lookup gp_d, _mcnt"],
                tables=d4("gp_t", used, idx_n, res_n), data=["gp_d: hex.vec 4"],
                verify=["hex.print %d, gp_d" % nb],
                expected=(lambda n, v=vals, m=mask, nb=nb:
                          b"".join(le_bytes(v[k & m], nb) for k in range(n))),
                note="doomfj generate_dispatch_table_fj, per-entry, %d entries" % (16 ** idx_n)))
    return out


def mutated_d4_probe():
    p = [q for q in d4_probes(mutate=True) if q.name == "d4 idx2 -> res2"][0]
    p.note = "a D4 table with entry 3 flipped"
    return p


# =============================================================================================
# 4a. one candidate line: today's sim.check_line vs the line's constants baked as code
# =============================================================================================
from doomfj.collision import (COLLISION_STATE_DECLS, LINE_BOX_BYTES, LINE_BOX_LEN,  # noqa: E402
                              LINE_REST_BYTES, LINE_REST_LEN, ST_HORIZONTAL, ST_NEGATIVE,
                              ST_POSITIVE, ST_VERTICAL, FLAG_ONE_SIDED, line_box, line_rest,
                              _RowBake)

BOX = (1000, 500, 16)            # the player's box: centre x, y and radius, in map units
SEED_F, SEED_C = 0, 256          # the opening seeds


def _row(v1, v2, flags, opentop=0, openbottom=0):
    (v1x, v1y), (v2x, v2y) = v1, v2
    dx, dy = v2x - v1x, v2y - v1y
    slope = (ST_HORIZONTAL if dy == 0 else ST_VERTICAL if dx == 0 else
             ST_POSITIVE if (dy > 0) == (dx > 0) else ST_NEGATIVE)
    return (v1x, v1y, dx, dy, min(v1x, v2x), max(v1x, v2x), min(v1y, v2y), max(v1y, v2y),
            slope, flags, opentop, openbottom)


LINE_CASES = [   # (tag, row, what it exercises)
    ("L1", _row((1100, 400), (1100, 600), FLAG_ONE_SIDED), "bbox reject on the 1st compare"),
    ("L2", _row((900, 400), (1100, 400), FLAG_ONE_SIDED), "bbox reject on the 4th compare"),
    ("L3", _row((900, 500), (1100, 500), FLAG_ONE_SIDED), "axis line straddled -> blocked"),
    ("L4", _row((950, 450), (1050, 550), 0, 128, 8), "diagonal straddled, two-sided -> opening"),
    ("L5", _row((1010, 400), (1100, 490), 0, 128, 8), "diagonal, bbox passes, no straddle"),
]


def _line_model(row):
    """(blocked, floor, ceil) -- check_position_table's per-line rule, for ONE line."""
    cx, cy, r = BOX
    bx_lo, bx_hi, by_lo, by_hi = (cx - r) << 16, (cx + r) << 16, (cy - r) << 16, (cy + r) << 16
    (v1x, v1y, dx, dy, minx, maxx, miny, maxy, slope, flags, ot, ob) = row
    if (bx_hi <= minx << 16 or bx_lo >= maxx << 16 or by_hi <= miny << 16 or by_lo >= maxy << 16):
        return False, SEED_F, SEED_C
    if _RowBake(v1x << 16, v1y << 16, dx << 16, dy << 16, slope).box_side(
            (by_hi, by_lo, bx_lo, bx_hi)) != -1:
        return False, SEED_F, SEED_C
    if flags:
        return True, SEED_F, SEED_C
    return False, max(SEED_F, ob), min(SEED_C, ot)


def _line_setup():
    cx, cy, r = BOX
    return ["hex.set 8, cbx_lo, 0x%x" % (((cx - r) << 16) & M32),
            "hex.set 8, cbx_hi, 0x%x" % (((cx + r) << 16) & M32),
            "hex.set 8, cby_lo, 0x%x" % (((cy - r) << 16) & M32),
            "hex.set 8, cby_hi, 0x%x" % (((cy + r) << 16) & M32)]


LINE_PRE = ["hex.set 8, cp_floor, %d" % SEED_F, "hex.set 8, cp_ceil, %d" % SEED_C]
LINE_VERIFY = [";gp_lv_ok", "gp_lv_blk:", "hex.set 2, gp_vb, 0xB", ";gp_lv_pr",
               "gp_lv_ok:", "hex.set 2, gp_vb, 0xA", "gp_lv_pr:",
               "hex.print gp_vb", "hex.print cp_floor", "hex.print cp_ceil"]


def _pack(vals, widths):
    v = sh = 0
    for x, nb in zip(vals, widths):
        v |= (x & ((1 << (8 * nb)) - 1)) << sh
        sh += 8 * nb
    return v


PRELUDE_PS = [
    "ns gp {",
    "    // sim.point_side with l's fixed_mul OPERANDS SWAPPED so the baked constant dyi is the",
    "    // multiplier (fixed_mul_lo runs one row per nonzero nibble of its SECOND operand; the",
    "    // low product commutes, so the value is identical). r already has dxi second. Cheap",
    "    // only for a NON-NEGATIVE constant (a negative one sign-extends to 8 dense nibbles).",
    "    def point_side_k side, x, y, v1x, v1y, dxi, dyi @ ax, ay, l, r, front, back, done, body {",
    "        ;body",
    "      ax: hex.vec 8",
    "      ay: hex.vec 8",
    "      l:  hex.vec 8",
    "      r:  hex.vec 8",
    "      body:",
    "        hex.mov 8, ax, x",
    "        hex.sub 8, ax, v1x",
    "        hex.mov 8, ay, y",
    "        hex.sub 8, ay, v1y",
    "        hex.fixed_mul_lo 8, 4, l, ax, dyi",
    "        hex.fixed_mul_lo 8, 4, r, dxi, ay",
    "        hex.scmp 8, r, l, front, back, back",
    "      front:",
    "        hex.set 1, side, 0",
    "        ;done",
    "      back:",
    "        hex.set 1, side, 1",
    "      done:",
    "    }",
    "}",
]


def baked_line(tag, row, blocked, nxt, swap=False):
    """ONE line's P_CheckLine with every line constant baked: constant cells, no table read, the
    slope switch and the one-sided test resolved at emit time."""
    (v1x, v1y, dx, dy, minx, maxx, miny, maxy, slope, flags, ot, ob) = row
    k = lambda s: tag + s                                     # noqa: E731
    code = [
        "hex.scmp 8, cbx_hi, %s, %s, %s, %s" % (k("minx"), nxt, nxt, k("ka")), k("ka") + ":",
        "hex.scmp 8, cbx_lo, %s, %s, %s, %s" % (k("maxx"), k("kb"), nxt, nxt), k("kb") + ":",
        "hex.scmp 8, cby_hi, %s, %s, %s, %s" % (k("miny"), nxt, nxt, k("kc")), k("kc") + ":",
        "hex.scmp 8, cby_lo, %s, %s, %s, %s" % (k("maxy"), k("kd"), nxt, nxt), k("kd") + ":",
    ]
    if slope == ST_HORIZONTAL:
        code += ["hex.scmp 8, cby_hi, %s, %s, %s, %s" % (k("v1y"), nxt, nxt, k("h1")), k("h1") + ":",
                 "hex.scmp 8, cby_lo, %s, %s, %s, %s" % (k("v1y"), k("hit"), k("hit"), nxt)]
    elif slope == ST_VERTICAL:
        code += ["hex.scmp 8, cbx_hi, %s, %s, %s, %s" % (k("v1x"), nxt, k("v1c"), k("v1c")),
                 k("v1c") + ":",
                 "hex.scmp 8, cbx_lo, %s, %s, %s, %s" % (k("v1x"), k("hit"), nxt, nxt)]
    else:
        ps = "gp.point_side_k" if swap else "sim.point_side"
        c1, c2 = (("cbx_lo", "cby_hi"), ("cbx_hi", "cby_lo")) if slope == ST_POSITIVE else \
                 (("cbx_hi", "cby_hi"), ("cbx_lo", "cby_lo"))
        code += ["%s cl_side1, %s, %s, %s, %s, %s, %s" % (ps, c1[0], c1[1], k("v1x"), k("v1y"),
                                                          k("dx"), k("dy")),
                 "%s cl_side2, %s, %s, %s, %s, %s, %s" % (ps, c2[0], c2[1], k("v1x"), k("v1y"),
                                                          k("dx"), k("dy")),
                 "hex.cmp 1, cl_side1, cl_side2, %s, %s, %s" % (k("hit"), nxt, k("hit"))]
    code += [k("hit") + ":"]
    if flags:
        code += [";" + blocked]
    else:
        code += ["hex.scmp 8, %s, cp_floor, %s, %s, %s" % (k("ob"), k("oc"), k("oc"), k("sf")),
                 k("sf") + ":", "hex.mov 8, cp_floor, " + k("ob"), k("oc") + ":",
                 "hex.scmp 8, %s, cp_ceil, %s, %s, %s" % (k("ot"), k("sc"), nxt, nxt),
                 k("sc") + ":", "hex.mov 8, cp_ceil, " + k("ot")]
    data = ["%s: hex.vec 8, 0x%x" % (k(nm), val & M32) for nm, val in (
        ("minx", minx << 16), ("maxx", maxx << 16), ("miny", miny << 16), ("maxy", maxy << 16),
        ("v1x", v1x << 16), ("v1y", v1y << 16), ("dx", dx), ("dy", dy), ("ob", ob), ("ot", ot))]
    return code, data


def line_probes():
    out = []
    rows = [c[1] for c in LINE_CASES]
    tables = (generate_packed_lut_fj("lnbox", [_pack(line_box(r), LINE_BOX_BYTES) for r in rows],
                                     LINE_BOX_LEN).splitlines() +
              generate_packed_lut_fj("lnrow", [_pack(line_rest(r), LINE_REST_BYTES) for r in rows],
                                     LINE_REST_LEN).splitlines())
    base_data = list(COLLISION_STATE_DECLS) + ["gp_vb: hex.vec 2", "gp_li: hex.vec 1"]
    for i, (tag, row, what) in enumerate(LINE_CASES):
        blk, fl, cl = _line_model(row)
        exp = (lambda n, b=blk, fl=fl, cl=cl:
               bytes([0xB if b else 0xA, fl & 0xFF, cl & 0xFF]) * n)
        out.append(Probe(
            "line %s today: sim.check_line" % tag,
            body=["sim.check_line lnbox, lnrow, 1, gp_li, gp_lv_blk", "gp_lv_blk:"],
            vbody=["sim.check_line lnbox, lnrow, 1, gp_li, gp_lv_blk"],
            setup=_line_setup() + ["hex.set 1, gp_li, %d" % i], pre=LINE_PRE, blob=tables,
            data=base_data, files=[CONSTS, FIXED, SIM], verify=LINE_VERIFY, expected=exp,
            note=what))
        for swap in ((False, True) if row[8] in (ST_POSITIVE,) else (False,)):
            code, cdata = baked_line("gp_k_", row, "gp_lv_blk", "gp_k_nxt", swap=swap)
            out.append(Probe(
                "line %s baked%s" % (tag, " (const multiplier)" if swap else ""),
                body=code + ["gp_k_nxt:", "gp_lv_blk:"], vbody=code + ["gp_k_nxt:"],
                setup=_line_setup(), pre=LINE_PRE,
                prelude=PRELUDE_PS if swap else [], data=base_data + cdata, files=[CONSTS, FIXED, SIM],
                verify=LINE_VERIFY, expected=exp, note=what))
    return out


# =============================================================================================
# 4b. the 32-unit cell of a 16.16 position, by jumps on its coordinate nibbles
# 5.  point location: a jump on the cell into the deepest safe BSP node, vs the full descent
# =============================================================================================
PRELUDE_J16 = [
    "ns gp {",
    "    // a 16-way jump on one hex cell, in the table shape the BlockPool can relocate: `pad 16`,",
    "    // sixteen plain `a;b` entries, then a wflip naming the head label. Each trampoline",
    "    // disarms the cell and jumps on (so a pinned cell pays only the index both ways).",
    "    def jump16 x, " + ", ".join("t%d" % i for i in range(16)) +
    " @ switch, " + ", ".join("r%d" % i for i in range(16)) + " {",
    "        wflip x+w, switch, x",
    "        pad 16",
    "      switch:",
    *["        ;r%d" % i for i in range(16)],
    *["      r%d: wflip x+w, switch, t%d" % (i, i) for i in range(16)],
    "    }",
    "}",
]


def _nib(v, i):
    return (v >> (4 * i)) & 0xF


def sgn12(p):
    """the 12-bit prefix a 3-level nibble tree spells (value >> 4), as a signed number"""
    return p - 0x1000 if p & 0x800 else p


def jump_tree(tag, cell, nibs, keys, leaf, default):
    """A tree of gp.jump16 on nibbles `nibs` (most significant first) of `cell`. `keys`: the set of
    integer values to separate (the tree splits on their nibbles); `leaf(prefix_value) -> label`
    for the value the full path spells. Returns (code lines, root label)."""
    code = []

    def node(prefix, depth, vals):
        lab = "%s_%d_%x" % (tag, depth, prefix)
        if depth == len(nibs):
            return leaf(prefix)
        nib = nibs[depth]
        targets = []
        for d in range(16):
            sub = [v for v in vals if _nib(v, nib) == d]
            targets.append(node((prefix << 4) | d, depth + 1, sub) if sub else default)
        code[:0] = []
        code.extend(["%s:" % lab, "    gp.jump16 %s+%d*dw, %s" % (cell, nib, ", ".join(targets))])
        return lab
    root = node(0, 0, sorted(set(keys)))
    return code, root


def _e1m1():
    from doomfj.config import DEFAULT_MAP_WAD
    from doomfj.wad import WadFile
    from doomfj.mapcompiler import bake_bsp
    w = WadFile.from_path(DEFAULT_MAP_WAD)
    return w, bake_bsp(w, "E1M1")


def cell_probes():
    """4b: the cell of a 16.16 position, by jumps on nibbles 7, 6, 5 of x then of y."""
    _w, cmap = _e1m1()
    xs = [v[0] for v in cmap.vertexes]
    ys = [v[1] for v in cmap.vertexes]
    X0, X1, Y0, Y1 = min(xs), max(xs), min(ys), max(ys)
    rnd = random.Random(5)
    pts = [(rnd.randint(X0, X1), rnd.randint(Y0, Y1)) for _ in range(256)]
    xkeys = {(x & 0xFFFF) >> 4 << 4 for x in range(X0, X1 + 1)}      # 16.16 integer part, per 16u
    ykeys = {(y & 0xFFFF) >> 4 << 4 for y in range(Y0, Y1 + 1)}

    def cid(x, y):
        return (((x >> 5) & 0xFF) | (((y >> 5) & 0xFF) << 8))

    probes = []
    for verify_ids in (False, True):
        code = []
        # the y-tree of every x-cell; its leaves are the cells
        xcells = sorted({x >> 5 for x in range(X0, X1 + 1)})
        yroot_of = {}
        for cx in xcells:
            yc, yroot = jump_tree("gp_cy%x" % (cx & 0xFFF), "gp_y", (7, 6, 5),
                                  {(k << 16) for k in ykeys},
                                  lambda pfx, cx=cx: "gp_cl_%x_%x" % (cx & 0xFFF,
                                                                      (sgn12(pfx) >> 1) & 0xFFF),
                                  "gp_cdone")
            code += yc
            yroot_of[cx] = yroot
        xc, xroot = jump_tree("gp_cx", "gp_x", (7, 6, 5), {(k << 16) for k in xkeys},
                              lambda pfx: yroot_of.get(sgn12(pfx) >> 1, "gp_cdone"),
                              "gp_cdone")
        code += xc
        # the leaves: in the timing build a cell is just a jump on; in the verify build it says
        # which cell it is
        for cx in xcells:
            for cy in sorted({y >> 5 for y in range(Y0, Y1 + 1)}):
                lab = "gp_cl_%x_%x" % (cx & 0xFFF, cy & 0xFFF)
                code += ["%s:" % lab] + (["    hex.set 4, gp_cid, 0x%x" % cid(cx << 5, cy << 5)]
                                         if verify_ids else []) + ["    ;gp_cdone"]
        probes.append(code)
    return pts, probes, cid


def cell_lookup_probes():
    pts, (code_t, code_v), cid = cell_probes()
    px = [((x & 0xFFFF) << 16) for x, y in pts]
    py = [((y & 0xFFFF) << 16) for x, y in pts]
    exp = lambda n: b"".join(le_bytes(cid(*pts[k & 255]), 2) for k in range(n))   # noqa: E731
    out = []
    for name, extra in (("cell lookup: 6 jump16 levels", ()),):
        p = Probe(name, body=[";gp_cx_0_0", "gp_cdone:"],
                  pre=["gp_px.lookup gp_x, _mcnt", "gp_py.lookup gp_y, _mcnt"],
                  tables=d4("gp_px", px, 2, 8) + d4("gp_py", py, 2, 8),
                  prelude=PRELUDE_J16, blob=code_t,
                  data=["gp_x: hex.vec 8", "gp_y: hex.vec 8", "gp_cid: hex.vec 4"],
                  extra_safe=("gp.jump16",),
                  note="x nibbles 7,6,5 then y nibbles 7,6,5 of 16.16 positions; E1M1 extent")
        pv = Probe(name + " [verify]", body=[";gp_cx_0_0", "gp_cdone:"], pre=p.pre,
                   tables=p.tables, prelude=PRELUDE_J16, blob=code_v, data=p.data,
                   extra_safe=p.extra_safe, verify=["hex.print 2, gp_cid"], expected=exp)
        p.expected, p._vprobe = None, pv
        out.append(p)
    return out


def ptloc_probes():
    """5: full BSP descent vs a jump on the 32-unit cell into the deepest node no point of the
    cell straddles (grid_ptloc.py's rule, exact by linearity over the cell's 4 corners)."""
    from doomfj.collision import generate_point_location_fj, point_location_decls
    from doomfj.mapcompiler import NF_SUBSECTOR, _point_side, seg_sector
    w, cmap = _e1m1()
    M = "E1M1"
    lds, sds, secs = w.linedefs(M), w.sidedefs(M), w.sectors(M)
    xs = [v[0] for v in cmap.vertexes]
    ys = [v[1] for v in cmap.vertexes]
    X0, X1, Y0, Y1 = min(xs), max(xs), min(ys), max(ys)

    def descend(x, y, start):
        node, depth = start, 0
        while not node & NF_SUBSECTOR:
            n = cmap.nodes[node]
            node = n.left if _point_side(n.x, n.y, n.dx, n.dy, x, y) > 0 else n.right
            depth += 1
        return node & (NF_SUBSECTOR - 1), depth

    def cell_start(cx, cy):
        x0, y0 = cx << 5, cy << 5
        cs = ((x0, y0), (x0 + 31, y0), (x0, y0 + 31), (x0 + 31, y0 + 31))
        node = cmap.root
        while not node & NF_SUBSECTOR:
            n = cmap.nodes[node]
            sides = [_point_side(n.x, n.y, n.dx, n.dy, a, b) > 0 for a, b in cs]
            if all(sides):
                node = n.left
            elif not any(sides):
                node = n.right
            else:
                return node
        return node

    def lab(node):
        return ("ptloc_l%d" % (node & (NF_SUBSECTOR - 1)) if node & NF_SUBSECTOR
                else "ptloc_n%d" % node)

    def live(ss):
        s = cmap.subsectors[ss]
        if not s.numsegs:
            return False
        sec = seg_sector(lds, sds, secs, cmap.segs[s.firstseg])
        return sec.ceil_h > sec.floor_h

    rnd = random.Random(1)
    pts = []
    while len(pts) < 256:
        x, y = rnd.randint(X0, X1), rnd.randint(Y0, Y1)
        ss, dep = descend(x, y, cmap.root)
        if live(ss):
            pts.append((x, y, ss, dep))
    # the grid tree on ptx / pty (10-nibble signed MAP UNITS): nibbles 3, 2, 1 -> 32-unit cells
    xcells = sorted({x >> 5 for x in range(X0, X1 + 1)})
    ycells = sorted({y >> 5 for y in range(Y0, Y1 + 1)})
    xkeys = {x & 0xFFFF for x in range(X0, X1 + 1)}
    ykeys = {y & 0xFFFF for y in range(Y0, Y1 + 1)}
    code, starts = [], {}
    yroot_of = {}
    for cx in xcells:
        def leafy(pfx, cx=cx):
            cy = sgn12(pfx) >> 1                              # nibbles 3,2,1 = y >> 4
            if cy not in starts.setdefault(cx, {}):
                starts[cx][cy] = cell_start(cx, cy)
            return lab(starts[cx][cy])
        yc, yroot = jump_tree("gp_gy%x" % (cx & 0xFFF), "pty", (3, 2, 1), ykeys, leafy, "ptloc_walk")
        code += yc
        yroot_of[cx] = yroot

    def leafx(pfx):
        return yroot_of.get(sgn12(pfx) >> 1, "ptloc_walk")
    xc, xroot = jump_tree("gp_gx", "ptx", (3, 2, 1), xkeys, leafx, "ptloc_walk")
    code += xc
    res_depth = []
    for x, y, ss, dep in pts:
        st = starts.get(x >> 5, {}).get(y >> 5)
        if st is None:
            st = cell_start(x >> 5, y >> 5)
        s2, d2 = descend(x, y, st)
        assert s2 == ss
        res_depth.append(d2)
    ptloc = generate_point_location_fj(cmap).splitlines()
    decls = point_location_decls()
    px = [x & M40 for x, y, s, d in pts]
    py = [y & M40 for x, y, s, d in pts]
    pre = ["gp_px.lookup ptx, _mcnt", "gp_py.lookup pty, _mcnt"]
    tables = d4("gp_px", px, 2, 10) + d4("gp_py", py, 2, 10)
    exp = lambda n: b"".join(le_bytes(pts[k & 255][2], 2) for k in range(n))   # noqa: E731
    common = dict(pre=pre, tables=tables, prelude=PRELUDE_J16, data=decls, files=[CONSTS, FIXED],
                  verify=["hex.print 2, ptss"], expected=exp, extra_safe=("gp.jump16",))
    full = Probe("ptloc full descent (ptloc_walk)", body=["stl.fcall ptloc_walk, ptloc_ret"],
                 blob=ptloc + code, **common,
                 note="E1M1, 256 live points; mean depth %.1f" % (sum(p[3] for p in pts) / 256))
    grid = Probe("ptloc grid start (jump16 x3+x3 -> node)", body=["stl.fcall %s, ptloc_ret" % xroot],
                 blob=ptloc + code, **common,
                 note="residual depth %.1f" % (sum(res_depth) / 256))
    return [full, grid], (sum(p[3] for p in pts) / 256, sum(res_depth) / 256)


# =============================================================================================
# 6. the octant classifier   7. AproxDistance   8. the aim-window write
# =============================================================================================
OFFS = [(random.Random(6 + i).randint(-2048, 2048), random.Random(900 + i).randint(-2048, 2048))
        for i in range(256)]


def octant(dx, dy):
    ax, ay = abs(dx), abs(dy)
    sx, sy = dx < 0, dy < 0
    if ay * 256 < ax * 106:
        return 4 if sx else 0
    if ax * 256 < ay * 106:
        return 6 if sy else 2
    return {(False, False): 1, (True, False): 3, (True, True): 5, (False, True): 7}[(sx, sy)]


def aprox(dx, dy):
    ax, ay = abs(dx), abs(dy)
    return ax + ay - ((ax if ax < ay else ay) >> 1)


PRELUDE_OCT = [
    "ns gp {",
    "    // dst[:6] = src[:4] * 106 (0x6A) by shifts and adds: 106 = 6*17 + 4",
    "    def mul106 dst, src < gp_m2, gp_m4, gp_m6 {",
    "        hex.zero gp_m2+4*dw",
    "        hex.mov 4, gp_m2, src",
    "        hex.shl_bit 5, gp_m2",              # m2 = src*2
    "        hex.mov 5, gp_m4, gp_m2",
    "        hex.shl_bit 5, gp_m4",              # m4 = src*4
    "        hex.mov 5, gp_m6, gp_m2",
    "        hex.add 5, gp_m6, gp_m4",           # m6 = src*6
    "        hex.zero dst",
    "        hex.mov 5, dst+dw, gp_m6",          # dst = m6 << 4
    "        hex.add 6, dst, gp_m6",             # + m6
    "        hex.add 6, dst, gp_m4",             # + m4  -> src*106
    "    }",
    "    // |ay|*256 < |ax|*106 -> lx ; |ax|*256 < |ay|*106 -> ly ; else ld  (lazy: one multiply",
    "    // when the offset is near the x axis)",
    "    def octreg ax, ay, lx, ld, ly @ c2 < gp_ta, gp_tb {",
    "        .mul106 gp_ta, ax",
    "        hex.zero 2, gp_tb",
    "        hex.mov 4, gp_tb+2*dw, ay",
    "        hex.cmp 6, gp_tb, gp_ta, lx, c2, c2",
    "      c2:",
    "        .mul106 gp_ta, ay",
    "        hex.zero 2, gp_tb",
    "        hex.mov 4, gp_tb+2*dw, ax",
    "        hex.cmp 6, gp_tb, gp_ta, ly, ld, ld",
    "    }",
    "}",
]


def octant_probes():
    body = ["hex.mov 4, gp_ax, gp_dx", "hex.mov 4, gp_ay, gp_dy",
            "hex.sign 4, gp_dx, gp_on, gp_op"]
    for sx, lab in ((1, "gp_on"), (0, "gp_op")):
        body += ["%s:" % lab] + (["hex.neg 4, gp_ax"] if sx else []) + \
                ["hex.sign 4, gp_dy, %s_n, %s_p" % (lab, lab)]
        for sy in (1, 0):
            q = "%s_%s" % (lab, "n" if sy else "p")
            body += ["%s:" % q] + (["hex.neg 4, gp_ay"] if sy else []) + \
                    ["gp.octreg gp_ax, gp_ay, %s_x, %s_d, %s_y" % (q, q, q),
                     "%s_x:" % q, "hex.set 1, gp_o, %d" % (4 if sx else 0), ";gp_odone",
                     "%s_y:" % q, "hex.set 1, gp_o, %d" % (6 if sy else 2), ";gp_odone",
                     "%s_d:" % q, "hex.set 1, gp_o, %d" % {(0, 0): 1, (1, 0): 3, (1, 1): 5,
                                                           (0, 1): 7}[(sx, sy)], ";gp_odone"]
    body += ["gp_odone:"]
    dx = [d & 0xFFFF for d, e in OFFS]
    dy = [e & 0xFFFF for d, e in OFFS]
    return [Probe("octant: 2 signs + |d|*106 vs |d|*256 (lazy)", body=body,
                  pre=["gp_dxt.lookup gp_dx, _mcnt", "gp_dyt.lookup gp_dy, _mcnt"],
                  tables=d4("gp_dxt", dx, 2, 4) + d4("gp_dyt", dy, 2, 4), prelude=PRELUDE_OCT,
                  data=["gp_dx: hex.vec 4", "gp_dy: hex.vec 4", "gp_ax: hex.vec 4",
                        "gp_ay: hex.vec 4", "gp_o: hex.vec 2", "gp_m2: hex.vec 6",
                        "gp_m4: hex.vec 6", "gp_m6: hex.vec 6", "gp_ta: hex.vec 6",
                        "gp_tb: hex.vec 6"],
                  verify=["hex.print gp_o"],
                  expected=lambda n: bytes(octant(*OFFS[k & 255]) for k in range(n)),
                  note="offsets uniform in +-2048; exact integer test, no atan")]


def dist_probes():
    body = ["hex.mov 4, gp_ax, gp_dx", "hex.sign 4, gp_dx, gp_an1, gp_ap1", "gp_an1:",
            "hex.neg 4, gp_ax", "gp_ap1:",
            "hex.mov 4, gp_ay, gp_dy", "hex.sign 4, gp_dy, gp_an2, gp_ap2", "gp_an2:",
            "hex.neg 4, gp_ay", "gp_ap2:",
            "hex.cmp 4, gp_ax, gp_ay, gp_alt, gp_age, gp_age",
            "gp_alt:", "hex.mov 4, gp_h, gp_ax", ";gp_ahs",
            "gp_age:", "hex.mov 4, gp_h, gp_ay",
            "gp_ahs:", "hex.shr_bit 4, gp_h",
            "hex.mov 5, gp_d, gp_ax", "hex.add 5, gp_d, gp_ay", "hex.sub 5, gp_d, gp_h"]
    dx = [d & 0xFFFF for d, e in OFFS]
    dy = [e & 0xFFFF for d, e in OFFS]
    return [Probe("AproxDistance (16-bit map units)", body=body,
                  pre=["gp_dxt.lookup gp_dx, _mcnt", "gp_dyt.lookup gp_dy, _mcnt"],
                  tables=d4("gp_dxt", dx, 2, 4) + d4("gp_dyt", dy, 2, 4),
                  data=["gp_dx: hex.vec 4", "gp_dy: hex.vec 4", "gp_ax: hex.vec 5",
                        "gp_ay: hex.vec 5", "gp_h: hex.vec 5", "gp_d: hex.vec 5"],
                  verify=["hex.print 2, gp_d"],
                  expected=lambda n: b"".join(le_bytes(aprox(*OFFS[k & 255]), 2) for k in range(n)),
                  note="abs x2, cmp 4, shr_bit 4, add 5, sub 5")]


def aim_probes():
    out = []
    for name, pre, write, want in (
            ("aim: empty -> write a CONSTANT id", ["hex.zero 2, gp_aim"],
             "hex.xor_by 2, gp_aim, 0x2A", 0x2A),
            ("aim: empty -> write a RUNTIME id", ["hex.zero 2, gp_aim"],
             "hex.xor 2, gp_aim, gp_tid", 0x2A),
            ("aim: already taken -> skip", ["hex.set 2, gp_aim, 0x17"],
             "hex.xor_by 2, gp_aim, 0x2A", 0x17)):
        out.append(Probe(name, body=["hex.if0 2, gp_aim, gp_aw_e", ";gp_aw_d", "gp_aw_e:",
                                     write, "gp_aw_d:"],
                         pre=pre, data=["gp_aim: hex.vec 2", "gp_tid: hex.vec 2, 0x2A"],
                         verify=["hex.print gp_aim"], expected=lambda n, v=want: bytes([v]) * n,
                         note="hex.if0 2 on a fixed-address column cell"))
    return out


# =============================================================================================
# calib: the plan's in-game MEASURED primitives, re-measured in this harness
# =============================================================================================
def calib_probes():
    n = 64
    pre = _eidx_pre(n) + ["hex.mov 2, gp_ws, _mcnt"]
    data = ["gp_arr:"] + [";%d*dw" % _plant(e) for e in range(n)] + \
           ["gp_base: hex.vec 8, gp_arr", "gp_ei: hex.vec 8", "gp_p: hex.vec 8",
            "gp_rb: hex.vec 4", "gp_ws: hex.vec 4", "gp_a: hex.vec 8", "gp_b: hex.vec 8"]
    rnd = random.Random(7)
    va = [rnd.randrange(1 << 32) for _ in range(256)]
    vb = [rnd.randrange(1 << 32) for _ in range(256)]
    ab = ["gp_ta.lookup gp_a, _mcnt", "gp_tb.lookup gp_b, _mcnt"]
    abt = d4("gp_ta", va, 2, 8) + d4("gp_tb", vb, 2, 8)
    return [
        (Probe("calib hex.ptr_index (8 nibbles)", body=["hex.ptr_index gp_p, gp_base, gp_ei"],
               pre=pre, data=data), 846),
        (Probe("calib hex.read_byte via pointer", body=["hex.read_byte gp_rb, gp_p"],
               pre=pre + ["hex.ptr_index gp_p, gp_base, gp_ei"], data=data), 260),
        (Probe("calib hex.write_byte via pointer", body=["hex.write_byte gp_p, gp_ws"],
               pre=pre + ["hex.ptr_index gp_p, gp_base, gp_ei"], data=data), 504),
        (Probe("calib hex.cmp 1 nibble", body=["hex.cmp 1, gp_a, gp_b, gp_c1, gp_c1, gp_c1",
                                               "gp_c1:"], pre=ab, tables=abt, data=data), 40),
        (Probe("calib hex.scmp 8", body=["hex.scmp 8, gp_a, gp_b, gp_c2, gp_c2, gp_c2", "gp_c2:"],
               pre=ab, tables=abt, data=data), 249),
    ]


# =============================================================================================
# the run
# =============================================================================================
def _fmt(v):
    return "%9.1f" % v


def run_groups(names):
    rows = []

    def do(p, modes=F.MODES, check=True, vprobe=None):
        for m in modes:
            per, stats = F.measure(p, m)
            if check:
                ok, why = F.verify(vprobe or p, m)
            else:
                ok, why = None, "-"
            rows.append(dict(name=p.name, mode=m, per_call=per, ok=ok, why=why, note=p.note,
                             stats=stats))
            print("  %-46s %-5s %s   %-5s %s" % (p.name[:46], m, _fmt(per),
                                                 {True: "ok", False: "FAIL", None: "-"}[ok],
                                                 (why if ok is not True else "")[:60]), flush=True)

    if "calib" in names:
        print("calib -- the plan's in-game MEASURED unit costs, re-measured here")
        for p, game in calib_probes():
            p.note = "in-game MEASURED %d (plan section 3)" % game
            do(p, check=False)
    if "rng" in names:
        print("rng -- plan D10")
        for p in rng_probes():
            do(p)
    if "idx" in names:
        print("idx -- ptr_index + read/write vs a jump into per-entity stubs")
        for p in idx_probes():
            do(p)
    if "win" in names:
        print("win -- plan 6.1's heavy-act window copy (27 nibbles each way)")
        for p in window_probes():
            do(p)
    if "d4" in names:
        print("d4 -- doomfj D4 dispatch lookups")
        for p in d4_probes():
            do(p)
    if "line" in names:
        print("line -- one candidate line: today's sim.check_line vs baked constants")
        for p in line_probes():
            do(p)
    if "cell" in names:
        print("cell -- 32-unit cell of a 16.16 position by nibble jumps")
        for p in cell_lookup_probes():
            do(p, modes=("plain", "pool", "pool+"), vprobe=p._vprobe)
    if "ptloc" in names:
        print("ptloc -- point location: full descent vs a jump on the cell into the BSP")
        ps, (dfull, dres) = ptloc_probes()
        print("  (Python: mean depth full %.2f nodes, residual after the cell start %.2f)"
              % (dfull, dres))
        for p in ps:
            do(p, modes=("plain", "pool", "pool+"))
    if "octant" in names:
        print("octant")
        for p in octant_probes():
            do(p)
    if "dist" in names:
        print("dist")
        for p in dist_probes():
            do(p)
    if "aim" in names:
        print("aim")
        for p in aim_probes():
            do(p)
    return rows


ALL = ("calib", "rng", "idx", "win", "d4", "line", "cell", "ptloc", "octant", "dist", "aim")

if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if not a.startswith("-")] or list(ALL)
    print("S6 fj micro-probes -- MEASURED: python scratchpad/gp/probes/s6/probes.py %s"
          % " ".join(names))
    print("ops/call = exact executed-op delta per body call (fjprobe.py); plain = no pool, "
          "pool = the ship BlockPool; placement 0x%x" % F.PLACE)
    rows = run_groups(names)
    outp = HERE / ("results_%s.json" % "_".join(names) if names != list(ALL) else "results.json")
    outp.write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    bad = [r for r in rows if r["ok"] is False]
    print("wrote %s; %d rows, %d verification FAILURES" % (outp.name, len(rows), len(bad)))
    raise SystemExit(1 if bad else 0)
