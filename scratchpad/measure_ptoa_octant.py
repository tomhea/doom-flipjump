"""Measure point_to_angle's OCTANT part (slope_div stubbed, scratchpad/projection_noslopediv.fj) on
the real 488 inputs -- the cost a coarse octant-space frustum pre-cull would pay per vertex. Compare
to the full 30,522/call: full - octant = slope_div (the division), the crushable/avoidable part."""
import json, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import flipjump as fj
from doomfj.harness import W
from doomfj.lut_generator import generate_slopediv_recip_lut_fj, generate_tantoangle_lut_fj
from doomfj.reference_model import SLOPERANGE
PROJ = ROOT / "scratchpad/projection_noslopediv.fj"
FIXED = ROOT / "src/fj/fixed_point.fj"
D = json.load(open(ROOT / "scratchpad/real_ptoa_pts.json"))
def measure(k):
    pts = D["pts"][:k]
    body, data = [], [f"viewx: hex.vec 8, {D['viewx']}", f"viewy: hex.vec 8, {D['viewy']}", "dst: hex.vec 8"]
    for i,(x,y) in enumerate(pts):
        body.append(f"proj.point_to_angle dst, viewx, viewy, vx{i}, vy{i}, 0")
        data += [f"vx{i}: hex.vec 8, {x}", f"vy{i}: hex.vec 8, {y}"]
    data += [generate_slopediv_recip_lut_fj("slopediv_recip"), generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    prog = "stl.startup_and_init_all\n"+"\n".join(body)+"\nstl.loop\n"+"\n".join(data)+"\n"
    tmp = Path(tempfile.mkdtemp()); p = tmp/"m.fj"; p.write_text(prog, encoding="utf-8")
    fj.assemble([FIXED.resolve(), PROJ.resolve(), p.resolve()], tmp/"m.fjm", memory_width=W, print_time=False)
    return fj.run(tmp/"m.fjm", print_time=False, print_termination=False).op_counter
K=20; t0=time.perf_counter()
o1=measure(K); o2=measure(2*K); per=(o2-o1)/K
print(f"octant-only (slope_div stubbed) per-call = {per:,.0f} ops")
print(f"full point_to_angle was 30,522 => slope_div (the division) = {30522-per:,.0f} ops/call")
print(f"({round(time.perf_counter()-t0,1)}s)")
