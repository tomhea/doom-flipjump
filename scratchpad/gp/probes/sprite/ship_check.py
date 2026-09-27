"""⚠ SUPERSEDED (M7 P1.6, 2026-09-27) -- kept as P1.4's record; it no longer assembles. It builds
P1.4's bank blocks `[r0][last][n]` (plib.py) from P1.4-era oracle cases, writes the slot's byte 3 as
0, emits no `rowmap` table and passes thing_record_body's removed `buckets` / `nld` parameters, so it
cannot drive the P1.6 column. Its checks moved to tests/fj/test_sprite_bank_fj.py: the derive and
both run walkers (fast, clipped, and the window walker above and below a near fragment) against
`strip_at`, and the record's tier / slot / min_b section TRANSPLANTED from the shipped source, each
with R9 mutants. NOT carried over: the load (frame.lines_spr_load, unchanged since P1.4) and
emit_col_lines' whole A+B composition on real oracle frames -- the byte-exact gates (m3_gate,
m2_std_gate, deg_gate) are what see those now.

M7 P1.4 -- THE COLUMN CHECK: the SHIPPED sprite column, record -> load -> emit, against the oracle.

docs/gp-ledger.md P1.4, kill criterion 1. The prototype (t2_emit.py / t8_pipeline.py) compared its
own copies of the proposed macros with the renderer of the day; the proposal is the shipped code
now, so this runs the SHIPPED macros on every oracle case of a frame and requires each column to
equal the plain column with the ORACLE's fragments painted over it, far fragment first --
ReferenceModel.render_wall_frame's V4b order:

  A     every sprite column of the frame, one fragment (the cases t8_pipeline.py runs)
  A+B   every sprite column again with a SECOND, farther fragment behind it -- another case's,
        (i + n/2) mod n, recorded after the first with that case's own slot and block, so the
        record takes slot B exactly as the renderer's thing pass does (sprflag already 1) and the
        emit composes region | B-above | (gap) | A | (gap) | B-below | region

One fj program per frame and variant: pass 1 records every column -- the per-thing SLOT write
and the column loop TRANSPLANTED from frame.thing_record_body, so they cannot drift from the
source -- and pass 2 seeds, loads (the real frame.lines_spr_load) and emits (the real
stream.emit_col_lines) each column through one shared leaf.

CONTROLS (R9). Each mutates the shipped source TEXT and must make the check fail:
  M1  the derive's unbias off by one row           stream.frag_derive  32768 -> 32767
  M2  the record's bias off by one row             the slot write      32768 -> 32767
  M3  a run walk's FIRST read on the narrow arm    stream.frag_runs    (the prototype's caught bug:
      region 1's step face armed stepcol in between, so a 3-nibble re-arm lands in the wrong block)
  M4  slot B read one byte early                   lines_spr_load  `ptr_add spslot_p, 5` -> 4
And the EXPECTATION is checked on the renderer before P1.4 (`--base <rev>`): that revision's
record, load and emit must meet it too, A and A+B -- the harness wires the macros right.

    python scratchpad/gp/probes/sprite/ship_check.py                  # every fight frame
    python scratchpad/gp/probes/sprite/ship_check.py heavy:gate664    # one frame
    python scratchpad/gp/probes/sprite/ship_check.py --controls heavy:gate664
    python scratchpad/gp/probes/sprite/ship_check.py --base 46ab826 heavy:gate664
"""
import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plib                                                                  # noqa: E402

import flipjump as fj                                                        # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO                  # noqa: E402

