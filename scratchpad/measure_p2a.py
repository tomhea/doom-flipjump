"""Micro-costs of the pass-1 per-seg primitives via the delta technique: assemble a tiny program
with K vs 2K instances of a snippet; per-call = (ops_2K - ops_K) / K. Small builds (no map), fast.
Usage: python scratchpad/measure_p2a.py [variant.fj]   (optional edited projection.fj to compare)"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, ".")

import flipjump as fj
from doomfj.harness import W
from doomfj.lut_generator import generate_tantoangle_lut_fj, generate_slopediv_recip_lut_fj

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")

# a spread of (x2,y2) 16.16 vertices around the fixed view point, one per call (all octants)
VIEW = (-416 << 16) & 0xFFFFFFFF, (256 << 16) & 0xFFFFFFFF
VERTS = [((-416 + dx) << 16) & 0xFFFFFFFF for dx in (100, -173, 55, -31, 220, -97, 12, -256)], \
        [((256 + dy) << 16) & 0xFFFFFFFF for dy in (37, 130, -211, -64, 5, -140, 254, -18)]

SNIPPETS = {
    "p2a": "proj.point_to_angle ang, viewx, viewy, vgx, vgy, 0",
    "slope_div": "proj.slope_div sidx3, num8, den8, 0",
    "read_table8_3": "hex.read_table 8, r8, tantoangle, 3, sidx3",
    "affine_cull": ("hex.fixed_mul 8, 4, sg, ca, viewx\n"
                    "        hex.fixed_mul 8, 4, sgt, cb, viewy\n"
                    "        hex.add 8, sg, sgt\n"
                    "        hex.add 8, sg, cc"),
}


def _prog(name: str, k: int) -> str:
    body = []
    xs, ys = VERTS
    for i in range(k):
        body.append(f"hex.set 8, vgx, {xs[i % 8]}")
        body.append(f"hex.set 8, vgy, {ys[i % 8]}")
        body.append(f"hex.set 8, num8, {0x1234 + i * 977}")
        body.append(f"hex.set 8, den8, {0x8000 + i * 3251}")
        body.append("        " + SNIPPETS[name])
    data = [
        f"viewx: hex.vec 8, {VIEW[0]}", f"viewy: hex.vec 8, {VIEW[1]}",
        "vgx: hex.vec 8", "vgy: hex.vec 8", "ang: hex.vec 8",
        "num8: hex.vec 8", "den8: hex.vec 8", "sidx3: hex.vec 3", "r8: hex.vec 8",
        "sg: hex.vec 8", "sgt: hex.vec 8",
        "ca: hex.vec 8, 0x00012345", "cb: hex.vec 8, 0xFFFE7890", "cc: hex.vec 8, 0x00100000",
        generate_tantoangle_lut_fj("tantoangle"),
        generate_slopediv_recip_lut_fj("slopediv_recip"),
    ]
    return ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n")


def run(name: str, proj_fj: Path, k: int) -> int:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "p.fj").write_text(_prog(name, k), encoding="utf-8")
    out = tmp / "p.fjm"
    fj.assemble([FIXED_POINT_FJ.resolve(), proj_fj.resolve(), (tmp / "p.fj").resolve()], out,
                memory_width=W, print_time=False, warning_as_errors=False)
    term = fj.run(out, print_time=False, print_termination=False)
    return term.op_counter


if __name__ == "__main__":
    proj = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("src/fj/projection.fj")
    for name in SNIPPETS:
        a, b = run(name, proj, 8), run(name, proj, 16)
        print(f"{name:16s} per-call ~= {(b - a) / 8:,.0f} ops", flush=True)
