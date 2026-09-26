"""Step 1: TODAY's emission on one oracle frame -- the plain column path vs the sprite path, both
through the REAL stream.emit_col_lines. Validates that the sprite path equals the plain column
with the fragment pasted over it, and prices both by the slope over passes."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402

frames = plib.by_frame(plib.load_cases())
key = tuple(sys.argv[1].split(":")) if len(sys.argv) > 1 else next(iter(frames))
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 12
cases = frames[key][:limit]
fr = plib.Frame(cases)
print("frame %s: %d cases, %d pids, %d step classes" % (key, len(cases), len(fr.pids), len(fr.classes)))

plain = {i: {"c_sprfl": 0} for i in range(len(cases))}
variants = [("BASE", [], None), ("PLAIN", [plib.TODAY_EMIT], plain), ("TODAY", [plib.TODAY_EMIT], None)]
res = {}
for name, leaf, extra in variants:
    ops = []
    for p in (1, 2):
        t0 = time.time()
        o, out = plib.assemble_run(plib.program(fr, leaf, p, per_case_extra=extra), "%s_p%d" % (name, p))
        ops.append(o)
        if p == 1:
            res[name + "_out"] = out
        print("  %-6s passes=%d ops %12d  (%.1fs)" % (name, p, o, time.time() - t0), flush=True)
    res[name] = ops[1] - ops[0]

n = len(cases)
print("per pass: BASE %d | PLAIN %d | TODAY %d" % (res["BASE"], res["PLAIN"], res["TODAY"]))
print("per column: PLAIN %.0f  TODAY %.0f  (sprite column minus plain column: %.0f)" %
      ((res["PLAIN"] - res["BASE"]) / n, (res["TODAY"] - res["BASE"]) / n,
       (res["TODAY"] - res["PLAIN"]) / n))

# validate: TODAY column == PLAIN column with the fragment rows pasted
pc = plib.decode(res["PLAIN_out"])
tc = plib.decode(res["TODAY_out"])
assert len(pc) == len(tc) == n, (len(pc), len(tc), n)
bad = 0
for i in range(n):
    (xp, pp), (xt, pt) = pc[i], tc[i]
    want = dict(pp)
    want.update(fr.expected_sprite_rows(i))
    if xp != xt or pt != want:
        bad += 1
        if bad <= 3:
            diff = [y for y in range(plib.H) if pt.get(y) != want.get(y)]
            print("  !! case %d x=%d differs at rows %s" % (i, xt, diff[:12]))
print("validation: %d/%d sprite columns == plain column + pasted fragment" % (n - bad, n))