H = plib.H
FJ_FILES = [s.name for s in plib.SRC]
# what P1.4 took out of wall_renderer.hoisted_scratch_decls() and what it put in -- so a --base run
# can declare the registers the older macros name (each is checked against that revision's text)
P14_REMOVED = ["p2_dssy1: hex.vec 2", "p2_dssy1b: hex.vec 2", "p2_dssy2: hex.vec 2",
               "p2_dssy2b: hex.vec 2", "p2_dsy0b: hex.vec 4", "p2_dsy0bb: hex.vec 4",
               "p2_slr: hex.vec 2", "p2_slrb: hex.vec 2", "p2_ssy1: hex.vec 2", "p2_ssy1b: hex.vec 2",
               "p2_ssy2: hex.vec 2", "p2_ssy2b: hex.vec 2", "p2_sy0b: hex.vec 4", "p2_sy0bb: hex.vec 4",
               "trb_blk_ofs: hex.vec w/4", "trb_run_r0: hex.vec 2", "trb_run_w8: hex.vec 8",
               "trb_sy1: hex.vec 8", "trb_sy2: hex.vec 8", "trb_y0_biased: hex.vec 8",
               "trb_y_base: hex.vec 8"] + \
              ["srw_%s: hex.vec %s" % kv for kv in (("ptr", "w/4"), ("rel", "2"), ("rel_w", "4"),
                                                   ("sbase", "w/4"), ("sidx", "w/4"), ("smidx", "4"),
                                                   ("tex", "2"), ("whi4", "4"), ("wlo4", "4"),
                                                   ("y0", "4"), ("yabs", "4"))] + \
              ["srn_%s: hex.vec %s" % kv for kv in (("cvh", "4"), ("ptr", "w/4"), ("rel", "2"),
                                                   ("rel_w", "4"), ("sbase", "w/4"), ("sidx", "w/4"),
                                                   ("smidx", "4"), ("tex", "2"), ("y0", "4"),
                                                   ("yabs", "4"))]


def name_of(decl):
    return decl.split(":")[0].strip()


def sources(rev):
    """{file: text} for the seven macro files, from the working tree or a git revision"""
    out = {}
    for f in FJ_FILES:
        if rev is None:
            out[f] = (plib.ROOT / "src/fj" / f).read_text(encoding="utf-8")
        else:
            out[f] = subprocess.run(["git", "-C", str(plib.ROOT), "show", "%s:src/fj/%s" % (rev, f)],
                                    capture_output=True, check=True).stdout.decode("utf-8")
    return out


def hoisted(rev):
    """the hoisted register declarations the macros of `rev` name"""
    now = plib.wr.hoisted_scratch_decls(plib.cfg)
    if rev is None:
        return now
    old_wr = subprocess.run(["git", "-C", str(plib.ROOT), "show", "%s:src/doomfj/wall_renderer.py" % rev],
                            capture_output=True, check=True).stdout.decode("utf-8")
    missing = [d for d in P14_REMOVED if '"%s"' % d not in old_wr]
    assert not missing, "%s's wall_renderer.py does not declare %s" % (rev, missing[:3])
    added = {name_of(d) for d in now} - {name_of(d) for d in re.findall(r'"([a-z0-9_]+: hex\.vec [^"]+)"', old_wr)}
    return [d for d in now if name_of(d) not in added] + P14_REMOVED


def transplant(frame_src, shipped):
    """the record's per-thing slot write (shipped only) and its column loop, as harness macros"""
    body = frame_src[frame_src.index("def thing_record_body"):]
    seg = body[body.index("      col_loop:"):body.index("      set_tstop:")]
    seg = seg.replace("rep(703, i) stl.fj 0, 0", "")      # the renderer's unreachable layout freeze
    code = "\n".join(l.split("//")[0] for l in seg.splitlines())
    glob = sorted(set(re.findall(r"\b(?:trb|gps)_[a-z0-9_]+\b", code)) | {"ballow", "hdfl", "sprbank", "spslot"})
    labels = ("col_loop, col_body, u_clamp, col_check, slot_check, slot_a, slot_b, slot_done, bucket_mul, "
              "bucket_mul_done, do_store, col_next, ret")
    params = "buckets, slotstride, deg, spn, nld" if shipped else "buckets, blkshift, slotstride, deg, spn, nld, viewh"
    out = "ns frame {\n    def gp_rec %s @ %s < %s {\n%s      ret:\n    }\n" % (params, labels, ", ".join(glob), seg)
    if shipped:
        a = body.index("        hex.inc 2, gps_nslot")
        slot = body[a:body.index("        // the column DDA", a)]
        sc = "\n".join(l.split("//")[0] for l in slot.splitlines())
        sglob = sorted(set(re.findall(r"\b(?:trb|gps)_[a-z0-9_]+\b", sc)) | {"gpslot"})
        out += "    def gp_slot < %s {\n%s    }\n" % (", ".join(sglob), slot)
    return out + "}\n"


