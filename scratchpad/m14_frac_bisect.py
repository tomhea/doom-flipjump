"""M14 section 4b — bisect the fractional-position divergence at the KERNEL level.

The renderer is byte-exact at integer player positions and not at fractional ones, and the whole
question is WHICH projection kernel first disagrees. Doing that inside a renderer build costs 25
minutes a try; every kernel here assembles in seconds, because `tests/fj/test_projection_kernels.py`
already established the pattern (drive one macro over cases, print, diff against the oracle).

Every existing case in that file feeds `viewx = vxu * 65536` -- a WHOLE number of map units. This
drives the same macros with the low nibbles populated, which is the regime `step_sim` produces from
the player's second step onward.

⚠ SUPERSEDED IN PART (CR-2026-08, PJ-2): the abs/sign inputs no longer exist -- wall_x_range and
wall_x_range_m multiply the SIGNED view coord now, so this harness no longer stages them. The note
below is kept because it records why they were there. Historically: (`hex.mov viewxa, viewx;
hex.sign; hex.neg`), i.e. the absolute value of the FULL 16.16 quantity -- not `abs(units) << 16`,
which is what the integer-only cases could get away with.

    python scratchpad/m14_frac_bisect.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import (generate_dispatch_table_fj, generate_slopediv_recip8_lut_fj,
                                  generate_slopediv_recip_lut_fj, generate_tantoangle_lut_fj,
                                  generate_viewangletox_lut_fj)
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.mapcompiler import bake_bsp, seg_affine_coeffs
from doomfj.reference_model import ReferenceModel, SLOPERANGE
from doomfj.wad import WadFile

PROJ = ROOT / "src/fj/projection.fj"
FIXP = ROOT / "src/fj/fixed_point.fj"
U = 1 << 16
M32 = 0xFFFFFFFF
cmap = bake_bsp(WadFile.from_path(str(ROOT / "tests/fixtures/square_room.wad")), "MAP01")
rm = ReferenceModel()

# (viewx16, viewy16, viewangle, seg) -- the integer baselines from WXR_CASES, then the SAME points
# with a half unit, a quarter unit and one ulp added. If the integer rows pass and the fractional
# ones fail, this macro is the divergence.
_A90, _A45 = 0x40000000, 0x20000000
BASE = [(128, 128, 0, 2), (128, 128, _A90, 1), (200, 128, 0, 2), (128, 128, _A45, 2)]
FRACS = [("integer", 0), ("+1 ulp", 1), ("+1/4 unit", 0x4000), ("+1/2 unit", 0x8000),
         ("+0.99 unit", 0xFDFF)]


def cases():
    for tag, f in FRACS:
        for vxu, vyu, va, si in BASE:
            yield tag, (vxu * U) + f, (vyu * U) + f, va, si


def run_wall_x_range(tmp: Path):
    body, data, want = [], [], b""
    for k, (_tag, vx16, vy16, va, si) in enumerate(cases()):
        seg = cmap.segs[si]
        v1x, v1y = cmap.vertexes[seg.v1]
        v2x, v2y = cmap.vertexes[seg.v2]
        fa, fb, fc = seg_affine_coeffs(seg, cmap.vertexes)
        sx, sy = vx16 if vx16 < (1 << 31) else vx16 - (1 << 32), vy16
        # the emitter's own abs/sign derivation, on the FULL 16.16 value
        vxa, vxs = (abs(sx) & M32, 1 if sx < 0 else 0)
        vya, vys = (abs(sy) & M32, 1 if sy < 0 else 0)
        body += [f"proj.wall_x_range vis, x1, x2, rwa, sgnr, vx{k}, vy{k}, "
                 f"vxa{k}, vxs{k}, vya{k}, vys{k}, va{k}, a{k}, b{k}, c{k}, e{k}, fa{k}, fb{k}, fc{k}",
                 "hex.print_as_digit 1, vis, 0", "stl.output 10",
                 "hex.print_as_digit 8, x1, 0", "stl.output 10",
                 "hex.print_as_digit 8, x2, 0", "stl.output 10",
                 "hex.print_as_digit 8, rwa, 0", "stl.output 10"]
        data += [f"vx{k}: hex.vec 8, {vx16 & M32}", f"vy{k}: hex.vec 8, {vy16 & M32}",
                 f"vxa{k}: hex.vec 8, {vxa}", f"vxs{k}: hex.vec 1, {vxs}",
                 f"vya{k}: hex.vec 8, {vya}", f"vys{k}: hex.vec 1, {vys}",
                 f"va{k}: hex.vec 8, {va & M32}",
                 f"a{k}: hex.vec 8, {(v1x << 16) & M32}", f"b{k}: hex.vec 8, {(v1y << 16) & M32}",
                 f"c{k}: hex.vec 8, {(v2x << 16) & M32}", f"e{k}: hex.vec 8, {(v2y << 16) & M32}",
                 f"fa{k}: hex.vec 8, {fa}", f"fb{k}: hex.vec 8, {fb}", f"fc{k}: hex.vec 8, {fc}"]
        res = rm.wall_x_range(vx16, vy16, va, seg, cmap.vertexes)
        want += (b"0\n00000000\n00000000\n00000000\n" if res is None else
                 f"1\n{res[0] & M32:08x}\n{res[1] & M32:08x}\n{res[2]:08x}\n".encode())
    data += ["vis: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8", "sgnr: hex.vec 8",
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
             generate_slopediv_recip_lut_fj("slopediv_recip"),
             generate_slopediv_recip8_lut_fj("slopediv_recip8"),
             generate_viewangletox_lut_fj("viewangletox", Config().VIEW_W, Config().TRIG_N)]
    src = tmp / "wxr.fj"
    src.write_text("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
                   + "\n".join(data) + "\n", encoding="utf-8")
    out = tmp / "wxr.fjm"
    fj.assemble([FIXP.resolve(), PROJ.resolve(), src.resolve()], out, memory_width=W,
                print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True), want


def run_wall_setup(tmp: Path):
    """proj.wall_setup -> (rw_normalangle, rw_distance). rw_distance feeds EVERY column's scale, so a
    fractional-position error here becomes a row-boundary error everywhere in the frame."""
    body, data, want = [], [], b""
    for k, (_tag, vx16, vy16, _va, si) in enumerate(cases()):
        seg = cmap.segs[si]
        a, b, c = seg_affine_coeffs(seg, cmap.vertexes)
        body += [f"proj.wall_setup nrm, rwd, vx{k}, vy{k}, sa{k}, a{k}, b{k}, c{k}",
                 "hex.print_as_digit 8, nrm, 0", "stl.output 10",
                 "hex.print_as_digit 8, rwd, 0", "stl.output 10"]
        data += [f"vx{k}: hex.vec 8, {vx16 & M32}", f"vy{k}: hex.vec 8, {vy16 & M32}",
                 f"sa{k}: hex.vec 4, {seg.angle & 0xFFFF}",
                 f"a{k}: hex.vec 8, {a}", f"b{k}: hex.vec 8, {b}", f"c{k}: hex.vec 8, {c}"]
        nrm, rwd = rm.wall_setup(vx16, vy16, seg, cmap.vertexes)
        want += f"{nrm:08x}\n{rwd:08x}\n".encode()
    data += ["nrm: hex.vec 8", "rwd: hex.vec 8"]
    src = tmp / "wsetup.fj"
    src.write_text("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
                   + "\n".join(data) + "\n", encoding="utf-8")
    out = tmp / "wsetup.fjm"
    fj.assemble([FIXP.resolve(), PROJ.resolve(), src.resolve()], out, memory_width=W,
                print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True), want


def report(name, got, want, per):
    gl, wl = got.decode().split("\n"), want.decode().split("\n")
    bad_by_tag = {}
    for k, (tag, vx16, vy16, va, si) in enumerate(cases()):
        g, w = gl[per * k:per * k + per], wl[per * k:per * k + per]
        bad_by_tag.setdefault(tag, [0, 0])
        bad_by_tag[tag][1] += 1
        if g != w:
            bad_by_tag[tag][0] += 1
            print(f"  MISMATCH {tag:12s} view=({vx16 / U:.4f},{vy16 / U:.4f}) va={va:#x} seg={si}"
                  f"\n      fj     {g}\n      oracle {w}")
    print(f"\n{name} vs oracle:")
    for tag, (bad, tot) in bad_by_tag.items():
        print(f"  {tag:12s} {tot - bad}/{tot} exact")
    return all(b == 0 for b, _ in bad_by_tag.values())


def run_e1m1_segs(tmp: Path):
    """THE REAL REPRO, at kernel level. At (-416, 256, 0) a half-unit step moves segs 424/435/533
    from x1=133 to x1=134 in the ORACLE -- column 133 changes hands, which is exactly the column
    whose pixels diverge in the frame. Ask fj the same question about the same segs."""
    e1 = bake_bsp(WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad")), "E1M1")
    segs = [424, 435, 533, 1427, 1543, 1551, 448, 460]
    pts = [("integer", (-416 * U), 256 * U), ("+1/2 unit", (-416 * U) + 0x8000, 256 * U)]
    body, data, want, meta = [], [], b"", []
    k = 0
    for tag, vx16, vy16 in pts:
        sx = vx16 - (1 << 32) if vx16 & (1 << 31) else vx16
        sy = vy16 - (1 << 32) if vy16 & (1 << 31) else vy16
        for si in segs:
            seg = e1.segs[si]
            v1x, v1y = e1.vertexes[seg.v1]
            v2x, v2y = e1.vertexes[seg.v2]
            fa, fb, fc = seg_affine_coeffs(seg, e1.vertexes)
            body += [f"proj.wall_x_range vis, x1, x2, rwa, sgnr, ex{k}, ey{k}, "
                     f"exa{k}, exs{k}, eya{k}, eys{k}, ea{k}, "
                     f"p{k}, q{k}, r{k}, s{k}, ga{k}, gb{k}, gc{k}",
                     "hex.print_as_digit 1, vis, 0", "stl.output 10",
                     "hex.print_as_digit 8, x1, 0", "stl.output 10",
                     "hex.print_as_digit 8, x2, 0", "stl.output 10",
                     "hex.print_as_digit 8, rwa, 0", "stl.output 10"]
            data += [f"ex{k}: hex.vec 8, {vx16 & M32}", f"ey{k}: hex.vec 8, {vy16 & M32}",
                     f"exa{k}: hex.vec 8, {abs(sx) & M32}", f"exs{k}: hex.vec 1, {1 if sx < 0 else 0}",
                     f"eya{k}: hex.vec 8, {abs(sy) & M32}", f"eys{k}: hex.vec 1, {1 if sy < 0 else 0}",
                     f"ea{k}: hex.vec 8, 0",
                     f"p{k}: hex.vec 8, {(v1x << 16) & M32}", f"q{k}: hex.vec 8, {(v1y << 16) & M32}",
                     f"r{k}: hex.vec 8, {(v2x << 16) & M32}", f"s{k}: hex.vec 8, {(v2y << 16) & M32}",
                     f"ga{k}: hex.vec 8, {fa}", f"gb{k}: hex.vec 8, {fb}", f"gc{k}: hex.vec 8, {fc}"]
            res = rm.wall_x_range(vx16, vy16, 0, seg, e1.vertexes)
            want += (b"0\n00000000\n00000000\n00000000\n" if res is None else
                     f"1\n{res[0] & M32:08x}\n{res[1] & M32:08x}\n{res[2]:08x}\n".encode())
            meta.append((tag, si, res))
            k += 1
    data += ["vis: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8", "sgnr: hex.vec 8",
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
             generate_slopediv_recip_lut_fj("slopediv_recip"),
             generate_slopediv_recip8_lut_fj("slopediv_recip8"),
             generate_viewangletox_lut_fj("viewangletox", Config().VIEW_W, Config().TRIG_N)]
    src = tmp / "e1seg.fj"
    src.write_text("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
                   + "\n".join(data) + "\n", encoding="utf-8")
    out = tmp / "e1seg.fjm"
    fj.assemble([FIXP.resolve(), PROJ.resolve(), src.resolve()], out, memory_width=W,
                print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    gl = io.get_output(allow_incomplete_output=True).decode().split("\n")
    wl = want.decode().split("\n")
    print("\nTHE REAL REPRO -- proj.wall_x_range on E1M1 segs at (-416, 256, 0):")
    bad = 0
    for k, (tag, si, res) in enumerate(meta):
        g, w = gl[4 * k:4 * k + 4], wl[4 * k:4 * k + 4]
        gx1 = int(g[1], 16) if g[0] == "1" else None
        ox1 = res[0] if res else None
        flag = "" if g == w else "   <<< MISMATCH"
        bad += g != w
        print(f"  {tag:10s} seg {si:5d}: fj x1={gx1} x2={int(g[2], 16) if g[0]=='1' else None}"
              f"   oracle x1={ox1} x2={res[1] if res else None}{flag}")
    return bad == 0


def run_head_to_kernel(tmp: Path):
    """END TO END through the emitter's OWN pass-1 head: read a state off the wire exactly as the
    shipped program does, run the same |view| / sign derivation, then ask wall_x_range for seg 424.

    The kernel answers x1=134 for the half-unit position when it is handed the values directly. The
    shipped renderer's frame does not move at all. So either the head loses the fraction on the way
    to the kernel, or it does not -- and this says which, in seconds."""
    from doomfj.wall_renderer import _state_wire_lines
    from doomfj.wireformat import encode_feed
    from doomfj.lut_generator import generate_emit_dispatch_table_fj

    e1 = bake_bsp(WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad")), "E1M1")
    seg = e1.segs[424]
    v1x, v1y = e1.vertexes[seg.v1]
    v2x, v2y = e1.vertexes[seg.v2]
    fa, fb, fc = seg_affine_coeffs(seg, e1.vertexes)
    ABSMUL = [                                   # verbatim from wall_renderer's pass1 (M13-absmul)
        ]
    prog = "\n".join([
        "stl.startup_and_init_all",
        *_state_wire_lines("bin"),               # THE EMITTER'S OWN WIRE
        *ABSMUL,
        # ... and everything else pass1 runs between the head and the walk, in the emitter's order:
        # the per-frame counters, the W1R rotation anchor, and the wedge descriptors. If any of them
        # disturbs viewx/viewy, the kernel downstream sees an integer position and the frame stops
        # responding to the fraction -- which is exactly the symptom.
        "hex.zero 2, n_drawn", "hex.zero 1, full",
        "hex.zero 10, wnt", "hex.mov 8, wnt, viewangle",
        "hex.zero 10, wnt2", "hex.mov 8, wnt2, viewangle",
        "hex.shl_bit 10, wnt", "hex.shl_bit 10, wnt", "hex.add 10, wnt, wnt2",
        "hex.shr_hex 10, 6, wnt", "hex.shr_bit 10, wnt",
        "hex.zero 4, wnoff", "hex.mov 4, wnoff, wnt",
        "proj.wedge_setup wqa, wna, wqb, wnb, wex, wey, weyx, wexy, viewangle, viewx, viewy",
        # BOTH range macros, side by side. `wall_x_range` is what tests/fj cover; the SHIPPED lines
        # leaf calls `wall_x_range_m`, which is the M13-mapmul variant -- and that one reads
        # `viewx + 4*dw`, the top 4 nibbles, i.e. the INTEGER MAP SLICE.
        "proj.wall_x_range vis, x1, x2, rwa, sgn_aff, viewx, viewy, "
        "viewangle, p, q, r, s, ga, gb, gc",
        "hex.print_as_digit 8, x1, 0", "stl.output 10",
        "proj.wall_x_range_m 0, 0, 0, vis, x1, x2, sgn_aff, viewx, viewy, "
        "viewangle, p, q, r, s, ga, gb, gc",
        "hex.print_as_digit 8, viewx, 0", "stl.output 10",
        "hex.print_as_digit 4, viewx + 4*dw, 0", "stl.output 10",   # the INTEGER map slice
        "hex.print_as_digit 1, vis, 0", "stl.output 10",
        "hex.print_as_digit 8, x1, 0", "stl.output 10",
        "hex.print_as_digit 8, x2, 0", "stl.output 10",
        "stl.loop", "bad:", "stl.loop",
        "wmagic: hex.vec 2", "pkeys: hex.vec 2",
        "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "vx: hex.vec 10", "vy: hex.vec 10",
        "n_drawn: hex.vec 2", "full: hex.vec 1",
        "wnt: hex.vec 10", "wnt2: hex.vec 10", "wnoff: hex.vec 4",
        "wqa: hex.vec 1", "wna: hex.vec 1", "wqb: hex.vec 1", "wnb: hex.vec 1",
        "wex: hex.vec 8", "wey: hex.vec 8", "weyx: hex.vec 8", "wexy: hex.vec 8",
        "vis: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8", "sgn_aff: hex.vec 8",
        f"p: hex.vec 8, {(v1x << 16) & M32}", f"q: hex.vec 8, {(v1y << 16) & M32}",
        f"r: hex.vec 8, {(v2x << 16) & M32}", f"s: hex.vec 8, {(v2y << 16) & M32}",
        f"ga: hex.vec 8, {fa}", f"gb: hex.vec 8, {fb}", f"gc: hex.vec 8, {fc}",
        generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2),
        generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
        generate_slopediv_recip_lut_fj("slopediv_recip"),
        generate_slopediv_recip8_lut_fj("slopediv_recip8"),
        generate_viewangletox_lut_fj("viewangletox", Config().VIEW_W, Config().TRIG_N),
        # the lines tier's DISPATCH forms of the same two tables -- wall_x_range_m reads these
        generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE),
                                   index_nibbles=3, result_nibbles=8),
        generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(),
                                   index_nibbles=3, result_nibbles=6),
    ]) + "\n"
    src = tmp / "head.fj"
    src.write_text(prog, encoding="utf-8")
    out = tmp / "head.fjm"
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), FIXP.resolve(), (ROOT / "src/fj/present.fj").resolve(),
                 PROJ.resolve(), (ROOT / "src/fj/stream_render.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    print("\nEMITTER HEAD -> wall_x_range, seg 424, via the real wire:")
    ok = True
    for tag, frac in (("integer", 0), ("+1/2 unit", 0x8000)):
        io = FixedIO(encode_feed((-416 * U) + frac, 256 * U, 0, 0))
        fj.run(out, io_device=io, print_time=False, print_termination=False)
        # skip the 13-byte state echo the wire emits before the prints
        o = io.get_output(allow_incomplete_output=True)[13:].decode("ascii").split("\n")
        res = rm.wall_x_range((-416 * U) + frac, 256 * U, 0, seg, e1.vertexes)
        # print order: [0] wall_x_range x1, [1] viewx, [2] viewx int slice, [3] vis, [4] x1_m, [5] x2_m
        plain_x1, m_x1 = int(o[0], 16), int(o[4], 16)
        ok &= plain_x1 == res[0] and m_x1 == res[0]
        print(f"  {tag:10s} viewx={o[1]}  oracle x1={res[0]:3d}"
              f"   wall_x_range x1={plain_x1:3d}   wall_x_range_m x1={m_x1:3d}"
              f"{'' if m_x1 == res[0] else '   <<< THE SHIPPED PATH IGNORES THE FRACTION'}")
    return ok


def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="m14frac_"))
    ok = report("proj.wall_setup", *run_wall_setup(tmp), per=2)
    ok &= report("proj.wall_x_range", *run_wall_x_range(tmp), per=4)
    ok &= run_e1m1_segs(tmp)
    ok &= run_head_to_kernel(tmp)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
