"""THE ROW RULE, applied to proj.wall_x_range_m's two affine multiplies.

`hex.fixed_mul_lo` runs one schoolbook row per NONZERO NIBBLE OF THE SECOND OPERAND, and it is
commutative with the same low product -- so operand order is a pure cost choice, bit-identical
either way (the M13-mulorder lever; proj.project_thing already exploits it and says so in place).

wall_x_range_m currently multiplies `a * viewxa` and `b * viewya`, i.e. the VIEW POSITION is the
second operand and therefore the one paying rows. This counts, over every seg the walk can reach
and over the sweep's own view positions, which side is sparser -- and it separates INTEGER view
positions (what every sweep feeds) from FRACTIONAL ones (what the player actually occupies), because
a lever that only wins on integers is a benchmark artefact (docs/handoff-perf.md §5e).

    python scratchpad/m14_mulorder.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.mapcompiler import bake_bsp, seg_affine_coeffs                # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from nb_validate import _near_any_line, true_sector                       # noqa: E402


N, F = 8, 4                      # every call site below is `fixed_mul_lo 8, 4`
M = N + F                        # the internal width the rows run over


def nz(v, n=8):
    """Nonzero nibbles of the low `n` nibbles -- the naive row COUNT."""
    v &= (1 << (4 * n)) - 1
    return sum(1 for k in range(n) if (v >> (4 * k)) & 0xF)


def rowcost(v, signed=True):
    """The REAL cost of putting `v` second, from fixed_point.fj:

        rep(n+f, j) .fixed_mul_lo.row n+f, j, res, wide_a, wide_b
        row: if wb[j] == 0 -> skip;  else  add_mul (m-j), res+j, wa, wb+j

    So a nonzero nibble at position j costs an `add_mul` of width (m - j): the LOW nibbles are the
    dear ones, and a count alone is the wrong statistic. Both operands are sign-extended from n to
    n+f first, so a NEGATIVE second operand also pays four 0xF nibbles at the top.
    """
    v &= (1 << (4 * N)) - 1
    if signed and (v >> (4 * N - 1)) & 0x8:          # sign-extend n -> n+f, as the macro does
        v |= ((1 << (4 * F)) - 1) << (4 * N)
    return sum(M - j for j in range(M) if (v >> (4 * j)) & 0xF)


mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
cmap = bake_bsp(mw, "E1M1")
verts = cmap.vertexes

A, B = [], []
for seg in cmap.segs:
    a, b, _c = seg_affine_coeffs(seg, verts)
    A.append(rowcost(a))
    B.append(rowcost(b))
print(f"{len(cmap.segs)} segs")
print(f"  ROW COST of a: mean {sum(A)/len(A):.1f}   of b: mean {sum(B)/len(B):.1f}   (max 78)")

# the sweep's view positions, as the wire builds them: viewx = vx << 16  ->  low 4 nibbles ZERO
lds, sds = mw.linedefs("E1M1"), mw.sidedefs("E1M1")
vs = [(v.x, v.y) for v in mw.vertexes("E1M1")]
xs, ys = [p[0] for p in vs], [p[1] for p in vs]
pts = []
for x in range(min(xs) + 13, max(xs), 256):
    for y in range(min(ys) + 7, max(ys), 256):
        if _near_any_line(vs, lds, x, y, 24.0) or true_sector(vs, lds, sds, x, y) == -1:
            continue
        pts.append((x, y))
# viewxa/viewya are ABSOLUTE values (unsigned), so they never pay the sign-extension nibbles
ints = ([rowcost(abs(x) << 16, signed=False) for x, _y in pts]
        + [rowcost(abs(y) << 16, signed=False) for _x, y in pts])
fracs = ([rowcost((abs(x) << 16) | 0x8000, signed=False) for x, _y in pts]
         + [rowcost((abs(y) << 16) | 0x8000, signed=False) for _x, y in pts])
print(f"{len(pts)} sweep points")
print(f"  ROW COST of |viewx|/|viewy| INTEGER   : mean {sum(ints)/len(ints):.1f}")
print(f"  ROW COST of |viewx|/|viewy| FRACTIONAL: mean {sum(fracs)/len(fracs):.1f}")

ab = (sum(A) + sum(B)) / (len(A) + len(B))
ci, cf = sum(ints) / len(ints), sum(fracs) / len(fracs)
print("\n=== proj.wall_x_range_m / wall_setup / seg_pass1_leaf_body_ts: a*viewxa ===")
print(f"  today   (view position second): {ci:.1f} on integers, {cf:.1f} fractional")
print(f"  swapped (coefficient second)  : {ab:.1f}, ALWAYS")
print(f"  -> integers {'WIN' if ab < ci else 'LOSE'} by {ci - ab:+.1f}, "
      f"fractional {'WIN' if ab < cf else 'LOSE'} by {cf - ab:+.1f}")

# proj.wall_screen_span: world_h = ceilfix - viewz. BOTH are integer<<16 (the emitter bakes
# ceilfix/floorfix as ceil_h<<16 and viewz as (floor+VIEWHEIGHT)<<16), so the difference has its
# low FOUR nibbles zero -- and those are the dearest rows. `scale` is a dense 16.16.
secs = mw.sectors("E1M1")
hs = sorted({s.ceil_h for s in secs} | {s.floor_h for s in secs})
wh = [rowcost((h << 16) & 0xFFFFFFFF) for h in hs]
print("\n=== proj.wall_screen_span / project_thing's gzt, sp_hh: world_h * scale ===")
print(f"  world_h (integer<<16, {len(hs)} distinct heights): mean row cost {sum(wh)/len(wh):.1f}")
print("  scale   (a dense 16.16, nibbles 0..7 generally all nonzero): row cost ~68")
print(f"  -> swapping puts world_h second: saves ~{68 - sum(wh)/len(wh):.0f} of 68 = "
      f"{100*(68 - sum(wh)/len(wh))/68:.0f}% of the multiply, on EVERY frame")