HOT = ["drawn:"] + [";0 * dw"] * 160 + ["sprflag:"] + [";0 * dw"] * 160 + \
      ["spslot:"] + [";0 * dw"] * (160 * 16) + ["gp_armd: hex.vec 2", "gp_k: hex.vec 8",
                                             "hdfl: hex.vec 1", "ballow: hex.vec 1"]


def col_setup(fr, i, blk):
    c = fr.cases[i]
    return ["hex.set 8, trb_col_x, %d" % c["x"], "hex.set 8, trb_tx2, %d" % c["x"],
            "hex.set 8, trb_frac_u, 0", "hex.set 8, trb_tistep, 0", "hex.set 2, trb_dw_max, 20",
            "hex.set w/4, trb_drawn_b, drawn", "frame.ptr_index4 trb_drawn_p, trb_drawn_b, trb_col_x",
            "hex.set w/4, trb_sprflag_b, sprflag",
            "frame.ptr_index4 trb_sprflag_p, trb_sprflag_b, trb_col_x",
            "hex.set w/4, trb_blk_const, %d" % blk, "hex.set 1, hdfl, 1", "hex.set 1, ballow, 1"]


def thing_consts(fr, s):
    return ["hex.set 8, trb_y0, %d" % (fr.slot_y0[s - 1] & 0xFFFFFFFF),
            "hex.set 2, trb_shade_row, %d" % fr.slot_lr[s - 1]]


