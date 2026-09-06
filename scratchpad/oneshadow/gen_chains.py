"""Generate the chain-macro family (add/sub x widths 2,4,10 -- 8 already exists), splice them
into frame_render.fj, comment-safely swap every direct hex.add/sub N call in the live files,
and extend chain_smoke.fj with per-width ripple vectors."""
from pathlib import Path

WIDTHS = [2, 4, 10]


def gen(op, n):
    jumper = f"hex.{op}.dst"
    rs = [f"r{i}" for i in range(n)]
    locals_ = ["rcc0"] + (["cc0_ok"] if op == "sub" else []) + rs + ["rcc1"] + (["done"] if op == "sub" else [])
    lines = []
    a = lines.append
    a(f"    //   dst[:{n}] {'+' if op == 'add' else '-'}= src[:{n}]   == hex.{op} {n}, dst, src, boundary-fused (see add8_chain).")
    a(f"    def {op}{n}_chain dst, src @ {', '.join(locals_)} \\")
    a(f"            < hex.tables.ret, hex.tables.res, {jumper} {{")
    a(f"        wflip hex.tables.ret+w, rcc0, {jumper}")
    a("      rcc0:")
    if op == "add":
        a("        hex.zero hex.tables.res")
    else:
        a("        hex.if0 hex.tables.res, cc0_ok")
        a("        hex.sub.not_carry")
        a("        hex.xor_by hex.tables.res, 0xf")
        a("      cc0_ok:")
    a(f"        hex.xor {jumper},   dst")
    a(f"        hex.xor {jumper}+4, src")
    a(f"        wflip hex.tables.ret+w, rcc0^r0, {jumper}")
    for i in range(n - 1):
        a(f"      r{i}:")
        a(f"        .dance_boundary dst+{i}*dw, dst+{i+1}*dw, src+{i+1}*dw, {jumper}, r{i}, r{i+1}")
    a(f"      r{n-1}:")
    a(f"        hex.xor_zero dst+{n-1}*dw, hex.tables.res")
    a(f"        wflip hex.tables.ret+w, r{n-1}^rcc1, {jumper}")
    a("      rcc1:")
    a("        wflip hex.tables.ret+w, rcc1")
    if op == "add":
        a("        hex.zero hex.tables.res")
    else:
        a("        hex.if0 hex.tables.res, done")
        a("        hex.sub.not_carry")
        a("        hex.xor_by hex.tables.res, 0xf")
        a("      done:")
    a("    }")
    return chr(10).join(lines)


blocks = []
for n in WIDTHS:
    blocks.append(gen("add", n))
    blocks.append(gen("sub", n))
family = (chr(10) * 2).join(blocks)

f = Path("src/fj/frame_render.fj")
t = f.read_text(encoding="utf-8")
anchor = "    def lines_dda_step < p2_prodc, p2_prodf, p2_stepc, p2_stepf {"
assert t.count(anchor) == 1
t = t.replace(anchor, family + chr(10) * 2 + anchor)
f.write_text(t, encoding="utf-8")
print(f"6 chain macros (widths {WIDTHS}) spliced into frame_render.fj")

# ---- the comment-safe mass swap ----
SWAPS = {f"hex.{op} {n}, ": f"frame.{op}{n}_chain " for op in ("add", "sub") for n in (2, 4, 8, 10)}
total = {}
for path in ["src/fj/frame_render.fj", "src/fj/projection.fj", "src/fj/stream_render.fj"]:
    p = Path(path)
    out = []
    count = 0
    for line in p.read_text(encoding="utf-8").splitlines(keepends=True):
        idx = line.find("//")
        code, comment = (line[:idx], line[idx:]) if idx >= 0 else (line, "")
        for old, new in SWAPS.items():
            if old in code:
                count += code.count(old)
                code = code.replace(old, new)
        out.append(code + comment)
    p.write_text("".join(out), encoding="utf-8")
    total[path] = count
    print(f"{path}: {count} calls swapped")
print("TOTAL:", sum(total.values()))