def partner(n, i):
    return (i + n // 2) % n


def record(fr, shipped, with_b):
    """pass 1: every A column in thing order (a new thing takes the next slot); then, for A+B,
    every column's B -- a later record into a column that already holds A, which is slot B"""
    n = len(fr.cases)
    rec = "frame.gp_rec 32, 16, 1, 1, 9" if shipped else "frame.gp_rec 32, 6, 16, 1, 1, 9, %d" % H
    pre = ["hex.set 2, gps_nslot, 0", "hex.set 2, gps_cur_s, 0"] if shipped else []
    for i in range(n):
        s = fr.slot_of[i]
        new_thing = i == 0 or s != fr.slot_of[i - 1]
        if shipped and new_thing:
            pre += thing_consts(fr, s) + ["frame.gp_slot"]
        pre += col_setup(fr, i, i) + ([] if shipped else thing_consts(fr, s))
        pre.append(rec)
    if with_b:
        for i in range(n):
            j = partner(n, i)
            s = fr.slot_of[j]
            pre += col_setup(fr, i, j)
            pre += (["hex.set 2, gps_s_rec, %d" % s] if shipped else thing_consts(fr, s))
            pre.append(rec)
    return pre


def leaf(shipped):
    head = ["hex.zero 8, gp_k", "hex.mov 2, gp_k, c_x", "frame.lines_spr_seed gp_k",
            "hex.read_byte gp_armd, p2_spfp"]           # a hot-block arm for the loaders' arm5 reads
    if shipped:
        load = "frame.lines_spr_load p2_sprfl, p2_s, p2_sblk, p2_sb, p2_sblkb"
        emit = ("stream.emit_col_lines %d, %d, 0, 0, 1, %d, 0, 1, 1, 1, 1, 1, 1, c_gnrow, c_x, c_cexcl, "
                "c_fstart, c_dummy2, c_dummy2, c_dummy2, c_dummy2, c_dummy2, c_dummy2, c_dummy2, "
                "c_dummy2, p2_sprfl, p2_s, p2_sblk, p2_sb, p2_sblkb, c_wlit, c_wlit2, c_wstrip, "
                "wstripbase, c_cbufa, c_cbufd, c_fbufa, c_fbufd" % (plib.cfg.CENTERY, H, plib.WPXSTRIDE))
    else:
        load = ("frame.lines_spr_load p2_sprfl, p2_ssy1, p2_ssy2, p2_sy0b, p2_sblk, p2_slr, p2_ssy1b, "
                "p2_ssy2b, p2_sy0bb, p2_sblkb, p2_slrb")
        emit = plib.TODAY_EMIT.replace(
            "c_sprfl, c_ssy1, c_ssy2, c_sy0b, c_sblk, c_slr, c_ssy1b, c_ssy2b, c_sy0bb, c_sblkb, c_slrb",
            "p2_sprfl, p2_ssy1, p2_ssy2, p2_sy0b, p2_sblk, p2_slr, p2_ssy1b, p2_ssy2b, p2_sy0bb, "
            "p2_sblkb, p2_slrb")
    return head + [load, emit]


def plain_leaf(shipped):
    return leaf(shipped)[:1] + [leaf(shipped)[-1].replace("p2_sprfl", "c_zero2")]


def program(fr, srcs, shipped, rev, with_b=False, plain=False):
    decls = [d for d in plib.common_decls() if name_of(d) not in {name_of(h) for h in hoisted(rev)}]
    decls += ["c_zero2: hex.vec 2"]
    text = plib.program(fr, plain_leaf(shipped) if plain else leaf(shipped), 1,
                        pre_loop=[] if plain else record(fr, shipped, with_b),
                        extra_text=transplant(srcs["frame_render.fj"], shipped),
                        hot_text="\n".join(HOT), prefilled_slots=False)
    # plib.program appends its own decls and the working tree's hoisted registers: swap in ours
    text = text.replace("\n".join(plib.common_decls()), "\n".join(decls), 1)
    text = text.replace(plib.wr.hoisted_scratch_fj(plib.cfg), "\n".join(hoisted(rev)), 1)
    return text


def run(text, srcs, name, tmp):
    consts = plib.cfg.emit_fj_consts(tmp / "fj_consts.fj")
    files = []
    for f in FJ_FILES:
        pth = tmp / f
        pth.write_text(srcs[f], encoding="utf-8")
        files.append(pth.resolve())
    prog = tmp / (name + ".fj")
    prog.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *files, prog.resolve()], out, memory_width=plib.W, print_time=False)
    io = FixedIO(b"")
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    cause = str(term.termination_cause)
    if "loop" not in cause.lower():                  # a crashed run ends early: never a result
        return None, "%s after %d ops" % (cause, term.op_counter)
    return plib.decode(io.get_output(allow_incomplete_output=True)), term.op_counter


def expected(fr, plain_col, i, j=None):
    px = dict(plain_col[1])
    if j is not None:
        px.update(fr.expected_sprite_rows(j))       # the far fragment first ...
    px.update(fr.expected_sprite_rows(i))           # ... the near one painted over it
    return (plain_col[0], px)


def check_frame(key, srcs, shipped, rev, tmp, variants=("A", "A+B")):
    fr = plib.Frame(plib.by_frame(plib.load_cases())[key])
    n = len(fr.cases)
    plain, err = run(program(fr, srcs, shipped, rev, plain=True), srcs, "plain", tmp)
    assert plain is not None, "the PLAIN column program crashed: %s" % err
    res = {}
    for v in variants:
        out, info = run(program(fr, srcs, shipped, rev, with_b=(v == "A+B")), srcs, v.replace("+", ""), tmp)
        if out is None:
            res[v] = (n, n, "CRASHED: " + info)
            continue
        bad = [i for i in range(n)
               if out[i] != expected(fr, plain[i], i, partner(n, i) if v == "A+B" else None)]
        res[v] = (len(bad), n, "%d ops" % info)
    return fr, res


def ab_shapes(fr):
    """how the A+B pairs sit, so the coverage is visible rather than assumed"""
    n = len(fr.cases)
    rows = lambda i: (max(0, min(H, fr.cases[i]["y_base"])),
                      max(0, min(H, fr.cases[i]["y_base"] + fr.cases[i]["runs"][-1][0])))
    shapes = {"B above and below A": 0, "B above A only": 0, "B below A only": 0, "B hidden by A": 0,
              "gap above A": 0, "gap below A": 0}
    for i in range(n):
        (a1, a2), (b1, b2) = rows(i), rows(partner(n, i))
        above, below = b1 < a1, b2 > a2
        shapes["B above and below A" if above and below else "B above A only" if above else
               "B below A only" if below else "B hidden by A"] += 1
        shapes["gap above A"] += b2 < a1
        shapes["gap below A"] += a2 < b1
    return shapes


MUTANTS = {
    "M1 derive unbias off by one": ("stream_render.fj", "hex.sub_constant 4, gps_y0, 32768",
                                    "hex.sub_constant 4, gps_y0, 32767", ("A", "A+B")),
    "M2 record bias off by one": ("frame_render.fj", "hex.add_constant 8, gps_yb8, 32768",
                                  "hex.add_constant 8, gps_yb8, 32767", ("A", "A+B")),
    "M3 first run read on the narrow arm": ("stream_render.fj",
                                            "      fast:\n        hex.read_byte_and_inc gps_rel, ptr",
                                            "      fast:\n        frame.read3_and_inc gps_rel, ptr",
                                            ("A",)),
    "M4 slot B read one byte early": ("frame_render.fj", "hex.ptr_add spslot_p, 5",
                                      "hex.ptr_add spslot_p, 4", ("A+B",)),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("frames", nargs="*", help="scen:vp (default: every fight frame)")
    ap.add_argument("--base", help="check a git revision's renderer instead (the pre-P1.4 macros)")
    ap.add_argument("--controls", action="store_true", help="run the four mutants instead")
    a = ap.parse_args()
    frames = [tuple(f.split(":")) for f in a.frames] or [k for k in plib.by_frame(plib.load_cases())
                                                         if k[0] != "static"]
    tmp = Path(tempfile.mkdtemp())
    if a.controls:
        srcs0 = sources(None)
        caught = 0
        for name, (f, old, new, variants) in MUTANTS.items():
            assert srcs0[f].count(old) == 1, "%s: the mutation no longer matches src/fj/%s" % (name, f)
            srcs = dict(srcs0, **{f: srcs0[f].replace(old, new)})
            bad = tot = 0
            for key in frames:
                _fr, res = check_frame(key, srcs, True, None, tmp, variants)
                bad += sum(r[0] for r in res.values())
                tot += sum(r[1] for r in res.values())
            caught += bad > 0
            print("CONTROL %-38s %s: %d/%d columns differ from the oracle" %
                  (name, "CAUGHT" if bad else "MISSED", bad, tot), flush=True)
        print("CONTROLS %s: %d/%d mutants caught" % ("PASS" if caught == len(MUTANTS) else "FAIL",
                                                     caught, len(MUTANTS)))
        return 0 if caught == len(MUTANTS) else 1
    srcs = sources(a.base)
    shipped = a.base is None
    what = "the SHIPPED macros (working tree)" if shipped else "the macros at %s" % a.base
    print("column check: %s, %d frame(s)" % (what, len(frames)), flush=True)
    tot = {"A": [0, 0], "A+B": [0, 0]}
    for key in frames:
        t0 = time.time()
        fr, res = check_frame(key, srcs, shipped, a.base, tmp)
        for v, (bad, n, info) in res.items():
            tot[v][0] += bad
            tot[v][1] += n
        print("  %-16s n=%3d  A: %d/%d differ (%s)  A+B: %d/%d differ (%s)  B vs A: %s  (%.0fs)" %
              ("%s:%s" % key, len(fr.cases), res["A"][0], res["A"][1], res["A"][2], res["A+B"][0],
               res["A+B"][1], res["A+B"][2],
               ", ".join("%s %d" % kv for kv in ab_shapes(fr).items() if kv[1]), time.time() - t0),
              flush=True)
    ok = tot["A"][0] == 0 and tot["A+B"][0] == 0
    print("COLUMN CHECK %s: A %d/%d columns equal the oracle, A+B %d/%d" %
          ("PASS" if ok else "FAIL", tot["A"][1] - tot["A"][0], tot["A"][1], tot["A+B"][1] - tot["A+B"][0],
           tot["A+B"][1]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
